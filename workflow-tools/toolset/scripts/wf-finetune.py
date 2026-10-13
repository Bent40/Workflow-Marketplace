#!/usr/bin/env python3
"""wf-finetune.py — the bridge that closes the orchestra → train → re-measure loop.

`wf orchestra baseline` MEASURES which skills a prompted small model fails
(classifying each PASS / NEEDS-FINETUNE / NO-EVALS / UNGRADED / ERROR);
`scripts/finetune_qlora.py` TRAINS a LoRA adapter on a chat-format SFT JSONL; and
re-running the baseline on the tuned adapter MEASURES the improvement. This tool
is the missing connective tissue between them:

    wf finetune prep    --from <orchestra-baseline> [--out <dir>] [--with-teacher]
    wf finetune run     --data <chat.jsonl> [--base <model>] [--steps N] [--dry-run]
    wf finetune compare --before <baseline> --after <baseline>
    wf finetune --selftest

THE LOOP
  baseline  →  prep        →  finetune_qlora.py  →  baseline (tuned)  →  compare
  (measure)    (training      (train — GPU/venv)     (re-measure)        (delta)
               scaffold)

HONESTY (non-negotiable — mirrors the repo's honesty gating, and the orchestra's):
  * SELECTION preserves the orchestra's verdict semantics. `prep` trains ONLY the
    skills the baseline classified NEEDS-FINETUNE. NO-EVALS is never invented an
    eval for; UNGRADED is NOT a NEEDS-FINETUNE (there was no measurement to fail);
    ERROR is NOT a PASS and is NOT trainable signal. PASS skills need no training.
    Everything excluded is LOGGED with the reason.
  * NO FABRICATED TRAINING LABELS. `prep` emits a SCAFFOLD: the user turns are the
    skills' real eval prompts, but the assistant target is EMPTY and clearly marked
    "to be filled by the teacher (distill_mini.py) or hand-authored — NOT
    fabricated". Good completions come from a TEACHER model or a human reference —
    never invented by this tool. `--with-teacher` fills them via distill_mini.py
    ONLY if a teacher endpoint is reachable; otherwise it FAILS CLOSED with guidance.
  * NO FAKE TRAINING RUN. `run` validates the JSONL is the shape finetune_qlora.py
    expects AND that no assistant slot is empty (it REFUSES to "train" on an unfilled
    scaffold). Actual training needs a GPU + the training venv; with neither it
    prints the EXACT command + env that WOULD run (`--dry-run`, the default when no
    GPU/venv is detected) — it never pretends a run happened.

The orchestra baseline is a Markdown report (what `wf orchestra baseline --out`
writes). `prep`/`compare` parse its per-skill table:
    | Skill | Family | #evals | Score | Verdict |
    | `skill-name` | family | 3 | 0.42 | NEEDS-FINETUNE |
A JSON baseline (a list of {name, verdict, score} records, or {"results": [...]})
is also accepted, so the loop works against either shape.

Exit codes: prep/compare -> 0 (success) / 2 (config/usage error).
            run -> 0 (dry-run printed, or real train succeeded) / 2 (refused:
            bad shape / empty assistant / no GPU without --dry-run / config error).
            selftest -> 0 / 1.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
FINETUNE_TRAINER = SCRIPTS / "finetune_qlora.py"
DISTILL_SCRIPT = SCRIPTS / "distill_mini.py"

# Optional private (org/box-specific) defaults: core/private/finetune.yaml, a flat
# `key: value` file that is never shipped. Present → its venv/teacher/legacy-env
# values apply; absent → the generic public defaults below. Shared with
# finetune_qlora.py and distill_mini.py (each reads the same file).
PRIVATE_FINETUNE_CFG = REPO_ROOT / "core" / "private" / "finetune.yaml"


def _load_private_cfg(path: Path = PRIVATE_FINETUNE_CFG) -> dict:
    cfg: dict = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return cfg
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        cfg[key.strip()] = val.strip().strip('"').strip("'")
    return cfg


_CFG = _load_private_cfg()


def _env(name: str, default: str) -> str:
    """`name` (a WF_* var) wins; else the private legacy-prefixed twin (the
    `legacy_env_prefix` key of the private config); else `default`."""
    if name in os.environ:
        return os.environ[name]
    legacy = _CFG.get("legacy_env_prefix", "")
    if legacy and name.startswith("WF_") and legacy + name[3:] in os.environ:
        return os.environ[legacy + name[3:]]
    return default


# The training venv the on-box trainer uses (mirrors finetune_qlora.py's docstring
# and distill_mini.py provisioning). Its presence is part of the readiness probe.
TRAIN_VENV = Path(os.path.expanduser(
    _env("WF_FT_VENV", _CFG.get("venv", "~/.wf-finetune/venv"))))

# Verdict labels — IDENTICAL to wf-orchestra.py's, so selection cannot drift from
# what the measurement harness wrote.
PASS = "PASS"
NEEDS = "NEEDS-FINETUNE"
NO_EVALS = "NO-EVALS"
UNGRADED = "UNGRADED"
ERROR = "ERROR"
ALL_VERDICTS = {PASS, NEEDS, NO_EVALS, UNGRADED, ERROR}

# The marker written into every empty assistant slot of a scaffold, so a half-built
# training set is unmistakable AND `run` can refuse it. Kept short so a teacher fill
# replaces the WHOLE content (never appends to it).
EMPTY_ASSISTANT_MARKER = (
    "<<TO BE FILLED BY THE TEACHER (distill_mini.py) OR HAND-AUTHORED — "
    "NOT FABRICATED BY wf finetune>>"
)

DEFAULT_BASE_MODEL = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
DEFAULT_STEPS = 30  # mirrors finetune_qlora.py's WF_FT_STEPS default

# The min length a rendered trajectory must reach to be a real training target.
# Mirrors _fill_with_teacher's len<80 skip: an empty-but-verified trace (blank
# stage content, only the proof footer) renders too thin to teach HOW to work, so
# it is SKIPPED (logged), never padded. Stage labels + a passing-signal footer keep
# any kept render well above whitespace.
TRACE_MIN_CONTENT = 80


# ── wf-trace.py: the SINGLE source of the verified-label decision ─────────────
# wf-finetune does NOT import wf-trace as a normal module — the filename is
# hyphenated, so a `import wf-trace` is impossible. We load it by path so that
# `compute_label` (and the constants it is defined against) are the SAME code the
# `wf trace export` path uses. This is deliberate: from-traces RE-VERIFIES every
# record with this exact function, so the two consumers cannot drift. If a future
# wf-trace refactor drops/renames compute_label, the selftest assertion below
# (and at import time, the AttributeError) fails LOUD rather than silently
# accepting an un-recomputed, possibly-fabricated label.
WF_TRACE_PY = SCRIPTS / "wf-trace.py"


def _load_wf_trace():
    """Load scripts/wf-trace.py by path and return its module. Fails loud if the
    file or the verified-decision symbol is absent (a future refactor catcher)."""
    spec = importlib.util.spec_from_file_location("wf_trace", WF_TRACE_PY)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the verified-label source: {WF_TRACE_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "compute_label"):
        raise ImportError(
            f"{WF_TRACE_PY} has no compute_label — the single source of the "
            f"verified-label decision is gone; refusing to grade traces without it")
    return mod


_WF_TRACE = _load_wf_trace()
# Pull the verified-decision API from wf-trace — re-homing any of these would
# split the source of truth, so they are referenced, never copied.
trace_compute_label = _WF_TRACE.compute_label
TRACE_EXECUTABLE_KINDS = _WF_TRACE.EXECUTABLE_KINDS
TRACE_REQUIRED_STAGES = _WF_TRACE.REQUIRED_STAGES
trace_exit = _WF_TRACE._exit


# ── orchestra baseline parsing ────────────────────────────────────────────────


class SkillVerdict:
    """One skill's row from an orchestra baseline."""

    def __init__(self, name: str, verdict: str, score: float | None,
                 n_evals: int | None = None):
        self.name = name
        self.verdict = verdict
        self.score = score
        self.n_evals = n_evals

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"SkillVerdict({self.name!r}, {self.verdict!r}, {self.score!r})"


# The orchestra per-skill table row. The verdict cell may carry a trailing HTML
# comment for ERROR rows (`... ERROR |<!-- detail -->`); the regex stops at the
# pipe so the comment never contaminates the verdict.
_ROW_RE = re.compile(
    r"^\|\s*`?(?P<name>[^|`]+?)`?\s*\|"      # Skill
    r"\s*(?P<family>[^|]*?)\s*\|"            # Family
    r"\s*(?P<nevals>[^|]*?)\s*\|"            # #evals
    r"\s*(?P<score>[^|]*?)\s*\|"             # Score
    r"\s*(?P<verdict>[A-Z][A-Z-]+)\b[^|]*\|",  # Verdict (UPPERCASE token)
    re.MULTILINE,
)


def _parse_score(cell: str) -> float | None:
    cell = (cell or "").strip()
    if cell in ("", "-", "—", "–"):
        return None
    try:
        return float(cell)
    except ValueError:
        return None


def _parse_int(cell: str) -> int | None:
    try:
        return int((cell or "").strip())
    except ValueError:
        return None


