#!/usr/bin/env python3
"""wf-guard.py — command-level safety guardrails: a PreToolUse gate with two
distinct strengths. `careful` is a BEST-EFFORT backstop / speed-bump that warns
or blocks OBVIOUS, accidental destructive shell commands — it is NOT a security
boundary, a sandbox, or an evasion-proof filter: it matches a conservative
allowlist of known-dangerous command shapes and can be trivially bypassed (shell
variables, line-splits, command substitution, base64/encodings, aliases). Treat
it as a guard rail against fat-finger mistakes, never as containment for a
determined or adversarial caller. `freeze` is the stronger path-confinement: it
restricts file edits to a single allowed directory by resolving the target path,
so it actually confines the WHERE of edits rather than pattern-guessing intent.
The runtime layer behind the authority/destructive-action boundary in CLAUDE.md
(inspired by gstack's /careful, /freeze, /guard).

Two parts share ONE detection core:
  - the `wf guard check` subcommand (what the hook calls), and
  - the same logic exercised by `--selftest` so it is unit-testable hook-free.

State: JSON at <repo>/.wf/guard.json (created lazily on first write; mirrors how
wf-lock.py locates its dot-dir state). Fields:
    { "careful": bool, "freeze_dir": str|null,    freeze_dir is repo-relative
      "budget_max": int|null, "budget_count": int }   tool-call circuit-breaker

A third, independent mode `budget` is a runaway-loop CIRCUIT-BREAKER: a per-task
tool-call ceiling that the PreToolUse gate counts against and BLOCKS once crossed,
so a thrashing loop halts instead of burning the session. Opt-in, fail-open, with a
clean resume (raise the ceiling or clear it). It is a tool-call cap (a deterministic
proxy for runaway cost); live token/$-spend gating is a deliberate non-goal here.

DEFAULT-SAFE: when NO guard state exists (fresh repo / careful off / no freeze),
the gate is a NO-OP — it allows everything. Guarding activates ONLY after the
user runs `wf guard ...`, so it never disrupts normal work.

Subcommands:
    wf guard status                 — print current state.
    wf guard careful on|off         — toggle destructive-command guarding.
    wf guard freeze <dir>           — restrict edits to <dir> (stored repo-rel).
    wf guard unfreeze               — clear the freeze.
    wf guard budget <N>|off         — tool-call circuit-breaker (set ceiling / clear).
    wf guard on                     — careful on + freeze(cwd) (combined mode).
    wf guard off                    — careful off + unfreeze + budget cleared (all off).
    wf guard check --tool <name> [--command <str>] [--path <p>]
                                    — the SAME logic the hook uses.
    wf guard --selftest             — exercise detection with planted cases.

Exit codes (check / the hook): 0 = allow (a warning may print to stderr), 2 =
BLOCK. status/careful/freeze/unfreeze/on/off → 0. selftest → 0 pass / 1 fail.
usage error → 2.

FAIL-OPEN: malformed input, a missing/corrupt state file, or any unexpected
error returns 0 (allow). The gate must never crash a user's tool call.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

STATE_FILE = "guard.json"
# budget_max: tool-call ceiling for the current task (null = off); budget_count:
# calls seen since the budget was (re)set. The budget is a runaway-loop
# CIRCUIT-BREAKER — opt-in, fail-open, with a clean resume (raise it / clear it).
DEFAULT_STATE = {"careful": False, "freeze_dir": None,
                 "budget_max": None, "budget_count": 0}

# ── Destructive-command patterns ──────────────────────────────────────────────
# ALLOWLIST-STYLE: we match a small, conservative set of KNOWN-DANGEROUS shapes
# and DEFAULT TO ALLOW everything else, so false positives are rare. Each entry
# is (compiled-regex, human label). Edit this list deliberately — it is the
# single source of truth for "what counts as destructive". Patterns are matched
# case-insensitively against the raw command string.
#
# BEST-EFFORT, NOT EVASION-PROOF. These patterns catch OBVIOUS, literal forms.
# They DELIBERATELY do not attempt to defeat obfuscation: variable expansion
# (`D=/; rm -rf $D`), line-splits / `\`-continuations, command substitution,
# base64/`eval` decoding, or aliases all slip through by design. `careful` is a
# fat-finger speed-bump, not containment — see the module docstring. The known
# limit is documented rather than chased.
import re

# rm flag-cluster fragment: short bundles like -rf/-fr/-r -f, or the long forms
# --recursive / --force in any order. Used by the rm patterns below.
_RM_RECURSIVE_FORCE = (
    r"(?:"
    r"(?:-\w*[rf]\w*[rf]\w*)"                      # combined short: -rf, -fr, -Rf …
    r"|(?:-\w*r\w*\s+(?:-\w+\s+)*-\w*f\w*)"        # split short: -r … -f
    r"|(?:-\w*f\w*\s+(?:-\w+\s+)*-\w*r\w*)"        # split short: -f … -r
    r"|(?:--recursive\b[\s\S]*?--force\b)"         # long: --recursive … --force
    r"|(?:--force\b[\s\S]*?--recursive\b)"         # long: --force … --recursive
    r")"
)
# A dangerous broad target for rm: filesystem root, $HOME/~, a glob, .., or ANY
# absolute path (/etc, /home/user/x, optionally quoted). `--no-preserve-root`
# is itself a tell. Relative/named targets (./build, node_modules) are excluded.
_RM_BROAD_TARGET = (
    r"(?:"
    r"--no-preserve-root"                          # explicit root-override tell
    r"|['\"]?/['\"]?\s*(?:$|;|&|\||\n)"            # root "/" possibly quoted, then EOL/sep
    r"|['\"]?/[^\s'\"]*"                           # any absolute path /... (quoted or bare)
    r"|~"                                          # home
    r"|\$HOME\b"                                   # $HOME
    r"|\*"                                         # glob
    r"|\.\.(?:/|\s|$)"                             # parent ..
    r")"
)

DESTRUCTIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # rm -rf / -fr / --recursive --force targeting a BROAD target: filesystem
    # root, ANY absolute path, ~, $HOME, a glob, or `..`. We require the
    # recursive+force flags AND a broad target so `rm -rf ./build` is not
    # flagged. Catches quoted root (`rm -rf "/"`), non-root absolute paths
    # (`rm -rf /etc`), and the long-flag form (`rm --recursive --force /`).
    (re.compile(r"\brm\s+(?:-\w+\s+)*" + _RM_RECURSIVE_FORCE
                + r"(?:\s+-[\w-]+)*\s+" + _RM_BROAD_TARGET, re.I),
     "rm -rf on a broad/absolute/root path"),
    # git push --force / -f / --force-with-lease to a protected ref (main/master).
    (re.compile(r"\bgit\s+push\b.*(?:--force\b|--force-with-lease\b|\s-f\b)"
                r".*\b(?:main|master)\b", re.I),
     "git force-push to a protected ref (main/master)"),
    # any git push --force / -f / --force-with-lease (force-push, broad).
    (re.compile(r"\bgit\s+push\b.*(?:--force\b|--force-with-lease\b|\s-f\b)", re.I),
     "git force-push"),
    # git push with a `+ref` force refspec (e.g. `git push origin +main`).
    (re.compile(r"\bgit\s+push\b[^\n]*\s\+\S", re.I),
     "git push with a +ref force refspec"),
    # git reset --hard (discards local changes irreversibly).
    (re.compile(r"\bgit\s+reset\s+(?:[^\n]*\s)?--hard\b", re.I),
     "git reset --hard (discards local changes)"),
    # SQL destructive DDL — ONLY in a plausible DB-execution context. We require
    # a DB client (psql/mysql/mariadb/sqlite3/sqlcmd) OR an execute flag
    # (-c/--command/-e/--execute) near the keyword, so a commit message or a
    # grep target containing "DROP TABLE"/"TRUNCATE" is NOT flagged.
    (re.compile(r"\b(?:psql|mysql|mariadb|sqlite3|sqlcmd)\b[\s\S]*?"
                r"\bDROP\s+(?:TABLE|DATABASE)\b", re.I),
     "SQL DROP TABLE/DATABASE via a DB client"),
    (re.compile(r"(?:-c\b|--command\b|-e\b|--execute\b)[\s\S]*?"
                r"\bDROP\s+(?:TABLE|DATABASE)\b", re.I),
     "SQL DROP TABLE/DATABASE via an execute flag"),
    (re.compile(r"\b(?:psql|mysql|mariadb|sqlite3|sqlcmd)\b[\s\S]*?"
                r"\bTRUNCATE\s+(?:TABLE\s+)?\w", re.I),
     "SQL TRUNCATE via a DB client"),
    (re.compile(r"(?:-c\b|--command\b|-e\b|--execute\b)[\s\S]*?"
                r"\bTRUNCATE\s+(?:TABLE\s+)?\w", re.I),
     "SQL TRUNCATE via an execute flag"),
    # mkfs (reformat a filesystem).
    (re.compile(r"\bmkfs(?:\.\w+)?\b", re.I), "mkfs (reformat a filesystem)"),
    # dd writing to a device/file (dd if=...).
    (re.compile(r"\bdd\s+(?:[^\n]*\s)?if=", re.I), "dd if= (raw disk/file write)"),
    # write / dd-output to a raw block device /dev/sd* (e.g. `> /dev/sda`,
    # `cat x > /dev/sdb`, `dd ... of=/dev/sda`). Overwrites a whole disk.
    (re.compile(r"(?:>\s*|\bof=)/dev/sd[a-z]\d*\b", re.I),
     "write to a raw block device /dev/sd*"),
    # find <path> -delete (recursively deletes matched files).
    (re.compile(r"\bfind\b[^\n]*\s-delete\b", re.I),
     "find ... -delete (recursive delete)"),
    # classic fork bomb :(){ :|:& };:
    (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
     "fork bomb :(){ :|:& };:"),
    # chmod -R 777 / (recursive world-writable on root).
    (re.compile(r"\bchmod\s+(?:-\w+\s+)*-\w*R\w*\s+777\s+/", re.I),
     "chmod -R 777 / (recursive world-writable root)"),
]

EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}


# ── Repo / state location (mirrors wf-lock.py's dot-dir approach) ──────────────
def _repo_root() -> Path:
    """Repo root is this script's parent's parent (scripts/ -> repo)."""
    return Path(__file__).resolve().parent.parent


def _state_dir(override: str | None = None) -> Path:
    """<repo>/.wf — created lazily on first write."""
    return Path(override) if override else _repo_root() / ".wf"


def load_state(state_dir: Path) -> dict:
    """Load guard state, FAIL-OPEN to the default (all-off) on any problem."""
    path = state_dir / STATE_FILE
    if not path.is_file():
        return dict(DEFAULT_STATE)
    try:
        data = json.loads(path.read_text() or "{}")
        if not isinstance(data, dict):
            return dict(DEFAULT_STATE)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_STATE)
    bmax = data.get("budget_max")
    bmax = bmax if isinstance(bmax, int) and not isinstance(bmax, bool) and bmax > 0 else None
    bcount = data.get("budget_count")
    bcount = bcount if isinstance(bcount, int) and not isinstance(bcount, bool) and bcount >= 0 else 0
    return {
        "careful": bool(data.get("careful", False)),
        "freeze_dir": data.get("freeze_dir") or None,
        "budget_max": bmax,
        "budget_count": bcount,
    }


def save_state(state_dir: Path, state: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    bmax = state.get("budget_max")
    bmax = bmax if isinstance(bmax, int) and not isinstance(bmax, bool) and bmax > 0 else None
    (state_dir / STATE_FILE).write_text(
        json.dumps({"careful": bool(state.get("careful", False)),
                    "freeze_dir": state.get("freeze_dir") or None,
                    "budget_max": bmax,
                    "budget_count": int(state.get("budget_count", 0) or 0)},
                   indent=2) + "\n")


# ── Detection core (shared by the hook path and selftest) ─────────────────────
def match_destructive(command: str) -> str | None:
    """Return the label of the FIRST destructive pattern that matches, else None.
    Allowlist-style: anything not matched is treated as safe."""
    if not command:
        return None
    for pat, label in DESTRUCTIVE_PATTERNS:
        if pat.search(command):
            return label
    return None


def _resolve_under(base: Path, target: Path) -> bool:
    """True if `target` resolves to `base` or a path inside it (segment-aware,
    so /a/bcd is NOT inside /a/b). Both are resolved without requiring existence."""
    try:
        base_r = base.resolve()
        target_r = target.resolve()
    except (OSError, RuntimeError):
        return False
    if target_r == base_r:
        return True
    try:
        target_r.relative_to(base_r)
        return True
    except ValueError:
        return False


def budget_step(state: dict) -> tuple[bool, str | None]:
    """The tool-call circuit-breaker. Increments state['budget_count'] IN PLACE and
    returns (block, message). Blocks once the count EXCEEDS budget_max (so a budget
    of N allows N calls, blocks the N+1th and every call after — until the user
    raises or clears it). No-op (False, None) when no budget is set. Pure on the
    dict (the caller persists), so it is unit-testable hook-free."""
    bmax = state.get("budget_max")
    if not isinstance(bmax, int) or isinstance(bmax, bool) or bmax <= 0:
        return False, None
    count = int(state.get("budget_count", 0) or 0) + 1
    state["budget_count"] = count
    if count > bmax:
        return True, (f"wf guard: BLOCKED — tool-call budget exhausted "
                      f"({bmax}/{bmax} used). This is a runaway-loop circuit-breaker. "
                      f"Raise it with `wf guard budget <N>` or clear it with "
                      f"`wf guard budget off` to resume.")
    return False, None


def evaluate(state: dict, tool: str, command: str | None,
             path: str | None, repo_root: Path) -> tuple[int, str | None]:
    """The single decision function. Returns (exit_code, message):
      (0, None)        — allow, nothing to say
      (0, warning)     — allow but emit `warning` to stderr (destructive + careful off)
      (2, reason)      — BLOCK, emit `reason` to stderr.

    Default-safe: with careful off and no freeze set, ALWAYS returns (0, None)."""
    careful = bool(state.get("careful", False))
    freeze_dir = state.get("freeze_dir") or None

    # 1. Destructive-command guard (Bash only).
    if tool == "Bash" and command:
        label = match_destructive(command)
        if label:
            if careful:
                return 2, (f"wf guard: BLOCKED a destructive command "
                           f"({label}). Disable with `wf guard careful off` if "
                           f"this is intentional.")
            # careful OFF → warn-only, still allow.
            return 0, (f"wf guard: WARNING — potentially destructive command "
                       f"({label}). `wf guard careful on` would block it.")

    # 2. Freeze guard (Edit/Write/MultiEdit only).
    if freeze_dir and tool in EDIT_TOOLS and path:
        allowed = (repo_root / freeze_dir)
        target = Path(path)
        if not target.is_absolute():
            target = repo_root / target
        if not _resolve_under(allowed, target):
            return 2, (f"wf guard: BLOCKED an edit OUTSIDE the freeze boundary. "
                       f"Edits are restricted to '{freeze_dir}/' "
                       f"(target: {path}). Clear with `wf guard unfreeze`.")

    return 0, None


# ── stdin parsing for the hook (Claude Code PreToolUse contract) ──────────────
def parse_hook_stdin(raw: str) -> tuple[str, str | None, str | None]:
    """Extract (tool_name, command, file_path) from a PreToolUse JSON payload.
    FAIL-OPEN: returns ("", None, None) on any parse problem so the caller allows."""
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return "", None, None
    except (json.JSONDecodeError, ValueError):
        return "", None, None
    tool = obj.get("tool_name") or ""
    ti = obj.get("tool_input")
    if not isinstance(ti, dict):
        ti = {}
    command = ti.get("command")
    path = ti.get("file_path")
    return (str(tool) if tool else "",
            str(command) if command is not None else None,
            str(path) if path is not None else None)


# ── CLI subcommands ───────────────────────────────────────────────────────────
def _rel_to_repo(p: str, repo_root: Path) -> str:
    """Best-effort repo-relative form of a path (for storing freeze_dir)."""
    cand = Path(p)
    if not cand.is_absolute():
        cand = Path.cwd() / cand
    try:
        return str(cand.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        # Outside the repo — store the resolved absolute path as a last resort.
        return str(cand.resolve())


def cmd_status(state_dir: Path) -> int:
    state = load_state(state_dir)
    careful = state.get("careful", False)
    freeze = state.get("freeze_dir") or None
    bmax = state.get("budget_max")
    if not careful and not freeze and not bmax:
        print("wf guard: OFF (no-op — all tool calls allowed).")
        return 0
    print("wf guard: ACTIVE")
    print(f"  careful    : {'on' if careful else 'off'}")
    print(f"  freeze_dir : {freeze if freeze else '(none)'}")
    if bmax:
        print(f"  budget     : {state.get('budget_count', 0)}/{bmax} tool calls used")
    else:
        print("  budget     : (off)")
    return 0


def cmd_careful(state_dir: Path, on: bool) -> int:
    state = load_state(state_dir)
    state["careful"] = on
    save_state(state_dir, state)
    print(f"wf guard: careful {'on' if on else 'off'}.")
    return 0


def cmd_freeze(state_dir: Path, dir_: str, repo_root: Path) -> int:
    rel = _rel_to_repo(dir_, repo_root)
    state = load_state(state_dir)
    state["freeze_dir"] = rel
    save_state(state_dir, state)
    print(f"wf guard: freeze set — edits restricted to '{rel}/'.")
    return 0


def cmd_unfreeze(state_dir: Path) -> int:
    state = load_state(state_dir)
    state["freeze_dir"] = None
    save_state(state_dir, state)
    print("wf guard: freeze cleared.")
    return 0


def cmd_on(state_dir: Path, repo_root: Path) -> int:
    rel = _rel_to_repo(str(Path.cwd()), repo_root)
    state = load_state(state_dir)  # preserve any active budget
    state["careful"] = True
    state["freeze_dir"] = rel
    save_state(state_dir, state)
    print(f"wf guard: ON — careful on + freeze restricted to '{rel}/'.")
    return 0


def cmd_off(state_dir: Path) -> int:
    save_state(state_dir, dict(DEFAULT_STATE))
    print("wf guard: OFF — careful off, freeze cleared.")
    return 0


def cmd_budget(state_dir: Path, value: str | None) -> int:
    """`wf guard budget <N>` sets a fresh tool-call ceiling (count reset to 0);
    `wf guard budget off` clears it. The resume path for a tripped breaker."""
    state = load_state(state_dir)
    if value in ("off", "0", "none", "clear"):
        state["budget_max"] = None
        state["budget_count"] = 0
        save_state(state_dir, state)
        print("wf guard: budget cleared (tool-call circuit-breaker off).")
        return 0
    try:
        n = int(value)
    except (TypeError, ValueError):
        sys.stderr.write("wf guard: 'budget' requires a positive integer or 'off'.\n")
        return 2
    if n < 1:
        sys.stderr.write("wf guard: budget must be >= 1 (or 'off').\n")
        return 2
    state["budget_max"] = n
    state["budget_count"] = 0
    save_state(state_dir, state)
    print(f"wf guard: budget set — circuit-breaker trips after {n} tool call(s). "
          f"Clear with `wf guard budget off`.")
    return 0


def cmd_check(state_dir: Path, tool: str, command: str | None,
              path: str | None, repo_root: Path) -> int:
    state = load_state(state_dir)
    # Budget circuit-breaker FIRST: count this call and block once the ceiling is
    # crossed. Persist the incremented count; a write failure fails OPEN (undercount,
    # never over-block).
    blocked, bmsg = budget_step(state)
    if isinstance(state.get("budget_max"), int) and state["budget_max"] > 0:
        try:
            save_state(state_dir, state)
        except Exception:  # noqa: BLE001 — fail open
            pass
    if blocked:
        sys.stderr.write((bmsg or "") + "\n")
        return 2
    code, msg = evaluate(state, tool, command, path, repo_root)
    if msg:
        sys.stderr.write(msg + "\n")
    return code


# ── Selftest ──────────────────────────────────────────────────────────────────
def selftest() -> int:
    problems: list[str] = []
    repo = _repo_root()

    # Destructive matcher: a battery of planted positive + negative cases.
    must_match = [
        "rm -rf /",
        "rm -fr ~",
        "rm -rf $HOME/stuff",
        "rm -rf *",
        "sudo rm -rf --no-preserve-root /",
        "git push --force origin main",
        "git push -f origin master",
        "git push --force-with-lease origin main",
        "git reset --hard HEAD~3",
        "psql -c 'DROP TABLE users;'",
        "mysql -e 'DROP DATABASE prod'",
        # TRUNCATE in a real DB-execution context (client / execute flag) → block.
        "sqlite3 db 'TRUNCATE TABLE orders;'",
        "psql -c 'TRUNCATE orders'",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
        "chmod -R 777 /",
        # ── FINDING 1 regression: evasions that previously SLIPPED PAST ───────
        'rm -rf "/"',                # quoted root
        "rm -rf /etc",               # any NON-root absolute path
        "rm -rf /home/user/important",
        "rm --recursive --force /",  # long flags
        "cat /dev/zero > /dev/sda",  # block-device write via redirect
        "> /dev/sda",                # bare redirect to a raw device
        "find / -delete",            # recursive find-delete
        "git push origin +main",     # force refspec via leading +
    ]
    must_not_match = [
        "rm -rf ./build",            # scoped relative subdir → safe
        "rm -rf node_modules",       # named dir, not broad → safe
        "ls -la",
        "git push origin feature/x",
        "echo hello",
        "python3 scripts/wf-guard.py --selftest",
        "git reset --soft HEAD~1",
        # ── FINDING 2 regression: SQL-DDL substrings OUTSIDE a DB context ─────
        'git commit -m "drop table talk in message"',  # commit message → safe
        "grep -r TRUNCATE src/",                        # grep target → safe
    ]
    for c in must_match:
        if match_destructive(c) is None:
            problems.append(f"destructive matcher MISSED: {c!r}")
    for c in must_not_match:
        hit = match_destructive(c)
        if hit is not None:
            problems.append(f"destructive matcher FALSE-POSITIVE on {c!r}: {hit}")

    with tempfile.TemporaryDirectory() as dd:
        sd = Path(dd) / ".wf"

        # 1. Fresh state (no file) → NO-OP: a dangerous command is allowed.
        code, _ = evaluate(load_state(sd), "Bash", "rm -rf /", None, repo)
        if code != 0:
            problems.append("1: fresh/empty state did not fail-open (no-op) for a "
                            "destructive command")

        # 2. careful ON → destructive command BLOCKED (exit 2).
        save_state(sd, {"careful": True, "freeze_dir": None})
        code, msg = evaluate(load_state(sd), "Bash", "rm -rf /", None, repo)
        if code != 2:
            problems.append("2: careful on did not BLOCK a destructive command")

        # 3. careful ON → a benign command still ALLOWED.
        code, _ = evaluate(load_state(sd), "Bash", "ls -la", None, repo)
        if code != 0:
            problems.append("3: careful on falsely blocked a benign command")

        # 4. careful OFF → same destructive command WARN-only (exit 0 + message).
        save_state(sd, {"careful": False, "freeze_dir": None})
        code, msg = evaluate(load_state(sd), "Bash", "rm -rf /", None, repo)
        if code != 0 or not (msg and "WARNING" in msg):
            problems.append("4: careful off did not warn-and-allow a destructive "
                            "command")

        # 5. Freeze blocks an Edit OUTSIDE freeze_dir, allows one INSIDE.
        with tempfile.TemporaryDirectory() as proj:
            proot = Path(proj)
            (proot / "allowed").mkdir()
            (proot / "elsewhere").mkdir()
            st = {"careful": False, "freeze_dir": "allowed"}
            # inside → allow
            code, _ = evaluate(st, "Edit", None,
                               str(proot / "allowed" / "a.py"), proot)
            if code != 0:
                problems.append("5a: freeze blocked an edit INSIDE the boundary")
            # outside → block
            code, msg = evaluate(st, "Write", None,
                                 str(proot / "elsewhere" / "b.py"), proot)
            if code != 2:
                problems.append("5b: freeze did not block an edit OUTSIDE the boundary")
            # MultiEdit outside → block
            code, _ = evaluate(st, "MultiEdit", None,
                               str(proot / "elsewhere" / "c.py"), proot)
            if code != 2:
                problems.append("5c: freeze did not block a MultiEdit outside boundary")
            # a near-miss sibling dir (allowedX) must NOT be treated as inside
            (proot / "allowedX").mkdir()
            code, _ = evaluate(st, "Edit", None,
                               str(proot / "allowedX" / "d.py"), proot)
            if code != 2:
                problems.append("5d: freeze treated a sibling near-miss dir as inside")
            # a Bash command is unaffected by freeze
            code, _ = evaluate(st, "Bash", "ls", None, proot)
            if code != 0:
                problems.append("5e: freeze wrongly affected a Bash command")

        # 6. FAIL-OPEN on malformed hook stdin.
        tool, cmd, pth = parse_hook_stdin("not json at all {{{")
        if (tool, cmd, pth) != ("", None, None):
            problems.append("6a: malformed stdin did not parse to empty/fail-open")
        # an empty tool → evaluate allows
        code, _ = evaluate({"careful": True, "freeze_dir": "x"}, "", None, None, repo)
        if code != 0:
            problems.append("6b: empty/missing tool did not fail-open (allow)")
        # well-formed stdin parses correctly
        tool, cmd, pth = parse_hook_stdin(
            '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}')
        if tool != "Bash" or cmd != "rm -rf /":
            problems.append("6c: well-formed stdin did not parse tool/command")

        # 7. Corrupt state file → fail-open to default (all-off).
        sd.mkdir(parents=True, exist_ok=True)
        (sd / STATE_FILE).write_text("{ corrupt json")
        st = load_state(sd)
        if st != DEFAULT_STATE:
            problems.append("7: corrupt state file did not fail-open to default")

        # 8. End-to-end exit-code regression for the two adversarial findings:
        #    careful ON → each Finding-1 evasion BLOCKS (exit 2); each Finding-2
        #    false-positive ALLOWS (exit 0). Exercises evaluate(), not just the
        #    matcher, so the hook decision path is covered.
        careful_on = {"careful": True, "freeze_dir": None}
        f1_evasions = [
            'rm -rf "/"', "rm -rf /etc", "rm -rf /home/user/important",
            "rm --recursive --force /", "cat /dev/zero > /dev/sda", "> /dev/sda",
            "find / -delete", "git push origin +main",
        ]
        for c in f1_evasions:
            code, _ = evaluate(careful_on, "Bash", c, None, repo)
            if code != 2:
                problems.append(f"8a: careful on did NOT block Finding-1 evasion {c!r} "
                                f"(exit {code}, expected 2)")
        f2_false_pos = [
            'git commit -m "drop table talk in message"',
            "grep -r TRUNCATE src/",
        ]
        for c in f2_false_pos:
            code, _ = evaluate(careful_on, "Bash", c, None, repo)
            if code != 0:
                problems.append(f"8b: careful on FALSELY blocked Finding-2 case {c!r} "
                                f"(exit {code}, expected 0)")
        # And a real DB drop in context still blocks (no new miss from scoping).
        code, _ = evaluate(careful_on, "Bash", "psql -c 'DROP TABLE users'", None, repo)
        if code != 2:
            problems.append("8c: careful on did NOT block a real DB DROP TABLE "
                            f"(exit {code}, expected 2)")

        # 9. BUDGET circuit-breaker (#21). budget_step: a ceiling of 2 allows the
        #    first 2 calls, blocks the 3rd (and after); no budget = no-op.
        bs = {"budget_max": 2, "budget_count": 0}
        r1 = budget_step(bs); r2 = budget_step(bs); r3 = budget_step(bs); r4 = budget_step(bs)
        if r1[0] or r2[0]:
            problems.append("9a: budget blocked within the ceiling")
        if not r3[0] or not r4[0]:
            problems.append("9b: budget did not block past the ceiling (no circuit-break)")
        if "circuit-breaker" not in (r3[1] or ""):
            problems.append("9c: budget block message missing the resume guidance")
        if budget_step({"budget_max": None, "budget_count": 5})[0]:
            problems.append("9d: an unset budget wrongly blocked (must be a no-op)")
        # cmd_check end-to-end through a temp state dir: set budget 1, first call
        # allows, second blocks; `budget off` resumes.
        bd = Path(dd) / "budget-wf"
        if cmd_budget(bd, "1") != 0:
            problems.append("9e: cmd_budget set failed")
        if cmd_check(bd, "Bash", "ls", None, repo) != 0:
            problems.append("9f: first call under budget 1 was blocked")
        if cmd_check(bd, "Bash", "ls", None, repo) != 2:
            problems.append("9g: second call over budget 1 was NOT blocked (exit != 2)")
        cmd_budget(bd, "off")
        if cmd_check(bd, "Bash", "ls", None, repo) != 0:
            problems.append("9h: `budget off` did not resume (call still blocked)")
        # the budget block is independent of careful/freeze (a benign Bash call,
        # careful off, still blocks once the ceiling is crossed).
        cmd_budget(bd, "1")
        cmd_check(bd, "Read", None, "x", repo)  # uses the 1 allowed call
        if cmd_check(bd, "Read", None, "x", repo) != 2:
            problems.append("9i: budget breaker did not apply to a non-Bash tool call")

    if problems:
        print("wf guard selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf guard selftest: PASS (destructive match+block under careful incl. "
          "Finding-1 evasions [quoted/non-root absolute rm -rf, long --recursive "
          "--force, /dev/sd* writes, find -delete, +ref force-push]; SQL DDL scoped "
          "to a DB-execution context so commit-msg/grep substrings are NOT flagged "
          "[Finding-2]; warn-only when off, benign always allowed, freeze blocks "
          "outside/allows inside, fail-open on malformed input & corrupt state; "
          "budget circuit-breaker allows up to the ceiling then blocks every call "
          "[any tool] until raised/cleared, no-op when unset)")
    return 0


# ── argparse / dispatch ───────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf guard", add_help=True)
    ap.add_argument("action", nargs="?",
                    choices=["status", "careful", "freeze", "unfreeze",
                             "on", "off", "check", "budget"])
    ap.add_argument("value", nargs="?",
                    help="careful: on|off ; freeze: <dir> ; budget: <N>|off")
    ap.add_argument("--tool", default=None, help="check: tool name")
    ap.add_argument("--command", default=None, help="check: shell command string")
    ap.add_argument("--path", default=None, help="check: target file path")
    ap.add_argument("--dir", default=None,
                    help="state dir (default: <repo>/.wf) — for tests")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("an action (status|careful|freeze|unfreeze|on|off|check) or "
                 "--selftest is required")

    repo_root = _repo_root()
    state_dir = _state_dir(args.dir)

    # FAIL-OPEN wrapper: `check` (the hook path) must never crash a tool call.
    if args.action == "check":
        try:
            if not args.tool:
                ap.error("'check' requires --tool")
            return cmd_check(state_dir, args.tool, args.command, args.path, repo_root)
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001 — fail OPEN, never block on a bug
            return 0

    if args.action == "status":
        return cmd_status(state_dir)
    if args.action == "careful":
        if args.value not in ("on", "off"):
            ap.error("'careful' requires on|off")
        return cmd_careful(state_dir, args.value == "on")
    if args.action == "freeze":
        if not args.value:
            ap.error("'freeze' requires a <dir> argument")
        return cmd_freeze(state_dir, args.value, repo_root)
    if args.action == "unfreeze":
        return cmd_unfreeze(state_dir)
    if args.action == "budget":
        if not args.value:
            ap.error("'budget' requires <N> or 'off'")
        return cmd_budget(state_dir, args.value)
    if args.action == "on":
        return cmd_on(state_dir, repo_root)
    # off
    return cmd_off(state_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
