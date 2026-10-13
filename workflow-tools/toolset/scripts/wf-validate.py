#!/usr/bin/env python3
"""wf-validate.py — run a project's declared validation commands and, on
failure, emit a structured repair-handoff packet. Epic D / RD-1.

Reads `validation:` from a project-level bmad.config.yaml (a mapping of
category -> ordered list of shell commands), runs each command, and reports
pass/fail. With --repair-handoff, each FAILING command also produces a
deterministic packet (command, exit_code, relevant_failure_lines,
likely_affected_files, suggested_next_microtask). This is a HANDOFF, never an
autofix loop — wf runs nothing it was not told to, and changes no files.

Exit codes: 0 = all commands passed; 1 = at least one command failed;
            2 = config missing/invalid (fail-closed, distinct from a check
                that ran and failed).

Usage:
    wf validate [--config PATH] [--repair-handoff]
    wf validate --selftest
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("wf validate: PyYAML not available; cannot parse config\n")
    sys.exit(2)

MAX_FAILURE_LINES = 12
MAX_FILES = 8

# A line is "relevant" if it carries an error marker or a file:line locator.
ERROR_RE = re.compile(
    r"(\berror\b|\berrors\b|\bfailed\b|\bfail\b|\bexception\b|traceback"
    r"|\bE\d{2,4}\b|[\w./-]+\.[A-Za-z]{1,8}:\d+|✕|✗)", re.I)
# A file-path-like token with an optional :line(:col). Extension is allowlisted
# (allowlist, not denylist) so noise like "e.g." or "v1.0" is not treated as a file.
FILE_RE = re.compile(r"([A-Za-z0-9_./-]+\.[A-Za-z]{1,8})(?::(\d+)(?::\d+)?)?")
CODE_EXT = re.compile(
    r"\.(py|js|jsx|ts|tsx|go|rs|java|rb|c|cc|cpp|h|hpp|cs|php|sql|ya?ml|json"
    r"|md|sh|css|s?html?|vue|kt|swift|scala|toml|ini|cfg|txt|xml|gradle|lock)$",
    re.I)


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf validate: {msg}\n")
    raise SystemExit(code)


def load_validation(config_path: Path) -> list[tuple[str, list[str]]]:
    """Parse + fail-closed-validate the `validation:` block. Returns an ordered
    list of (category, [commands]) in the file's declared order."""
    if not config_path.is_file():
        _die(f"config not found: {config_path} "
             f"(pass --config PATH or add bmad.config.yaml)")
    try:
        data = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as e:
        _die(f"{config_path.name}: invalid YAML: {e}")
    if not isinstance(data, dict) or "validation" not in data:
        _die(f"{config_path.name}: missing top-level 'validation' mapping")
    val = data["validation"]
    if not isinstance(val, dict) or not val:
        _die("'validation' must be a non-empty mapping of category -> [commands]")
    items: list[tuple[str, list[str]]] = []
    for cat, cmds in val.items():
        if not isinstance(cat, str) or not cat.strip():
            _die("validation category names must be non-empty strings")
        if not isinstance(cmds, list) or not cmds or \
                not all(isinstance(c, str) and c.strip() for c in cmds):
            _die(f"validation category '{cat}' must be a non-empty list of "
                 f"non-empty command strings")
        items.append((cat, cmds))
    return items


def _is_file_token(p: str) -> bool:
    # Allowlist by code/config extension, and reject URL-ish tokens so a URL in
    # failure output (e.g. https://host/page.html) is never mistaken for a source
    # file in the handoff hint.
    if "://" in p or p.startswith("//"):
        return False
    return bool(CODE_EXT.search(p))


def relevant_failure_lines(output: str) -> list[str]:
    lines = [ln.rstrip() for ln in output.splitlines()
             if ln.strip() and ERROR_RE.search(ln)]
    return lines[:MAX_FAILURE_LINES]


def likely_affected_files(lines: list[str]) -> list[str]:
    files: list[str] = []
    for ln in lines:
        for m in FILE_RE.finditer(ln):
            p = m.group(1)
            if _is_file_token(p) and p not in files:
                files.append(p)
    return files[:MAX_FILES]


def _first_loc(file: str, lines: list[str]) -> str:
    for ln in lines:
        m = re.search(re.escape(file) + r":(\d+)", ln)
        if m:
            return f"{file}:{m.group(1)}"
    return file


