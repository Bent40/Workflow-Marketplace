#!/usr/bin/env python3
"""wf-lock.py — repo-local concurrency-lease registry: claim a module (or a
contended shared file) before editing so parallel workers — multiple agents,
multiple sessions, or a solo dev on parallel branches — do not edit the same
subtree concurrently or cause merge collisions. The lease surface behind the
`collab.shared_file_lock` rule.

Granularity is the MODULE by default (a path-glob subtree); cross-cutting shared
files (manifests, migrations, central routers, base schemas) take their own
narrow exact-path claims so a one-line dependency bump never locks a whole
module. This tool only records and compares leases — it never edits code, never
touches git, never computes a trust boundary. The lease is advisory: it surfaces
only on a detected overlap, so a single worker sees no friction.

Registry: JSON at <dir>/leases.json (default <repo>/.bmad/locks; override with
--dir for tests). Each lease: {glob, worker, note, ts}. The dir/file are created
lazily on the first write.

Overlap model (deterministic, dependency-free — NOT a full glob engine):
  - Normalize a claim to a path PREFIX: strip a trailing `/**` or `/*`. A claim
    with no wildcard is an EXACT path (a shared-file claim).
  - Compare by PATH SEGMENT (split on `/`), never raw string prefix, so `src/a`
    does NOT match `src/ab`.
  - Two claims CONFLICT when one normalized prefix is a path-prefix of the other
    (module containment), OR they are the same exact path. Sibling sub-trees
    (`src/a/**` vs `src/b/**`) never conflict. A module claim conflicts with a
    file claim inside it. A shared-file claim conflicts only with another claim
    covering that same path.
  - A claim NEVER conflicts with another claim by the SAME worker (re-claim is
    idempotent).

  list                  — print active leases.
  claim <glob> --worker — record a lease unless a DIFFERENT worker holds an
                          overlapping one (then print it and exit 1, no write).
  release <glob> --worker / release --all --worker — drop the worker's matching
                          (or all) leases.
  check <glob>          — exit 1 + list overlaps if ANY live claim overlaps.

Exit codes: claim → 0 ok / 1 conflict. check → 0 clear / 1 overlap.
            release/list → 0. selftest → 0 pass / 1 fail. usage error → 2.

Usage:
    wf lock claim <glob> --worker <id> [--note <text>] [--dir PATH]
    wf lock release (<glob> | --all) --worker <id> [--dir PATH]
    wf lock check <glob> [--dir PATH]
    wf lock list [--dir PATH]
    wf lock --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

LEASES_FILE = "leases.json"


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf lock: {msg}\n")
    raise SystemExit(code)


def _default_dir() -> Path:
    """<repo>/.bmad/locks — repo root is this script's parent's parent."""
    return Path(__file__).resolve().parent.parent / ".bmad" / "locks"


def _norm(claim: str) -> tuple[str, ...]:
    """Normalize a claim to a tuple of path segments (its prefix). Strips a
    trailing `/**` or `/*`, then splits on `/` dropping empty segments. A claim
    with no wildcard yields the exact path's segments."""
    c = claim.strip().strip("/")
    if c.endswith("/**"):
        c = c[:-3]
    elif c.endswith("/*"):
        c = c[:-2]
    elif c == "**" or c == "*":
        c = ""
    return tuple(seg for seg in c.split("/") if seg)


def _is_wildcard(claim: str) -> bool:
    c = claim.strip().strip("/")
    return c.endswith(("/**", "/*")) or c in ("**", "*")


def _conflicts(a: str, b: str) -> bool:
    """True when claims a and b overlap under the module-containment model.

    One normalized prefix is a path-prefix of the other (by segment), OR they
    are the same exact path. A bare `**`/`*` (empty prefix) contains everything.
    A non-wildcard claim that equals a wildcard's prefix is a file-inside-module
    and conflicts; two distinct exact paths only conflict if one's segments are
    a prefix of the other (which, for files, means equality or nesting)."""
    pa, pb = _norm(a), _norm(b)
    n = min(len(pa), len(pb))
    if pa[:n] != pb[:n]:
        return False  # diverge before either ends — sibling subtrees
    # one prefix is a (segment) prefix of the other → containment / equality
    return True


