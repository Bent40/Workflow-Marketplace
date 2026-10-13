#!/usr/bin/env python3
"""wf-learn.py — a persistent, append-only, confidence-scored, staleness-aware
store of durable PROJECT-OPERATIONAL learnings (inspired by gstack's /learn +
learnings.jsonl). It captures the kind of fact that saves real time next session
— "the suite needs FOO=bar", "module X's API expects Y", "the build breaks unless
Z runs first" — so a fresh session does not re-discover or re-stub the same quirk.

LOAD-BEARING SCOPE LINE (do not blur it — see core/DECISIONS.md D4 and CLAUDE.md):
  - This store is for PERSISTENT, project-operational learnings: durable facts
    ABOUT THE PROJECT/codebase (quirks, command fixes, architecture insights).
  - It is NOT for the EPHEMERAL toolset / skill-gap reflections ("should this
    skill exist / how do I improve my own tooling"). Those stay in-conversation,
    feed skill-governance, and are discarded — they are NEVER written here.

STORAGE (committed, not local): gstack keeps learnings local in ~/.gstack; we
instead commit them, because this repo's container is EPHEMERAL ("anything worth
keeping needs to be committed and pushed") AND the learnings have shared value.
The real file therefore lives at a TRACKED path, _workflow/learnings.jsonl (NOT
the gitignored .wf/). The path is overridable for tests via --file or the
WF_LEARN_FILE env var, so --selftest writes to a tempdir and never touches the
real log.

Entry schema (one JSON object per line):
  ts          ISO8601 timestamp (real wall-clock time at write == learned_at)
  skill       originating skill/agent/context (optional; "" if unset)
  type        pattern | pitfall | preference | architecture | tool | operational
  key         short slug
  insight     the durable fact (text)
  confidence  base confidence, integer 1..10
  source      observed | user-stated | inferred
  files       list of repo-relative paths (optional; drives staleness)
  valid_from  ISO8601 — when the fact became true (defaults to ts at write)
  valid_to    ISO8601 — when the fact STOPPED being true (absent/null while LIVE)
  closed_reason  why it was closed (set with valid_to: superseded / retracted)

SUPERSESSION (write-adjudication, deterministic — no LLM): `add` does NOT blind-
append. It compares the new learning against the LIVE entries sharing its (key,
type) and decides:
  - NOOP   — an identical live learning already exists; nothing is written.
  - UPDATE — a live entry with the same (key, type) but a DIFFERENT insight is
             SUPERSEDED: its valid_to is stamped (never deleted — history is
             preserved and auditable) and the new learning is appended LIVE.
  - ADD    — no live (key, type) match; a plain append.
`retract` (DELETE) closes a live learning by stamping valid_to without adding a
new fact. Recall (list/search/export) shows LIVE entries by default; pass --all
to include superseded/retracted history. Bi-temporal validity means a contradictory
old fact ("FOO=bar" then "FOO=baz") never lingers live, yet "as-of" history stays.
Back-compatible: an entry with no valid_to is LIVE.

Effective confidence (computed at READ time, never mutates the stored base):
  - source in {observed, inferred}  -> decays with age (facts the agent deduced
    or watched happen go stale).
  - source == user-stated, OR type == preference  -> does NOT decay (a stated
    fact / a preference is durable until explicitly changed).
  Decay: lose 1 point per DECAY_DAYS days of age, floored at MIN_EFFECTIVE.
  (Linear, integer, deliberately simple — see _effective_confidence.)

Staleness: an entry whose `files` lists a path that no longer exists (resolved
relative to the repo root) is flagged STALE in list/prune.

Subcommands:
  add     append one validated entry (fail-closed exit 2 on bad input).
  list    show entries with EFFECTIVE confidence (filters: --type, --min-confidence).
  search  case-insensitive match over key + insight + files.
  prune   report (and with --apply remove) STALE entries and entries whose
          EFFECTIVE confidence has decayed below PRUNE_FLOOR.
  export  emit Markdown grouped by type (for docs / handoff).
  check   validate every line is well-formed JSON with required fields;
          fail-closed (exit non-zero) on any malformed line — never silently skip.

Exit codes: add -> 0 ok / 2 bad input.  check -> 0 ok / 1 malformed.
            prune -> 0.  list/search/export -> 0.  selftest -> 0 pass / 1 fail.
            usage error -> 2.

Usage:
    wf learn add --type T --key K --insight "..." [--confidence N] [--source S]
                 [--skill name] [--files a,b] [--file PATH]
    wf learn list [--type T] [--min-confidence N] [--file PATH]
    wf learn search <query> [--rank] [--semantic] [--all] [--file PATH]
    wf learn prune [--apply] [--file PATH]
    wf learn export [--md] [--file PATH]
    wf learn check [--file PATH]
    wf learn --selftest
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = REPO_ROOT / "_workflow" / "learnings.jsonl"
_STALE_ROOT = REPO_ROOT  # rebound by _learn_file() to the active store's root

TYPES = ("pattern", "pitfall", "preference", "architecture", "tool", "operational")
SOURCES = ("observed", "user-stated", "inferred")
REQUIRED_FIELDS = ("ts", "type", "key", "insight", "confidence", "source")

# --- decay / prune tuning (deliberately simple, all in one place) -------------
DECAY_DAYS = 30      # one confidence point is lost per this many days of age
MIN_EFFECTIVE = 1    # effective confidence never decays below this
PRUNE_FLOOR = 2      # prune removes entries whose effective confidence is < this
NON_DECAYING_SOURCES = ("user-stated",)   # stated facts don't go stale
NON_DECAYING_TYPES = ("preference",)      # preferences don't go stale


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf learn: {msg}\n")
    raise SystemExit(code)


def _learn_file(arg_file: str | None) -> Path:
    """Resolve the learnings file: --file > $WF_LEARN_FILE > the PROJECT'S
    store > the toolset repo's own tracked store.

    Learnings are PROJECT-SPECIFIC (boot design D1, resolved 2026-07-08):
    when the caller stands outside this repo, the store is
    <project>/_workflow/learnings.jsonl — the project root found by walking
    up from the caller dir ($WF_CALLER_CWD, exported by the `wf` dispatcher,
    else cwd) to the nearest dir holding `_workflow/` or `.git`. Only when
    the caller is inside the toolset repo itself does the repo's own store
    apply (this repo is an ordinary consumer of its own tool)."""
    if arg_file:
        resolved = Path(arg_file)
    elif os.environ.get("WF_LEARN_FILE"):
        resolved = Path(os.environ["WF_LEARN_FILE"])
    else:
        caller = Path(os.environ.get("WF_CALLER_CWD") or Path.cwd()).resolve()
        if caller == REPO_ROOT or REPO_ROOT in caller.parents:
            resolved = DEFAULT_FILE
        else:
            root = caller
            for cand in (caller, *caller.parents):
                if (cand / "_workflow").is_dir() or (cand / ".git").exists():
                    root = cand
                    break
            resolved = root / "_workflow" / "learnings.jsonl"
    _set_stale_root(resolved)
    return resolved


def _set_stale_root(learn_file: Path) -> None:
    """Staleness (`files:` entries) resolves against the ACTIVE store's
    project root, not unconditionally against the toolset repo."""
    global _STALE_ROOT
    p = learn_file.resolve()
    _STALE_ROOT = p.parent.parent if p.parent.name == "_workflow" else REPO_ROOT


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO8601 ts to an aware UTC datetime (tolerates a trailing Z)."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _effective_confidence(entry: dict, *, as_of: datetime) -> int:
    """Confidence after age decay, computed at read time (never stored).

    user-stated entries and preference-type entries do not decay. Everything
    else loses 1 point per DECAY_DAYS of age, floored at MIN_EFFECTIVE. Linear
    and integer on purpose: easy to reason about and to assert on in tests."""
    base = int(entry.get("confidence", 0))
    if entry.get("source") in NON_DECAYING_SOURCES or entry.get("type") in NON_DECAYING_TYPES:
        return base
    try:
        age_days = (as_of - _parse_ts(entry["ts"])).total_seconds() / 86400.0
    except (KeyError, ValueError):
        return base  # unparseable ts → treat as undecayed (check/prune surface it)
    if age_days <= 0:
        return base
    decayed = base - int(age_days // DECAY_DAYS)
    return max(MIN_EFFECTIVE, decayed)


def _is_stale(entry: dict) -> list[str]:
    """Return the listed `files` that no longer exist (resolved at repo root).

    A non-empty result means the entry is STALE — its referenced file moved or
    was deleted, so the learning may no longer apply."""
    missing: list[str] = []
    for f in entry.get("files") or []:
        if not isinstance(f, str) or not f.strip():
            continue
        p = Path(f)
        if not p.is_absolute():
            p = _STALE_ROOT / f
        if not p.exists():
            missing.append(f)
    return missing


def _validate_entry(entry: dict) -> list[str]:
    """Structural validation used by `check`; returns a list of problems."""
    problems: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in entry:
            problems.append(f"missing required field '{field}'")
    if "type" in entry and entry["type"] not in TYPES:
        problems.append(f"invalid type {entry['type']!r} (want one of {'|'.join(TYPES)})")
    if "source" in entry and entry["source"] not in SOURCES:
        problems.append(f"invalid source {entry['source']!r} (want one of {'|'.join(SOURCES)})")
    if "confidence" in entry:
        c = entry["confidence"]
        if not isinstance(c, int) or isinstance(c, bool) or not (1 <= c <= 10):
            problems.append(f"confidence {c!r} must be an int in 1..10")
    if "ts" in entry:
        try:
            _parse_ts(entry["ts"])
        except (ValueError, TypeError, AttributeError):
            problems.append(f"unparseable ts {entry.get('ts')!r}")
    # Bi-temporal fields are optional, but if present and non-empty must parse.
    for tf in ("valid_from", "valid_to"):
        if entry.get(tf):
            try:
                _parse_ts(entry[tf])
            except (ValueError, TypeError, AttributeError):
                problems.append(f"unparseable {tf} {entry.get(tf)!r}")
    if "files" in entry and not isinstance(entry["files"], list):
        problems.append("files must be a list")
    return problems


def load_entries(path: Path, *, strict: bool = False) -> list[dict]:
    """Read all entries. In strict mode (check), ANY malformed line raises and
    fails closed — we never silently skip. In non-strict mode (list/search/...)
    a malformed line is skipped with a stderr warning so a single bad line does
    not take down a read-only view."""
    if not path.is_file():
        return []
    entries: list[dict] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                raise ValueError("line is not a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            if strict:
                _die(f"{path}:{lineno}: malformed line: {e}", code=1)
            sys.stderr.write(f"wf learn: skipping malformed {path}:{lineno}: {e}\n")
            continue
        if strict:
            probs = _validate_entry(obj)
            if probs:
                _die(f"{path}:{lineno}: " + "; ".join(probs), code=1)
        entries.append(obj)
    return entries


def append_entry(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _rewrite(path: Path, entries: list[dict]) -> None:
    """Overwrite the whole file (used by supersession/retract/prune)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")


