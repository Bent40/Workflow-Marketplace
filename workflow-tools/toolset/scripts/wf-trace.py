#!/usr/bin/env python3
"""wf-trace.py — record, grade, and export WHOLE-TASK PROCESS TRAILS as
verified training data (the teacher/data-generator layer).

WHY THIS EXISTS (and how it differs from what's already here):
  - `wf orchestra` / `wf finetune` work at PER-SKILL granularity: a skill's eval
    output becomes a training example.
  - `wf trace` works at the WHOLE-TASK TRAJECTORY level: the full process trail of
    how a task was handled — task -> classify -> plan -> explore -> implement ->
    test -> review -> fix -> report — captured as ONE structured record. That
    process trail (not just the final code) is the high-signal curriculum for
    teaching an agent HOW to work.
  This is the mechanism behind `orchestration.finetune_from_verified_traces`.

THE HONESTY CORE (the whole point — read this before changing anything):
  A trace's quality LABEL is **earned from recorded EXECUTABLE ground-truth
  signals** (tests / eval / browse-E2E / mutate / audit / review-gate exit codes),
  never asserted. `verified` requires >=1 PASSING executable signal AND the
  required stages; a failing signal makes it `failed`; no executable signal at all
  makes it `unverified` (NOT training-grade). The label is always COMPUTED from
  signals — `validate` REJECTS a stored label that does not match the recompute
  (a hand-set/fabricated `verified` is a hard failure), and `export` RE-COMPUTES
  the label rather than trusting the file. This is the dataset-quality filter that
  keeps a teacher system from training future models on its own unverified blind
  spots (model collapse). Anchoring on EXECUTABLE ground truth — not an LLM judge's
  opinion — is deliberate: a judge can be wrong in a correlated way; a passing test
  suite is non-gameable.

PRIVACY: a trace captures the actual work, so it inherits the PROJECT's privacy.
Traces from an org/private project stay in that project's private repo — they are
never civilian-public. The tool is civilian; the data is the project's.

STORAGE: one JSON file per trace under the traces dir (default _workflow/traces/;
override with --dir or $WF_TRACE_DIR). --selftest uses a tempdir and never touches
the real store.

Subcommands:
  start   --task T [--size S --type Y --risk a,b]      begin a trace, print its id
  stage   --id ID --stage S [--content C --artifacts a,b]   append a trajectory stage
  signal  --id ID --kind K --exit N [--cmd C --summary S]    record a ground-truth signal
  end     --id ID                                       finalize: compute + store the label
  grade   --id ID                                       show the computed label + why
  validate [--id ID]                                    validate one/all; fail-closed
  export  [--verified-only] [--format jsonl]            emit training-ready records
  record  --json '<trail>' | --file F                   ingest a WHOLE trail in one call
                                                        (end-of-task capture; payload label IGNORED)
  enable                                                opt this project into ambient capture
  status                                                report whether capture is enabled
  list                                                  list traces with computed labels

Exit codes: validate -> 0 ok / 1 invalid.  others -> 0 / 2 usage.  selftest -> 0/1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO_ROOT / "_workflow" / "traces"

# Trajectory stages a process trail is built from.
STAGES = ("classify", "plan", "explore", "decision", "implement",
          "test", "review", "fix", "report")
# Signal kinds. EXECUTABLE ones carry non-gameable ground truth (a real exit code);
# `review_gate` is a human/LLM gate kept SEPARATE so a label never rests on it alone.
EXECUTABLE_KINDS = ("tests", "eval", "browse", "mutate", "audit")
SIGNAL_KINDS = EXECUTABLE_KINDS + ("review_gate",)
# A trace must show it did the work and reported, on top of a passing signal, to be
# training-grade. (Deliberately small: the passing executable signal does the heavy
# lifting; these guard against a "signal but no actual trajectory" record.)
REQUIRED_STAGES = ("implement", "report")


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf trace: {msg}\n")
    raise SystemExit(code)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dir(arg_dir: str | None) -> Path:
    if arg_dir:
        return Path(arg_dir)
    env = os.environ.get("WF_TRACE_DIR")
    return Path(env) if env else DEFAULT_DIR


def _slug(s: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in s.strip().lower()]
    out = "".join(keep).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out[:60] or "trace"


def _path(d: Path, tid: str) -> Path:
    return d / f"{tid}.json"


def load_trace(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_trace(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def all_traces(d: Path) -> list[tuple[Path, dict]]:
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append((p, load_trace(p)))
        except (json.JSONDecodeError, ValueError) as e:
            sys.stderr.write(f"wf trace: skipping unreadable {p}: {e}\n")
    return out


# ---------------------------------------------------------------------------
# THE HONESTY CORE: label is COMPUTED from executable signals, never asserted.
# ---------------------------------------------------------------------------
def compute_label(trace: dict) -> tuple[str, str]:
    """Return (label, reason). label in verified | failed | unverified.

    verified  -> >=1 PASSING executable signal, NO failing executable signal,
                 and the required stages are present.
    failed    -> any executable signal recorded a non-zero exit.
    unverified-> no executable signal to stand on (NOT training-grade), or
                 passing signals but the trajectory is incomplete.
    `review_gate` signals are NEVER sufficient on their own — a label rests on
    executable ground truth, not on a gate's say-so."""
    signals = trace.get("signals", []) or []
    execs = [s for s in signals if s.get("kind") in EXECUTABLE_KINDS]
    failing = [s for s in execs if _exit(s) != 0]
    passing = [s for s in execs if _exit(s) == 0]
    stages = {st.get("stage") for st in trace.get("stages", []) or []}
    missing = [s for s in REQUIRED_STAGES if s not in stages]
    if failing:
        kinds = ",".join(sorted({s.get("kind", "?") for s in failing}))
        return "failed", f"{len(failing)} executable signal(s) failed ({kinds})"
    if not execs:
        return "unverified", "no executable ground-truth signal recorded — not training-grade"
    if missing:
        return "unverified", f"passing signals but trajectory incomplete (missing stage: {','.join(missing)})"
    kinds = ",".join(sorted({s.get("kind", "?") for s in passing}))
    return "verified", f"{len(passing)} passing executable signal(s) ({kinds}); required stages present"


