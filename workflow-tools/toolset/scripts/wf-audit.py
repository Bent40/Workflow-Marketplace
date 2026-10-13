#!/usr/bin/env python3
"""wf-audit.py — story-completion audit: cross-reference the actionable
commitments in a BMAD story/plan (Acceptance Criteria + Tasks/Subtasks) against
the actual code diff and report which items have textual EVIDENCE in the diff
vs which are UNVERIFIED. Inspired by gstack's /ship plan-completion gate; it
strengthens honesty-gating by surfacing "did every accepted item actually land?"
before a story is called done.

HONESTY CONTRACT — this tool is a heuristic SURFACER, not a prover. It never
claims an item is "complete" or "done"; it only reports whether the diff does or
does not contain textual evidence for it. "UNVERIFIED" means **no textual
evidence found in the diff — verify manually**, NOT "incomplete". A confident
green here would itself be an overclaim, so the tool deliberately under-claims:
EVIDENCE is a hint to look, UNVERIFIED is a flag to check by hand, and the
highest-value finding is a CONTRADICTION — a task checkbox marked [x]
(claimed done) for which the diff carries no evidence.

Fail-closed: a story file that cannot be parsed into any acceptance criteria or
tasks is an ERROR (exit 2), never a silent green.

The diff is acquired through a testable SEAM: `audit_story_text(story_text,
diff_text, ...)` does all the work on plain strings, so the selftest injects a
synthetic diff and never depends on the repo's real git state. `main` is the
only place that shells out to git.

Exit codes:
    0  report produced (report-only mode, or --block with nothing to block on)
    1  --block and at least one acceptance criterion is UNVERIFIED, or any
       [x]-claimed task is UNVERIFIED (a contradiction)
    2  usage / parse error (fail-closed: unparseable story, bad args, git failure)

Usage:
    wf audit <story-file> [--base <ref>] [--block] [--threshold N]
    wf audit <story-file> --ears        # lint acceptance criteria against EARS
    wf audit --selftest
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# --- Section detection --------------------------------------------------------
# BMAD story format (see .claude/skills/bmad-create-story/template.md):
#   ## Acceptance Criteria      -> numbered list "1. ...", "2. ..."
#   ## Tasks / Subtasks         -> checkbox list "- [ ] ..." / "- [x] ..."
# We are robust to minor heading variation (case-insensitive; "Acceptance
# Criteria"/"ACs"; "Tasks"/"Tasks / Subtasks"/"Tasks/Subtasks").
AC_HEADING_RE = re.compile(
    r"^#{1,6}\s+(acceptance\s+criteria|acceptance\s+criterion|ac['’]?s?)\s*$",
    re.IGNORECASE)
TASK_HEADING_RE = re.compile(
    r"^#{1,6}\s+(tasks?(\s*/\s*subtasks?)?|tasks?\s+and\s+subtasks?|subtasks?)\s*$",
    re.IGNORECASE)
ANY_HEADING_RE = re.compile(r"^#{1,6}\s+\S")

# Numbered AC item: "1. text", "2) text" (optionally indented).
NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*\S)\s*$")
# Bullet AC item (some authors use "- text" under Acceptance Criteria).
BULLET_RE = re.compile(r"^\s*[-*+]\s+(?!\[[ xX]\])(.*\S)\s*$")
# Checkbox task item: "- [ ] text" (open) / "- [x] text" (claimed done). Captures
# indent (for nesting), the mark, and the text.
CHECKBOX_RE = re.compile(r"^(\s*)[-*+]\s+\[([ xX])\]\s+(.*\S)\s*$")

# Tokens worth matching on: identifiers / file-ish / CamelCase / snake_case /
# dotted.paths — length >= 3, must contain a letter. We also keep multi-word
# "key nouns" by stripping stopwords from the prose.
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_./-]{2,}")

# Conventional, deliberately-broad stopword list so generic words ("the",
# "should", "user", "system") do not count as salient evidence. Kept small and
# obvious — over-stripping just makes the tool MORE conservative (more
# UNVERIFIED), which is the safe direction for a surfacer.
STOPWORDS = frozenset("""
a an and are as at be been being but by can could do does done for from had has
have how if in into is it its may might must no not of off on or over should so
some such than that the their then there these they this those to too under up
upon use used uses using was were what when where which while who will with
without would you your yours we our ub item items list new add added adds adding
ensure ensures make makes making support supports return returns returned valid
invalid value values via per etc eg ie test tests testing case cases handle
handles handled given when then user users system response request via able
""".split())

# Generic words that are real tokens but too common to be evidence on their own.
# (Kept separate so the stopword set stays prose-oriented.)
GENERIC_TOKENS = frozenset({
    "ac", "acs", "task", "tasks", "subtask", "subtasks", "story", "code",
    "file", "files", "function", "method", "class", "module", "endpoint",
    "api", "data", "string", "number", "true", "false", "null", "none",
})


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf audit: {msg}\n")
    raise SystemExit(code)


# --- Story parsing ------------------------------------------------------------
def parse_story(text: str) -> tuple[list[str], list[dict]]:
    """Parse a BMAD story into (acceptance_criteria, tasks).

    Returns:
      acceptance_criteria: list[str]  — the AC item texts, in order.
      tasks: list[dict]               — {"text": str, "claimed_done": bool}
                                        for each checkbox task/subtask.

    A story with NEITHER any AC nor any task is unparseable → caller fails closed.
    """
    lines = text.splitlines()
    acs: list[str] = []
    tasks: list[dict] = []
    section: str | None = None  # "ac" | "task" | None

    for line in lines:
        if AC_HEADING_RE.match(line):
            section = "ac"
            continue
        if TASK_HEADING_RE.match(line):
            section = "task"
            continue
        # Any other heading closes the current actionable section.
        if ANY_HEADING_RE.match(line):
            section = None
            continue
        if section == "ac":
            m = NUMBERED_RE.match(line)
            if m:
                acs.append(m.group(1).strip())
                continue
            # Skip the template placeholder line, but accept real bullets.
            mb = BULLET_RE.match(line)
            if mb:
                txt = mb.group(1).strip()
                if not _is_placeholder(txt):
                    acs.append(txt)
        elif section == "task":
            mc = CHECKBOX_RE.match(line)
            if mc:
                mark, txt = mc.group(2), mc.group(3).strip()
                if not _is_placeholder(txt):
                    tasks.append({
                        "text": txt,
                        "claimed_done": mark.lower() == "x",
                    })

    # Drop pure template placeholders from the AC list too.
    acs = [a for a in acs if not _is_placeholder(a)]
    return acs, tasks


def _is_placeholder(text: str) -> bool:
    """A template stub like '[Add acceptance criteria from epics/PRD]' or a
    bare 'Task 1 (AC: #)' carries no real commitment to audit."""
    t = text.strip()
    low = t.lower()
    if t.startswith("[") and t.endswith("]") and "add " in low:
        return True
    if re.fullmatch(r"(task|subtask)\s*\d+(\.\d+)?\s*(\(ac:\s*#?\))?", low):
        return True
    return False


# --- Salient-term extraction --------------------------------------------------
def salient_terms(text: str) -> list[str]:
    """Derive the salient terms of an item: identifier/file-ish tokens and key
    nouns, lowercased, stopwords + too-generic words removed, de-duplicated in
    order. An `(AC: #)` reference and inline code backticks do not change the
    terms (the markers are stripped first)."""
    # Strip an "(AC: 1, 2)" reference and surrounding code-fence backticks so we
    # match on the substance, not the bookkeeping.
    cleaned = re.sub(r"\(ac:?[^)]*\)", " ", text, flags=re.IGNORECASE)
    cleaned = cleaned.replace("`", " ")
    terms: list[str] = []
    seen: set[str] = set()
    for raw in TOKEN_RE.findall(cleaned):
        low = raw.lower()
        # Keep the dotted/slashed/underscored/camel originals lowercased; they are
        # the high-signal identifiers. Plain prose words are filtered by stoplist.
        if low in STOPWORDS or low in GENERIC_TOKENS:
            continue
        if low in seen:
            continue
        seen.add(low)
        terms.append(low)
    return terms


# --- Diff handling ------------------------------------------------------------
def _basename(p: str) -> str:
    return p.rstrip("/").rsplit("/", 1)[-1]


def parse_diff(diff_text: str, exclude: set[str] | None = None) -> tuple[list[str], str]:
    """Split a unified diff into (changed_file_paths, searchable_blob).

    The searchable blob is the lowercased concatenation of changed file paths and
    ADDED lines only (lines starting with a single '+', excluding the '+++'
    header) — we look for evidence in what was ADDED, not what was removed. Path
    components are also split on '/._-' so a token like `is_valid_email` matches a
    file `validators/email.py` via its stem.

    `exclude` is a set of paths (and/or basenames) to drop ENTIRELY from the
    searchable blob. The audited story file itself is always excluded: otherwise
    the story's own AC/task prose would appear in the diff (a story add or edit is
    part of the changeset) and falsely "match" every item — the most dangerous
    false-green for an honesty tool."""
    exclude = exclude or set()
    excl_bases = {_basename(p) for p in exclude}
    paths: list[str] = []
    blocks: list[tuple[str, list[str]]] = []  # (current_path, added_lines)
    cur_path: str | None = None
    cur_added: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if cur_path is not None:
                blocks.append((cur_path, cur_added))
            m = re.search(r" b/(\S+)\s*$", line)
            cur_path, cur_added = (m.group(1) if m else None), []
            continue
        if line.startswith("+++ "):
            m = re.match(r"^\+\+\+\s+(?:b/)?(.+?)\s*$", line)
            if m and m.group(1) != "/dev/null":
                cur_path = m.group(1)
            continue
        if line.startswith("--- "):
            continue
        if line.startswith("+"):
            cur_added.append(line[1:])
    if cur_path is not None:
        blocks.append((cur_path, cur_added))

    added: list[str] = []
    for p, lines in blocks:
        if p in exclude or _basename(p) in excl_bases:
            continue  # never let the audited story (or other excluded file) be evidence
        paths.append(p)
        added.extend(lines)
    # Build the searchable blob: added content + paths + path stems.
    path_tokens: list[str] = []
    for p in paths:
        path_tokens.append(p)
        path_tokens.extend(re.split(r"[/._\-]+", p))
    blob = "\n".join(added + path_tokens).lower()
    # De-dup paths preserving order.
    seen: set[str] = set()
    uniq_paths = [p for p in paths if not (p in seen or seen.add(p))]
    return uniq_paths, blob


def match_terms(terms: list[str], blob: str) -> list[str]:
    """Return the salient terms that appear in the diff blob. A term matches as a
    SUBSTRING of the lowercased blob (so `is_valid_email` matches whether it
    appears as an identifier, in a path, or split across the added lines). Simple
    and conservative on purpose."""
    return [t for t in terms if t and t in blob]


# --- Classification -----------------------------------------------------------
def classify_item(text: str, blob: str, threshold: int) -> dict:
    """Classify one item against the diff blob.

    Heuristic (deliberately simple + commented): derive the item's salient terms;
    count how many appear in the diff blob; if the count is >= threshold (and at
    least one term exists), call it EVIDENCE and record which terms matched (so a
    human can verify); otherwise UNVERIFIED. An item with NO salient terms at all
    is UNVERIFIED (we cannot find evidence for an empty query — fail toward the
    flag, never toward a false green)."""
    terms = salient_terms(text)
    matched = match_terms(terms, blob)
    # Effective threshold cannot exceed the number of terms the item actually has
    # (a 1-term AC must be matchable), but is at least 1.
    eff = max(1, min(threshold, len(terms))) if terms else 1
    has_evidence = bool(terms) and len(matched) >= eff
    return {
        "text": text,
        "terms": terms,
        "matched": matched,
        "status": "EVIDENCE" if has_evidence else "UNVERIFIED",
    }


def audit_story_text(story_text: str, diff_text: str, *,
                     threshold: int = 1,
                     exclude_paths: set[str] | None = None) -> dict:
    """The testable SEAM: audit a story's text against a diff's text, both plain
    strings. Returns a structured result. Raises SystemExit(2) (fail-closed) if
    the story parses to no actionable items at all. `exclude_paths` drops those
    files from the diff blob — always used for the audited story itself so its own
    prose cannot become false evidence."""
    acs, tasks = parse_story(story_text)
    if not acs and not tasks:
        _die("could not parse any Acceptance Criteria or Tasks/Subtasks from the "
             "story (expected a '## Acceptance Criteria' numbered list and/or a "
             "'## Tasks / Subtasks' checkbox list) — failing closed", code=2)
    paths, blob = parse_diff(diff_text, exclude=exclude_paths)

    ac_results = [classify_item(a, blob, threshold) for a in acs]
    task_results = []
    for t in tasks:
        r = classify_item(t["text"], blob, threshold)
        r["claimed_done"] = t["claimed_done"]
        # A CONTRADICTION: checkbox says [x] (claimed done) but no diff evidence.
        r["contradiction"] = t["claimed_done"] and r["status"] == "UNVERIFIED"
        task_results.append(r)

    return {
        "paths": paths,
        "changed_files": len(paths),
        "claimed_done": sum(1 for t in tasks if t["claimed_done"]),
        # Tool-evidence gate: an empty diff (0 changed files) under a story that
        # claims done items is a completion claim with NO tool/diff evidence —
        # the honesty bar's worst case, surfaced loudly in the report.
        "zero_evidence": len(paths) == 0,
        "acs": ac_results,
        "tasks": task_results,
        "threshold": threshold,
        "ac_unverified": sum(1 for r in ac_results if r["status"] == "UNVERIFIED"),
        "ac_evidence": sum(1 for r in ac_results if r["status"] == "EVIDENCE"),
        "task_unverified": sum(1 for r in task_results if r["status"] == "UNVERIFIED"),
        "task_evidence": sum(1 for r in task_results if r["status"] == "EVIDENCE"),
        "contradictions": sum(1 for r in task_results if r["contradiction"]),
    }


# --- Reporting ----------------------------------------------------------------
def _row(idx: str, r: dict) -> str:
    mark = "✓" if r["status"] == "EVIDENCE" else "·"
    flag = "  ⚠ CONTRADICTION (claimed [x], no diff evidence)" if r.get("contradiction") else ""
    text = r["text"]
    if len(text) > 68:
        text = text[:65] + "..."
    line = f"  {mark} [{r['status']:<10}] {idx} {text}{flag}"
    if r["status"] == "EVIDENCE" and r["matched"]:
        ev = ", ".join(r["matched"][:5])
        line += f"\n        evidence: matched {len(r['matched'])} term(s) in diff: {ev}"
    return line


def render_report(result: dict, story_name: str, base: str | None) -> str:
    out: list[str] = []
    out.append("── story-completion audit ─────────────────────────────────────")
    out.append(f"story:  {story_name}")
    out.append(f"diff:   {base or 'working tree (staged + unstaged) vs HEAD'}  "
               f"({len(result['paths'])} changed file(s))")
    out.append("")
    out.append("HONESTY NOTE: this is a heuristic SURFACER, not proof of completion.")
    out.append("  EVIDENCE   = salient terms of the item appear in the diff (a HINT —")
    out.append("               still verify the item is actually satisfied).")
    out.append("  UNVERIFIED = no textual evidence found in the diff — verify manually.")
    out.append("               It does NOT mean 'incomplete'.")
    out.append("")
    out.append("Acceptance Criteria:")
    if result["acs"]:
        for i, r in enumerate(result["acs"], 1):
            out.append(_row(f"AC{i}.", r))
    else:
        out.append("  (none parsed)")
    out.append("")
    out.append("Tasks / Subtasks:")
    if result["tasks"]:
        for i, r in enumerate(result["tasks"], 1):
            box = "[x]" if r["claimed_done"] else "[ ]"
            out.append(_row(f"T{i} {box}", r))
    else:
        out.append("  (none parsed)")
    out.append("")
    out.append("Summary:")
    out.append(f"  acceptance criteria : {result['ac_evidence']} with evidence, "
               f"{result['ac_unverified']} UNVERIFIED")
    out.append(f"  tasks               : {result['task_evidence']} with evidence, "
               f"{result['task_unverified']} UNVERIFIED")
    out.append(f"  contradictions      : {result['contradictions']} "
               f"(task claimed [x] but no diff evidence — highest-value finding)")
    if result["changed_files"] == 0 and result["claimed_done"] > 0:
        out.append(f"  ⚠ ZERO-EVIDENCE     : {result['claimed_done']} task(s) marked "
                   f"[x] but the diff changed 0 files — completion claimed with no "
                   f"tool/diff evidence at all (verify before calling done).")
    out.append("───────────────────────────────────────────────────────────────")
    return "\n".join(out)


def block_exit_code(result: dict) -> int:
    """In --block mode, fail (1) if any AC is UNVERIFIED or any [x]-claimed task
    is UNVERIFIED (a contradiction). Open [ ] tasks that are UNVERIFIED do NOT
    block — an open task is honestly not-yet-done, not an overclaim."""
    if result["ac_unverified"] > 0 or result["contradictions"] > 0:
        return 1
    return 0


# --- git seam (only place we touch git) ---------------------------------------
def compute_diff(base: str | None, cwd: Path) -> str:
    """Acquire the diff text. Default (no --base): the working tree (staged +
    unstaged) against HEAD — i.e. `git diff HEAD` — so it audits what the dev has
    changed but not yet committed. With --base <ref>: `git diff <ref>...HEAD`
    (the symmetric-difference form: everything on HEAD since it diverged from
    <ref>), which is what you want when auditing a feature branch against main.
    Any git failure is fail-closed (exit 2)."""
    if base:
        args = ["git", "diff", f"{base}...HEAD"]
    else:
        args = ["git", "diff", "HEAD"]
    try:
        proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)
    except OSError as e:
        _die(f"could not run git: {e}")
    if proc.returncode != 0:
        _die(f"git diff failed (exit {proc.returncode}): "
             f"{(proc.stderr or '').strip() or 'no stderr'}")
    return proc.stdout


# --- EARS acceptance-criteria lint (design.acceptance_criteria_ears) -----------
# Detect which EARS pattern an acceptance criterion follows. EARS removes
# modal-verb ambiguity by requiring a 'shall' response in one of five lead-in
# shapes. An AC with no 'shall' fits NO pattern -> a smell to rewrite (or to
# confirm it is a non-behavioral AC, where EARS deliberately does not apply).
# Advisory SURFACER, consistent with the tool's honesty contract: it never blocks.
EARS_LEAD_RE = re.compile(r"^\s*(if|when|while|where)\b", re.IGNORECASE)
SHALL_RE = re.compile(r"\bshall\b", re.IGNORECASE)
THEN_RE = re.compile(r"\bthen\b", re.IGNORECASE)
EARS_LEAD_PATTERN = {
    "when": "Event (WHEN … shall)",
    "while": "State (WHILE … shall)",
    "where": "Optional (WHERE … shall)",
    "if": "Unwanted (IF … THEN … shall)",
}


def ears_classify(text: str) -> dict:
    """Classify one AC against the five EARS patterns. Returns
    {pattern: str|None, shall: bool, note: str}. `pattern` is None when the AC
    carries no 'shall' (fits no pattern — a smell to rewrite or confirm
    non-behavioral)."""
    has_shall = bool(SHALL_RE.search(text))
    lead = EARS_LEAD_RE.match(text)
    kw = lead.group(1).lower() if lead else None
    if not has_shall:
        return {"pattern": None, "shall": False,
                "note": "no 'shall' — fits no EARS pattern (rewrite as one of the "
                        "five shapes, or confirm it is a non-behavioral AC)"}
    if kw:
        note = ""
        if kw == "if" and not THEN_RE.search(text):
            note = "IF without an explicit THEN — tighten to 'IF … THEN the system shall …'"
        return {"pattern": EARS_LEAD_PATTERN[kw], "shall": True, "note": note}
    return {"pattern": "Ubiquitous (the system shall …)", "shall": True, "note": ""}


def render_ears_report(acs: list[str], story_name: str) -> tuple[str, int]:
    """Render the EARS lint over a story's acceptance criteria. Returns
    (report_text, smell_count). Advisory only — never blocks."""
    out: list[str] = []
    out.append("── EARS acceptance-criteria lint ──────────────────────────────")
    out.append(f"story:  {story_name}")
    out.append("")
    out.append("EARS gives each BEHAVIORAL acceptance criterion one of five 'shall'")
    out.append("shapes so it is unambiguous and test-traceable. An AC with no pattern")
    out.append("is a SMELL — rewrite it, unless it is deliberately a non-behavioral")
    out.append("(data-shape / UI-layout) AC, where EARS does not apply. Advisory only.")
    out.append("")
    smells = 0
    if not acs:
        out.append("  (no acceptance criteria parsed)")
    for i, a in enumerate(acs, 1):
        c = ears_classify(a)
        if c["pattern"] is None:
            smells += 1
            mark, label = "·", "NO-PATTERN"
        else:
            mark, label = "✓", c["pattern"]
        text = a if len(a) <= 58 else a[:55] + "..."
        line = f"  {mark} [{label}] AC{i}. {text}"
        if c["note"]:
            line += f"\n        note: {c['note']}"
        out.append(line)
    out.append("")
    shaped = len(acs) - smells
    out.append(f"Summary: {shaped}/{len(acs)} acceptance criteria are EARS-shaped; "
               f"{smells} fit no pattern (smell — rewrite or confirm non-behavioral).")
    out.append("───────────────────────────────────────────────────────────────")
    return "\n".join(out), smells


# --- selftest -----------------------------------------------------------------
def selftest() -> int:
    """Planted-fixture selftest with a POSITIVE CONTROL WITH TEETH. Uses the
    string seam (audit_story_text) so it never depends on the repo's git state."""
    problems: list[str] = []

    # A story with: an AC whose terms ARE in the diff (negative control — should
    # be EVIDENCE), an AC whose terms are ABSENT from the diff (positive control —
    # MUST be flagged UNVERIFIED and MUST make --block fail), a [x] task with no
    # evidence (must be a CONTRADICTION), and a [ ] task with evidence.
    story = """# Story 1.2: Email validation

Status: ready-for-dev

## Acceptance Criteria

1. Invalid emails are rejected by `is_valid_email` with a 400 response.
2. A nightly `purge_audit_logs` cron removes stale telemetry rows.

## Tasks / Subtasks

- [x] Implement the rollback_transaction safeguard (AC: #2)
- [ ] Add is_valid_email helper to the signup handler (AC: #1)
"""
    # The diff contains is_valid_email + signup, but NOTHING about
    # purge_audit_logs / rollback_transaction.
    diff = """diff --git a/auth/signup.py b/auth/signup.py
--- a/auth/signup.py
+++ b/auth/signup.py
@@ -1,3 +1,8 @@
+def is_valid_email(addr):
+    return "@" in addr
+
 def signup(req):
+    if not is_valid_email(req.email):
+        return 400
     ...
"""
    result = audit_story_text(story, diff, threshold=1)

    # negative control: AC1 (is_valid_email, signup, 400) -> EVIDENCE, not flagged
    ac1 = result["acs"][0]
    if ac1["status"] != "EVIDENCE":
        problems.append(f"negative control: AC1 should be EVIDENCE, got {ac1['status']}")
    if "is_valid_email" not in ac1["matched"]:
        problems.append("negative control: AC1 did not record the matched term")

    # POSITIVE CONTROL WITH TEETH: AC2 (purge_audit_logs, telemetry, cron) is
    # absent from the diff -> MUST be UNVERIFIED.
    ac2 = result["acs"][1]
    if ac2["status"] != "UNVERIFIED":
        problems.append(f"positive control: AC2 (absent terms) should be "
                        f"UNVERIFIED, got {ac2['status']} (matched={ac2['matched']})")

    # the [x] task with no evidence MUST be a contradiction; the [ ] task with
    # evidence MUST NOT be.
    t_rollback = result["tasks"][0]
    t_signup = result["tasks"][1]
    if not t_rollback["contradiction"]:
        problems.append("contradiction: [x] rollback_transaction task with no "
                        "evidence was not flagged as a contradiction")
    if t_signup["contradiction"]:
        problems.append("contradiction: [ ] open task was wrongly flagged as a "
                        "contradiction")
    if t_signup["status"] != "EVIDENCE":
        problems.append("the [ ] signup task (is_valid_email in diff) should be "
                        "EVIDENCE")

    # --block MUST fail (1) because AC2 is UNVERIFIED and the [x] task contradicts.
    if block_exit_code(result) != 1:
        problems.append("--block did not fail despite an UNVERIFIED AC and a "
                        "[x]-but-UNVERIFIED contradiction")

    # An all-evidence story under --block must pass (0): assert the gate is not
    # stuck-on.
    clean_story = ("## Acceptance Criteria\n\n"
                   "1. is_valid_email rejects bad input.\n\n"
                   "## Tasks / Subtasks\n\n"
                   "- [x] Add is_valid_email to signup\n")
    clean = audit_story_text(clean_story, diff, threshold=1)
    if block_exit_code(clean) != 0:
        problems.append("--block wrongly failed on an all-evidence story (gate "
                        "stuck on)")

    # fail-closed: an unparseable story (no AC, no tasks) MUST exit 2.
    try:
        audit_story_text("# Just a title\n\nSome prose, no sections.\n", diff)
        problems.append("unparseable story did not fail closed")
    except SystemExit as e:
        if e.code != 2:
            problems.append(f"unparseable story exit {e.code}, expected 2")

    # exclusion seam: the audited story file's OWN text must not become evidence.
    # Here the diff is a story.md add whose body restates AC2's absent terms; with
    # story.md excluded, AC2 must STAY UNVERIFIED (no false-green from self-match).
    story_diff = ("diff --git a/story.md b/story.md\n"
                  "--- /dev/null\n+++ b/story.md\n@@ -0,0 +1,3 @@\n"
                  "+## Acceptance Criteria\n"
                  "+1. purge_audit_logs telemetry cron nightly.\n")
    excl = audit_story_text(story, story_diff + diff, threshold=1,
                            exclude_paths={"story.md"})
    if excl["acs"][1]["status"] != "UNVERIFIED":
        problems.append("exclusion: AC2 matched the story file's own text "
                        "(self-evidence false-green not prevented)")

    # parse_story correctness: claimed-done flag + placeholder stripping.
    acs, tasks = parse_story(
        "## Acceptance Criteria\n\n1. [Add acceptance criteria from epics/PRD]\n"
        "2. real criterion about widgets\n\n"
        "## Tasks / Subtasks\n\n- [x] done thing\n- [ ] open thing\n")
    if acs != ["real criterion about widgets"]:
        problems.append(f"placeholder AC not stripped: {acs}")
    if [t["claimed_done"] for t in tasks] != [True, False]:
        problems.append("task claimed_done flags parsed incorrectly")

    # EARS lint: each of the five patterns is recognized, and a no-'shall' AC is a
    # NO-PATTERN smell (the failure the lint exists to surface).
    ears_cases = [
        ("When the user submits, the system shall return 200.", "Event"),
        ("While syncing is active, the system shall show a spinner.", "State"),
        ("Where export is enabled, the system shall add a CSV button.", "Optional"),
        ("If the token is invalid, then the system shall reject it.", "Unwanted"),
        ("The system shall log every write.", "Ubiquitous"),
        ("Invalid emails are rejected.", None),  # no 'shall' -> smell
    ]
    for txt, want in ears_cases:
        got = ears_classify(txt)["pattern"]
        if want is None and got is not None:
            problems.append(f"EARS: '{txt[:28]}' should be NO-PATTERN, got {got}")
        elif want is not None and (got is None or not got.startswith(want)):
            problems.append(f"EARS: '{txt[:28]}' should be {want}, got {got}")
    _rep, smells = render_ears_report([c[0] for c in ears_cases], "fixture")
    if smells != 1:
        problems.append(f"EARS report: expected 1 smell, got {smells}")

    # Tool-evidence gate: a [x] task against an EMPTY diff is a zero-evidence
    # completion claim — 0 changed files, the [x] task is a contradiction, and
    # --block fails.
    empty = audit_story_text(
        "## Acceptance Criteria\n\n1. widget frobnicates on save.\n\n"
        "## Tasks / Subtasks\n\n- [x] implement frobnicate\n", "", threshold=1)
    if empty["changed_files"] != 0 or not empty["zero_evidence"]:
        problems.append("zero-evidence: empty diff should report 0 changed files")
    if empty["claimed_done"] != 1 or empty["contradictions"] != 1:
        problems.append("zero-evidence: [x] task with empty diff should be a contradiction")
    if block_exit_code(empty) != 1:
        problems.append("zero-evidence: --block should fail on a claimed-done task "
                        "with an empty diff")

    if problems:
        print("wf audit selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf audit selftest: PASS (positive control flags an absent-term AC "
          "UNVERIFIED + --block exits non-zero; negative control is EVIDENCE; "
          "[x]-no-evidence is a contradiction; story self-text excluded from "
          "evidence; unparseable story fails closed; EARS lint recognizes the 5 "
          "patterns + the no-shall smell; zero-evidence empty-diff [x] claim blocks)")
    return 0