def parse_baseline(path: Path) -> list[SkillVerdict]:
    """Parse an orchestra baseline into per-skill verdicts.

    Accepts EITHER the Markdown report (the default `wf orchestra baseline --out`
    artifact — parsed via its per-skill table) OR a JSON baseline (a list of
    records, or an object with a "results"/"skills" list). Fails loud (ValueError)
    on an unreadable/empty file so a missing baseline never silently selects nothing.
    """
    if not path.is_file():
        raise ValueError(f"baseline not found: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        raise ValueError(f"baseline is empty: {path}")

    # Try JSON first (a stripped leading char of '{' or '[').
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            return _parse_json_baseline(json.loads(text), path)
        except (json.JSONDecodeError, ValueError):
            pass  # fall through to Markdown (a .md that happens to start with {)

    rows: list[SkillVerdict] = []
    seen: set[str] = set()
    for m in _ROW_RE.finditer(text):
        name = m.group("name").strip()
        verdict = m.group("verdict").strip()
        # Skip the table HEADER/separator rows: the header verdict cell is the
        # literal word "Verdict" (mixed case → not matched by the UPPERCASE token
        # rule), and separators are dashes — but guard explicitly anyway.
        if verdict not in ALL_VERDICTS:
            continue
        if name in ("Skill", "") or set(name) <= {"-", " ", ":"}:
            continue
        if name in seen:
            continue
        seen.add(name)
        rows.append(SkillVerdict(name, verdict, _parse_score(m.group("score")),
                                 _parse_int(m.group("nevals"))))
    if not rows:
        raise ValueError(
            f"no per-skill verdict rows found in {path} — is this an orchestra "
            f"baseline report (it must contain the per-skill table)?"
        )
    return rows


def _parse_json_baseline(data, path: Path) -> list[SkillVerdict]:
    if isinstance(data, dict):
        records = data.get("results") or data.get("skills") or data.get("per_skill")
        if records is None:
            raise ValueError(f"{path}: JSON object has no 'results'/'skills' list")
    else:
        records = data
    if not isinstance(records, list):
        raise ValueError(f"{path}: expected a list of skill records")
    rows: list[SkillVerdict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        name = rec.get("name") or rec.get("skill")
        verdict = rec.get("verdict")
        if not name or verdict not in ALL_VERDICTS:
            continue
        score = rec.get("score")
        rows.append(SkillVerdict(str(name), str(verdict),
                                 float(score) if isinstance(score, (int, float)) else None,
                                 rec.get("n_evals")))
    if not rows:
        raise ValueError(f"{path}: no valid skill records in JSON baseline")
    return rows


# ── eval-prompt discovery (the user turns) ────────────────────────────────────


def _skill_dir(name: str, skills_root: Path = SKILLS_DIR) -> Path:
    return skills_root / name


def load_eval_prompts(skill_name: str, *, skills_root: Path = SKILLS_DIR,
                      include_triggers: bool = False) -> list[tuple[str, str]]:
    """Return [(eval_id, prompt)] for a skill — its evals.json `prompt`s, and
    optionally its triggers.json `query`s. Mirrors the discovery wf-eval-coverage /
    wf-orchestra use (the colocated <skill>/evals/ layout, with a <skill>/ fallback).
    A malformed/missing eval file yields nothing (it is NOT a crash) — the caller
    notes a selected skill that produced zero prompts."""
    sd = _skill_dir(skill_name, skills_root)
    out: list[tuple[str, str]] = []
    for evals_json in (sd / "evals" / "evals.json", sd / "evals.json"):
        if not evals_json.is_file():
            continue
        try:
            data = json.loads(evals_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("evals"), list):
            for i, ev in enumerate(data["evals"]):
                if isinstance(ev, dict) and isinstance(ev.get("prompt"), str) \
                        and ev["prompt"].strip():
                    out.append((str(ev.get("id", f"eval-{i}")), ev["prompt"]))
        break  # first existing evals.json wins (don't double-count colocated)
    if include_triggers:
        for trig_json in (sd / "evals" / "triggers.json", sd / "triggers.json"):
            if not trig_json.is_file():
                continue
            try:
                data = json.loads(trig_json.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, list):
                for i, t in enumerate(data):
                    if isinstance(t, dict) and isinstance(t.get("query"), str) \
                            and t["query"].strip() and t.get("should_trigger"):
                        out.append((f"trigger-{i}", t["query"]))
            break
    return out


# ── prep ──────────────────────────────────────────────────────────────────────


def _scaffold_record(skill: str, eval_id: str, prompt: str,
                     assistant: str = EMPTY_ASSISTANT_MARKER) -> dict:
    """One training-set line. Assistant content is the EMPTY marker by default —
    filled only by a teacher / hand-author, NEVER fabricated here."""
    return {
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": assistant},
        ],
        "skill": skill,
        "source": eval_id,
    }


def build_scaffold(baseline_rows: list[SkillVerdict], *,
                   skills_root: Path = SKILLS_DIR,
                   include_triggers: bool = False
                   ) -> tuple[list[dict], list[str], dict[str, list[str]]]:
    """Select ONLY NEEDS-FINETUNE skills and build the scaffold records.

    Returns (records, selected_skill_names, excluded_by_reason). `excluded_by_reason`
    maps an exclusion reason -> [skill names], so prep can log exactly what was left
    out and WHY (the honesty requirement). A selected skill that yields zero prompts
    is reported (it cannot contribute training data)."""
    selected: list[str] = []
    excluded: dict[str, list[str]] = {}
    records: list[dict] = []

    def exclude(reason: str, name: str) -> None:
        excluded.setdefault(reason, []).append(name)

    for row in baseline_rows:
        if row.verdict == NEEDS:
            prompts = load_eval_prompts(row.name, skills_root=skills_root,
                                        include_triggers=include_triggers)
            if not prompts:
                exclude("NEEDS-FINETUNE but no eval prompts found (cannot train)",
                        row.name)
                continue
            selected.append(row.name)
            for eval_id, prompt in prompts:
                records.append(_scaffold_record(row.name, eval_id, prompt))
        elif row.verdict == PASS:
            exclude("PASS (model already passes — no training needed)", row.name)
        elif row.verdict == NO_EVALS:
            exclude("NO-EVALS (cannot measure — never invent an eval/target)", row.name)
        elif row.verdict == UNGRADED:
            exclude("UNGRADED (has evals but none checkable — NOT a NEEDS-FINETUNE)",
                    row.name)
        elif row.verdict == ERROR:
            exclude("ERROR (the measurement call failed — NOT a PASS, not trainable signal)",
                    row.name)
    return records, selected, excluded


def _write_plan(out_dir: Path, jsonl_path: Path, selected: list[str],
                excluded: dict[str, list[str]], records: list[dict],
                include_triggers: bool, with_teacher: bool) -> Path:
    plan = out_dir / "finetune-plan.md"
    per_skill: dict[str, int] = {}
    for rec in records:
        per_skill[rec["skill"]] = per_skill.get(rec["skill"], 0) + 1
    lines: list[str] = []
    lines.append("# Finetune plan")
    lines.append("")
    lines.append(
        "Generated by `wf finetune prep` from an orchestra baseline. It selects ONLY "
        "the skills the baseline classified **NEEDS-FINETUNE** and turns each one's "
        "eval prompts into the USER turns of a training-set SCAFFOLD. The assistant "
        "targets are **empty** and MUST be filled by a teacher (`distill_mini.py`) or "
        "hand-authored — they are **never fabricated** by this tool."
    )
    lines.append("")
    lines.append("## Selected skills (NEEDS-FINETUNE)")
    lines.append("")
    if selected:
        lines.append("| Skill | # training examples (scaffold) |")
        lines.append("|-------|-------------------------------:|")
        for s in selected:
            lines.append(f"| `{s}` | {per_skill.get(s, 0)} |")
    else:
        lines.append("_none — the baseline reported no trainable NEEDS-FINETUNE skills._")
    lines.append("")
    lines.append(f"- **Total scaffold examples:** {len(records)}")
    lines.append(f"- **Trigger queries included as user turns:** "
                 f"{'yes' if include_triggers else 'no'}")
    lines.append(f"- **Scaffold JSONL:** `{jsonl_path.name}` (assistant slots EMPTY"
                 f"{' — already teacher-filled' if with_teacher else ''})")
    lines.append("")
    lines.append("## Excluded (and why — honesty)")
    lines.append("")
    if excluded:
        for reason, names in excluded.items():
            lines.append(f"- **{reason}:** {', '.join(f'`{n}`' for n in names)}")
    else:
        lines.append("- (nothing excluded)")
    lines.append("")
    lines.append("## Next steps")
    lines.append("")
    lines.append(
        "1. **Fill the assistant targets.** Either run `wf finetune prep --with-teacher` "
        "(needs a reachable teacher endpoint — `distill_mini.py`), or hand-author a good "
        "reference completion for each user turn. Each assistant slot currently holds the "
        f"placeholder marker (`{EMPTY_ASSISTANT_MARKER[:40]}…`)."
    )
    lines.append(
        "2. **Train.** `wf finetune run --data " + jsonl_path.name + "` — it validates the "
        "filled JSONL and (on a GPU box with the training venv) invokes "
        "`scripts/finetune_qlora.py`; with no GPU it prints the exact command + env."
    )
    lines.append(
        "3. **Re-measure + compare.** Re-run `wf orchestra baseline` against the tuned "
        "adapter, then `wf finetune compare --before <baseline> --after <tuned-baseline>` "
        "to see which skills moved NEEDS-FINETUNE → PASS."
    )
    lines.append("")
    plan.write_text("\n".join(lines), encoding="utf-8")
    return plan


def _fill_with_teacher(records: list[dict]) -> tuple[list[dict], str | None]:
    """(Gated) Fill empty assistant slots via the teacher (distill_mini.py's
    endpoint). Returns (records, error) — on ANY teacher unavailability returns the
    UNCHANGED records and a non-None error string so prep FAILS CLOSED rather than
    leaving fabricated/blank targets. NEVER fabricates a target locally."""
    import urllib.error
    import urllib.request

    url = _env("WF_TEACHER_URL",
               _CFG.get("teacher_url", "http://localhost:11434")).rstrip("/")
    model = _env("WF_TEACHER_MODEL", _CFG.get("teacher_model", "gpt-oss:120b"))
    system = (
        "You are a senior expert. Answer the task with a concrete, well-structured, "
        "decisive response. No preamble or meta-commentary."
    )

    def _chat(task: str) -> str:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": task},
            ],
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 1024},
        }).encode()
        req = urllib.request.Request(
            f"{url}/api/chat", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read())
        return (body.get("message", {}) or {}).get("content", "") or ""

    # Probe the teacher first — fail closed if unreachable (no partial fabrication).
    try:
        probe = _chat("Reply with: ok")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return records, (
            f"teacher endpoint unreachable at {url} (model={model}): {exc}. "
            f"NOT fabricating targets. Set WF_TEACHER_URL / WF_TEACHER_MODEL "
            f"to a reachable teacher, or hand-author the assistant targets."
        )
    if not probe.strip():
        return records, f"teacher at {url} returned an empty probe response (fail closed)"

    filled: list[dict] = []
    for rec in records:
        user_turn = rec["messages"][0]["content"]
        try:
            ans = _chat(user_turn).strip()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return records, f"teacher call failed mid-fill: {exc} (fail closed)"
        if len(ans) < 80:
            # Honest: a too-short teacher answer is skipped, not padded.
            ans = EMPTY_ASSISTANT_MARKER
        new = dict(rec)
        new["messages"] = [rec["messages"][0], {"role": "assistant", "content": ans}]
        filled.append(new)
    return filled, None


