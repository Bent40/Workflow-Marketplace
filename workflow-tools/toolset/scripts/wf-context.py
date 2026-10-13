#!/usr/bin/env python3
"""wf-context.py — context-tag registry: a named tag resolves to a bundle of
globbed paths (+ optional tests / commands / cross-refs), and — for risk tags —
to review/reporting OBLIGATIONS. The tag IS the context pack, so this one
resolver supersedes the old E2 `context_packs`. Epic H (basic registry) + D3
(risk-aware story-tag flow).

Driven by a `context:` block in bmad.config.yaml:

    context:
      tags:
        auth:                                 # work-area tag (the default)
          type: work_area                     # work_area | risk  (default work_area)
          description: Authentication & session flows
          paths: ["src/auth/**", "src/middleware/session.js"]
          tests: ["src/auth/**/*.test.js"]    # optional
          commands: ["npm run test:auth"]     # optional
          see_also: ["billing"]               # optional; must name real tags
        SECURITY:                             # risk tag
          type: risk
          description: Auth, permissions, unsafe input, secrets.
          paths: ["server/auth/**"]           # optional for a risk tag
          triggers: ["require security review", "check input validation"]
          allow_empty: true                   # optional; suppress the stale-glob FAIL

  list            — tags + descriptions + file counts
  show  <tag>     — resolve a tag: matched files, tests, commands, see_also
  pack  <tag>     — emit a context pack (markdown bundle)
  resolve         — resolve a SET of tags (--tags A,B | --story FILE) to the
                    unioned paths/tests + risk obligations (D3 / H3)
  check           — fail-closed registry validation (exit 0 ok / 1 bad / 2 config)

Context tags are GUIDANCE, not truth and not an authorization/trust boundary: a
tag set says where to START, never that nothing else matters (see the
`context.tags_are_hints_not_truth` rule). This tool only READS and resolves; it
never writes, runs commands, or computes trust.

Usage:
    wf context list|show|pack|check [<tag>] [--config PATH] [--dir ROOT]
    wf context resolve (--tags UI,API | --story FILE) [--strict] [--config PATH]
    wf context --selftest
"""
from __future__ import annotations

import argparse
import glob as globlib
import re
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("wf context: PyYAML not available; cannot parse config\n")
    sys.exit(2)

EXCLUDES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".idea", ".DS_Store",
}
GUARDRAIL = ("> Context tags are GUIDANCE, not an authorization or trust "
            "boundary. Inclusion does not make a file trusted; exclusion does "
            "not make an action safe.")
HINTS_NOT_TRUTH = ("> Tags say where to START — not that nothing else matters. "
                   "Verify imports, tests, deps, and security before editing.")
