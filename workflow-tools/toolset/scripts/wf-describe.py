#!/usr/bin/env python3
"""wf-describe.py — function swagger: catalog, friction rules, probe engine (Da).

Design: docs/mockups/wf-describe.md (v3, approved 2026-07-09). Three parts:

CATALOG (static, stdlib `ast`, exact): every function/method in the project,
module-grouped, with badges (boundary / inbound / fixture / plain), an input
schema derived from signatures + type hints, the manipulation chain
(assignment lines), boundary calls, and friction rules F1-F8 — every claim
anchored to file:line. Zero hits on a rule is reported as checked-none-found.

  F1 unguarded response/input access   (fail)     F5 no timeout        (hang)
  F2 no error/status check             (fail)     F6 non-idempotent    (info)
  F3 lossy transform on a wire value   (corrupt)  F7 raw input on wire (info)
  F4 call-time env resolution          (fail)     F8 global from resp  (corrupt)

PROBE (real execution, never simulation): --probe file.py:func --input '<json>'
runs the function in an ISOLATED SUBPROCESS — known boundary libs are stubbed
before import (nothing is charged/sent), sockets are blocked, and a line
tracer records each executed line with the intermediate values it produced.
An exception marks the exact line with the real error; later lines report
never-ran. --response '<json>' seeds what the stubbed boundary returns, so the
response-parsing path is exercised against a real shape. Typed dataclass
params are constructed from your JSON; arbitrary objects become SEEDED STUBS
(attributes return what your sample says; a missing attribute raises an honest
probe error, never a guess). Live-infra params (db sessions etc.) are refused
with a needs-a-fixture message unless your input provides them — a database is
never faked. Probes EXECUTE project code: a notice prints on every run.

OUTPUT: HTML snapshot (default <dir>/_workflow/describe.html, self-contained)
+ --json. --probe ... --save records the probe at _workflow/probes/<func>.json.
--serve (Db) is not built yet and says so.

Usage:
  wf describe [--dir D] [--json] [--out FILE] [--all]
  wf describe --probe <file.py:func> --input '<json>' [--response '<json>'] [--save]
  wf describe --selftest
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import linecache
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", "target", ".next", "coverage",
    "_bmad", "_bmad-output", ".claude", ".wf", ".bmad", "vendor", ".tox",
    "evals", "tests", "test",
}
FILE_CAP = 4000

# Boundary detector table — module roots whose calls cross the process
# boundary. Doubles as the probe's stub table.
BOUNDARY_LIBS = {
    "requests": "http", "httpx": "http", "aiohttp": "http", "urllib3": "http",
    "stripe": "sdk", "sendgrid": "sdk", "boto3": "sdk", "twilio": "sdk",
    "openai": "sdk", "anthropic": "sdk",
    "psycopg2": "db", "pymongo": "db", "redis": "db", "sqlalchemy": "db",
    "kafka": "queue", "pika": "queue",
}
HTTP_VERBS = {"get", "post", "put", "patch", "delete", "head", "options", "request", "send"}
MUTATING = {"post", "put", "patch", "delete", "create", "send", "charge", "publish", "insert"}

FIXTURE_ANNOTATIONS = {"Session", "Connection", "Engine", "Cursor", "AsyncSession"}
FIXTURE_PARAM_NAMES = {"session", "conn", "connection", "db", "cursor", "engine"}
INBOUND_NAME_RX = re.compile(r"^(parse_|normalize_|from_|load_|decode_|deserialize_|validate_)")
INBOUND_PARAMS = {"raw", "data", "payload", "body", "event", "message", "record"}

SEVERITY = {"F1": "fail", "F2": "fail", "F3": "corrupt", "F4": "fail",
            "F5": "hang", "F6": "info", "F7": "info", "F8": "corrupt"}
RULE_TITLES = {
    "F1": "unguarded response/input access", "F2": "no error/status check",
    "F3": "lossy transform on a wire value", "F4": "call-time env resolution",
    "F5": "no timeout", "F6": "non-idempotent mutation",
    "F7": "unvalidated input on the wire", "F8": "global state from response",
}


def _die(msg: str, code: int = 2) -> None:
    print(f"wf describe: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _src(path: Path, lineno: int) -> str:
    return linecache.getline(str(path), lineno).strip()


# ── catalog: AST scan ────────────────────────────────────────────────────────


def _call_root(node: ast.AST) -> str | None:
    """Leftmost name of a call chain: stripe.Charge.create -> 'stripe'."""
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _attr_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


class _FnScan(ast.NodeVisitor):
    """Single-function body scan: boundaries, env reads, friction evidence."""

    def __init__(self, module_globals: set[str], aliases: dict[str, str]):
        self.globals = module_globals
        self.aliases = aliases          # local alias -> boundary lib root
        self.boundary_calls: list[dict] = []
        self.env_reads: list[int] = []
        self.json_calls: list[int] = []          # <x>.json() sites
        self.guard_lines: list[int] = []         # raise_for_status/.ok/.status_code
        self.subscript_chains: list[tuple[int, str]] = []
        self.get_guarded: set[int] = set()       # .get( usage lines
        self.lossy_casts: list[int] = []
        self.fstring_calls: list[int] = []       # boundary call w/ f-string arg
        self.global_writes: list[int] = []
        self.assign_lines: list[int] = []
        self.try_depth = 0

    def visit_Try(self, node: ast.Try):
        self.try_depth += 1
        self.generic_visit(node)
        self.try_depth -= 1

    def visit_Assign(self, node: ast.Assign):
        self.assign_lines.append(node.lineno)
        for t in node.targets:
            root = t
            while isinstance(root, (ast.Subscript, ast.Attribute)):
                root = root.value
            if isinstance(t, (ast.Subscript, ast.Attribute)) and \
                    isinstance(root, ast.Name) and root.id in self.globals:
                self.global_writes.append(node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        func = node.func
        chain = _attr_chain(func) if isinstance(func, ast.Attribute) else []
        root = _call_root(node)
        lib = self.aliases.get(root or "", root)

        if lib in BOUNDARY_LIBS:
            verb = chain[-1].lower() if chain else ""
            kwargs = {k.arg for k in node.keywords if k.arg}
            self.boundary_calls.append({
                "lib": lib, "kind": BOUNDARY_LIBS[lib], "line": node.lineno,
                "verb": verb, "has_timeout": "timeout" in kwargs,
                "has_idem": any("idempoten" in (k or "") for k in kwargs),
                "mutating": verb in MUTATING,
                "fstring_arg": any(isinstance(a, ast.JoinedStr) for a in node.args)
                or any(isinstance(k.value, ast.JoinedStr) for k in node.keywords),
            })
        if chain and chain[-1] == "json" and not node.args:
            self.json_calls.append(node.lineno)
        if chain and chain[-1] == "raise_for_status":
            self.guard_lines.append(node.lineno)
        if chain and chain[-1] == "get" and node.args:
            self.get_guarded.add(node.lineno)
        if chain and chain[:1] == ["os"] and chain[-1] in ("getenv", "environ"):
            self.env_reads.append(node.lineno)
        if isinstance(func, ast.Name) and func.id in ("int", "float") and node.args:
            a = node.args[0]
            if isinstance(a, ast.BinOp) and isinstance(a.op, (ast.Mult, ast.Div)):
                self.lossy_casts.append(node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in ("ok", "status_code"):
            self.guard_lines.append(node.lineno)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        base = node.value
        # X[...] where X is <call>.json() or another subscript -> chain access
        if isinstance(base, ast.Call):
            ch = _attr_chain(base.func) if isinstance(base.func, ast.Attribute) else []
            if ch and ch[-1] == "json":
                self.subscript_chains.append((node.lineno, "response"))
        elif isinstance(base, ast.Subscript):
            self.subscript_chains.append((node.lineno, "chain"))
        elif isinstance(base, ast.Name):
            self.subscript_chains.append((node.lineno, base.id))
        # os.environ["X"]
        if isinstance(base, ast.Attribute):
            ch = _attr_chain(base)
            if ch[:2] == ["os", "environ"]:
                self.env_reads.append(node.lineno)
        self.generic_visit(node)


def _module_boundary_aliases(tree: ast.Module) -> dict[str, str]:
    """import requests as rq / from stripe import Charge -> alias map."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if root in BOUNDARY_LIBS:
                    aliases[a.asname or root] = root
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in BOUNDARY_LIBS:
                for a in node.names:
                    aliases[a.asname or a.name] = root
    return aliases