def _exit(sig: dict) -> int:
    """A signal with a missing/non-int exit_code is treated as FAILED (fail-closed —
    an unrecorded result never counts as a pass)."""
    v = sig.get("exit_code")
    return v if isinstance(v, int) and not isinstance(v, bool) else 1


def validate_trace(trace: dict) -> list[str]:
    problems: list[str] = []
    for f in ("id", "task", "stages"):
        if f not in trace:
            problems.append(f"missing required field '{f}'")
    for i, st in enumerate(trace.get("stages", []) or []):
        if st.get("stage") not in STAGES:
            problems.append(f"stage[{i}] invalid stage {st.get('stage')!r} (want one of {'|'.join(STAGES)})")
    for i, s in enumerate(trace.get("signals", []) or []):
        if s.get("kind") not in SIGNAL_KINDS:
            problems.append(f"signal[{i}] invalid kind {s.get('kind')!r}")
        if not isinstance(s.get("exit_code"), int) or isinstance(s.get("exit_code"), bool):
            problems.append(f"signal[{i}] exit_code must be an int (got {s.get('exit_code')!r})")
    # THE CRUX: a stored label must EQUAL the recomputed ground-truth label.
    # A hand-set / fabricated 'verified' (no passing signal) is rejected here.
    if "label" in trace:
        computed, _ = compute_label(trace)
        if trace["label"] != computed:
            problems.append(
                f"label {trace['label']!r} does not match the ground-truth-computed "
                f"{computed!r} — a label must be EARNED from recorded executable "
                f"signals, never asserted")
    return problems


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_start(d: Path, args) -> int:
    task = (args.task or "").strip()
    if not task:
        _die("--task must be non-empty")
    tid = _slug(args.id) if args.id else f"{_slug(task)[:32]}-{_now().replace(':', '').replace('-', '')[:13]}"
    path = _path(d, tid)
    if path.exists():
        _die(f"trace {tid} already exists at {path}")
    risk = [r.strip() for r in (args.risk or "").split(",") if r.strip()]
    trace = {
        "id": tid,
        "ts": _now(),
        "task": task,
        "classification": {"size": args.size or "", "type": args.type or "", "risk": risk},
        "stages": [],
        "signals": [],
    }
    save_trace(path, trace)
    print(f"started trace {tid} -> {path}")
    return 0