TYPES = ("work_area", "risk")
TAG_TOKEN_RE = re.compile(r"\[([A-Za-z0-9_./-]+)\]")
TAGS_LINE_RE = re.compile(r"^\s*Tags\s*:", re.IGNORECASE)


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf context: {msg}\n")
    raise SystemExit(code)


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that REJECTS duplicate mapping keys instead of silently
    keeping the last — so duplicate tag definitions are caught, not collapsed."""


def _construct_mapping(loader, node, deep=False):  # noqa: ANN001
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_tags(config_path: Path) -> dict[str, dict]:
    """Return the context.tags mapping (possibly empty). Fail-closed on a
    missing file, non-mapping top level, a malformed context/tags shape, or a
    DUPLICATE tag definition (exit 2 — a structurally broken registry)."""
    if not config_path.is_file():
        _die(f"config not found: {config_path} (pass --config or add bmad.config.yaml)")
    try:
        data = yaml.load(config_path.read_text(), Loader=_UniqueKeyLoader)
    except yaml.constructor.ConstructorError as e:
        _die(f"{config_path.name}: {e.problem} (duplicate tag definitions are rejected)")
    except yaml.YAMLError as e:
        _die(f"{config_path.name}: invalid YAML: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        _die(f"{config_path.name}: top-level must be a mapping")
    ctx = data.get("context")
    if ctx is None:
        return {}
    if not isinstance(ctx, dict):
        _die("'context' must be a mapping")
    tags = ctx.get("tags")
    if tags is None:
        return {}
    if not isinstance(tags, dict):
        _die("'context.tags' must be a mapping of tag -> spec")
    return tags


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "K", "M", "G"):
        if size < 1024 or unit == "G":
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{int(n)}B"


def resolve_paths(root: Path, patterns: list[str]) -> list[str]:
    """Resolve glob patterns to a sorted, de-duped list of repo-relative files,
    excluding the usual noise directories. Uses the glob module with
    recursive=True so `**` matches files (pathlib's `**` matches dirs only).

    Results are CONFINED to the repo root: both the root and each hit are
    resolved before the containment check, so a `../**` or symlink escape is
    dropped (a context pack must never reach outside the repo)."""
    root_r = root.resolve()
    found: set[str] = set()
    for pat in patterns:
        for hit in globlib.glob(str(root / pat), recursive=True):
            p = Path(hit).resolve()
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(root_r)
            except ValueError:
                continue  # escapes the repo root — fail-closed, dropped
            if any(part in EXCLUDES for part in rel.parts):
                continue
            found.add(rel.as_posix())
    return sorted(found)


def _tag_type(spec: dict) -> str:
    return spec.get("type", "work_area")


def compute_check(tags: dict[str, dict], root: Path) -> list[str]:
    """Registry-level validation (D3 / check 21). Fail-closed: invalid type, a
    tag with neither paths nor triggers, a stale glob (unless allow_empty),
    malformed list fields, and bad see_also."""
    problems: list[str] = []
    for name in sorted(tags):
        spec = tags[name]
        if not isinstance(spec, dict):
            problems.append(f"{name}: tag must be a mapping")
            continue
        ttype = _tag_type(spec)
        if ttype not in TYPES:
            problems.append(f"{name}: invalid type {ttype!r} (must be work_area|risk)")
        paths = spec.get("paths", [])
        if paths and (not isinstance(paths, list) or
                      not all(isinstance(p, str) and p.strip() for p in paths)):
            problems.append(f"{name}: 'paths' must be a list of strings")
            paths = []
        triggers = spec.get("triggers", [])
        if triggers and (not isinstance(triggers, list) or
                         not all(isinstance(t, str) and t.strip() for t in triggers)):
            problems.append(f"{name}: 'triggers' must be a list of strings")
            triggers = []
        tests = spec.get("tests", [])
        if tests and (not isinstance(tests, list) or
                      not all(isinstance(t, str) and t.strip() for t in tests)):
            problems.append(f"{name}: 'tests' must be a list of strings")
        if not paths and not triggers:
            problems.append(f"{name}: a tag must declare 'paths' or 'triggers' "
                            f"(both empty)")
        allow_empty = spec.get("allow_empty", False)
        if not isinstance(allow_empty, bool):
            problems.append(f"{name}: 'allow_empty' must be true/false")
            allow_empty = False
        cmds = spec.get("commands", [])
        if cmds and (not isinstance(cmds, list) or
                     not all(isinstance(c, str) and c.strip() for c in cmds)):
            problems.append(f"{name}: 'commands' must be a list of strings")
        sa = spec.get("see_also", [])
        if sa and (not isinstance(sa, list) or not all(isinstance(s, str) for s in sa)):
            problems.append(f"{name}: 'see_also' must be a list of strings")
            sa = []
        if not allow_empty:
            for pat in (paths or []):
                if not resolve_paths(root, [pat]):
                    problems.append(f'{name}: glob "{pat}" matches 0 files (stale; '
                                    f'set allow_empty: true if intentional)')
        for s in (sa or []):
            if s not in tags:
                problems.append(f'{name}: see_also "{s}" is not a defined tag')
    return problems


def cmd_check(tags: dict[str, dict], root: Path, quiet: bool = False) -> int:
    if not tags:
        if not quiet:
            print("context check: no context tags defined (nothing to validate).")
        return 0
    problems = compute_check(tags, root)
    if not quiet:
        bad = {p.split(":")[0] for p in problems}
        for name in sorted(tags):
            if name not in bad and isinstance(tags[name], dict):
                n = len(resolve_paths(root, tags[name].get("paths", []) or []))
                np = len(tags[name].get("paths", []) or [])
                print(f"OK   {name} [{_tag_type(tags[name])}] ({np} paths → {n} files)")
        for p in problems:
            print(f"FAIL {p}")
        if problems:
            print(f"context check: {len(problems)} problem(s) in {len(tags)} tag(s).")
        else:
            print(f"context check: OK ({len(tags)} tag(s)).")
    return 1 if problems else 0


def cmd_list(tags: dict[str, dict], root: Path) -> int:
    if not tags:
        print("no context tags defined.")
        return 0
    for name in sorted(tags):
        spec = tags[name] if isinstance(tags[name], dict) else {}
        desc = spec.get("description", "")
        n = len(resolve_paths(root, spec.get("paths", []) or []))
        tag = f"{name} [{_tag_type(spec)}]"
        print(f"- {tag} — {desc} ({n} files)" if desc else f"- {tag} ({n} files)")
    print(GUARDRAIL)
    return 0


def cmd_show(tags: dict[str, dict], root: Path, name: str) -> int:
    if name not in tags or not isinstance(tags[name], dict):
        _die(f"unknown tag: {name}")
    spec = tags[name]
    files = resolve_paths(root, spec.get("paths", []) or [])
    print(f"{name} [{_tag_type(spec)}]: {spec.get('description', '')}".rstrip())
    print(f"files ({len(files)}): " + (", ".join(files) if files else "(none)"))
    if spec.get("tests"):
        tfiles = resolve_paths(root, spec["tests"])
        print(f"tests ({len(tfiles)}): " + (", ".join(tfiles) if tfiles
                                            else "(globs: " + ", ".join(spec["tests"]) + ")"))
    if spec.get("commands"):
        print("commands: " + ", ".join(spec["commands"]))
    if _tag_type(spec) == "risk" and spec.get("triggers"):
        print("obligations: " + "; ".join(spec["triggers"]))
    if spec.get("see_also"):
        print("see_also: " + ", ".join(spec["see_also"]))
    print(GUARDRAIL)
    return 0


def cmd_pack(tags: dict[str, dict], root: Path, name: str) -> int:
    if name not in tags or not isinstance(tags[name], dict):
        _die(f"unknown tag: {name}")
    spec = tags[name]
    files = resolve_paths(root, spec.get("paths", []) or [])
    out = [f"# Context pack: {name} [{_tag_type(spec)}]"]
    if spec.get("description"):
        out.append(spec["description"])
    out += ["", f"## Files ({len(files)})"]
    for rel in files:
        try:
            size = (root / rel).stat().st_size
        except OSError:
            size = 0
        out.append(f"- `{rel}` ({_human_size(size)})")
    if not files:
        out.append("(none)")
    if spec.get("commands"):
        out += ["", "## Commands"] + [f"- {c}" for c in spec["commands"]]
    if _tag_type(spec) == "risk" and spec.get("triggers"):
        out += ["", "## Obligations"] + [f"- {t}" for t in spec["triggers"]]
    if spec.get("see_also"):
        out += ["", "## See also"] + [f"- {s}" for s in spec["see_also"]]
    out += ["", GUARDRAIL]
    print("\n".join(out))
    return 0


def parse_story_tags(text: str) -> tuple[list[str], bool]:
    """Return (tag_names, had_tags_line) from the first `Tags:` line of a story
    (`Tags: [UI] [API] [SECURITY]`). Order-preserving, de-duped. Fence-aware: a
    `Tags:` line inside a ``` / ~~~ code block is ignored (it is sample text, not
    the story's tags)."""
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if TAGS_LINE_RE.match(line):
            seen: list[str] = []
            for m in TAG_TOKEN_RE.findall(line):
                if m not in seen:
                    seen.append(m)
            return seen, True
    return [], False


def resolve_tags(tags: dict[str, dict], root: Path, names: list[str]) -> dict:
    """Resolve a SET of tag names to unioned paths/tests + per-risk-tag
    obligations. Returns {unknown, paths, tests, obligations}."""
    unknown = [n for n in names if n not in tags or not isinstance(tags[n], dict)]
    path_globs: list[str] = []
    test_globs: list[str] = []
    obligations: list[tuple[str, str]] = []
    for n in names:
        if n in unknown:
            continue
        spec = tags[n]
        path_globs += spec.get("paths", []) or []
        test_globs += spec.get("tests", []) or []
        if _tag_type(spec) == "risk":
            for t in spec.get("triggers", []) or []:
                obligations.append((n, t))
    return {
        "unknown": unknown,
        "paths": resolve_paths(root, path_globs),
        "tests": resolve_paths(root, test_globs),
        "test_globs": sorted(set(test_globs)),
        "obligations": obligations,
    }


def cmd_resolve(tags: dict[str, dict], root: Path, names: list[str],
                source: str, strict: bool, had_tags_line: bool) -> int:
    if not had_tags_line and source.startswith("story"):
        msg = f"{source}: no `Tags:` line found"
        if strict:
            _die(msg + " (strict)", code=1)
        sys.stderr.write(f"wf context: WARN {msg}\n")
    if not names:
        # no tags to resolve; warn unless already handled above
        if had_tags_line or not source.startswith("story"):
            sys.stderr.write("wf context: WARN no tags to resolve\n")
        print("resolved tags: (none)")
        return 0
    res = resolve_tags(tags, root, names)
    if res["unknown"]:
        _die(f"unknown tag(s): {', '.join(res['unknown'])} "
             f"(define them in the context registry)", code=1)
    print(f"resolved tags: {', '.join(names)}")
    print(f"paths ({len(res['paths'])} files): " +
          (", ".join(res["paths"]) if res["paths"] else "(none)"))
    if res["tests"] or res["test_globs"]:
        print(f"tests ({len(res['tests'])} files): " +
              (", ".join(res["tests"]) if res["tests"]
               else "(globs: " + ", ".join(res["test_globs"]) + ")"))
    if res["obligations"]:
        print("obligations (from risk tags):")
        for tag, ob in res["obligations"]:
            print(f"- {tag}: {ob}")
    print(HINTS_NOT_TRUTH)
    return 0


def selftest() -> int:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as dd:
        root = Path(dd)
        (root / "src" / "auth").mkdir(parents=True)
        (root / "src" / "billing").mkdir(parents=True)
        (root / "src" / "auth" / "login.js").write_text("export function login(){}\n")
        (root / "src" / "auth" / "session.js").write_text("export const s = () => {};\n")
        (root / "src" / "billing" / "pay.js").write_text("export function pay(){}\n")
        cfg = root / "bmad.config.yaml"
        cfg.write_text(
            "context:\n"
            "  tags:\n"
            "    auth:\n"
            "      type: work_area\n"
            "      description: Auth flows\n"
            '      paths: ["src/auth/**"]\n'
            '      tests: ["src/auth/**/*.js"]\n'
            '      see_also: ["billing"]\n'
            "    billing:\n"
            '      paths: ["src/billing/**"]\n'
            "    SECURITY:\n"
            "      type: risk\n"
            '      paths: ["src/auth/**"]\n'
            '      triggers: ["require security review", "check input validation"]\n'
            "    stale:\n"
            '      paths: ["src/nope/**"]\n'
            "    badref:\n"
            '      paths: ["src/auth/login.js"]\n'
            '      see_also: ["ghost"]\n')
        tags = load_tags(cfg)
        probs = compute_check(tags, root)
        if not any("stale" in p and "0 files" in p for p in probs):
            problems.append("check did not flag the stale glob")
        if not any('badref: see_also "ghost"' in p for p in probs):
            problems.append("check did not flag the bad see_also")
        if any(p.startswith(("auth:", "billing:", "SECURITY:")) for p in probs):
            problems.append(f"check flagged a valid tag: {probs}")
        clean = {k: tags[k] for k in ("auth", "billing", "SECURITY")}
        if cmd_check(clean, root, quiet=True) != 0:
            problems.append("clean registry did not pass check")
        # invalid type is flagged
        bt = compute_check({"x": {"type": "weird", "paths": ["src/auth/**"]}}, root)
        if not any("invalid type" in p for p in bt):
            problems.append("check did not flag an invalid type")
        # a tag with neither paths nor triggers is flagged
        nt = compute_check({"empty": {"type": "risk"}}, root)
        if not any("must declare" in p for p in nt):
            problems.append("check did not flag a tag with no paths and no triggers")
        # a pure-risk tag (triggers only, no paths) is VALID
        if compute_check({"r": {"type": "risk",
                                "triggers": ["x"]}}, root):
            problems.append("a triggers-only risk tag was wrongly flagged")
        # allow_empty suppresses the stale-glob FAIL
        if compute_check({"e": {"paths": ["src/nope/**"], "allow_empty": True}}, root):
            problems.append("allow_empty did not suppress the stale-glob FAIL")
        # resolve: union of paths + risk obligations surface
        res = resolve_tags(tags, root, ["auth", "SECURITY"])
        if res["unknown"]:
            problems.append(f"resolve flagged known tags unknown: {res['unknown']}")
        if "src/auth/login.js" not in res["paths"]:
            problems.append("resolve missing auth paths")
        if ("SECURITY", "require security review") not in res["obligations"]:
            problems.append("resolve did not surface the SECURITY obligation")
        # resolve: an unknown tag is reported
        if resolve_tags(tags, root, ["nope"])["unknown"] != ["nope"]:
            problems.append("resolve did not report an unknown tag")
        # story parsing
        st, had = parse_story_tags("# Story\n\nTags: [auth] [SECURITY] [auth]\n\nbody\n")
        if st != ["auth", "SECURITY"] or not had:
            problems.append(f"story tag parse wrong: {st}, had={had}")
        if parse_story_tags("# Story\n\nno tags here\n") != ([], False):
            problems.append("story with no Tags line did not return empty")
        # a Tags line inside a code fence is ignored (sample text, not tags)
        fenced = "# Story\n\n```\nTags: [auth]\n```\n\nbody\n"
        if parse_story_tags(fenced) != ([], False):
            problems.append("fenced Tags line was wrongly parsed")
        # a real Tags line before a fenced one wins
        real_then_fenced = "Tags: [billing]\n\n```\nTags: [auth]\n```\n"
        if parse_story_tags(real_then_fenced) != (["billing"], True):
            problems.append("real Tags line before a fence was not preferred")
        # containment: a `..` glob must never surface a file above the root
        (root.parent / "context-selftest-outside.txt").write_text("x")
        try:
            escaped = resolve_paths(root, ["../**"])
            if any(f.startswith("..") or "context-selftest-outside" in f
                   for f in escaped):
                problems.append(f"resolve_paths escaped the repo root: {escaped}")
        finally:
            (root.parent / "context-selftest-outside.txt").unlink(missing_ok=True)
        # duplicate tag definitions -> load fails closed (exit 2)
        dup = root / "dup.yaml"
        dup.write_text('context:\n  tags:\n    a:\n      paths: ["x"]\n'
                       '    a:\n      paths: ["y"]\n')
        try:
            load_tags(dup)
            problems.append("duplicate tag def did not fail closed")
        except SystemExit as e:
            if e.code != 2:
                problems.append(f"duplicate tag def exit {e.code}, expected 2")
        # missing config -> exit 2
        try:
            load_tags(root / "nope.yaml")
            problems.append("missing config did not fail closed")
        except SystemExit as e:
            if e.code != 2:
                problems.append(f"missing config exit {e.code}, expected 2")
        # malformed context -> exit 2
        bad = root / "bad.yaml"
        bad.write_text("context:\n  tags: not_a_mapping\n")
        try:
            load_tags(bad)
            problems.append("malformed context did not fail closed")
        except SystemExit as e:
            if e.code != 2:
                problems.append(f"malformed context exit {e.code}, expected 2")
    if problems:
        print("wf context selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf context selftest: PASS (resolve+obligations, story-tag parse, "
          "check fail-closed incl. stale glob/bad see_also/invalid type/"
          "no-paths-no-triggers, allow_empty, duplicate-key + config errors)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf context")
    ap.add_argument("action", nargs="?",
                    choices=["list", "show", "pack", "resolve", "check"])
    ap.add_argument("tag", nargs="?")
    ap.add_argument("--config", default=None, help="path to bmad.config.yaml")
    ap.add_argument("--dir", default=None, help="repo root for globbing (default: config dir)")
    ap.add_argument("--tags", default=None, help="resolve: comma-separated tag names")
    ap.add_argument("--story", default=None, help="resolve: a story file with a Tags: line")
    ap.add_argument("--strict", action="store_true",
                    help="resolve: a story with no Tags line is a FAIL, not a warning")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("an action (list|show|pack|resolve|check) or --selftest is required")
    if args.config:
        config_path = Path(args.config)
    else:
        base = Path(args.dir) if args.dir else Path.cwd()
        config_path = base / "bmad.config.yaml"
    root = Path(args.dir) if args.dir else config_path.parent
    tags = load_tags(config_path)
    if args.action in ("show", "pack") and not args.tag:
        ap.error(f"'{args.action}' requires a <tag> argument")
    if args.action == "list":
        return cmd_list(tags, root)
    if args.action == "check":
        return cmd_check(tags, root)
    if args.action == "show":
        return cmd_show(tags, root, args.tag)
    if args.action == "pack":
        return cmd_pack(tags, root, args.tag)
    # resolve
    if bool(args.tags) == bool(args.story):
        ap.error("resolve requires exactly one of --tags or --story")
    if args.tags:
        names = [t.strip() for t in args.tags.split(",") if t.strip()]
        return cmd_resolve(tags, root, names, "tags", args.strict, True)
    story = Path(args.story)
    if not story.is_file():
        _die(f"story not found: {story}")
    names, had_tags_line = parse_story_tags(story.read_text())
    return cmd_resolve(tags, root, names, f"story {story.name}", args.strict,
                       had_tags_line=had_tags_line)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