def cmd_prep(args: argparse.Namespace) -> int:
    try:
        rows = parse_baseline(Path(args.__dict__["from"]).expanduser())
    except ValueError as exc:
        sys.stderr.write(f"wf finetune prep: {exc}\n")
        return 2

    records, selected, excluded = build_scaffold(
        rows, include_triggers=args.with_triggers)

    teacher_note = ""
    if args.with_teacher:
        if not records:
            sys.stderr.write(
                "wf finetune prep: --with-teacher requested but there are no "
                "NEEDS-FINETUNE training examples to fill.\n")
            return 2
        records, err = _fill_with_teacher(records)
        if err is not None:
            sys.stderr.write(f"wf finetune prep: --with-teacher FAILED CLOSED: {err}\n")
            return 2
        teacher_note = " (teacher-filled)"

    out_dir = Path(args.out).expanduser() if args.out else \
        Path(args.__dict__["from"]).expanduser().resolve().parent / "finetune-prep"
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "train-scaffold.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    plan = _write_plan(out_dir, jsonl_path, selected, excluded, records,
                       args.with_triggers, args.with_teacher)

    print(f"wf finetune prep: selected {len(selected)} NEEDS-FINETUNE skill(s); "
          f"{len(records)} training example(s){teacher_note}")
    for s in selected:
        n = sum(1 for r in records if r["skill"] == s)
        print(f"  + {s} ({n} examples)")
    if excluded:
        print("  excluded (honesty):")
        for reason, names in excluded.items():
            print(f"    - {reason}: {', '.join(names)}")
    print(f"wf finetune prep: wrote scaffold -> {jsonl_path}")
    print(f"wf finetune prep: wrote plan     -> {plan}")
    if not args.with_teacher and records:
        print("wf finetune prep: assistant targets are EMPTY — fill them via "
              "`--with-teacher` (distill_mini.py) or hand-authoring before `run`.")
    return 0


# ── from-traces (FILLED targets from VERIFIED process trails) ─────────────────
#
# The never-fabricate crux, stated verbatim so it cannot be lost in a refactor:
#   a prep scaffold's assistant is EMPTY because the good answer does not exist
#   yet; a from-traces assistant is FILLED because it is the externally-verified
#   trajectory — transcription of proven work, not fabrication.
#
# `wf finetune prep` turns a baseline's NEEDS-FINETUNE skills into EMPTY scaffolds
# (the good completion has to come from a teacher/human). `from-traces` is the
# COMPLEMENTARY positive-demonstration source: a `wf trace` process trail that
# PASSED executable ground truth already CONTAINS a known-good answer — the work
# that the passing tests/eval/etc. verified. Transcribing that proven trajectory
# into a training target is legitimate; inventing one is not. The two never
# collide: prep still drives the per-skill NEEDS-FINETUNE path; from-traces only
# adds verified positive demonstrations.


