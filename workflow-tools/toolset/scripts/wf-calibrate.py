#!/usr/bin/env python3
"""wf-calibrate.py — measure the MEASURER. Every LLM-as-judge gate in this repo
(wf orchestra --grader judge, bmad-eval-runner, the review gates) is TRUSTED but
never validated against ground truth — a silent single point of failure under the
"measured, not asserted" bar. This tool computes the judge's AGREEMENT with a
human-labeled gold set (Cohen's kappa) and FAILS the judge below a floor, so the
judge itself becomes falsifiable.

HONESTY (non-negotiable): a real calibration needs REAL human labels. This ships
the HARNESS plus an ILLUSTRATIVE example gold set clearly marked as a placeholder
(core/eval/judge-calibration/) — exactly like wf finetune emits an empty scaffold
rather than fabricating targets. Synthetic labels give the harness its SHAPE, not a
trustworthy calibration; replace them with real (output, human-verdict) pairs.
Scope it small and to the owned/priority judges, or it becomes ceremony; kappa on
a tiny set is itself noisy — treat the floor as a FLOOR check, not a precise score.

The judge run is a testable SEAM: `calibrate(records, judge_fn)` takes any
`judge_fn(output, criterion) -> "PASS"|"FAIL"`, so --selftest uses a stub (NO
network) and the real CLI builds a judge over an OpenAI-compatible endpoint
(reusing wf-orchestra's backend — no duplicate HTTP logic).

Usage:
    wf calibrate --gold <file.jsonl> --judge-model <url> --judge-model-name <name>
                 [--floor 0.6] [--judge-api-key-env JUDGE_API_KEY]
    wf calibrate --selftest

Exit codes: 0 = kappa >= floor (judge trustworthy); 1 = kappa < floor (judge FAILS
calibration); 2 = usage / no gold / unreachable judge.  selftest -> 0 / 1.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLD = REPO_ROOT / "core" / "eval" / "judge-calibration" / "example.jsonl"
DEFAULT_FLOOR = 0.6  # Cohen's kappa: ~0.6 is "substantial" agreement (a floor, not a target)
LABELS = ("PASS", "FAIL")


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf calibrate: {msg}\n")
    raise SystemExit(code)


def cohen_kappa(pairs: list[tuple]) -> float | None:
    """Cohen's kappa for a list of (label_a, label_b) pairs. Returns a float in
    [-1, 1], or None if fewer than 2 pairs. kappa=1 perfect agreement, 0 = chance,
    <0 worse than chance. Pure + exact (the agreement instrument itself)."""
    n = len(pairs)
    if n < 2:
        return None
    labels = sorted(set(a for a, _ in pairs) | set(b for _, b in pairs))
    po = sum(1 for a, b in pairs if a == b) / n
    pe = 0.0
    for lab in labels:
        pa = sum(1 for a, _ in pairs if a == lab) / n
        pb = sum(1 for _, b in pairs if b == lab) / n
        pe += pa * pb
    if pe >= 1.0:
        # degenerate (one label only) — perfect iff observed agreement is perfect.
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1 - pe)


def load_gold(path: Path) -> list[dict]:
    """Load a gold JSONL of {id, output, gold:'PASS'|'FAIL', criterion?}. Fails
    CLOSED on a malformed line or a bad/absent gold label — a calibration set you
    can't trust is worse than none."""
    if not path.is_file():
        _die(f"gold set not found: {path}")
    records: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            _die(f"{path}:{lineno}: malformed JSON: {e}")
        if not isinstance(obj, dict) or "output" not in obj or obj.get("gold") not in LABELS:
            _die(f"{path}:{lineno}: each record needs 'output' and gold in {LABELS}")
        records.append(obj)
    if not records:
        _die(f"{path}: no gold records found")
    return records


def calibrate(records: list[dict], judge_fn) -> dict:
    """Run `judge_fn(output, criterion) -> 'PASS'|'FAIL'` over each gold record and
    score agreement vs the human gold label. Returns {kappa, agreement, n, pairs,
    disagreements}. The seam every test/CLI shares."""
    pairs: list[tuple] = []
    disagreements: list[dict] = []
    for rec in records:
        jv = judge_fn(rec["output"], rec.get("criterion", ""))
        jv = jv if jv in LABELS else "FAIL"  # a non-PASS/FAIL judge reply = FAIL (fail closed)
        gold = rec["gold"]
        pairs.append((jv, gold))
        if jv != gold:
            disagreements.append({"id": rec.get("id", "?"), "judge": jv, "gold": gold})
    n = len(pairs)
    agreement = (sum(1 for a, b in pairs if a == b) / n) if n else 0.0
    return {"kappa": cohen_kappa(pairs), "agreement": agreement, "n": n,
            "pairs": pairs, "disagreements": disagreements}


