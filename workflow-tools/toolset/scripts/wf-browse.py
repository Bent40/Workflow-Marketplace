#!/usr/bin/env python3
"""wf-browse.py — a real-browser executor that gives the agent "eyes" (inspired
by gstack's /browse). It drives a REAL Chromium via Playwright-Python: navigate,
screenshot, dump the accessibility tree, and run scripted end-to-end flows.

WHY THIS EXISTS: this repo's `core/rules/dod.real_browser_e2e_for_ui.yaml`
MANDATES at least one real-browser end-to-end happy path for any meaningful
browser UI — fake-DOM/unit tests are not enough. `wf browse run <steps>` is the
executor that satisfies that gate; the other subcommands give the agent the
ability to look at, audit, and screenshot a live page.

RIGHT-SIZED V1 (NOT gstack's Bun daemon/HTTP server): a single Playwright process
per invocation, launching a Chromium `launch_persistent_context` with a
user-data-dir under `.wf/browse/profile/` so cookies/login survive across calls.
No long-lived daemon; cross-call PAGE state (a live DOM between two separate CLI
calls) is deferred — a scripted flow that needs multi-step state runs as ONE
`wf browse run`. (`.wf/` is gitignored, so browser state is never committed.)

LAZY IMPORT (load-bearing): this tool MUST import and run with Playwright ABSENT.
`playwright` is NEVER imported at module top level — only inside the functions
that actually drive a browser, behind `_load_playwright()`. So `status`,
`--selftest`, the steps-file parser, the @ref map, and `wf doctor`'s check all
work in a browser-less container; only `shot`/`snapshot`/`run` need the browser,
and they FAIL CLOSED (one-line reason + "run `wf browse setup`", non-zero exit,
NO traceback) when it is absent.

Subcommands:
  status            report whether playwright (python pkg) + chromium are present;
                    never crash if absent. Exit 0 always (it is a report).
  setup             `pip install playwright` (if the import is missing) then
                    `python -m playwright install chromium`; idempotent (detects
                    already-present and skips); fail-closed with the manual
                    commands if the network/proxy blocks it. Prints what it did.
  shot <url> <out.png> [--full-page]
                    launch headless, goto, screenshot, close. Exit 0 on success.
  snapshot <url> [--json]
                    dump the accessibility tree (role + accessible name) as a
                    readable outline AND assign stable short @ref ids to
                    interactive nodes (button/link/input/...), persisting a
                    ref->locator map to `.wf/browse/refs.json` for the next call.
  run <steps-file>  execute a scripted flow (YAML or JSON list) in ONE process and
                    emit a structured per-step PASS/FAIL result. A failed
                    assert/step -> non-zero exit naming the failing step. THIS is
                    the real-browser E2E happy-path runner (dod.real_browser_e2e_for_ui).

Step kinds (in a flow file):
  goto <url>                 navigate
  click  (one of: ref/text/selector)   click a @ref (from the last snapshot), by
                             visible text, or by CSS selector
  fill   (selector|ref) + value        type into an input
  wait_for (selector|text)             wait until a selector / text appears
  screenshot <path>          capture a PNG
  assert_text <substring>    fail unless the page body contains the substring
  assert_title <substring>   fail unless the document title contains the substring
  assert_no_console_errors [ignore: [..substrings..]]
                             fail if any console error was logged so far in the
                             flow (analytics/favicon noise can be ignored)
  assert_no_failed_requests [ignore: [..substrings..]]
                             fail if any request failed or returned >= 400 so far
  dblclick / hover (ref/text/selector) double-click / hover (hover menus)
  press <key> [selector|ref]           keyboard key (Enter, Tab, Escape, ArrowDown,
                             Control+A...) on the page or a focused field
  select (selector|ref) + option       pick a <select> option by value or label
  set_viewport width + height          resize (e.g. 375x667 for a phone)
  set_offline true|false     drop / restore the network mid-flow
  reload / back              reload the page / browser back button
  snapshot [path]            re-mint @refs for the CURRENT page mid-flow (and
                             optionally write its outline to path)
  assert_a11y [fail_on: [critical,serious]] [ignore: [rule-ids]] [tags: [wcag2aa]]
                             inject axe-core and FAIL on accessibility violations
                             at the given impact levels (FAILS CLOSED if axe can't
                             load — a silently-skipped a11y gate is a fake-green)
                             ($WF_BROWSE_AXE_SRC=<path to axe.min.js> loads axe
                             from a local file when the CDN is blocked)

A step is a mapping; `kind:` (or the bare first key) names it. Examples:
  - goto: https://example.com
  - assert_text: Example Domain
  - { kind: click, ref: "@e3" }
  - { kind: fill, selector: "#user", value: alice }

Exit codes: 0 = success; 2 = usage / fail-closed (no browser, bad steps file);
            1 = a browse/flow step or assertion FAILED. selftest -> 0 pass / 1 fail.

Usage:
    wf browse status
    wf browse setup
    wf browse shot <url> <out.png> [--full-page]
    wf browse snapshot <url> [--json]
    wf browse run <steps-file>
    wf browse effort <steps-file> [--baseline <steps-file>]
    wf browse --profile <name> run <steps-file>   # isolated profile + refs
    wf browse --selftest        # BROWSER-FREE: routing + fail-closed + parser + ref map
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Runtime browser state lives under the gitignored .wf/ tree; the dir is
# overridable for tests via $WF_BROWSE_DIR so the selftest never touches the real
# profile/refs.
# In a plugin install (WF_PROJECT_MODE=1) the toolset dir is a read-only cache,
# so browser state lives in the caller's project instead.
DEFAULT_BROWSE_DIR = (Path.cwd() if os.environ.get("WF_PROJECT_MODE") == "1"
                      else REPO_ROOT) / ".wf" / "browse"

# Interactive accessibility roles we mint @ref ids for (snapshot + click-by-ref).
INTERACTIVE_ROLES = (
    "button", "link", "textbox", "checkbox", "radio", "combobox",
    "searchbox", "menuitem", "tab", "switch", "slider", "spinbutton",
)

# The single fail-closed message every browser command prints when Chromium /
# Playwright is unavailable. One line, no traceback, points at `setup`.
SETUP_HINT = "run `wf browse setup` to install Playwright + Chromium"


def _browse_dir() -> Path:
    env = os.environ.get("WF_BROWSE_DIR")
    return Path(env) if env else DEFAULT_BROWSE_DIR


# Named profiles isolate concurrent runs (e.g. two persona testers driving the
# same app at once): each gets its own Chromium user-data-dir AND its own @ref
# map, so they never collide on Chromium's profile lock or overwrite each other's
# refs. Selected by `--profile NAME` (or $WF_BROWSE_PROFILE); unset keeps the
# original single shared profile layout.
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _profile_name() -> str | None:
    name = os.environ.get("WF_BROWSE_PROFILE") or None
    if name is not None and not _PROFILE_NAME_RE.match(name):
        _die(f"invalid profile name {name!r} (use letters, digits, - or _)")
    return name


def _state_dir() -> Path:
    name = _profile_name()
    return _browse_dir() / "profiles" / name if name else _browse_dir()


def _refs_path() -> Path:
    return _state_dir() / "refs.json"


def _profile_dir() -> Path:
    return _state_dir() / "profile"


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf browse: {msg}\n")
    raise SystemExit(code)


# --- browser availability (the lazy seam) -------------------------------------

class BrowserUnavailable(Exception):
    """Raised when Playwright (the package) or Chromium (the browser binary) is
    not installed. Carries a one-line, traceback-free reason and the setup hint."""


def _playwright_module():
    """Import playwright lazily. Returns the module or raises BrowserUnavailable.

    NEVER called at import time — only from inside a browser-driving function —
    so this whole tool loads and self-tests with playwright absent."""
    try:
        import playwright  # noqa: F401  (presence probe)
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except Exception as e:  # ImportError, or a broken partial install
        raise BrowserUnavailable(
            f"Playwright Python package is not installed ({e.__class__.__name__})"
        )


def _playwright_pkg_present() -> bool:
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False


def _chromium_executable_path() -> str | None:
    """The full-Chromium executable path Playwright would launch, WITHOUT
    launching it (and without importing playwright if the package is absent).
    Returns None if the package is absent or the probe fails."""
    if not _playwright_pkg_present():
        return None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
        return path or None
    except Exception:
        return None


def _chromium_present() -> bool:
    """Best-effort probe for an installed full Chromium browser binary, WITHOUT
    launching it (and without importing playwright if the package is absent)."""
    path = _chromium_executable_path()
    return bool(path) and Path(path).exists()


def _derive_install_layout(exe_path: str | None = None):
    """Derive (ROOT, REV) and the headless-shell path from the full-Chromium
    executable path. The install layout is:

        <ROOT>/chromium-<REV>/chrome-linux64/chrome                     (full)
        <ROOT>/chromium_headless_shell-<REV>/chrome-headless-shell-linux64/chrome-headless-shell

    `executable_path` == `<ROOT>/chromium-<REV>/chrome-linux64/chrome`, so ROOT is
    its parent's parent's parent and REV is the number in the `chromium-<REV>`
    dir. Returns (root: Path|None, rev: str|None, headless_shell: Path|None) —
    all None if the path can't be parsed (so callers fail closed, never crash)."""
    if exe_path is None:
        exe_path = _chromium_executable_path()
    if not exe_path:
        return None, None, None
    try:
        exe = Path(exe_path)
        chromium_dir = exe.parent.parent          # <ROOT>/chromium-<REV>
        root = chromium_dir.parent                 # <ROOT>
        m = re.match(r"chromium-(\d+)$", chromium_dir.name)
        rev = m.group(1) if m else None
        if rev is None:
            return root, None, None
        shell_dir = root / f"chromium_headless_shell-{rev}"
        # Two on-disk layouts exist: the current CfT one and the older
        # `chrome-linux/headless_shell` one (still shipped in some prebuilt
        # images, e.g. cloud containers with /opt/pw-browsers). Prefer whichever
        # exists; default to the CfT path so a missing install still fails closed.
        candidates = (shell_dir / "chrome-headless-shell-linux64" / "chrome-headless-shell",
                      shell_dir / "chrome-linux" / "headless_shell")
        headless = next((c for c in candidates if c.exists()), candidates[0])
        return root, rev, headless
    except Exception:
        return None, None, None