def _read_trace_records(traces: str) -> tuple[list[dict], str | None]:
    """Read `wf trace export` records from a file, a traces DIRECTORY, or stdin.

    - `-`            -> one JSON object per non-blank line on stdin.
    - a JSONL file   -> one JSON object per non-blank line.
    - a directory    -> each *.json trace file in the dir, RE-EXPORTED here via
                        wf-trace's own _export_record so the {trajectory, signals,
                        label, provenance} shape is identical and the label is
                        RECOMPUTED (never trusting a stored/upstream --verified-only).

    Returns (records, error). A non-None error is a config/usage failure (exit 2).
    Malformed lines are skipped (they cannot qualify) but do not abort the read."""
    if traces == "-":
        text = sys.stdin.read()
        return _parse_jsonl(text), None

    p = Path(traces).expanduser()
    if p.is_dir():
        # Recompute every trace ourselves — defense in depth: an upstream export's
        # --verified-only is NOT remembered, the directory is re-graded from source.
        recs: list[dict] = []
        for jf in sorted(p.glob("*.json")):
            try:
                trace = json.loads(jf.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(trace, dict):
                recs.append(_export_trace(trace))
        return recs, None
    if p.is_file():
        return _parse_jsonl(p.read_text(encoding="utf-8")), None
    return [], (f"--traces path not found: {p} (want a `wf trace export` JSONL, a "
                f"traces directory, or `-` for stdin)")


def _parse_jsonl(text: str) -> list[dict]:
    out: list[dict] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _export_trace(trace: dict) -> dict:
    """Re-derive an export record from a raw trace file using wf-trace's own
    recompute, so a directory input matches a `wf trace export` JSONL exactly."""
    label, reason = trace_compute_label(trace)
    return {
        "id": trace.get("id"),
        "task": trace.get("task"),
        "classification": trace.get("classification", {}),
        "trajectory": trace.get("stages", []),
        "signals": trace.get("signals", []),
        "label": label,
        "label_reason": reason,
        "provenance": "ground-truth-verified" if label == "verified" else label,
    }


def _passing_exec_signals(signals: list[dict]) -> list[dict]:
    """The PASSING executable signals — the externally-verified ground truth the
    trajectory rests on. review_gate is excluded (compute_label never lets it carry
    a label alone); a missing/non-int exit_code is fail-closed via trace_exit."""
    return [s for s in (signals or [])
            if s.get("kind") in TRACE_EXECUTABLE_KINDS and trace_exit(s) == 0]


def _render_trajectory(trajectory: list[dict], signals: list[dict]) -> str:
    """TRANSCRIPTION ONLY — a deterministic string build of the verified trajectory.

    NO LLM/teacher/model call, NO rewrite, NO invention. For each stage in order:
    a labeled section ('## implement\\n<content>  (artifacts: ...)'); then an
    evidence footer listing each PASSING executable signal as
    'Verified: <cmd> -> <summary> (exit 0)'. The footer is the proof that this is
    REAL work that passed executable ground truth — the crux distinguishing a
    from-traces target from prep's empty scaffold."""
    parts: list[str] = []
    for st in trajectory or []:
        stage = (st.get("stage") or "").strip()
        if not stage:
            continue
        content = (st.get("content") or "").strip()
        artifacts = st.get("artifacts") or []
        header = f"## {stage}"
        body = content
        if artifacts:
            art = ", ".join(str(a) for a in artifacts)
            body = (body + f"  (artifacts: {art})") if body else f"(artifacts: {art})"
        parts.append(f"{header}\n{body}".rstrip())
    passing = _passing_exec_signals(signals)
    if passing:
        footer = ["", "## verified"]
        for s in passing:
            cmd = (s.get("cmd") or s.get("kind") or "signal").strip()
            summary = (s.get("summary") or "").strip()
            arrow = f" -> {summary}" if summary else ""
            footer.append(f"Verified: {cmd}{arrow} (exit 0)")
        parts.append("\n".join(footer))
    return "\n\n".join(p for p in parts if p.strip()).strip()


def _traces_record(rec: dict, *, tag: str | None,
                   require_signal_kind: list[str] | None,
                   min_stages: list[str] | None,
                   classification_header: bool = True
                   ) -> tuple[dict | None, str | None]:
    """Map ONE export record -> one FILLED training example, or (None, reason) if
    it is excluded. DOES NOT TRUST the input: it RE-COMPUTES the label from the
    record's own trajectory+signals and accepts ONLY a recomputed `verified` whose
    provenance is `ground-truth-verified` (plus any stronger --require-signal-kind /
    --min-stages bar). The assistant target is the deterministic transcription of
    the verified trajectory — NEVER invented, NEVER the EMPTY_ASSISTANT_MARKER."""
    rid = rec.get("id") or "?"
    task = (rec.get("task") or "").strip()
    trajectory = rec.get("trajectory") or []
    signals = rec.get("signals") or []

    # 1. RE-VERIFY from scratch — the stored label / a pre-filtered export is NEVER
    #    trusted. compute_label needs >=1 passing executable signal, no failing one,
    #    and the required stages (implement+report); review_gate alone is insufficient.
    label, _reason = trace_compute_label({"stages": trajectory, "signals": signals})
    if label != "verified":
        return None, f"recomputed label is {label!r} (not verified) [{rid}]"
    if rec.get("provenance") != "ground-truth-verified":
        return None, (f"provenance {rec.get('provenance')!r} != 'ground-truth-verified' "
                      f"[{rid}]")

    # 2. Optional STRONGER bars.
    if require_signal_kind:
        present = {s.get("kind") for s in _passing_exec_signals(signals)}
        missing = [k for k in require_signal_kind if k not in present]
        if missing:
            return None, (f"missing required passing signal kind(s): "
                          f"{','.join(missing)} [{rid}]")
    if min_stages:
        have = {st.get("stage") for st in trajectory}
        missing_st = [s for s in min_stages if s not in have]
        if missing_st:
            return None, f"missing required stage(s): {','.join(missing_st)} [{rid}]"

    # 3. USER turn = the task verbatim (skip an empty task), optional classification
    #    header. ASSISTANT turn = the deterministic trajectory transcription.
    if not task:
        return None, f"empty task — nothing to learn from [{rid}]"
    user = task
    if classification_header:
        cls = rec.get("classification") or {}
        size = (cls.get("size") or "").strip()
        type_ = (cls.get("type") or "").strip()
        risk = cls.get("risk") or []
        bits = []
        if size:
            bits.append(f"{size} {type_}".strip() if type_ else size)
        elif type_:
            bits.append(type_)
        if risk:
            bits.append("risk: " + ",".join(str(r) for r in risk))
        if bits:
            user = f"[{'; '.join(bits)}]\n{task}"

    assistant = _render_trajectory(trajectory, signals)

    # 4. EMPTY-BUT-VERIFIED GUARD: a trace can be verified yet have blank stage
    #    content. If even the labels + proof footer render below the floor, SKIP it
    #    (logged) — never pad, never fabricate.
    if len(assistant) < TRACE_MIN_CONTENT:
        return None, (f"verified but rendered trajectory too thin "
                      f"({len(assistant)}<{TRACE_MIN_CONTENT} chars) — skipped, not "
                      f"padded [{rid}]")
    if EMPTY_ASSISTANT_MARKER in assistant:
        # Defensive: a transcription must NEVER contain the empty marker.
        return None, f"rendered assistant contained the empty marker [{rid}]"

    skill = tag or (rec.get("classification") or {}).get("type") or "trace"
    out = _scaffold_record(skill=str(skill), eval_id=f"trace:{rid}",
                           prompt=user, assistant=assistant)
    return out, None


def build_traces_scaffold(records: list[dict], *, tag: str | None = None,
                          require_signal_kind: list[str] | None = None,
                          min_stages: list[str] | None = None
                          ) -> tuple[list[dict], list[str], dict[str, list[str]]]:
    """Map verified-export records -> FILLED training examples. Returns the SAME
    (records, selected_ids, excluded_by_reason) tuple shape as build_scaffold, so
    the existing _write_plan renders selected/excluded-with-reasons verbatim."""
    out: list[dict] = []
    selected: list[str] = []
    excluded: dict[str, list[str]] = {}

    def exclude(reason: str, rid: str) -> None:
        excluded.setdefault(reason, []).append(rid)

    for rec in records:
        rid = str(rec.get("id") or "?")
        built, reason = _traces_record(
            rec, tag=tag, require_signal_kind=require_signal_kind,
            min_stages=min_stages)
        if built is None:
            exclude(reason or "excluded", rid)
            continue
        selected.append(rid)
        out.append(built)
    return out, selected, excluded


def _write_traces_plan(out_dir: Path, jsonl_path: Path, selected: list[str],
                       excluded: dict[str, list[str]], records: list[dict]) -> Path:
    """Render the from-traces plan. Reuses the selected/excluded structure so the
    honesty surface (what trained, what was excluded and WHY) is explicit."""
    plan = out_dir / "from-traces-plan.md"
    lines: list[str] = []
    lines.append("# Finetune from-traces plan")
    lines.append("")
    lines.append(
        "Generated by `wf finetune from-traces`. Each training example is one "
        "**externally-verified** `wf trace` process trail: the USER turn is the "
        "task, the ASSISTANT turn is a deterministic **transcription** of the "
        "verified trajectory (stages + the passing executable-signal proof). A "
        "prep scaffold's assistant is EMPTY because the good answer does not exist "
        "yet; a from-traces assistant is **FILLED** because it is the "
        "externally-verified trajectory — transcription of proven work, **not "
        "fabrication**. Every record was RE-VERIFIED here (the stored label is "
        "never trusted): a recomputed `verified` label + `ground-truth-verified` "
        "provenance is required to train."
    )
    lines.append("")
    lines.append("## Selected (verified traces -> FILLED training examples)")
    lines.append("")
    if selected:
        lines.append("| Trace id | assistant chars (transcribed) |")
        lines.append("|----------|------------------------------:|")
        by_src = {r["source"]: len(r["messages"][1]["content"]) for r in records}
        for sid in selected:
            lines.append(f"| `{sid}` | {by_src.get('trace:' + sid, 0)} |")
    else:
        lines.append("_none — no trace recomputed to a ground-truth-verified label._")
    lines.append("")
    lines.append(f"- **Total filled examples:** {len(records)}")
    lines.append("")
    lines.append("## Excluded (and why — honesty)")
    lines.append("")
    if excluded:
        for reason, ids in excluded.items():
            lines.append(f"- **{reason}:** {', '.join(f'`{n}`' for n in ids)}")
    else:
        lines.append("- (nothing excluded)")
    lines.append("")
    lines.append("## Next steps")
    lines.append("")
    lines.append(
        "1. **Train.** `wf finetune run --data " + jsonl_path.name + "` — it "
        "re-validates the FILLED JSONL (exactly-2-turns, user+assistant, NO "
        "empty/marker assistant) and, on a GPU box with the training venv, invokes "
        "`scripts/finetune_qlora.py`; with no GPU it prints the exact command + env."
    )
    lines.append(
        "2. **Re-measure.** Re-run `wf orchestra baseline` against the tuned adapter "
        "and `wf finetune compare` to see what moved."
    )
    lines.append("")
    plan.write_text("\n".join(lines), encoding="utf-8")
    return plan


def _csv_list(val: str | None) -> list[str] | None:
    if not val:
        return None
    items = [x.strip() for x in val.split(",") if x.strip()]
    return items or None


def cmd_from_traces(args: argparse.Namespace) -> int:
    # Default --traces source: explicit, else the traces dir ($WF_TRACE_DIR or
    # _workflow/traces), mirroring wf-trace's own default.
    traces_arg = args.traces
    if traces_arg is None:
        env_dir = os.environ.get("WF_TRACE_DIR")
        traces_arg = env_dir if env_dir else str(REPO_ROOT / "_workflow" / "traces")

    records_in, err = _read_trace_records(traces_arg)
    if err is not None:
        sys.stderr.write(f"wf finetune from-traces: {err}\n")
        return 2

    require_kind = _csv_list(getattr(args, "require_signal_kind", None))
    min_stages = _csv_list(getattr(args, "min_stages", None))
    # Validate any --require-signal-kind against the executable kinds (a typo would
    # silently exclude everything otherwise).
    if require_kind:
        bad = [k for k in require_kind if k not in TRACE_EXECUTABLE_KINDS]
        if bad:
            sys.stderr.write(
                f"wf finetune from-traces: --require-signal-kind has non-executable "
                f"kind(s) {','.join(bad)} (want a subset of "
                f"{','.join(TRACE_EXECUTABLE_KINDS)})\n")
            return 2

    out_records, selected, excluded = build_traces_scaffold(
        records_in, tag=args.tag, require_signal_kind=require_kind,
        min_stages=min_stages)

    # EMPTY CORPUS: fail loud (exit 2). Never write an empty JSONL.
    if not out_records:
        sys.stderr.write(
            "wf finetune from-traces: NO verified trace qualified — refusing to "
            "write an empty training set (fail loud).\n")
        if excluded:
            sys.stderr.write("  excluded (honesty):\n")
            for reason, ids in excluded.items():
                sys.stderr.write(f"    - {reason}: {', '.join(ids)}\n")
        else:
            sys.stderr.write(f"  (read 0 trace record(s) from {traces_arg})\n")
        return 2

    out_dir = Path(args.out).expanduser() if args.out else \
        (REPO_ROOT / "_workflow" / "finetune-from-traces")
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "train-from-traces.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for rec in out_records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    plan = _write_traces_plan(out_dir, jsonl_path, selected, excluded, out_records)

    print(f"wf finetune from-traces: {len(out_records)} FILLED example(s) from "
          f"{len(selected)} verified trace(s)")
    for sid in selected:
        print(f"  + trace:{sid}")
    if excluded:
        print("  excluded (honesty):")
        for reason, ids in excluded.items():
            print(f"    - {reason}: {', '.join(ids)}")
    print(f"wf finetune from-traces: wrote filled JSONL -> {jsonl_path}")
    print(f"wf finetune from-traces: wrote plan        -> {plan}")

    if args.run:
        print("wf finetune from-traces: --run -> handing the FILLED JSONL to "
              "`wf finetune run` (re-validates, then GPU-gated train/dry-run)…")
        run_args = argparse.Namespace(
            data=str(jsonl_path), base=args.base, steps=args.steps,
            dry_run=getattr(args, "dry_run", False))
        return cmd_run(run_args)

    print(f"wf finetune from-traces: next -> wf finetune run --data {jsonl_path}")
    return 0


# ── run ───────────────────────────────────────────────────────────────────────


def validate_training_jsonl(path: Path) -> tuple[int, list[str]]:
    """Validate `path` is the chat JSONL finetune_qlora.py expects, with NO empty
    assistant content. Returns (n_records, errors). A non-empty `errors` list means
    `run` must REFUSE (fail closed) — we never train on a malformed file or an
    unfilled scaffold."""
    errors: list[str] = []
    if not path.is_file():
        return 0, [f"data file not found: {path}"]
    n = 0
    n_empty = 0
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        n += 1
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"line {lineno}: invalid JSON: {exc}")
            continue
        msgs = rec.get("messages") if isinstance(rec, dict) else None
        if not isinstance(msgs, list) or not msgs:
            errors.append(f"line {lineno}: missing a non-empty 'messages' list")
            continue
        roles = [m.get("role") for m in msgs if isinstance(m, dict)]
        if "user" not in roles or "assistant" not in roles:
            errors.append(f"line {lineno}: messages must include a user AND an assistant turn")
        for m in msgs:
            if not isinstance(m, dict) or "role" not in m or "content" not in m:
                errors.append(f"line {lineno}: each message needs 'role' and 'content'")
                break
            if m.get("role") == "assistant":
                content = (m.get("content") or "").strip()
                if not content or EMPTY_ASSISTANT_MARKER in (m.get("content") or ""):
                    n_empty += 1
    if n == 0:
        errors.append("the JSONL has no records")
    if n_empty:
        errors.append(
            f"{n_empty} record(s) have an EMPTY/placeholder assistant target — refusing "
            f"to train on an unfilled scaffold. Fill assistant targets via a teacher "
            f"(distill_mini.py / `wf finetune prep --with-teacher`) or hand-authoring."
        )
    return n, errors