# --- main ---------------------------------------------------------------------
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="wf audit",
        description="Story-completion audit: cross-reference a BMAD story's "
                    "accepted items against the code diff and flag UNVERIFIED "
                    "ones (a heuristic surfacer, NOT proof of completion).")
    ap.add_argument("story", nargs="?", help="path to the BMAD story/plan .md")
    ap.add_argument("--base", default=None,
                    help="git ref to diff against (uses '<base>...HEAD'); "
                         "default audits the working tree + staged vs HEAD")
    ap.add_argument("--block", action="store_true",
                    help="exit non-zero if any acceptance criterion is UNVERIFIED "
                         "or any [x]-claimed task has no diff evidence")
    ap.add_argument("--threshold", type=int, default=1,
                    help="min salient terms that must appear in the diff to call "
                         "an item EVIDENCE (default: 1; capped at an item's term "
                         "count)")
    ap.add_argument("--ears", action="store_true",
                    help="lint the story's acceptance criteria against the EARS "
                         "patterns and exit (advisory; needs no diff)")
    ap.add_argument("--selftest", action="store_true", help="run the selftest")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.story:
        ap.error("a story file is required (or use --selftest)")
    if args.threshold < 1:
        _die("--threshold must be >= 1")

    story_path = Path(args.story)
    if not story_path.is_file():
        _die(f"story not found: {story_path}")
    story_text = story_path.read_text()

    # --ears: an AC-only lint that needs no diff (and no git). Advisory: it prints
    # the EARS report and exits 0 regardless of smells, per the honesty contract.
    if args.ears:
        acs, _ = parse_story(story_text)
        report, _smells = render_ears_report(acs, story_path.name)
        print(report)
        return 0

    diff_text = compute_diff(args.base, Path.cwd())
    # Always exclude the audited story file from its own evidence (by repo-relative
    # path when resolvable, and by basename as a fallback) — a story add/edit is
    # part of the changeset and its prose would otherwise match every item.
    exclude = {args.story, story_path.name}
    try:
        exclude.add(str(story_path.resolve().relative_to(Path.cwd().resolve())))
    except ValueError:
        pass
    result = audit_story_text(story_text, diff_text, threshold=args.threshold,
                              exclude_paths=exclude)
    print(render_report(result, story_path.name, args.base))

    if args.block:
        rc = block_exit_code(result)
        if rc != 0:
            print(f"\nwf audit: BLOCK — {result['ac_unverified']} UNVERIFIED "
                  f"acceptance criterion(a) and/or {result['contradictions']} "
                  f"claimed-done-but-unverified task(s). Verify manually before "
                  f"calling the story done.")
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