def _headless_shell_present() -> bool:
    """Probe for the separate `chrome-headless-shell` binary. This tool launches
    `headless=True`, which uses Playwright's headless-shell binary rather than the
    full Chromium — so readiness MUST require this too, or status falsely reports
    'ready' while every headless launch fails."""
    _root, _rev, headless = _derive_install_layout()
    return bool(headless) and headless.exists()


def _require_browser() -> None:
    """Fail closed (BrowserUnavailable) unless the package AND both the full
    Chromium binary AND the headless-shell binary are present (we launch headless,
    so headless-shell is load-bearing). Callers convert this into exit 2 + hint."""
    if not _playwright_pkg_present():
        raise BrowserUnavailable("Playwright Python package is not installed")
    if not _chromium_present():
        raise BrowserUnavailable("Chromium browser binary is not installed")
    if not _headless_shell_present():
        raise BrowserUnavailable(
            "Chromium headless-shell binary is not installed (required for headless launch)"
        )


# --- accessibility-tree capture via CDP (Playwright >=1.55 removed page.accessibility) --

# Roles the old `page.accessibility.snapshot()` folded into a parent's accessible
# name — structural wrappers and pure text leaves that add no actionable identity
# to the outline. We collapse them (hoisting any children) UNLESS the subtree
# carries an interactive node we must keep a path to.
_AX_NOISE_ROLES = {"statictext", "inlinetextbox", "linebreak", "none", "generic", ""}


def _ax_value(field):
    """A CDP AX property value is `{"type":..., "value":...}` (or None). Old
    `page.accessibility.snapshot()` exposed the bare `.value`; mirror that."""
    if isinstance(field, dict):
        return field.get("value")
    return field


def cdp_axtree_to_nested(nodes: list) -> dict:
    """Convert a flat CDP `Accessibility.getFullAXTree` node list into the SAME
    nested `{"role":..., "name":..., "children":[...]}` dict that the removed
    `page.accessibility.snapshot()` returned — so flatten_axtree/write_refs/
    _resolve_click stay UNCHANGED.

    Each CDP node has `nodeId`, `role.value`, `name.value` (or `name` None), and
    `childIds`. We root at the node that is no one's child (the RootWebArea),
    recurse, and skip ignored / structural / text-noise nodes the way the old AX
    snapshot did — hoisting a skipped node's children so the outline stays clean
    but no interactive descendant is ever lost."""
    by_id: dict[str, dict] = {}
    for n in nodes:
        nid = n.get("nodeId")
        if nid is not None:
            by_id[str(nid)] = n
    child_ids: set[str] = set()
    for n in nodes:
        for c in (n.get("childIds") or []):
            child_ids.add(str(c))
    roots = [n for n in nodes if str(n.get("nodeId")) not in child_ids]

    def role_of(n: dict) -> str:
        return str(_ax_value(n.get("role")) or "")

    def name_of(n: dict) -> str:
        return str(_ax_value(n.get("name")) or "")

    def subtree_has_interactive(nid, _seen: set | None = None) -> bool:
        if _seen is None:
            _seen = set()
        sid = str(nid)
        if sid in _seen:
            return False
        _seen.add(sid)
        n = by_id.get(sid)
        if n is None:
            return False
        if role_of(n).lower() in (r.lower() for r in INTERACTIVE_ROLES):
            return True
        return any(subtree_has_interactive(c, _seen) for c in (n.get("childIds") or []))

    def is_meaningful(n: dict) -> bool:
        if n.get("ignored"):
            return False
        r = role_of(n).lower()
        # Keep every node with a real role; collapse structural/text noise unless
        # it is the only path to an interactive descendant.
        if r in _AX_NOISE_ROLES:
            return subtree_has_interactive(n.get("nodeId"))
        return True

    def build(nid, is_root: bool = False) -> list:
        n = by_id.get(str(nid))
        if n is None:
            return []
        children_nested: list = []
        for c in (n.get("childIds") or []):
            children_nested.extend(build(c))
        if is_root or is_meaningful(n):
            return [{"role": role_of(n), "name": name_of(n), "children": children_nested}]
        return children_nested  # collapse: hoist children to the parent

    if not roots:
        return {}
    built = build(roots[0].get("nodeId"), is_root=True)
    return built[0] if built else {}


def _capture_axtree(page) -> dict:
    """Capture the page's accessibility tree as a nested {role,name,children}
    dict using the Chrome DevTools Protocol (Playwright >=1.55 removed the
    `page.accessibility` API this tool used to call)."""
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send("Accessibility.enable")
        nodes = cdp.send("Accessibility.getFullAXTree").get("nodes", [])
    finally:
        try:
            cdp.detach()
        except Exception:
            pass
    return cdp_axtree_to_nested(nodes)


# --- accessibility-tree flattening + @ref minting (pure, browser-free) --------

def flatten_axtree(node: dict, *, _depth: int = 0, _acc: list | None = None,
                   _counter: list | None = None, _refs: dict | None = None) -> tuple[list, dict]:
    """Flatten a Playwright accessibility-tree dict into (outline_rows, ref_map).

    Pure function over a plain dict — no browser needed — so the selftest can
    exercise the exact production logic on injected data. Each interactive node
    (role in INTERACTIVE_ROLES) gets a stable short id `@eN`; the ref_map maps
    that id to a locator spec the next call can act on (role+name).

    Returns:
      outline_rows: list of (indent, ref_or_None, role, name) tuples.
      ref_map:      { "@eN": {"role": ..., "name": ...} }.
    """
    if _acc is None:
        _acc, _counter, _refs = [], [0], {}
    role = str(node.get("role", "") or "")
    name = str(node.get("name", "") or "")
    ref = None
    if role in INTERACTIVE_ROLES:
        _counter[0] += 1
        ref = f"@e{_counter[0]}"
        _refs[ref] = {"role": role, "name": name}
    # Skip the synthetic root "WebArea"/"RootWebArea" wrapper from the outline but
    # still recurse into its children at the same depth.
    is_root_wrapper = _depth == 0 and role.lower() in ("webarea", "rootwebarea", "")
    if not is_root_wrapper:
        _acc.append((_depth, ref, role, name))
    child_depth = _depth if is_root_wrapper else _depth + 1
    for child in node.get("children", []) or []:
        flatten_axtree(child, _depth=child_depth, _acc=_acc, _counter=_counter, _refs=_refs)
    return _acc, _refs


def render_outline(rows: list) -> str:
    """Render flattened rows as a readable indented outline."""
    out = []
    for indent, ref, role, name in rows:
        pad = "  " * indent
        label = f'"{name}"' if name else "(no name)"
        tag = f" {ref}" if ref else ""
        out.append(f"{pad}- {role}: {label}{tag}")
    return "\n".join(out)


def write_refs(ref_map: dict) -> None:
    p = _refs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ref_map, ensure_ascii=False, indent=2, sort_keys=True))


def read_refs() -> dict:
    p = _refs_path()
    if not p.is_file():
        return {}
    try:
        obj = json.loads(p.read_text())
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


# --- steps-file parsing (pure, browser-free) ----------------------------------

STEP_KINDS = (
    "goto", "click", "fill", "wait_for", "screenshot", "assert_text", "assert_title",
    "assert_no_console_errors", "assert_no_failed_requests", "assert_a11y",
    # interaction + environment kinds (persona testers: keyboard-only users,
    # double-clickers, hover menus, small screens, flaky networks, back-button use)
    "dblclick", "hover", "press", "select", "set_viewport", "set_offline",
    "reload", "back", "snapshot",
)

# Steps a USER performs — the honest "effort" a flow costs. Navigation (goto) is
# counted separately (a typed URL is not an in-app click); waits, asserts,
# screenshots and environment changes are the harness, not the user.
EFFORT_ACTION_KINDS = ("click", "dblclick", "fill", "press", "select", "hover")

# axe-core source for the a11y gate (assert_a11y). Loaded into the page at run
# time via add_script_tag; offline this raises and the gate FAILS CLOSED.
AXE_CDN = "https://unpkg.com/axe-core@4/axe.min.js"
# Default WCAG conformance tags scanned, and the impact levels that FAIL the gate.
A11Y_DEFAULT_TAGS = ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa")
A11Y_DEFAULT_FAIL_IMPACTS = ("critical", "serious")


def parse_steps(text: str) -> list[dict]:
    """Parse a YAML or JSON list of steps into a normalized list of dicts.

    Each returned step is `{"kind": <one of STEP_KINDS>, ...args}`. Accepts two
    shapes per item:
      - shorthand single-key mapping: `{goto: <url>}` -> {kind: goto, value: <url>}
      - explicit mapping: `{kind: fill, selector: "#u", value: x}`

    Fails closed (raises ValueError) on: not-a-list, an item that is not a
    mapping, an unknown step kind, or a missing required argument. NEVER silently
    drops a malformed step."""
    text = (text or "").strip()
    if not text:
        raise ValueError("steps file is empty")
    data = None
    # Try JSON first (a strict subset), then YAML if available.
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        try:
            import yaml
            data = yaml.safe_load(text)
        except ImportError:
            raise ValueError(
                "steps file is not valid JSON and PyYAML is unavailable to parse YAML"
            )
        except Exception as e:
            raise ValueError(f"steps file is not valid YAML/JSON: {e}")
    if not isinstance(data, list):
        raise ValueError("steps file must be a top-level list of steps")
    steps: list[dict] = []
    for i, item in enumerate(data, 1):
        steps.append(_normalize_step(item, i))
    if not steps:
        raise ValueError("steps file contains no steps")
    return steps