def probe_training_readiness() -> dict:
    """Mirror gpu_env_probe.py / the finetune scripts: detect a GPU (nvidia-smi),
    the training python modules (torch/unsloth/trl), and the provisioned training
    venv. Returns a dict used to decide dry-run vs real, and printed in the report."""
    gpu = None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            gpu = out.stdout.strip().splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError):
        gpu = None
    have_torch = importlib.util.find_spec("torch") is not None
    cuda = False
    if have_torch:
        try:
            import torch  # type: ignore[import-not-found]
            cuda = bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001
            cuda = False
    return {
        "gpu": gpu,
        "torch": have_torch,
        "unsloth": importlib.util.find_spec("unsloth") is not None,
        "trl": importlib.util.find_spec("trl") is not None,
        "cuda_available": cuda,
        "venv": TRAIN_VENV.is_dir(),
        "trainer": FINETUNE_TRAINER.is_file(),
    }


def _readiness_ok(rd: dict) -> bool:
    """A REAL training run needs: a GPU, the trainer script, and either the training
    modules importable here OR the provisioned training venv to run them in."""
    return bool(rd["gpu"] and rd["trainer"] and
                ((rd["torch"] and rd["unsloth"]) or rd["venv"]))


def _build_env_command(data: Path, base: str, steps: int) -> tuple[dict, list[str]]:
    """The EXACT env + command finetune_qlora.py would be invoked with."""
    env = {
        "WF_FT_DATA": str(data),
        "WF_FT_BASE": base,
        "WF_FT_STEPS": str(steps),
    }
    # Prefer the training venv's python when present; else the trainer's own shebang
    # python (the box's `python3`).
    venv_py = TRAIN_VENV / "bin" / "python"
    py = str(venv_py) if venv_py.is_file() else "python3"
    cmd = [py, str(FINETUNE_TRAINER)]
    return env, cmd


def cmd_run(args: argparse.Namespace) -> int:
    data = Path(args.data).expanduser()
    base = args.base or DEFAULT_BASE_MODEL
    steps = args.steps if args.steps is not None else DEFAULT_STEPS

    # 1. Shape + filled-assistant validation — fail closed on a scaffold.
    n, errors = validate_training_jsonl(data)
    if errors:
        sys.stderr.write("wf finetune run: REFUSING to train — the training data is "
                         "not valid (fail closed):\n")
        for e in errors:
            sys.stderr.write(f"  - {e}\n")
        return 2
    print(f"wf finetune run: validated {n} training record(s) "
          f"(chat shape OK, no empty assistant targets)")

    # 2. Readiness probe.
    rd = probe_training_readiness()
    print("wf finetune run: training readiness —")
    print(f"  GPU: {rd['gpu'] or 'NONE (nvidia-smi unavailable)'}")
    print(f"  torch: {'yes' if rd['torch'] else 'no'} "
          f"(cuda_available={rd['cuda_available']})  "
          f"unsloth: {'yes' if rd['unsloth'] else 'no'}  "
          f"trl: {'yes' if rd['trl'] else 'no'}")
    print(f"  training venv ({TRAIN_VENV}): {'present' if rd['venv'] else 'absent'}")
    print(f"  trainer script ({FINETUNE_TRAINER.name}): "
          f"{'present' if rd['trainer'] else 'MISSING'}")

    env, cmd = _build_env_command(data, base, steps)
    ready = _readiness_ok(rd)

    # 3. Dry-run (explicit, or the default when not ready) — print exact env+command.
    if args.dry_run or not ready:
        why = "(--dry-run requested)" if args.dry_run else \
            "(no GPU/training venv detected — defaulting to dry-run, NOT faking a run)"
        print(f"wf finetune run: DRY-RUN {why}. The command that WOULD train:")
        print("")
        env_str = " ".join(f"{k}={v}" for k, v in env.items())
        print(f"  {env_str} \\\n    {' '.join(cmd)}")
        print("")
        if not ready and not args.dry_run:
            print("wf finetune run: this box is NOT training-ready. To make it ready:")
            if not rd["gpu"]:
                print("  - a CUDA GPU is required (none found via nvidia-smi)")
            if not rd["venv"] and not (rd["torch"] and rd["unsloth"]):
                print(f"  - provision the training venv at {TRAIN_VENV} "
                      f"(torch + unsloth + trl), as finetune_qlora.py expects")
            if not rd["trainer"]:
                print(f"  - the trainer script is missing: {FINETUNE_TRAINER}")
            print("  Run on a self-hosted GPU runner; this is GPU/endpoint-gated by design.")
            # A requested-real run on a non-ready box is a fail-closed condition.
            return 2 if not args.dry_run else 0
        return 0

    # 4. Real training (GPU + venv present). Never reached in this container.
    print(f"wf finetune run: training-ready — invoking {FINETUNE_TRAINER.name} "
          f"(base={base}, steps={steps})")
    run_env = dict(os.environ)
    run_env.update(env)
    proc = subprocess.run(cmd, env=run_env)
    if proc.returncode != 0:
        sys.stderr.write(f"wf finetune run: trainer exited {proc.returncode}\n")
        return 2
    print("wf finetune run: training completed. Re-run `wf orchestra baseline` on the "
          "tuned adapter, then `wf finetune compare`.")
    return 0


# ── compare ───────────────────────────────────────────────────────────────────


def compare_baselines(before: list[SkillVerdict], after: list[SkillVerdict]) -> dict:
    """Diff two baselines by per-skill verdict. Returns the loop-outcome sets:
    improved (NEEDS-FINETUNE → PASS), regressed (PASS → NEEDS-FINETUNE), still-needs,
    new-pass-from-other, unchanged, plus per-skill mean-score deltas where both have
    a score, and the only-in-before / only-in-after skill names."""
    b = {r.name: r for r in before}
    a = {r.name: r for r in after}
    common = [n for n in a if n in b]

    improved: list[tuple[str, float | None, float | None]] = []
    regressed: list[tuple[str, float | None, float | None]] = []
    still_needs: list[str] = []
    unchanged: list[str] = []
    other_change: list[tuple[str, str, str]] = []
    score_deltas: list[tuple[str, float, float, float]] = []

    for name in sorted(common):
        bv, av = b[name].verdict, a[name].verdict
        if bv == NEEDS and av == PASS:
            improved.append((name, b[name].score, a[name].score))
        elif bv == PASS and av == NEEDS:
            regressed.append((name, b[name].score, a[name].score))
        elif bv == NEEDS and av == NEEDS:
            still_needs.append(name)
        elif bv == av:
            unchanged.append(name)
        else:
            other_change.append((name, bv, av))
        if b[name].score is not None and a[name].score is not None:
            score_deltas.append((name, b[name].score, a[name].score,
                                 a[name].score - b[name].score))

    measured_before = [r.score for r in before if r.score is not None]
    measured_after = [r.score for r in after if r.score is not None]
    mean_before = (sum(measured_before) / len(measured_before)
                   if measured_before else None)
    mean_after = (sum(measured_after) / len(measured_after)
                  if measured_after else None)

    return {
        "improved": improved,
        "regressed": regressed,
        "still_needs": still_needs,
        "unchanged": unchanged,
        "other_change": other_change,
        "score_deltas": score_deltas,
        "only_before": sorted(n for n in b if n not in a),
        "only_after": sorted(n for n in a if n not in b),
        "mean_before": mean_before,
        "mean_after": mean_after,
    }


def _fmt(s: float | None) -> str:
    return "—" if s is None else f"{s:.2f}"