def _friction(fn: ast.FunctionDef, scan: _FnScan, path: Path, inbound: bool,
              params: list[dict]) -> list[dict]:
    hits: list[dict] = []

    def hit(rule: str, line: int, note: str) -> None:
        hits.append({"rule": rule, "severity": SEVERITY[rule], "line": line,
                     "source": _src(path, line), "note": note})

    param_names = {p["name"] for p in params}
    for line, base in scan.subscript_chains:
        if line in scan.get_guarded:
            continue
        if base in ("response", "chain"):
            hit("F1", line, "unguarded access on a response/chained value — "
                "upstream schema drift is a KeyError/IndexError here")
        elif inbound and base in param_names:
            hit("F1", line, f"unguarded key on inbound param `{base}` — a partial "
                "payload explodes mid-transform")
    if scan.json_calls and not scan.guard_lines and scan.boundary_calls:
        hit("F2", scan.json_calls[0], "response parsed with no status/error check — "
            "a non-2xx flows onward as data")
    for line in scan.lossy_casts:
        hit("F3", line, "truncating int/float cast on an arithmetic result — "
            "unit or precision drift corrupts silently")
    for line in scan.env_reads:
        hit("F4", line, "env resolved at call time — missing config fails at the "
            "first call in production, not at boot")
    for b in scan.boundary_calls:
        if b["kind"] == "http" and not b["has_timeout"]:
            hit("F5", b["line"], f"{b['lib']} call without timeout= — a stalled "
                "upstream stalls every caller")
        if b["mutating"] and not b["has_idem"]:
            hit("F6", b["line"], "mutating call with no idempotency key — a retry "
                "repeats the effect")
        if b["fstring_arg"]:
            hit("F7", b["line"], "f-string built into the wire call — un-encoded "
                "input can truncate/alter the request")
    for line in scan.global_writes:
        if scan.boundary_calls:
            hit("F8", line, "module-global written inside a boundary function — "
                "a partial failure leaves shared state corrupted")
    return hits


def _param_schema(a: ast.arg, fixture: bool) -> dict:
    ann = ast.unparse(a.annotation) if a.annotation else None
    kind = "json"
    if fixture:
        kind = "fixture"
    elif ann:
        base = ann.split("[")[0].split(".")[-1]
        if base in ("str", "int", "float", "bool", "Decimal", "bytes"):
            kind = "field"
        elif base in ("dict", "list", "Dict", "List", "Any", "Optional", "None"):
            kind = "json"
        else:
            kind = "object"
    return {"name": a.arg, "annotation": ann, "kind": kind}


def scan_file(path: Path, rel: str) -> list[dict]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError) as exc:
        return [{"module": rel, "error": f"unparseable: {exc}"}]
    aliases = _module_boundary_aliases(tree)
    module_globals = {t.id for n in tree.body if isinstance(n, ast.Assign)
                      for t in n.targets if isinstance(t, ast.Name)}
    out: list[dict] = []

    def walk(nodes, qual_prefix=""):
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                walk(node.body, qual_prefix + node.name + ".")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scan = _FnScan(module_globals, aliases)
                for st in node.body:
                    scan.visit(st)
                args = [a for a in node.args.args if a.arg not in ("self", "cls")]
                params = []
                for a in args:
                    ann = ast.unparse(a.annotation) if a.annotation else ""
                    fixture = (a.arg in FIXTURE_PARAM_NAMES
                               or ann.split("[")[0].split(".")[-1] in FIXTURE_ANNOTATIONS)
                    params.append(_param_schema(a, fixture))
                inbound = bool(INBOUND_NAME_RX.match(node.name)
                               or {p["name"] for p in params} & INBOUND_PARAMS)
                fr = _friction(node, scan, path, inbound, params)
                badges = []
                if scan.boundary_calls:
                    badges.append("boundary")
                if inbound:
                    badges.append("inbound")
                if any(p["kind"] == "fixture" for p in params):
                    badges.append("fixture")
                if not badges:
                    badges.append("plain")
                out.append({
                    "name": node.name, "qualname": qual_prefix + node.name,
                    "module": rel, "line": node.lineno,
                    "returns": ast.unparse(node.returns) if node.returns else None,
                    "params": params, "badges": badges,
                    "boundaries": [{"lib": b["lib"], "kind": b["kind"], "line": b["line"]}
                                   for b in scan.boundary_calls],
                    "manipulation": [{"line": l, "source": _src(path, l)}
                                     for l in scan.assign_lines[:8]],
                    "friction": fr,
                })
    walk(tree.body)
    return out


# ── JS/TS heuristic scanner (Dc — labeled `js-heuristic` on every card) ─────

JS_EXTS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
_JS_DECL = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)")
_JS_ARROW = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)=]*)\)\s*=>")
_JS_SDKS = ("stripe", "twilio", "pg", "mongoose", "redis", "got", "axios")


def _js_params(raw: str) -> list[dict]:
    params: list[dict] = []
    for piece in [p.strip() for p in raw.split(",") if p.strip()]:
        name = re.split(r"[?:=\s]", piece, 1)[0].strip("{}. ")
        if not name or not re.match(r"^\w+$", name):
            continue
        ann = piece.split(":", 1)[1].split("=")[0].strip() if ":" in piece else None
        base = (ann or "").split("<")[0].split("|")[0].strip()
        fixture = name in FIXTURE_PARAM_NAMES or base in ("Pool", "Client", "Connection", "Db")
        if fixture:
            kind = "fixture"
        elif base in ("string", "number", "boolean"):
            kind = "field"
        elif ann is None or base in ("any", "object", "unknown", "Record"):
            kind = "json"
        else:
            kind = "object"
        params.append({"name": name, "annotation": ann, "kind": kind})
    return params


def scan_js_file(path: Path, rel: str) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    out: list[dict] = []
    i = 0
    while i < len(lines):
        m = _JS_DECL.match(lines[i]) or _JS_ARROW.match(lines[i])
        if not m:
            i += 1
            continue
        name, raw_params = m.group(1), m.group(2)
        start = i
        depth = 0
        opened = False
        j = i
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            if "{" in lines[j]:
                opened = True
            if opened and depth <= 0:
                break
            j += 1
        body = "\n".join(lines[start:j + 1])

        def _line_of(rx: str) -> int | None:
            mm = re.search(rx, body)
            return start + 1 + body[:mm.start()].count("\n") if mm else None

        params = _js_params(raw_params)
        boundaries = []
        for lib_rx, lib in (
                (r"\bfetch\s*\(", "fetch"),
                (r"\baxios(?:\.\w+)?\s*\(", "axios"),
                *[(rf"\b{s}\.", s) for s in _JS_SDKS if s != "axios"]):
            ln = _line_of(lib_rx)
            if ln:
                boundaries.append({"lib": lib, "kind": "http" if lib in ("fetch", "axios", "got") else "sdk",
                                   "line": ln})
        inbound = bool(INBOUND_NAME_RX.match(re.sub(r"([A-Z])", r"_\1", name).lower() + "_")
                       or INBOUND_NAME_RX.match(name.lower() + "_")
                       or name.lower().startswith(("parse", "normalize", "from", "load", "decode"))
                       or {p["name"] for p in params} & INBOUND_PARAMS)
        hits: list[dict] = []

        def hit(rule: str, ln: int | None, note: str) -> None:
            if ln:
                hits.append({"rule": rule, "severity": SEVERITY[rule], "line": ln,
                             "source": lines[ln - 1].strip(), "note": note + " [heuristic]"})

        has_json = re.search(r"\.json\s*\(\s*\)", body)
        has_guard = re.search(r"\.ok\b|\.status(?:Code)?\b", body)
        hit("F1", _line_of(r"\.json\(\)\s*\)*\s*(?:\.\w+|\[)"),
            "unguarded chain directly on .json() — schema drift throws here")
        if has_json:
            hit("F1", _line_of(r"\.\w+\[\d+\]"),
                "numeric index into a parsed-response field with no guard")
        if inbound:
            for p in params:
                hit("F1", _line_of(rf"\b{p['name']}\.\w+\.\w+"),
                    f"deep access on inbound param `{p['name']}` — a partial payload "
                    "is a TypeError mid-transform")
        if boundaries and has_json and not has_guard:
            hit("F2", start + 1 + body[:has_json.start()].count("\n"),
                "response parsed with no ok/status check")
        hit("F3", _line_of(r"(?:parseInt|Math\.(?:round|trunc|floor))\([^)]*[*/]"),
            "truncating/rounding cast on arithmetic — unit drift corrupts silently")
        hit("F4", _line_of(r"process\.env[.\[]"),
            "env resolved at call time — missing config fails at first call")
        if re.search(r"\bfetch\s*\(", body) and not re.search(r"AbortSignal|signal\s*:", body):
            hit("F5", _line_of(r"\bfetch\s*\("), "fetch without an AbortSignal/timeout")
        if re.search(r"\baxios(?:\.\w+)?\s*\(", body) and "timeout" not in body:
            hit("F5", _line_of(r"\baxios(?:\.\w+)?\s*\("), "axios call without timeout")
        if (re.search(r"axios\.(post|put|patch|delete)\b", body)
                or re.search(r"method:\s*['\"](POST|PUT|PATCH|DELETE)", body)) \
                and not re.search(r"[Ii]dempoten", body):
            hit("F6", _line_of(r"axios\.(?:post|put|patch|delete)\b|method:\s*['\"]"),
                "mutating call with no idempotency key — a retry repeats the effect")
        hit("F7", _line_of(r"(?:fetch|axios(?:\.\w+)?)\s*\(\s*`[^`]*\$\{"),
            "template literal built into the wire call — un-encoded input")
        if boundaries:
            hit("F8", _line_of(r"(?m)^[ \t]*[A-Z_][A-Z0-9_]{2,}(?:\.\w+|\[[^\]]+\])\s*="),
                "module-global written inside a boundary function")

        badges = []
        if boundaries:
            badges.append("boundary")
        if inbound:
            badges.append("inbound")
        if any(p["kind"] == "fixture" for p in params):
            badges.append("fixture")
        if not badges:
            badges.append("plain")
        manip = []
        for k, ln_text in enumerate(lines[start:j + 1], start=start + 1):
            if re.match(r"^\s*(?:const|let|var)\s+\w+\s*=", ln_text) and len(manip) < 8:
                manip.append({"line": k, "source": ln_text.strip()})
        out.append({"name": name, "qualname": name, "module": rel, "line": start + 1,
                    "returns": None, "params": params, "badges": badges,
                    "boundaries": boundaries, "manipulation": manip,
                    "friction": hits, "scanner": "js-heuristic"})
        i = j + 1
    return out