def _normalize_step(item, idx: int) -> dict:
    # A bare string item names a NO-ARG step kind (e.g. "assert_no_console_errors").
    # A bare string naming an arg-taking kind (e.g. "goto") still fails closed in
    # _validate_step_args, so this only eases the genuinely arg-free assertions.
    if isinstance(item, str):
        kind = item.strip()
        step = {"kind": kind}
        if kind not in STEP_KINDS:
            raise ValueError(f"step {idx}: unknown step kind {kind!r} "
                             f"(known: {', '.join(STEP_KINDS)})")
        _validate_step_args(step, idx)
        return step
    if not isinstance(item, dict):
        raise ValueError(f"step {idx}: must be a mapping or a bare kind string, "
                         f"got {type(item).__name__}")
    item = dict(item)
    if "kind" in item:
        kind = str(item.pop("kind"))
        step = {"kind": kind, **item}
    else:
        # shorthand: a single-key mapping whose key is the step kind.
        keys = list(item.keys())
        if len(keys) != 1:
            raise ValueError(
                f"step {idx}: ambiguous step (expected a `kind:` field or a single "
                f"<kind>: <value> pair, got keys {keys})"
            )
        kind = str(keys[0])
        step = {"kind": kind, "value": item[keys[0]]}
    if kind not in STEP_KINDS:
        raise ValueError(f"step {idx}: unknown step kind {kind!r} "
                         f"(known: {', '.join(STEP_KINDS)})")
    _validate_step_args(step, idx)
    return step


def _validate_step_args(step: dict, idx: int) -> None:
    kind = step["kind"]
    if kind in ("goto", "assert_text", "assert_title"):
        if not (step.get("value") or step.get("url") or step.get("text")):
            raise ValueError(f"step {idx}: {kind} requires a value (url/text)")
    elif kind == "wait_for":
        if not (step.get("value") or step.get("selector") or step.get("text")):
            raise ValueError(f"step {idx}: wait_for requires a selector or text")
    elif kind == "screenshot":
        if not (step.get("value") or step.get("path")):
            raise ValueError(f"step {idx}: screenshot requires a path")
    elif kind in ("click", "dblclick", "hover"):
        if not (step.get("ref") or step.get("text") or step.get("selector")
                or step.get("value")):
            raise ValueError(f"step {idx}: {kind} requires one of ref/text/selector")
    elif kind == "press":
        if not (step.get("key") or step.get("value")):
            raise ValueError(f"step {idx}: press requires a key (e.g. Enter, Tab, Escape)")
    elif kind == "select":
        if not (step.get("selector") or step.get("ref")):
            raise ValueError(f"step {idx}: select requires a selector or @ref")
        if step.get("option") is None and step.get("value") is None:
            raise ValueError(f"step {idx}: select requires an option (value or label)")
    elif kind == "set_viewport":
        try:
            w, h = int(step.get("width")), int(step.get("height"))
        except (TypeError, ValueError):
            raise ValueError(f"step {idx}: set_viewport requires integer width and height")
        if w <= 0 or h <= 0:
            raise ValueError(f"step {idx}: set_viewport width/height must be positive")
    elif kind == "set_offline":
        if not isinstance(step.get("value"), bool):
            raise ValueError(f"step {idx}: set_offline requires true or false")
    elif kind == "snapshot":
        v = step.get("path") or step.get("value")
        if v is not None and not isinstance(v, str):
            raise ValueError(f"step {idx}: snapshot `path` must be a string")
    elif kind == "fill":
        target = step.get("selector") or step.get("ref")
        if not target:
            raise ValueError(f"step {idx}: fill requires a selector or @ref")
        if step.get("value") is None:
            raise ValueError(f"step {idx}: fill requires a value")
    elif kind in ("assert_no_console_errors", "assert_no_failed_requests"):
        # No required args. Optional `ignore`: a substring or list of substrings
        # to exclude (analytics/favicon noise) — validate its shape if present.
        ig = step.get("ignore")
        if ig is not None and not isinstance(ig, (list, str)):
            raise ValueError(f"step {idx}: {kind} `ignore` must be a string or "
                             f"list of strings")
    elif kind == "assert_a11y":
        # No required args. Optional fail_on / ignore / tags, each a string or list.
        for opt in ("fail_on", "ignore", "tags"):
            v = step.get(opt)
            if v is not None and not isinstance(v, (list, str)):
                raise ValueError(f"step {idx}: assert_a11y `{opt}` must be a string "
                                 f"or list of strings")


# --- per-step result serialization (pure, browser-free) -----------------------

def effort_summary(steps: list[dict]) -> dict:
    """Count what a flow costs its user: in-app actions (clicks, typing, keys,
    selects, hovers) and navigations. Pure and deterministic over the steps, so a
    before/after diff over the SAME frozen task flow is a measurement, not a
    persona's self-report."""
    by_kind = {k: 0 for k in EFFORT_ACTION_KINDS}
    for s in steps:
        if s.get("kind") in by_kind:
            by_kind[s["kind"]] += 1
    return {"actions": sum(by_kind.values()),
            "navigations": sum(1 for s in steps if s.get("kind") == "goto"),
            "by_kind": {k: v for k, v in by_kind.items() if v}}


def render_effort(e: dict) -> str:
    parts = ", ".join(f"{k} {v}" for k, v in e["by_kind"].items()) or "none"
    return f"effort: {e['actions']} action(s) ({parts}), {e['navigations']} navigation(s)"


def make_result(idx: int, kind: str, status: str, detail: str = "") -> dict:
    """Build one per-step result record. `status` is PASS or FAIL."""
    return {"step": idx, "kind": kind, "status": status, "detail": detail}


def render_results(results: list[dict]) -> str:
    lines = []
    for r in results:
        mark = "PASS" if r["status"] == "PASS" else "FAIL"
        d = f"  — {r['detail']}" if r.get("detail") else ""
        lines.append(f"  [{r['step']:>2}] {mark}  {r['kind']}{d}")
    passed = sum(1 for r in results if r["status"] == "PASS")
    lines.append(f"— {passed}/{len(results)} steps PASSED")
    return "\n".join(lines)


# --- verification-as-artifact: persist proof-of-work into a COMMITTED tree ----
# wf browse normally writes screenshots/state under the gitignored .wf/, so the
# evidence is ephemeral and a later reviewer re-trusts a pass/fail line. With
# --evidence-dir, the run's screenshots + a machine-readable results.json (the
# per-step PASS/FAIL + the run exit code) + a one-page walkthrough.md land in a
# committed tree, so the artifact is EARNED from exit codes, never a bare PNG.

def _redirect_screenshots(steps: list[dict], evidence_dir: Path) -> None:
    """Rewrite RELATIVE `screenshot` step paths to live under evidence_dir (so a
    run's visual evidence lands in the committed evidence tree). Absolute paths are
    left as the author set them. Mutates `steps` in place. Pure (no browser)."""
    for s in steps:
        if s.get("kind") != "screenshot":
            continue
        p = s.get("path") or s.get("value")
        if p and not Path(p).is_absolute():
            s["path"] = str(evidence_dir / p)
            s.pop("value", None)