def _is_live(entry: dict) -> bool:
    """LIVE = not yet superseded/retracted. Absent/empty valid_to == live (so
    every pre-supersession entry stays live without migration)."""
    v = entry.get("valid_to")
    return v is None or v == ""


def _norm_insight(s: str) -> str:
    """Normalize an insight for duplicate detection: lowercased, whitespace
    collapsed. Deliberately simple (the NOOP test is exact-after-normalization)."""
    return " ".join(str(s).lower().split())


_WORD_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(s: str) -> list[str]:
    return _WORD_RE.findall(str(s).lower())


def bm25_rank(query: str, docs: list[tuple], *, k1: float = 1.5,
              b: float = 0.75) -> list[tuple]:
    """Rank (id, text) docs against `query` by Okapi BM25 — pure-Python, NO deps,
    offline-safe (no embedding API). Returns [(id, score)] with score>0,
    highest first. A LEXICAL TF-IDF ranker: better ordering + term weighting than
    raw substring, especially for multi-term queries. True SEMANTIC recall (a query
    phrased differently than the stored fact) is the OPT-IN tier below
    (`embed_rank`, all-MiniLM-L6-v2) — substring stays the zero-dep default, BM25
    the no-dep ranked upgrade, embeddings the optional semantic upgrade."""
    q_terms = _tokenize(query)
    toks = [(i, _tokenize(t)) for i, t in docs]
    n = len(toks)
    if n == 0 or not q_terms:
        return []
    avgdl = (sum(len(t) for _, t in toks) / n) or 1.0
    df: dict[str, int] = {}
    for _, t in toks:
        for term in set(t):
            df[term] = df.get(term, 0) + 1
    out: list[tuple] = []
    for i, t in toks:
        if not t:
            continue
        tf: dict[str, int] = {}
        for term in t:
            tf[term] = tf.get(term, 0) + 1
        dl = len(t)
        score = 0.0
        for qt in q_terms:
            f = tf.get(qt, 0)
            if not f:
                continue
            inv_df = math.log(1 + (n - df[qt] + 0.5) / (df[qt] + 0.5))
            score += inv_df * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        if score > 0:
            out.append((i, score))
    out.sort(key=lambda x: -x[1])
    return out


