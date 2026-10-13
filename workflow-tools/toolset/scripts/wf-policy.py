#!/usr/bin/env python3
"""wf-policy.py — per-skill-category POLICY OVERLAYS: the owned `core/` layer that
imposes OBLIGATIONS on the vendored skills WITHOUT editing them.

LOAD-BEARING DESIGN (do not blur it — see core/policy/policy-schema.md and CLAUDE.md):
  - The skills under .claude/skills/ are a pinned, MIT fork; we do NOT modify them.
    A policy overlay (core/policy/overlays/<id>.yaml) attaches declarative
    obligations to a CATEGORY of skills (e.g. ux/ui/design) and is SURFACED to the
    agent at skill-invocation time via `wf policy show <skill>` — never injected.
  - OUTSIDE HELP IS FIRST-CLASS. Any obligation that leans on a paid/external
    capability (the worked example: "use Claude to generate the design" — only
    available to Claude customers) MUST carry, in validated schema fields:
      (a) what the external help is (`name`),
      (b) that it is paid/gated + its availability (`availability`),
      (c) HOW TO CONNECT it (API key / subscription / MCP) as INSTRUCTIONS ONLY,
          never auto-connect (`how_to_connect`; CLAUDE.md working rule 2), and
      (d) a GRACEFUL FALLBACK that marks the requirement DEGRADED honestly, never
          silently skipped (`fallback`).
    `check` FAILS CLOSED if an overlay references external help without complete
    how_to_connect + fallback (+ name + availability).

This tool only READS. It never writes, never runs anything, and — by design —
NEVER connects any external help; it only surfaces the connect instructions.

Overlay schema (one file = one overlay; full contract in policy-schema.md):
  id            REQUIRED slug; must equal the filename stem
  title         REQUIRED human label
  applies_to    REQUIRED mapping with non-empty skill_globs and/or categories
    skill_globs   fnmatch globs over skill names; each MUST match >=1 real skill
    categories    free-form category tags the caller can target
  requirements  REQUIRED non-empty list of obligation strings
  external_help OPTIONAL list; when present every entry is REQUIRED-complete:
                  name, availability, how_to_connect, fallback (why is recommended)
  enforcement   OPTIONAL; only "instructions" is valid today (default)

Subcommands:
  list    list overlays (id, title, what they apply to).
  show    resolve which overlays apply to a skill/category and print the full
          obligations PLUS, prominently, any external_help (availability +
          how-to-connect + the DEGRADED fallback). "no policy applies" if none.
  check   validate every overlay; FAIL CLOSED (exit 1) on a malformed overlay, a
          glob matching NO real skill, or external help missing how_to_connect /
          fallback (or name / availability).

Exit codes: list/show -> 0.  check -> 0 ok / 1 violations / 2 config error.
            selftest -> 0 pass / 1 fail.  usage error -> 2.

Usage:
    wf policy list [--overlays DIR] [--skills DIR]
    wf policy show <skill-or-category> [--overlays DIR] [--skills DIR]
    wf policy check [--overlays DIR] [--skills DIR]
    wf policy --selftest
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from fnmatch import fnmatchcase
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml is a hard dependency here
    sys.stderr.write("wf policy: PyYAML is required (pip install pyyaml)\n")
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OVERLAYS = REPO_ROOT / "core" / "policy" / "overlays"
DEFAULT_SKILLS = REPO_ROOT / ".claude" / "skills"

VALID_ENFORCEMENT = ("instructions",)
# external_help fields that are REQUIRED whenever an obligation leans on outside help.
EXTERNAL_HELP_REQUIRED = ("name", "availability", "how_to_connect", "fallback")


def _die(msg: str, code: int = 2) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf policy: {msg}\n")
    raise SystemExit(code)


# --- loading ------------------------------------------------------------------

def _real_skills(skills_dir: Path) -> list[str]:
    """Skill names = immediate subdirectories of the skills root (each is a skill).

    Used to enforce the stale-glob rule: a skill_globs entry matching ZERO real
    skills is a dead overlay and fails closed."""
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if p.is_dir())


def _load_overlay(path: Path) -> dict:
    """Parse one overlay file. Raises on unreadable / non-mapping YAML."""
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ValueError(f"unreadable/invalid YAML: {e}")
    if obj is None or not isinstance(obj, dict):
        raise ValueError("overlay must be a YAML mapping")
    return obj


def _overlay_files(overlays_dir: Path) -> list[Path]:
    if not overlays_dir.is_dir():
        return []
    return sorted(p for p in overlays_dir.glob("*.yaml") if p.is_file())


# --- validation (fail-closed) -------------------------------------------------

def _validate_overlay(overlay: dict, stem: str, real_skills: list[str]) -> list[str]:
    """Structural + semantic validation; returns a list of problems (empty = ok).

    Enforces the stale-glob rule (a skill_glob must match a real skill) and the
    external-help completeness rule (paid/external help needs how_to_connect +
    fallback, plus name + availability)."""
    problems: list[str] = []

    oid = overlay.get("id")
    if not isinstance(oid, str) or not oid.strip():
        problems.append("missing/empty required field 'id'")
    elif oid != stem:
        problems.append(f"id {oid!r} must equal the filename stem {stem!r}")

    if not isinstance(overlay.get("title"), str) or not overlay["title"].strip():
        problems.append("missing/empty required field 'title'")

    applies = overlay.get("applies_to")
    globs: list = []
    cats: list = []
    if not isinstance(applies, dict):
        problems.append("missing required mapping 'applies_to'")
    else:
        globs = applies.get("skill_globs") or []
        cats = applies.get("categories") or []
        if not isinstance(globs, list):
            problems.append("applies_to.skill_globs must be a list")
            globs = []
        if not isinstance(cats, list):
            problems.append("applies_to.categories must be a list")
            cats = []
        if not globs and not cats:
            problems.append("applies_to must define a non-empty skill_globs or categories")
        for g in globs:
            if not isinstance(g, str) or not g.strip():
                problems.append(f"applies_to.skill_globs entry {g!r} must be a non-empty string")
                continue
            # STALE-GLOB RULE: a glob matching zero real skills is a dead overlay.
            if not fnmatch.filter(real_skills, g):
                problems.append(
                    f"applies_to.skill_globs {g!r} matches NO real skill under the "
                    f"skill catalog (stale/dead glob)"
                )
        for c in cats:
            if not isinstance(c, str) or not c.strip():
                problems.append(f"applies_to.categories entry {c!r} must be a non-empty string")

    reqs = overlay.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        problems.append("missing/empty required list 'requirements'")
    else:
        for r in reqs:
            if not isinstance(r, str) or not r.strip():
                problems.append(f"requirements entry {r!r} must be a non-empty string")

    helps = overlay.get("external_help")
    if helps is not None:
        if not isinstance(helps, list):
            problems.append("external_help must be a list")
        else:
            for i, h in enumerate(helps):
                if not isinstance(h, dict):
                    problems.append(f"external_help[{i}] must be a mapping")
                    continue
                name = h.get("name")
                label = name if isinstance(name, str) and name.strip() else f"#{i}"
                # THE LOAD-BEARING RULE: outside help must tell you how to connect
                # it AND how to degrade honestly without it — else FAIL CLOSED.
                for field in EXTERNAL_HELP_REQUIRED:
                    v = h.get(field)
                    if not isinstance(v, str) or not v.strip():
                        problems.append(
                            f"external_help[{label}] missing/empty required field "
                            f"'{field}' (paid/external help must declare "
                            f"name+availability+how_to_connect+fallback)"
                        )

    enf = overlay.get("enforcement")
    if enf is not None and enf not in VALID_ENFORCEMENT:
        problems.append(f"enforcement {enf!r} must be one of {'|'.join(VALID_ENFORCEMENT)}")

    return problems


# --- resolution (skill/category -> overlays) ----------------------------------

def _applies(overlay: dict, target: str) -> bool:
    """An overlay applies to `target` if any skill_glob fnmatches it (read as a
    skill name) OR any category equals it (read as a category)."""
    applies = overlay.get("applies_to") or {}
    for g in applies.get("skill_globs") or []:
        if isinstance(g, str) and fnmatchcase(target, g):
            return True
    for c in applies.get("categories") or []:
        if isinstance(c, str) and c == target:
            return True
    return False


def _applies_summary(overlay: dict) -> str:
    applies = overlay.get("applies_to") or {}
    globs = ", ".join(applies.get("skill_globs") or []) or "—"
    cats = ", ".join(applies.get("categories") or []) or "—"
    return f"skills[{globs}] categories[{cats}]"


# --- commands -----------------------------------------------------------------

def cmd_list(overlays_dir: Path, skills_dir: Path) -> int:
    files = _overlay_files(overlays_dir)
    if not files:
        print(f"No policy overlays in {overlays_dir} (nothing to list).")
        return 0
    print(f"Policy overlays ({len(files)}) in {overlays_dir}:")
    for path in files:
        try:
            ov = _load_overlay(path)
        except ValueError as e:
            print(f"  ! {path.name}: UNREADABLE — {e} (run `wf policy check`)")
            continue
        oid = ov.get("id", path.stem)
        title = ov.get("title", "(no title)")
        nreq = len(ov.get("requirements") or [])
        nhelp = len(ov.get("external_help") or [])
        print(f"  - {oid}: {title}")
        print(f"      applies to: {_applies_summary(ov)}")
        print(f"      {nreq} requirement(s)"
              + (f", {nhelp} external-help entr{'y' if nhelp == 1 else 'ies'} (paid/gated)" if nhelp else ""))
    print("\nGuardrail: overlays are OBLIGATIONS, not authorization. Connecting any")
    print("external help is a permissioned, instructed action the human approves.")
    return 0


def _print_overlay(ov: dict) -> None:
    print(f"  [{ov.get('id', '?')}] {ov.get('title', '')}")
    print(f"  applies to: {_applies_summary(ov)}")
    print("  Requirements (obligations you must honor):")
    for r in ov.get("requirements") or []:
        print(f"    - {r}")
    helps = ov.get("external_help") or []
    if helps:
        print("  OUTSIDE HELP (paid/gated — recommend & instruct, NEVER auto-connect):")
        for h in helps:
            print(f"    * {h.get('name', '(unnamed)')}")
            if h.get("why"):
                print(f"        why:           {h['why'].strip()}")
            print(f"        availability:  {str(h.get('availability', '')).strip()}")
            print(f"        how to connect:{_indent_block(h.get('how_to_connect', ''))}")
            print(f"        DEGRADED fallback:{_indent_block(h.get('fallback', ''))}")
    enf = ov.get("enforcement", "instructions")
    print(f"  enforcement: {enf}")


def _indent_block(text) -> str:
    """Render a (possibly multi-line) string indented under its label."""
    s = " ".join(str(text).split())  # collapse YAML-folded whitespace to one space
    return " " + s


def cmd_show(overlays_dir: Path, skills_dir: Path, target: str) -> int:
    target = target.strip()
    if not target:
        _die("show needs a skill name or category", code=2)
    files = _overlay_files(overlays_dir)
    applying: list[dict] = []
    for path in files:
        try:
            ov = _load_overlay(path)
        except ValueError:
            # A malformed overlay is surfaced by `check`; show stays read-only and
            # simply can't resolve it — it does not crash the query.
            continue
        if _applies(ov, target):
            applying.append(ov)
    if not applying:
        print(f"no policy applies to '{target}'.")
        print("(No governed-category obligations — proceed with the skill's own contract.)")
        return 0
    print(f"Policy for '{target}' — {len(applying)} overlay(s) apply:")
    print("Consult these BEFORE invoking the skill; honor each obligation, connect")
    print("any required outside help using the instructions below (never silently),")
    print("or mark that requirement DEGRADED honestly.\n")
    for ov in applying:
        _print_overlay(ov)
        print()
    return 0


def cmd_check(overlays_dir: Path, skills_dir: Path) -> int:
    real_skills = _real_skills(skills_dir)
    files = _overlay_files(overlays_dir)
    if not files:
        print(f"wf policy check: OK (no overlays in {overlays_dir} — nothing to validate)")
        return 0
    if not real_skills:
        _die(f"skill catalog {skills_dir} has no skills — cannot validate skill_globs", code=2)
    problems: list[str] = []
    seen_ids: dict[str, str] = {}
    for path in files:
        try:
            ov = _load_overlay(path)
        except ValueError as e:
            problems.append(f"{path.name}: {e}")
            continue
        for p in _validate_overlay(ov, path.stem, real_skills):
            problems.append(f"{path.name}: {p}")
        oid = ov.get("id")
        if isinstance(oid, str) and oid in seen_ids:
            problems.append(f"{path.name}: duplicate id {oid!r} (also in {seen_ids[oid]})")
        elif isinstance(oid, str):
            seen_ids[oid] = path.name
    if problems:
        sys.stderr.write("wf policy check: FAIL (%d violation%s)\n"
                         % (len(problems), "" if len(problems) == 1 else "s"))
        for p in problems:
            sys.stderr.write(f"  - {p}\n")
        return 1
    print(f"wf policy check: OK ({len(files)} overlay(s) valid; "
          f"globs match real skills; external help complete)")
    return 0


# --- selftest (planted fixtures, with teeth) ----------------------------------

def selftest() -> int:
    import io
    import contextlib
    import tempfile

    problems: list[str] = []

    def run(fn, *a) -> tuple[int, str]:
        buf = io.StringIO()
        err = io.StringIO()
        rc = 0
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            try:
                rc = fn(*a)
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 1
        return rc, buf.getvalue() + err.getvalue()

    with tempfile.TemporaryDirectory() as dd:
        d = Path(dd)
        skills = d / "skills"
        overlays = d / "overlays"
        skills.mkdir()
        overlays.mkdir()
        # a known UX skill the overlay will govern, and a benign one it will not.
        (skills / "demo-ux-designer").mkdir()
        (skills / "demo-agent-dev").mkdir()

        good = (
            "id: ux-fixture\n"
            "title: UX fixture overlay\n"
            "applies_to:\n"
            "  skill_globs: ['demo-ux-*']\n"
            "  categories: ['ux']\n"
            "requirements:\n"
            "  - 'Generate the design with Claude (artifact, not prose)'\n"
            "  - 'Ship a real mockup artifact'\n"
            "external_help:\n"
            "  - name: 'Claude design generation'\n"
            "    why: 'the first obligation needs Claude access'\n"
            "    availability: 'Paid — requires Claude access (API key or subscription)'\n"
            "    how_to_connect: 'Set ANTHROPIC_API_KEY from https://console.anthropic.com/ "
            "(recommend, never auto-connect)'\n"
            "    fallback: 'If unavailable, hand-author the mockup and mark the requirement DEGRADED'\n"
            "enforcement: instructions\n"
        )
        (overlays / "ux-fixture.yaml").write_text(good)

        # 1. check PASSES on the good fixture overlay.
        rc, out = run(cmd_check, overlays, skills)
        if rc != 0 or "OK" not in out:
            problems.append(f"1: check failed on a valid overlay (rc={rc}, out={out!r})")

        # 2. show on the governed UX skill surfaces the REQUIREMENTS + the external
        #    help connect-instructions + the DEGRADED fallback.
        rc, out = run(cmd_show, overlays, skills, "demo-ux-designer")
        if rc != 0:
            problems.append(f"2: show on governed skill exited {rc}")
        if "ux-fixture" not in out or "Ship a real mockup" not in out:
            problems.append("2: show did not surface the requirements")
        if "ANTHROPIC_API_KEY" not in out or "console.anthropic.com" not in out:
            problems.append("2: show did not surface the how-to-connect instructions")
        if "Paid" not in out:
            problems.append("2: show did not surface the paid/gated availability")
        if "DEGRADED" not in out:
            problems.append("2: show did not surface the DEGRADED fallback")
        if "never" not in out.lower() and "auto-connect" not in out.lower():
            problems.append("2: show did not warn against auto-connecting")

        # 2b. resolution also works by CATEGORY, not just skill name.
        rc, out = run(cmd_show, overlays, skills, "ux")
        if "ux-fixture" not in out:
            problems.append("2b: show by category did not resolve the overlay")

        # 3. a benign skill with no overlay yields "no policy applies".
        rc, out = run(cmd_show, overlays, skills, "demo-agent-dev")
        if rc != 0 or "no policy applies" not in out:
            problems.append(f"3: benign skill did not yield 'no policy applies' (out={out!r})")

        # 4. check FAILS CLOSED on a MALFORMED overlay (not valid YAML mapping).
        bad_dir = d / "bad-malformed"
        bad_dir.mkdir()
        (bad_dir / "broken.yaml").write_text("id: broken\ntitle: x\n: : : not a mapping\n")
        rc, out = run(cmd_check, bad_dir, skills)
        if rc != 1:
            problems.append(f"4: check did not fail-closed (rc=1) on malformed overlay (rc={rc})")

        # 5. check FAILS CLOSED on a glob matching NO real skill (stale/dead glob).
        stale_dir = d / "bad-stale-glob"
        stale_dir.mkdir()
        (stale_dir / "stale.yaml").write_text(
            "id: stale\ntitle: Stale glob overlay\n"
            "applies_to:\n  skill_globs: ['no-such-skill-zzz-*']\n"
            "requirements:\n  - 'do a thing'\n"
        )
        rc, out = run(cmd_check, stale_dir, skills)
        if rc != 1 or "stale" not in out.lower() and "matches NO real skill" not in out:
            problems.append(f"5: check did not fail-closed on a glob matching no skill (rc={rc}, out={out!r})")

        # 6a. check FAILS CLOSED on external help missing how_to_connect.
        nohow_dir = d / "bad-no-howto"
        nohow_dir.mkdir()
        (nohow_dir / "nohow.yaml").write_text(
            "id: nohow\ntitle: Missing how_to_connect\n"
            "applies_to:\n  skill_globs: ['demo-ux-*']\n"
            "requirements:\n  - 'use Claude'\n"
            "external_help:\n"
            "  - name: 'Claude'\n    availability: 'Paid'\n"
            "    fallback: 'degrade and mark DEGRADED'\n"  # how_to_connect MISSING
        )
        rc, out = run(cmd_check, nohow_dir, skills)
        if rc != 1 or "how_to_connect" not in out:
            problems.append(f"6a: check did not fail-closed on missing how_to_connect (rc={rc}, out={out!r})")

        # 6b. check FAILS CLOSED on external help missing fallback.
        nofb_dir = d / "bad-no-fallback"
        nofb_dir.mkdir()
        (nofb_dir / "nofb.yaml").write_text(
            "id: nofb\ntitle: Missing fallback\n"
            "applies_to:\n  skill_globs: ['demo-ux-*']\n"
            "requirements:\n  - 'use Claude'\n"
            "external_help:\n"
            "  - name: 'Claude'\n    availability: 'Paid'\n"
            "    how_to_connect: 'set ANTHROPIC_API_KEY'\n"  # fallback MISSING
        )
        rc, out = run(cmd_check, nofb_dir, skills)
        if rc != 1 or "fallback" not in out:
            problems.append(f"6b: check did not fail-closed on missing fallback (rc={rc}, out={out!r})")

        # 7. list works on the good overlay dir.
        rc, out = run(cmd_list, overlays, skills)
        if rc != 0 or "ux-fixture" not in out:
            problems.append(f"7: list did not show the fixture overlay (out={out!r})")

    if problems:
        print("wf policy selftest: FAIL — " + "; ".join(problems))
        return 1
    print("wf policy selftest: PASS (check passes valid overlay; show surfaces "
          "requirements + paid availability + how-to-connect + DEGRADED fallback "
          "+ no-auto-connect warning; resolves by skill AND category; benign skill "
          "-> no policy; check FAILS CLOSED on malformed, stale glob, and external "
          "help missing how_to_connect/fallback)")
    return 0


# --- entrypoint ---------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="wf policy", add_help=True)
    ap.add_argument("--selftest", action="store_true",
                    help="run the planted-fixture selftest and exit")
    sub = ap.add_subparsers(dest="action")

    def _add_dirs(p):
        p.add_argument("--overlays", default=None,
                       help="overlay dir (default: core/policy/overlays)")
        p.add_argument("--skills", default=None,
                       help="skill catalog dir (default: .claude/skills)")

    _add_dirs(sub.add_parser("list", help="list overlays"))
    p_show = sub.add_parser("show", help="resolve + print the policy for a skill/category")
    p_show.add_argument("target", help="skill name or category")
    _add_dirs(p_show)
    _add_dirs(sub.add_parser("check", help="validate overlays; fail-closed"))

    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("an action (list|show|check) or --selftest is required")

    overlays_dir = Path(args.overlays) if getattr(args, "overlays", None) else DEFAULT_OVERLAYS
    skills_dir = Path(args.skills) if getattr(args, "skills", None) else DEFAULT_SKILLS

    if args.action == "list":
        return cmd_list(overlays_dir, skills_dir)
    if args.action == "show":
        return cmd_show(overlays_dir, skills_dir, args.target)
    if args.action == "check":
        return cmd_check(overlays_dir, skills_dir)
    ap.error(f"unknown action {args.action!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