def scan_project(root: Path) -> dict:
    functions: list[dict] = []
    errors: list[str] = []
    count = 0
    candidates = sorted(root.rglob("*.py")) + sorted(
        p for ext in JS_EXTS for p in root.rglob(f"*{ext}")
        if not p.name.endswith((".d.ts", ".min.js")))
    for p in candidates:
        relp = p.relative_to(root)
        if any(part in SKIP_DIRS for part in relp.parts[:-1]) or relp.parts[0].startswith("."):
            continue
        count += 1
        if count > FILE_CAP:
            errors.append(f"file cap {FILE_CAP} reached — catalog truncated (stated, not silent)")
            break
        scanned = (scan_file(p, relp.as_posix()) if p.suffix == ".py"
                   else scan_js_file(p, relp.as_posix()))
        for fn in scanned:
            if fn.get("error"):
                errors.append(f"{relp}: {fn['error']}")
            else:
                fn.setdefault("scanner", "py-ast")
                functions.append(fn)
    fr_fns = [f for f in functions if f["friction"]]
    sev: dict[str, int] = {}
    for f in fr_fns:
        for h in f["friction"]:
            sev[h["severity"]] = sev.get(h["severity"], 0) + 1
    return {
        "schema": 1, "root": str(root),
        "summary": {
            "functions": len(functions),
            "friction_functions": len(fr_fns),
            "friction_points": sum(len(f["friction"]) for f in fr_fns),
            "by_severity": sev,
            "rules_checked": sorted(RULE_TITLES),
        },
        "functions": functions,
        "errors": errors,
    }


# ── probe worker (runs in the ISOLATED subprocess) ──────────────────────────


class _StubResponse:
    def __init__(self, data):
        self._data = data if data is not None else {}
        self.status_code, self.ok, self.headers = 200, True, {}
        self.text = json.dumps(self._data)

    def json(self):
        return self._data

    def raise_for_status(self):
        return None

    def __repr__(self):
        return f"<stub response 200 {self.text[:60]}>"


class _StubAttr:
    def __init__(self, lib, path_, response, calls):
        self._lib, self._path, self._resp, self._calls = lib, path_, response, calls

    def __getattr__(self, k):
        if k.startswith("_"):
            raise AttributeError(k)
        return _StubAttr(self._lib, f"{self._path}.{k}", self._resp, self._calls)

    def __call__(self, *args, **kwargs):
        self._calls.append({
            "lib": self._lib, "call": self._path,
            "args": [repr(a)[:80] for a in args],
            "kwargs": {k: repr(v)[:80] for k, v in kwargs.items()},
        })
        return _StubResponse(self._resp)


class _Seeded:
    """Attribute/key access returns what the probe sample provided; anything
    missing raises an HONEST probe error, never a guessed value."""

    def __init__(self, data, name):
        object.__setattr__(self, "_d", data if isinstance(data, dict) else {})
        object.__setattr__(self, "_n", name)

    def __getattr__(self, k):
        d = object.__getattribute__(self, "_d")
        n = object.__getattribute__(self, "_n")
        if k in d:
            v = d[k]
            return _Seeded(v, f"{n}.{k}") if isinstance(v, dict) else v
        raise AttributeError(
            f"probe stub '{n}': attribute {k!r} not provided in your sample input")

    __getitem__ = __getattr__

    def get(self, k, default=None):
        return object.__getattribute__(self, "_d").get(k, default)

    def __repr__(self):
        return f"<seeded {object.__getattribute__(self, '_n')} {object.__getattribute__(self, '_d')!r}>"