def build_packet(category: str, command: str, exit_code: int, output: str) -> str:
    lines = relevant_failure_lines(output)
    files = likely_affected_files(lines)
    top = _first_loc(files[0], lines) if files else "(see command output)"
    first = lines[0].strip() if lines else "(no parseable error line)"
    out = [
        "── repair handoff ────────────────────────────────────────────",
        f"command:                 {command}",
        f"category:                {category}",
        f"exit_code:               {exit_code}",
        "relevant_failure_lines:",
    ]
    out += [f"  - {ln.strip()}" for ln in lines] or \
        ["  - (none parsed; see full command output above)"]
    out.append("likely_affected_files:")
    out += [f"  - {f}" for f in files] or ["  - (none parsed)"]
    out += [
        "suggested_next_microtask:",
        f"  Fix the `{category}` failure: start at {top}",
        f'  ("{first}"). Re-run `{command}` to confirm, then re-run '
        f"`wf validate`.",
        "───────────────────────────────────────────────────────────────",
    ]
    return "\n".join(out)


def run_validation(items: list[tuple[str, list[str]]], cwd: Path,
                   repair: bool, quiet: bool = False) -> int:
    total = 0
    failed: list[tuple[str, str, int, str]] = []
    for cat, cmds in items:
        for i, cmd in enumerate(cmds):
            total += 1
            proc = subprocess.run(cmd, shell=True, cwd=str(cwd),
                                  capture_output=True, text=True)
            output = (proc.stdout or "") + (proc.stderr or "")
            ok = proc.returncode == 0
            if not quiet:
                extra = "" if ok else f"  (exit {proc.returncode})"
                print(f"{'PASS' if ok else 'FAIL'}  {cat}[{i}]  {cmd}{extra}")
            if not ok:
                failed.append((cat, cmd, proc.returncode, output))
    if failed:
        if not quiet:
            print(f"validate: {len(failed)} of {total} command(s) failed.")
            if repair:
                print()
                for cat, cmd, rc, output in failed:
                    print(build_packet(cat, cmd, rc, output))
                    print()
        return 1
    if not quiet:
        print(f"validate: all {total} command(s) passed.")
    return 0


def selftest() -> int:
    py = sys.executable
    problems: list[str] = []
    # 1. schema fail-closed + valid parse
    with tempfile.TemporaryDirectory() as dd:
        d = Path(dd)
        bad = d / "bad.yaml"
        bad.write_text("validation: not_a_mapping\n")
        try:
            load_validation(bad)
            problems.append("malformed config did not fail closed")
        except SystemExit as e:
            if e.code != 2:
                problems.append(f"malformed config exit {e.code}, expected 2")
        missing = d / "nope.yaml"
        try:
            load_validation(missing)
            problems.append("missing config did not fail closed")
        except SystemExit as e:
            if e.code != 2:
                problems.append(f"missing config exit {e.code}, expected 2")
        good = d / "good.yaml"
        good.write_text('validation:\n  lint:\n    - "echo ok"\n')
        if load_validation(good) != [("lint", ["echo ok"])]:
            problems.append("valid config parsed incorrectly")
    # 2. all-pass run -> 0
    ok_items = [("good", [f"{py} -c \"print('ok')\""])]
    if run_validation(ok_items, Path.cwd(), False, quiet=True) != 0:
        problems.append("all-pass run did not exit 0")
    # 3. failing run -> 1
    fail_cmd = (f"{py} -c \"import sys; "
                f"sys.stderr.write('fixture.py:3: Error: boom\\n'); sys.exit(1)\"")
    if run_validation([("bad", [fail_cmd])], Path.cwd(), False, quiet=True) != 1:
        problems.append("failing run did not exit 1")
    # 4. packet carries all 5 fields + extracts the affected file
    packet = build_packet("lint", "npm run lint", 1,
                          "src/api/users.js:42:7  error  'token' is unused\n")
    for field in ("command:", "exit_code:", "relevant_failure_lines:",
                  "likely_affected_files:", "suggested_next_microtask:"):
        if field not in packet:
            problems.append(f"packet missing field {field}")
    if "src/api/users.js" not in packet:
        problems.append("packet did not extract the affected file")
    # 5. a URL in failure output must NOT be mistaken for an affected file
    files = likely_affected_files(["see https://example.com/docs/page.html",
                                   "tests/test_x.py:5: AssertionError"])
    if any("example.com" in f for f in files):
        problems.append("URL leaked into likely_affected_files")
    if "tests/test_x.py" not in files:
        problems.append("real file not extracted alongside a URL")
    if problems:
        print("wf validate selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf validate selftest: PASS (schema fail-closed, pass/fail runs, "
          "5-field repair packet)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf validate")
    ap.add_argument("--config", default=None,
                    help="path to bmad.config.yaml (default: ./bmad.config.yaml)")
    ap.add_argument("--repair-handoff", action="store_true",
                    help="on failure, emit a structured repair packet per failing command")
    ap.add_argument("--selftest", action="store_true", help="run the selftest")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    config_path = Path(args.config) if args.config else Path.cwd() / "bmad.config.yaml"
    items = load_validation(config_path)
    return run_validation(items, config_path.parent, args.repair_handoff)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
