#!/usr/bin/env python3
"""wf-mutate.py — a minimal mutation-testing gate: the antidote to green-but-
TAUTOLOGICAL tests. Line coverage proves a line executed; it does NOT prove a test
would CATCH A BUG. This tool mutates an operator in the source and re-runs the
test command: if the suite still PASSES on the mutated code, that mutant SURVIVED —
objective proof the tests don't actually pin that behavior.

RIGHT-SIZED v1 (honest about scope): Python only, a FOCUSED operator set
(comparison + boolean flips, where tautological tests most often hide), via the
`tokenize` module so it mutates real OPERATORS only (never operators inside string
literals). A surviving mutant is a FLOOR signal ("these tests don't pin this"),
not a full mutation score; WARN by default (a story-diff honesty surfacer, like
wf audit), exit non-zero only with --block.

SAFETY: the target file is ALWAYS restored (a try/finally), even on error or
interrupt — a mutation run never leaves the file mutated.

HONEST BASELINE (v2.6.1): mutation results REQUIRE a green baseline. Before any
mutation the test command runs once on the UNMUTATED file and must exit 0 — a
red baseline (broken env, flaky test, poisoned .pyc) would score every mutant
KILLED, a FALSE PERFECT SCORE, so the run aborts fail-closed instead. After the
final restore the baseline runs once more and the run FAILS loudly if it is no
longer green (a run that left the tree or its state dirty). Survivors were
always trustworthy (a red baseline can't manufacture a false survivor); an
"all killed" claim is only meaningful past this gate.

BYTECODE ISOLATION (v2.6.1): every test subprocess (baseline AND per-mutant)
runs with PYTHONDONTWRITEBYTECODE=1 plus a per-run unique PYTHONPYCACHEPREFIX
tempdir. CPython's timestamp(1s-granularity)+size .pyc validity check makes a
length-preserving mutation (== -> !=) mutated and restored within one second
look unchanged, so a shared in-tree __pycache__ would keep executing STALE
MUTATED BYTECODE — in this run and in concurrent runs sharing the tree.

The mutation generation is a PURE function (`mutate_source`) over source text, so
--selftest exercises it without running anything; the run/restore/survivor logic
is exercised against a synthetic temp project (a strong test KILLS, a tautological
test lets the mutant SURVIVE, a red baseline ABORTS, the isolation env is proven
applied, and the post-run integrity re-check fires on a dirty end-state).

Usage:
    wf mutate <file.py> --test "<command>" [--lines A-B] [--max N] [--block]
    wf mutate --selftest

Exit codes: 0 = report produced (WARN), or --block with no survivors;
            1 = --block and at least one mutant SURVIVED;
            2 = usage / file error, a RED BASELINE (fail-closed abort), or a
                failed post-run integrity re-check.  selftest -> 0 / 1.
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

# Operator mutations. OP tokens (comparison flips) and NAME tokens (boolean flips).
# A FOCUSED set on purpose — comparisons + booleans are where a tautological test
# most often fails to pin behavior. Each swap is a meaningful semantic flip.
OP_SWAPS = {"==": "!=", "!=": "==", "<": ">=", "<=": ">", ">": "<=", ">=": "<"}
NAME_SWAPS = {"and": "or", "or": "and", "True": "False", "False": "True"}


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf mutate: {msg}\n")
    raise SystemExit(code)


class BaselineNotGreenError(RuntimeError):
    """The test command failed on the UNMUTATED file — a red baseline would
    score every mutant KILLED (a false perfect score), so the run must abort
    fail-closed before any mutation is applied."""


class PostRunIntegrityError(RuntimeError):
    """The baseline was green before the run but red after the final restore —
    the run left the tree or its state dirty; the results cannot be trusted."""


def _isolated_env(pyc_prefix: str) -> dict[str, str]:
    """Env for every test subprocess (baseline AND per-mutant): bytecode fully
    isolated. PYTHONDONTWRITEBYTECODE stops .pyc writes; the per-run unique
    PYTHONPYCACHEPREFIX redirects .pyc reads away from any shared in-tree
    __pycache__ — so a run never reads or writes a cache another run (or a
    prior mutant) could have poisoned."""
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = pyc_prefix
    return env


def _run_test(test_cmd: str, cwd: Path, env: dict[str, str]) -> int:
    """Run the test command once in the isolated env; -1 = runner won't start."""
    try:
        return subprocess.run(test_cmd, shell=True, cwd=str(cwd),
                              capture_output=True, env=env).returncode
    except Exception:  # noqa: BLE001 — a runner that won't start = inconclusive
        return -1