# --- OPTIONAL local semantic backend (#23 deferred dep) -----------------------
# An OPT-IN tier above BM25: cosine similarity over local embeddings catches
# recall where the query is phrased differently than the stored fact (BM25 needs
# shared terms). The model (all-MiniLM-L6-v2, ~80-90MB) and its runtime
# (sentence-transformers) are DELIBERATELY NOT in any default install —
# substring is the zero-dep default, BM25 the no-dep ranked upgrade, this the
# opt-in semantic upgrade. The backend NEVER auto-installs; when it is absent the
# caller falls back to BM25 (a clear, fail-SOFT note — never a silent skip and
# never a fake result).
EMBED_MODEL = "all-MiniLM-L6-v2"
_EMBEDDER_CACHE: dict = {}


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors (0.0 if either is zero)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _load_embedder():
    """Return a callable list[str]->list[list[float]] backed by a local MiniLM
    model, or None when the optional dependency/model isn't installed. Cached.
    Pure fail-SOFT: ANY import/load error returns None so the caller falls back to
    BM25 — it never raises, never auto-installs, never reaches the network on its
    own beyond what sentence-transformers does to fetch the model on first use."""
    if "fn" in _EMBEDDER_CACHE:
        return _EMBEDDER_CACHE["fn"]
    fn = None
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        model = SentenceTransformer(EMBED_MODEL)

        def fn(texts):  # type: ignore[misc]
            return [list(map(float, v)) for v in model.encode(list(texts))]
    except Exception:
        fn = None
    _EMBEDDER_CACHE["fn"] = fn
    return fn


def embed_rank(query: str, docs: list[tuple], *, embedder=None):
    """Semantically rank (id, text) docs against `query` by cosine similarity of
    local embeddings. Returns [(id, score)] highest-first, or **None** when no
    embedder is available — that None is the explicit signal for the caller to
    fall back to BM25. `embedder` is an injectable seam (a callable
    list[str]->list[vec]) so the ranking is testable WITHOUT the heavy optional
    dependency."""
    fn = embedder or _load_embedder()
    if fn is None:
        return None
    if not docs or not str(query).strip():
        return []
    ids = [i for i, _ in docs]
    texts = [t for _, t in docs]
    vecs = fn([query] + texts)
    qv, dvs = vecs[0], vecs[1:]
    out = [(ids[i], _cosine(qv, dv)) for i, dv in enumerate(dvs)]
    out.sort(key=lambda x: -x[1])
    return out


# --- commands -----------------------------------------------------------------

def cmd_add(path: Path, args, quiet: bool = False,
            now: datetime | None = None) -> int:
    if args.type not in TYPES:
        _die(f"--type must be one of {'|'.join(TYPES)} (got {args.type!r})")
    if args.source not in SOURCES:
        _die(f"--source must be one of {'|'.join(SOURCES)} (got {args.source!r})")
    if not isinstance(args.confidence, int) or not (1 <= args.confidence <= 10):
        _die(f"--confidence must be an int in 1..10 (got {args.confidence!r})")
    key = (args.key or "").strip()
    insight = (args.insight or "").strip()
    if not key:
        _die("--key must be a non-empty slug")
    if not insight:
        _die("--insight must be non-empty")
    files = [f.strip() for f in (args.files or "").split(",") if f.strip()]
    now_iso = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "ts": now_iso,
        "valid_from": now_iso,
        "skill": (args.skill or "").strip(),
        "type": args.type,
        "key": key,
        "insight": insight,
        "confidence": args.confidence,
        "source": args.source,
        "files": files,
    }

    # WRITE-ADJUDICATION (deterministic): compare against LIVE entries sharing the
    # same (key, type). Identical insight -> NOOP; different insight -> supersede
    # the old ones (stamp valid_to, never delete) then append the new LIVE entry.
    existing = load_entries(path)

    def _same_slot(e: dict) -> bool:
        return _is_live(e) and e.get("key") == key and e.get("type") == args.type

    live_same = [e for e in existing if _same_slot(e)]
    if any(_norm_insight(e.get("insight", "")) == _norm_insight(insight)
           for e in live_same):
        if not quiet:
            print(f"noop: [{args.type}] {key} — an identical live learning is "
                  f"already recorded; nothing written.")
        return 0
    if live_same:
        for e in existing:
            if _same_slot(e):
                e["valid_to"] = now_iso
                e["closed_reason"] = "superseded by a newer learning"
        _rewrite(path, existing)
        append_entry(path, entry)
        if not quiet:
            print(f"updated: [{entry['type']}] {entry['key']} superseded "
                  f"{len(live_same)} prior live learning(s) (kept as history) -> {path}")
        return 0

    append_entry(path, entry)
    if not quiet:
        print(f"learned: [{entry['type']}] {entry['key']} "
              f"(confidence {entry['confidence']}, source {entry['source']}) -> {path}")
    return 0


