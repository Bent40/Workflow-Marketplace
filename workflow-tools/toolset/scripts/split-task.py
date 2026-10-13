#!/usr/bin/env python3
"""split-task.py — scaffold local-model microtask packets from a story.

Part of the cross-agent framework's local-model tooling. This is a DETERMINISTIC
scaffolder, not an LLM splitter: the intelligent decomposition (deciding what the
microtasks are) is the orchestrator's job and is provided as a `## Microtasks`
list in the story file. This tool turns each list item into a contract-conformant
microtask packet file (per adapters/local-models/microtask-protocol.md), plus an
orchestration index — so a small-context worker model receives one narrow,
well-formed packet at a time.

Usage:
    scripts/split-task.py <story.md> [--out <dir>] [--profile <name>]
    scripts/split-task.py --selftest        # run on the bundled example story

The story must contain a section headed `## Microtasks` (preferred) or `## Tasks`
with a markdown list; each item becomes one packet, in order. The intelligent
work — what the packets are — is the orchestrator's; this tool only mechanizes
turning that list into proper packets.

EXECUTION WAVES (opt-in): a microtask item may carry leading annotations:
    - `[P]`                 — independent / parallelizable
    - `[depends-on: 1, 3]`  — depends on task 1 and 3 (1-based list order;
                              `after:` / `needs:` are accepted synonyms)
When ANY item is annotated, the tool computes a dependency-ordered set of WAVES
(tasks in a wave are independent and may run in parallel; waves run in sequence)
and emits an `## Execution waves` section. The MAIN agent owns wave dispatch —
it launches each wave's packets as DIRECT subagents it ledgers (never nested) and
advances only when a wave is fully integrated + verified. A circular/unsatisfiable
dependency FAILS CLOSED. With NO annotations the behavior is unchanged (a plain
ordered sequence).
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_STORY = REPO_ROOT / "adapters" / "local-models" / "example-story.md"
DEFAULT_PROFILE = "local-small-context"

# The microtask packet contract fields (see
# adapters/local-models/microtask-protocol.md). Every generated packet must
# carry all of these.
REQUIRED_PACKET_FIELDS = (
    "objective", "allowed_files", "forbidden_files", "context_budget",
    "max_edit_size", "expected_output_format", "validation", "stop_condition",
    "handoff_summary_format",
)

SECTION_RE = re.compile(r"^##\s+(microtasks|tasks)\s*$", re.IGNORECASE)
HEADER_RE = re.compile(r"^#\s+(.*\S)\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
# Leading execution-wave annotations on a microtask item: [P] / [depends-on: ...].
_ANNOT_RE = re.compile(r"^\s*\[([^\]]*)\]\s*(.*)$", re.DOTALL)
_DEPS_RE = re.compile(r"^(?:depends-on|after|needs)\s*:\s*(.+)$", re.IGNORECASE)


def _parse_item_annotations(raw: str) -> tuple[str, set[int], bool]:
    """Strip leading [P] / [depends-on: ...] annotations off a microtask item.
    Returns (clean_objective, deps:set[int 1-based], parallel:bool). An
    unrecognized [..] is left intact (it's part of the objective)."""
    deps: set[int] = set()
    parallel = False
    text = raw
    while True:
        m = _ANNOT_RE.match(text)
        if not m:
            break
        tag, rest = m.group(1).strip(), m.group(2)
        if tag.lower() == "p":
            parallel = True
            text = rest
            continue
        dm = _DEPS_RE.match(tag)
        if dm:
            for tok in re.split(r"[\s,]+", dm.group(1).strip()):
                if tok.isdigit():
                    deps.add(int(tok))
            text = rest
            continue
        break  # unrecognized annotation -> part of the objective; stop stripping
    return text.strip(), deps, parallel


def compute_waves(items: list[dict]) -> tuple[list[list[int]] | None, list[int]]:
    """Group items (each {objective, deps, parallel}) into dependency-ordered
    waves of 0-based indices. A task is in the earliest wave after all of its
    deps. Returns (waves, []) or (None, stuck_indices) on a cycle / unsatisfiable
    dependency. Out-of-range and self deps are ignored (defensive)."""
    n = len(items)
    deps: list[set[int]] = []
    for i, it in enumerate(items):
        d = {x - 1 for x in it["deps"] if 1 <= x <= n}
        d.discard(i)
        deps.append(d)
    remaining = set(range(n))
    waves: list[list[int]] = []
    while remaining:
        ready = [i for i in range(n) if i in remaining and deps[i].isdisjoint(remaining)]
        if not ready:
            return None, sorted(remaining)  # cycle / unsatisfiable -> caller fails closed
        waves.append(ready)
        remaining -= set(ready)
    return waves, []


def _die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"split-task: {msg}\n")
    raise SystemExit(2)