def render_compare(diff: dict) -> str:
    lines: list[str] = []
    lines.append("wf finetune compare — orchestra baseline delta (the loop outcome)")
    lines.append("=" * 64)
    lines.append("")
    lines.append(f"IMPROVED  (NEEDS-FINETUNE → PASS): {len(diff['improved'])}")
    for name, bs, as_ in diff["improved"]:
        lines.append(f"  ✓ {name}  ({_fmt(bs)} → {_fmt(as_)})")
    lines.append(f"REGRESSED (PASS → NEEDS-FINETUNE): {len(diff['regressed'])}")
    for name, bs, as_ in diff["regressed"]:
        lines.append(f"  ✗ {name}  ({_fmt(bs)} → {_fmt(as_)})")
    lines.append(f"STILL NEEDS-FINETUNE: {len(diff['still_needs'])}")
    for name in diff["still_needs"]:
        lines.append(f"  · {name}")
    lines.append(f"UNCHANGED (same verdict): {len(diff['unchanged'])}")
    if diff["other_change"]:
        lines.append(f"OTHER verdict changes: {len(diff['other_change'])}")
        for name, bv, av in diff["other_change"]:
            lines.append(f"  ~ {name}  ({bv} → {av})")
    if diff["only_before"]:
        lines.append(f"only in BEFORE (dropped): {', '.join(diff['only_before'])}")
    if diff["only_after"]:
        lines.append(f"only in AFTER (added): {', '.join(diff['only_after'])}")
    lines.append("")
    lines.append("Mean measured score (graded skills): "
                 f"{_fmt(diff['mean_before'])} → {_fmt(diff['mean_after'])}"
                 + (f"  (Δ {diff['mean_after'] - diff['mean_before']:+.2f})"
                    if diff["mean_before"] is not None
                    and diff["mean_after"] is not None else ""))
    lines.append("")
    movers = [d for d in diff["score_deltas"] if abs(d[3]) >= 0.005]
    if movers:
        lines.append("Per-skill score deltas (skills scored in both):")
        for name, bs, as_, d in sorted(movers, key=lambda x: -x[3]):
            lines.append(f"  {name}: {bs:.2f} → {as_:.2f}  ({d:+.2f})")
        lines.append("")
    if diff["improved"]:
        lines.append("LOOP OUTCOME: the fine-tune moved "
                     f"{len(diff['improved'])} skill(s) from NEEDS-FINETUNE to PASS.")
    elif diff["regressed"]:
        lines.append("LOOP OUTCOME: NO improvement; "
                     f"{len(diff['regressed'])} skill(s) REGRESSED — investigate.")
    else:
        lines.append("LOOP OUTCOME: no verdict changed between the two baselines.")
    return "\n".join(lines)


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        before = parse_baseline(Path(args.before).expanduser())
        after = parse_baseline(Path(args.after).expanduser())
    except ValueError as exc:
        sys.stderr.write(f"wf finetune compare: {exc}\n")
        return 2
    diff = compare_baselines(before, after)
    print(render_compare(diff))
    return 0


# ── selftest (synthetic fixtures, NO GPU, NO endpoint) ────────────────────────


def _synthetic_baseline_md() -> str:
    """An orchestra-baseline-shaped Markdown report with a mix of verdicts, in the
    EXACT per-skill table format wf-orchestra renders."""
    return (
        "# Orchestra baseline report\n\n"
        "## Model under test\n\n- **Model name:** `qwen2.5:7b`\n\n"
        "## Per-skill\n\n"
        "| Skill | Family | #evals | Score | Verdict |\n"
        "|-------|--------|-------:|------:|---------|\n"
        "| `self-needs-a` | design | 2 | 0.40 | NEEDS-FINETUNE |\n"
        "| `self-needs-b` | test | 3 | 0.55 | NEEDS-FINETUNE |\n"
        "| `self-pass` | planning | 2 | 0.95 | PASS |\n"
        "| `self-noevals` | other | 0 | — | NO-EVALS |\n"
        "| `self-ungraded` | other | 1 | — | UNGRADED |\n"
        "| `self-error` | other | 1 | — | ERROR |<!-- endpoint blip -->\n"
        "\n"
    )


def _write_self_skills(root: Path) -> None:
    """Two NEEDS-FINETUNE skills with real evals.json prompts; the others have no
    discoverable prompts (so even if selection were wrong they could not train)."""
    for name, prompts in (
        ("self-needs-a", ["Design the empty state for a new chat workspace."]),
        ("self-needs-b", ["Write a test plan for the login flow.",
                          "Write an edge-case test for pagination."]),
    ):
        d = root / name / "evals"
        d.mkdir(parents=True)
        evals = {"skill_name": name,
                 "evals": [{"id": f"{name}-{i}", "prompt": p}
                           for i, p in enumerate(prompts)]}
        (d / "evals.json").write_text(json.dumps(evals), encoding="utf-8")


