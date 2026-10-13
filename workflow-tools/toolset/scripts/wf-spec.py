#!/usr/bin/env python3
"""wf-spec.py — mechanical spec scaffold + validation, gated by the
constitution. Epic C / C1+C2.

Composes with (never replaces) the BMAD authoring skills (bmad-spec, bmad-prd):
those own the authoring conversation; this owns the deterministic scaffold + gate.

  init    <feature>   scaffold specs/<feature>/{spec,plan,tasks,acceptance}.md
  check   <feature>   fail-closed: required sections present, acceptance.md
                      acknowledges every constitution constraint ACTIVE for the
                      profile (every shipped constraint is `default`),
                      AND no unresolved [NEEDS CLARIFICATION] marker remains.
  markers <feature>   fail-closed scan for unresolved [NEEDS CLARIFICATION]
          | --path P   markers in a spec folder or a single file. The marker is
                      bmad-spec's inline signal (Spec Law rule 9) for a
                      load-bearing gap that downstream must not silently pass.
  analyze <feature>   read-only PRE-implement readiness sweep: requirement→task
          [--block]   coverage map + cross-artifact consistency, graded
          [--since P] CRITICAL/HIGH/MEDIUM/LOW. Advisory by default; --block exits
                      1 while a CRITICAL/HIGH finding remains. --since PRIOR diffs
                      load-bearing IDs vs a prior spec — a dropped CAP/REQ id (no
                      RETIRED record) or a retired-id reuse on a same-slug update is
                      CRITICAL. Mutates nothing. (Complements check's binary gate and
                      wf audit's post-impl diff surfacer — grades the static pack.)
  split   <feature>   feed tasks.md → split-task.py microtask packets.

The constitution (core/constitution/*.yaml) keeps an `activation` field per
constraint; only `default` exists since the secure posture (and its `secure_only`
constraints) was removed 2026-10-13 (core/DECISIONS.md D6).

Exit codes: check → 0 ok / 1 violations / 2 config error. init/split → 0 (2 on error).

Usage:
    wf spec init|check|split <feature> [--dir ROOT] [--profile civilian]
    wf spec analyze <feature> [--block] [--since PRIOR] [--dir ROOT] [--profile ...]
    wf spec markers (<feature> | --path PATH) [--dir ROOT]
    wf spec --selftest
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
    sys.stderr.write("wf spec: PyYAML not available; cannot parse constitution\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
CONSTITUTION_DIR = REPO_ROOT / "core" / "constitution"
VALID_ACT = {"default"}
VALID_SEV = {"low", "medium", "high"}

SPEC_FILES = {
    "spec.md": {"title": "Spec", "sections": ["Goal", "Requirements", "Out of scope"]},
    "plan.md": {"title": "Plan", "sections": ["Approach"]},
    "tasks.md": {"title": "Tasks", "sections": ["Tasks"]},
    "acceptance.md": {"title": "Acceptance",
                      "sections": ["Acceptance criteria", "Constitution acknowledgements"]},
}
HEADING_RE = re.compile(r"^(#{2,6})\s+(.*\S)\s*$")
ACK_RE = re.compile(r"^\s*[-*]\s*([A-Za-z][A-Za-z0-9]*-[A-Za-z0-9-]+)\s*:")
# bmad-spec's inline "load-bearing gap" marker (Spec Law rule 9). Tolerates a bare
# [NEEDS CLARIFICATION] and the [NEEDS CLARIFICATION: detail] form; case-insensitive.
MARKER_RE = re.compile(r"\[NEEDS\s+CLARIFICATION(?::[^\]]*)?\]", re.IGNORECASE)
# Requirement-ID namespace for the analyze coverage map. A requirement is a bullet
# under spec.md "Requirements" beginning with one of these IDs; a task "covers" a
# requirement when its line mentions that ID.
REQ_ID_RE = re.compile(r"\b((?:REQ|FR|NFR|R)-\d+)\b")
REQ_DEF_RE = re.compile(r"^\s*[-*]\s*(?:\[[ xX]\]\s*)?(?:\*\*)?((?:REQ|FR|NFR|R)-\d+)\b")
TASK_LINE_RE = re.compile(r"^\s*[-*]\s*(?:\[[ xX]\]\s*)?\S")
GLOSSARY_DEF_RE = re.compile(r"^\s*[-*]\s*(.+?)\s*\(not:\s*(.+?)\)\s*$", re.IGNORECASE)
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
# bmad-spec capability IDs (a SPEC.md kernel lists them as "- id: CAP-1") — these
# are load-bearing and ID-stable: never silently dropped, never reused once retired.
CAP_DEF_RE = re.compile(r"^\s*-\s*id:\s*(CAP-\d+)\b")
# A deliberate retirement/supersede record in .decision-log.md authorizes dropping
# (or forbids reusing) an ID: "RETIRED: CAP-3" or "SUPERSEDED: CAP-3 -> CAP-7".
RETIRE_RE = re.compile(r"(?:RETIRED|SUPERSEDED|RETIRE[SD]?)\s*[:=]\s*"
                       r"((?:CAP|REQ|FR|NFR|R)-\d+)", re.IGNORECASE)


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf spec: {msg}\n")
    raise SystemExit(code)


def load_constitution(dir: Path = CONSTITUTION_DIR) -> list[dict]:
    """Parse + fail-closed-validate all constitution constraints."""
    if not dir.is_dir():
        _die(f"constitution dir not found: {dir}")
    constraints: list[dict] = []
    ids: set[str] = set()
    files = sorted(dir.glob("*.yaml"))
    if not files:
        _die(f"no constitution files in {dir}")
    for f in files:
        try:
            data = yaml.safe_load(f.read_text())
        except yaml.YAMLError as e:
            _die(f"{f.name}: invalid YAML: {e}")
        if not isinstance(data, dict) or not isinstance(data.get("constraints"), list) \
                or not data["constraints"]:
            _die(f"{f.name}: must have a non-empty 'constraints' list")
        for c in data["constraints"]:
            if not isinstance(c, dict):
                _die(f"{f.name}: each constraint must be a mapping")
            cid = c.get("id")
            if not isinstance(cid, str) or not cid.strip():
                _die(f"{f.name}: a constraint is missing a string 'id'")
            if cid in ids:
                _die(f"duplicate constraint id: {cid}")
            ids.add(cid)
            if not isinstance(c.get("statement"), str) or not c["statement"].strip():
                _die(f"{cid}: missing 'statement'")
            if c.get("activation") not in VALID_ACT:
                _die(f"{cid}: activation must be one of {sorted(VALID_ACT)}")
            if c.get("severity") not in VALID_SEV:
                _die(f"{cid}: severity must be one of {sorted(VALID_SEV)}")
            constraints.append({"id": cid, "statement": c["statement"],
                                "activation": c["activation"], "severity": c["severity"],
                                "file": f.name})
    return constraints


def active_ids(constraints: list[dict], profile: str) -> list[str]:
    """Constraint ids active for a profile (civilian = every `default` one)."""
    return [c["id"] for c in constraints if c["activation"] == "default"]


def _sections(lines: list[str]) -> set[str]:
    return {m.group(2).strip().lower()
            for ln in lines for m in [HEADING_RE.match(ln)] if m}


def _acked_ids(text: str) -> set[str]:
    """Acknowledged ids, scoped to the 'Constitution acknowledgements' section
    only — an ack placed under any other heading does not count (the gate must
    be precise about where acknowledgements live)."""
    acked: set[str] = set()
    in_section = False
    sec_level = 0
    for ln in text.splitlines():
        m = HEADING_RE.match(ln)
        if m:
            if m.group(2).strip().lower() == "constitution acknowledgements":
                in_section, sec_level = True, len(m.group(1))
            elif in_section and len(m.group(1)) <= sec_level:
                in_section = False
            continue
        if in_section:
            am = ACK_RE.match(ln)
            if am:
                acked.add(am.group(1))
    return acked


def _section_lines(text: str, heading_lower: str) -> list[str]:
    """Content lines under the first heading whose text equals `heading_lower`
    (case-insensitive), up to the next heading of the same or higher level.
    The level-1 title (#) is not a heading here, so '# Tasks' never shadows the
    '## Tasks' section. Empty list if the heading is absent."""
    out: list[str] = []
    in_section = False
    sec_level = 0
    for ln in text.splitlines():
        m = HEADING_RE.match(ln)
        if m:
            if not in_section and m.group(2).strip().lower() == heading_lower:
                in_section, sec_level = True, len(m.group(1))
            elif in_section and len(m.group(1)) <= sec_level:
                break
            continue
        if in_section:
            out.append(ln)
    return out


def _requirements(spec_text: str) -> list[str]:
    """Requirement IDs declared under spec.md 'Requirements', in document order,
    duplicates preserved (the caller dedups and flags repeats)."""
    return [m.group(1) for ln in _section_lines(spec_text, "requirements")
            for m in [REQ_DEF_RE.match(ln)] if m]


def _glossary(spec_text: str) -> dict[str, str]:
    """Banned-synonym -> canonical term, from spec.md 'Glossary' entries shaped
    '- Canonical (not: synA, synB)'. Empty if there is no glossary."""
    banned: dict[str, str] = {}
    for ln in _section_lines(spec_text, "glossary"):
        m = GLOSSARY_DEF_RE.match(ln)
        if m:
            canonical = m.group(1).strip()
            for syn in (s.strip() for s in m.group(2).split(",")):
                if syn:
                    banned[syn.lower()] = canonical
    return banned


def _tasks(tasks_text: str) -> list[tuple[str, set[str]]]:
    """Each task bullet under tasks.md 'Tasks' as (stripped line, {req IDs it cites})."""
    return [(ln.strip(), set(REQ_ID_RE.findall(ln)))
            for ln in _section_lines(tasks_text, "tasks") if TASK_LINE_RE.match(ln)]


def scan_markers(target: Path) -> list[tuple[Path, int, str]]:
    """Every unresolved [NEEDS CLARIFICATION] marker in `target`, as
    (file, 1-based line, stripped line). `target` may be a single .md file or a
    directory (scanned recursively for *.md). Hidden files (e.g. .decision-log.md,
    which only RECORDS that a question was raised) are skipped, so the scan tracks
    the live contract, not its memory. A non-existent target yields no hits — the
    caller decides whether that is an error."""
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = sorted(p for p in target.rglob("*.md") if not p.name.startswith("."))
    else:
        return []
    hits: list[tuple[Path, int, str]] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, ln in enumerate(text.splitlines(), 1):
            if MARKER_RE.search(ln):
                hits.append((f, lineno, ln.strip()))
    return hits


def _scaffold(spec: dict, ack_ids: list[str] | None = None) -> str:
    out = [f"# {spec['title']}", "",
           "<!-- wf spec: keep the section headings. -->", ""]
    for s in spec["sections"]:
        out += [f"## {s}", ""]
        if s.lower() == "constitution acknowledgements" and ack_ids is not None:
            out += [f"- {cid}: TODO" for cid in ack_ids] + [""]
        else:
            out += ["_TODO._", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def cmd_init(feature_dir: Path, constraints: list[dict], quiet: bool = False) -> int:
    feature_dir.mkdir(parents=True, exist_ok=True)
    default_ids = [c["id"] for c in constraints if c["activation"] == "default"]
    for fname, spec in SPEC_FILES.items():
        path = feature_dir / fname
        if path.exists():
            if not quiet:
                print(f"skip  {path}")
            continue
        ack = default_ids if fname == "acceptance.md" else None
        path.write_text(_scaffold(spec, ack))
        if not quiet:
            print(f"wrote {path}")
    return 0


def compute_check(feature_dir: Path, profile: str, constraints: list[dict]) -> list[str]:
    problems: list[str] = []
    for fname, spec in SPEC_FILES.items():
        path = feature_dir / fname
        if not path.is_file():
            problems.append(f"{fname}: file not found")
            continue
        secs = _sections(path.read_text().splitlines())
        for s in spec["sections"]:
            if s.lower() not in secs:
                problems.append(f'{fname}: missing section "{s}"')
    acc = feature_dir / "acceptance.md"
    active = active_ids(constraints, profile)
    if acc.is_file():
        acked = _acked_ids(acc.read_text())
        for cid in active:
            if cid not in acked:
                problems.append(f"constitution: active constraint {cid} not "
                                f"acknowledged in acceptance.md")
    else:
        problems.append("constitution: acceptance.md missing — cannot verify "
                        "acknowledgements")
    for f, lineno, _ in scan_markers(feature_dir):
        try:
            rel = f.relative_to(feature_dir)
        except ValueError:  # pragma: no cover - feature_dir is always the root here
            rel = f
        problems.append(f"{rel}:{lineno}: unresolved [NEEDS CLARIFICATION] marker")
    return problems


def cmd_check(feature_dir: Path, profile: str, constraints: list[dict],
              quiet: bool = False) -> int:
    problems = compute_check(feature_dir, profile, constraints)
    if not quiet:
        for fname in SPEC_FILES:
            if (feature_dir / fname).is_file() and \
                    not any(p.startswith(f"{fname}:") for p in problems):
                print(f"OK   {feature_dir / fname}")
        for p in problems:
            print(f"FAIL {p}")
        n_active = len(active_ids(constraints, profile))
        if problems:
            print(f"spec check [{profile}]: {len(problems)} problem(s).")
        else:
            print(f"spec check [{profile}]: OK ({n_active} active constraint(s) "
                  f"acknowledged).")
    return 1 if problems else 0


def cmd_markers(target: Path, quiet: bool = False) -> int:
    """Fail-closed scan for unresolved [NEEDS CLARIFICATION] markers.
    0 = none found, 1 = one or more remain, 2 = target does not exist."""
    if not target.exists():
        _die(f"path not found: {target}")
    hits = scan_markers(target)
    base = target if target.is_dir() else target.parent
    if not quiet:
        for f, lineno, line in hits:
            try:
                rel = f.relative_to(base)
            except ValueError:
                rel = f
            print(f"FAIL {rel}:{lineno}: {line}")
        if hits:
            print(f"spec markers: {len(hits)} unresolved [NEEDS CLARIFICATION] "
                  f"marker(s) in {target}.")
        else:
            print(f"spec markers: OK (no unresolved markers in {target}).")
    return 1 if hits else 0


def _spec_ids(target: Path) -> set[str]:
    """Load-bearing, ID-stable identifiers in a spec: CAP-N from a SPEC.md kernel's
    Capabilities and REQ-/FR-/NFR-/R- from a spec.md Requirements list. `target` may
    be a spec directory (reads SPEC.md and/or spec.md) or a single .md file. Pure."""
    files = [target / "SPEC.md", target / "spec.md"] if target.is_dir() else [target]
    ids: set[str] = set()
    for f in files:
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        ids.update(m.group(1) for ln in text.splitlines()
                   for m in [CAP_DEF_RE.match(ln)] if m)
        ids.update(_requirements(text))  # REQ-/FR-/NFR-/R- under "Requirements"
    return ids


def _retired_ids(feature_dir: Path) -> set[str]:
    """IDs explicitly retired/superseded in the spec's .decision-log.md (if any)."""
    log = feature_dir / ".decision-log.md"
    if not log.is_file():
        return set()
    return {m.group(1).upper()
            for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()
            for m in [RETIRE_RE.search(ln)] if m}


def compute_id_regression(feature_dir: Path, since: Path) -> list[dict]:
    """Deterministic preservation gate for a same-slug spec UPDATE: diff the prior
    spec (`since`) against the current one and flag (1) a load-bearing ID dropped with
    no retire/supersede record, and (2) a retired ID reused — both silent regressions
    the LLM preservation passes (Spec Law rule 7/9) can miss while every other gate
    stays green. Findings use compute_analyze's shape. Pure (file diff, never git)."""
    prior = _spec_ids(since)
    current = _spec_ids(feature_dir)
    retired = _retired_ids(feature_dir)
    findings: list[dict] = []
    for cid in sorted(prior - current - retired):
        findings.append({"severity": "CRITICAL",
                         "message": f"load-bearing id {cid} was in the prior spec "
                                    f"({since}) but is dropped here with no RETIRED/"
                                    f"SUPERSEDED record in .decision-log.md"})
    for cid in sorted(current & retired):
        findings.append({"severity": "CRITICAL",
                         "message": f"id {cid} was retired (per .decision-log.md) but "
                                    f"reappears in the current spec — retired IDs are "
                                    f"never reused"})
    return findings


def compute_analyze(feature_dir: Path, profile: str,
                    constraints: list[dict], since: Path | None = None) -> list[dict]:
    """Read-only, pre-implement readiness sweep. Returns findings as
    {severity, message}, sorted CRITICAL→LOW. Mutates nothing.

    Distinct from `check` (the binary constitution-acknowledgement GATE) and from
    `wf audit` (the POST-implement diff surfacer): this grades a static spec pack
    BEFORE dev, and its core product is the requirement→task coverage map."""
    findings: list[dict] = []

    def add(sev: str, msg: str) -> None:
        findings.append({"severity": sev, "message": msg})

    # A bmad-spec KERNEL dir (SPEC.md, no lowercase pack) is not a malformed pack —
    # skip the pack-completeness + constitution-ack checks for it (both pack-specific);
    # the marker scan and the --since ID-regression still apply.
    kernel_mode = (feature_dir / "SPEC.md").is_file() and \
        not (feature_dir / "spec.md").is_file()
    texts: dict[str, str] = {}
    if not kernel_mode:
        for fname in SPEC_FILES:
            p = feature_dir / fname
            if p.is_file():
                texts[fname] = p.read_text(encoding="utf-8", errors="replace")
            else:
                add("CRITICAL", f"missing core artifact: {fname}")

    spec_text = texts.get("spec.md", "")
    tasks_text = texts.get("tasks.md", "")
    acc_text = texts.get("acceptance.md", "")

    # requirements inventory (+ duplicate detection)
    inventory: list[str] = []
    seen: set[str] = set()
    for rid in _requirements(spec_text):
        if rid in seen:
            add("HIGH", f"duplicate requirement id {rid} in spec.md Requirements")
        else:
            seen.add(rid)
            inventory.append(rid)
    if "spec.md" in texts and not inventory:
        add("HIGH", "no requirements with IDs (REQ-/FR-/NFR-/R-N) found in spec.md "
                    "Requirements — task coverage cannot be verified")

    # requirement → task coverage map
    tasks = _tasks(tasks_text)
    covered: set[str] = set()
    for _, refs in tasks:
        covered |= refs
    for rid in inventory:
        if rid not in covered:
            add("CRITICAL", f"requirement {rid} has zero task coverage (orphan requirement)")
    known = set(inventory)
    for line, refs in tasks:
        for d in sorted(refs - known):
            add("HIGH", f"task cites unknown requirement {d}: {line}")
        if not refs:
            add("LOW", f"task maps to no requirement (acceptable for infra/setup): {line}")

    # constitution readiness — GRADED by constraint severity (check is the binary gate)
    if not kernel_mode:
        acked = _acked_ids(acc_text) if "acceptance.md" in texts else set()
        sev_map = {"high": "CRITICAL", "medium": "HIGH", "low": "MEDIUM"}
        active = set(active_ids(constraints, profile))
        for c in constraints:
            if c["id"] in active and c["id"] not in acked:
                add(sev_map[c["severity"]],
                    f"constitution {c['id']} ({c['severity']}) not acknowledged in acceptance.md")

    # unresolved clarification markers (reuse the rule-9 scan)
    for f, lineno, _ in scan_markers(feature_dir):
        try:
            rel = f.relative_to(feature_dir)
        except ValueError:  # pragma: no cover
            rel = f
        add("HIGH", f"unresolved [NEEDS CLARIFICATION] marker at {rel}:{lineno}")

    # terminology drift vs the optional glossary
    banned = _glossary(spec_text)
    if banned:
        glossary_lines = set(_section_lines(spec_text, "glossary"))
        for fname in ("spec.md", "plan.md", "tasks.md"):
            for lineno, ln in enumerate(texts.get(fname, "").splitlines(), 1):
                if ln in glossary_lines:
                    continue
                for syn, canon in banned.items():
                    if re.search(rf"\b{re.escape(syn)}\b", ln, re.IGNORECASE):
                        add("MEDIUM", f"terminology drift in {fname}:{lineno}: "
                                      f"'{syn}' used; prefer '{canon}'")

    # same-slug UPDATE preservation gate (opt-in via --since): dropped / retired-reused IDs
    if since is not None:
        findings.extend(compute_id_regression(feature_dir, since))

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    return findings


def cmd_analyze(feature_dir: Path, profile: str, constraints: list[dict],
                block: bool = False, quiet: bool = False,
                since: Path | None = None) -> int:
    """Print the readiness sweep. Default is advisory (exit 0). With --block, exit 1
    while any CRITICAL or HIGH finding (the 'clear before implement' tiers) remains.
    With --since PRIOR, also diff load-bearing IDs vs the prior spec (dropped /
    retired-reused). Config errors fail closed earlier in load_constitution (exit 2)."""
    findings = compute_analyze(feature_dir, profile, constraints, since=since)
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    blockers = counts["CRITICAL"] + counts["HIGH"]
    if not quiet:
        for f in findings:
            print(f"{f['severity']:8} {f['message']}")
        n_active = len(active_ids(constraints, profile))
        print(f"spec analyze [{profile}]: {counts['CRITICAL']} critical, "
              f"{counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low "
              f"({n_active} active constraint(s)).")
        if not findings:
            print("spec analyze: OK (no findings).")
        elif block and blockers:
            print(f"spec analyze: BLOCK — {blockers} CRITICAL/HIGH finding(s) must "
                  f"clear before implement.")
        elif not block and blockers:
            print("spec analyze: advisory — re-run with --block to gate on CRITICAL/HIGH.")
    return 1 if (block and blockers) else 0


def cmd_split(feature_dir: Path) -> int:
    tasks = feature_dir / "tasks.md"
    if not tasks.is_file():
        _die(f"tasks.md not found in {feature_dir}")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "split-task.py"), str(tasks)]).returncode


