#!/usr/bin/env python3
"""wf-reflect.py — turn OBSERVED workflow activity into recurrence-gated
improvement CANDIDATES, without inventing findings and without violating the
repo's ephemeral-reflection rule.

WHY THIS EXISTS
  A daily "what did the workflow do well/badly" pass is only useful if it is
  (a) fed by real evidence, (b) cheap, and (c) silent when nothing recurred.
  Run naively it becomes a proposal generator: it fires every day because that
  is its job, and a repo whose governance rule is "a new skill is the most
  expensive option" drowns. The recurrence gate is the whole design: a signal
  is not a candidate until it has happened ENOUGH TIMES in ENOUGH DISTINCT
  CONTEXTS to clear the "repeatable, consequential" bar CLAUDE.md already sets.

WHAT IT READS (metadata + repo activity ONLY — never conversation content)
  This tool has NO access to conversation transcripts and never asks for them.
  It consumes two JSON observation payloads that an agent collects upstream:
    * SESSIONS — Claude Code session METADATA (id, title, status, timestamps,
      model, effort level, repo/branch, token usage, rate-limit state). This is
      exactly what the session-listing API returns; it carries no message text.
    * REPOS — repository activity (commits, changed files, CI check runs,
      branches, PR review comments), collected via git or the GitHub API.
  Conversation content is out of scope BY CONSTRUCTION, not by omission.

THE EPHEMERAL/PERSISTENT LINE (load-bearing — see core/DECISIONS.md D4a)
  This repo deliberately keeps TOOLSET / skill-gap reflections EPHEMERAL: never
  written to a file, committed, or filed. `wf reflect` does not weaken that; it
  splits the two halves and treats them differently:
    * OBSERVATIONS (facts) ARE persisted, append-only, at the tracked path
      _workflow/reflect/observations.jsonl — the same class of thing as a
      `wf cost` readout, and persisted for the same reason `wf learn` is
      (this container is ephemeral, so evidence that must accumulate ACROSS
      days has to be committed). Facts are not reflections.
    * The DIGEST (the suggestions) is a REFLECTION and stays EPHEMERAL. It is
      printed to stdout and NEVER written into the repo by this tool — see
      `digest`, which refuses an output path on purpose. A human adjudicates it;
      only accepted dispositions land in docs/field-feedback-backlog.md, which
      is a human-reviewed field-evidence table, not an agent's self-commentary.
  Never route a digest item into `wf learn` (that store is for PROJECT-
  OPERATIONAL facts, not toolset reflection).

HONESTY CONTRACT
  * Never invents. Every signal traces to ingested observation records, and
    every candidate carries its evidence ids. No observations -> "no candidates
    (0 observations)", never a fabricated clean bill of health.
  * NO SILENT CAPS. Signals that exist but fail the recurrence gate are
    reported as a SUPPRESSED count with their rule names — a gate that hides
    what it dropped reads as "nothing happened" when something did.
  * Fail-OPEN per record on ingest (a malformed or schema-drifted observation is
    skipped and COUNTED, never a crash — a partial ledger beats a hard error),
    but fail-CLOSED in `check` (any malformed ledger line is an error, never a
    silent skip). Same split as wf cost / wf learn.
  * Idempotent ingest: re-running the same day is a NOOP, not double-counting.
    A daily job that inflates its own evidence would manufacture recurrence.

Subcommands:
  ingest   normalize + append observations (idempotent); --sessions/--repos JSON
  signals  show every derived signal with its occurrence/context counts (ungated)
  digest   apply the recurrence gate and print the ephemeral DRAFT digest
  check    fail-closed validation of the observation ledger
  --selftest   every rule proven with a positive AND a guarded negative

Usage:
    wf reflect ingest --sessions <f.json> [--repos <f.json>] [--file <ledger>]
    wf reflect signals [--json]
    wf reflect digest [--min-occurrences N] [--min-contexts N] [--json]
    wf reflect check
    wf reflect --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = REPO_ROOT / "_workflow" / "reflect" / "observations.jsonl"
# Explicitly ACCEPTED findings. A frozen item is a decision on the record — not a
# silent suppression: it is committed, carries a reason and a date, is reported
# as a count on every run, and is reversible with `unfreeze`. Frozen by IDENTITY,
# so accepting today's backlog does NOT blind the rule to a new occurrence.
DEFAULT_FROZEN = REPO_ROOT / "_workflow" / "reflect" / "frozen.jsonl"

# --- recurrence gate defaults -------------------------------------------------
# The bar CLAUDE.md sets in prose ("repeatable, consequential") made mechanical.
# A signal must have fired MIN_OCCURRENCES times across MIN_CONTEXTS distinct
# contexts (sessions for session rules, days for repo rules) to be a CANDIDATE.
MIN_OCCURRENCES = 3
MIN_CONTEXTS = 2

# --- rule thresholds (deliberately explicit + editable) ------------------------
COST_OUTLIER_FACTOR = 3.0     # session total tokens > factor x repo median
COST_MIN_SAMPLE = 3           # need this many sessions before a median means anything
CACHE_ROI_MIN = 1.0           # cache_read < cache_write * this => poor cache ROI
LOW_OUTPUT_TOKENS = 2000      # "small task" ceiling for effort-escalation
HIGH_EFFORT = {"high", "max", "xhigh"}
STALLED_HOURS = 24            # non-terminal session untouched this long
TERMINAL_STATUSES = {
    "session_status_completed", "session_status_archived",
    "session_status_failed", "completed", "archived", "failed",
}
REWORK_MIN_COMMITS = 3        # same file in >= N commits ...
REWORK_WINDOW_DAYS = 7        # ... within this window
ABANDON_DAYS = 14             # unmerged branch untouched this long
REVERT_PATTERNS = (
    r"\brevert\b", r"\bre-?fix\b", r"\bfix(?:up)? (?:the )?fix\b",
    r"\bundo\b", r"\bbroke(?:n)? (?:the )?build\b", r"\bhotfix\b",
)
REVIEW_THEMES = {
    "error-handling": (r"\berror handling\b", r"\bunhandled\b", r"\bswallow(?:ed|s)? (?:the )?exception\b"),
    "naming": (r"\bnaming\b", r"\brename\b", r"\bmisleading name\b"),
    "tests": (r"\bmissing test\b", r"\bno test(?:s)? (?:for|cover)\b", r"\buntested\b"),
    "duplication": (r"\bduplicat(?:e|ion|ed)\b", r"\bcopy[- ]paste\b", r"\bDRY\b"),
    "security": (r"\bsecurity\b", r"\binjection\b", r"\bsanitiz", r"\bsecret\b"),
    "docs": (r"\bdocument(?:ation)?\b", r"\bdocstring\b", r"\bcomment (?:is|are) (?:stale|wrong)\b"),
}

OBS_KINDS = {"session", "commit", "check", "branch", "review"}
REQUIRED_OBS_FIELDS = ("ts", "kind", "source_id", "at", "fields")


# =============================================================================
# time helpers
# =============================================================================

def _parse_ts(value) -> datetime | None:
    """Parse an ISO8601 timestamp fail-open. Returns None on anything unusable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _day(value: str) -> str:
    """Calendar day of an ISO timestamp — the 'distinct context' for repo rules."""
    dt = _parse_ts(value)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d") if dt else "unknown"


# =============================================================================
# normalizers — raw MCP/GitHub payloads -> flat observation records
#
# Tolerant BY DESIGN: the upstream payload shapes are external and drift. Each
# normalizer digs through the nested shape but also accepts an already-flat one,
# and returns None for a record it cannot make sense of (counted as skipped by
# the caller, never crashing the daily run).
# =============================================================================

def _dig(obj, *path, default=None):
    """Walk nested dicts safely: _dig(d, 'a', 'b') -> d['a']['b'] or default."""
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _repo_of_session(raw: dict) -> str:
    """Best-effort repo attribution for a session, from sources or outcomes."""
    sources = _dig(raw, "session_context", "sources", default=[]) or []
    for src in sources:
        url = _dig(src, "git_repository", "url", default="") or ""
        if url:
            return url.rstrip("/").removesuffix(".git").split("/", 3)[-1] if "://" in url else url
    outcomes = _dig(raw, "session_context", "outcomes", default=[]) or []
    for out in outcomes:
        repo = _dig(out, "git_repository", "git_info", "repo", default="") or ""
        if repo:
            return repo
    return raw.get("repo", "") or "unknown"