def selftest() -> int:
    problems: list[str] = []

    with tempfile.TemporaryDirectory(prefix="wf-finetune-self-") as td:
        tmp = Path(td)
        skills_root = tmp / "skills"
        skills_root.mkdir()
        _write_self_skills(skills_root)

        # ── parse_baseline (Markdown) selects the right rows ──
        bl = tmp / "baseline.md"
        bl.write_text(_synthetic_baseline_md(), encoding="utf-8")
        rows = parse_baseline(bl)
        by = {r.name: r for r in rows}
        if set(by) != {"self-needs-a", "self-needs-b", "self-pass",
                       "self-noevals", "self-ungraded", "self-error"}:
            problems.append(f"parse_baseline parsed wrong skills: {sorted(by)}")
        if by.get("self-needs-a") and by["self-needs-a"].verdict != NEEDS:
            problems.append("parse_baseline mis-read a NEEDS-FINETUNE verdict")
        if by.get("self-error") and by["self-error"].verdict != ERROR:
            problems.append("parse_baseline mis-read the ERROR verdict (HTML comment leak?)")
        if by.get("self-needs-a") and by["self-needs-a"].score != 0.40:
            problems.append(f"parse_baseline mis-read score: {by['self-needs-a'].score}")

        # ── prep selects ONLY NEEDS-FINETUNE; excludes the rest WITH reasons ──
        records, selected, excluded = build_scaffold(rows, skills_root=skills_root)
        if set(selected) != {"self-needs-a", "self-needs-b"}:
            problems.append(f"prep selected wrong skills: {selected} "
                            f"(must be ONLY NEEDS-FINETUNE)")
        for forbidden in ("self-pass", "self-noevals", "self-ungraded", "self-error"):
            if forbidden in selected:
                problems.append(f"prep WRONGLY selected {forbidden} (honesty violation)")
        # Excluded reasons must cover PASS, NO-EVALS, UNGRADED, ERROR.
        excluded_names = {n for names in excluded.values() for n in names}
        for required in ("self-pass", "self-noevals", "self-ungraded", "self-error"):
            if required not in excluded_names:
                problems.append(f"prep did not log {required} as excluded")
        if len(records) != 3:  # 1 + 2 prompts
            problems.append(f"prep produced {len(records)} records, expected 3")

        # ── scaffold shape: messages[user,assistant], assistant EMPTY + marked ──
        for rec in records:
            msgs = rec.get("messages")
            if not (isinstance(msgs, list) and len(msgs) == 2):
                problems.append(f"scaffold record has wrong messages: {rec}")
                continue
            if msgs[0]["role"] != "user" or not msgs[0]["content"].strip():
                problems.append("scaffold user turn missing/empty")
            if msgs[1]["role"] != "assistant":
                problems.append("scaffold second turn is not assistant")
            if msgs[1]["content"] != EMPTY_ASSISTANT_MARKER:
                problems.append("scaffold assistant target is NOT the empty marker "
                                "(must not be fabricated/filled by prep)")
            if "skill" not in rec or "source" not in rec:
                problems.append("scaffold record missing skill/source provenance")

        # ── run: REFUSES the empty scaffold (fail closed) ──
        scaffold_jsonl = tmp / "scaffold.jsonl"
        with scaffold_jsonl.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        n, errs = validate_training_jsonl(scaffold_jsonl)
        if not errs:
            problems.append("validate_training_jsonl ACCEPTED an empty-assistant "
                            "scaffold (must fail closed)")
        elif not any("EMPTY/placeholder assistant" in e for e in errs):
            problems.append(f"validate did not flag the empty assistant slots: {errs}")

        # run --dry-run on the scaffold must REFUSE (exit 2).
        rc = cmd_run(argparse.Namespace(data=str(scaffold_jsonl), base=None,
                                        steps=None, dry_run=True))
        if rc == 0:
            problems.append("run --dry-run on an EMPTY scaffold returned 0 "
                            "(must refuse with exit 2)")

        # ── run: ACCEPTS a filled fixture, dry-run prints the command, NO training ──
        filled = tmp / "filled.jsonl"
        with filled.open("w", encoding="utf-8") as fh:
            for rec in records:
                good = dict(rec)
                good["messages"] = [rec["messages"][0],
                                    {"role": "assistant",
                                     "content": "A concrete, well-structured answer "
                                                "to the task, long enough to be real."}]
                fh.write(json.dumps(good) + "\n")
        n2, errs2 = validate_training_jsonl(filled)
        if errs2:
            problems.append(f"validate REJECTED a properly filled JSONL: {errs2}")
        rc2 = cmd_run(argparse.Namespace(data=str(filled), base="my-base",
                                         steps=5, dry_run=True))
        if rc2 != 0:
            problems.append(f"run --dry-run on a FILLED fixture returned {rc2}, expected 0")

        # ── validate also rejects malformed JSON + shape errors ──
        bad = tmp / "bad.jsonl"
        bad.write_text('{not json}\n{"messages": []}\n'
                       '{"messages": [{"role": "user", "content": "x"}]}\n',
                       encoding="utf-8")
        _, bad_errs = validate_training_jsonl(bad)
        if len(bad_errs) < 2:
            problems.append(f"validate did not catch malformed/shape errors: {bad_errs}")

        # ── compare: improved / regressed / unchanged on synthetic before/after ──
        before = [
            SkillVerdict("a", NEEDS, 0.40), SkillVerdict("b", NEEDS, 0.50),
            SkillVerdict("c", PASS, 0.90), SkillVerdict("d", PASS, 0.88),
            SkillVerdict("e", NO_EVALS, None),
        ]
        after = [
            SkillVerdict("a", PASS, 0.90),   # improved
            SkillVerdict("b", NEEDS, 0.62),  # still needs (score up)
            SkillVerdict("c", PASS, 0.92),   # unchanged
            SkillVerdict("d", NEEDS, 0.40),  # regressed
            SkillVerdict("e", NO_EVALS, None),
        ]
        diff = compare_baselines(before, after)
        if [x[0] for x in diff["improved"]] != ["a"]:
            problems.append(f"compare improved set wrong: {diff['improved']}")
        if [x[0] for x in diff["regressed"]] != ["d"]:
            problems.append(f"compare regressed set wrong: {diff['regressed']}")
        if diff["still_needs"] != ["b"]:
            problems.append(f"compare still_needs wrong: {diff['still_needs']}")
        if "c" not in diff["unchanged"]:
            problems.append(f"compare unchanged set wrong: {diff['unchanged']}")
        # score-delta for 'a' must be +0.50
        a_delta = next((d for d in diff["score_deltas"] if d[0] == "a"), None)
        if a_delta is None or abs(a_delta[3] - 0.50) > 1e-9:
            problems.append(f"compare score-delta for 'a' wrong: {a_delta}")
        rendered = render_compare(diff)
        for needle in ("IMPROVED", "REGRESSED", "LOOP OUTCOME", "Mean measured score"):
            if needle not in rendered:
                problems.append(f"compare render missing {needle!r}")

        # ── parse_baseline also accepts a JSON baseline ──
        jbl = tmp / "baseline.json"
        jbl.write_text(json.dumps({"results": [
            {"name": "jx", "verdict": NEEDS, "score": 0.3},
            {"name": "jy", "verdict": PASS, "score": 0.9},
        ]}), encoding="utf-8")
        jrows = {r.name: r.verdict for r in parse_baseline(jbl)}
        if jrows != {"jx": NEEDS, "jy": PASS}:
            problems.append(f"JSON baseline parse wrong: {jrows}")

        # ── parse_baseline fails loud on an empty/garbage file ──
        empty = tmp / "empty.md"
        empty.write_text("no table here at all\n", encoding="utf-8")
        try:
            parse_baseline(empty)
            problems.append("parse_baseline did not fail on a baseline with no table")
        except ValueError:
            pass

        # ════════════════════════════════════════════════════════════════════
        #  from-traces teeth (synthetic export records — NO GPU, NO endpoint)
        # ════════════════════════════════════════════════════════════════════

        # MUST-HOLD 6: the verified-decision source is loaded. If compute_label is
        # absent (a future wf-trace refactor), fail LOUD here.
        if not callable(trace_compute_label):
            problems.append("from-traces: compute_label not loaded from wf-trace "
                            "(the single source of the verified decision is gone)")

        def _export_rec(rid, task, stages, signals, *, cls=None,
                        label=None, provenance=None):
            """Build a `wf trace export`-shaped record. label/provenance default to
            the RECOMPUTED ground truth (so a default record is honest); a test can
            override them to prove the recompute, not the stored value, decides."""
            trajectory = [{"stage": s, "ts": "t", "content": c, "artifacts": a}
                          for (s, c, a) in stages]
            comp, _ = trace_compute_label({"stages": trajectory, "signals": signals})
            rec = {
                "id": rid, "task": task,
                "classification": cls or {"size": "small", "type": "change", "risk": []},
                "trajectory": trajectory, "signals": signals,
                "label": label if label is not None else comp,
                "label_reason": "synthetic",
                "provenance": provenance if provenance is not None
                else ("ground-truth-verified" if comp == "verified" else comp),
            }
            return rec

        verified_rec = _export_rec(
            "ft-good", "add retry to the uploader",
            [("plan", "decide on backoff", []),
             ("implement", "added exponential backoff retry", ["uploader.py"]),
             ("test", "ran the suite", []),
             ("report", "done — retries on 5xx", [])],
            [{"kind": "tests", "cmd": "pytest", "exit_code": 0, "summary": "12 passed"}])

        failed_rec = _export_rec(
            "ft-failed", "break the uploader",
            [("implement", "introduced a bug", []), ("report", "oops", [])],
            [{"kind": "tests", "cmd": "pytest", "exit_code": 1, "summary": "3 failed"}])

        nosig_rec = _export_rec(
            "ft-nosig", "no executable proof",
            [("implement", "did something", []), ("report", "claims done", [])],
            [])  # no executable signal -> unverified

        # (1) a verified trace renders to a non-empty, MARKER-FREE assistant that
        #     validate_training_jsonl ACCEPTS.
        ftrecs, ftsel, ftexc = build_traces_scaffold([verified_rec])
        if ftsel != ["ft-good"]:
            problems.append(f"from-traces(1): verified trace not selected: {ftsel}")
        if len(ftrecs) != 1:
            problems.append(f"from-traces(1): expected 1 filled record, got {len(ftrecs)}")
        else:
            asst = ftrecs[0]["messages"][1]["content"]
            usr = ftrecs[0]["messages"][0]["content"]
            if not asst.strip():
                problems.append("from-traces(1): assistant target is empty")
            # MUST-HOLD 5 + assistant-is-transcription: the proof footer + stages
            # are present (deterministic transcription, not a teacher call).
            if "Verified:" not in asst or "## implement" not in asst:
                problems.append("from-traces(1): assistant missing trajectory "
                                "transcription / verified footer")
            if "add retry to the uploader" not in usr:
                problems.append("from-traces(1): user turn is not the task verbatim")
            if ftrecs[0]["source"] != "trace:ft-good":
                problems.append(f"from-traces(1): wrong source {ftrecs[0]['source']!r}")
            # MUST-HOLD 3: byte-compatible with validate_training_jsonl (downstream
            # re-gate). Write + validate it.
            ftjsonl = tmp / "from-traces.jsonl"
            with ftjsonl.open("w", encoding="utf-8") as fh:
                for r in ftrecs:
                    fh.write(json.dumps(r) + "\n")
            n_ft, ft_errs = validate_training_jsonl(ftjsonl)
            if ft_errs:
                problems.append(f"from-traces(3): validate REJECTED a filled trace "
                                f"record: {ft_errs}")
            # route through cmd_run --dry-run (the unchanged downstream) -> 0, no train
            rc_ft = cmd_run(argparse.Namespace(data=str(ftjsonl), base=None,
                                               steps=None, dry_run=True))
            if rc_ft != 0:
                problems.append(f"from-traces(3): cmd_run --dry-run on filled traces "
                                f"returned {rc_ft}, expected 0")

        # (5) the rendered assistant NEVER equals/contains EMPTY_ASSISTANT_MARKER.
        for r in ftrecs:
            if EMPTY_ASSISTANT_MARKER in r["messages"][1]["content"]:
                problems.append("from-traces(5): rendered assistant contains the "
                                "EMPTY_ASSISTANT_MARKER (must never happen)")

        # (2) a failed / unverified / no-signal trace is EXCLUDED-with-reason.
        _, sel2, exc2 = build_traces_scaffold([failed_rec, nosig_rec])
        if sel2:
            problems.append(f"from-traces(2): a failed/unverified trace was SELECTED: "
                            f"{sel2}")
        exc2_ids = {i for ids in exc2.values() for i in ids}
        if "ft-failed" not in exc2_ids or "ft-nosig" not in exc2_ids:
            problems.append(f"from-traces(2): failed/unverified not excluded: {exc2}")

        # (3-recompute) MUST-HOLD 1: a record whose STORED label says 'verified' but
        # whose signals are STRIPPED recomputes to unverified -> EXCLUDED. This proves
        # the RECOMPUTE decides, not the stored label / a pre-filtered export.
        liar = _export_rec(
            "ft-liar", "claims verified, no signal",
            [("implement", "x", []), ("report", "y", [])],
            [],  # NO signal — but we lie in the stored fields:
            label="verified", provenance="ground-truth-verified")
        _, sel3, exc3 = build_traces_scaffold([liar])
        if sel3:
            problems.append("from-traces(1/recompute): a stored-'verified'-but-"
                            "recomputes-unverified trace was SELECTED (trusted the "
                            "stored label instead of recomputing)")
        if "ft-liar" not in {i for ids in exc3.values() for i in ids}:
            problems.append("from-traces(1/recompute): the lying record was not excluded")

        # (4) a DIRECTORY input is RE-GRADED, not trusted. Write raw trace files
        #     (stages/signals, no export wrapper) and read via _read_trace_records:
        #     a genuine verified one qualifies, a signal-stripped liar does not.
        tdir = tmp / "tracedir"
        tdir.mkdir()
        (tdir / "good.json").write_text(json.dumps({
            "id": "dir-good", "task": "directory verified trace",
            "classification": {"size": "small", "type": "fix", "risk": []},
            "stages": [{"stage": "implement",
                        "content": "fixed the off-by-one in the pager loop",
                        "artifacts": ["pager.py"]},
                       {"stage": "report",
                        "content": "verified the boundary case is handled",
                        "artifacts": []}],
            "signals": [{"kind": "tests", "cmd": "pytest", "exit_code": 0,
                         "summary": "ok"}],
            "label": "verified"}), encoding="utf-8")
        (tdir / "liar.json").write_text(json.dumps({
            "id": "dir-liar", "task": "directory liar",
            "stages": [{"stage": "implement", "content": "x", "artifacts": []},
                       {"stage": "report", "content": "y", "artifacts": []}],
            "signals": [],  # no signal, but stored label lies:
            "label": "verified"}), encoding="utf-8")
        dir_recs, dir_err = _read_trace_records(str(tdir))
        if dir_err:
            problems.append(f"from-traces(4): directory read errored: {dir_err}")
        _, dsel, dexc = build_traces_scaffold(dir_recs)
        if dsel != ["dir-good"]:
            problems.append(f"from-traces(4): directory not re-graded correctly "
                            f"(selected {dsel}, expected ['dir-good'])")
        if "dir-liar" not in {i for ids in dexc.values() for i in ids}:
            problems.append("from-traces(4): the directory liar was not re-graded out")

        # (5b) EMPTY-BUT-VERIFIED render guard: a verified trace with blank stage
        #      content but a passing signal renders only labels+footer; if below the
        #      floor it is SKIPPED (logged), never padded. Build one whose render is
        #      forced thin (single empty stage label) and confirm it is excluded with
        #      the thin-render reason — and that a normal verified one is NOT skipped.
        thin = _export_rec(
            "ft-thin", "verified but blank",
            [("implement", "", []), ("report", "", [])],
            [{"kind": "tests", "cmd": "x", "exit_code": 0, "summary": ""}])
        # Render it directly to see the floor decision deterministically.
        thin_render = _render_trajectory(thin["trajectory"], thin["signals"])
        _, tsel, texc = build_traces_scaffold([thin])
        if len(thin_render) < TRACE_MIN_CONTENT:
            if tsel:
                problems.append("from-traces(5b): a thin verified render was kept "
                                "(must be skipped, not padded)")
            if not any("too thin" in reason for reason in texc):
                problems.append(f"from-traces(5b): thin render not logged with reason: "
                                f"{texc}")
        # else: the labels+footer already clear the floor — that's the intended
        # never-whitespace behaviour; the kept record is still real transcription.

        # (7) EMPTY CORPUS exits 2: cmd_from_traces over only-unverified input must
        #     fail loud (exit 2), never write an empty JSONL.
        ec_dir = tmp / "empty-corpus-out"
        ec_jsonl_pre = list(ec_dir.glob("*.jsonl")) if ec_dir.is_dir() else []
        only_bad = tmp / "only-bad.jsonl"
        with only_bad.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(failed_rec) + "\n")
            fh.write(json.dumps(nosig_rec) + "\n")
        rc_empty = cmd_from_traces(argparse.Namespace(
            traces=str(only_bad), out=str(ec_dir), tag=None,
            require_signal_kind=None, min_stages=None, run=False,
            dry_run=False, base=None, steps=None))
        if rc_empty != 2:
            problems.append(f"from-traces(7): empty corpus returned {rc_empty}, "
                            f"expected 2 (fail loud)")
        wrote = list(ec_dir.glob("*.jsonl")) if ec_dir.is_dir() else []
        if len(wrote) > len(ec_jsonl_pre):
            problems.append("from-traces(7): an empty corpus WROTE a JSONL (must not)")

        # end-to-end cmd_from_traces happy path: writes the filled JSONL + plan,
        # default (no --run) exits 0.
        e2e_out = tmp / "ft-e2e"
        e2e_jsonl = tmp / "e2e-in.jsonl"
        with e2e_jsonl.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(verified_rec) + "\n")
        rc_e2e = cmd_from_traces(argparse.Namespace(
            traces=str(e2e_jsonl), out=str(e2e_out), tag="my-skill",
            require_signal_kind=None, min_stages=None, run=False,
            dry_run=False, base=None, steps=None))
        if rc_e2e != 0:
            problems.append(f"from-traces(e2e): happy path returned {rc_e2e}, expected 0")
        if not (e2e_out / "train-from-traces.jsonl").is_file():
            problems.append("from-traces(e2e): did not write train-from-traces.jsonl")
        if not (e2e_out / "from-traces-plan.md").is_file():
            problems.append("from-traces(e2e): did not write from-traces-plan.md")
        else:
            e2e_line = (e2e_out / "train-from-traces.jsonl").read_text(
                encoding="utf-8").splitlines()[0]
            e2e_rec = json.loads(e2e_line)
            if e2e_rec.get("skill") != "my-skill":
                problems.append(f"from-traces(e2e): --tag not honored: "
                                f"{e2e_rec.get('skill')!r}")

    if problems:
        print("wf finetune selftest: FAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print(
        "wf finetune selftest: PASS (parses an orchestra baseline's per-skill table "
        "incl. the ERROR row's HTML-comment; prep selects ONLY NEEDS-FINETUNE and "
        "logs PASS/NO-EVALS/UNGRADED/ERROR exclusions with reasons; the scaffold is "
        "messages[user,assistant] with an EMPTY, clearly-marked assistant target "
        "(never fabricated); run validates shape and REFUSES the empty scaffold "
        "(fail closed) but accepts a filled fixture and dry-run prints the command "
        "WITHOUT training; validate catches malformed/shape errors; compare computes "
        "the right improved/regressed/still-needs/unchanged sets and score deltas; "
        "JSON baselines parse too; an empty baseline fails loud. FROM-TRACES: "
        "compute_label is loaded from wf-trace (single verified-decision source); a "
        "verified trace renders to a non-empty, MARKER-FREE assistant that validate "
        "ACCEPTS and routes clean through cmd_run --dry-run; failed/unverified/no-"
        "signal traces are excluded-with-reason; a stored-'verified'-but-recomputes-"
        "unverified record is EXCLUDED (the recompute decides, not the stored label); "
        "a DIRECTORY input is re-graded not trusted; an empty-but-verified thin "
        "render is skipped not padded; an empty corpus exits 2 and writes nothing; "
        "--tag is honored)"
    )
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="wf finetune",
        description="Bridge orchestra (measure) → finetune_qlora (train) → re-measure.",
    )
    ap.add_argument("--selftest", action="store_true",
                    help="run built-in self-test (no GPU, no endpoint, synthetic fixtures)")
    sub = ap.add_subparsers(dest="cmd")

    p_prep = sub.add_parser(
        "prep", help="turn a baseline's NEEDS-FINETUNE skills into a training scaffold")
    p_prep.add_argument("--from", required=True,
                        help="orchestra baseline report (Markdown or JSON)")
    p_prep.add_argument("--out", help="output dir for the scaffold + plan "
                                      "(default: <baseline-dir>/finetune-prep)")
    p_prep.add_argument("--with-teacher", action="store_true",
                        help="fill assistant targets via the teacher (distill_mini.py); "
                             "FAILS CLOSED if no teacher endpoint is reachable")
    p_prep.add_argument("--with-triggers", action="store_true",
                        help="also use triggers.json queries as user turns")

    p_run = sub.add_parser("run", help="validate a chat JSONL and train (GPU) or dry-run")
    p_run.add_argument("--data", required=True, help="chat-format training JSONL")
    p_run.add_argument("--base", help=f"base model (default: {DEFAULT_BASE_MODEL})")
    p_run.add_argument("--steps", type=int, help=f"train steps (default: {DEFAULT_STEPS})")
    p_run.add_argument("--dry-run", action="store_true",
                       help="print the exact command/env without training "
                            "(the default when no GPU/training venv is detected)")

    p_cmp = sub.add_parser("compare", help="diff two orchestra baselines (the loop outcome)")
    p_cmp.add_argument("--before", required=True, help="baseline BEFORE fine-tune")
    p_cmp.add_argument("--after", required=True, help="baseline AFTER fine-tune")

    p_ft = sub.add_parser(
        "from-traces",
        help="turn VERIFIED `wf trace` process trails into FILLED training examples")
    p_ft.add_argument(
        "--traces", default=None,
        help="a `wf trace export` JSONL, a traces DIRECTORY (default $WF_TRACE_DIR "
             "or _workflow/traces), or `-` for stdin")
    p_ft.add_argument("--out", help="output dir for the filled JSONL + plan "
                                    "(default: _workflow/finetune-from-traces)")
    p_ft.add_argument("--tag", help="skill tag for emitted records "
                                    "(default: classification.type, else 'trace')")
    p_ft.add_argument("--require-signal-kind", dest="require_signal_kind",
                      help="comma list — require these PASSING executable signal "
                           "kind(s) (a stronger bar than the verified default)")
    p_ft.add_argument("--min-stages", dest="min_stages",
                      help="comma list — require these trajectory stages present "
                           "(a stronger bar than implement+report)")
    p_ft.add_argument("--run", action="store_true",
                      help="hand the filled JSONL straight to `wf finetune run` "
                           "(re-validates, then GPU-gated train/dry-run)")
    p_ft.add_argument("--dry-run", action="store_true",
                      help="with --run, force dry-run (print the command, never train)")
    p_ft.add_argument("--base", help=f"base model for --run (default: {DEFAULT_BASE_MODEL})")
    p_ft.add_argument("--steps", type=int,
                      help=f"train steps for --run (default: {DEFAULT_STEPS})")

    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.cmd == "prep":
        return cmd_prep(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "compare":
        return cmd_compare(args)
    if args.cmd == "from-traces":
        return cmd_from_traces(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