def render(result: dict, floor: float, gold_path: Path) -> str:
    k = result["kappa"]
    out = ["── wf calibrate — judge-vs-human agreement ────────────────────"]
    out.append(f"gold:      {gold_path}  ({result['n']} labeled pair(s))")
    out.append(f"agreement: {result['agreement']*100:.0f}%  (raw)")
    out.append(f"kappa:     {('%.2f' % k) if k is not None else 'n/a'}   floor {floor:.2f}")
    if result["disagreements"]:
        out.append("disagreements (judge vs gold):")
        for d in result["disagreements"][:8]:
            out.append(f"  - {d['id']}: judge={d['judge']} gold={d['gold']}")
    if k is None:
        out.append("VERDICT: INSUFFICIENT DATA (need >= 2 labeled pairs).")
    elif k >= floor:
        out.append(f"VERDICT: OK — judge agrees with the gold set (kappa {k:.2f} >= {floor:.2f}).")
    else:
        out.append(f"VERDICT: FAIL — judge disagrees too much (kappa {k:.2f} < {floor:.2f}); "
                   f"do not trust this judge until recalibrated.")
    out.append("NOTE: a real calibration needs REAL human labels; a tiny set's kappa is "
               "noisy — this is a FLOOR check, not a precise score.")
    out.append("───────────────────────────────────────────────────────────────")
    return "\n".join(out)


def _build_real_judge(model_url: str, model_name: str, api_key_env: str):
    """Build a judge_fn backed by an OpenAI-compatible endpoint, REUSING
    wf-orchestra's backend (no duplicate HTTP logic). Lazy — imported only for a
    real run, so --selftest stays network-free."""
    spec = importlib.util.spec_from_file_location(
        "wf_orchestra", REPO_ROOT / "scripts" / "wf-orchestra.py")
    orch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(orch)
    backend = orch.OpenAIChatBackend(model_url, model_name,
                                     api_key=os.environ.get(api_key_env) or None)
    system = ("You are a strict binary eval grader. Given a CRITERION and an OUTPUT, "
              "reply with EXACTLY one word: PASS if the output meets the criterion, "
              "else FAIL. No other text.")

    def judge_fn(output: str, criterion: str) -> str:
        user = f"CRITERION:\n{criterion or '(meets the stated bar)'}\n\nOUTPUT:\n{output}\n\nReply PASS or FAIL only."
        try:
            raw = backend.chat(system, user)
        except Exception as e:  # noqa: BLE001 — a dead judge fails the run loudly
            raise orch.BackendError(str(e))
        up = (raw or "").strip().upper()
        return "PASS" if up.startswith("PASS") else "FAIL"

    return judge_fn