def write_evidence(evidence_dir: Path, steps_file: str,
                   results: list[dict], rc: int, effort: dict | None = None) -> dict:
    """Persist a run's proof-of-work into evidence_dir: results.json (the machine
    signal — per-step PASS/FAIL + the run exit code, so the artifact is earned not
    asserted) and walkthrough.md (a one-page human summary: PASS/FAIL table,
    embedded screenshots, and the clean-page summaries carried in step details).
    Pure: takes an already-computed results list, NEVER drives a browser. Returns
    the manifest."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in results if r["status"] == "PASS")
    total = len(results)
    shots = sorted(p.name for p in evidence_dir.glob("*.png"))
    manifest = {
        "task": evidence_dir.name,
        "steps_file": steps_file,
        "exit_code": rc,
        "passed": passed,
        "total": total,
        "results": results,
        "screenshots": shots,
    }
    if effort is not None:
        manifest["effort"] = effort
    (evidence_dir / "results.json").write_text(json.dumps(manifest, indent=2) + "\n")
    lines = [f"# Browser verification — {evidence_dir.name}", "",
             f"**Result:** {'PASS' if rc == 0 else 'FAIL'} "
             f"({passed}/{total} steps) — exit {rc}",
             f"Flow: `{steps_file}`"]
    if effort is not None:
        lines.append(f"Effort: {render_effort(effort)}")
    lines += ["", "## Steps", "",
             "| # | step | status | detail |", "| --- | --- | --- | --- |"]
    for r in results:
        detail = (r.get("detail") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['step']} | {r['kind']} | {r['status']} | {detail} |")
    if shots:
        lines += ["", "## Screenshots", ""] + [f"![{n}]({n})" for n in shots]
    (evidence_dir / "walkthrough.md").write_text("\n".join(lines) + "\n")
    return manifest


# --- browser-driven commands (the only ones that need Playwright) -------------

def _resolve_click(page, refs: dict, step: dict):
    """Return a Playwright locator for a click step (by @ref, text, or selector)."""
    if step.get("selector"):
        return page.locator(step["selector"])
    if step.get("ref") or (isinstance(step.get("value"), str) and step["value"].startswith("@")):
        ref = step.get("ref") or step.get("value")
        spec = refs.get(ref)
        if not spec:
            raise ValueError(f"unknown @ref {ref!r} (run `wf browse snapshot` first)")
        return page.get_by_role(spec["role"], name=spec["name"]) if spec.get("name") \
            else page.get_by_role(spec["role"])
    text = step.get("text") or step.get("value")
    return page.get_by_text(text, exact=False)


def _resolve_field(page, refs: dict, target: str, default_role: str):
    """Locator for a form field addressed by @ref or CSS selector."""
    if target and target.startswith("@"):
        spec = refs.get(target) or {}
        role = spec.get("role", default_role)
        return page.get_by_role(role, name=spec.get("name")) if spec.get("name") \
            else page.get_by_role(role)
    return page.locator(target)


def cmd_shot(url: str, out: str, full_page: bool) -> int:
    _require_browser()
    sync_playwright = _playwright_module()
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(_profile_dir()), headless=True)
        try:
            page = ctx.new_page()
            page.goto(url, wait_until="load")
            page.screenshot(path=str(out_path), full_page=full_page)
        finally:
            ctx.close()
    print(f"wf browse shot: wrote {out_path} ({'full page' if full_page else 'viewport'}) "
          f"from {url}")
    return 0


def cmd_snapshot(url: str, as_json: bool) -> int:
    _require_browser()
    sync_playwright = _playwright_module()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(_profile_dir()), headless=True)
        try:
            page = ctx.new_page()
            page.goto(url, wait_until="load")
            tree = _capture_axtree(page) or {}
        finally:
            ctx.close()
    rows, ref_map = flatten_axtree(tree)
    write_refs(ref_map)
    if as_json:
        print(json.dumps({"url": url, "outline": [
            {"depth": d, "ref": r, "role": role, "name": name}
            for (d, r, role, name) in rows
        ], "refs": ref_map}, ensure_ascii=False, indent=2))
    else:
        print(f"# accessibility snapshot: {url}")
        print(render_outline(rows))
        print(f"\n— {len(ref_map)} interactive node(s) given @refs "
              f"(saved to {_refs_path()})")
    return 0


def run_flow(steps: list[dict], *, browse_dir: Path | None = None) -> tuple[list[dict], int]:
    """Execute a parsed flow in ONE browser process. Returns (results, exit_code).

    exit_code: 0 all PASS; 1 a step/assertion FAILED. Requires a browser; the
    caller has already called _require_browser via the command wrapper."""
    sync_playwright = _playwright_module()
    refs = read_refs()
    results: list[dict] = []
    rc = 0
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(_profile_dir()), headless=True)
        try:
            page = ctx.new_page()
            # Accumulate runtime errors across the whole flow so an
            # assert_no_console_errors / assert_no_failed_requests step can check
            # everything that happened since the first goto.
            state = {"console_errors": [], "failed_requests": [], "ctx": ctx}

            def _on_console(msg):
                try:
                    if msg.type == "error":
                        state["console_errors"].append(msg.text)
                except Exception:
                    pass

            def _on_requestfailed(req):
                try:
                    fail = getattr(req, "failure", None)
                    state["failed_requests"].append(
                        f"{req.method} {req.url}" + (f" ({fail})" if fail else " (failed)"))
                except Exception:
                    pass

            def _on_response(resp):
                try:
                    if resp.status >= 400:
                        state["failed_requests"].append(f"{resp.status} {resp.url}")
                except Exception:
                    pass

            page.on("console", _on_console)
            page.on("requestfailed", _on_requestfailed)
            page.on("response", _on_response)
            for i, step in enumerate(steps, 1):
                kind = step["kind"]
                try:
                    detail = _exec_step(page, refs, step, state)
                    results.append(make_result(i, kind, "PASS", detail))
                except Exception as e:
                    results.append(make_result(i, kind, "FAIL", str(e)))
                    rc = 1
                    break  # stop at the first failure (happy-path runner)
        finally:
            ctx.close()
    return results, rc


# --- runtime-error assertion helpers (pure, browser-free) ---------------------
# These check accumulators that run_flow fills from page `console` / `requestfailed`
# / `response` events. Keeping the decision pure makes it testable without a
# browser (the file's seam philosophy) and lets a flow assert "no console errors /
# no failed XHRs on the happy path" — the class of 'looks fine, is broken'
# regression a screenshot/assert_text gate is blind to.

def _norm_ignore(ignore) -> list[str]:
    if ignore is None:
        return []
    return [ignore] if isinstance(ignore, str) else [str(x) for x in ignore]


def _console_error_summary(errors: list[str], ignore) -> tuple[bool, str]:
    """(ok, detail) for assert_no_console_errors. ok=True iff no non-ignored
    console error was seen."""
    ign = _norm_ignore(ignore)
    kept = [e for e in errors if not any(g in e for g in ign)]
    if kept:
        return False, (f"{len(kept)} console error(s) on the page: "
                       + " | ".join(kept[:3]))
    seen = len(errors)
    return True, f"no console errors (saw {seen}, {seen - len(kept)} ignored)"


def _failed_request_summary(failures: list[str], ignore) -> tuple[bool, str]:
    """(ok, detail) for assert_no_failed_requests. ok=True iff no non-ignored
    failed/>=400 request was seen."""
    ign = _norm_ignore(ignore)
    kept = [f for f in failures if not any(g in f for g in ign)]
    if kept:
        return False, (f"{len(kept)} failed request(s): " + " | ".join(kept[:3]))
    seen = len(failures)
    return True, f"no failed requests (saw {seen}, {seen - len(kept)} ignored)"


def _axe_summary(violations: list, fail_on, ignore) -> tuple[bool, str]:
    """(ok, detail) for assert_a11y over axe-core's `violations` list. ok=True iff
    no violation at the failing impact levels (default critical+serious) remains
    after dropping ignored rule ids. Pure — exercised browser-free in the selftest.
    HONESTLY scoped: automation catches ~30-57% of WCAG issues; the rest needs
    human judgement (dod.accessibility_gate keeps the manual checklist)."""
    fi = set(_norm_ignore(fail_on)) or set(A11Y_DEFAULT_FAIL_IMPACTS)
    ign = set(_norm_ignore(ignore))
    bad = [v for v in violations
           if isinstance(v, dict) and v.get("impact") in fi and v.get("id") not in ign]
    if bad:
        items = [f"{v.get('id')}({v.get('impact')}, {len(v.get('nodes', []))} node(s))"
                 for v in bad]
        return False, (f"{len(bad)} a11y violation(s) at {sorted(fi)}: "
                       + " | ".join(items[:4]))
    return True, f"no {sorted(fi)} a11y violations ({len(violations)} rule(s) flagged total)"


def _exec_step(page, refs: dict, step: dict, state: dict | None = None) -> str:
    kind = step["kind"]
    state = state or {"console_errors": [], "failed_requests": []}
    if kind == "goto":
        url = step.get("value") or step.get("url")
        page.goto(url, wait_until="load")
        return f"-> {url}"
    if kind == "click":
        loc = _resolve_click(page, refs, step)
        loc.first.click(timeout=10000)
        return "clicked"
    if kind == "dblclick":
        _resolve_click(page, refs, step).first.dblclick(timeout=10000)
        return "double-clicked"
    if kind == "hover":
        _resolve_click(page, refs, step).first.hover(timeout=10000)
        return "hovered"
    if kind == "press":
        key = step.get("key") or step.get("value")
        target = step.get("selector") or step.get("ref")
        if target:
            _resolve_field(page, refs, target, "textbox").first.press(key, timeout=10000)
            return f"pressed {key!r} in {target!r}"
        page.keyboard.press(key)
        return f"pressed {key!r}"
    if kind == "select":
        target = step.get("selector") or step.get("ref")
        option = step.get("option") if step.get("option") is not None else step.get("value")
        loc = _resolve_field(page, refs, target, "combobox").first
        try:
            loc.select_option(str(option), timeout=10000)
        except Exception:
            loc.select_option(label=str(option), timeout=10000)
        return f"selected {option!r} in {target!r}"
    if kind == "set_viewport":
        w, h = int(step["width"]), int(step["height"])
        page.set_viewport_size({"width": w, "height": h})
        return f"viewport {w}x{h}"
    if kind == "set_offline":
        ctx = state.get("ctx")
        if ctx is None:
            raise RuntimeError("set_offline needs the browser context (run inside `wf browse run`)")
        ctx.set_offline(bool(step["value"]))
        return "offline" if step["value"] else "online"
    if kind == "reload":
        page.reload(wait_until="load")
        return "reloaded"
    if kind == "back":
        if page.go_back(wait_until="load") is None:
            raise AssertionError("no previous page in history to go back to")
        return f"back -> {page.url}"
    if kind == "snapshot":
        rows, ref_map = flatten_axtree(_capture_axtree(page) or {})
        # Re-mint @refs for the CURRENT page so later steps (and the next run's
        # first steps) can target what is on screen now, mid-flow.
        refs.clear()
        refs.update(ref_map)
        write_refs(ref_map)
        out = step.get("path") or step.get("value")
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(f"# accessibility snapshot: {page.url}\n"
                                 + render_outline(rows) + "\n")
        return f"{len(ref_map)} @ref(s) on {page.url}" + (f" -> {out}" if out else "")
    if kind == "fill":
        target = step.get("selector") or step.get("ref")
        value = step.get("value", "")
        _resolve_field(page, refs, target, "textbox").first.fill(value, timeout=10000)
        return f"filled {target!r}"
    if kind == "wait_for":
        sel = step.get("selector") or step.get("value")
        if step.get("text") or (sel and not _looks_like_selector(sel)):
            txt = step.get("text") or sel
            page.get_by_text(txt, exact=False).first.wait_for(timeout=10000)
            return f"saw text {txt!r}"
        page.wait_for_selector(sel, timeout=10000)
        return f"saw selector {sel!r}"
    if kind == "screenshot":
        path = step.get("path") or step.get("value")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=path, full_page=bool(step.get("full_page")))
        return f"-> {path}"
    if kind == "assert_text":
        needle = step.get("value") or step.get("text")
        body = page.content()
        if needle not in body and needle not in (page.inner_text("body") or ""):
            raise AssertionError(f"text {needle!r} not found on page")
        return f"found {needle!r}"
    if kind == "assert_title":
        needle = step.get("value") or step.get("text")
        title = page.title()
        if needle not in title:
            raise AssertionError(f"title {title!r} does not contain {needle!r}")
        return f"title contains {needle!r}"
    if kind == "assert_no_console_errors":
        ok, detail = _console_error_summary(state["console_errors"], step.get("ignore"))
        if not ok:
            raise AssertionError(detail)
        return detail
    if kind == "assert_no_failed_requests":
        ok, detail = _failed_request_summary(state["failed_requests"], step.get("ignore"))
        if not ok:
            raise AssertionError(detail)
        return detail
    if kind == "assert_a11y":
        tags = _norm_ignore(step.get("tags")) or list(A11Y_DEFAULT_TAGS)
        # Inject axe-core and run it scoped to the WCAG tag set. FAIL CLOSED: if axe
        # cannot be loaded/run (offline, CDN blocked), the gate FAILS — a silently
        # skipped a11y check is a fake-green.
        try:
            # $WF_BROWSE_AXE_SRC: a local axe.min.js (e.g. from `npm i axe-core`)
            # for boxes whose egress blocks the CDN. Still fails closed if bad.
            local_axe = os.environ.get("WF_BROWSE_AXE_SRC")
            if local_axe:
                page.add_script_tag(path=local_axe)
            else:
                page.add_script_tag(url=AXE_CDN)
            violations = page.evaluate(
                """(tags) => axe.run(document, tags && tags.length
                       ? { runOnly: { type: 'tag', values: tags } } : {})
                     .then(r => r.violations)""",
                tags)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"a11y gate FAILS CLOSED: could not load/run axe-core ({e.__class__.__name__}: {e}); "
                f"ensure network/CDN access (or pre-cache axe) — never skip the gate")
        ok, detail = _axe_summary(violations or [], step.get("fail_on"), step.get("ignore"))
        if not ok:
            raise AssertionError(detail)
        return detail
    raise ValueError(f"unhandled step kind {kind!r}")  # unreachable (validated)


def _looks_like_selector(s: str) -> bool:
    """Heuristic: treat #id, .class, [attr], tag>child, etc. as CSS selectors."""
    s = s.strip()
    return bool(s) and (s[0] in "#.[" or ">" in s or s.startswith("//")
                        or any(c in s for c in "[]"))