def _get(d: Path, tid: str) -> tuple[Path, dict]:
    path = _path(d, _slug(tid))
    if not path.is_file():
        _die(f"no trace {tid} at {path}")
    return path, load_trace(path)


def cmd_stage(d: Path, args) -> int:
    if args.stage not in STAGES:
        _die(f"--stage must be one of {'|'.join(STAGES)} (got {args.stage!r})")
    path, trace = _get(d, args.id)
    artifacts = [a.strip() for a in (args.artifacts or "").split(",") if a.strip()]
    trace.setdefault("stages", []).append({
        "stage": args.stage, "ts": _now(),
        "content": (args.content or "").strip(), "artifacts": artifacts,
    })
    save_trace(path, trace)
    print(f"trace {trace['id']}: +stage {args.stage} ({len(trace['stages'])} total)")
    return 0


def cmd_signal(d: Path, args) -> int:
    if args.kind not in SIGNAL_KINDS:
        _die(f"--kind must be one of {'|'.join(SIGNAL_KINDS)} (got {args.kind!r})")
    if args.exit is None:
        _die("--exit (the real exit code) is required — a signal without a result fails closed")
    path, trace = _get(d, args.id)
    trace.setdefault("signals", []).append({
        "kind": args.kind, "ts": _now(), "cmd": (args.cmd or "").strip(),
        "exit_code": int(args.exit), "summary": (args.summary or "").strip(),
    })
    save_trace(path, trace)
    lbl, why = compute_label(trace)
    print(f"trace {trace['id']}: +signal {args.kind} exit={args.exit} -> label now {lbl} ({why})")
    return 0


def cmd_end(d: Path, args) -> int:
    path, trace = _get(d, args.id)
    label, reason = compute_label(trace)
    trace["label"], trace["label_reason"] = label, reason
    trace["ended_ts"] = _now()
    save_trace(path, trace)
    print(f"trace {trace['id']} finalized: {label} — {reason}")
    return 0


def cmd_grade(d: Path, args) -> int:
    _, trace = _get(d, args.id)
    label, reason = compute_label(trace)
    print(f"{trace['id']}: {label} — {reason}")
    return 0


def cmd_validate(d: Path, args) -> int:
    items = [_get(d, args.id)] if args.id else all_traces(d)
    bad = 0
    for path, trace in items:
        probs = validate_trace(trace)
        if probs:
            bad += 1
            print(f"INVALID {getattr(path, 'name', trace.get('id'))}:")
            for p in probs:
                print(f"  - {p}")
        else:
            print(f"ok {trace.get('id')}")
    if bad:
        print(f"wf trace validate: FAIL — {bad} invalid trace(s)")
        return 1
    print(f"wf trace validate: OK ({len(items)} trace(s))")
    return 0


def _export_record(trace: dict) -> dict:
    """A training-ready record. The label is RECOMPUTED (the file is not trusted),
    and provenance records that it rests on executable ground truth."""
    label, reason = compute_label(trace)
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


def cmd_export(d: Path, args) -> int:
    n = 0
    for _, trace in all_traces(d):
        rec = _export_record(trace)
        if args.verified_only and rec["label"] != "verified":
            continue
        print(json.dumps(rec, ensure_ascii=False))
        n += 1
    sys.stderr.write(f"wf trace export: {n} record(s)"
                     f"{' (verified-only)' if args.verified_only else ''}\n")
    return 0


def cmd_list(d: Path, args) -> int:
    items = all_traces(d)
    for _, trace in items:
        label, _ = compute_label(trace)
        st = len(trace.get("stages", []))
        sg = len(trace.get("signals", []))
        print(f"  {trace.get('id'):40s} {label:10s} stages={st} signals={sg}")
    print(f"— {len(items)} trace(s) in {d}")
    return 0