def mutate_source(src: str) -> list[dict]:
    """Generate single-operator mutants of `src`. Returns a list of
    {line, desc, source} — each a full mutated source with exactly ONE operator
    swapped. Pure (no I/O). Uses tokenize so only real operator/keyword TOKENS are
    mutated, never their occurrences inside string literals or names."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []  # unparseable -> nothing to mutate (caller reports 0 mutants)
    lines = src.splitlines(keepends=True)
    mutants: list[dict] = []
    for tok in toks:
        repl = None
        if tok.type == tokenize.OP and tok.string in OP_SWAPS:
            repl = OP_SWAPS[tok.string]
        elif tok.type == tokenize.NAME and tok.string in NAME_SWAPS:
            repl = NAME_SWAPS[tok.string]
        if repl is None:
            continue
        (r1, c1), (r2, c2) = tok.start, tok.end
        if r1 != r2 or r1 < 1 or r1 > len(lines):
            continue  # operators live on a single line; skip anything odd
        line = lines[r1 - 1]
        # Precise span replacement (handles different-length swaps robustly).
        new_line = line[:c1] + repl + line[c2:]
        new_lines = list(lines)
        new_lines[r1 - 1] = new_line
        mutants.append({"line": r1,
                        "desc": f"L{r1}: {tok.string!r} -> {repl!r}",
                        "source": "".join(new_lines)})
    return mutants


def _in_range(line: int, lines_spec: str | None) -> bool:
    """True if `line` is within the optional A-B (or single A) range spec."""
    if not lines_spec:
        return True
    try:
        if "-" in lines_spec:
            a, b = lines_spec.split("-", 1)
            return int(a) <= line <= int(b)
        return line == int(lines_spec)
    except ValueError:
        return True  # malformed spec -> don't filter (surface everything)


def run_mutation_testing(file_path: Path, test_cmd: str, *, cwd: Path,
                         lines_spec: str | None = None,
                         max_mutants: int | None = None) -> list[dict]:
    """Gate on a GREEN baseline, apply each mutant, run `test_cmd`, classify,
    ALWAYS restore the file, then re-check the baseline post-run.
    A mutant where the test still PASSES (rc 0) SURVIVED (tests don't catch it);
    a non-zero rc means the test KILLED it — a classification that is only
    meaningful because the baseline was verified green first. Raises
    BaselineNotGreenError on a red baseline (fail-closed: never score mutants
    against a broken suite) and PostRunIntegrityError if the restored tree is
    no longer green. Returns per-mutant result dicts."""
    original = file_path.read_text(encoding="utf-8")
    mutants = [m for m in mutate_source(original) if _in_range(m["line"], lines_spec)]
    if max_mutants is not None:
        mutants = mutants[:max_mutants]
    pyc_root = tempfile.mkdtemp(prefix="wf-mutate-pyc-")  # per-run unique cache
    env = _isolated_env(pyc_root)
    results: list[dict] = []
    try:
        # BASELINE GATE (fail-closed): rc != 0 on the UNMUTATED file means every
        # mutant would trivially score KILLED — a false perfect score.
        rc = _run_test(test_cmd, cwd, env)
        if rc != 0:
            raise BaselineNotGreenError(
                f"baseline is not green — mutation results would be meaningless "
                f"(the test command exited {rc} on the UNMUTATED file; a red "
                f"baseline scores every mutant KILLED, a false perfect score). "
                f"Fix the tests/env first.")
        try:
            for m in mutants:
                file_path.write_text(m["source"], encoding="utf-8")
                rc = _run_test(test_cmd, cwd, env)
                status = "SURVIVED" if rc == 0 else "KILLED"
                results.append({"desc": m["desc"], "line": m["line"], "status": status})
        finally:
            file_path.write_text(original, encoding="utf-8")  # ALWAYS restore
        # POST-RUN INTEGRITY RE-CHECK: the restored tree must still be green —
        # red here means the run left the tree or its state dirty.
        rc = _run_test(test_cmd, cwd, env)
        if rc != 0:
            raise PostRunIntegrityError(
                f"post-run integrity check FAILED — the baseline is no longer "
                f"green after the final restore (the test command exited {rc}); "
                f"the run left the tree or its state dirty, so these results "
                f"cannot be trusted.")
    finally:
        shutil.rmtree(pyc_root, ignore_errors=True)
    return results


def render(results: list[dict], file_path: Path) -> str:
    survived = [r for r in results if r["status"] == "SURVIVED"]
    out = ["── wf mutate — mutation-testing gate ──────────────────────────"]
    out.append(f"file:    {file_path}")
    out.append(f"mutants: {len(results)}   killed: {len(results) - len(survived)}   "
               f"SURVIVED: {len(survived)}")
    out.append("")
    if not results:
        out.append("no mutable operators found (nothing to test).")
    for r in results:
        mark = "·SURVIVED" if r["status"] == "SURVIVED" else "✓killed  "
        out.append(f"  {mark}  {r['desc']}")
    if survived:
        out.append("")
        out.append("SURVIVED mutants = the tests still PASS with this operator flipped, "
                   "so they do NOT pin that behavior (tautological/weak). Strengthen the "
                   "assertion. NOTE: a minimal operator set is a FLOOR, not a full "
                   "mutation score.")
    out.append("───────────────────────────────────────────────────────────────")
    return "\n".join(out)


def selftest() -> int:
    problems: list[str] = []

    # 1. mutate_source is pure + token-precise: a comparison + a boolean flip are
    #    generated; an operator INSIDE a string literal is NOT mutated.
    src = ('def f(x):\n'
           '    s = "a == b and c"   # operators in this string must NOT mutate\n'
           '    return x > 0 and x != 5\n')
    muts = mutate_source(src)
    descs = " | ".join(m["desc"] for m in muts)
    if "'>' -> '<='" not in descs:
        problems.append(f"1: comparison '>' not mutated: {descs}")
    if "'and' -> 'or'" not in descs:
        problems.append(f"1: boolean 'and' not mutated: {descs}")
    if "'!=' -> '=='" not in descs:
        problems.append(f"1: comparison '!=' not mutated: {descs}")
    # the string literal's `==`/`and` are on line 2; none of those columns mutate.
    if any(m["line"] == 2 for m in muts):
        problems.append("1: an operator inside a string literal was mutated (token-unsafe)")

    # 2. end-to-end: a STRONG test KILLS the `>` mutant; a TAUTOLOGICAL test lets a
    #    mutant SURVIVE; the file is restored afterward.
    with tempfile.TemporaryDirectory() as dd:
        proj = Path(dd)
        mod = proj / "mod.py"
        mod.write_text("def is_pos(x):\n    return x > 0\n")
        before = mod.read_text()
        strong = ('python3 -c "import sys; sys.path.insert(0, \'.\'); '
                  'import mod; assert mod.is_pos(1) and not mod.is_pos(-1)"')
        res_strong = run_mutation_testing(mod, strong, cwd=proj)
        if mod.read_text() != before:
            problems.append("2: file not restored after a mutation run (UNSAFE)")
        if not res_strong or not any(r["status"] == "KILLED" for r in res_strong):
            problems.append(f"2: a strong test did not KILL any mutant: {res_strong}")
        # tautological test: always passes -> every mutant SURVIVES.
        weak = 'python3 -c "assert True"'
        res_weak = run_mutation_testing(mod, weak, cwd=proj)
        if not res_weak or not all(r["status"] == "SURVIVED" for r in res_weak):
            problems.append(f"2: a tautological test should leave every mutant SURVIVED: {res_weak}")
        # the render names the survivors loudly.
        rep = render(res_weak, mod)
        if "SURVIVED" not in rep or "tautological" not in rep:
            problems.append("2: render did not surface survivors / the tautology note")

    # 3. --lines filtering: only mutants on the requested line survive the filter.
    multi = "a = 1 == 2\nb = 3 < 4\n"
    m_all = mutate_source(multi)
    line2 = [m for m in m_all if _in_range(m["line"], "2")]
    if not line2 or any(m["line"] != 2 for m in line2):
        problems.append(f"3: --lines range filter wrong: {[m['line'] for m in line2]}")

    # 4. RED BASELINE aborts fail-closed (defect-1 fix): the tool must never
    #    score mutants against a broken suite — a red baseline would report
    #    every mutant KILLED, a false perfect score.
    with tempfile.TemporaryDirectory() as dd:
        proj = Path(dd)
        mod = proj / "mod.py"
        mod.write_text("def is_pos(x):\n    return x > 0\n")
        before = mod.read_text()
        red = 'python3 -c "raise SystemExit(1)"'
        try:
            res_red = run_mutation_testing(mod, red, cwd=proj)
            problems.append(f"4: red baseline did NOT abort (scored: {res_red})")
        except BaselineNotGreenError as e:
            if "baseline is not green" not in str(e):
                problems.append(f"4: red-baseline abort lacks the clear message: {e}")
        if mod.read_text() != before:
            problems.append("4: file not restored after a red-baseline abort (UNSAFE)")
        # end-to-end teeth: the CLI itself must exit non-zero, say why on
        # stderr, and print NO mutant report (no 'killed' count) on stdout.
        proc = subprocess.run([sys.executable, __file__, str(mod), "--test", red],
                              capture_output=True, text=True, cwd=str(proj))
        if proc.returncode == 0:
            problems.append("4: CLI exited 0 on a red baseline (must be non-zero)")
        if "baseline is not green" not in proc.stderr:
            problems.append(f"4: CLI stderr lacks the red-baseline message: {proc.stderr!r}")
        if "killed" in proc.stdout.lower():
            problems.append(f"4: CLI reported mutants killed on a red baseline: {proc.stdout!r}")

    # 5. ISOLATION ENV is actually applied (defect-2 fix): the test subprocess
    #    must see PYTHONDONTWRITEBYTECODE=1 and a set PYTHONPYCACHEPREFIX that
    #    is the SAME within a run (per-run tempdir) and DIFFERENT across runs.
    #    The probe asserts the env itself — if the env were missing, the probe
    #    would exit non-zero and the baseline gate would flag it right here.
    with tempfile.TemporaryDirectory() as dd:
        proj = Path(dd)
        mod = proj / "mod.py"
        mod.write_text("def is_pos(x):\n    return x > 0\n")
        probe = ('python3 -c "import os; '
                 "assert os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'; "
                 "p = os.environ.get('PYTHONPYCACHEPREFIX'); assert p; "
                 "open('seen.txt', 'a').write(p + chr(10))\"")
        try:
            for _ in (1, 2):
                run_mutation_testing(mod, probe, cwd=proj, max_mutants=1)
        except (BaselineNotGreenError, PostRunIntegrityError) as e:
            problems.append(f"5: isolation env not applied to the test subprocess: {e}")
        else:
            prefixes = (proj / "seen.txt").read_text().splitlines()
            # 2 runs x (baseline + 1 mutant + post-run re-check) = 6 probe hits.
            if len(prefixes) != 6:
                problems.append(f"5: expected 6 isolated test invocations, saw {len(prefixes)}")
            elif not (len(set(prefixes[:3])) == 1 and len(set(prefixes[3:])) == 1
                      and prefixes[0] != prefixes[3]):
                problems.append(f"5: PYTHONPYCACHEPREFIX not per-run unique: {prefixes}")
            elif "wf-mutate-pyc-" not in prefixes[0]:
                problems.append(f"5: PYTHONPYCACHEPREFIX is not the per-run tempdir: {prefixes[0]}")

    # 6. POST-RUN INTEGRITY re-check fires on a dirty end-state: a stateful
    #    test command goes green (baseline), green (mutant), then RED on the
    #    post-run re-check — simulating a run that left its state dirty.
    with tempfile.TemporaryDirectory() as dd:
        proj = Path(dd)
        mod = proj / "mod.py"
        mod.write_text("def is_pos(x):\n    return x > 0\n")
        before = mod.read_text()
        dirty = ('python3 -c "import os, sys; '
                 "n = int(open('n.txt').read()) if os.path.exists('n.txt') else 0; "
                 "open('n.txt', 'w').write(str(n + 1)); sys.exit(0 if n < 2 else 1)\"")
        try:
            run_mutation_testing(mod, dirty, cwd=proj, max_mutants=1)
            problems.append("6: post-run integrity re-check did NOT fire on a dirty end-state")
        except PostRunIntegrityError as e:
            if "no longer green" not in str(e):
                problems.append(f"6: integrity failure lacks the clear message: {e}")
        except BaselineNotGreenError as e:
            problems.append(f"6: baseline gate misfired on a green baseline: {e}")
        if mod.read_text() != before:
            problems.append("6: file not restored after an integrity failure (UNSAFE)")

    if problems:
        print("wf mutate selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf mutate selftest: PASS (token-precise operator mutation skips string "
          "literals; a strong test KILLS the boundary mutant while a tautological "
          "test leaves every mutant SURVIVED; the file is always restored; --lines "
          "scoping works; survivors are surfaced as the tautology signal; a RED "
          "baseline ABORTS fail-closed with no mutants scored and a non-zero CLI "
          "exit; every test subprocess runs bytecode-isolated with "
          "PYTHONDONTWRITEBYTECODE=1 and a per-run-unique PYTHONPYCACHEPREFIX; "
          "the post-run integrity re-check fails loudly on a dirty end-state)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="wf mutate",
        description="Minimal mutation-testing gate: mutate an operator, re-run the "
                    "tests; a SURVIVING mutant means the tests don't pin that behavior.")
    ap.add_argument("file", nargs="?", help="the Python source file to mutate")
    ap.add_argument("--test", default=None, help="the test command to run per mutant")
    ap.add_argument("--lines", default=None, help="restrict to a line range A-B (e.g. a diff's changed lines)")
    ap.add_argument("--max", type=int, default=None, help="cap the number of mutants")
    ap.add_argument("--block", action="store_true",
                    help="exit non-zero if any mutant SURVIVED (default: WARN-only)")
    ap.add_argument("--selftest", action="store_true", help="run the selftest")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.file:
        ap.error("a source file is required (or use --selftest)")
    if not args.test:
        ap.error("--test '<command>' is required (how to run the tests per mutant)")
    path = Path(args.file)
    if not path.is_file():
        _die(f"file not found: {path}")
    if path.suffix != ".py":
        _die(f"v1 supports Python (.py) only; got {path.suffix or 'no suffix'}")

    try:
        results = run_mutation_testing(path, args.test, cwd=Path.cwd(),
                                       lines_spec=args.lines, max_mutants=args.max)
    except (BaselineNotGreenError, PostRunIntegrityError) as e:
        _die(str(e))  # fail-closed: never print a mutant score off a bad run
    print(render(results, path))
    if args.block and any(r["status"] == "SURVIVED" for r in results):
        n = sum(1 for r in results if r["status"] == "SURVIVED")
        print(f"\nwf mutate: BLOCK — {n} mutant(s) SURVIVED (tests don't pin that "
              f"behavior). Strengthen the assertions before calling the tests done.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