def _load_context_module():
    """Import scripts/wf-context.py so we reuse its ONE resolver — no
    duplicate resolution logic (the tags_are_hints_not_truth boundary)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "wf_context", REPO_ROOT / "scripts" / "wf-context.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def resolve_story_context(story_path: Path, config_arg) -> dict:
    """Resolve the story's `Tags:` line through the context registry to
    {names, paths, obligations}. Exits 1 on an unknown tag, 2 on missing config."""
    ctx = _load_context_module()
    if config_arg:
        config_path = Path(config_arg)
    else:
        alongside = story_path.resolve().parent / "bmad.config.yaml"
        config_path = alongside if alongside.is_file() else REPO_ROOT / "bmad.config.yaml"
    tags_map = ctx.load_tags(config_path)   # exits 2 on missing/malformed
    names, had = ctx.parse_story_tags(story_path.read_text())
    if not had:
        sys.stderr.write(f"split-task: WARN {story_path.name}: no `Tags:` line; "
                         f"nothing to resolve\n")
    res = ctx.resolve_tags(tags_map, config_path.parent, names)
    if res["unknown"]:
        sys.stderr.write(f"split-task: unknown tag(s) in {story_path.name}: "
                         f"{', '.join(res['unknown'])}\n")
        raise SystemExit(1)
    return {"names": names, "paths": res["paths"], "obligations": res["obligations"]}


def slugify(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen].rstrip("-")) or "task"


def parse_story(text: str) -> tuple[str, list[dict]]:
    """Return (title, items) parsed from the story, where each item is
    {objective, deps:set[int], parallel:bool} — wave annotations stripped off the
    objective. (Back-compat: callers that only want objectives read item["objective"].)"""
    title = "Untitled story"
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            title = m.group(1)
            break

    lines = text.splitlines()
    items: list[dict] = []
    in_section = False
    for line in lines:
        if SECTION_RE.match(line):
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):  # next section ends the list
                break
            m = LIST_ITEM_RE.match(line)
            if m:
                obj, deps, parallel = _parse_item_annotations(m.group(1))
                items.append({"objective": obj, "deps": deps, "parallel": parallel})
    return title, items


def render_packet(n: int, total: int, objective: str, title: str,
                  story_name: str, profile: str, context: dict | None = None) -> str:
    if context and context.get("paths"):
        cand = ", ".join(context["paths"][:8])
        extra = "" if len(context["paths"]) <= 8 else f", … (+{len(context['paths']) - 8})"
        allowed = f"- allowed_files: <FILL from tag-resolved candidates: {cand}{extra}>"
    else:
        allowed = "- allowed_files: <FILL: explicit minimal set you may read/edit>"
    obligations: list[str] = []
    if context and context.get("obligations"):
        obls = "; ".join(f"{t}→{o}" for t, o in context["obligations"])
        obligations = [f"- risk_obligations: {obls} (satisfy before this packet is done)"]
    return "\n".join([
        f"# Microtask {n:02d}/{total:02d} — {objective}",
        f"<!-- generated by scripts/split-task.py from {story_name} -->",
        "",
        f"> {title}",
        "",
        "## Packet",
        f"- objective: {objective}",
        allowed,
        "- forbidden_files: <FILL: shared routers, migrations, config>",
        "- context_budget: <FILL: ceiling for this packet>",
        "- max_edit_size: <FILL: e.g. one function / <= N changed lines>",
        "- expected_output_format: patch/diff",
        "- validation: <FILL: exact command to run, or manual check>",
        "- stop_condition: stop after this single objective",
        "- handoff_summary_format: <FILL: shape of the terse summary for the orchestrator>",
        *obligations,
        "",
        "## Operating rules (local)",
        f"Follow `adapters/{profile}/local/SYSTEM.md`. Key points: one objective,",
        "touch only the allowed files, make the smallest change that satisfies it,",
        "run the stated validation, then stop and hand back a short summary.",
        "",
    ]) + "\n"


def render_index(title: str, story_name: str, profile: str,
                 packets: list[tuple[str, str]], context: dict | None = None,
                 waves: list[list[int]] | None = None) -> str:
    lines = [
        f"# Microtask plan — {title}",
        f"<!-- generated by scripts/split-task.py from {story_name} -->",
        "",
        "The ORCHESTRATOR owns decomposition, integration, and final acceptance.",
        "Run the packets below in order, integrate each returned diff, and do the",
        "final acceptance check yourself. A small-context worker handles one packet",
        "at a time and stops after each.",
        "",
        f"- Operating rules: `adapters/{profile}/local/SYSTEM.md`",
        f"- Review pass: `adapters/{profile}/local/REVIEW.md`",
        f"- Packet contract: `adapters/{profile}/local/TASK.md`",
    ]
    if context is not None:
        names = ", ".join(context["names"]) if context["names"] else "(no tags)"
        lines += ["", f"## Focused context (from story tags: {names})",
                  "Candidate files (tag-resolved — START here, then verify imports, "
                  "tests, deps, and security before editing):"]
        lines += [f"- `{p}`" for p in context["paths"]] or ["- (none resolved)"]
        if context["obligations"]:
            lines += ["", "Risk obligations (satisfy before done):"]
            lines += [f"- {t}: {o}" for t, o in context["obligations"]]
        lines += ["", "> Tags say where to START — not that nothing else matters."]
    lines += ["", "## Sequence"]
    for i, (fname, objective) in enumerate(packets, 1):
        lines.append(f"{i}. `{fname}` — {objective}")
    if waves:
        lines += [
            "", "## Execution waves",
            "Tasks within a wave are INDEPENDENT and may run in parallel; waves run "
            "in SEQUENCE. The MAIN agent owns wave dispatch: launch each wave's "
            "packets as DIRECT subagents it ledgers (NEVER nested — "
            "subagents.default_for_nontrivial_claude_work), and advance to the next "
            "wave only once the current wave's packets are all integrated AND "
            "verified (subagents.orphan_reclaim_watchdog; size the fan-out by "
            "orchestration.subagent_trigger_thresholds).",
        ]
        for w, group in enumerate(waves, 1):
            names = ", ".join(f"`{packets[i][0]}`" for i in group)
            kind = "parallel" if len(group) > 1 else "single"
            lines.append(f"- Wave {w} ({kind}): {names}")
    return "\n".join(lines) + "\n"


def split(story_path: Path, out_dir: Path, profile: str,
          context: dict | None = None) -> list[Path]:
    if not story_path.is_file():
        _die(f"story not found: {story_path}")
    text = story_path.read_text()
    title, items = parse_story(text)
    if not items:
        _die(f"no '## Microtasks' (or '## Tasks') list found in {story_path.name}; "
             f"the orchestrator must provide the decomposition as a markdown list")
    # Execution waves are computed only when the author opted in via [P] /
    # [depends-on:] annotations; otherwise behavior is the unchanged ordered list.
    waves: list[list[int]] | None = None
    if any(it["deps"] or it["parallel"] for it in items):
        waves, stuck = compute_waves(items)
        if waves is None:
            _die(f"circular or unsatisfiable [depends-on] among the microtasks in "
                 f"{story_path.name} (stuck: task(s) {', '.join(str(i + 1) for i in stuck)}); "
                 f"fix the dependencies")
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(items)
    written: list[Path] = []
    index_entries: list[tuple[str, str]] = []
    for i, item in enumerate(items, 1):
        objective = item["objective"]
        fname = f"{i:02d}-{slugify(objective)}.md"
        (out_dir / fname).write_text(
            render_packet(i, total, objective, title, story_path.name, profile, context))
        written.append(out_dir / fname)
        index_entries.append((fname, objective))
    index = out_dir / "00-orchestration.md"
    index.write_text(render_index(title, story_path.name, profile, index_entries,
                                  context, waves))
    written.insert(0, index)
    return written


def selftest() -> int:
    if not EXAMPLE_STORY.is_file():
        print(f"split-task selftest: FAIL (missing example story {EXAMPLE_STORY})")
        return 1
    title, tasks = parse_story(EXAMPLE_STORY.read_text())
    tmp = Path(tempfile.mkdtemp(prefix="split-task-selftest-"))
    written = split(EXAMPLE_STORY, tmp, DEFAULT_PROFILE)
    problems = []
    if len(written) != len(tasks) + 1:
        problems.append(f"expected {len(tasks)+1} files, got {len(written)}")
    index_text = (tmp / "00-orchestration.md").read_text()
    if title not in index_text:
        problems.append("index missing story title")
    if len(tasks) >= 1:
        first_objective = tasks[0]["objective"]
        first_packet = sorted(p for p in written if p.name.startswith("01-"))
        if not first_packet or first_objective not in first_packet[0].read_text():
            problems.append("first packet missing its objective")
        if "## Packet" not in first_packet[0].read_text():
            problems.append("first packet missing the contract template")
    # every generated packet (not the index) must carry all 9 contract fields
    for p in written:
        if p.name == "00-orchestration.md":
            continue
        body = p.read_text()
        missing = [f for f in REQUIRED_PACKET_FIELDS if f"- {f}:" not in body]
        if missing:
            problems.append(f"{p.name} missing contract field(s): {', '.join(missing)}")
    for p in written:
        p.unlink()
    tmp.rmdir()
    # --context-from-tags (stage 5): inject focused context + risk obligations,
    # WITHOUT dropping any of the 9 contract fields.
    ctmp = Path(tempfile.mkdtemp(prefix="split-task-ctx-"))
    (ctmp / "src").mkdir()
    (ctmp / "src" / "auth.py").write_text("def login():\n    pass\n")
    (ctmp / "bmad.config.yaml").write_text(
        "context:\n  tags:\n"
        '    auth:\n      paths: ["src/auth.py"]\n'
        '    SECURITY:\n      type: risk\n      paths: ["src/auth.py"]\n'
        '      triggers: ["require security review"]\n')
    story = ctmp / "story.md"
    story.write_text("# Login fix\n\nTags: [auth] [SECURITY]\n\n"
                     "## Microtasks\n\n- add login\n- add logout\n")
    cctx = resolve_story_context(story, str(ctmp / "bmad.config.yaml"))
    split(story, ctmp / "out", DEFAULT_PROFILE, cctx)
    idx = (ctmp / "out" / "00-orchestration.md").read_text()
    if "Focused context (from story tags: auth, SECURITY)" not in idx:
        problems.append("ctx index missing focus section")
    if "require security review" not in idx or "`src/auth.py`" not in idx:
        problems.append("ctx index missing obligations/candidate files")
    pkt = (ctmp / "out" / "01-add-login.md").read_text()
    if "tag-resolved candidates: src/auth.py" not in pkt:
        problems.append("ctx packet missing tag-resolved allowed_files candidates")
    if "risk_obligations:" not in pkt or "require security review" not in pkt:
        problems.append("ctx packet missing risk_obligations")
    miss = [f for f in REQUIRED_PACKET_FIELDS if f"- {f}:" not in pkt]
    if miss:
        problems.append(f"ctx packet dropped contract field(s): {', '.join(miss)}")
    story.write_text("# X\n\nTags: [ghost]\n\n## Microtasks\n\n- a\n")
    try:
        resolve_story_context(story, str(ctmp / "bmad.config.yaml"))
        problems.append("ctx unknown tag did not fail closed")
    except SystemExit as e:
        if e.code != 1:
            problems.append(f"ctx unknown tag exit {e.code}, expected 1")
    for p in sorted(ctmp.rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    ctmp.rmdir()

    # EXECUTION WAVES (#17): annotations produce correct wave grouping + an
    # Execution-waves section; objectives are stripped of annotations; a cycle
    # fails closed; an un-annotated story emits NO waves section (back-compat).
    wtmp = Path(tempfile.mkdtemp(prefix="split-task-waves-"))
    wstory = wtmp / "w.md"
    wstory.write_text("# Waves\n\n## Microtasks\n\n"
                      "- [P] build A\n- [P] build B\n- [depends-on: 1, 2] integrate\n")
    _wt, witems = parse_story(wstory.read_text())
    wv, _stuck = compute_waves(witems)
    if wv != [[0, 1], [2]]:
        problems.append(f"waves: expected [[0,1],[2]], got {wv}")
    if witems[0]["objective"] != "build A" or witems[2]["deps"] != {1, 2}:
        problems.append(f"waves: annotation parse wrong: {witems}")
    split(wstory, wtmp / "out", DEFAULT_PROFILE)
    widx = (wtmp / "out" / "00-orchestration.md").read_text()
    if "## Execution waves" not in widx or "Wave 1 (parallel)" not in widx \
            or "Wave 2 (single)" not in widx:
        problems.append("waves: index missing/!wrong Execution waves section")
    # the stripped objective (not the raw "[P] build A") is what lands in the packet
    if "[P]" in (wtmp / "out" / "01-build-a.md").read_text():
        problems.append("waves: annotation leaked into the packet objective")
    # a cycle fails closed (exit 2)
    cstory = wtmp / "c.md"
    cstory.write_text("# Cycle\n\n## Microtasks\n\n- [depends-on: 2] a\n- [depends-on: 1] b\n")
    _ct, citems = parse_story(cstory.read_text())
    if compute_waves(citems)[0] is not None:
        problems.append("waves: a dependency cycle was not detected")
    try:
        split(cstory, wtmp / "cout", DEFAULT_PROFILE)
        problems.append("waves: split did not fail closed on a cycle")
    except SystemExit as e:
        if e.code != 2:
            problems.append(f"waves: cycle exit {e.code}, expected 2")
    # an un-annotated story emits NO waves section (back-compat)
    pstory = wtmp / "p.md"
    pstory.write_text("# Plain\n\n## Microtasks\n\n- a\n- b\n")
    split(pstory, wtmp / "pout", DEFAULT_PROFILE)
    if "## Execution waves" in (wtmp / "pout" / "00-orchestration.md").read_text():
        problems.append("waves: an un-annotated story wrongly emitted a waves section")
    for p in sorted(wtmp.rglob("*"), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink()
    wtmp.rmdir()

    if problems:
        print("split-task selftest: FAIL — " + "; ".join(problems))
        return 1
    print(f"split-task selftest: PASS ({len(tasks)} packets from the example story; "
          f"--context-from-tags injects focus + obligations, keeps the 9 fields; "
          f"[P]/[depends-on] annotations compute dependency waves + fail closed on a "
          f"cycle, un-annotated stays a plain sequence)")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="split-task.py",
        description="Scaffold local-model microtask packets from a story's "
                    "'## Microtasks' decomposition (deterministic; not an LLM "
                    "splitter).",
    )
    parser.add_argument("story", nargs="?", help="path to the story .md file")
    parser.add_argument("--out", type=Path, default=None,
                        help="output directory (default: <story>.microtasks/)")
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help=f"profile name for surface references (default: {DEFAULT_PROFILE})")
    parser.add_argument("--context-from-tags", action="store_true",
                        help="resolve the story's Tags: line via the context registry "
                             "and inject focused context (candidate files + risk "
                             "obligations) into the index and packets")
    parser.add_argument("--config", default=None,
                        help="path to bmad.config.yaml for --context-from-tags "
                             "(tag globs resolve relative to its directory — the "
                             "project root; default: alongside the story, else repo root)")
    parser.add_argument("--selftest", action="store_true",
                        help="run the bundled selftest and exit")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.story:
        parser.error("a story file is required (or use --selftest)")
    story_path = Path(args.story)
    out_dir = args.out or (story_path.with_suffix("").parent
                           / (story_path.stem + ".microtasks"))
    context = None
    if args.context_from_tags:
        context = resolve_story_context(story_path, args.config)
    for p in split(story_path, out_dir, args.profile, context):
        print(f"wrote {p}")
    if context is not None:
        print(f"context-from-tags: {', '.join(context['names']) or '(no tags)'} → "
              f"{len(context['paths'])} candidate file(s), "
              f"{len(context['obligations'])} obligation(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