def _probe_worker(file: str, func: str, input_json: str, response_json: str,
                  root: str) -> int:
    import importlib.util
    import socket as _socket
    import types

    calls: list[dict] = []
    try:
        sample = json.loads(input_json) if input_json else {}
        response = json.loads(response_json) if response_json else None
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "error": {"type": "BadInput",
              "msg": f"input/response is not valid JSON: {exc}"}}))
        return 0

    # 1. Block the network at the socket layer.
    def _blocked(*a, **k):
        raise RuntimeError("wf describe probe: network is blocked")
    _socket.socket = _blocked            # type: ignore[assignment]
    _socket.create_connection = _blocked  # type: ignore[assignment]

    # 2. Stub every known boundary lib BEFORE the project module imports it.
    for lib in BOUNDARY_LIBS:
        mod = types.ModuleType(lib)
        mod.__getattr__ = (lambda l: lambda k: _StubAttr(l, f"{l}.{k}", response, calls))(lib)  # type: ignore[attr-defined]
        sys.modules[lib] = mod

    # 3. Import the target module honestly.
    sys.path.insert(0, root)
    target = Path(root) / file
    try:
        spec = importlib.util.spec_from_file_location(target.stem, target)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)                 # type: ignore[union-attr]
    except BaseException as exc:  # noqa: BLE001
        print(json.dumps({"status": "import-error", "error": {
            "type": type(exc).__name__,
            "msg": f"could not import {file}: {exc}"}}))
        return 0

    obj = module
    for part in func.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            print(json.dumps({"status": "error", "error": {"type": "NotFound",
                  "msg": f"function {func!r} not found in {file}"}}))
            return 0
    import inspect
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError):
        print(json.dumps({"status": "error", "error": {"type": "NotCallable",
              "msg": f"{func!r} has no inspectable signature"}}))
        return 0

    # 4. Bind the sample to the parameters.
    params = [p for p in sig.parameters.values()
              if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
    bound: dict[str, object] = {}
    if len(params) == 1 and params[0].name not in (sample if isinstance(sample, dict) else {}):
        bound[params[0].name] = sample
    else:
        for p in params:
            if isinstance(sample, dict) and p.name in sample:
                v = sample[p.name]
                ann = p.annotation
                if isinstance(v, dict) and inspect.isclass(ann) and ann not in (dict, object):
                    try:
                        v = ann(**v)
                    except BaseException:  # noqa: BLE001
                        v = _Seeded(v, p.name)
                bound[p.name] = v
            elif p.default is not p.empty:
                continue
            else:
                fixture = (p.name in FIXTURE_PARAM_NAMES
                           or getattr(p.annotation, "__name__", "") in FIXTURE_ANNOTATIONS)
                kind = ("needs-fixture" if fixture else "error")
                msg = (f"parameter {p.name!r} is live infrastructure — provide it in "
                       f"--input (that IS the fixture); a database is never faked"
                       if fixture else f"parameter {p.name!r} not provided in --input")
                print(json.dumps({"status": kind, "error": {"type": "MissingParam", "msg": msg}}))
                return 0

    # 5. Trace + execute.
    code = obj.__code__ if hasattr(obj, "__code__") else None
    executed: list[int] = []
    line_values: dict[int, dict] = {}
    state = {"prev": {}, "last": None}
    err: dict = {}

    def _diff(frame):
        cur = {}
        for k, v in frame.f_locals.items():
            try:
                cur[k] = repr(v)[:120]
            except BaseException:  # noqa: BLE001
                cur[k] = "<unrepr>"
        if state["last"] is not None:
            d = {k: v for k, v in cur.items() if state["prev"].get(k) != v}
            if d:
                line_values.setdefault(state["last"], {}).update(d)
        state["prev"] = cur

    def tracer(frame, event, arg):
        if frame.f_code is not code:
            return None
        if event == "line":
            _diff(frame)
            state["last"] = frame.f_lineno
            if frame.f_lineno not in executed:
                executed.append(frame.f_lineno)
        elif event == "exception":
            err["line"] = frame.f_lineno
            err["type"] = arg[0].__name__
            err["msg"] = str(arg[1])[:300]
        elif event == "return":
            _diff(frame)
        return tracer

    result_repr = None
    status = "ok"
    sys.settrace(tracer)
    try:
        result = obj(**bound)
        result_repr = repr(result)[:300]
    except BaseException as exc:  # noqa: BLE001
        status = "exception"
        err.setdefault("type", type(exc).__name__)
        err.setdefault("msg", str(exc)[:300])
    finally:
        sys.settrace(None)

    src_file = str(target)
    trace = [{"line": ln, "source": linecache.getline(src_file, ln).rstrip(),
              "values": line_values.get(ln, {})} for ln in executed]
    print(json.dumps({
        "status": status, "function": func, "file": file,
        "input": sample, "response_seed": response,
        "trace": trace, "error": err or None,
        "boundary_calls": calls, "return": result_repr,
    }))
    return 0


# ── node probe worker (Dc) — written to a temp file and run under node ──────

_NODE_WORKER = r"""
const [,, file, func, inputJson, responseJson, root] = process.argv;
const path = require('path'); const fs = require('fs'); const util = require('util');
const RESP = responseJson ? JSON.parse(responseJson) : {};
const calls = [];
const net = require('net');
net.Socket.prototype.connect = function(){ throw new Error('wf describe probe: network is blocked'); };
require('dns').lookup = () => { throw new Error('wf describe probe: network is blocked'); };
const stubResponse = { ok: true, status: 200, statusCode: 200, headers: {}, data: RESP,
  json: async () => RESP, text: async () => JSON.stringify(RESP) };
globalThis.fetch = (...args) => {
  calls.push({lib: 'fetch', call: 'fetch', args: args.map(a => util.inspect(a).slice(0, 80)), kwargs: {}});
  return Promise.resolve(stubResponse);
};
const Module = require('module');
const STUBS = ['axios','got','node-fetch','stripe','pg','mongoose','redis','ioredis',
               '@prisma/client','aws-sdk','twilio','@sendgrid/mail','openai','@anthropic-ai/sdk'];
const origLoad = Module._load;
function mkStub(lib, p){
  const f = function(...args){
    calls.push({lib, call: p, args: args.map(a => util.inspect(a).slice(0, 80)), kwargs: {}});
    return Promise.resolve(stubResponse);
  };
  return new Proxy(f, { get(t, k){
    if (k === 'then' || typeof k === 'symbol') return undefined;
    if (k === 'default') return mkStub(lib, p);
    return mkStub(lib, p + '.' + String(k));
  }});
}
Module._load = function(id, ...rest){
  if (STUBS.includes(id)) return mkStub(id, id);
  return origLoad.apply(this, [id, ...rest]);
};
function out(o){ console.log(JSON.stringify(o)); }
(async () => {
  const abs = path.resolve(root, file);
  let mod;
  try { mod = await import(require('url').pathToFileURL(abs).href); }
  catch (e) { out({status: 'import-error', error: {type: e.constructor.name,
    msg: 'could not import ' + file + ': ' + e.message}}); return; }
  let fn = mod[func] ?? (mod.default && mod.default[func]);
  if (typeof fn !== 'function') { out({status: 'error', error: {type: 'NotFound',
    msg: "function '" + func + "' not found in " + file + " (is it exported?)"}}); return; }
  const input = inputJson ? JSON.parse(inputJson) : {};
  const m = fn.toString().match(/\(([^)]*)\)/);
  const params = m ? m[1].split(',').map(s => s.trim().split(/[=:\s{]/)[0]).filter(Boolean) : [];
  let args;
  if (params.length <= 1 && !(input && typeof input === 'object' && params[0] in input)) args = [input];
  else args = params.map(p => (input && p in input) ? input[p] : undefined);
  let result, status = 'ok', error = null;
  try { result = fn(...args); if (result && typeof result.then === 'function') result = await result; }
  catch (e) {
    status = 'exception';
    const escaped = abs.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const lm = (e.stack || '').split('\n')
      .map(l => l.match(new RegExp(escaped + ':(\\d+):(\\d+)'))).find(Boolean);
    const line = lm ? parseInt(lm[1], 10) : null;
    let src = null;
    try { if (line) src = fs.readFileSync(abs, 'utf8').split('\n')[line - 1].trim(); } catch {}
    error = {type: e.constructor.name, msg: String(e.message).slice(0, 300), line, source: src};
  }
  out({status, function: func, file, input, response_seed: responseJson ? RESP : null,
       trace: null,
       note: 'per-line value trace for JS arrives with Dc v2 (instrumentation); the failing line comes from the real stack',
       error, boundary_calls: calls,
       return: status === 'ok' ? util.inspect(result).slice(0, 300) : null});
})();
"""

import shutil  # noqa: E402


# ── probe runner (parent side) ───────────────────────────────────────────────


def run_probe(root: Path, spec: str, input_json: str, response_json: str) -> dict:
    if ":" not in spec:
        _die("--probe wants <file:function>")
    file, func = spec.split(":", 1)
    if not (root / file).is_file():
        _die(f"no such file under {root}: {file}")
    print("wf describe: probe executes project code "
          "(isolated subprocess · boundaries stubbed · network blocked)", file=sys.stderr)
    suffix = Path(file).suffix
    if suffix in JS_EXTS:
        node = shutil.which("node")
        if not node:
            return {"status": "error", "error": {"type": "NodeMissing",
                    "msg": "probing a JS/TS function needs `node` on PATH — not found"}}
        worker = Path(tempfile.gettempdir()) / "wf-describe-node-worker.cjs"
        worker.write_text(_NODE_WORKER, encoding="utf-8")
        cmd = [node]
        if suffix in (".ts", ".tsx"):
            cmd.append("--experimental-strip-types")
        cmd += [str(worker), file, func, input_json or "{}",
                response_json or "", str(root)]
        env = {**os.environ, "NODE_NO_WARNINGS": "1"}
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    else:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--_probe-worker",
             "--file", file, "--func", func, "--input", input_json or "{}",
             "--response", response_json or "", "--root", str(root)],
            capture_output=True, text=True, timeout=60,
        )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"status": "error", "error": {"type": "WorkerFailure",
                "msg": (proc.stderr or "no output").strip()[:400]}}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return {"status": "error", "error": {"type": "WorkerGarbage",
                "msg": proc.stdout[:400]}}


def render_probe(res: dict) -> str:
    lines: list[str] = []
    st = res.get("status")
    if st in ("error", "import-error", "needs-fixture"):
        e = res.get("error") or {}
        tag = "needs a fixture" if st == "needs-fixture" else "probe error"
        return f"✗ {tag}: [{e.get('type')}] {e.get('msg')}"
    err = res.get("error")
    fail_line = err.get("line") if err else None
    if res.get("trace") is None and err and err.get("line"):
        lines.append(f"  ✗ {err['line']:>4}  {err.get('source') or ''}")
    if res.get("note"):
        lines.append(f"  note: {res['note']}")
    for t in res.get("trace") or []:
        mark = "✗" if t["line"] == fail_line else "·"
        vals = "   ".join(f"{k} = {v}" for k, v in (t["values"] or {}).items())
        lines.append(f"  {mark} {t['line']:>4}  {t['source'].strip():<58} {vals}")
        if t["line"] == fail_line:
            break
    for c in res.get("boundary_calls") or []:
        lines.append(f"  ⛔ boundary intercepted: {c['call']}({', '.join(list(c['kwargs']) or c['args'])})")
    if st == "ok":
        lines.append(f"  ✓ returns {res.get('return')}")
    else:
        lines.append(f"  ✗ fails at line {fail_line}: {err.get('type')}: {err.get('msg')}"
                     if err else "  ✗ failed (no line info)")
        lines.append("    (lines after the failure never ran)")
    return "\n".join(lines)