def selftest() -> int:
    problems: list[str] = []
    constraints = load_constitution()  # real shipped constitution
    civ = set(active_ids(constraints, "civilian"))
    if not civ:
        problems.append("no active constitution constraint shipped (gate toothless)")
    with tempfile.TemporaryDirectory() as dd:
        fdir = Path(dd) / "specs" / "demo"
        cmd_init(fdir, constraints, quiet=True)
        if cmd_check(fdir, "civilian", constraints, quiet=True) != 0:
            problems.append("civilian check was not green after init")
        acc = fdir / "acceptance.md"
        # removing acceptance.md must FAIL
        acc.unlink()
        if cmd_check(fdir, "civilian", constraints, quiet=True) != 1:
            problems.append("check did not fail when acceptance.md was removed")
        # restore, then drop one default ack -> FAIL
        cmd_init(fdir, constraints, quiet=True)  # recreates only acceptance.md
        default_ids = [c["id"] for c in constraints if c["activation"] == "default"]
        if default_ids:
            drop = default_ids[0]
            txt = (fdir / "acceptance.md").read_text()
            txt = "\n".join(l for l in txt.splitlines()
                            if not re.match(rf"^\s*[-*]\s*{re.escape(drop)}\s*:", l))
            (fdir / "acceptance.md").write_text(txt)
            if cmd_check(fdir, "civilian", constraints, quiet=True) != 1:
                problems.append(f"check did not fail on a missing ack ({drop})")
            # an ack placed OUTSIDE the acknowledgements section must NOT count
            mis = (fdir / "acceptance.md")
            mis.write_text(mis.read_text().replace(
                "## Acceptance criteria",
                f"## Acceptance criteria\n\n- {drop}: misplaced ack\n"))
            if cmd_check(fdir, "civilian", constraints, quiet=True) != 1:
                problems.append(f"a misplaced (out-of-section) ack satisfied the gate ({drop})")
    # marker scan: clean spec passes, an unresolved marker fails, hidden files skipped
    with tempfile.TemporaryDirectory() as dd:
        sdir = Path(dd) / "specs" / "spec-demo"
        sdir.mkdir(parents=True)
        (sdir / "SPEC.md").write_text("# Demo\n\n## Why\nReasons.\n")
        if cmd_markers(sdir, quiet=True) != 0:
            problems.append("marker scan flagged a clean spec")
        (sdir / "SPEC.md").write_text(
            "# Demo\n\n## Capabilities\n- id: CAP-1\n  intent: export reports "
            "[NEEDS CLARIFICATION: which formats?]\n")
        if cmd_markers(sdir, quiet=True) != 1:
            problems.append("marker scan missed an unresolved [NEEDS CLARIFICATION] marker")
        # the decision log RECORDS questions; it must not trip the live-contract scan
        (sdir / "SPEC.md").write_text("# Demo\n\n## Why\nReasons.\n")
        (sdir / ".decision-log.md").write_text("raised [NEEDS CLARIFICATION: x] earlier\n")
        if cmd_markers(sdir, quiet=True) != 0:
            problems.append("marker scan did not skip the hidden .decision-log.md")
    # the constitution check folds the marker scan in: a green pack with a marker fails
    with tempfile.TemporaryDirectory() as dd:
        fdir = Path(dd) / "specs" / "demo-markers"
        cmd_init(fdir, constraints, quiet=True)
        if cmd_check(fdir, "civilian", constraints, quiet=True) != 0:
            problems.append("baseline civilian check not green before marker fold-in test")
        sp = fdir / "spec.md"
        sp.write_text(sp.read_text() + "\nScope [NEEDS CLARIFICATION: which surfaces?].\n")
        if cmd_check(fdir, "civilian", constraints, quiet=True) != 1:
            problems.append("check did not fail on an unresolved marker in the pack")
    # analyze: graded pre-implement readiness sweep — the four canonical cases,
    # read-only, and the --block exit-code contract.
    with tempfile.TemporaryDirectory() as dd:
        adir = Path(dd) / "specs" / "demo-analyze"
        cmd_init(adir, constraints, quiet=True)  # default constraints acked, sections present
        full_tasks = ("# Tasks\n\n## Tasks\n- [ ] T1 build auth form (REQ-1)\n"
                      "- [ ] T2 add logout button (REQ-2)\n")
        (adir / "spec.md").write_text(
            "# Spec\n\n## Goal\nShip auth.\n\n## Requirements\n"
            "- REQ-1: users can sign-in\n- REQ-2: users can sign-out\n\n"
            "## Glossary\n- sign-in (not: login)\n\n## Out of scope\n- SSO\n")
        (adir / "tasks.md").write_text(full_tasks)
        # 1) fully covered, all constraints acked, no markers/drift -> no blockers
        f0 = compute_analyze(adir, "civilian", constraints)
        if any(x["severity"] in ("CRITICAL", "HIGH") for x in f0):
            problems.append(f"analyze flagged a clean pack: {[x['message'] for x in f0]}")
        # 2) orphan a requirement (drop its task) -> CRITICAL
        (adir / "tasks.md").write_text("# Tasks\n\n## Tasks\n- [ ] T1 build auth form (REQ-1)\n")
        f2 = compute_analyze(adir, "civilian", constraints)
        if not any(x["severity"] == "CRITICAL" and "REQ-2" in x["message"] for x in f2):
            problems.append("analyze missed orphaned requirement REQ-2 (expected CRITICAL)")
        (adir / "tasks.md").write_text(full_tasks)  # restore coverage
        # 3) un-ack a MUST (high-severity, default) constraint -> CRITICAL
        high_default = next((c["id"] for c in constraints
                             if c["activation"] == "default" and c["severity"] == "high"), None)
        if high_default:
            acc = adir / "acceptance.md"
            acc.write_text("\n".join(
                l for l in acc.read_text().splitlines()
                if not re.match(rf"^\s*[-*]\s*{re.escape(high_default)}\s*:", l)))
            f3 = compute_analyze(adir, "civilian", constraints)
            if not any(x["severity"] == "CRITICAL" and high_default in x["message"] for x in f3):
                problems.append(f"analyze missed un-acked MUST constraint {high_default} (expected CRITICAL)")
            acc.unlink()
            cmd_init(adir, constraints, quiet=True)  # restore the acks (only acceptance.md is missing)
        else:
            problems.append("no default high-severity constraint shipped (analyze MUST case toothless)")
        # 4) terminology drift via the glossary -> MEDIUM
        (adir / "plan.md").write_text("# Plan\n\n## Approach\nUse login throughout.\n")
        f4 = compute_analyze(adir, "civilian", constraints)
        if not any(x["severity"] == "MEDIUM" and "login" in x["message"] for x in f4):
            problems.append("analyze missed terminology drift ('login' vs 'sign-in', expected MEDIUM)")
        # read-only: a sweep must not mutate the pack
        before = {p.name: p.read_text() for p in sorted(adir.glob("*.md"))}
        cmd_analyze(adir, "civilian", constraints, block=True, quiet=True)
        after = {p.name: p.read_text() for p in sorted(adir.glob("*.md"))}
        if before != after:
            problems.append("analyze mutated the spec pack (must be read-only)")
        # exit-code contract: only MEDIUM left -> --block returns 0
        if cmd_analyze(adir, "civilian", constraints, block=True, quiet=True) != 0:
            problems.append("analyze --block failed on a pack with only MEDIUM findings")
        # re-introduce a CRITICAL orphan -> --block returns 1
        (adir / "tasks.md").write_text("# Tasks\n\n## Tasks\n- [ ] T1 only (REQ-1)\n")
        if cmd_analyze(adir, "civilian", constraints, block=True, quiet=True) != 1:
            problems.append("analyze --block did not fail with a CRITICAL orphan present")
    # same-slug UPDATE preservation gate (--since): dropped / retired-reused IDs
    with tempfile.TemporaryDirectory() as dd:
        prior = Path(dd) / "prior"
        cur = Path(dd) / "specs" / "spec-demo"
        prior.mkdir(parents=True)
        cur.mkdir(parents=True)
        (prior / "SPEC.md").write_text(
            "# Demo\n\n## Capabilities\n- id: CAP-1\n  intent: a\n  success: a\n"
            "- id: CAP-2\n  intent: b\n  success: b\n")
        # 1) current drops CAP-2 with NO retirement record -> CRITICAL
        (cur / "SPEC.md").write_text(
            "# Demo\n\n## Capabilities\n- id: CAP-1\n  intent: a\n  success: a\n")
        if not any(x["severity"] == "CRITICAL" and "CAP-2" in x["message"]
                   for x in compute_id_regression(cur, prior)):
            problems.append("id-regression missed a silently-dropped capability (CAP-2)")
        # 2) record the retirement -> the drop is authorized, no finding
        (cur / ".decision-log.md").write_text("Verdict: RETIRED: CAP-2 (folded into CAP-1)\n")
        if any("CAP-2" in x["message"] and "dropped" in x["message"]
               for x in compute_id_regression(cur, prior)):
            problems.append("id-regression flagged a RETIRED id as a silent drop")
        # 3) reuse of a retired id -> CRITICAL
        (cur / "SPEC.md").write_text(
            "# Demo\n\n## Capabilities\n- id: CAP-1\n  intent: a\n  success: a\n"
            "- id: CAP-2\n  intent: new\n  success: new\n")
        if not any(x["severity"] == "CRITICAL" and "CAP-2" in x["message"]
                   and "retired" in x["message"].lower()
                   for x in compute_id_regression(cur, prior)):
            problems.append("id-regression missed a retired-id reuse (CAP-2)")
        # 4) wired through analyze --since (the reuse surfaces as a finding)
        if not any("retired" in x["message"].lower() and "CAP-2" in x["message"]
                   for x in compute_analyze(cur, "civilian", constraints, since=prior)):
            problems.append("analyze --since did not surface the id regression")
    if problems:
        print("wf spec selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf spec selftest: PASS (constitution schema; "
          "spec init/check; constitution gate fail-closed; clarification-marker scan; "
          "analyze coverage+severity ladder, read-only, --block contract; "
          "--since id-regression: dropped / retired-reused IDs)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf spec")
    ap.add_argument("action", nargs="?",
                    choices=["init", "check", "split", "markers", "analyze"])
    ap.add_argument("feature", nargs="?")
    ap.add_argument("--dir", default=None, help="repo root (default: cwd)")
    ap.add_argument("--profile", choices=["civilian"], default="civilian")
    ap.add_argument("--path", default=None,
                    help="markers: scan this file or directory directly")
    ap.add_argument("--block", action="store_true",
                    help="analyze: exit 1 while any CRITICAL/HIGH finding remains")
    ap.add_argument("--since", default=None,
                    help="analyze: a prior spec dir/file to diff IDs against — flags a "
                         "load-bearing CAP/REQ id dropped (no RETIRED record) or a "
                         "retired id reused on a same-slug update")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("an action (init|check|split|markers|analyze) and <feature>, "
                 "or --selftest, is required")
    base = Path(args.dir) if args.dir else Path.cwd()
    if args.action == "markers":
        if args.path:
            return cmd_markers(Path(args.path))
        if args.feature:
            return cmd_markers(base / "specs" / args.feature)
        ap.error("markers needs <feature> or --path PATH")
    if not args.feature:
        ap.error("an action (init|check|split|analyze) and <feature> is required")
    constraints = load_constitution()
    feature_dir = base / "specs" / args.feature
    if args.action == "init":
        return cmd_init(feature_dir, constraints)
    if args.action == "check":
        return cmd_check(feature_dir, args.profile, constraints)
    if args.action == "analyze":
        return cmd_analyze(feature_dir, args.profile, constraints, block=args.block,
                           since=Path(args.since) if args.since else None)
    return cmd_split(feature_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