def cmd_run(steps_file: str, evidence_dir: str | None = None) -> int:
    path = Path(steps_file)
    if not path.is_file():
        _die(f"steps file not found: {steps_file}")
    try:
        steps = parse_steps(path.read_text())
    except ValueError as e:
        _die(f"bad steps file {steps_file}: {e}")
    ev: Path | None = None
    if evidence_dir:
        ev = Path(evidence_dir)
        try:
            if ev.resolve().is_relative_to(DEFAULT_BROWSE_DIR.parent.resolve()):
                print(f"wf browse run: WARNING — evidence-dir {ev} is under the "
                      f"gitignored .wf/; evidence there will NOT be committed "
                      f"(use e.g. _workflow/evidence/<task>/ instead).")
        except (OSError, ValueError):  # pragma: no cover - resolve edge cases
            pass
        _redirect_screenshots(steps, ev)
    # Parse-then-require: a malformed flow fails closed (exit 2) BEFORE we ever
    # need a browser, so a CI without Chromium still catches a broken flow file.
    try:
        _require_browser()
    except BrowserUnavailable as e:
        _die(f"{e} — {SETUP_HINT}")
    print(f"wf browse run: {len(steps)} step(s) from {steps_file}")
    results, rc = run_flow(steps)
    print(render_results(results))
    effort = effort_summary(steps)
    print(f"wf browse run: {render_effort(effort)}")
    if rc != 0:
        failed = next((r for r in results if r["status"] == "FAIL"), None)
        if failed:
            print(f"wf browse run: FAILED at step {failed['step']} "
                  f"({failed['kind']}): {failed['detail']}")
    if ev is not None:
        m = write_evidence(ev, steps_file, results, rc, effort)
        print(f"wf browse run: evidence -> {ev}/results.json + walkthrough.md "
              f"({m['passed']}/{m['total']} steps, exit {rc})")
    return rc


# --- curl-resume fallback download (for proxies that drop big streams) --------

# The two CfT zips `playwright install chromium` fetches: the full Chromium and
# the headless-shell. Each extracts to its own top-level dir; the inner relative
# path to the executable is used to chmod +x after extraction.
_CFT_ZIPS = (
    # (zip name, install-dir prefix, inner relative path to the executable)
    ("chrome-linux64",
     "chromium", "chrome-linux64/chrome"),
    ("chrome-headless-shell-linux64",
     "chromium_headless_shell", "chrome-headless-shell-linux64/chrome-headless-shell"),
)


def _curl_available() -> bool:
    return shutil.which("curl") is not None