# ── HTML snapshot ────────────────────────────────────────────────────────────

_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1a1d21;--dim:#6b7280;--line:#e5e5e0;
--mono:ui-monospace,Menlo,Consolas,monospace;--fail:#b3261e;--corrupt:#9a5b00;
--hang:#7a4fbf;--info:#3565a0;--ok:#2e7d4f}
@media(prefers-color-scheme:dark){:root{--bg:#16181c;--card:#1f2228;--ink:#e8eaed;
--dim:#9aa0a6;--line:#33373d;--fail:#ff8a80;--corrupt:#ffc107;--hang:#c39bf5;
--info:#8ab4f8;--ok:#81c995}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,sans-serif;
padding:1.5rem 1rem 3rem}main{max-width:880px;margin:0 auto}
h1{font-size:1.15rem}code,pre{font-family:var(--mono);font-size:.82rem}
.sub{color:var(--dim);font-size:.8rem;margin-bottom:1rem}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:8px;font-size:.82rem;margin-bottom:1.6rem}
th,td{text-align:left;padding:.4rem .6rem;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-size:.7rem;text-transform:uppercase}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:1rem 1.2rem;margin-bottom:1.2rem}
.card h2{font-size:.95rem;font-family:var(--mono);margin:0}
.loc{color:var(--dim);font-size:.75rem;font-family:var(--mono);margin:.1rem 0 .6rem}
.k{font-size:.68rem;font-weight:700;text-transform:uppercase;color:var(--dim);margin:.6rem 0 .2rem}
pre{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:.45rem .65rem;
overflow-x:auto}
.fp{border-left:3px solid var(--line);padding:.3rem .6rem;margin:.35rem 0;font-size:.84rem}
.fp.fail{border-color:var(--fail)}.fp.corrupt{border-color:var(--corrupt)}
.fp.hang{border-color:var(--hang)}.fp.info{border-color:var(--info)}
.tag{font-size:.64rem;font-weight:700;border:1px solid;border-radius:99px;padding:.03rem .4rem;margin-right:.3rem}
.tag.fail{color:var(--fail);border-color:var(--fail)}.tag.corrupt{color:var(--corrupt);border-color:var(--corrupt)}
.tag.hang{color:var(--hang);border-color:var(--hang)}.tag.info{color:var(--info);border-color:var(--info)}
.foot{color:var(--dim);font-size:.76rem;border-top:1px solid var(--line);padding-top:.7rem;margin-top:2rem}
"""


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(cat: dict, *, show_all: bool = False) -> str:
    s = cat["summary"]
    fns = cat["functions"]
    shown = fns if show_all else [f for f in fns if f["friction"] or "inbound" in f["badges"]]
    rows = "".join(
        f"<tr><td><code>{_esc(f['qualname'])}</code></td><td><code>{_esc(f['module'])}</code></td>"
        f"<td>{' '.join(_esc(b) for b in f['badges'])}</td>"
        f"<td>{' '.join(sorted({h['rule'] for h in f['friction']})) or '—'}</td></tr>"
        for f in shown)
    cards = []
    for f in shown:
        params = ", ".join(
            f"{p['name']}: {p['annotation'] or 'untyped'} [{p['kind']}]" for p in f["params"])
        manip = "\n".join(f"{m['source']}" for m in f["manipulation"] if m["source"])
        fps = "".join(
            f"<div class='fp {h['severity']}'><span class='tag {h['severity']}'>{h['rule']} · "
            f"{h['severity']}</span>{_esc(h['note'])} <span class='loc'>{_esc(f['module'])}:"
            f"{h['line']} — <code>{_esc(h['source'])}</code></span></div>"
            for h in f["friction"]) or "<div class='fp'>F1–F8 checked — none found</div>"
        probe_hint = (f"wf describe --probe {f['module']}:{f['qualname']} "
                      f"--input '{{…}}'")
        cards.append(
            f"<div class='card'><h2>{_esc(f['qualname'])}({_esc(params)})"
            f"{' → ' + _esc(f['returns']) if f['returns'] else ''}</h2>"
            f"<div class='loc'>{_esc(f['module'])}:{f['line']} · {' · '.join(f['badges'])}"
            + (" · <b>js-heuristic scanner</b> (regex-scope; labeled per design)"
               if f.get("scanner") == "js-heuristic" else "") + "</div>"
            + (f"<div class='k'>manipulation</div><pre>{_esc(manip)}</pre>" if manip else "")
            + f"<div class='k'>friction</div>{fps}"
            + f"<div class='k'>probe</div><pre>{_esc(probe_hint)}</pre></div>")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>wf describe · {_esc(Path(cat['root']).name)}</title><style>{_CSS}</style></head>
<body><main><h1><code>wf describe</code> · {_esc(Path(cat['root']).name)}</h1>
<div class="sub">static snapshot · {s['functions']} functions · {s['friction_functions']}
friction-bearing shown{' (use --all for every function)' if not show_all else ''} ·
{s['friction_points']} friction points · rules F1–F8 all checked ·
probe any card with the command it shows (--serve arrives with Db)</div>
<table><tr><th>function</th><th>module</th><th>badges</th><th>friction</th></tr>{rows}</table>
{''.join(cards)}
<div class="foot">every claim anchored to file:line by the AST scanner; probes are REAL
execution (isolated subprocess · stubbed boundaries · no network) — nothing model-inferred.
machine view: <code>wf describe --json</code></div></main></body></html>"""


# ── Db: --serve (live two-pane UI) and --replay (saved-probe corpus) ─────────

