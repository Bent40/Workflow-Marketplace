#!/usr/bin/env python3
"""wf-memory.py — project memory pack: scaffold, validate, and report on the
structured memory/ files that let a new session resume instantly. Epic B / RD-1.

Driven by core/memory/memory-contract.yaml (the file set + required sections).
  init    — scaffold any MISSING memory file from the contract (idempotent;
            never overwrites an existing file).
  check   — fail-closed: every file exists and every required section is present.
  refresh — ADVISORY packet (empty sections, TODO placeholders, empty Next
            actions, empty Decisions). Never writes anything.

Exit codes: check → 0 ok / 1 violations / 2 contract error.
            init/refresh → 0 (2 on contract error).

Usage:
    wf memory init|check|refresh [--dir PATH]
    wf memory --selftest
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("wf memory: PyYAML not available; cannot parse contract\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = REPO_ROOT / "core" / "memory" / "memory-contract.yaml"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
PLACEHOLDER_RE = re.compile(r"\(?(TODO|TBD|FIXME)\b", re.I)


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf memory: {msg}\n")
    raise SystemExit(code)


def load_contract() -> dict[str, dict]:
    if not CONTRACT.is_file():
        _die(f"contract not found: {CONTRACT}")
    try:
        data = yaml.safe_load(CONTRACT.read_text())
    except yaml.YAMLError as e:
        _die(f"memory-contract.yaml: invalid YAML: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict) \
            or not data["files"]:
        _die("memory-contract.yaml: must have a non-empty 'files' mapping")
    files: dict[str, dict] = {}
    for name, spec in data["files"].items():
        if not isinstance(spec, dict):
            _die(f"memory-contract.yaml: '{name}' must be a mapping")
        secs = spec.get("required_sections")
        if not isinstance(secs, list) or not secs or \
                not all(isinstance(s, str) and s.strip() for s in secs):
            _die(f"memory-contract.yaml: '{name}' needs a non-empty "
                 f"required_sections list")
        files[name] = {
            "title": str(spec.get("title", name)).strip(),
            "description": str(spec.get("description", "")).strip(),
            "required_sections": secs,
        }
    return files


def _section_spans(lines: list[str]) -> dict[str, tuple[int, int]]:
    """name(lower) -> (first content line idx, end idx) for each SECTION heading.

    Only level >= 2 headings (`##`+) count as sections, so the file's H1 title
    (e.g. `# Open Risks`) never shadows a same-named required section
    (`## Open risks`). A section's body extends to the next heading of the SAME
    or HIGHER rank, so deeper subheadings (a `### subtask` under `## Done`) stay
    inside the section body rather than truncating it."""
    heads = [(i, len(m.group(1)), m.group(2).strip())
             for i, ln in enumerate(lines) for m in [HEADING_RE.match(ln)]
             if m and len(m.group(1)) >= 2]
    spans: dict[str, tuple[int, int]] = {}
    for k, (idx, lvl, text) in enumerate(heads):
        end = len(lines)
        for j in range(k + 1, len(heads)):
            if heads[j][1] <= lvl:
                end = heads[j][0]
                break
        spans.setdefault(text.lower(), (idx + 1, end))
    return spans


def _scaffold(spec: dict) -> str:
    out = [f"# {spec['title']}", "",
           "<!-- wf memory: required sections below; keep the headings. -->", ""]
    for s in spec["required_sections"]:
        out += [f"## {s}", "", "_TODO._", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def compute_check(mem_dir: Path, contract: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    for name, spec in contract.items():
        path = mem_dir / name
        if not path.is_file():
            problems.append(f"{name}: file not found")
            continue
        spans = _section_spans(path.read_text().splitlines())
        for s in spec["required_sections"]:
            if s.lower() not in spans:
                problems.append(f'{name}: missing section "{s}"')
    return problems


def compute_refresh(mem_dir: Path, contract: dict[str, dict]) -> list[tuple[str, list[str]]]:
    report: list[tuple[str, list[str]]] = []
    for name, spec in contract.items():
        path = mem_dir / name
        if not path.is_file():
            report.append((name, ["file not found — run `wf memory init`"]))
            continue
        lines = path.read_text().splitlines()
        spans = _section_spans(lines)
        findings: list[str] = []
        for s in spec["required_sections"]:
            span = spans.get(s.lower())
            if span is None:
                findings.append(f'section "{s}" missing')
                continue
            body = [ln for ln in lines[span[0]:span[1]]
                    if ln.strip() and not ln.strip().startswith("<!--")]
            real = [ln for ln in body if not PLACEHOLDER_RE.match(ln.strip().strip("_*`> -"))]
            if not body:
                findings.append(f'section "{s}" is empty')
            elif not real:
                findings.append(f'section "{s}" still has a TODO placeholder')
        if findings:
            report.append((name, findings))
    return report


def cmd_init(mem_dir: Path, contract: dict[str, dict], quiet: bool = False) -> int:
    mem_dir.mkdir(parents=True, exist_ok=True)
    for name, spec in contract.items():
        path = mem_dir / name
        if path.exists():
            if not quiet:
                print(f"skip  {path} (exists)")
            continue
        path.write_text(_scaffold(spec))
        if not quiet:
            print(f"wrote {path}")
    return 0


def cmd_check(mem_dir: Path, contract: dict[str, dict], quiet: bool = False) -> int:
    problems = compute_check(mem_dir, contract)
    if not quiet:
        for name in contract:
            n = sum(1 for p in problems if p.startswith(f"{name}:"))
            if n == 0 and (mem_dir / name).is_file():
                total = len(contract[name]["required_sections"])
                print(f"OK   {mem_dir / name} ({total}/{total} sections)")
        for p in problems:
            print(f"FAIL {mem_dir}/{p}")
        if problems:
            print(f"memory check: {len(problems)} problem(s).")
        else:
            print(f"memory check: OK ({len(contract)} files).")
    return 1 if problems else 0


def cmd_refresh(mem_dir: Path, contract: dict[str, dict], quiet: bool = False) -> int:
    report = compute_refresh(mem_dir, contract)
    if not quiet:
        print("── memory refresh ────────────────────────────────────────────")
        if not report:
            print("no findings — memory looks complete.")
        for name, findings in report:
            print(name)
            for f in findings:
                print(f"  - {f}")
        if report:
            print("suggested_next_step:")
            print("  Fill the empty/placeholder sections (especially Next "
                  "actions) before ending the session.")
        print("───────────────────────────────────────────────────────────────")
    return 0


def selftest() -> int:
    contract = load_contract()
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as dd:
        d = Path(dd) / "memory"
        cmd_init(d, contract, quiet=True)
        if cmd_check(d, contract, quiet=True) != 0:
            problems.append("check after init was not green")
        # init is idempotent: a 2nd init leaves files untouched
        marker = d / "current-state.md"
        marker.write_text(marker.read_text() + "\nEDITED\n")
        cmd_init(d, contract, quiet=True)
        if "EDITED" not in marker.read_text():
            problems.append("init overwrote an existing file (not idempotent)")
        # removing a required section must FAIL check
        f = d / "open-risks.md"
        f.write_text(f.read_text().replace("## Open risks", "## Risks"))
        if cmd_check(d, contract, quiet=True) != 1:
            problems.append("check did not fail on a missing section")
        # a missing file must FAIL check
        (d / "next-actions.md").unlink()
        probs = compute_check(d, contract)
        if not any("next-actions.md: file not found" in p for p in probs):
            problems.append("check did not flag the missing file")
        # refresh on a fresh all-TODO pack must report findings
        with tempfile.TemporaryDirectory() as dd2:
            d2 = Path(dd2) / "memory"
            cmd_init(d2, contract, quiet=True)
            if not compute_refresh(d2, contract):
                problems.append("refresh found nothing on an all-TODO pack")
            # and a filled section must NOT be flagged
            cs = d2 / "next-actions.md"
            cs.write_text("# Next Actions\n\n## Next actions\n\n- Ship Epic B\n")
            na = [f for n, fs in compute_refresh(d2, contract)
                  if n == "next-actions.md" for f in fs]
            if na:
                problems.append(f"refresh wrongly flagged a filled section: {na}")
            # a section with real content under a deeper ### subheading must NOT
            # be flagged empty (level-aware span)
            cur = d2 / "current-state.md"
            cur.write_text("# Current State\n\n## Done\n\n### subtask\n\n"
                           "- finished the thing\n\n## In progress\n\n_TODO._\n"
                           "\n## Next\n\n_TODO._\n\n## Blockers\n\n_TODO._\n")
            done = [f for n, fs in compute_refresh(d2, contract)
                    if n == "current-state.md" for f in fs if "Done" in f]
            if done:
                problems.append(f"refresh flagged a section with nested content: {done}")
    if problems:
        print("wf memory selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf memory selftest: PASS (init idempotent, check fail-closed, "
          "refresh advisory findings)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf memory")
    ap.add_argument("action", nargs="?", choices=["init", "check", "refresh"])
    ap.add_argument("--dir", default=None, help="memory dir (default: ./memory)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("an action (init|check|refresh) or --selftest is required")
    contract = load_contract()
    mem_dir = Path(args.dir) if args.dir else Path.cwd() / "memory"
    return {"init": cmd_init, "check": cmd_check,
            "refresh": cmd_refresh}[args.action](mem_dir, contract)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
