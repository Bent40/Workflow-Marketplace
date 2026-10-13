#!/usr/bin/env python3
"""wf-map.py — persistent structural project map: build / query / check.

Adopts the map-first retrieval IDEA (popularized by Graphify, 2026-04) without
the tool: instead of grep-and-read over the whole tree, an agent queries a
PERSISTED structural index and jumps straight to file:line targets, reading
only the spans it needs. Everything here is DETERMINISTIC, offline, stdlib-only
— no LLM pass, no hooks, no network. Same tree → byte-identical map.

Position among the neighbors (they build maps; none is queryable-persistent):
  compress-context  one-shot markdown map for small-context prompts (no store)
  wf describe       exact Python function catalog + probe (no query surface)
  wf context        config-declared tag → path bundles (guidance, not structure)

BUILD  walks the project, hashes every file (sha1 — the staleness ground
truth), and extracts symbols per language: Python via stdlib `ast` (exact:
classes, functions, Class.method, imports; regex fallback on syntax errors),
JS/TS via the same regex family compress-context uses (approximate), Markdown
headings (#..###), YAML top-level keys, shell/Go/Rust via cheap regexes.
Index: <project>/_workflow/map.json. Caps are reported, never silent.

QUERY  case-insensitive substring over symbol names, signatures, headings,
imports, and file paths; ranked (exact name > prefix > substring > text/path),
emitted as `path:line  kind  name — sig`. Exit 0 hits / 1 none (grep
convention). A moved git HEAD since build prints a staleness warning on stderr
— the answer still comes, honestly labelled.

CHECK  re-hashes the tree and diffs against the index: FRESH exit 0, STALE
exit 1 (added/changed/removed counts + capped sample), no map exit 2.
Fail-closed like `wf context check`.

Usage:
  wf map build  [--dir D] [--out F] [--exclude a,b] [--max-files N] [--json]
  wf map query  <term> [--dir D] [--kind K] [--limit N] [--json]
  wf map check  [--dir D] [--json]
  wf map --selftest
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Shared with compress-context.py — see scripts/_langmap.py for what is
# deliberately NOT shared (this tool's own exclusion additions, which keep
# .claude and drop build/vendor trees, and its h1-h3 heading depth).
from _langmap import (  # noqa: E402
    BASE_EXCLUDES, JS_EXTS, JS_IMPORT_RES, JS_SYMBOL_RULES, MD_EXTS, PY_EXTS,
    PY_SYMBOL_RE, SIG_MAXLEN, md_heading_re,
)

MAP_VERSION = 1
MAP_REL = Path("_workflow") / "map.json"

# Walk exclusions: parity with compress-context/wf-describe noise sets. Dot-dirs
# are skipped EXCEPT .claude (skills/hooks are real project structure). _bmad is
# indexed — on this repo the vendored skills ARE the searchable surface.
SKIP_DIRS = set(BASE_EXCLUDES) | {
    ".tox", "dist", "build", "target", ".next", "coverage", "vendor",
    "_bmad-output",
}
KEEP_DOTDIRS = {".claude"}
MAX_FILES_DEFAULT = 20000
EXTRACT_MAX_BYTES = 1_500_000  # symbol extraction cap; hashing has no cap
QUERY_LIMIT_DEFAULT = 20

YAML_EXTS = {".yaml", ".yml"}
SH_EXTS = {".sh", ".bash"}

MD_HEADING_RE = md_heading_re(3)
YAML_KEY_RE = re.compile(r"^([A-Za-z_][\w.-]*):(?:\s|$)")
SH_FUNC_RES = (
    re.compile(r"^(\w[\w-]*)\s*\(\)\s*\{?"),
    re.compile(r"^function\s+(\w[\w-]*)"),
)
GO_RES = (("func", re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)")),
          ("class", re.compile(r"^type\s+(\w+)\s+(?:struct|interface)")))
RS_RES = (("func", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)")),
          ("class", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+(\w+)")))


def _caller_dir(arg_dir: str | None) -> Path:
    if arg_dir:
        return Path(arg_dir).expanduser().resolve()
    env = os.environ.get("WF_CALLER_CWD")
    return Path(env).resolve() if env else Path.cwd().resolve()


def _git_head(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:
        return None


def _sig(line: str) -> str:
    line = line.strip()
    return line[:SIG_MAXLEN] + "…" if len(line) > SIG_MAXLEN else line


# --- extraction ---------------------------------------------------------------

def _extract_python(text: str) -> list[dict]:
    syms: list[dict] = []
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        for i, raw in enumerate(lines, 1):
            m = PY_SYMBOL_RE.match(raw)
            if m:
                kind = "class" if raw.lstrip().startswith("class") else "def"
                syms.append({"kind": kind, "name": m.group(1), "line": i, "sig": _sig(raw)})
        return syms

    def visit(nodes, prefix: str):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "def"
                name = f"{prefix}{node.name}"
                raw = lines[node.lineno - 1] if node.lineno <= len(lines) else node.name
                syms.append({"kind": kind, "name": name, "line": node.lineno, "sig": _sig(raw)})
                if isinstance(node, ast.ClassDef):
                    visit(node.body, f"{node.name}.")
    visit(tree.body, "")
    # imports anywhere in the file (try-wrapped and function-local included),
    # deduped per module root — "who imports X" must not miss guarded imports
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [(alias.name.split(".")[0], node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [(node.module.split(".")[0], node.lineno)]
        else:
            continue
        for mod, lineno in mods:
            if mod not in seen:
                seen.add(mod)
                syms.append({"kind": "import", "name": mod, "line": lineno, "sig": ""})
    return syms


def _extract_regex(text: str, table) -> list[dict]:
    syms = []
    for i, raw in enumerate(text.splitlines(), 1):
        for kind, rx in table:
            m = rx.match(raw)
            if m:
                syms.append({"kind": kind, "name": m.group(1), "line": i, "sig": _sig(raw)})
                break
    return syms


def _extract_js(text: str) -> list[dict]:
    syms = _extract_regex(text, JS_SYMBOL_RULES)
    for i, raw in enumerate(text.splitlines(), 1):
        for rx in JS_IMPORT_RES:
            m = rx.search(raw)
            if m and not m.group(1).startswith("."):
                syms.append({"kind": "import", "name": m.group(1), "line": i, "sig": ""})
    return syms


def _extract_md(text: str) -> list[dict]:
    syms = []
    in_fence = False
    for i, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = MD_HEADING_RE.match(raw)
        if m:
            syms.append({"kind": "heading", "name": m.group(2), "line": i, "sig": ""})
    return syms


def _extract_yaml(text: str) -> list[dict]:
    return [{"kind": "key", "name": m.group(1), "line": i, "sig": ""}
            for i, raw in enumerate(text.splitlines(), 1)
            if (m := YAML_KEY_RE.match(raw))]


def _extract_sh(text: str) -> list[dict]:
    syms = []
    for i, raw in enumerate(text.splitlines(), 1):
        for rx in SH_FUNC_RES:
            m = rx.match(raw)
            if m and m.group(1) not in ("if", "while", "for", "case"):
                syms.append({"kind": "func", "name": m.group(1), "line": i, "sig": _sig(raw)})
                break
    return syms


def _extract(path: Path, data: bytes) -> tuple[str, list[dict]]:
    """(lang, symbols) for one file; unknown/oversized/binary → ('other', [])."""
    ext = path.suffix.lower()
    if len(data) > EXTRACT_MAX_BYTES or b"\x00" in data[:8192]:
        return "other", []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "other", []
    if ext in PY_EXTS:
        return "py", _extract_python(text)
    if ext in JS_EXTS:
        return "js", _extract_js(text)
    if ext in MD_EXTS:
        return "md", _extract_md(text)
    if ext in YAML_EXTS:
        return "yaml", _extract_yaml(text)
    if ext in SH_EXTS:
        return "sh", _extract_sh(text)
    if ext == ".go":
        return "go", _extract_regex(text, GO_RES)
    if ext == ".rs":
        return "rs", _extract_regex(text, RS_RES)
    return "other", []


# --- walk / build -------------------------------------------------------------

def _walk(root: Path, extra_excludes: set[str]) -> list[Path]:
    skip = SKIP_DIRS | extra_excludes
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in skip and (not d.startswith(".") or d in KEEP_DOTDIRS)
        )
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p == root / MAP_REL:  # the index must never index itself
                continue
            out.append(p)
    return out


def _hash_tree(root: Path, extra_excludes: set[str], max_files: int):
    """[(relpath, sha1, size)] for the first max_files files + dropped count."""
    files = _walk(root, extra_excludes)
    dropped = max(0, len(files) - max_files)
    rows = []
    for p in files[:max_files]:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        rows.append((p.relative_to(root).as_posix(), hashlib.sha1(data).hexdigest(), data))
    return rows, dropped


def cmd_build(args) -> int:
    root = _caller_dir(args.dir)
    if not root.is_dir():
        sys.stderr.write(f"wf map build: not a directory: {root}\n")
        return 2
    extra = {e.strip() for e in (args.exclude or "").split(",") if e.strip()}
    rows, dropped = _hash_tree(root, extra, args.max_files)
    files: dict[str, dict] = {}
    n_syms = 0
    for rel, sha, data in rows:
        lang, syms = _extract(Path(rel), data)
        n_syms += len(syms)
        entry = {"sha1": sha, "size": len(data), "lang": lang}
        if syms:
            entry["symbols"] = syms
        files[rel] = entry
    index = {
        "version": MAP_VERSION,
        "generator": "wf-map",
        "built_head": _git_head(root),
        "excludes": sorted(SKIP_DIRS | extra),
        "max_files": args.max_files,
        "dropped_files": dropped,   # never a silent cap
        "files": files,
    }
    out_path = Path(args.out).expanduser().resolve() if args.out else root / MAP_REL
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, indent=None, separators=(",", ":"),
                                   sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "map": str(out_path), "files": len(files), "symbols": n_syms,
        "dropped_files": dropped, "built_head": index["built_head"],
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"wf map: built {out_path}")
        print(f"  files {len(files)}  symbols {n_syms}  head {index['built_head'] or '-'}")
        if dropped:
            print(f"  WARNING: {dropped} file(s) beyond --max-files {args.max_files} "
                  f"NOT indexed — raise --max-files for full coverage")
    return 0


# --- query --------------------------------------------------------------------

def _load_map(root: Path):
    path = root / MAP_REL
    if not path.is_file():
        sys.stderr.write(f"wf map: no index at {path} — run `wf map build` first\n")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"wf map: unreadable index {path}: {exc}\n")
        return None


def _score(term: str, name: str) -> int:
    low = name.lower()
    if low == term:
        return 100
    if low.startswith(term):
        return 80
    if term in low:
        return 60
    return 0


def cmd_query(args) -> int:
    root = _caller_dir(args.dir)
    index = _load_map(root)
    if index is None:
        return 2
    head_now = _git_head(root)
    if index.get("built_head") and head_now and head_now != index["built_head"]:
        sys.stderr.write(
            f"wf map: STALE-RISK — map built at {index['built_head']}, HEAD is "
            f"{head_now}; `wf map build` to refresh (`wf map check` for the diff)\n")
    term = args.term.lower()
    hits = []
    for rel, entry in index["files"].items():
        path_score = _score(term, rel) or _score(term, Path(rel).name)
        if path_score and (not args.kind or args.kind == "file"):
            hits.append((min(path_score, 30), rel, 1, "file", rel, ""))
        for s in entry.get("symbols", ()):
            if args.kind and s["kind"] != args.kind:
                continue
            sc = _score(term, s["name"])
            if not sc and s.get("sig") and term in s["sig"].lower():
                sc = 40
            if sc:
                hits.append((sc, rel, s["line"], s["kind"], s["name"], s.get("sig", "")))
    hits.sort(key=lambda h: (-h[0], h[1], h[2]))
    shown = hits[: args.limit]
    if args.json:
        print(json.dumps({"term": args.term, "total": len(hits), "shown": len(shown),
                          "hits": [{"path": h[1], "line": h[2], "kind": h[3],
                                    "name": h[4], "sig": h[5], "score": h[0]}
                                   for h in shown]}, indent=2))
    else:
        for sc, rel, line, kind, name, sig in shown:
            loc = f"{rel}:{line}"
            print(f"{loc:<60} {kind:<8} {name}" + (f" — {sig}" if sig and sig != name else ""))
        if len(hits) > len(shown):
            print(f"… {len(hits) - len(shown)} more hit(s) — raise --limit or narrow the term")
        if not hits:
            print(f"wf map: no hits for '{args.term}'")
    return 0 if hits else 1


# --- check --------------------------------------------------------------------

def cmd_check(args) -> int:
    root = _caller_dir(args.dir)
    index = _load_map(root)
    if index is None:
        return 2
    extra = set(index.get("excludes", [])) - SKIP_DIRS
    rows, dropped = _hash_tree(root, extra, index.get("max_files", MAX_FILES_DEFAULT))
    now = {rel: sha for rel, sha, _ in rows}
    then = {rel: e["sha1"] for rel, e in index["files"].items()}
    added = sorted(set(now) - set(then))
    removed = sorted(set(then) - set(now))
    changed = sorted(r for r in set(now) & set(then) if now[r] != then[r])
    stale = bool(added or removed or changed)
    if args.json:
        print(json.dumps({"fresh": not stale, "added": len(added), "removed": len(removed),
                          "changed": len(changed), "dropped_files": dropped,
                          "sample": (added + changed + removed)[:20]}, indent=2))
    elif stale:
        print(f"wf map check: STALE — +{len(added)} added  ~{len(changed)} changed  "
              f"-{len(removed)} removed (of {len(then)} indexed)")
        for rel in (added + changed + removed)[:10]:
            tag = "+" if rel in added else ("~" if rel in changed else "-")
            print(f"  {tag} {rel}")
        if len(added) + len(changed) + len(removed) > 10:
            print("  … (full diff via --json)")
        print("  → `wf map build` to refresh")
    else:
        print(f"wf map check: FRESH ({len(then)} files verified by content hash)")
    return 1 if stale else 0


# --- selftest -----------------------------------------------------------------

def selftest() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool):
        (print(f"  ok  {label}") if ok else failures.append(label))
        if not ok:
            print(f"  FAIL {label}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pkg").mkdir()
        (root / "pkg" / "billing.py").write_text(
            "import requests\n\nclass Invoice:\n    def total(self):\n        return 1\n\n"
            "def deduct_credits(user, amount):\n    return amount\n")
        (root / "app.ts").write_text(
            "import { x } from 'react'\nexport async function renderDashboard() {}\n")
        (root / "notes.md").write_text("# Billing design\n\n## Credit deduction\ntext\n")
        (root / "run.sh").write_text("deploy_edge() {\n  true\n}\n")

        argv = lambda *a: parse(list(a))  # noqa: E731
        check("build exits 0", cmd_build(argv("build", "--dir", td)) == 0)
        idx = json.loads((root / MAP_REL).read_text())
        check("map excludes itself", "_workflow/map.json" not in idx["files"])
        syms = {(s["name"], s["kind"], s["line"])
                for e in idx["files"].values() for s in e.get("symbols", ())}
        check("py class+method+func exact lines",
              {("Invoice", "class", 3), ("Invoice.total", "def", 4),
               ("deduct_credits", "def", 7)} <= syms)
        check("py import captured", ("requests", "import", 1) in syms)
        check("ts func + md heading + sh func",
              {("renderDashboard", "func", 2), ("Credit deduction", "heading", 3),
               ("deploy_edge", "func", 1)} <= syms)
        check("query hit exits 0", cmd_query(argv("query", "deduct", "--dir", td)) == 0)
        check("query miss exits 1",
              cmd_query(argv("query", "zzz_nonexistent", "--dir", td)) == 1)
        check("query --kind filters",
              cmd_query(argv("query", "deduct", "--dir", td, "--kind", "heading")) == 0)
        check("check FRESH exits 0", cmd_check(argv("check", "--dir", td)) == 0)
        (root / "pkg" / "billing.py").write_text("def changed():\n    pass\n")
        check("check STALE exits 1 after edit", cmd_check(argv("check", "--dir", td)) == 1)
        check("rebuild → FRESH again",
              cmd_build(argv("build", "--dir", td)) == 0
              and cmd_check(argv("check", "--dir", td)) == 0)
        check("no-map dir exits 2",
              cmd_query(argv("query", "x", "--dir", str(root / "pkg"))) == 2)

    if failures:
        print(f"wf map selftest: FAIL ({len(failures)}): " + "; ".join(failures))
        return 1
    print("wf map selftest: PASS (12 checks)")
    return 0


# --- cli ----------------------------------------------------------------------

def parse(argv: list[str]):
    ap = argparse.ArgumentParser(prog="wf map", add_help=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="walk + hash + extract → _workflow/map.json")
    b.add_argument("--dir"); b.add_argument("--out")
    b.add_argument("--exclude", help="extra dir names, comma-separated")
    b.add_argument("--max-files", type=int, default=MAX_FILES_DEFAULT)
    b.add_argument("--json", action="store_true")
    q = sub.add_parser("query", help="ranked file:line hits from the map")
    q.add_argument("term"); q.add_argument("--dir")
    q.add_argument("--kind", choices=["def", "class", "func", "heading", "key",
                                      "import", "file"])
    q.add_argument("--limit", type=int, default=QUERY_LIMIT_DEFAULT)
    q.add_argument("--json", action="store_true")
    c = sub.add_parser("check", help="re-hash tree, FRESH exit 0 / STALE exit 1")
    c.add_argument("--dir")
    c.add_argument("--json", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--selftest":
        return selftest()
    args = parse(argv)
    return {"build": cmd_build, "query": cmd_query, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