_APP_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>wf describe · %TITLE%</title><style>%CSS%
.wrap{display:flex;gap:0;max-width:none}nav{width:290px;flex:none;border-right:1px solid var(--line);
padding:.7rem;overflow-y:auto;height:calc(100vh - 70px)}
nav input{width:100%%;font:inherit;padding:.3rem .5rem;border:1px solid var(--line);border-radius:6px;
background:var(--card);color:var(--ink);margin-bottom:.5rem}
.chip{font-size:.7rem;border:1px solid var(--line);border-radius:99px;padding:.1rem .5rem;cursor:pointer;color:var(--dim)}
.chip.on{border-color:var(--info);color:var(--info);font-weight:700}
.mod{color:var(--dim);font-size:.7rem;font-family:var(--mono);margin:.55rem 0 .1rem}
.fn{padding:.22rem .5rem;border-radius:6px;cursor:pointer;font-family:var(--mono);font-size:.78rem;display:flex;justify-content:space-between;gap:.4rem}
.fn:hover,.fn.sel{background:color-mix(in srgb,var(--info) 12%%,transparent)}
main{flex:1;padding:1rem 1.3rem;max-width:840px}
textarea{width:100%%;font-family:var(--mono);font-size:.8rem;background:var(--bg);color:var(--ink);
border:1px solid var(--line);border-radius:6px;padding:.4rem .6rem;resize:vertical}
.run{font:inherit;font-weight:700;padding:.3rem .9rem;border-radius:6px;border:1px solid var(--ok);
background:transparent;color:var(--ok);cursor:pointer;margin:.4rem 0}
.tl{display:flex;gap:.7rem;padding:.24rem .6rem;font-family:var(--mono);font-size:.78rem;border-bottom:1px solid var(--line)}
.tl .ln{color:var(--dim);min-width:3em;text-align:right}.tl .val{color:var(--ok);margin-left:auto;padding-left:.8rem}
.tl.red{background:color-mix(in srgb,var(--fail) 14%%,transparent)}.tl.red .val{color:var(--fail);font-weight:700}
.verdict{padding:.4rem .6rem;font-size:.8rem}.bad{color:var(--fail)}.good{color:var(--ok)}
.trace{border:1px solid var(--line);border-radius:6px;margin-top:.5rem;background:var(--card);overflow:hidden}
</style></head><body><main style="max-width:none;padding:0">
<div style="padding:.6rem 1rem;border-bottom:1px solid var(--line)">
<b><code>wf describe --serve</code> · %TITLE%</b>
<span class="sub" style="margin-left:.7rem">live — Execute runs YOUR code (isolated subprocess ·
boundaries stubbed · network blocked)</span></div>
<div class="wrap"><nav>
<input id="q" placeholder="filter…" oninput="draw()">
<span class="chip on" id="c-fr" onclick="mode='fr';chips();draw()">friction</span>
<span class="chip" id="c-all" onclick="mode='all';chips();draw()">all</span>
<div id="list"></div></nav><main id="pane"></main></div>
<script>
const CAT = %CATALOG%;
let mode='fr', sel=null;
function chips(){document.getElementById('c-fr').className='chip'+(mode==='fr'?' on':'');
document.getElementById('c-all').className='chip'+(mode==='all'?' on':'');}
function fns(){const q=document.getElementById('q').value.toLowerCase();
return CAT.functions.filter(f=>(mode==='all'||f.friction.length||f.badges.includes('inbound'))
&&(!q||f.qualname.toLowerCase().includes(q)||f.module.toLowerCase().includes(q)));}
function draw(){const by={};for(const f of fns()){(by[f.module]=by[f.module]||[]).push(f);}
let h='';for(const m of Object.keys(by).sort()){h+=`<div class="mod">${m}</div>`;
for(const f of by[m]){const k=f.module+':'+f.qualname;
h+=`<div class="fn${k===sel?' sel':''}" onclick="pick('${k}')"><span>${f.qualname}</span>`
+`<span class="sub">${f.badges[0]}</span></div>`;}}
document.getElementById('list').innerHTML=h||'<div class="sub">no matches</div>';}
function pick(k){sel=k;draw();const [m,q]=[k.slice(0,k.lastIndexOf(':')),k.slice(k.lastIndexOf(':')+1)];
const f=CAT.functions.find(x=>x.module===m&&x.qualname===q);
const params=f.params.map(p=>`${p.name}: ${p.annotation||'untyped'} [${p.kind}]`).join(', ');
const fps=f.friction.map(h=>`<div class="fp ${h.severity}"><span class="tag ${h.severity}">${h.rule}</span>`
+`${h.note} <span class="loc">${f.module}:${h.line}</span></div>`).join('')
||'<div class="fp">F1–F8 checked — none found</div>';
const skel=f.params.length?('{ '+f.params.filter(p=>p.kind!=='fixture').map(p=>`"${p.name}": null`).join(', ')+' }'):'{}';
document.getElementById('pane').innerHTML=
`<div class="sig" style="font-family:var(--mono);font-weight:700">${f.qualname}(${params})</div>
<div class="loc">${f.module}:${f.line} · ${f.badges.join(' · ')}${f.scanner==='js-heuristic'?' · <b>js-heuristic</b>':''}</div>
<div class="k">FRICTION</div>${fps}
<div class="k">TRY IT OUT</div>
<div>input <textarea id="pin" rows="2">${skel}</textarea></div>
<div>stubbed boundary returns (optional) <textarea id="prsp" rows="1"></textarea></div>
<button class="run" onclick="exec('${f.module}','${f.qualname}')">▶ Execute</button>
<div id="out"></div>`;}
async function exec(m,q){const out=document.getElementById('out');out.innerHTML='<div class="sub">running…</div>';
const r=await fetch('/probe',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({spec:m+':'+q,input:document.getElementById('pin').value,
response:document.getElementById('prsp').value})});
const res=await r.json();let h='<div class="trace">';const fl=res.error&&res.error.line;
if(res.trace){for(const t of res.trace){const red=t.line===fl;
h+=`<div class="tl${red?' red':''}"><span class="ln">${t.line}</span><code>${(t.source||'').trim()}</code>`
+`<span class="val">${red?(res.error.type+': '+res.error.msg):Object.entries(t.values||{}).map(([k,v])=>k+' = '+v).join('  ')}</span></div>`;
if(red)break;}}
else if(res.error&&res.error.line){h+=`<div class="tl red"><span class="ln">${res.error.line}</span>`
+`<code>${res.error.source||''}</code><span class="val">${res.error.type}</span></div>`;}
for(const c of res.boundary_calls||[]){h+=`<div class="tl"><span class="ln">⛔</span><code>intercepted: ${c.call}</code></div>`;}
h+='</div>';
if(res.status==='ok'){h+=`<div class="verdict good">✓ returns ${res.return}</div>`;}
else{const e=res.error||{};h+=`<div class="verdict bad">✗ ${e.type||res.status}: ${e.msg||''}`
+(e.line?` — at line ${e.line}; later lines never ran`:'')+'</div>';}
if(res.note)h+=`<div class="sub">${res.note}</div>`;
out.innerHTML=h;}
chips();draw();const first=fns()[0];if(first)pick(first.module+':'+first.qualname);
</script></main></body></html>"""


def serve_app_html(cat: dict) -> str:
    html = _APP_HTML.replace("%CSS%", _CSS)
    html = html.replace("%TITLE%", _esc(Path(cat["root"]).name))
    html = html.replace("%CATALOG%", json.dumps(_strip_serve(cat)))
    return html.replace("%%", "%")


def _strip_serve(cat: dict) -> dict:
    return {"root": cat["root"], "summary": cat["summary"],
            "functions": [{k: f[k] for k in ("qualname", "module", "line", "params",
                                             "badges", "friction", "scanner")
                           if k in f or k == "scanner"}
                          | {"scanner": f.get("scanner", "py-ast")}
                          for f in cat["functions"]]}


def serve(root: Path, port: int) -> int:
    import http.server

    cat = scan_project(root)
    html = serve_app_html(cat)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def do_GET(self):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/probe":
                self.send_response(404)
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                req = json.loads(self.rfile.read(length) or b"{}")
                res = run_probe(root, req.get("spec", ""),
                                req.get("input") or "{}", req.get("response") or "")
            except SystemExit:
                res = {"status": "error", "error": {"type": "BadSpec", "msg": "bad probe spec"}}
            except Exception as exc:  # noqa: BLE001
                res = {"status": "error", "error": {"type": type(exc).__name__, "msg": str(exc)[:200]}}
            body = json.dumps(res).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"wf describe --serve: http://127.0.0.1:{srv.server_address[1]}/ "
          f"({cat['summary']['functions']} functions; Execute RUNS project code — "
          "isolated subprocess, stubbed boundaries, no network). Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def replay_probes(root: Path) -> tuple[int, list[str]]:
    """Re-run every saved probe; DRIFT when status/error-type/error-line moved.
    Returns (exit_code, report_lines) — the CI hook (DD3)."""
    probes_dir = root / "_workflow" / "probes"
    saved = sorted(probes_dir.glob("*.json")) if probes_dir.is_dir() else []
    if not saved:
        return 0, ["no saved probes under _workflow/probes/ — nothing to replay (stated)"]
    lines: list[str] = []
    drift = 0
    for p in saved:
        rec = _read_json(p)
        if not isinstance(rec, dict) or "probe" not in rec:
            drift += 1
            lines.append(f"DRIFT {p.name}: unreadable saved probe")
            continue
        old = rec.get("result") or {}
        new = run_probe(root, rec["probe"], rec.get("input") or "{}",
                        rec.get("response") or "")
        oe, ne = old.get("error") or {}, new.get("error") or {}
        same = (old.get("status") == new.get("status")
                and oe.get("type") == ne.get("type") and oe.get("line") == ne.get("line")
                and old.get("return") == new.get("return"))
        if same:
            lines.append(f"PASS  {p.name} ({new.get('status')})")
        else:
            drift += 1
            lines.append(f"DRIFT {p.name}: {old.get('status')}/{oe.get('type')}@{oe.get('line')} "
                         f"-> {new.get('status')}/{ne.get('type')}@{ne.get('line')}")
    return (1 if drift else 0), lines


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ── selftest ─────────────────────────────────────────────────────────────────

_FIXTURE = '''\
import os
import requests

CACHE = {}

def parse_user(raw):
    uid = int(raw["id"])
    handle = raw["handle"].replace("@", "")
    plan = raw.get("plan", "free")
    return (uid, handle, plan)

def geocode(addr: str):
    r = requests.get(f"https://geo.example.com/v1?q={addr}")
    return (r.json()["results"][0]["lat"], r.json()["results"][0]["lng"])

def charge(total: float, currency: str):
    key = os.environ["PAY_KEY"]
    cents = int(total * 100)
    resp = requests.post("https://pay.example.com/charge",
                         json={"amount": cents, "cur": currency.lower()}, timeout=5)
    CACHE["last"] = resp.json()["id"]
    return cents

def get_orders(session, user_id: int):
    return session.query(user_id)

def safe_fetch(url: str):
    r = requests.get(url, timeout=3)
    r.raise_for_status()
    return r.json().get("data", [])

def slugify(title: str) -> str:
    return title.lower().replace(" ", "-")
'''


_JS_FIXTURE_MJS = '''export function parseUser(raw) {
  const uid = parseInt(raw.id, 10);
  const handle = raw.handle.replace("@", "");
  return { uid, handle, plan: raw.plan || "free" };
}

export async function geocode(addr) {
  const r = await fetch(`https://geo.example.com/v1?q=${addr}`);
  const j = await r.json();
  return [j.results[0].lat, j.results[0].lng];
}

export async function safeFetch(url) {
  const r = await fetch(url, { signal: AbortSignal.timeout(3000) });
  if (!r.ok) throw new Error("bad status");
  const j = await r.json();
  return j.data || [];
}

export function slug(title) {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}
'''

_JS_FIXTURE_CJS = '''const axios = require('axios');

const CACHE = {};

async function charge(total, currency) {
  const key = process.env.PAY_KEY;
  const cents = Math.round(total * 100);
  const resp = await axios.post("https://pay.example.com/charge",
    { amount: cents, cur: currency.toLowerCase(), key }, { timeout: 5000 });
  CACHE.last = resp.data.id;
  return cents;
}

module.exports = { charge };
'''


def selftest() -> int:
    problems: list[str] = []
    node_note = "node probes RAN"
    with tempfile.TemporaryDirectory(prefix="wfdescribe-") as td:
        root = Path(td)
        (root / "app").mkdir()
        (root / "app" / "svc.py").write_text(_FIXTURE, encoding="utf-8")

        cat = scan_project(root)
        by = {f["qualname"]: f for f in cat["functions"]}
        if len(by) != 6:
            problems.append(f"catalog: expected 6 functions, got {sorted(by)}")

        # badges
        if "inbound" not in by["parse_user"]["badges"]:
            problems.append("catalog: parse_user should be inbound")
        if "boundary" not in by["geocode"]["badges"]:
            problems.append("catalog: geocode should be boundary")
        if "fixture" not in by["get_orders"]["badges"]:
            problems.append("catalog: get_orders should be fixture-flagged")
        if by["slugify"]["badges"] != ["plain"]:
            problems.append(f"catalog: slugify should be plain: {by['slugify']['badges']}")

        # friction rules — positives AND negatives
        def rules(fn):
            return {h["rule"] for h in by[fn]["friction"]}
        if "F1" not in rules("parse_user"):
            problems.append("F1 missed: parse_user unguarded raw[...]")
        if "F1" not in rules("geocode") or "F2" not in rules("geocode") \
                or "F5" not in rules("geocode") or "F7" not in rules("geocode"):
            problems.append(f"geocode rules wrong: {rules('geocode')}")
        gm = {h["rule"] for h in by["charge"]["friction"]}
        if not {"F3", "F4", "F6", "F8"} <= gm:
            problems.append(f"charge rules wrong: {gm}")
        if "F5" in gm:
            problems.append("F5 false positive: charge HAS a timeout")
        sf = rules("safe_fetch")
        if "F2" in sf or "F1" in sf or "F5" in sf:
            problems.append(f"safe_fetch false positives (guarded + .get + timeout): {sf}")
        if rules("slugify"):
            problems.append(f"slugify should have zero friction: {rules('slugify')}")

        # schema kinds
        pk = {p["name"]: p["kind"] for p in by["charge"]["params"]}
        if pk != {"total": "field", "currency": "field"}:
            problems.append(f"schema: charge params wrong: {pk}")
        if by["get_orders"]["params"][0]["kind"] != "fixture":
            problems.append("schema: session should be fixture kind")
        if by["parse_user"]["params"][0]["kind"] != "json":
            problems.append("schema: untyped raw should be json kind")

        # HTML + json snapshot
        html = render_html(cat)
        for needle in ("parse_user", "F1", "rules F1–F8 all checked", "wf describe --probe"):
            if needle not in html:
                problems.append(f"html missing {needle!r}")

        # ── probes (REAL subprocess execution) ─────────────────────────────
        def probe(func, inp, resp=""):
            return run_probe(root, f"app/svc.py:{func}", inp, resp)

        r = probe("parse_user", '{"id": "7", "handle": "@ada"}')
        if r["status"] != "ok" or "('7'" in str(r.get("return")) \
                or r.get("return") != "(7, 'ada', 'free')":
            problems.append(f"probe: valid parse_user wrong: {r.get('status')}/{r.get('return')}")
        else:
            vals = {k: v for t in r["trace"] for k, v in t["values"].items()}
            if vals.get("uid") != "7" or vals.get("handle") != "'ada'":
                problems.append(f"probe: intermediate values missing: {vals}")

        r = probe("parse_user", "{}")
        if r["status"] != "exception" or r["error"]["type"] != "KeyError" \
                or r["error"].get("line") != 7:
            problems.append(f"probe: empty user should KeyError at line 7: {r.get('error')}")

        r = probe("parse_user", '{"id": "7", "handle": null}')
        e = r.get("error") or {}
        if r["status"] != "exception" or e.get("type") != "AttributeError" or e.get("line") != 8:
            problems.append(f"probe: null handle should AttributeError at line 8 (.replace): {e}")
        else:
            executed = [t["line"] for t in r["trace"]]
            if 9 in executed:
                problems.append("probe: line after the failure claims to have run")

        # response-side: normal + empty results (F1 executable)
        r = probe("geocode", '{"addr": "x"}', '{"results": [{"lat": 1.0, "lng": 2.0}]}')
        if r["status"] != "ok" or r.get("return") != "(1.0, 2.0)":
            problems.append(f"probe: geocode normal response wrong: {r.get('return')} {r.get('error')}")
        if not r.get("boundary_calls"):
            problems.append("probe: geocode boundary call not intercepted/recorded")
        r = probe("geocode", '{"addr": "x"}', '{"results": []}')
        if r["status"] != "exception" or (r.get("error") or {}).get("type") != "IndexError":
            problems.append(f"probe: empty results should IndexError: {r.get('error')}")

        # env missing -> F4 demonstrated live; boundary never reached
        r = probe("charge", '{"total": 19.995, "currency": "USD"}')
        if r["status"] != "exception" or (r.get("error") or {}).get("type") != "KeyError":
            problems.append(f"probe: missing PAY_KEY should KeyError: {r.get('error')}")

        # needs-fixture honesty
        r = probe("get_orders", '{"user_id": 3}')
        if r["status"] != "needs-fixture":
            problems.append(f"probe: live session should refuse with needs-fixture: {r}")
        # ...and providing the data IS the fixture (seeded stub takes over)
        r = probe("get_orders", '{"user_id": 3, "session": {"query": "unused"}}')
        if r["status"] not in ("ok", "exception"):
            problems.append(f"probe: seeded session should attempt execution: {r['status']}")

        # import honesty
        (root / "app" / "broken.py").write_text("import nope_not_a_module\n", encoding="utf-8")
        r = run_probe(root, "app/broken.py:x", "{}", "")
        if r["status"] != "import-error":
            problems.append(f"probe: broken import should report import-error: {r['status']}")

        # renderer smoke
        out = render_probe(probe("parse_user", "{}"))
        if "KeyError" not in out or "never ran" not in out:
            problems.append(f"render_probe missing failure framing: {out!r}")

        # ── Dc: JS/TS tier ──────────────────────────────────────────────────
        (root / "web").mkdir()
        (root / "web" / "app.mjs").write_text(_JS_FIXTURE_MJS, encoding="utf-8")
        (root / "web" / "pay.cjs").write_text(_JS_FIXTURE_CJS, encoding="utf-8")
        cat2 = scan_project(root)
        jsby = {f["qualname"]: f for f in cat2["functions"]
                if f.get("scanner") == "js-heuristic"}
        if set(jsby) != {"parseUser", "geocode", "safeFetch", "slug", "charge"}:
            problems.append(f"js catalog wrong: {sorted(jsby)}")
        else:
            def jr(fn):
                return {h["rule"] for h in jsby[fn]["friction"]}
            if "boundary" not in jsby["geocode"]["badges"]:
                problems.append("js: geocode should be boundary (fetch)")
            if "inbound" not in jsby["parseUser"]["badges"]:
                problems.append("js: parseUser should be inbound")
            if not {"F1", "F2", "F5", "F7"} <= jr("geocode"):
                problems.append(f"js geocode rules wrong: {jr('geocode')}")
            cm = jr("charge")
            if not {"F3", "F4", "F6", "F8"} <= cm or "F5" in cm:
                problems.append(f"js charge rules wrong (F5 must be absent — has timeout): {cm}")
            sfr = jr("safeFetch")
            if "F2" in sfr or "F5" in sfr:
                problems.append(f"js safeFetch false positives (ok+signal present): {sfr}")
            if jr("slug"):
                problems.append(f"js slug should be clean: {jr('slug')}")
            if not all(h["note"].endswith("[heuristic]") for f in jsby.values()
                       for h in f["friction"]):
                problems.append("js: every heuristic finding must be labeled [heuristic]")
        html2 = render_html(cat2, show_all=True)
        if "js-heuristic scanner" not in html2:
            problems.append("html: js cards must carry the heuristic label")

        # node probes (real execution) — skipped with a STATED note if node absent
        if shutil.which("node"):
            r = run_probe(root, "web/app.mjs:parseUser", '{"id": "7", "handle": "@ada"}', "")
            if r["status"] != "ok" or "'ada'" not in str(r.get("return")):
                problems.append(f"js probe: valid parseUser wrong: {r.get('status')}/{r.get('return')}")
            r = run_probe(root, "web/app.mjs:parseUser", "{}", "")
            e = r.get("error") or {}
            if r["status"] != "exception" or e.get("type") != "TypeError" \
                    or e.get("line") != 3 or "replace" not in (e.get("source") or ""):
                problems.append(f"js probe: empty user should TypeError at the .replace line: {e}")
            r = run_probe(root, "web/app.mjs:geocode", '{"addr": "x"}', '{"results": []}')
            e = r.get("error") or {}
            if r["status"] != "exception" or e.get("type") != "TypeError":
                problems.append(f"js probe: empty results should TypeError: {e}")
            if not any(c["lib"] == "fetch" for c in r.get("boundary_calls") or []):
                problems.append("js probe: fetch not intercepted/recorded")
            r = run_probe(root, "web/app.mjs:geocode", '{"addr": "x"}',
                          '{"results": [{"lat": 1, "lng": 2}]}')
            if r["status"] != "ok" or "1" not in str(r.get("return")):
                problems.append(f"js probe: normal response wrong: {r.get('return')}")
            r = run_probe(root, "web/pay.cjs:charge", '{"total": 19.995, "currency": "USD"}', '{"id": "ch_1"}')
            if r["status"] != "ok" or "2000" not in str(r.get("return")):
                problems.append(f"js probe: cjs charge wrong (Math.round(1999.5)=2000): {r}")
            if not any(c["lib"] == "axios" for c in r.get("boundary_calls") or []):
                problems.append("js probe: axios require-hook stub not intercepted")
        else:
            node_note = "node ABSENT — JS probe cases SKIPPED (stated, not silent)"

        # ── Db: --replay round-trip + drift teeth ───────────────────────────
        probes_dir = root / "_workflow" / "probes"
        probes_dir.mkdir(parents=True)
        for name, inp in (("ok", '{"id": "7", "handle": "@a"}'), ("boom", "{}")):
            res = run_probe(root, "app/svc.py:parse_user", inp, "")
            (probes_dir / f"parse_user-{name}.json").write_text(json.dumps(
                {"probe": "app/svc.py:parse_user", "input": inp, "response": "",
                 "result": res}), encoding="utf-8")
        code, rep = replay_probes(root)
        if code != 0 or not all(l.startswith("PASS") for l in rep):
            problems.append(f"replay: fresh saved probes should all PASS: {rep}")
        tampered = _read_json(probes_dir / "parse_user-boom.json")
        tampered["result"]["status"] = "ok"
        (probes_dir / "parse_user-boom.json").write_text(json.dumps(tampered), encoding="utf-8")
        code, rep = replay_probes(root)
        if code != 1 or not any(l.startswith("DRIFT") for l in rep):
            problems.append(f"replay: tampered expectation must DRIFT with exit 1: {rep}")

        # ── Db: --serve round-trip against a real local server ─────────────
        import http.client
        import threading
        import http.server as _hs

        cat3 = scan_project(root)
        app_html = serve_app_html(cat3)
        for needle in ("parse_user", "TRY IT OUT", "/probe", "network blocked"):
            if needle not in app_html:
                problems.append(f"serve html missing {needle!r}")

        class _H(_hs.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                req = json.loads(self.rfile.read(length))
                res = run_probe(root, req["spec"], req["input"], req.get("response") or "")
                body = json.dumps(res).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = _hs.ThreadingHTTPServer(("127.0.0.1", 0), _H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
            payload = json.dumps({"spec": "app/svc.py:parse_user", "input": "{}"})
            conn.request("POST", "/probe", body=payload,
                         headers={"Content-Type": "application/json"})
            resp = json.loads(conn.getresponse().read())
            if resp.get("status") != "exception" or (resp.get("error") or {}).get("type") != "KeyError":
                problems.append(f"serve: POST /probe round-trip wrong: {resp.get('error')}")
        finally:
            srv.shutdown()

    if problems:
        print("wf describe selftest: FAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print(
        "wf describe selftest: PASS "
        "(catalog: 6 fixture functions, badges boundary/inbound/fixture/plain; "
        "rules F1-F8 each proven with a positive AND a guarded negative; schema "
        "kinds field/json/fixture; HTML snapshot; probes are REAL subprocess "
        "execution: valid input traced with intermediate values, empty user "
        "KeyErrors at the exact line, null handle AttributeErrors on .replace "
        "with later lines never-ran, response-side probe passes on a normal "
        "shape and IndexErrors on empty results, boundary calls intercepted "
        "and recorded, missing env KeyErrors live, live db session refused "
        "needs-fixture unless the sample provides it, import failure reported "
        "honestly. Dc js-heuristic: 5 fixture functions with per-rule positives+"
        "negatives all labeled [heuristic]; node worker: fetch stubbed globally, "
        "axios stubbed via require-hook, red line from the real stack, ESM+CJS "
        f"both probed — {node_note}. Db: --replay passes fresh saved probes and "
        "DRIFTs with exit 1 on a tampered expectation; --serve app HTML carries "
        "the catalog and a REAL local POST /probe round-trip returns the exact "
        "KeyError)"
    )
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────


def _caller_dir(arg_dir: str | None) -> Path:
    if arg_dir:
        return Path(arg_dir).expanduser().resolve()
    env = os.environ.get("WF_CALLER_CWD")
    return Path(env).resolve() if env else Path.cwd().resolve()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="wf describe",
        description="Function swagger: catalog + friction rules + probe engine (Da).")
    ap.add_argument("--dir", help="project directory (default: caller dir)")
    ap.add_argument("--json", action="store_true", help="machine view")
    ap.add_argument("--out", help="HTML output path (default <dir>/_workflow/describe.html)")
    ap.add_argument("--all", action="store_true", help="include friction-free functions in the HTML")
    ap.add_argument("--probe", metavar="FILE:FUNC", help="execute one function against --input")
    ap.add_argument("--input", default="", help="probe input JSON")
    ap.add_argument("--response", default="", help="JSON the stubbed boundary returns")
    ap.add_argument("--save", action="store_true", help="save the probe under _workflow/probes/")
    ap.add_argument("--serve", action="store_true",
                    help="live two-pane UI on 127.0.0.1 (Execute runs project code)")
    ap.add_argument("--port", type=int, default=8787, help="--serve port (default 8787)")
    ap.add_argument("--replay", action="store_true",
                    help="re-run every saved probe under _workflow/probes/ and fail on drift")
    ap.add_argument("--selftest", action="store_true")
    # hidden worker plumbing
    ap.add_argument("--_probe-worker", dest="worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--file", help=argparse.SUPPRESS)
    ap.add_argument("--func", help=argparse.SUPPRESS)
    ap.add_argument("--root", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.worker:
        return _probe_worker(args.file, args.func, args.input, args.response, args.root)
    if args.selftest:
        return selftest()

    root = _caller_dir(args.dir)
    if not root.is_dir():
        _die(f"not a directory: {root}")

    if args.serve:
        return serve(root, args.port)
    if args.replay:
        code, lines = replay_probes(root)
        for l in lines:
            print(l)
        print(f"wf describe --replay: {'OK' if code == 0 else 'DRIFT DETECTED'}")
        return code

    if args.probe:
        res = run_probe(root, args.probe, args.input, args.response)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"probe {args.probe} · input {args.input or '{}'}")
            print(render_probe(res))
        if args.save:
            dest = root / "_workflow" / "probes" / (args.probe.split(":", 1)[1] + ".json")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps({"probe": args.probe, "input": args.input,
                                        "response": args.response, "result": res},
                                       indent=2) + "\n", encoding="utf-8")
            print(f"saved: {dest.relative_to(root)}")
        return 0 if res.get("status") in ("ok", "exception") else 1

    cat = scan_project(root)
    if args.json:
        print(json.dumps(cat, indent=2))
        return 0
    out = Path(args.out) if args.out else root / "_workflow" / "describe.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(cat, show_all=args.all), encoding="utf-8")
    s = cat["summary"]
    print(f"wf describe: {s['functions']} functions scanned · "
          f"{s['friction_functions']} friction-bearing · {s['friction_points']} friction points "
          f"({', '.join(f'{v} {k}' for k, v in sorted(s['by_severity'].items())) or 'none'})")
    for e in cat["errors"]:
        print(f"  note: {e}")
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