def cmd_retract(path: Path, key: str, type_: str | None, reason: str,
                now: datetime | None = None, quiet: bool = False) -> int:
    """DELETE in the ADD/UPDATE/DELETE/NOOP taxonomy: close the LIVE learning(s)
    for `key` (optionally narrowed by --type) by stamping valid_to — the fact is
    retired, not erased, so history stays auditable."""
    key = (key or "").strip()
    if not key:
        _die("--key must be a non-empty slug")
    now_iso = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = load_entries(path)
    closed = 0
    for e in entries:
        if _is_live(e) and e.get("key") == key and (type_ is None or e.get("type") == type_):
            e["valid_to"] = now_iso
            e["closed_reason"] = f"retracted: {reason}" if reason else "retracted"
            closed += 1
    if closed:
        _rewrite(path, entries)
    if not quiet:
        if closed:
            print(f"retracted: closed {closed} live learning(s) for key {key!r} "
                  f"(kept as history) -> {path}")
        else:
            print(f"retract: no live learning found for key {key!r}"
                  f"{f' of type {type_}' if type_ else ''} — nothing changed.")
    return 0


def _fmt_entry(entry: dict, eff: int, stale: list[str]) -> str:
    base = entry.get("confidence", "?")
    conf = f"{eff}/10" if eff == base else f"{eff}/10 (base {base})"
    tag = " [STALE: " + ",".join(stale) + "]" if stale else ""
    if not _is_live(entry):
        reason = entry.get("closed_reason") or "closed"
        tag += f" [CLOSED {entry.get('valid_to','?')}: {reason}]"
    files = entry.get("files") or []
    fpart = f"  files={','.join(files)}" if files else ""
    return (f"[{entry.get('type','?')}] {entry.get('key','?')}  conf={conf}  "
            f"src={entry.get('source','?')}{tag}\n"
            f"    {entry.get('insight','')}{fpart}")


def cmd_list(path: Path, args, as_of: datetime | None = None) -> int:
    as_of = as_of or datetime.now(timezone.utc)
    entries = load_entries(path)
    if args.type and args.type not in TYPES:
        _die(f"--type must be one of {'|'.join(TYPES)} (got {args.type!r})")
    include_closed = bool(getattr(args, "all", False))
    shown = 0
    for e in entries:
        if not include_closed and not _is_live(e):
            continue  # superseded/retracted history hidden unless --all
        if args.type and e.get("type") != args.type:
            continue
        eff = _effective_confidence(e, as_of=as_of)
        if args.min_confidence is not None and eff < args.min_confidence:
            continue
        print(_fmt_entry(e, eff, _is_stale(e)))
        shown += 1
    live = sum(1 for e in entries if _is_live(e))
    scope = "total" if include_closed else f"live; {len(entries)} total incl. history"
    print(f"— {shown} entr{'y' if shown == 1 else 'ies'} "
          f"(of {len(entries) if include_closed else live} {scope}) in {path}")
    return 0


def cmd_search(path: Path, query: str, as_of: datetime | None = None,
               include_closed: bool = False, rank: bool = False,
               semantic: bool = False, embedder=None) -> int:
    as_of = as_of or datetime.now(timezone.utc)
    entries = load_entries(path)
    pool = [e for e in entries if include_closed or _is_live(e)]

    if semantic:
        # OPT-IN semantic tier. Absent backend -> fail-SOFT to BM25 with a clear
        # note (never a silent skip, never a fabricated result).
        docs = [(idx, f"{e.get('key','')} {e.get('insight','')} "
                      f"{' '.join(e.get('files') or [])}")
                for idx, e in enumerate(pool)]
        ranked = embed_rank(query, docs, embedder=embedder)
        if ranked is None:
            sys.stderr.write(
                "wf learn: semantic backend unavailable (optional dep "
                "'sentence-transformers' + the all-MiniLM-L6-v2 model are not "
                "installed) — falling back to BM25. Enable with: "
                "pip install sentence-transformers (downloads ~80-90MB on first "
                "use; not installed by default).\n")
            rank = True  # fall through to the no-dep ranked tier
        else:
            for idx, _score in ranked:
                e = pool[idx]
                print(_fmt_entry(e, _effective_confidence(e, as_of=as_of), _is_stale(e)))
            print(f"— {len(ranked)} semantic match(es) for {query!r} in {path}"
                  f"{'' if include_closed else ' (live only; --all for history)'}")
            return 0

    if rank:
        # BM25 relevance ranking over key + insight + files (lexical, no deps).
        docs = [(idx, f"{e.get('key','')} {e.get('insight','')} "
                      f"{' '.join(e.get('files') or [])}")
                for idx, e in enumerate(pool)]
        ranked = bm25_rank(query, docs)
        for idx, _score in ranked:
            e = pool[idx]
            print(_fmt_entry(e, _effective_confidence(e, as_of=as_of), _is_stale(e)))
        print(f"— {len(ranked)} BM25-ranked match(es) for {query!r} in {path}"
              f"{'' if include_closed else ' (live only; --all for history)'}")
        return 0

    q = query.lower()
    hits = 0
    for e in pool:
        hay = " ".join([
            str(e.get("key", "")),
            str(e.get("insight", "")),
            " ".join(e.get("files") or []),
        ]).lower()
        if q in hay:
            print(_fmt_entry(e, _effective_confidence(e, as_of=as_of), _is_stale(e)))
            hits += 1
    print(f"— {hits} match(es) for {query!r} in {path}"
          f"{'' if include_closed else ' (live only; --all for history)'}")
    return 0