# ---------------------------------------------------------------------------
# end-of-task capture: one call records a whole trail (no per-stage tool spam)
# ---------------------------------------------------------------------------
def _read_payload(args) -> str:
    if getattr(args, "json", None):
        return args.json
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    return sys.stdin.read()


def cmd_record(d: Path, args) -> int:
    """Ingest a COMPLETE trail in one call: {task, classification?, stages[],
    signals[]}. Any `label` in the payload is IGNORED — the label is always
    computed from the signals, so `record` can never inject a fabricated
    'verified'. This is the lighter end-of-task capture the router uses."""
    raw = _read_payload(args)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        _die(f"record payload is not valid JSON: {e}")
    if not isinstance(payload, dict):
        _die("record payload must be a JSON object")
    task = (payload.get("task") or "").strip()
    if not task:
        _die("record payload missing non-empty 'task'")
    stages = []
    for st in payload.get("stages", []) or []:
        if st.get("stage") not in STAGES:
            _die(f"invalid stage {st.get('stage')!r} (want one of {'|'.join(STAGES)})")
        stages.append({"stage": st["stage"], "ts": st.get("ts") or _now(),
                       "content": (st.get("content") or "").strip(),
                       "artifacts": list(st.get("artifacts") or [])})
    signals = []
    for s in payload.get("signals", []) or []:
        if s.get("kind") not in SIGNAL_KINDS:
            _die(f"invalid signal kind {s.get('kind')!r}")
        if not isinstance(s.get("exit_code"), int) or isinstance(s.get("exit_code"), bool):
            _die(f"signal {s.get('kind')!r} needs an int exit_code (the real result)")
        signals.append({"kind": s["kind"], "ts": s.get("ts") or _now(),
                        "cmd": (s.get("cmd") or "").strip(), "exit_code": int(s["exit_code"]),
                        "summary": (s.get("summary") or "").strip()})
    cls = payload.get("classification") or {}
    tid = _slug(payload.get("id") or f"{_slug(task)[:32]}-{_now().replace(':', '').replace('-', '')[:13]}")
    path = _path(d, tid)
    if path.exists():
        _die(f"trace {tid} already exists at {path}")
    trace = {
        "id": tid, "ts": _now(), "task": task,
        "classification": {"size": cls.get("size", ""), "type": cls.get("type", ""),
                           "risk": list(cls.get("risk") or [])},
        "stages": stages, "signals": signals,
    }
    label, reason = compute_label(trace)  # COMPUTED — any payload label is ignored
    trace["label"], trace["label_reason"], trace["ended_ts"] = label, reason, _now()
    save_trace(path, trace)
    print(f"recorded trace {tid}: {label} — {reason} -> {path}")
    return 0


def _enabled(d: Path) -> bool:
    return (d / ".enabled").exists()


def cmd_enable(d: Path, args) -> int:
    d.mkdir(parents=True, exist_ok=True)
    (d / ".enabled").write_text(
        "# wf trace capture opt-in marker. Its presence tells the ambient router to\n"
        "# record a process trail at task completion (orchestration.trace_capture_on_\n"
        "# completion). Remove this file to stop ambient capture.\n", encoding="utf-8")
    print(f"trace capture ENABLED for {d} (router will capture trails on task completion)")
    return 0


def cmd_status(d: Path, args) -> int:
    on = _enabled(d)
    n = len(all_traces(d))
    print(f"trace capture: {'ENABLED' if on else 'disabled'} (dir {d}, {n} trace(s))"
          + ("" if on else " — run `wf trace enable` to opt in"))
    return 0