def selftest() -> int:
    problems: list[str] = []

    # 1. cohen_kappa math: perfect agreement = 1.0; chance-level ≈ 0; <2 -> None.
    if cohen_kappa([("PASS", "PASS"), ("FAIL", "FAIL")]) != 1.0:
        problems.append("1: perfect agreement should be kappa 1.0")
    if cohen_kappa([("PASS", "PASS")]) is not None:
        problems.append("1: <2 pairs should be None")
    # total disagreement (judge always opposite) -> kappa negative.
    k_bad = cohen_kappa([("PASS", "FAIL"), ("FAIL", "PASS"), ("PASS", "FAIL"), ("FAIL", "PASS")])
    if k_bad is None or k_bad >= 0:
        problems.append(f"1: systematic disagreement should be kappa < 0, got {k_bad}")

    # 2. calibrate with a GOOD stub judge (mirrors gold) -> high kappa, OK gate;
    #    a BAD stub judge (always PASS) -> low kappa, FAIL gate. NO network.
    records = [
        {"id": "a", "output": "x", "gold": "PASS", "criterion": "c"},
        {"id": "b", "output": "y", "gold": "FAIL", "criterion": "c"},
        {"id": "c", "output": "z", "gold": "PASS", "criterion": "c"},
        {"id": "d", "output": "w", "gold": "FAIL", "criterion": "c"},
    ]
    gold_by_out = {r["output"]: r["gold"] for r in records}
    good = calibrate(records, lambda o, c: gold_by_out[o])
    if good["kappa"] != 1.0 or good["agreement"] != 1.0:
        problems.append(f"2: a perfect stub judge should give kappa 1.0: {good['kappa']}")
    always_pass = calibrate(records, lambda o, c: "PASS")
    if always_pass["kappa"] is None or always_pass["kappa"] >= DEFAULT_FLOOR:
        problems.append(f"2: an always-PASS judge should fail the floor: {always_pass['kappa']}")
    if len(always_pass["disagreements"]) != 2:
        problems.append(f"2: always-PASS should disagree on the 2 FAIL golds: {always_pass['disagreements']}")
    # a non-PASS/FAIL judge reply is coerced to FAIL (fail closed).
    coerced = calibrate([{"output": "x", "gold": "PASS"}], lambda o, c: "maybe?")
    if coerced["pairs"][0][0] != "FAIL":
        problems.append("2: a junk judge reply was not coerced to FAIL")

    # 3. render reflects the gate verdict and the honesty note.
    rep = render(always_pass, DEFAULT_FLOOR, Path("g.jsonl"))
    if "VERDICT: FAIL" not in rep or "human labels" not in rep:
        problems.append("3: render missing the FAIL verdict / honesty note")

    # 4. the shipped example gold set parses and is well-formed (fail-closed loader).
    if DEFAULT_GOLD.is_file():
        try:
            recs = load_gold(DEFAULT_GOLD)
            if len(recs) < 2:
                problems.append("4: example gold set has < 2 records")
        except SystemExit:
            problems.append("4: shipped example gold set failed the fail-closed loader")
    # a malformed gold line fails closed (exit 2).
    import tempfile
    with tempfile.TemporaryDirectory() as dd:
        bad = Path(dd) / "bad.jsonl"
        bad.write_text('{"output":"x","gold":"MAYBE"}\n')  # invalid gold label
        try:
            load_gold(bad)
            problems.append("4: a bad gold label did not fail closed")
        except SystemExit as e:
            if e.code != 2:
                problems.append(f"4: bad gold exit {e.code}, expected 2")

    if problems:
        print("wf calibrate selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf calibrate selftest: PASS (Cohen's kappa exact: 1.0 perfect, <0 on "
          "systematic disagreement, None under 2 pairs; calibrate gates a mirroring "
          "stub OK and an always-PASS judge FAIL below the floor; junk judge replies "
          "coerce to FAIL; render shows the verdict + honesty note; the example gold "
          "set parses and a bad label fails closed — all network-free)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="wf calibrate",
        description="Measure an LLM judge's agreement with a human gold set (Cohen's "
                    "kappa) and fail it below a floor.")
    ap.add_argument("--gold", default=str(DEFAULT_GOLD),
                    help="gold JSONL of {output, gold:'PASS'|'FAIL', criterion?}")
    ap.add_argument("--judge-model", default=None, help="OpenAI-compatible judge endpoint URL")
    ap.add_argument("--judge-model-name", default=None, help="judge model name")
    ap.add_argument("--judge-api-key-env", default="JUDGE_API_KEY",
                    help="env var holding the judge API key (value never printed)")
    ap.add_argument("--floor", type=float, default=DEFAULT_FLOOR,
                    help=f"minimum acceptable kappa (default {DEFAULT_FLOOR})")
    ap.add_argument("--selftest", action="store_true", help="run the selftest")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.judge_model or not args.judge_model_name:
        _die("a real run needs --judge-model <url> and --judge-model-name <name> "
             "(use --selftest for the network-free harness check)")
    records = load_gold(Path(args.gold))
    judge_fn = _build_real_judge(args.judge_model, args.judge_model_name,
                                 args.judge_api_key_env)
    try:
        result = calibrate(records, judge_fn)
    except Exception as e:  # noqa: BLE001 — a dead/erroring judge fails loudly, never fakes
        _die(f"judge run failed (no fabricated score): {e}")
    print(render(result, args.floor, Path(args.gold)))
    k = result["kappa"]
    return 0 if (k is not None and k >= args.floor) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