def cmd_prune(path: Path, apply: bool, as_of: datetime | None = None) -> int:
    as_of = as_of or datetime.now(timezone.utc)
    entries = load_entries(path)
    keep: list[dict] = []
    removed: list[tuple[dict, str]] = []
    for e in entries:
        stale = _is_stale(e)
        eff = _effective_confidence(e, as_of=as_of)
        if stale:
            removed.append((e, f"STALE (missing: {','.join(stale)})"))
        elif eff < PRUNE_FLOOR:
            removed.append((e, f"decayed below floor (eff {eff} < {PRUNE_FLOOR})"))
        else:
            keep.append(e)
    print(f"prune: {len(removed)} of {len(entries)} entr"
          f"{'y' if len(entries) == 1 else 'ies'} flagged for removal "
          f"(floor={PRUNE_FLOOR}):")
    for e, reason in removed:
        print(f"  - [{e.get('type','?')}] {e.get('key','?')}: {reason}")
    if apply:
        if removed:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as fh:
                for e in keep:
                    fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
            print(f"applied: rewrote {path} with {len(keep)} kept entr"
                  f"{'y' if len(keep) == 1 else 'ies'} ({len(removed)} removed).")
        else:
            print("applied: nothing to remove; file unchanged.")
    else:
        print("(report only — pass --apply to rewrite the file without these)")
    return 0


def cmd_export(path: Path, as_of: datetime | None = None,
               include_closed: bool = False) -> int:
    as_of = as_of or datetime.now(timezone.utc)
    entries = load_entries(path)
    if not include_closed:
        entries = [e for e in entries if _is_live(e)]
    print("# Project learnings\n")
    if not entries:
        print("_No learnings recorded yet._")
        return 0
    for t in TYPES:
        group = [e for e in entries if e.get("type") == t]
        if not group:
            continue
        print(f"## {t}\n")
        for e in group:
            eff = _effective_confidence(e, as_of=as_of)
            stale = _is_stale(e)
            tag = " _(STALE)_" if stale else ""
            files = e.get("files") or []
            fpart = f" — `{', '.join(files)}`" if files else ""
            print(f"- **{e.get('key','?')}** (conf {eff}/10, "
                  f"{e.get('source','?')}){tag}: {e.get('insight','')}{fpart}")
        print()
    return 0


def cmd_check(path: Path) -> int:
    # strict load fails closed (exit 1) on the first malformed/invalid line.
    entries = load_entries(path, strict=True)
    print(f"learn check: OK ({len(entries)} well-formed entr"
          f"{'y' if len(entries) == 1 else 'ies'}) in {path}")
    return 0


# --- selftest -----------------------------------------------------------------