def normalize_session(raw: dict, *, now: datetime) -> dict | None:
    """Session METADATA -> observation. No message content is read or expected."""
    if not isinstance(raw, dict):
        return None
    sid = raw.get("id") or raw.get("session_id") or ""
    if not sid:
        return None
    usage = _dig(raw, "external_metadata", "usage", default=None)
    if not isinstance(usage, dict):
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}

    def _tok(name: str) -> int:
        try:
            return int(usage.get(name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    created = raw.get("created_at", "") or ""
    updated = raw.get("updated_at", "") or created
    ctx = raw.get("session_context") if isinstance(raw.get("session_context"), dict) else {}
    rl = _dig(raw, "external_metadata", "rate_limit_info", "status", default="") or ""
    return {
        "ts": _iso(now),
        "kind": "session",
        "source_id": str(sid),
        "repo": _repo_of_session(raw),
        "at": updated or _iso(now),
        "fields": {
            "title": raw.get("title", "") or "",
            "status": str(raw.get("session_status", "") or raw.get("status", "")).lower(),
            "created_at": created,
            "updated_at": updated,
            "model": ctx.get("model", "") or "",
            "effort_level": str(ctx.get("effort_level", "") or "").lower(),
            "input_tokens": _tok("input_tokens"),
            "output_tokens": _tok("output_tokens"),
            "cache_read_tokens": _tok("cache_read_tokens"),
            "cache_write_tokens": _tok("cache_write_tokens"),
            "rate_limit_status": str(rl).lower(),
        },
    }


def normalize_repo_payload(raw: dict, *, now: datetime) -> list[dict]:
    """One repo's activity -> commit / check / branch / review observations."""
    out: list[dict] = []
    if not isinstance(raw, dict):
        return out
    # Lowercased: GitHub repo slugs are case-insensitive, but a mixed-case
    # full_name on one collection day (vs lowercase on another) used to split
    # a single recurring signal (e.g. abandoned_branch) into two separate,
    # under-counted keys. Normalize at the source so the recurrence gate sees
    # one repo, not two.
    repo = (raw.get("full_name") or raw.get("repo") or "unknown").lower()

    for commit in raw.get("commits", []) or []:
        if not isinstance(commit, dict):
            continue
        sha = commit.get("sha") or commit.get("id") or ""
        if not sha:
            continue
        files = [f for f in (commit.get("files") or []) if isinstance(f, str)]
        out.append({
            "ts": _iso(now), "kind": "commit", "source_id": f"{repo}@{sha}", "repo": repo,
            "at": commit.get("committed_at") or commit.get("date") or _iso(now),
            "fields": {"sha": sha, "message": commit.get("message", "") or "", "files": files},
        })

    for check in raw.get("checks", []) or []:
        if not isinstance(check, dict):
            continue
        name = check.get("name") or ""
        sha = check.get("head_sha") or check.get("sha") or ""
        if not name:
            continue
        out.append({
            "ts": _iso(now), "kind": "check", "source_id": f"{repo}@{sha}:{name}", "repo": repo,
            "at": check.get("completed_at") or check.get("at") or _iso(now),
            "fields": {"name": name, "conclusion": str(check.get("conclusion", "") or "").lower(),
                       "head_sha": sha,
                       # The branch is what makes a CI candidate ACTIONABLE. Without
                       # it "ci fails on this repo" sends you hunting; with it you
                       # know which branch to open. Found by running this for real.
                       "branch": check.get("head_branch") or check.get("branch") or ""},
        })

    for branch in raw.get("branches", []) or []:
        if not isinstance(branch, dict):
            continue
        name = branch.get("name") or ""
        if not name:
            continue
        out.append({
            "ts": _iso(now), "kind": "branch", "source_id": f"{repo}#{name}", "repo": repo,
            "at": branch.get("updated_at") or branch.get("pushed_at") or _iso(now),
            "fields": {"name": name, "merged": bool(branch.get("merged", False))},
        })

    for review in raw.get("review_comments", []) or []:
        if not isinstance(review, dict):
            continue
        # NB: `or`-chaining would discard a legitimate id of 0 (review ids are
        # ints), silently dropping evidence. Test for absence, not falsiness.
        rid = review.get("id", review.get("url", ""))
        body = review.get("body", "") or ""
        if rid is None or rid == "" or not body:
            continue
        out.append({
            "ts": _iso(now), "kind": "review", "source_id": f"{repo}:{rid}", "repo": repo,
            "at": review.get("created_at") or _iso(now),
            "fields": {"body": body, "path": review.get("path", "") or ""},
        })
    return out


# =============================================================================
# ledger I/O
# =============================================================================

def _obs_identity(obs: dict) -> tuple:
    """Idempotency key. A daily re-run must NOT double-count: the same event
    ingested twice is one observation. Inflated evidence would manufacture the
    very recurrence the gate is supposed to measure."""
    return (obs.get("kind", ""), obs.get("source_id", ""), obs.get("at", ""))


def read_ledger(path: Path, *, strict: bool = False,
                required: tuple = REQUIRED_OBS_FIELDS,
                kinds: set | None = None) -> tuple[list[dict], int]:
    """Read observations. Fail-OPEN (skip+count bad lines) unless strict, which
    fails CLOSED by raising — `check` uses strict, everything else does not.
    `required`/`kinds` parameterize the schema so both ledgers (signals and
    open work) share one reader and one honesty contract."""
    kinds = OBS_KINDS if kinds is None else kinds
    if not path.exists():
        return [], 0
    records, skipped = [], 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            if strict:
                raise ValueError(f"line {lineno}: not valid JSON ({exc.msg})") from exc
            skipped += 1
            continue
        if not isinstance(obj, dict) or any(f not in obj for f in required):
            if strict:
                missing = [f for f in required if not isinstance(obj, dict) or f not in obj]
                raise ValueError(f"line {lineno}: missing required field(s) {missing}")
            skipped += 1
            continue
        if obj.get("kind") not in kinds:
            if strict:
                raise ValueError(f"line {lineno}: unknown kind {obj.get('kind')!r}")
            skipped += 1
            continue
        records.append(obj)
    return records, skipped


def append_ledger(path: Path, observations: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for obs in observations:
            fh.write(json.dumps(obs, ensure_ascii=False, sort_keys=True) + "\n")
    return len(observations)


# =============================================================================
# rules engine
#
# Each rule turns observations into HITS. A hit is (rule, key, context, at,
# evidence) where `key` groups recurrence and `context` is the distinct-context
# unit (session id for session rules, calendar day for repo rules). Rules never
# judge; they only report what the records show.
# =============================================================================

def _hit(rule: str, key: str, context: str, at: str, evidence: str,
         identity: str | None = None) -> dict:
    """One rule firing.

    `identity` names the underlying THING the hit is about — a branch, a commit,
    a failing check run. Recurrence is counted over DISTINCT identities, not over
    hits, because a persistent-state rule re-observes the same thing every run:
    a branch that has been cold for 90 days is ONE abandoned branch seen 30
    times, not 30 abandoned branches. Event-shaped rules pass a naturally unique
    identity (a sha, a check run), so their counts are unaffected. Defaults to
    the hit itself, which reproduces the old per-observation behaviour."""
    return {"rule": rule, "key": key, "context": context, "at": at,
            "evidence": evidence, "identity": identity or f"{at}|{evidence}"}


def _norm_repo(repo: str) -> str:
    """Repo names arrive in mixed case from different collectors, and the same
    repo under two spellings would count as two separate signals — and did, for
    18 repos, until this was normalized at ingest. Normalizing again at READ
    time keeps historical records from re-splitting the count."""
    return (repo or "unknown").lower()


def _session_rules(sessions: list[dict], *, now: datetime) -> list[dict]:
    hits: list[dict] = []
    by_repo: dict[str, list[dict]] = {}
    for obs in sessions:
        by_repo.setdefault(_norm_repo(obs.get("repo", "unknown")), []).append(obs)

    for repo, group in by_repo.items():
        totals = []
        for obs in group:
            f = obs["fields"]
            totals.append(f["input_tokens"] + f["output_tokens"] +
                          f["cache_read_tokens"] + f["cache_write_tokens"])
        median = statistics.median(totals) if len(totals) >= COST_MIN_SAMPLE else None

        for obs, total in zip(group, totals):
            f, sid = obs["fields"], obs["source_id"]

            # cost_outlier — a session that cost multiples of this repo's norm.
            if median and median > 0 and total > median * COST_OUTLIER_FACTOR:
                hits.append(_hit("cost_outlier", repo, sid, obs["at"],
                                 f"{total} tokens vs repo median {int(median)}", identity=sid))

            # cache_inefficiency — prompt-cache ROI is poor (paying to write a
            # cache that is barely read back).
            if f["cache_write_tokens"] > 0 and \
               f["cache_read_tokens"] < f["cache_write_tokens"] * CACHE_ROI_MIN:
                hits.append(_hit("cache_inefficiency", repo, sid, obs["at"],
                                 f"cache_read {f['cache_read_tokens']} < cache_write "
                                 f"{f['cache_write_tokens']}", identity=sid))

            # effort_escalation — high/max reasoning effort spent on a session
            # that produced very little. cascade_routing says escalate on an
            # EXTERNAL-verifier fail, not by default.
            if f["effort_level"] in HIGH_EFFORT and 0 < f["output_tokens"] < LOW_OUTPUT_TOKENS:
                hits.append(_hit("effort_escalation", repo, sid, obs["at"],
                                 f"effort={f['effort_level']} but output={f['output_tokens']} tokens", identity=sid))

            # stalled_session — non-terminal and untouched; a spawn-and-forget smell.
            updated = _parse_ts(f["updated_at"])
            if f["status"] not in TERMINAL_STATUSES and updated and \
               (now - updated) > timedelta(hours=STALLED_HOURS):
                hours = int((now - updated).total_seconds() // 3600)
                hits.append(_hit("stalled_session", repo, sid, obs["at"],
                                 f"status={f['status'] or 'unknown'} untouched {hours}h",
                                 identity=sid))

            # rate_limit_pressure — capacity, not craft, was the binding constraint.
            if f["rate_limit_status"] and f["rate_limit_status"] != "allowed":
                hits.append(_hit("rate_limit_pressure", "account", sid, obs["at"],
                                 f"rate limit status={f['rate_limit_status']}",
                                 identity=sid))
    return hits


def _repo_rules(observations: list[dict], *, now: datetime) -> list[dict]:
    hits: list[dict] = []
    commits = [o for o in observations if o["kind"] == "commit"]
    checks = [o for o in observations if o["kind"] == "check"]
    branches = [o for o in observations if o["kind"] == "branch"]
    reviews = [o for o in observations if o["kind"] == "review"]

    # revert_churn — work that had to be undone or re-fixed.
    for obs in commits:
        msg = obs["fields"].get("message", "") or ""
        for pattern in REVERT_PATTERNS:
            if re.search(pattern, msg, re.IGNORECASE):
                hits.append(_hit("revert_churn", _norm_repo(obs["repo"]),
                                 _day(obs["at"]), obs["at"], msg.splitlines()[0][:120],
                                 identity=obs["fields"].get("sha") or obs["source_id"]))
                break

    # rework_file — one file rewritten repeatedly in a short window: the change
    # was not understood the first time, or the design fights the code.
    touches: dict[tuple[str, str], list[dict]] = {}
    for obs in commits:
        for path in obs["fields"].get("files", []):
            touches.setdefault((_norm_repo(obs["repo"]), path), []).append(obs)
    for (repo, path), group in touches.items():
        dated = sorted(
            [(g, _parse_ts(g["at"])) for g in group if _parse_ts(g["at"])],
            key=lambda pair: pair[1],
        )
        # Count non-overlapping BURSTS, not commits. One burst is ordinary
        # development; a file that burns repeatedly is the actual signal. Emitting
        # a single hit per file (and stopping) would make this rule unable to
        # reach the recurrence gate at all — a rule that can never fire is worse
        # than no rule, because it reads as coverage.
        idx = 0
        while idx < len(dated):
            obs, when = dated[idx]
            window = [pair for pair in dated[idx:]
                      if (pair[1] - when) <= timedelta(days=REWORK_WINDOW_DAYS)]
            if len(window) >= REWORK_MIN_COMMITS:
                hits.append(_hit("rework_file", f"{repo}:{path}", _day(obs["at"]), obs["at"],
                                 f"{len(window)} commits touched {path} within "
                                 f"{REWORK_WINDOW_DAYS}d",
                                 identity=f"{repo}:{path}@{_day(obs['at'])}"))
                idx += len(window)
            else:
                idx += 1

    # ci_failure_repeat — the same check failing again and again.
    for obs in checks:
        if obs["fields"].get("conclusion") == "failure":
            branch = obs["fields"].get("branch") or ""
            where = f" on {branch}" if branch else ""
            hits.append(_hit("ci_failure_repeat",
                             f"{_norm_repo(obs['repo'])}:{obs['fields']['name']}",
                             _day(obs["at"]), obs["at"],
                             f"{obs['fields']['name']} failed at "
                             f"{obs['fields'].get('head_sha','')[:8]}{where}",
                             identity=obs["source_id"]))

    # abandoned_branch — started, pushed, never merged, gone cold.
    for obs in branches:
        when = _parse_ts(obs["at"])
        if not obs["fields"].get("merged") and when and \
           (now - when) > timedelta(days=ABANDON_DAYS):
            days = (now - when).days
            hits.append(_hit("abandoned_branch", _norm_repo(obs["repo"]),
                             _day(obs["at"]), obs["at"],
                             f"{obs['fields']['name']} unmerged, cold {days}d",
                             identity=f"{_norm_repo(obs['repo'])}#{obs['fields']['name']}"))

    # review_theme_repeat — reviewers keep raising the same class of problem.
    for obs in reviews:
        body = obs["fields"].get("body", "") or ""
        for theme, patterns in REVIEW_THEMES.items():
            if any(re.search(p, body, re.IGNORECASE) for p in patterns):
                hits.append(_hit("review_theme_repeat",
                                 f"{_norm_repo(obs['repo'])}:{theme}",
                                 _day(obs["at"]), obs["at"], body.strip()[:120],
                                 identity=obs["source_id"]))
    return hits


def analyze(observations: list[dict], *, now: datetime,
            min_occurrences: int = MIN_OCCURRENCES,
            min_contexts: int = MIN_CONTEXTS,
            frozen: frozenset | None = None) -> dict:
    """THE testable seam. Pure function: observation records -> signals split
    into recurrence-gated CANDIDATES and reported SUPPRESSED ones."""
    sessions = [o for o in observations if o["kind"] == "session"]
    hits = _session_rules(sessions, now=now) + _repo_rules(observations, now=now)

    frozen = frozen or frozenset()
    frozen_hits = [h for h in hits if (h["rule"], h["identity"]) in frozen]
    hits = [h for h in hits if (h["rule"], h["identity"]) not in frozen]

    grouped: dict[tuple[str, str], list[dict]] = {}
    for hit in hits:
        grouped.setdefault((hit["rule"], hit["key"]), []).append(hit)

    signals = []
    for (rule, key), group in sorted(grouped.items()):
        contexts = sorted({h["context"] for h in group})
        ats = sorted(h["at"] for h in group)
        # Recurrence counts DISTINCT identities. The raw observation count is
        # kept alongside so re-observation is visible rather than erased.
        identities = {h["identity"] for h in group}
        occurrences = len(identities)
        seen = {}
        for h in group:                      # one evidence line per identity
            seen.setdefault(h["identity"], h["evidence"])
        signals.append({
            "rule": rule, "key": key,
            "occurrences": occurrences, "observations": len(group),
            "contexts": len(contexts),
            "first_seen": ats[0], "last_seen": ats[-1],
            "evidence": list(seen.values())[:5],
            "passes_gate": occurrences >= min_occurrences and len(contexts) >= min_contexts,
        })

    candidates = [s for s in signals if s["passes_gate"]]
    suppressed = [s for s in signals if not s["passes_gate"]]
    candidates.sort(key=lambda s: (-s["occurrences"], s["rule"], s["key"]))
    return {
        "observations": len(observations),
        "sessions": len(sessions),
        "gate": {"min_occurrences": min_occurrences, "min_contexts": min_contexts},
        "candidates": candidates,
        "suppressed": suppressed,
        "suppressed_count": len(suppressed),
        "frozen_count": len({(h["rule"], h["identity"]) for h in frozen_hits}),
        "frozen_rules": sorted({h["rule"] for h in frozen_hits}),
    }


# =============================================================================
# frozen findings — accepted, not hidden
# =============================================================================

def load_frozen(path: Path) -> frozenset:
    """(rule, identity) pairs that have been explicitly accepted. Unreadable or
    malformed lines are skipped fail-OPEN: a broken freeze file must never cause
    a finding to be hidden, only to be reported again."""
    if not path.exists():
        return frozenset()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if isinstance(rec, dict) and rec.get("rule") and rec.get("identity"):
                out.add((rec["rule"], rec["identity"]))
        except json.JSONDecodeError:
            continue
    return frozenset(out)


def cmd_freeze(args, ledger: Path, *, now: datetime) -> int:
    """Accept the findings a rule currently produces. Frozen by IDENTITY, so a
    NEW occurrence of the same rule still surfaces tomorrow."""
    observations, _ = read_ledger(ledger)
    sessions = [o for o in observations if o["kind"] == "session"]
    hits = _session_rules(sessions, now=now) + _repo_rules(observations, now=now)
    target = [h for h in hits if h["rule"] == args.rule
              and (not args.key or h["key"] == args.key)]
    if not target:
        print(f"wf reflect freeze: no current findings for rule {args.rule!r}"
              + (f" key {args.key!r}" if args.key else "") + " — nothing frozen")
        return 0
    frozen_path = Path(args.frozen_file) if args.frozen_file else Path(
        os.environ.get("WF_REFLECT_FROZEN", str(DEFAULT_FROZEN)))
    already = load_frozen(frozen_path)
    new = sorted({(h["rule"], h["identity"]) for h in target} - already)
    if not new:
        print(f"wf reflect freeze: all {len(target)} finding(s) already frozen")
        return 0
    frozen_path.parent.mkdir(parents=True, exist_ok=True)
    with frozen_path.open("a", encoding="utf-8") as fh:
        for rule, identity in new:
            fh.write(json.dumps({"rule": rule, "identity": identity,
                                 "reason": args.reason or "accepted backlog",
                                 "frozen_at": _iso(now)},
                                ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wf reflect freeze: froze {len(new)} identity/identities for {args.rule}")
    print(f"  reason: {args.reason or 'accepted backlog'}")
    print(f"  file:   {frozen_path}")
    print("  A NEW occurrence of this rule will still surface — only these exact")
    print("  identities are accepted, and every run reports the frozen count.")
    return 0


def cmd_unfreeze(args, ledger: Path, *, now: datetime) -> int:
    frozen_path = Path(args.frozen_file) if args.frozen_file else Path(
        os.environ.get("WF_REFLECT_FROZEN", str(DEFAULT_FROZEN)))
    if not frozen_path.exists():
        print(f"wf reflect unfreeze: nothing frozen ({frozen_path} absent)")
        return 0
    kept, dropped = [], 0
    for line in frozen_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        if rec.get("rule") == args.rule and (not args.identity
                                             or rec.get("identity") == args.identity):
            dropped += 1
            continue
        kept.append(line)
    frozen_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    print(f"wf reflect unfreeze: released {dropped} frozen identity/identities "
          f"for {args.rule}")
    return 0


# =============================================================================
# rendering
# =============================================================================

RULE_PROMPTS = {
    "cost_outlier": "sessions on this repo blow past their own norm — right-size the process or split the task",
    "cache_inefficiency": "prompt-cache ROI is poor — context is being rebuilt instead of reused",
    "effort_escalation": "high reasoning effort spent on small outputs — cascade_routing says escalate on a verifier fail, not by default",
    "stalled_session": "sessions left non-terminal — spawn-and-forget; reconcile at stop spots",
    "rate_limit_pressure": "capacity, not craft, was the binding constraint",
    "revert_churn": "work is being undone or re-fixed — verification is landing after the commit, not before",
    "rework_file": "the same file keeps being rewritten — the change was not understood up front",
    "ci_failure_repeat": "the same check keeps failing — a pre-push gate is missing",
    "abandoned_branch": "branches started and left cold — scope or dispatch discipline",
    "review_theme_repeat": "reviewers keep raising the same class of problem",
}


def render(report: dict) -> str:
    out: list[str] = []
    gate = report["gate"]
    out.append("wf reflect — DRAFT digest (ephemeral: adjudicate, then discard)")
    out.append(f"  observations: {report['observations']} ({report['sessions']} sessions)")
    out.append(f"  recurrence gate: >= {gate['min_occurrences']} occurrences "
               f"across >= {gate['min_contexts']} distinct contexts")
    out.append("")

    if report["observations"] == 0:
        out.append("no candidates (0 observations ingested) — this is an EMPTY INPUT,")
        out.append("not a clean bill of health. Check the collection step ran.")
        return "\n".join(out)

    if not report["candidates"]:
        out.append("no candidates cleared the recurrence gate.")
    else:
        out.append(f"CANDIDATES ({len(report['candidates'])}) — recurring, evidence-backed:")
        for sig in report["candidates"]:
            out.append("")
            out.append(f"  [{sig['rule']}] {sig['key']}")
            seen_note = (f" (seen {sig['observations']}x)"
                         if sig.get("observations", sig["occurrences"]) > sig["occurrences"]
                         else "")
            out.append(f"    {sig['occurrences']} distinct{seen_note} across "
                       f"{sig['contexts']} contexts "
                       f"({sig['first_seen'][:10]} -> {sig['last_seen'][:10]})")
            out.append(f"    reading: {RULE_PROMPTS.get(sig['rule'], 'recurring signal')}")
            for ev in sig["evidence"]:
                out.append(f"    - {ev}")

    # NO SILENT CAPS: say what the gate held back, or a quiet run reads as "all clear".
    out.append("")
    if report["suppressed_count"]:
        rules = sorted({s["rule"] for s in report["suppressed"]})
        out.append(f"SUPPRESSED by the gate: {report['suppressed_count']} signal(s) "
                   f"below threshold — {', '.join(rules)}")
        out.append("  (seen, not yet repeatable. They stay in the ledger and will")
        out.append("   surface if they recur.)")
    else:
        out.append("SUPPRESSED by the gate: none")

    # Frozen is an accepted DECISION, reported every run — never a silent drop.
    if report.get("frozen_count"):
        out.append(f"FROZEN (accepted, still tracked): {report['frozen_count']} "
                   f"identity/identities — {', '.join(report['frozen_rules'])}")
        out.append("  (acknowledged on the record; a NEW occurrence still surfaces.")
        out.append("   Release with `wf reflect unfreeze --rule <rule>`.)")

    out.append("")
    out.append("This digest is a TOOLSET reflection: ephemeral by rule (DECISIONS D4a).")
    out.append("Do NOT commit it and never route it into `wf learn`. Adjudicate each")
    out.append("candidate; only accepted dispositions belong in")
    out.append("docs/field-feedback-backlog.md.")
    return "\n".join(out)


# =============================================================================
# subcommands
# =============================================================================

def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"wf reflect: no such file: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"wf reflect: {path} is not valid JSON ({exc.msg})")


def cmd_ingest(args, ledger: Path, *, now: datetime) -> int:
    fresh: list[dict] = []
    skipped = 0

    if args.sessions:
        payload = _load_json(Path(args.sessions))
        raw_sessions = payload.get("sessions", payload) if isinstance(payload, dict) else payload
        if not isinstance(raw_sessions, list):
            raise SystemExit("wf reflect: --sessions must hold a list (or {'sessions': [...]})")
        for raw in raw_sessions:
            obs = normalize_session(raw, now=now)
            if obs is None:
                skipped += 1
            else:
                fresh.append(obs)

    if args.repos:
        payload = _load_json(Path(args.repos))
        raw_repos = payload.get("repos", payload) if isinstance(payload, dict) else payload
        if not isinstance(raw_repos, list):
            raise SystemExit("wf reflect: --repos must hold a list (or {'repos': [...]})")
        for raw in raw_repos:
            produced = normalize_repo_payload(raw, now=now)
            if not produced and not isinstance(raw, dict):
                skipped += 1
            fresh.extend(produced)

    existing, bad_lines = read_ledger(ledger)
    seen = {_obs_identity(o) for o in existing}
    new: list[dict] = []
    for obs in fresh:
        ident = _obs_identity(obs)
        if ident in seen:
            continue          # idempotent: same event, already recorded
        seen.add(ident)
        new.append(obs)

    append_ledger(ledger, new)
    dupes = len(fresh) - len(new)
    print(f"wf reflect ingest: +{len(new)} new observation(s), {dupes} duplicate(s) ignored, "
          f"{skipped} unusable record(s) skipped"
          + (f", {bad_lines} malformed ledger line(s) skipped" if bad_lines else ""))
    print(f"  ledger: {ledger} ({len(existing) + len(new)} total)")
    return 0


def _frozen_for(args) -> frozenset:
    return load_frozen(Path(args.frozen_file) if getattr(args, "frozen_file", None)
                       else Path(os.environ.get("WF_REFLECT_FROZEN", str(DEFAULT_FROZEN))))


def cmd_signals(args, ledger: Path, *, now: datetime) -> int:
    observations, bad = read_ledger(ledger)
    report = analyze(observations, now=now, frozen=_frozen_for(args),
                     min_occurrences=args.min_occurrences, min_contexts=args.min_contexts)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print(f"wf reflect signals — {report['observations']} observation(s), "
          f"{len(report['candidates']) + report['suppressed_count']} signal(s)"
          + (f" ({bad} malformed line(s) skipped)" if bad else ""))
    for sig in report["candidates"] + report["suppressed"]:
        gate = "CANDIDATE" if sig["passes_gate"] else "below-gate"
        print(f"  [{gate:>10}] {sig['rule']}: {sig['key']} "
              f"({sig['occurrences']}x / {sig['contexts']} contexts)")
    return 0


def cmd_digest(args, ledger: Path, *, now: datetime) -> int:
    observations, _ = read_ledger(ledger)
    report = analyze(observations, now=now, frozen=_frozen_for(args),
                     min_occurrences=args.min_occurrences, min_contexts=args.min_contexts)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render(report))
    return 0


def cmd_check(args, ledger: Path, *, now: datetime) -> int:
    """Fail-CLOSED: any malformed line is an error. A silently-skipped ledger
    line is evidence quietly lost, which would understate recurrence."""
    if not ledger.exists():
        print(f"wf reflect check: OK (no ledger yet at {ledger})")
        return 0
    try:
        observations, _ = read_ledger(ledger, strict=True)
    except ValueError as exc:
        print(f"wf reflect check: FAIL — {exc}", file=sys.stderr)
        return 2
    ow = Path(os.environ.get("WF_OPENWORK_FILE", str(DEFAULT_OPENWORK)))
    ow_count = 0
    if ow.exists():
        try:
            ow_records, _ = read_ledger(ow, strict=True, required=REQUIRED_ITEM_FIELDS,
                                        kinds=OPENWORK_KINDS)
        except ValueError as exc:
            print(f"wf reflect check: FAIL — open-work ledger {exc}", file=sys.stderr)
            return 2
        ow_count = len(ow_records)
    print(f"wf reflect check: OK ({len(observations)} well-formed observation(s), "
          f"{ow_count} open-work record(s))")
    return 0


# =============================================================================
# selftest — every rule proven with a POSITIVE and a GUARDED NEGATIVE.
# A rule that only ever fires proves nothing; the negative is what shows the
# threshold is real and not a tautology.
# =============================================================================

_NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _ago(**kw) -> str:
    return _iso(_NOW - timedelta(**kw))


def _sess(sid, repo="own/repo", *, out=5000, cin=0, cread=0, cwrite=0,
          effort="medium", status="session_status_completed", updated=None, rl="allowed"):
    return {
        "id": sid, "title": f"session {sid}",
        "session_status": status,
        "created_at": _ago(days=1), "updated_at": updated or _ago(hours=1),
        "session_context": {"model": "m", "effort_level": effort,
                            "sources": [{"git_repository": {"url": f"https://github.com/{repo}"}}]},
        "external_metadata": {"usage": {"input_tokens": cin, "output_tokens": out,
                                        "cache_read_tokens": cread, "cache_write_tokens": cwrite},
                              "rate_limit_info": {"status": rl}},
    }


def _obs_from_sessions(raws):
    return [o for o in (normalize_session(r, now=_NOW) for r in raws) if o]


def _obs_from_repos(raws):
    out = []
    for raw in raws:
        out.extend(normalize_repo_payload(raw, now=_NOW))
    return out


def _fired(observations, **kw) -> set:
    report = analyze(observations, now=_NOW, **kw)
    return {s["rule"] for s in report["candidates"] + report["suppressed"]}


def _selftest() -> int:
    ok = True

    def check(label: str, condition: bool):
        nonlocal ok
        if not condition:
            ok = False
            print(f"  FAIL: {label}", file=sys.stderr)

    # --- session rules --------------------------------------------------------
    # cost_outlier: cache fields zeroed so this test isolates ONE rule.
    pos = _obs_from_sessions([_sess("s1", out=100), _sess("s2", out=100),
                              _sess("s3", out=100), _sess("s4", out=1000)])
    check("cost_outlier positive", "cost_outlier" in _fired(pos))
    neg = _obs_from_sessions([_sess("s1", out=100), _sess("s2", out=100),
                              _sess("s3", out=100), _sess("s4", out=200)])
    check("cost_outlier negative (2x median is under the 3x bar)",
          "cost_outlier" not in _fired(neg))
    check("cost_outlier negative (below min sample, no median)",
          "cost_outlier" not in _fired(_obs_from_sessions([_sess("s1", out=100),
                                                          _sess("s2", out=99999)])))

    check("cache_inefficiency positive",
          "cache_inefficiency" in _fired(_obs_from_sessions([_sess("s1", cread=50, cwrite=100)])))
    check("cache_inefficiency negative (cache read back more than written)",
          "cache_inefficiency" not in _fired(_obs_from_sessions([_sess("s1", cread=200, cwrite=100)])))
    check("cache_inefficiency negative (no cache written at all)",
          "cache_inefficiency" not in _fired(_obs_from_sessions([_sess("s1", cread=0, cwrite=0)])))

    check("effort_escalation positive",
          "effort_escalation" in _fired(_obs_from_sessions([_sess("s1", effort="max", out=100)])))
    check("effort_escalation negative (high effort, large output = justified)",
          "effort_escalation" not in _fired(_obs_from_sessions([_sess("s1", effort="max", out=50000)])))
    check("effort_escalation negative (small output at low effort is fine)",
          "effort_escalation" not in _fired(_obs_from_sessions([_sess("s1", effort="low", out=100)])))

    check("stalled_session positive",
          "stalled_session" in _fired(_obs_from_sessions(
              [_sess("s1", status="session_status_running", updated=_ago(hours=48))])))
    check("stalled_session negative (terminal status never stalls)",
          "stalled_session" not in _fired(_obs_from_sessions(
              [_sess("s1", status="session_status_completed", updated=_ago(hours=48))])))
    check("stalled_session negative (running but recently touched)",
          "stalled_session" not in _fired(_obs_from_sessions(
              [_sess("s1", status="session_status_running", updated=_ago(hours=1))])))

    check("rate_limit_pressure positive",
          "rate_limit_pressure" in _fired(_obs_from_sessions([_sess("s1", rl="exceeded")])))
    check("rate_limit_pressure negative (allowed is not pressure)",
          "rate_limit_pressure" not in _fired(_obs_from_sessions([_sess("s1", rl="allowed")])))

    # --- repo rules -----------------------------------------------------------
    check("revert_churn positive",
          "revert_churn" in _fired(_obs_from_repos([{"full_name": "o/r", "commits": [
              {"sha": "a", "message": 'Revert "bad change"', "committed_at": _ago(days=1)}]}])))
    # Guarded negative: substring matching would fire on "convert"/"revertible";
    # the word-boundary anchor must not.
    check("revert_churn negative (word-boundary, not substring)",
          "revert_churn" not in _fired(_obs_from_repos([{"full_name": "o/r", "commits": [
              {"sha": "a", "message": "convert config to yaml; add revertible migration",
               "committed_at": _ago(days=1)}]}])))

    rework_pos = [{"full_name": "o/r", "commits": [
        {"sha": f"c{i}", "message": "wip", "files": ["a.py"], "committed_at": _ago(days=i)}
        for i in range(3)]}]
    check("rework_file positive", "rework_file" in _fired(_obs_from_repos(rework_pos)))
    rework_neg_window = [{"full_name": "o/r", "commits": [
        {"sha": f"c{i}", "message": "wip", "files": ["a.py"], "committed_at": _ago(days=i * 20)}
        for i in range(3)]}]
    check("rework_file negative (same count, spread beyond the window)",
          "rework_file" not in _fired(_obs_from_repos(rework_neg_window)))
    rework_neg_count = [{"full_name": "o/r", "commits": [
        {"sha": f"c{i}", "message": "wip", "files": ["a.py"], "committed_at": _ago(days=i)}
        for i in range(2)]}]
    check("rework_file negative (inside window but under the count)",
          "rework_file" not in _fired(_obs_from_repos(rework_neg_count)))

    check("ci_failure_repeat positive",
          "ci_failure_repeat" in _fired(_obs_from_repos([{"full_name": "o/r", "checks": [
              {"name": "build", "conclusion": "failure", "head_sha": "abc", "completed_at": _ago(days=1)}]}])))
    branch_ev = analyze(_obs_from_repos([{"full_name": "o/r", "checks": [
        {"name": "ci", "conclusion": "failure", "head_sha": "deadbeefcafe",
         "head_branch": "claude/some-branch", "completed_at": _ago(days=1)}]}]),
        now=_NOW)
    all_sigs = branch_ev["candidates"] + branch_ev["suppressed"]
    check("ci_failure_repeat evidence names the BRANCH, not just the repo",
          any("claude/some-branch" in e for s_ in all_sigs for e in s_["evidence"]))
    no_branch = analyze(_obs_from_repos([{"full_name": "o/r", "checks": [
        {"name": "ci", "conclusion": "failure", "head_sha": "deadbeefcafe",
         "completed_at": _ago(days=1)}]}]), now=_NOW)
    check("ci_failure_repeat degrades cleanly when no branch is supplied",
          all(" on " not in e for s_ in (no_branch["candidates"] + no_branch["suppressed"])
              for e in s_["evidence"]))
    check("ci_failure_repeat negative (a passing check is not a failure)",
          "ci_failure_repeat" not in _fired(_obs_from_repos([{"full_name": "o/r", "checks": [
              {"name": "build", "conclusion": "success", "head_sha": "abc", "completed_at": _ago(days=1)}]}])))

    check("abandoned_branch positive",
          "abandoned_branch" in _fired(_obs_from_repos([{"full_name": "o/r", "branches": [
              {"name": "old", "merged": False, "updated_at": _ago(days=30)}]}])))
    check("abandoned_branch negative (merged, however old)",
          "abandoned_branch" not in _fired(_obs_from_repos([{"full_name": "o/r", "branches": [
              {"name": "old", "merged": True, "updated_at": _ago(days=30)}]}])))
    check("abandoned_branch negative (unmerged but still warm)",
          "abandoned_branch" not in _fired(_obs_from_repos([{"full_name": "o/r", "branches": [
              {"name": "new", "merged": False, "updated_at": _ago(days=2)}]}])))

    check("review_theme_repeat positive",
          "review_theme_repeat" in _fired(_obs_from_repos([{"full_name": "o/r", "review_comments": [
              {"id": 1, "body": "missing test for the failure path", "created_at": _ago(days=1)}]}])))
    check("review_theme_repeat negative (no themed content)",
          "review_theme_repeat" not in _fired(_obs_from_repos([{"full_name": "o/r", "review_comments": [
              {"id": 1, "body": "looks good to me, shipping", "created_at": _ago(days=1)}]}])))

    # --- the recurrence gate itself ------------------------------------------
    gated = _obs_from_repos([{"full_name": "o/r", "checks": [
        {"name": "build", "conclusion": "failure", "head_sha": f"s{i}",
         "completed_at": _ago(days=i)} for i in range(3)]}])
    rep = analyze(gated, now=_NOW)
    check("gate: 3 occurrences across 3 days clears", 
          any(s["rule"] == "ci_failure_repeat" for s in rep["candidates"]))

    under = _obs_from_repos([{"full_name": "o/r", "checks": [
        {"name": "build", "conclusion": "failure", "head_sha": "s0", "completed_at": _ago(days=1)}]}])
    rep_under = analyze(under, now=_NOW)
    check("gate: a single occurrence does NOT become a candidate", not rep_under["candidates"])
    check("gate: sub-threshold signals are REPORTED, not silently dropped",
          rep_under["suppressed_count"] == 1)
    check("gate: the digest names what it suppressed",
          "SUPPRESSED by the gate: 1 signal" in render(rep_under))

    same_day = _obs_from_repos([{"full_name": "o/r", "checks": [
        {"name": "build", "conclusion": "failure", "head_sha": f"s{i}",
         "completed_at": _ago(hours=i)} for i in range(3)]}])
    check("gate: 3 occurrences in ONE context fail the distinct-context bar",
          not analyze(same_day, now=_NOW)["candidates"])

    # --- THE GATE CHANGE: recurrence counts DISTINCT items, not re-observations
    def _branch_obs(name, at, repo="o/r"):
        return {"ts": _iso(_NOW), "kind": "branch", "source_id": f"{repo}#{name}@{at}",
                "repo": repo, "at": at, "fields": {"name": name, "merged": False}}

    # One cold branch seen on 10 separate days is ONE abandoned branch.
    same_branch = [_branch_obs("feature/x", _ago(days=30 + i)) for i in range(10)]
    rep_same = analyze(same_branch, now=_NOW)
    sigs = rep_same["candidates"] + rep_same["suppressed"]
    ab = [x for x in sigs if x["rule"] == "abandoned_branch"][0]
    check("gate: one branch re-observed 10x counts as 1 occurrence",
          ab["occurrences"] == 1)
    check("gate: the raw observation count is kept, not erased",
          ab["observations"] == 10)
    check("gate: a single re-observed branch does NOT become a candidate",
          not rep_same["candidates"])

    # Guarded negative: genuinely distinct branches still count, and still gate in.
    many = [_branch_obs(f"feature/{i}", _ago(days=30 + i)) for i in range(4)]
    rep_many = analyze(many, now=_NOW)
    ab_many = [x for x in rep_many["candidates"] if x["rule"] == "abandoned_branch"]
    check("gate NEGATIVE: 4 DISTINCT cold branches still count as 4 and gate in",
          ab_many and ab_many[0]["occurrences"] == 4)

    # Event-shaped rules are unaffected — each failing check is its own identity.
    ev = _obs_from_repos([{"full_name": "o/r", "checks": [
        {"name": "ci", "conclusion": "failure", "head_sha": f"sha{i}",
         "completed_at": _ago(days=i)} for i in range(3)]}])
    ci = [x for x in analyze(ev, now=_NOW)["candidates"] if x["rule"] == "ci_failure_repeat"]
    check("gate: event rules keep their counts (3 distinct failures = 3)",
          ci and ci[0]["occurrences"] == 3)

    # Case normalization: the same repo under two spellings is ONE signal.
    mixed = ([_branch_obs("feature/a", _ago(days=30), repo="Bent40/Repo")]
             + [_branch_obs("feature/b", _ago(days=31), repo="bent40/repo")])
    keys = {x["key"] for x in analyze(mixed, now=_NOW)["suppressed"]
            + analyze(mixed, now=_NOW)["candidates"] if x["rule"] == "abandoned_branch"}
    check("gate: mixed-case repo names collapse to ONE signal", len(keys) == 1)

    # --- FROZEN: accepted, never silently hidden ------------------------------
    frz = frozenset({("abandoned_branch", "o/r#feature/0"),
                     ("abandoned_branch", "o/r#feature/1"),
                     ("abandoned_branch", "o/r#feature/2"),
                     ("abandoned_branch", "o/r#feature/3")})
    rep_frozen = analyze(many, now=_NOW, frozen=frz)
    check("frozen: accepted identities leave the candidate list",
          not [x for x in rep_frozen["candidates"] if x["rule"] == "abandoned_branch"])
    check("frozen: the count is REPORTED, not silently dropped",
          rep_frozen["frozen_count"] == 4
          and "abandoned_branch" in rep_frozen["frozen_rules"])
    check("frozen: the digest names the frozen count",
          "FROZEN (accepted, still tracked): 4" in render(rep_frozen))

    # The whole point of freezing by IDENTITY: a NEW branch still surfaces.
    plus_new = many + [_branch_obs("feature/BRAND-NEW", _ago(days=40))]
    rep_new = analyze(plus_new, now=_NOW, frozen=frz,
                      min_occurrences=1, min_contexts=1)
    fresh = [x for x in rep_new["candidates"] if x["rule"] == "abandoned_branch"]
    check("frozen NEGATIVE: a NEW identity still surfaces past the freeze",
          fresh and any("BRAND-NEW" in e for e in fresh[0]["evidence"]))
    check("frozen NEGATIVE: the frozen ones are not re-counted as new",
          fresh and fresh[0]["occurrences"] == 1)

    # A broken freeze file must never hide a finding.
    with tempfile.TemporaryDirectory() as tmp:
        ff = Path(tmp) / "frozen.jsonl"
        ff.write_text('{"rule":"abandoned_branch","identity":"o/r#feature/0"}\n'
                      'NOT JSON AT ALL\n'
                      '{"rule":"abandoned_branch"}\n', encoding="utf-8")
        loaded = load_frozen(ff)
        check("frozen file reads fail-OPEN (bad lines skipped, valid one kept)",
              loaded == frozenset({("abandoned_branch", "o/r#feature/0")}))
        check("frozen: an absent file freezes nothing",
              load_frozen(Path(tmp) / "nope.jsonl") == frozenset())

    # --- reachability: every rule must be able to BECOME a candidate ----------
    # A rule that fires but can never clear the gate is decorative — it reads as
    # coverage while contributing nothing. This is the test that caught
    # rework_file emitting one hit per file forever.
    reach_inputs = {
        "cost_outlier": _obs_from_sessions(
            [_sess(f"b{i}", out=100) for i in range(5)]
            + [_sess(f"o{i}", out=100_000) for i in range(3)]),
        "cache_inefficiency": _obs_from_sessions(
            [_sess(f"c{i}", cread=1, cwrite=100) for i in range(3)]),
        "effort_escalation": _obs_from_sessions(
            [_sess(f"e{i}", effort="max", out=100) for i in range(3)]),
        "stalled_session": _obs_from_sessions(
            [_sess(f"s{i}", status="session_status_running", updated=_ago(hours=48))
             for i in range(3)]),
        "rate_limit_pressure": _obs_from_sessions(
            [_sess(f"r{i}", rl="exceeded") for i in range(3)]),
        "revert_churn": _obs_from_repos([{"full_name": "o/r", "commits": [
            {"sha": f"v{i}", "message": "Revert bad change", "committed_at": _ago(days=i)}
            for i in range(3)]}]),
        "rework_file": _obs_from_repos([{"full_name": "o/r", "commits": [
            {"sha": f"w{b}{i}", "message": "wip", "files": ["a.py"],
             "committed_at": _ago(days=b * 40 + i)}
            for b in range(3) for i in range(3)]}]),
        "ci_failure_repeat": _obs_from_repos([{"full_name": "o/r", "checks": [
            {"name": "build", "conclusion": "failure", "head_sha": f"h{i}",
             "completed_at": _ago(days=i)} for i in range(3)]}]),
        "abandoned_branch": _obs_from_repos([{"full_name": "o/r", "branches": [
            {"name": f"b{i}", "merged": False, "updated_at": _ago(days=30 + i)}
            for i in range(3)]}]),
        "review_theme_repeat": _obs_from_repos([{"full_name": "o/r", "review_comments": [
            {"id": i, "body": "missing test for this branch", "created_at": _ago(days=i)}
            for i in range(3)]}]),
    }
    check("reachability fixtures cover every rule that has a reading",
          set(reach_inputs) == set(RULE_PROMPTS))
    for rule, observations in reach_inputs.items():
        candidates = {s["rule"] for s in analyze(observations, now=_NOW)["candidates"]}
        check(f"{rule} can actually reach CANDIDATE (not a decorative rule)",
              rule in candidates)

    # --- empty input is never a clean bill of health --------------------------
    empty = render(analyze([], now=_NOW))
    check("empty input is labelled EMPTY INPUT, not 'all clear'", "EMPTY INPUT" in empty)

    # --- normalizers are fail-open -------------------------------------------
    check("normalize_session rejects a record with no id", normalize_session({"title": "x"}, now=_NOW) is None)
    check("normalize_session rejects a non-dict", normalize_session("nope", now=_NOW) is None)
    check("normalize_repo_payload survives junk", normalize_repo_payload("nope", now=_NOW) == [])

    # --- ledger: idempotency, fail-open read, fail-closed check ---------------
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "obs.jsonl"
        sessions_file = Path(tmp) / "s.json"
        sessions_file.write_text(json.dumps({"sessions": [_sess("s1"), _sess("s2")]}), encoding="utf-8")
        args = argparse.Namespace(sessions=str(sessions_file), repos=None)
        cmd_ingest(args, ledger, now=_NOW)
        first, _ = read_ledger(ledger)
        cmd_ingest(args, ledger, now=_NOW)
        second, _ = read_ledger(ledger)
        check("ingest is idempotent (a daily re-run cannot inflate evidence)",
              len(first) == 2 and len(second) == 2)

        with ledger.open("a", encoding="utf-8") as fh:
            fh.write("{not json at all\n")
        recs, skipped = read_ledger(ledger)
        check("read_ledger fails OPEN on a malformed line", len(recs) == 2 and skipped == 1)
        rc = cmd_check(argparse.Namespace(), ledger, now=_NOW)
        check("check fails CLOSED on the same malformed line (exit 2)", rc == 2)

        clean = Path(tmp) / "clean.jsonl"
        append_ledger(clean, first)
        check("check passes on a clean ledger", cmd_check(argparse.Namespace(), clean, now=_NOW) == 0)

    # --- the digest must carry its own ephemerality warning -------------------
    warn = render(analyze(gated, now=_NOW))
    check("digest states it is ephemeral (D4a) and must not be committed",
          "ephemeral" in warn.lower() and "field-feedback-backlog.md" in warn)
    check("digest warns against routing into wf learn", "wf learn" in warn)

    # --- OPEN-WORK LANE: transitions, each with a guarded negative ------------
    def _ow(item_id, rnd, progress_days, *, refs=None, present=None, kind="pr"):
        return {"ts": _iso(_NOW), "round": rnd, "item_id": item_id, "repo": "o/r",
                "kind": kind, "title": item_id, "url": "",
                "opened_at": _ago(days=90), "last_progress_at": _ago(days=progress_days),
                "refs": refs or [], "refs_present": present}

    r1, r2 = "2026-08-18T00:00:00Z", "2026-08-19T00:00:00Z"

    # This lane must NOT be recurrence-gated: one sighting is actionable.
    first = openwork_delta([_ow("a", r1, 1)], now=_NOW)
    check("openwork: a single item surfaces immediately (no recurrence gate)",
          len(first["new"]) == 1)
    check("openwork: the first round says so instead of faking deltas", first["first_run"])

    # ADVANCED — and the negative: an item that did not move is not 'advanced'.
    moved = openwork_delta([_ow("a", r1, 10), _ow("a", r2, 1)], now=_NOW)
    check("openwork ADVANCED positive", len(moved["advanced"]) == 1)
    still = openwork_delta([_ow("a", r1, 10), _ow("a", r2, 10)], now=_NOW)
    check("openwork ADVANCED negative (no movement is not progress)",
          not still["advanced"] and still["unchanged"] == 1)

    # WENT STALER — crossing a band boundary, not merely aging within one.
    worse = openwork_delta([_ow("a", r1, 6), _ow("a", r2, 25)], now=_NOW)
    check("openwork WENT STALER positive (fresh -> stale)", len(worse["worsened"]) == 1)
    same_band = openwork_delta([_ow("a", r1, 1), _ow("a", r2, 5)], now=_NOW)
    check("openwork WENT STALER negative (aged but stayed in-band)",
          not same_band["worsened"])

    # RESOLVED — disappearing from the latest round is the good news case.
    gone = openwork_delta([_ow("a", r1, 5), _ow("b", r1, 5), _ow("b", r2, 5)], now=_NOW)
    check("openwork RESOLVED positive", len(gone["resolved"]) == 1
          and gone["resolved"][0]["item_id"] == "a")
    check("openwork RESOLVED negative (an item still present is not resolved)",
          all(i["item_id"] != "b" for i in gone["resolved"]))

    # NEWLY ORPHANED — transition only; an already-orphaned item is not re-flagged.
    orph = openwork_delta([_ow("a", r1, 5, refs=["x.py"], present=True),
                           _ow("a", r2, 5, refs=["x.py"], present=False)], now=_NOW)
    check("openwork NEWLY ORPHANED positive", len(orph["orphaned"]) == 1)
    already = openwork_delta([_ow("a", r1, 5, refs=["x.py"], present=False),
                              _ow("a", r2, 5, refs=["x.py"], present=False)], now=_NOW)
    check("openwork NEWLY ORPHANED negative (not re-flagged every day)",
          not already["orphaned"])

    # UNKNOWN must stay unknown — never quietly reported as live.
    unknown = _item_state(_ow("a", r1, 5, refs=["x.py"], present=None), now=_NOW)
    check("openwork: unchecked refs are UNKNOWN, not assumed live",
          unknown["relevance"] == "unknown")
    check("openwork: an item with no refs at all is live",
          _item_state(_ow("a", r1, 5), now=_NOW)["relevance"] == "live")

    # Staleness ladder boundaries are real thresholds, not decoration.
    check("openwork band ladder", (_band(0), _band(6), _band(7), _band(20),
                                   _band(21), _band(59), _band(60))
          == ("fresh", "fresh", "aging", "aging", "stale", "stale", "dormant"))

    # refs resolution against a real checkout: present, missing, and unchecked.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "here.py").write_text("x", encoding="utf-8")
        items = [_ow("a", r1, 1, refs=["here.py"]), _ow("b", r1, 1, refs=["gone.py"]),
                 _ow("c", r1, 1)]
        _resolve_refs(items, root)
        check("_resolve_refs marks an existing path present", items[0]["refs_present"] is True)
        check("_resolve_refs marks a vanished path absent", items[1]["refs_present"] is False)
        _resolve_refs(items, None)
        check("_resolve_refs leaves refs UNKNOWN when no root is given",
              items[2]["refs_present"] is None)

    # Inventory is collapsed, never dumped; the cap announces itself.
    many = ([_ow(f"i{i}", r1, 5) for i in range(30)]
            + [_ow(f"i{i}", r2, 5) for i in range(30)])
    rep_many = openwork_delta(many, now=_NOW)
    text_many = render_openwork(rep_many)
    check("openwork collapses unchanged items to a count, not a list",
          rep_many["unchanged"] == 30 and "unchanged since last round: 30" in text_many)
    big_new = openwork_delta([_ow(f"n{i}", r1, 5) for i in range(30)], now=_NOW)
    check("openwork caps long lists but SAYS it capped",
          "not a silent truncation" in render_openwork(big_new))
    check("openwork never asserts irrelevance, only evidence",
          "never a verdict" in render_openwork(orph))

    # --- cross-repo marker-body redaction, with guarded negatives -------------
    def _mk(repo, host=None):
        return normalize_openwork(
            {"full_name": repo, "markers": [
                {"key": "src/secret.py:42", "title": "TODO: swap the vendor auth token flow",
                 "refs": ["src/secret.py"], "last_progress_at": _ago(days=3)}],
             "branchs": [
                {"key": "feature/x", "title": "feature/x", "last_progress_at": _ago(days=3)}]},
            now=_NOW, round_id=r1, host_repo=host)

    foreign = {i["kind"]: i for i in _mk("o/other", host="o/host")}
    check("redaction: a cross-repo marker body is dropped",
          foreign["marker"]["title"] == "" and foreign["marker"]["redacted"] is True)
    check("redaction: the marker's PATH survives, so it stays actionable",
          foreign["marker"]["refs"] == ["src/secret.py"]
          and "src/secret.py:42" in foreign["marker"]["item_id"])
    check("redaction NEGATIVE: a cross-repo BRANCH keeps its name (only bodies go)",
          foreign["branch"]["title"] == "feature/x" and foreign["branch"]["redacted"] is False)

    same = {i["kind"]: i for i in _mk("o/host", host="o/host")}
    check("redaction NEGATIVE: the HOST repo's own marker body is kept",
          same["marker"]["title"].startswith("TODO: swap the vendor")
          and same["marker"]["redacted"] is False)

    nohost = {i["kind"]: i for i in _mk("o/other", host=None)}
    check("redaction NEGATIVE: no --host-repo means no redaction (opt-in)",
          nohost["marker"]["title"].startswith("TODO: swap the vendor"))

    # The live ledger stores repos lowercased while the canonical name is mixed
    # case; a case-sensitive host match would redact the host's OWN markers.
    cased = {i["kind"]: i for i in _mk("bent40/workflow", host="Bent40/Workflow")}
    check("redaction: host match is case-insensitive (ledger lowercases repo names)",
          cased["marker"]["redacted"] is False)

    red_text = render_openwork(openwork_delta([foreign["marker"]], now=_NOW))
    check("redaction is VISIBLE in the digest, not silent",
          "body withheld" in red_text)
    check("redaction: the digest shows the path in place of the body",
          "src/secret.py" in red_text)
    check("redaction: the withheld body never reaches the rendered output",
          "vendor auth token" not in red_text)

    # The open-work ledger honours the same fail-open / fail-closed split.
    with tempfile.TemporaryDirectory() as tmp:
        owl = Path(tmp) / "ow.jsonl"
        append_ledger(owl, [_ow("a", r1, 1)])
        with owl.open("a", encoding="utf-8") as fh:
            fh.write('{"ts":"x","round":"y"}\n')          # missing item_id/repo/kind
        recs, skipped = read_ledger(owl, required=REQUIRED_ITEM_FIELDS, kinds=OPENWORK_KINDS)
        check("open-work ledger reads fail-OPEN", len(recs) == 1 and skipped == 1)
        try:
            read_ledger(owl, strict=True, required=REQUIRED_ITEM_FIELDS, kinds=OPENWORK_KINDS)
            check("open-work ledger check fails CLOSED", False)
        except ValueError:
            check("open-work ledger check fails CLOSED", True)

    if ok:
        print("wf reflect selftest: PASS (10 rules each proven with a positive AND a "
              "guarded negative, AND proven reachable as a CANDIDATE so no rule is "
              "decorative — thresholds, word boundaries, time windows and terminal "
              "states all shown to matter; recurrence gate proven to admit 3-across-2 and "
              "reject both under-count and single-context; suppressed signals proven "
              "REPORTED not dropped; empty input labelled EMPTY INPUT not 'all clear'; "
              "ingest proven idempotent; ledger read fail-OPEN while check fails CLOSED; "
              "digest carries its own D4a ephemerality warning. OPEN-WORK lane: single "
              "sighting surfaces immediately with NO recurrence gate; advanced/staler/resolved/newly-orphaned each proven with a guarded negative; unchecked refs "
              "stay UNKNOWN; band ladder boundaries exact; inventory collapsed to a count "
              "and long lists announce their cap; fail-open/fail-closed split holds; "
              "cross-repo marker BODIES redacted while path/line survive, host-repo and "
              "non-marker items untouched, host match case-insensitive, redaction visible "
              "in the digest and the withheld body never reaching the output. GATE: recurrence "
              "counts DISTINCT identities — one branch re-observed 10x is 1 occurrence with the "
              "raw count kept, 4 distinct branches still count 4, event rules unchanged, "
              "mixed-case repos collapse to one signal; FROZEN identities leave the candidates "
              "but are REPORTED, a NEW identity still surfaces past the freeze, and a broken "
              "freeze file fails OPEN rather than hiding a finding)")
        return 0
    print("wf reflect selftest: FAIL", file=sys.stderr)
    return 1


# =============================================================================
# main
# =============================================================================

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="wf reflect",
        description="Recurrence-gated workflow-improvement candidates from observed "
                    "session metadata + repo activity (never conversation content).")
    ap.add_argument("--selftest", action="store_true", help="run the internal test suite")
    ap.add_argument("--file", help="observation ledger path (default _workflow/reflect/observations.jsonl)")
    sub = ap.add_subparsers(dest="action")

    p_ing = sub.add_parser("ingest", help="normalize + append observations (idempotent)")
    p_ing.add_argument("--sessions", help="JSON file of session metadata records")
    p_ing.add_argument("--repos", help="JSON file of repo activity records")

    for name, helptext in (("signals", "list every derived signal, gated or not"),
                           ("digest", "print the ephemeral DRAFT digest")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--frozen-file")
        p.add_argument("--min-occurrences", type=int, default=MIN_OCCURRENCES)
        p.add_argument("--min-contexts", type=int, default=MIN_CONTEXTS)
        p.add_argument("--json", action="store_true")

    p_track = sub.add_parser("track", help="record a round of OPEN WORK (not recurrence-gated)")
    p_track.add_argument("--repos", required=True, help="JSON file of open-work records")
    p_track.add_argument("--root", help="local checkout to resolve refs against "
                                        "(unchecked refs stay UNKNOWN, never assumed fine)")
    p_track.add_argument("--host-repo", help="the repo this ledger is committed into; "
                                             "marker BODIES from any other repo are redacted "
                                             "(path and line are kept)")

    p_open = sub.add_parser("openwork", help="delta report: what changed since the previous round")
    p_open.add_argument("--json", action="store_true")

    p_fr = sub.add_parser("freeze", help="accept a rule's CURRENT findings (by identity)")
    p_fr.add_argument("--rule", required=True)
    p_fr.add_argument("--key", help="narrow to one signal key (e.g. one repo)")
    p_fr.add_argument("--reason", help="why this is accepted — recorded with the entry")
    p_fr.add_argument("--frozen-file")

    p_uf = sub.add_parser("unfreeze", help="release frozen findings so they report again")
    p_uf.add_argument("--rule", required=True)
    p_uf.add_argument("--identity", help="release just this identity (default: all for the rule)")
    p_uf.add_argument("--frozen-file")

    sub.add_parser("check", help="fail-closed ledger validation")

    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.action:
        ap.error("an action (ingest|signals|digest|track|openwork|freeze|unfreeze|check) "
                 "or --selftest is required")

    ledger = Path(args.file) if args.file else Path(
        os.environ.get("WF_REFLECT_FILE", str(DEFAULT_LEDGER)))
    now = datetime.now(timezone.utc)

    if args.action == "ingest":
        if not args.sessions and not args.repos:
            raise SystemExit("wf reflect ingest: at least one of --sessions / --repos is required")
        return cmd_ingest(args, ledger, now=now)
    if args.action == "signals":
        return cmd_signals(args, ledger, now=now)
    if args.action == "digest":
        return cmd_digest(args, ledger, now=now)
    if args.action == "track":
        return cmd_track(args, Path(args.file) if args.file else Path(
            os.environ.get("WF_OPENWORK_FILE", str(DEFAULT_OPENWORK))), now=now)
    if args.action == "openwork":
        return cmd_openwork(args, Path(args.file) if args.file else Path(
            os.environ.get("WF_OPENWORK_FILE", str(DEFAULT_OPENWORK))), now=now)
    if args.action == "freeze":
        return cmd_freeze(args, ledger, now=now)
    if args.action == "unfreeze":
        return cmd_unfreeze(args, ledger, now=now)
    if args.action == "check":
        return cmd_check(args, ledger, now=now)
    return 2



# =============================================================================
# OPEN-WORK LANE — unfinished work, continuation tracking, staleness
#
# DELIBERATELY NOT RECURRENCE-GATED. The signals lane suppresses one-offs on
# purpose: a pattern is only worth acting on once it repeats. Unfinished work is
# the opposite — a single branch abandoned mid-refactor is actionable the first
# day it is seen, and running it through a ">=3 occurrences" gate would hide
# exactly what this lane exists to surface. Same tool, second ledger, different
# gate: a STALENESS LADDER plus DELTA reporting.
#
# WHY DELTAS, NOT INVENTORY. A daily "here are your 41 open items" is a nag list
# that gets skimmed and then ignored, and an ignored report is worse than none —
# it manufactures the feeling of oversight without the fact of it. This lane
# reports what CHANGED since the previous round and collapses everything else to
# a single unchanged count.
#
# HONESTY. The tool never asserts that work is irrelevant — that is a human
# judgement it has no standing to make. It reports the EVIDENCE ("all 3
# referenced paths no longer exist") and bands the age. Same contract as
# wf audit: UNVERIFIED is a flag to look, not a verdict.
# =============================================================================

DEFAULT_OPENWORK = REPO_ROOT / "_workflow" / "reflect" / "openwork.jsonl"

# Staleness ladder — idle days since the item last actually MOVED.
STALENESS_BANDS = (("fresh", 0), ("aging", 7), ("stale", 21), ("dormant", 60))
OPENWORK_KINDS = {"pr", "branch", "issue", "marker", "deferred"}
REQUIRED_ITEM_FIELDS = ("ts", "round", "item_id", "repo", "kind")


def _band(idle_days: float) -> str:
    band = STALENESS_BANDS[0][0]
    for name, threshold in STALENESS_BANDS:
        if idle_days >= threshold:
            band = name
    return band


def _band_rank(name: str) -> int:
    for idx, (band, _) in enumerate(STALENESS_BANDS):
        if band == name:
            return idx
    return 0


def normalize_openwork(raw: dict, *, now: datetime, round_id: str,
                       host_repo: str | None = None) -> list[dict]:
    """One repo's open-work payload -> item observations for this round.

    CROSS-REPO REDACTION: the ledger is committed into ONE repo but describes
    many. A marker's body is verbatim source text, so storing it for a foreign
    repo turns this ledger into a searchable index of other private codebases —
    an aggregation effect that grows daily and sidesteps the plugin leak gate,
    because the data arrives on a branch rather than through a build. When
    `host_repo` is set, markers from any OTHER repo keep their path and line
    (which is what you open) and lose their body. Nothing is silently dropped:
    the record is flagged `redacted` and the digest says so."""
    out: list[dict] = []
    if not isinstance(raw, dict):
        return out
    # Lowercased for the same reason as normalize_repo_payload: a mixed-case
    # full_name on one collection day used to fragment an item's identity
    # across rounds, making the openwork delta report spurious RESOLVED+NEW
    # pairs instead of a stable item_id.
    repo = (raw.get("full_name") or raw.get("repo") or "unknown").lower()
    foreign = bool(host_repo) and repo != str(host_repo).lower()
    for kind in sorted(OPENWORK_KINDS):
        for item in raw.get(kind + "s", []) or []:
            if not isinstance(item, dict):
                continue
            key = item.get("key", item.get("id", item.get("name", "")))
            if key is None or key == "":
                continue
            refs = [r for r in (item.get("refs") or []) if isinstance(r, str)]
            present = item.get("refs_present")
            redacted = foreign and kind == "marker"
            out.append({
                "ts": _iso(now), "round": round_id,
                "item_id": f"{repo}:{kind}:{key}", "repo": repo, "kind": kind,
                "redacted": redacted,
                "title": "" if redacted else str(item.get("title", "") or "")[:200],
                "url": item.get("url", "") or "",
                "opened_at": item.get("opened_at") or item.get("created_at") or "",
                "last_progress_at": item.get("last_progress_at")
                                    or item.get("updated_at") or item.get("opened_at") or "",
                "refs": refs,
                "refs_present": present if isinstance(present, bool) else None,
            })
    return out


def _resolve_refs(items: list[dict], root: Path | None) -> None:
    """Fill refs_present for items whose paths can be checked against a local
    checkout. Items from repos not present locally keep refs_present=None —
    UNKNOWN is reported as unknown, never silently as 'fine'."""
    if root is None:
        return
    for item in items:
        if not item["refs"] or item["refs_present"] is not None:
            continue
        item["refs_present"] = any((root / ref).exists() for ref in item["refs"])


def _item_state(obs: dict, *, now: datetime) -> dict:
    progressed = _parse_ts(obs.get("last_progress_at", ""))
    idle_days = (now - progressed).days if progressed else None
    band = _band(idle_days) if idle_days is not None else "unknown"
    if obs.get("refs") and obs.get("refs_present") is False:
        relevance = "orphaned"
    elif obs.get("refs") and obs.get("refs_present") is None:
        relevance = "unknown"
    else:
        relevance = "live"
    return {**obs, "idle_days": idle_days, "band": band, "relevance": relevance}


def openwork_delta(observations: list[dict], *, now: datetime) -> dict:
    """THE testable seam for this lane. Compares the newest observation round
    against the previous one and reports TRANSITIONS."""
    rounds: dict[str, dict[str, dict]] = {}
    for obs in observations:
        rounds.setdefault(obs["round"], {})[obs["item_id"]] = obs
    order = sorted(rounds)
    if not order:
        return {"rounds": 0, "first_run": True, "new": [], "advanced": [], "worsened": [],
                "orphaned": [], "resolved": [], "unchanged": 0, "open_total": 0}

    latest = {k: _item_state(v, now=now) for k, v in rounds[order[-1]].items()}
    previous = ({k: _item_state(v, now=now) for k, v in rounds[order[-2]].items()}
                if len(order) > 1 else {})

    new, advanced, worsened, orphaned, unchanged = [], [], [], [], 0
    for item_id, cur in sorted(latest.items()):
        prev = previous.get(item_id)
        if prev is None:
            new.append(cur)
            continue
        moved = (_parse_ts(cur.get("last_progress_at", "")) or datetime.min.replace(tzinfo=timezone.utc)) > \
                (_parse_ts(prev.get("last_progress_at", "")) or datetime.min.replace(tzinfo=timezone.utc))
        band_worse = _band_rank(cur["band"]) > _band_rank(prev["band"])
        now_orphaned = cur["relevance"] == "orphaned" and prev["relevance"] != "orphaned"
        if moved:
            advanced.append(cur)
        if band_worse:
            worsened.append(cur)
        if now_orphaned:
            orphaned.append(cur)
        if not (moved or band_worse or now_orphaned):
            unchanged += 1

    resolved = [previous[i] for i in sorted(previous) if i not in latest]
    return {
        "rounds": len(order), "first_run": len(order) == 1,
        "new": new, "advanced": advanced, "worsened": worsened,
        "orphaned": orphaned, "resolved": resolved,
        "unchanged": unchanged, "open_total": len(latest),
    }


def render_openwork(report: dict) -> str:
    out = ["wf reflect — open work (delta since the previous round)"]
    if report["rounds"] == 0:
        out.append("  no rounds recorded yet — run `wf reflect track` first.")
        return "\n".join(out)
    out.append(f"  {report['open_total']} item(s) open across {report['rounds']} recorded round(s)")
    if report["first_run"]:
        out.append("  FIRST ROUND — everything reads as new because there is nothing to")
        out.append("  compare against yet. Deltas become meaningful from the next run.")
    out.append("")

    def block(title: str, items: list[dict], detail) -> None:
        if not items:
            return
        out.append(f"{title} ({len(items)}):")
        for it in items[:20]:
            if it.get("redacted"):
                where = ", ".join(it.get("refs") or []) or it["item_id"].split(":", 2)[-1]
                label = f"{where}  (body withheld — cross-repo)"
            else:
                label = it.get("title") or it["item_id"]
            out.append(f"  - [{it['kind']}] {it['repo']} :: {label}")
            out.append(f"      {detail(it)}")
        if len(items) > 20:
            out.append(f"  ... and {len(items) - 20} more (capped at 20 — not a silent truncation)")
        out.append("")

    block("RESOLVED since last round", report["resolved"],
          lambda it: "no longer open — finished, merged, or closed")
    block("ADVANCED", report["advanced"],
          lambda it: f"moved; idle {it['idle_days']}d, band {it['band']}")
    block("WENT STALER", report["worsened"],
          lambda it: f"crossed into '{it['band']}' — idle {it['idle_days']}d")
    block("NEWLY ORPHANED (evidence, not a verdict)", report["orphaned"],
          lambda it: f"every referenced path is gone: {', '.join(it['refs'][:4])}")
    block("NEW", report["new"],
          lambda it: f"first seen; idle {it['idle_days']}d, band {it['band']}")

    out.append(f"unchanged since last round: {report['unchanged']}")
    out.append("")
    out.append("Orphaned/stale is EVIDENCE to judge, never a verdict that the work is")
    out.append("irrelevant. Close it, revive it, or say why it stays open.")
    return "\n".join(out)


def cmd_track(args, ledger: Path, *, now: datetime) -> int:
    payload = _load_json(Path(args.repos))
    raw_repos = payload.get("repos", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_repos, list):
        raise SystemExit("wf reflect track: --repos must hold a list (or {'repos': [...]})")
    round_id = _iso(now)
    items: list[dict] = []
    for raw in raw_repos:
        items.extend(normalize_openwork(raw, now=now, round_id=round_id,
                                        host_repo=getattr(args, "host_repo", None)))
    _resolve_refs(items, Path(args.root) if args.root else None)
    append_ledger(ledger, items)
    kinds: dict[str, int] = {}
    for it in items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())) or "nothing"
    n_red = sum(1 for i in items if i.get("redacted"))
    print(f"wf reflect track: recorded round {round_id} — {len(items)} open item(s) ({summary})")
    if n_red:
        print(f"  {n_red} cross-repo marker body/bodies redacted (path + line kept)")
    print(f"  ledger: {ledger}")
    return 0


def cmd_openwork(args, ledger: Path, *, now: datetime) -> int:
    observations, bad = read_ledger(ledger, required=REQUIRED_ITEM_FIELDS, kinds=OPENWORK_KINDS)
    report = openwork_delta(observations, now=now)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(render_openwork(report))
        if bad:
            print(f"\n({bad} malformed ledger line(s) skipped)")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