def load_leases(reg_dir: Path) -> list[dict]:
    path = reg_dir / LEASES_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text() or "[]")
    except (json.JSONDecodeError, OSError) as e:
        _die(f"corrupt registry {path}: {e}")
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        _die(f"corrupt registry {path}: expected a JSON list of leases")
    return data


def save_leases(reg_dir: Path, leases: list[dict]) -> None:
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / LEASES_FILE).write_text(json.dumps(leases, indent=2) + "\n")


def overlaps(leases: list[dict], glob: str, *, exclude_worker: str | None = None) -> list[dict]:
    """Live leases overlapping `glob`, optionally excluding one worker (so a
    re-claim by the same worker is not a self-conflict)."""
    out = []
    for lease in leases:
        if exclude_worker is not None and lease.get("worker") == exclude_worker:
            continue
        if _conflicts(glob, lease.get("glob", "")):
            out.append(lease)
    return out


def _fmt(lease: dict) -> str:
    g = lease.get("glob", "?")
    w = lease.get("worker", "?")
    note = lease.get("note") or ""
    ts = lease.get("ts", "")
    tail = f"  note={note!r}" if note else ""
    return f"{g}  worker={w}  ts={ts}{tail}"


def cmd_claim(reg_dir: Path, glob: str, worker: str, note: str | None) -> int:
    leases = load_leases(reg_dir)
    conflict = overlaps(leases, glob, exclude_worker=worker)
    if conflict:
        sys.stderr.write(
            f"wf lock: claim {glob!r} blocked — overlapping live claim(s) by "
            f"another worker:\n")
        for c in conflict:
            sys.stderr.write(f"  {_fmt(c)}\n")
        return 1
    # idempotent re-claim: same worker + same glob already present → no dup
    for lease in leases:
        if lease.get("worker") == worker and lease.get("glob") == glob:
            print(f"already held: {_fmt(lease)}")
            return 0
    leases.append({
        "glob": glob,
        "worker": worker,
        "note": note or "",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    save_leases(reg_dir, leases)
    print(f"claimed: {glob}  worker={worker}")
    return 0


def cmd_release(reg_dir: Path, glob: str | None, worker: str, all_: bool) -> int:
    leases = load_leases(reg_dir)
    if all_:
        kept = [l for l in leases if l.get("worker") != worker]
    else:
        kept = [l for l in leases
                if not (l.get("worker") == worker and l.get("glob") == glob)]
    removed = len(leases) - len(kept)
    if removed:
        save_leases(reg_dir, kept)
    target = "all leases" if all_ else repr(glob)
    print(f"released {removed} lease(s) for worker={worker} ({target}).")
    return 0


def cmd_check(reg_dir: Path, glob: str) -> int:
    leases = load_leases(reg_dir)
    hits = overlaps(leases, glob)
    if hits:
        print(f"OVERLAP: {glob} overlaps {len(hits)} live claim(s):")
        for h in hits:
            print(f"  {_fmt(h)}")
        return 1
    print(f"clear: {glob} overlaps no live claim.")
    return 0


def cmd_list(reg_dir: Path) -> int:
    leases = load_leases(reg_dir)
    if not leases:
        print("no active leases.")
        return 0
    print(f"active leases ({len(leases)}):")
    for lease in leases:
        print(f"- {_fmt(lease)}")
    return 0


def selftest() -> int:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as dd:
        reg = Path(dd) / "locks"

        # 1. claim succeeds on empty registry
        if cmd_claim(reg, "src/auth/**", "w1", None) != 0:
            problems.append("1: first claim on empty registry did not succeed")

        # 2. a second claim on the SAME module by a different worker is rejected,
        #    registry unchanged
        before = (reg / LEASES_FILE).read_text()
        if cmd_claim(reg, "src/auth/**", "w2", None) != 1:
            problems.append("2: same-module claim by another worker was not rejected")
        if (reg / LEASES_FILE).read_text() != before:
            problems.append("2: rejected claim mutated the registry (not fail-closed)")

        # 3. sibling sub-tree claim by a different worker SUCCEEDS
        if cmd_claim(reg, "src/billing/**", "w2", None) != 0:
            problems.append("3: sibling subtree was falsely blocked")

        # 4. a file claim INSIDE a claimed module by a different worker is rejected
        if cmd_claim(reg, "src/auth/login.py", "w3", None) != 1:
            problems.append("4: file inside a claimed module was not rejected")

        # 5. a shared-file claim does not block a disjoint module, but blocks a
        #    second claim of the same file
        if cmd_claim(reg, "package.json", "w4", None) != 0:
            problems.append("5a: shared-file claim on free path did not succeed")
        if cmd_claim(reg, "src/api/**", "w5", None) != 0:
            problems.append("5b: disjoint module was blocked by a shared-file claim")
        if cmd_claim(reg, "package.json", "w6", None) != 1:
            problems.append("5c: second package.json claim was not blocked")

        # 6. re-claim by the SAME worker is idempotent
        n_before = len(load_leases(reg))
        if cmd_claim(reg, "src/auth/**", "w1", None) != 0:
            problems.append("6: re-claim by same worker was not idempotent (exit)")
        if len(load_leases(reg)) != n_before:
            problems.append("6: re-claim by same worker duplicated the lease")

        # 7. release clears the lease so a previously-blocked worker can claim
        cmd_release(reg, "src/auth/**", "w1", all_=False)
        if cmd_check(reg, "src/auth/**") != 0:
            problems.append("7a: release did not clear the auth lease")
        if cmd_claim(reg, "src/auth/**", "w2", None) != 0:
            problems.append("7b: previously-blocked worker could not claim after release")

        # 8. check mirrors claim's conflict decision across a battery of cases
        with tempfile.TemporaryDirectory() as dd2:
            reg2 = Path(dd2) / "locks"
            cmd_claim(reg2, "src/auth/**", "h1", None)
            cmd_claim(reg2, "shared/config.yaml", "h1", None)
            cases = [
                ("src/auth/sub/**", True),    # nested under module → overlap
                ("src/auth/login.py", True),  # file inside module → overlap
                ("src/authz/**", False),      # segment-distinct sibling → clear
                ("src/billing/**", False),    # disjoint → clear
                ("shared/config.yaml", True), # same exact shared file → overlap
                ("shared/configy.yaml", False),  # near-miss filename → clear
                ("src/**", True),             # parent module contains auth → overlap
            ]
            for glob, expect_conflict in cases:
                claim_blocked = (overlaps(load_leases(reg2), glob,
                                          exclude_worker="other") != [])
                check_overlap = (cmd_check(reg2, glob) == 1)
                if claim_blocked != expect_conflict:
                    problems.append(f"8: conflict decision wrong for {glob!r} "
                                    f"(got {claim_blocked}, want {expect_conflict})")
                if check_overlap != claim_blocked:
                    problems.append(f"8: check disagrees with claim for {glob!r}")

    if problems:
        print("wf lock selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf lock selftest: PASS (claim/reject/sibling/file-in-module, "
          "shared-file carve-out, idempotent re-claim, release-then-claim, "
          "check mirrors claim)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf lock")
    ap.add_argument("action", nargs="?",
                    choices=["claim", "release", "check", "list"])
    ap.add_argument("glob", nargs="?", help="path-glob module or exact file claim")
    ap.add_argument("--worker", default=None, help="worker/lease owner id")
    ap.add_argument("--note", default=None, help="claim: optional note")
    ap.add_argument("--all", action="store_true",
                    help="release: drop all leases owned by --worker")
    ap.add_argument("--dir", default=None,
                    help="registry dir (default: <repo>/.bmad/locks)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("an action (claim|release|check|list) or --selftest is required")

    reg_dir = Path(args.dir) if args.dir else _default_dir()

    if args.action == "list":
        return cmd_list(reg_dir)

    if args.action == "check":
        if not args.glob:
            ap.error("'check' requires a <glob> argument")
        return cmd_check(reg_dir, args.glob)

    if args.action == "claim":
        if not args.glob:
            ap.error("'claim' requires a <glob> argument")
        if not args.worker:
            ap.error("'claim' requires --worker")
        return cmd_claim(reg_dir, args.glob, args.worker, args.note)

    # release
    if not args.worker:
        ap.error("'release' requires --worker")
    if args.all:
        return cmd_release(reg_dir, None, args.worker, all_=True)
    if not args.glob:
        ap.error("'release' requires a <glob> argument or --all")
    return cmd_release(reg_dir, args.glob, args.worker, all_=False)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