def selftest() -> int:
    import tempfile

    problems: list[str] = []
    # A fixed "now" so decay is deterministic — never depends on wall-clock deltas.
    NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class A:  # tiny args shim
        def __init__(self, **kw):
            self.__dict__.update(kw)

    # Staleness resolves files relative to the REPO ROOT (production behavior), so
    # the "present" path must be a real repo file and the "stale" path must be one
    # that genuinely does not exist at the repo root.
    PRESENT = "scripts/wf-learn.py"          # exists at repo root
    MISSING = "does-not-exist-xyz-zzz.py"    # does not exist at repo root

    with tempfile.TemporaryDirectory() as dd:
        d = Path(dd)
        f = d / "learnings.jsonl"

        # 1. add several entries (validation passes)
        cmd_add(f, A(type="operational", key="suite-env", insight="suite needs FOO=bar",
                     confidence=8, source="observed", skill="dev", files=""), quiet=True)
        cmd_add(f, A(type="architecture", key="api-shape", insight="module X expects Y",
                     confidence=7, source="inferred", skill="", files=""), quiet=True)
        cmd_add(f, A(type="preference", key="tabs", insight="user prefers spaces over tabs",
                     confidence=6, source="user-stated", skill="", files=""), quiet=True)
        if len(load_entries(f)) != 3:
            problems.append("1: expected 3 entries after three adds")

        # 2. fail-closed validation: a bad --type / --confidence must exit 2
        for bad in (A(type="nope", key="k", insight="i", confidence=5,
                      source="observed", skill="", files=""),
                    A(type="operational", key="k", insight="i", confidence=99,
                      source="observed", skill="", files="")):
            try:
                cmd_add(f, bad, quiet=True)
                problems.append("2: add accepted invalid input (no fail-closed)")
            except SystemExit as e:
                if e.code != 2:
                    problems.append(f"2: bad add exited {e.code}, expected 2")
        if len(load_entries(f)) != 3:
            problems.append("2: a rejected add still mutated the file")

        entries = load_entries(f)

        # 3. DECAY with teeth: inject an OLD observed entry and a FRESH one;
        #    effective confidence of the old one must be strictly lower, while a
        #    user-stated entry of the same age must NOT decay.
        old = dict(entries[0]); old["ts"] = "2025-01-01T00:00:00Z"; old["confidence"] = 8
        fresh = dict(entries[0]); fresh["ts"] = "2026-01-01T00:00:00Z"; fresh["confidence"] = 8
        eff_old = _effective_confidence(old, as_of=NOW)
        eff_fresh = _effective_confidence(fresh, as_of=NOW)
        if not (eff_old < eff_fresh):
            problems.append(f"3: observed decay failed (old {eff_old} !< fresh {eff_fresh})")
        if eff_fresh != 8:
            problems.append(f"3: fresh observed entry wrongly decayed (eff {eff_fresh})")
        stated_old = dict(entries[2]); stated_old["ts"] = "2025-01-01T00:00:00Z"
        if _effective_confidence(stated_old, as_of=NOW) != stated_old["confidence"]:
            problems.append("3: user-stated entry decayed (it must not)")
        pref_old = dict(entries[2]); pref_old["source"] = "observed"
        pref_old["type"] = "preference"; pref_old["ts"] = "2025-01-01T00:00:00Z"
        if _effective_confidence(pref_old, as_of=NOW) != pref_old["confidence"]:
            problems.append("3: preference-type entry decayed (it must not)")

        # 4. list filters: --type and --min-confidence (on EFFECTIVE confidence)
        import io
        import contextlib

        def run(fn, *a, **k) -> str:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                fn(*a, **k)
            return buf.getvalue()

        out = run(cmd_list, f, A(type="architecture", min_confidence=None), as_of=NOW)
        if "api-shape" not in out or "suite-env" in out:
            problems.append("4: --type filter wrong")
        out = run(cmd_list, f, A(type=None, min_confidence=7), as_of=NOW)
        # all three are fresh (NOW≈their add time) → ≥7 keeps the 8 and 7, drops the 6
        if "tabs" in out:
            problems.append("4: --min-confidence did not drop the low-confidence entry")
        if "suite-env" not in out:
            problems.append("4: --min-confidence wrongly dropped a high-confidence entry")

        # 5. search hit AND miss
        out = run(cmd_search, f, "FOO=bar", as_of=NOW)
        if "1 match" not in out or "suite-env" not in out:
            problems.append("5: search did not hit a known term")
        out = run(cmd_search, f, "zzz-nonexistent-zzz", as_of=NOW)
        if "0 match" not in out:
            problems.append("5: search wrongly matched a nonexistent term")

        # 6. STALENESS + prune --apply: add a stale entry (missing file) and a
        #    decayed-below-floor entry; prune --apply must remove exactly those.
        cmd_add(f, A(type="tool", key="ghost", insight="refers to a deleted file",
                     confidence=9, source="observed", skill="",
                     files=f"{PRESENT},{MISSING}"), quiet=True)
        # an old observed entry whose effective confidence falls under PRUNE_FLOOR
        decayed = {"ts": "2020-01-01T00:00:00Z", "type": "pitfall", "key": "ancient",
                   "insight": "long stale", "confidence": 2, "source": "observed",
                   "skill": "", "files": []}
        append_entry(f, decayed)
        stale_hit = _is_stale({"files": [PRESENT, MISSING]})
        if stale_hit != [MISSING]:
            problems.append(f"6: staleness detection wrong: {stale_hit}")
        before = len(load_entries(f))
        run(cmd_prune, f, True, as_of=NOW)
        after = load_entries(f)
        keys_after = {e.get("key") for e in after}
        if "ghost" in keys_after:
            problems.append("6: prune --apply did not remove the STALE entry")
        if "ancient" in keys_after:
            problems.append("6: prune --apply did not remove the decayed entry")
        if "suite-env" not in keys_after or "tabs" not in keys_after:
            problems.append("6: prune --apply removed an entry it should have kept")
        if len(after) != before - 2:
            problems.append(f"6: prune removed {before - len(after)} entries, expected 2")

        # 7. check FAILS CLOSED on a planted malformed line (never silently skips)
        with f.open("a", encoding="utf-8") as fh:
            fh.write("{ this is not valid json \n")
        try:
            cmd_check(f)
            problems.append("7: check passed despite a malformed line (not fail-closed)")
        except SystemExit as e:
            if e.code != 1:
                problems.append(f"7: check exited {e.code} on malformed line, expected 1")

        # 8. check also fails closed on a structurally-invalid (bad enum) line
        g = d / "bad-enum.jsonl"
        g.write_text(json.dumps({"ts": "2026-01-01T00:00:00Z", "type": "bogus",
                                 "key": "k", "insight": "i", "confidence": 5,
                                 "source": "observed"}) + "\n")
        try:
            cmd_check(g)
            problems.append("8: check passed an invalid enum value")
        except SystemExit as e:
            if e.code != 1:
                problems.append(f"8: check exited {e.code} on bad enum, expected 1")

        # 9. SUPERSESSION (write-adjudication) on a fresh file: ADD -> UPDATE
        #    (old closed, new live, history kept) -> NOOP (identical re-add adds
        #    nothing) -> retract (DELETE) -> a new-key ADD. Plus live-by-default
        #    recall (--all reveals history).
        T0 = datetime(2026, 2, 1, tzinfo=timezone.utc)
        T1 = datetime(2026, 2, 2, tzinfo=timezone.utc)
        s = d / "supersede.jsonl"
        cmd_add(s, A(type="operational", key="db-host", insight="db host is NYC",
                     confidence=8, source="observed", skill="", files=""), quiet=True, now=T0)
        cmd_add(s, A(type="operational", key="db-host", insight="db host is SF",
                     confidence=8, source="observed", skill="", files=""), quiet=True, now=T1)
        alls = load_entries(s)
        live = [e for e in alls if _is_live(e)]
        if len(alls) != 2:
            problems.append(f"9: supersede must keep history (2 lines), got {len(alls)}")
        if len(live) != 1 or live[0].get("insight") != "db host is SF":
            problems.append(f"9: only live entry after supersede must be SF, got "
                            f"{[e.get('insight') for e in live]}")
        closed = [e for e in alls if not _is_live(e)]
        if len(closed) != 1 or not closed[0].get("valid_to"):
            problems.append("9: superseded entry must be stamped valid_to (history)")
        # NOOP: identical live insight adds no line
        cmd_add(s, A(type="operational", key="db-host", insight="db host is SF",
                     confidence=8, source="observed", skill="", files=""), quiet=True, now=T1)
        if len(load_entries(s)) != 2:
            problems.append("9: identical re-add should NOOP (no new line)")
        # live-by-default recall: default hides the superseded NYC, --all shows it
        out_live = run(cmd_list, s, A(type=None, min_confidence=None, all=False), as_of=T1)
        if "SF" not in out_live or "NYC" in out_live:
            problems.append("9: default list must show live (SF), hide superseded (NYC)")
        out_all = run(cmd_list, s, A(type=None, min_confidence=None, all=True), as_of=T1)
        if "NYC" not in out_all or "CLOSED" not in out_all:
            problems.append("9: --all list must include superseded history (CLOSED tag)")
        # retract (DELETE): closes the live entry -> 0 live for that key
        cmd_retract(s, "db-host", None, "decommissioned", now=T1, quiet=True)
        if any(_is_live(e) for e in load_entries(s)):
            problems.append("9: retract must close the live entry (0 live)")
        # a NEW key is a plain ADD even alongside history
        cmd_add(s, A(type="tool", key="cache", insight="redis on 6379",
                     confidence=7, source="observed", skill="", files=""), quiet=True, now=T1)
        if sum(1 for e in load_entries(s) if _is_live(e)) != 1:
            problems.append("9: a new-key add should be a plain ADD (1 live)")

        # 10. BM25 ranking (#23): the doc with the strongest term overlap ranks
        #     first; an off-topic query returns nothing; no deps.
        docs = [(0, "database host configuration postgres"),
                (1, "redis cache port"),
                (2, "the database connection pool size for postgres")]
        ranked = bm25_rank("postgres database", docs)
        if not ranked or ranked[0][0] not in (0, 2):
            problems.append(f"10: BM25 did not rank a postgres-database doc first: {ranked}")
        if any(i == 1 for i, _ in ranked):
            problems.append("10: BM25 returned the off-topic (redis) doc for a postgres query")
        if bm25_rank("zzz-nonexistent", docs):
            problems.append("10: BM25 returned hits for an absent term")
        # tokenizer ignores punctuation/case.
        if _tokenize("FOO=bar, baz!") != ["foo", "bar", "baz"]:
            problems.append(f"10: tokenizer wrong: {_tokenize('FOO=bar, baz!')}")

        # 11. OPTIONAL semantic backend (#23 deferred dep): an INJECTED embedder
        #     ranks by cosine (testable without the ~80MB dep); an ABSENT backend
        #     returns None (the fall-back signal); cmd_search --semantic FAILS SOFT
        #     to BM25 when absent — never silently skips, never fabricates a hit.
        VOCAB = ["postgres", "database", "redis", "cache", "port", "pool"]

        def fake_embed(texts):  # deterministic bag-of-words vectors, no deps
            return [[float(_tokenize(t).count(w)) for w in VOCAB] for t in texts]

        sdocs = [(0, "database host postgres"),
                 (1, "redis cache port"),
                 (2, "postgres connection pool")]
        sr = embed_rank("postgres database", sdocs, embedder=fake_embed)
        if not sr or sr[0][0] != 0:
            problems.append(f"11: semantic embed_rank did not rank the best match first: {sr}")
        if sr and sr[0][1] <= 0:
            problems.append("11: semantic top score should be > 0")
        # cosine sanity: identical vectors -> 1.0, orthogonal -> 0.0
        if abs(_cosine([1.0, 1.0], [1.0, 1.0]) - 1.0) > 1e-9:
            problems.append("11: cosine of identical vectors must be 1.0")
        if _cosine([1.0, 0.0], [0.0, 1.0]) != 0.0:
            problems.append("11: cosine of orthogonal vectors must be 0.0")
        # ABSENT backend -> None (deterministic via the cache sentinel)
        _EMBEDDER_CACHE["fn"] = None
        try:
            if embed_rank("anything", sdocs) is not None:
                problems.append("11: embed_rank must return None when no backend is available")
            # cmd_search --semantic must FAIL SOFT to BM25 (still finds the term)
            out = run(cmd_search, f, "FOO=bar", as_of=NOW, semantic=True)
            if "BM25-ranked match" not in out or "suite-env" not in out:
                problems.append("11: --semantic did not fall back to BM25 when backend absent")
        finally:
            _EMBEDDER_CACHE.pop("fn", None)
        # cmd_search --semantic with an INJECTED embedder ranks semantically
        out = run(cmd_search, f, "suite environment variable", as_of=NOW,
                  semantic=True, embedder=fake_embed)
        if "semantic match" not in out:
            problems.append("11: --semantic with an injected embedder did not rank semantically")

    # 12. D1 (boot design, resolved 2026-07-08): learnings are PROJECT-SPECIFIC.
    #     Store resolution: --file > $WF_LEARN_FILE > project-local > toolset.
    saved_env = {k: os.environ.get(k) for k in ("WF_LEARN_FILE", "WF_CALLER_CWD")}
    try:
        os.environ.pop("WF_LEARN_FILE", None)
        with tempfile.TemporaryDirectory() as pd:
            proj = Path(pd).resolve()
            (proj / ".git").mkdir()
            sub = proj / "src" / "deep"
            sub.mkdir(parents=True)

            # Caller inside a consumer project -> that project's store, from a
            # SUBDIR too (walk-up to the .git root), and staleness resolves
            # against the PROJECT, not the toolset repo.
            os.environ["WF_CALLER_CWD"] = str(proj)
            if _learn_file(None) != proj / "_workflow" / "learnings.jsonl":
                problems.append("12: project caller did not resolve to the project store")
            if _STALE_ROOT != proj:
                problems.append("12: staleness root did not follow the project store")
            os.environ["WF_CALLER_CWD"] = str(sub)
            if _learn_file(None) != proj / "_workflow" / "learnings.jsonl":
                problems.append("12: subdir caller did not walk up to the project root")

            # Caller inside the TOOLSET repo (root or subdir) -> repo store.
            for inside in (REPO_ROOT, REPO_ROOT / "scripts"):
                os.environ["WF_CALLER_CWD"] = str(inside)
                if _learn_file(None) != DEFAULT_FILE:
                    problems.append(f"12: toolset caller {inside} left the repo store")

            # Precedence unchanged: --file and $WF_LEARN_FILE both beat
            # project-local resolution.
            os.environ["WF_CALLER_CWD"] = str(proj)
            os.environ["WF_LEARN_FILE"] = str(proj / "elsewhere.jsonl")
            if _learn_file(None) != proj / "elsewhere.jsonl":
                problems.append("12: $WF_LEARN_FILE no longer wins over project-local")
            if _learn_file(str(proj / "arg.jsonl")) != proj / "arg.jsonl":
                problems.append("12: --file no longer wins")
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _set_stale_root(DEFAULT_FILE)  # restore production staleness root

    if problems:
        print("wf learn selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf learn selftest: PASS (add+validate fail-closed, list/type/min-conf "
          "filter, search hit+miss, observed-decays-while-user-stated-does-not, "
          "staleness+prune --apply, check fail-closed on malformed+invalid, "
          "supersession ADD/UPDATE/NOOP + retract with bi-temporal history kept + "
          "live-by-default recall; BM25 --rank orders by lexical relevance, no deps; "
          "--semantic uses an opt-in local-embedding tier that fails SOFT to BM25 "
          "when the ~80MB dep is absent; D1 project-local store: caller-dir walk-up, "
          "toolset-repo unchanged, --file/$WF_LEARN_FILE precedence kept, "
          "staleness follows the active store)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf learn")
    ap.add_argument("--selftest", action="store_true",
                    help="run the in-tempdir selftest and exit")
    # --file is accepted both before the subcommand and on each subcommand, so
    # `wf learn --file X list` and `wf learn list --file X` both work.
    ap.add_argument("--file", default=None,
                    help="learnings file (default: $WF_LEARN_FILE or "
                         "_workflow/learnings.jsonl)")
    sub = ap.add_subparsers(dest="action")

    # A sentinel lets a subcommand-level --file override the global one without a
    # subparser default of None clobbering an earlier global --file.
    def _add_file_arg(p):
        p.add_argument("--file", dest="sub_file", default=None,
                       help="learnings file (default: $WF_LEARN_FILE or "
                            "_workflow/learnings.jsonl)")

    p_add = sub.add_parser("add", help="append one learning")
    p_add.add_argument("--type", required=True, choices=list(TYPES))
    p_add.add_argument("--key", required=True, help="short slug")
    p_add.add_argument("--insight", required=True, help="the durable fact")
    p_add.add_argument("--confidence", type=int, default=5, help="base 1..10 (default 5)")
    p_add.add_argument("--source", default="observed", choices=list(SOURCES))
    p_add.add_argument("--skill", default="", help="originating skill/context")
    p_add.add_argument("--files", default="", help="comma-separated repo paths (staleness)")
    _add_file_arg(p_add)

    p_list = sub.add_parser("list", help="show entries with effective confidence")
    p_list.add_argument("--type", default=None, choices=list(TYPES))
    p_list.add_argument("--min-confidence", type=int, default=None,
                        help="hide entries below this EFFECTIVE confidence")
    p_list.add_argument("--all", action="store_true",
                        help="include superseded/retracted history (default: live only)")
    _add_file_arg(p_list)

    p_search = sub.add_parser("search", help="case-insensitive match over key+insight+files")
    p_search.add_argument("query")
    p_search.add_argument("--all", action="store_true",
                          help="include superseded/retracted history (default: live only)")
    p_search.add_argument("--rank", action="store_true",
                          help="rank by BM25 relevance (lexical, no deps) instead of "
                               "substring order")
    p_search.add_argument("--semantic", action="store_true",
                          help="rank by local-embedding semantic similarity "
                               "(OPT-IN: needs sentence-transformers + the "
                               "~80-90MB all-MiniLM-L6-v2 model; falls back to "
                               "BM25 if absent)")
    _add_file_arg(p_search)

    p_retract = sub.add_parser("retract", help="close a live learning by key (DELETE; kept as history)")
    p_retract.add_argument("--key", required=True, help="slug of the learning(s) to retract")
    p_retract.add_argument("--type", default=None, choices=list(TYPES),
                           help="narrow the retraction to one type")
    p_retract.add_argument("--reason", default="", help="why it no longer holds")
    _add_file_arg(p_retract)

    p_prune = sub.add_parser("prune", help="report (or --apply remove) stale/decayed entries")
    p_prune.add_argument("--apply", action="store_true",
                         help="rewrite the file without the flagged entries")
    _add_file_arg(p_prune)

    p_export = sub.add_parser("export", help="emit Markdown grouped by type")
    p_export.add_argument("--md", action="store_true",
                          help="emit Markdown (the default and only format)")
    p_export.add_argument("--all", action="store_true",
                          help="include superseded/retracted history (default: live only)")
    _add_file_arg(p_export)

    _add_file_arg(sub.add_parser("check", help="validate every line; fail-closed on malformed"))

    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("an action (add|list|search|prune|export|check) or --selftest is required")

    # subcommand-level --file wins over the global one when both/either is given.
    path = _learn_file(getattr(args, "sub_file", None) or args.file)

    if args.action == "add":
        return cmd_add(path, args)
    if args.action == "list":
        return cmd_list(path, args)
    if args.action == "search":
        return cmd_search(path, args.query,
                          include_closed=bool(getattr(args, "all", False)),
                          rank=bool(getattr(args, "rank", False)),
                          semantic=bool(getattr(args, "semantic", False)))
    if args.action == "retract":
        return cmd_retract(path, args.key, args.type, args.reason)
    if args.action == "prune":
        return cmd_prune(path, args.apply)
    if args.action == "export":
        return cmd_export(path, include_closed=bool(getattr(args, "all", False)))
    if args.action == "check":
        return cmd_check(path)
    ap.error(f"unknown action {args.action!r}")  # unreachable


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