def _curl_content_length(url: str) -> int | None:
    """Expected download size via `curl -sSI -L` Content-Length. -L follows the
    cdn.playwright.dev 307 -> storage.googleapis.com redirect; we take the LAST
    Content-Length header (the redirect itself carries `content-length: 0`).
    Returns None if no usable size header is found (caller falls back to a
    stops-growing heuristic)."""
    try:
        r = subprocess.run(["curl", "-sSI", "-L", url],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    size = None
    for line in r.stdout.splitlines():
        if ":" in line and line.split(":", 1)[0].strip().lower() == "content-length":
            try:
                val = int(line.split(":", 1)[1].strip())
            except ValueError:
                continue
            if val > 0:
                size = val  # last positive wins (final 200, not the 307)
    return size


def _resume_download(url: str, dest_zip: Path, expected: int | None,
                     max_iters: int = 40) -> bool:
    """Resume-download `url` into `dest_zip` with `curl -C -`, looping until the
    file reaches `expected` bytes (or, with no size header, until it stops growing
    across two iterations). Returns True on a complete download, False otherwise.

    This is the crux of the fix: this env's egress proxy permits the host but
    DROPS the large binary stream ("server closed connection"), so a single
    streamed GET fails — but HTTP Range is supported, so a resumable curl reels
    the file in across reconnects."""
    last_size = -1
    stalled = 0
    for _ in range(max_iters):
        subprocess.run(
            ["curl", "-sS", "-L", "-C", "-", "--retry", "3",
             "--retry-all-errors", "--retry-delay", "1", "-o", str(dest_zip), url],
            timeout=600,
        )
        size = dest_zip.stat().st_size if dest_zip.exists() else 0
        if expected is not None:
            if size >= expected:
                return True
        else:
            if size > 0 and size == last_size:
                stalled += 1
                if stalled >= 2:
                    return True  # no size header but two passes made no progress
            else:
                stalled = 0
        if size == last_size and expected is not None:
            # not yet at `expected` but no progress this pass — keep retrying a
            # bounded number of times; curl's own retries handle transient drops.
            stalled += 1
            if stalled >= 5:
                break
        else:
            stalled = 0
        last_size = size
    # final check
    if expected is not None:
        return dest_zip.exists() and dest_zip.stat().st_size >= expected
    return dest_zip.exists() and dest_zip.stat().st_size > 0


def _validate_zip(zip_path: Path) -> bool:
    """True if `zip_path` is a complete, uncorrupted zip (in-process; no subproc)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return zf.testzip() is None
    except (zipfile.BadZipFile, OSError):
        return False


def _resume_install_browsers(version: str, root: Path, rev: str) -> bool:
    """Install BOTH CfT browser binaries (full Chromium + headless-shell) by
    resumable curl, bypassing the proxy that drops Playwright's single-stream
    download. URLs are built from the PARSED CfT `version` (never hardcoded):

        https://cdn.playwright.dev/builds/cft/<version>/linux64/<name>.zip

    `-L` follows the 307 to storage.googleapis.com. Each zip is downloaded into a
    tempdir, validated, extracted into `<root>` (it expands to its own top-level
    dir), the inner binary chmod +x'd, and an INSTALLATION_COMPLETE marker
    touched in the install dir. Returns True only if BOTH binaries land; returns
    False (never crashes) if curl is absent or a download can't complete, so the
    caller can fail closed with guidance."""
    if not _curl_available():
        print("    ! curl not found — cannot use the resume fallback.")
        return False
    ok_all = True
    with tempfile.TemporaryDirectory(prefix="wf-browse-cft-") as td:
        tmp = Path(td)
        for name, dir_prefix, inner_rel in _CFT_ZIPS:
            url = (f"https://cdn.playwright.dev/builds/cft/{version}"
                   f"/linux64/{name}.zip")
            dest_dir = root / f"{dir_prefix}-{rev}"
            inner_exe = dest_dir / inner_rel
            if inner_exe.exists():
                print(f"    - {name}: already present, skipping.")
                continue
            print(f"    - {name}: resume-downloading from {url}")
            expected = _curl_content_length(url)
            sz = f"{expected/1024/1024:.1f} MiB" if expected else "unknown size"
            print(f"      expected size: {sz}")
            zip_path = tmp / f"{name}.zip"
            if not _resume_download(url, zip_path, expected):
                print(f"    ! {name}: resume download did not complete.")
                ok_all = False
                continue
            if not _validate_zip(zip_path):
                print(f"    ! {name}: downloaded zip is corrupt/incomplete.")
                ok_all = False
                continue
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(dest_dir)
                if inner_exe.exists():
                    inner_exe.chmod(inner_exe.stat().st_mode | 0o111)
                else:
                    print(f"    ! {name}: extracted but {inner_rel} is missing.")
                    ok_all = False
                    continue
                (dest_dir / "INSTALLATION_COMPLETE").touch()
                print(f"    - {name}: extracted to {dest_dir} (+x, INSTALLATION_COMPLETE).")
            except Exception as e:
                print(f"    ! {name}: extraction failed ({e.__class__.__name__}: {e}).")
                ok_all = False
            finally:
                try:
                    zip_path.unlink(missing_ok=True)
                except Exception:
                    pass
    return ok_all


_CFT_VERSION_RE = re.compile(r"/cft/([^/]+)/")


def _parse_cft_version(install_output: str) -> str | None:
    """Parse the CfT version from `playwright install chromium`'s output. The
    line is, e.g.:
      Downloading Chrome for Testing 148.0.7778.96 (playwright chromium v1223)
        from https://cdn.playwright.dev/builds/cft/148.0.7778.96/linux64/chrome-linux64.zip
    We find the `...from <url>.zip` and pull the version out of `/cft/<version>/`.
    (The output carries ANSI escapes around ` from <url>`; the regex is robust to
    them since it matches on the URL path, not surrounding bytes.)"""
    m = re.search(r"from (https://\S+\.zip)", install_output)
    if m:
        url = m.group(1)
        # strip any trailing ANSI reset bytes captured by \S+
        url = re.split(r"\x1b\[", url)[0]
        vm = _CFT_VERSION_RE.search(url)
        if vm:
            return vm.group(1)
    # fallback: any /cft/<version>/ anywhere in the output
    vm = _CFT_VERSION_RE.search(install_output)
    return vm.group(1) if vm else None


# --- status + setup -----------------------------------------------------------

def cmd_status() -> int:
    pkg = _playwright_pkg_present()
    chromium = _chromium_present() if pkg else False
    # headless-shell is what `headless=True` actually launches — report it
    # honestly, and require it for "ready" (a missing one => headless fails).
    headless = _headless_shell_present() if pkg else False
    print("wf browse status:")
    print(f"  playwright (python package)    : {'present' if pkg else 'ABSENT'}")
    print(f"  chromium (full browser binary) : {'present' if chromium else 'ABSENT'}")
    print(f"  chrome-headless-shell (binary) : {'present' if headless else 'ABSENT'}"
          "  [required: we launch headless]")
    print(f"  profile dir                    : {_profile_dir()}")
    print(f"  refs map                       : {_refs_path()}"
          f"{' (exists)' if _refs_path().is_file() else ' (none yet)'}")
    if pkg and chromium and headless:
        print("  -> ready: shot/snapshot/run can drive a real browser.")
    else:
        print(f"  -> not ready: {SETUP_HINT}")
    return 0  # status is a report; it never fails


def cmd_setup() -> int:
    """Install Playwright + Chromium on demand; idempotent; fail-closed on a
    blocked network with the manual commands. Prints exactly what it did."""
    print("wf browse setup: ensuring Playwright + Chromium are installed.")
    did_something = False

    if _playwright_pkg_present():
        print("  - playwright package: already installed (skipping pip install).")
    else:
        print("  - playwright package: installing via pip ...")
        rc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright"]
        ).returncode
        if rc != 0:
            print("  ! pip install playwright FAILED (offline / proxy-blocked?).")
            print("    Manual: python3 -m pip install playwright")
            print(f"    Then  : {sys.executable} -m playwright install chromium")
            return 2
        did_something = True
        if not _playwright_pkg_present():
            print("  ! playwright still not importable after install.")
            return 2
        print("  - playwright package: installed.")

    # "fully installed" requires BOTH the full Chromium AND the headless-shell
    # binary (we launch headless). If either is missing, attempt the download.
    if _chromium_present() and _headless_shell_present():
        print("  - chromium binaries: already installed (skipping browser download).")
    else:
        print("  - chromium binaries: downloading via `playwright install chromium` ...")
        # Capture combined stdout+stderr so that, on a proxy-dropped download, we
        # can parse the CfT version and fall back to a resumable curl install.
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True,
        )
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        rc = proc.returncode
        if rc != 0 or not (_chromium_present() and _headless_shell_present()):
            # DON'T fail immediately — this env's proxy drops the big binary
            # stream ("server closed connection") even though it permits the host
            # and the CDN supports HTTP Range. Retry with a resumable curl.
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            version = _parse_cft_version(combined)
            exe_path = _chromium_executable_path()
            root, rev, _hs = _derive_install_layout(exe_path)
            if not _curl_available():
                print("  ! `playwright install chromium` FAILED and curl is unavailable "
                      "for the resume fallback.")
                print(f"    Manual: {sys.executable} -m playwright install chromium")
                print("    (the download is ~175MB and needs outbound network access)")
                return 2
            if not (version and root and rev):
                print("  ! `playwright install chromium` FAILED and the CfT "
                      "version/install layout could not be derived for the fallback.")
                print(f"    (parsed version={version!r}, root={root}, rev={rev})")
                print(f"    Manual: {sys.executable} -m playwright install chromium")
                return 2
            print("  ~ direct download failed: proxy dropped the direct download; "
                  "retrying with resumable curl.")
            print(f"    CfT version {version} -> {root} (rev {rev})")
            if not _resume_install_browsers(version, root, rev):
                print("  ! resume fallback could not complete both downloads.")
                print(f"    Manual: {sys.executable} -m playwright install chromium")
                return 2
        did_something = True
        if not _chromium_present():
            print("  ! chromium (full) still not detected after install.")
            return 2
        if not _headless_shell_present():
            print("  ! chrome-headless-shell still not detected after install "
                  "(required for headless launch).")
            return 2
        print("  - chromium binaries: installed (full + headless-shell).")

    if did_something:
        print("wf browse setup: DONE — ready to drive a real browser.")
    else:
        print("wf browse setup: nothing to do — already fully installed.")
    return 0


# --- selftest (BROWSER-FREE) --------------------------------------------------

def selftest() -> int:
    """Browser-free selftest: routing, fail-closed degradation, the steps parser,
    per-step result serialization, and the @ref map round-trip — all on injected
    data, NEVER launching a real browser.

    Asserts:
      (a) the module imports and status/--selftest run with playwright ABSENT;
      (b) shot/snapshot/run fail closed (exit 2, the setup hint, no traceback)
          when a browser is unavailable;
      (c) the steps parser accepts a well-formed flow and fails closed on a
          malformed / unknown-step file;
      (d) per-step result serialization + the @ref map read/write round-trip.
    """
    import io
    import contextlib
    import tempfile

    problems: list[str] = []

    def capture(fn, *a, **k):
        out, err = io.StringIO(), io.StringIO()
        rc = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = fn(*a, **k)
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    # (a) status runs with playwright absent and never crashes (exit 0).
    rc, out, _ = capture(cmd_status)
    if rc != 0:
        problems.append(f"a: status exited {rc} (expected 0)")
    if "playwright" not in out.lower():
        problems.append("a: status output did not report playwright availability")
    # In THIS container playwright is absent; assert we detect+report that without
    # raising. (If a future box HAS it, the status line still must be well-formed.)
    if not _playwright_pkg_present() and "ABSENT" not in out:
        problems.append("a: playwright absent but status did not say ABSENT")

    # (b) the browser commands fail closed with the hint + non-zero, NO traceback.
    #     We force the "unavailable" path deterministically by pointing the probe
    #     at the real environment: _require_browser must raise BrowserUnavailable
    #     whenever the package or binary is missing. To keep the selftest
    #     environment-INDEPENDENT, we exercise the fail-closed wrapper directly via
    #     a monkeypatched _require_browser that always reports unavailable.
    import types
    this = sys.modules[__name__]
    saved = this._require_browser

    def _always_unavailable():
        raise BrowserUnavailable("Chromium browser binary is not installed")
    try:
        this._require_browser = _always_unavailable  # type: ignore[assignment]

        # shot: build args via the same path main() uses, but call the wrapper.
        rc, out, err = capture(_browse_guarded, lambda: cmd_shot("http://x", "/tmp/none.png", False))
        if rc != 2:
            problems.append(f"b: shot exited {rc} on no-browser (expected 2)")
        if SETUP_HINT not in (out + err):
            problems.append("b: shot did not print the setup hint")
        if "Traceback" in (out + err):
            problems.append("b: shot leaked a traceback")

        rc, out, err = capture(_browse_guarded, lambda: cmd_snapshot("http://x", False))
        if rc != 2:
            problems.append(f"b: snapshot exited {rc} on no-browser (expected 2)")
        if SETUP_HINT not in (out + err):
            problems.append("b: snapshot did not print the setup hint")

        # run: with a VALID flow file, the failure must be the missing browser
        # (exit 2 + hint), not a parse error — proving fail-closed ordering.
        with tempfile.TemporaryDirectory() as dd:
            good = Path(dd) / "flow.yaml"
            good.write_text("- goto: https://example.com\n- assert_text: Example Domain\n")
            rc, out, err = capture(cmd_run, str(good))
            if rc != 2:
                problems.append(f"b: run on a valid flow w/o browser exited {rc} (expected 2)")
            if SETUP_HINT not in (out + err):
                problems.append("b: run did not print the setup hint")
            if "Traceback" in (out + err):
                problems.append("b: run leaked a traceback")
    finally:
        this._require_browser = saved  # type: ignore[assignment]

    # (c) steps parser: a well-formed flow parses; malformed / unknown-step fails.
    try:
        steps = parse_steps(
            "- goto: https://example.com\n"
            "- { kind: fill, selector: '#u', value: alice }\n"
            "- click: Sign in\n"
            "- assert_text: Welcome\n"
        )
        if [s["kind"] for s in steps] != ["goto", "fill", "click", "assert_text"]:
            problems.append(f"c: parsed kinds wrong: {[s['kind'] for s in steps]}")
        if steps[0]["value"] != "https://example.com":
            problems.append("c: goto shorthand value not captured")
        if steps[1].get("selector") != "#u" or steps[1].get("value") != "alice":
            problems.append("c: explicit fill args not captured")
    except Exception as e:
        problems.append(f"c: well-formed flow failed to parse: {e}")

    # JSON form also parses (the parser must accept JSON too).
    try:
        js = parse_steps('[{"kind": "goto", "value": "http://a"}, {"assert_title": "X"}]')
        if [s["kind"] for s in js] != ["goto", "assert_title"]:
            problems.append("c: JSON flow parsed to wrong kinds")
    except Exception as e:
        problems.append(f"c: JSON flow failed to parse: {e}")

    # the runtime-error assertion kinds parse (bare + with an ignore list), and a
    # non-string/list ignore fails closed.
    try:
        rsteps = parse_steps(
            "- assert_no_console_errors\n"
            "- { kind: assert_no_failed_requests, ignore: ['/favicon.ico', analytics] }\n")
        if [s["kind"] for s in rsteps] != ["assert_no_console_errors",
                                           "assert_no_failed_requests"]:
            problems.append(f"c: runtime-assert kinds parsed wrong: {[s['kind'] for s in rsteps]}")
        if rsteps[1].get("ignore") != ["/favicon.ico", "analytics"]:
            problems.append("c: assert_no_failed_requests ignore list not captured")
    except Exception as e:
        problems.append(f"c: runtime-assert flow failed to parse: {e}")
    try:
        parse_steps("- { kind: assert_no_console_errors, ignore: 5 }\n")
        problems.append("c: numeric ignore was accepted (should fail closed)")
    except ValueError:
        pass
    # assert_a11y parses bare and with options; a bad option shape fails closed.
    try:
        asteps = parse_steps(
            "- assert_a11y\n"
            "- { kind: assert_a11y, fail_on: [critical], tags: [wcag2aa], ignore: [color-contrast] }\n")
        if [s["kind"] for s in asteps] != ["assert_a11y", "assert_a11y"]:
            problems.append(f"c: assert_a11y kinds parsed wrong: {[s['kind'] for s in asteps]}")
        if asteps[1].get("fail_on") != ["critical"] or asteps[1].get("ignore") != ["color-contrast"]:
            problems.append("c: assert_a11y options not captured")
    except Exception as e:
        problems.append(f"c: assert_a11y flow failed to parse: {e}")
    try:
        parse_steps("- { kind: assert_a11y, tags: 5 }\n")
        problems.append("c: assert_a11y numeric tags accepted (should fail closed)")
    except ValueError:
        pass

    # (f) the pure runtime-error summaries: errors/failures fail (unless ignored),
    #     an empty accumulator passes — exercised without a browser.
    ok, _d = _console_error_summary([], None)
    if not ok:
        problems.append("f: empty console errors should pass")
    ok, d = _console_error_summary(["Uncaught TypeError: x", "favicon 404"], ["favicon"])
    if ok or "TypeError" not in d:
        problems.append(f"f: a real console error must fail (ignored favicon): ok={ok} d={d}")
    ok, _d = _console_error_summary(["only favicon noise"], ["favicon"])
    if not ok:
        problems.append("f: a fully-ignored console error should pass")
    ok, d = _failed_request_summary(["500 https://api/x", "404 https://cdn/analytics.js"], "analytics")
    if ok or "500" not in d:
        problems.append(f"f: a 500 must fail (ignored analytics): ok={ok} d={d}")
    ok, _d = _failed_request_summary([], None)
    if not ok:
        problems.append("f: no failed requests should pass")
    # a11y: a critical violation fails; ignoring its rule id passes; only
    # minor/moderate (below the default fail levels) passes; empty passes.
    crit = [{"id": "image-alt", "impact": "critical", "nodes": [{}, {}]}]
    ok, d = _axe_summary(crit, None, None)
    if ok or "image-alt" not in d:
        problems.append(f"f: a critical a11y violation must fail: ok={ok} d={d}")
    ok, _d = _axe_summary(crit, None, "image-alt")
    if not ok:
        problems.append("f: ignoring the only violation's rule id should pass")
    ok, _d = _axe_summary([{"id": "x", "impact": "moderate", "nodes": [{}]}], None, None)
    if not ok:
        problems.append("f: a moderate-only violation should pass the default critical+serious gate")
    ok, _d = _axe_summary([], None, None)
    if not ok:
        problems.append("f: no a11y violations should pass")

    for bad, why in (
        ("- frobnicate: nope\n", "unknown step kind"),
        ("- goto:\n", "missing required arg"),
        ("not: [a, list]\n", "not a top-level list"),
        ("- {selector: '#u', value: x}\n", "ambiguous multi-key shorthand"),
        ("", "empty file"),
    ):
        try:
            parse_steps(bad)
            problems.append(f"c: malformed flow accepted ({why})")
        except ValueError:
            pass  # expected: fail closed
        except Exception as e:
            problems.append(f"c: malformed flow raised {type(e).__name__}, expected ValueError ({why})")

    # (d) per-step result serialization + @ref map read/write round-trip, on a
    #     temp browse dir so the real .wf/browse is never touched.
    with tempfile.TemporaryDirectory() as dd:
        os.environ["WF_BROWSE_DIR"] = dd
        try:
            # result serialization
            results = [make_result(1, "goto", "PASS", "-> x"),
                       make_result(2, "assert_text", "FAIL", "not found")]
            rendered = render_results(results)
            if "PASS  goto" not in rendered or "FAIL  assert_text" not in rendered:
                problems.append("d: render_results missing PASS/FAIL rows")
            if "1/2 steps PASSED" not in rendered:
                problems.append("d: render_results wrong pass count")

            # @ref map round-trip through the on-disk refs.json
            ref_map = {"@e1": {"role": "button", "name": "Sign in"},
                       "@e2": {"role": "link", "name": "Home"}}
            write_refs(ref_map)
            back = read_refs()
            if back != ref_map:
                problems.append(f"d: refs round-trip mismatch: {back}")

            # the axtree flattener mints @refs for interactive nodes only, on a
            # synthetic tree (no browser) — exercising production flatten logic.
            tree = {"role": "WebArea", "name": "doc", "children": [
                {"role": "heading", "name": "Title"},
                {"role": "button", "name": "OK"},
                {"role": "link", "name": "Next"},
                {"role": "text", "name": "blah"},
            ]}
            rows, refs2 = flatten_axtree(tree)
            roles_with_ref = sorted(refs2[r]["role"] for r in refs2)
            if roles_with_ref != ["button", "link"]:
                problems.append(f"d: flatten minted refs for wrong roles: {roles_with_ref}")
            outline = render_outline(rows)
            if "button: \"OK\" @e" not in outline or "heading: \"Title\"" not in outline:
                problems.append("d: outline rendering wrong")
            if "@e" in outline.split("heading")[1].split("\n")[0]:
                problems.append("d: a non-interactive node got an @ref")

            # (e) the CDP-axtree converter assembles flat `getFullAXTree` nodes
            #     (nodeId/role.value/name.value/childIds) into the SAME nested
            #     {role,name,children} dict the removed page.accessibility.snapshot()
            #     produced — skipping ignored/structural/text-noise nodes while
            #     never dropping a path to an interactive descendant. Exercised on
            #     injected CDP-shaped data, NO browser.
            cdp_nodes = [
                {"nodeId": "1", "role": {"value": "RootWebArea"}, "name": {"value": ""},
                 "childIds": ["2"], "ignored": False},
                # a `none` structural wrapper (ignored) — must be collapsed, its
                # children hoisted, yet the button beneath it survives.
                {"nodeId": "2", "role": {"value": "none"}, "name": None,
                 "childIds": ["3", "4", "5", "6"], "ignored": True},
                {"nodeId": "3", "role": {"value": "heading"}, "name": {"value": "Title"},
                 "childIds": ["7"], "ignored": False},
                # a StaticText text-noise leaf under the heading — must be dropped.
                {"nodeId": "7", "role": {"value": "StaticText"}, "name": {"value": "Title"},
                 "childIds": [], "ignored": False},
                {"nodeId": "4", "role": {"value": "button"}, "name": {"value": "OK"},
                 "childIds": [], "ignored": False},
                {"nodeId": "5", "role": {"value": "textbox"}, "name": {"value": "email"},
                 "childIds": [], "ignored": False},
                {"nodeId": "6", "role": {"value": "link"}, "name": {"value": "Next"},
                 "childIds": [], "ignored": False},
            ]
            nested = cdp_axtree_to_nested(cdp_nodes)
            if nested.get("role") != "RootWebArea":
                problems.append(f"e: CDP convert root role wrong: {nested.get('role')!r}")
            kids = [(c["role"], c["name"]) for c in nested.get("children", [])]
            if kids != [("heading", "Title"), ("button", "OK"),
                        ("textbox", "email"), ("link", "Next")]:
                problems.append(f"e: CDP convert hoisted/collapsed wrong: {kids}")
            # the StaticText noise leaf must have been dropped from the heading.
            heading = next((c for c in nested["children"] if c["role"] == "heading"), {})
            if heading.get("children"):
                problems.append(f"e: CDP convert kept text-noise leaf: {heading.get('children')}")
            # feeding the converted tree through the UNCHANGED flatten/ref logic
            # mints @refs for exactly the interactive nodes — the end-to-end seam.
            crows, crefs = flatten_axtree(nested)
            cdp_ref_roles = sorted(crefs[r]["role"] for r in crefs)
            if cdp_ref_roles != ["button", "link", "textbox"]:
                problems.append(f"e: CDP->flatten minted refs for wrong roles: {cdp_ref_roles}")
            coutline = render_outline(crows)
            if 'button: "OK" @e' not in coutline or 'textbox: "email" @e' not in coutline:
                problems.append("e: CDP->flatten outline missing interactive @refs")
        finally:
            os.environ.pop("WF_BROWSE_DIR", None)

    # --- (f) verification-as-artifact: --evidence-dir redirect + manifest (pure) --
    with tempfile.TemporaryDirectory() as dd:
        ev = Path(dd) / "_workflow" / "evidence" / "demo-task"
        steps = [{"kind": "screenshot", "path": "home.png"},
                 {"kind": "screenshot", "path": "/tmp/abs.png"},
                 {"kind": "goto", "value": "http://x"}]
        _redirect_screenshots(steps, ev)
        if steps[0]["path"] != str(ev / "home.png"):
            problems.append("f: relative screenshot path not redirected into evidence-dir")
        if steps[1]["path"] != "/tmp/abs.png":
            problems.append("f: absolute screenshot path was wrongly rewritten")
        results = [make_result(1, "goto", "PASS", "-> http://x"),
                   make_result(2, "assert_text", "PASS", "found 'hi'"),
                   make_result(3, "assert_no_console_errors", "FAIL", "1 console error")]
        write_evidence(ev, "flow.yaml", results, 1)
        rj = json.loads((ev / "results.json").read_text())
        want_passed = sum(1 for r in results if r["status"] == "PASS")
        if rj.get("passed") != want_passed or rj.get("total") != 3 or rj.get("exit_code") != 1:
            problems.append("f: results.json pass-count/total/exit-code does not match the run")
        if not (ev / "walkthrough.md").is_file():
            problems.append("f: walkthrough.md not written")
        else:
            wt = (ev / "walkthrough.md").read_text()
            if "assert_no_console_errors" not in wt or "exit 1" not in wt:
                problems.append("f: walkthrough.md missing the step table / exit code")

    # --- (g) persona-tester step kinds, effort counter, isolated profiles (pure) --
    good = json.dumps([
        {"goto": "http://x"}, {"kind": "dblclick", "text": "Row 1"},
        {"kind": "hover", "selector": "#menu"}, {"press": "Tab"},
        {"kind": "press", "key": "Enter", "selector": "#q"},
        {"kind": "select", "selector": "#size", "option": "L"},
        {"kind": "set_viewport", "width": 375, "height": 667},
        {"set_offline": True}, "reload", "back", "snapshot",
        {"kind": "fill", "selector": "#q", "value": "x"}, {"click": "Save"},
    ])
    try:
        gsteps = parse_steps(good)
        if [s_["kind"] for s_ in gsteps][-4:] != ["back", "snapshot", "fill", "click"]:
            problems.append("g: new step kinds parsed in the wrong order/kind")
        e = effort_summary(gsteps)
        if e["actions"] != 7 or e["navigations"] != 1 or e["by_kind"].get("press") != 2:
            problems.append(f"g: effort counted wrong: {e}")
        if effort_summary(parse_steps(good)) != e:
            problems.append("g: effort count is not deterministic")
    except ValueError as ex:
        problems.append(f"g: valid persona flow rejected: {ex}")
    for bad, why in (
        ('[{"kind": "set_viewport", "width": 375}]', "set_viewport without height"),
        ('[{"kind": "set_viewport", "width": -1, "height": 5}]', "negative viewport"),
        ('[{"set_offline": "yes"}]', "non-bool set_offline"),
        ('[{"kind": "select", "selector": "#s"}]', "select without option"),
        ('[{"kind": "press"}]', "press without key"),
        ('["dblclick"]', "dblclick without target"),
    ):
        try:
            parse_steps(bad)
            problems.append(f"g: accepted {why}")
        except ValueError:
            pass
    with tempfile.TemporaryDirectory() as gd:
        os.environ["WF_BROWSE_DIR"] = gd
        try:
            shared_refs, shared_prof = _refs_path(), _profile_dir()
            os.environ["WF_BROWSE_PROFILE"] = "lazy"
            lazy = (_refs_path(), _profile_dir())
            os.environ["WF_BROWSE_PROFILE"] = "chaos"
            chaos = (_refs_path(), _profile_dir())
            if len({shared_refs, lazy[0], chaos[0]}) != 3 or \
                    len({shared_prof, lazy[1], chaos[1]}) != 3:
                problems.append("g: named profiles do not isolate refs/profile dirs")
            os.environ["WF_BROWSE_PROFILE"] = "../escape"
            rc, _o, _e = capture(_profile_name)
            if rc != 2:
                problems.append("g: path-traversal profile name was not rejected")
        finally:
            os.environ.pop("WF_BROWSE_PROFILE", None)
            os.environ.pop("WF_BROWSE_DIR", None)
        # both headless-shell install layouts are detected.
        root = Path(gd) / "pw"
        exe = root / "chromium-1194" / "chrome-linux" / "chrome"
        old = root / "chromium_headless_shell-1194" / "chrome-linux" / "headless_shell"
        old.parent.mkdir(parents=True)
        old.write_text("")
        if _derive_install_layout(str(exe))[2] != old:
            problems.append("g: older chrome-linux/headless_shell layout not detected")
        old.unlink()
        cft = (root / "chromium_headless_shell-1194" / "chrome-headless-shell-linux64"
               / "chrome-headless-shell")
        if _derive_install_layout(str(exe))[2] != cft:
            problems.append("g: missing headless shell should default to the CfT path")

    if problems:
        print("wf browse selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf browse selftest: PASS (loads+status with playwright ABSENT; "
          "shot/snapshot/run fail closed w/ setup hint + no traceback; steps "
          "parser accepts good flow & fails closed on malformed; runtime-error "
          "assert kinds parse + their pure console/request summaries flag real "
          "errors and honor ignore lists; assert_a11y parses + its pure axe summary "
          "fails critical/serious violations and honors ignore/impact levels; result "
          "serialization + @ref map "
          "round-trip + axtree flatten + CDP-axtree->nested converter + "
          "--evidence-dir screenshot redirect & results.json/walkthrough manifest + "
          "persona step kinds, deterministic effort count, isolated named profiles "
          "and both headless-shell layouts all browser-free)")
    return 0


def cmd_effort(flow: str, baseline: str | None) -> int:
    """Browser-free: report the user effort a flow costs, optionally diffed
    against a baseline flow for the SAME task. Only meaningful when both flows
    PASS under `wf browse run` (a shorter failing flow proves nothing)."""
    def load(f: str) -> list[dict]:
        if not Path(f).is_file():
            _die(f"steps file not found: {f}")
        try:
            return parse_steps(Path(f).read_text())
        except ValueError as e:
            _die(f"bad steps file {f}: {e}")
    cur = effort_summary(load(flow))
    print(f"{flow}: {render_effort(cur)}")
    if baseline:
        base = effort_summary(load(baseline))
        print(f"{baseline}: {render_effort(base)}")
        d = cur["actions"] - base["actions"]
        verdict = "fewer" if d < 0 else ("more" if d > 0 else "same")
        print(f"delta: {d:+d} action(s) ({verdict} than baseline); "
              f"navigations {cur['navigations'] - base['navigations']:+d}")
    return 0


def _browse_guarded(fn):
    """Wrap a browser command so BrowserUnavailable becomes a clean exit 2 + hint
    (never a traceback). Used by every browser subcommand in main()."""
    try:
        return fn()
    except BrowserUnavailable as e:
        _die(f"{e} — {SETUP_HINT}")


# --- CLI ----------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf browse", add_help=True)
    ap.add_argument("--selftest", action="store_true",
                    help="run the browser-free selftest and exit")
    ap.add_argument("--profile", default=None,
                    help="named, isolated browser profile + @ref map (for concurrent "
                         "runs, e.g. one per persona tester); default: the shared one")
    sub = ap.add_subparsers(dest="action")

    sub.add_parser("status", help="report playwright + chromium availability")
    sub.add_parser("setup", help="install playwright + chromium on demand (idempotent)")

    p_shot = sub.add_parser("shot", help="screenshot a URL")
    p_shot.add_argument("url")
    p_shot.add_argument("out", help="output .png path")
    p_shot.add_argument("--full-page", action="store_true", help="capture the full scroll height")

    p_snap = sub.add_parser("snapshot", help="dump the accessibility tree + mint @refs")
    p_snap.add_argument("url")
    p_snap.add_argument("--json", action="store_true", help="emit JSON instead of an outline")

    p_run = sub.add_parser("run", help="execute a scripted flow (YAML/JSON) — the E2E runner")
    p_run.add_argument("steps_file", help="YAML or JSON list of steps")
    p_run.add_argument("--evidence-dir", default=None,
                       help="persist screenshots + results.json + walkthrough.md into "
                            "DIR (use a COMMITTED tree, e.g. _workflow/evidence/<task>/, "
                            "not the gitignored .wf/) so the verification is durable proof")

    p_eff = sub.add_parser("effort", help="count a flow's user actions (browser-free); "
                                          "diff against a baseline flow for the same task")
    p_eff.add_argument("steps_file")
    p_eff.add_argument("--baseline", default=None, help="baseline flow for the same task")

    args = ap.parse_args(argv)
    if args.profile:
        os.environ["WF_BROWSE_PROFILE"] = args.profile
        _profile_name()  # validate early (exit 2 on a bad name)

    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("a subcommand (status|setup|shot|snapshot|run|effort) or --selftest is required")

    if args.action == "status":
        return cmd_status()
    if args.action == "setup":
        return cmd_setup()
    if args.action == "shot":
        return _browse_guarded(lambda: cmd_shot(args.url, args.out, args.full_page))
    if args.action == "snapshot":
        return _browse_guarded(lambda: cmd_snapshot(args.url, args.json))
    if args.action == "run":
        # cmd_run does its own fail-closed handling
        return cmd_run(args.steps_file, args.evidence_dir)
    if args.action == "effort":
        return cmd_effort(args.steps_file, args.baseline)
    ap.error(f"unknown action {args.action!r}")  # unreachable


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