# ---------------------------------------------------------------------------
# selftest (with teeth)
# ---------------------------------------------------------------------------
def selftest() -> int:
    import tempfile

    problems: list[str] = []

    class A:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    with tempfile.TemporaryDirectory() as dd:
        d = Path(dd)

        def mk(tid, stages, signals, label=None):
            t = {"id": tid, "ts": _now(), "task": f"task {tid}",
                 "classification": {"size": "small", "type": "change", "risk": []},
                 "stages": [{"stage": s, "ts": _now(), "content": "", "artifacts": []} for s in stages],
                 "signals": signals}
            if label is not None:
                t["label"] = label
            save_trace(_path(d, tid), t)
            return t

        # 1. verified: implement+report+report and a PASSING test signal
        t = mk("good", ["plan", "implement", "test", "report"],
               [{"kind": "tests", "ts": _now(), "cmd": "pytest", "exit_code": 0, "summary": "42 passed"}])
        lbl, _ = compute_label(t)
        if lbl != "verified":
            problems.append(f"1: complete+passing trace should be verified, got {lbl}")

        # 2. failed: a failing executable signal dominates
        t = mk("bad", ["plan", "implement", "test", "report"],
               [{"kind": "tests", "ts": _now(), "exit_code": 1, "summary": "1 failed"}])
        if compute_label(t)[0] != "failed":
            problems.append("2: a failing signal must yield 'failed'")

        # 3. unverified: no executable signal at all (NOT training-grade)
        t = mk("nosig", ["plan", "implement", "report"], [])
        if compute_label(t)[0] != "unverified":
            problems.append("3: no executable signal must be 'unverified'")

        # 4. review_gate alone is NOT enough (label rests on executable ground truth)
        t = mk("gateonly", ["implement", "report"],
               [{"kind": "review_gate", "ts": _now(), "exit_code": 0, "summary": "looks good"}])
        if compute_label(t)[0] != "unverified":
            problems.append("4: a review_gate-only trace must NOT be verified")

        # 5. incomplete trajectory: passing signal but no 'report' stage
        t = mk("incomplete", ["implement"],
               [{"kind": "tests", "ts": _now(), "exit_code": 0}])
        if compute_label(t)[0] != "unverified":
            problems.append("5: passing signal but incomplete trajectory must be 'unverified'")

        # 6. THE TEETH: a FABRICATED 'verified' label with no passing signal is INVALID
        mk("fabricated", ["implement", "report"], [], label="verified")
        _, ftrace = _get(d, "fabricated")
        if not validate_trace(ftrace):
            problems.append("6: a fabricated 'verified' label (no signal) MUST fail validate")
        # and a correct stored label validates clean
        mk("honest", ["implement", "report"],
           [{"kind": "tests", "ts": _now(), "exit_code": 0}], label="verified")
        _, htrace = _get(d, "honest")
        if validate_trace(htrace):
            problems.append("6: an honestly-earned 'verified' label must validate clean")

        # 7. export --verified-only recomputes and emits ONLY ground-truth-verified
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_export(d, A(verified_only=True, format="jsonl"))
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        ids = {json.loads(l)["id"] for l in lines}
        if "good" not in ids or "honest" not in ids:
            problems.append(f"7: verified-only export missing a verified trace: {ids}")
        if ids & {"bad", "nosig", "gateonly", "incomplete", "fabricated"}:
            problems.append(f"7: verified-only export leaked a non-verified trace: {ids}")
        # every exported record must be provenance=ground-truth-verified
        if any(json.loads(l)["provenance"] != "ground-truth-verified" for l in lines):
            problems.append("7: a verified-only record had non-ground-truth provenance")

        # 8. fail-closed: a signal with a missing exit_code counts as FAILED, not pass
        t = {"id": "noexit", "task": "x", "stages": [{"stage": "implement"}, {"stage": "report"}],
             "signals": [{"kind": "tests"}]}  # no exit_code
        if compute_label(t)[0] == "verified":
            problems.append("8: a signal with no exit_code must NOT count as a pass")

        # 9. round-trip via the real CLI commands (start/stage/signal/end)
        cmd_start(d, A(task="cli round trip", id="cli", size="small", type="change", risk=""))
        cmd_stage(d, A(id="cli", stage="implement", content="did it", artifacts=""))
        cmd_stage(d, A(id="cli", stage="report", content="done", artifacts=""))
        cmd_signal(d, A(id="cli", kind="tests", exit=0, cmd="pytest", summary="ok"))
        cmd_end(d, A(id="cli"))
        _, cli = _get(d, "cli")
        if cli.get("label") != "verified" or validate_trace(cli):
            problems.append(f"9: CLI round-trip should produce a clean verified trace, got {cli.get('label')}")

        # 10. record (one-call capture) IGNORES any payload label — a malicious
        #     'verified' on a trail with no signal must come out 'unverified'.
        cmd_record(d, A(json=json.dumps({
            "id": "rec-fake", "task": "sneak a fake verified",
            "stages": [{"stage": "implement"}, {"stage": "report"}],
            "signals": [], "label": "verified"}), file=None))
        _, rf = _get(d, "rec-fake")
        if rf.get("label") != "unverified" or validate_trace(rf):
            problems.append(f"10: record must IGNORE an input label and compute unverified, got {rf.get('label')}")
        # a genuine one-call trail with a passing signal computes verified + validates
        cmd_record(d, A(json=json.dumps({
            "id": "rec-good", "task": "real trail",
            "stages": [{"stage": "plan"}, {"stage": "implement"}, {"stage": "report"}],
            "signals": [{"kind": "tests", "cmd": "pytest", "exit_code": 0, "summary": "ok"}]}), file=None))
        _, rg = _get(d, "rec-good")
        if rg.get("label") != "verified" or validate_trace(rg):
            problems.append(f"10: a genuine recorded trail should be verified+valid, got {rg.get('label')}")
        # enable marker controls the opt-in the router checks
        if _enabled(d):
            problems.append("10: capture should be disabled before enable")
        cmd_enable(d, A())
        if not _enabled(d):
            problems.append("10: cmd_enable must set the opt-in marker")

    if problems:
        print("wf trace selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf trace selftest: PASS (label computed from executable ground truth, not "
          "asserted; failing signal -> failed; no/only-review-gate signal -> unverified; "
          "incomplete trajectory -> unverified; FABRICATED verified label fails validate "
          "while an earned one passes; verified-only export recomputes + emits only "
          "ground-truth-verified; missing exit_code fails closed; CLI round-trip clean)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf trace")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dir", default=None, help="traces dir (default $WF_TRACE_DIR or _workflow/traces/)")
    sub = ap.add_subparsers(dest="action")

    p = sub.add_parser("start", help="begin a trace")
    p.add_argument("--task", required=True)
    p.add_argument("--id", default=None)
    p.add_argument("--size", default="")
    p.add_argument("--type", default="")
    p.add_argument("--risk", default="")

    p = sub.add_parser("stage", help="append a trajectory stage")
    p.add_argument("--id", required=True)
    p.add_argument("--stage", required=True, choices=list(STAGES))
    p.add_argument("--content", default="")
    p.add_argument("--artifacts", default="")

    p = sub.add_parser("signal", help="record a ground-truth signal")
    p.add_argument("--id", required=True)
    p.add_argument("--kind", required=True, choices=list(SIGNAL_KINDS))
    p.add_argument("--exit", type=int, default=None, help="the real exit code (required)")
    p.add_argument("--cmd", default="")
    p.add_argument("--summary", default="")

    for name, helptext in (("end", "finalize: compute + store the label"),
                           ("grade", "show the computed label"),):
        q = sub.add_parser(name, help=helptext)
        q.add_argument("--id", required=True)

    q = sub.add_parser("validate", help="validate one/all traces; fail-closed")
    q.add_argument("--id", default=None)

    q = sub.add_parser("export", help="emit training-ready records")
    q.add_argument("--verified-only", action="store_true")
    q.add_argument("--format", default="jsonl", choices=["jsonl"])

    q = sub.add_parser("record", help="ingest a whole trail in one call (end-of-task capture)")
    q.add_argument("--json", default=None, help="the trail as a JSON string")
    q.add_argument("--file", default=None, help="read the trail JSON from a file")

    sub.add_parser("enable", help="opt this project into ambient trace capture")
    sub.add_parser("status", help="report whether trace capture is enabled")
    sub.add_parser("list", help="list traces with computed labels")

    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("an action (start|stage|signal|end|grade|validate|export|record|enable|status|list) or --selftest is required")
    d = _dir(args.dir)
    return {
        "start": cmd_start, "stage": cmd_stage, "signal": cmd_signal,
        "end": cmd_end, "grade": cmd_grade, "validate": cmd_validate,
        "export": cmd_export, "record": cmd_record, "enable": cmd_enable,
        "status": cmd_status, "list": cmd_list,
    }[args.action](d, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
