#!/usr/bin/env python3
"""generate-adapters.py — cross-agent adapter prototype (Phase 1–4A.5 + Gemini).

Renders the universal rule files in core/rules/*.yaml into per-(profile, target)
instruction files under adapters/<profile>/<target>/. A deliberately narrow
PROOF of the architecture:

    core rules
      -> selected by PROFILE (core/profiles/*.yaml, by activation level)
      -> AND by TARGET applicability (rule.applies_to)
      -> AND by TARGET CAPABILITY (rule.requires_capabilities vs the target's
         capabilities in core/targets/*.yaml)
      -> rendered into the target's expected file shape
      -> generated files under adapters/<profile>/<target>/
      -> validated by drift + stale detection (--check / wf-doctor)

It is NOT the full rule corpus or a finished compiler.

Usage:
    scripts/generate-adapters.py            # write generated files
    scripts/generate-adapters.py --check    # verify on-disk files are in sync
                                            # (exit 1 on drift/stale; for doctor/CI)

Three selection axes:
  * TARGET applicability — `applies_to` lists the targets a rule is meant for.
  * PROFILE              — a rule's `activation` vs a profile's includes_activations.
  * CAPABILITY           — a rule's `requires_capabilities` must be satisfied by
                           the target's capabilities, so no target receives an
                           instruction for a mechanism it lacks (e.g. subagents).
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment without pyyaml
    sys.stderr.write(
        "generate-adapters: PyYAML not available; cannot parse core/ YAML\n"
    )
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / "core" / "rules"
PROFILES_DIR = REPO_ROOT / "core" / "profiles"
TARGETS_DIR = REPO_ROOT / "core" / "targets"
MODES_DIR = REPO_ROOT / "core" / "modes"
ROLES_DIR = REPO_ROOT / "core" / "roles"
PATHGROUPS_FILE = REPO_ROOT / "core" / "path-groups.yaml"
ADAPTERS_DIR = REPO_ROOT / "adapters"

SENTINEL = "GENERATED FILE — do not edit by hand."
BANNER = (
    f"{SENTINEL}\n"
    "Source of truth: core/rules/*.yaml + core/profiles/*.yaml + "
    "core/targets/*.yaml. Regenerate with scripts/generate-adapters.py."
)

RULE_FIELDS = ("id", "scope", "severity", "activation", "applies_to",
               "summary", "short_form", "full_text")
PROFILE_FIELDS = ("id", "summary", "includes_activations")
TARGET_FIELDS = ("id", "summary", "capabilities")
MODE_FIELDS = ("id", "summary")
ROLE_FIELDS = ("id", "summary", "activation", "applies_to", "applicable_modes",
               "render")

# The `team` and `secure` activations (and their profiles) were removed
# 2026-10-13 (core/DECISIONS.md D6); every rule/role is `default` now. The field
# and the profile selection axis stay so a future opt-in posture can re-add one.
KNOWN_ACTIVATIONS = ("default",)
KNOWN_SEVERITIES = ("critical", "high", "medium", "low")
# Fixed path-group vocabulary (RD-2). A rule's path_group, and every group
# defined in core/path-groups.yaml, must be one of these.
KNOWN_PATH_GROUPS = ("backend", "frontend", "tests", "security", "docs")
KNOWN_CAPABILITIES = ("subagents", "bmad_skills", "hooks", "mcp", "repo_editing",
                      "agents_md", "repo_guidance", "github_native",
                      "path_instructions", "context_file", "small_context",
                      "microtasks")
SEVERITY_RANK = {s: i for i, s in enumerate(KNOWN_SEVERITIES)}
ACTIVATION_RANK = {a: i for i, a in enumerate(KNOWN_ACTIVATIONS)}


def _die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    raise SystemExit(f"generate-adapters: {msg}")


def _load_yaml(path: Path):
    """Parse a YAML file, turning a parse error into a clean fail-closed message
    (with the offending file) instead of an opaque traceback."""
    try:
        with path.open() as fh:
            return yaml.safe_load(fh)
    except yaml.YAMLError as e:
        _die(f"{path.name}: invalid YAML: {e}")


# --- loading + schema validation ----------------------------------------------

def load_targets() -> dict[str, set[str]]:
    """Load target capability manifests -> {id: set(capabilities)}.

    The set of valid targets is derived from these manifests (single source of
    truth), so a rule's applies_to is validated against what actually exists."""
    targets: dict[str, set[str]] = {}
    for path in sorted(TARGETS_DIR.glob("*.yaml")):
        t = _load_yaml(path)
        if not isinstance(t, dict):
            _die(f"{path.name}: not a YAML mapping")
        missing = [f for f in TARGET_FIELDS if f not in t]
        if missing:
            _die(f"{path.name}: missing required field(s): {', '.join(missing)}")
        if path.stem != t["id"]:
            _die(f"{path.name}: filename stem '{path.stem}' must match id '{t['id']}'")
        caps = t["capabilities"]
        if not isinstance(caps, list) or not caps:
            _die(f"{path.name}: capabilities must be a non-empty list")
        unknown = [c for c in caps if c not in KNOWN_CAPABILITIES]
        if unknown:
            _die(f"{path.name}: unknown capability(ies): {', '.join(unknown)} "
                 f"(known: {', '.join(KNOWN_CAPABILITIES)})")
        targets[t["id"]] = set(caps)
    if not targets:
        _die("no target manifests found in core/targets/")
    return targets


def load_path_groups() -> dict[str, dict]:
    """Load core/path-groups.yaml -> {group: {summary, paths}}.

    The single source of the applyTo globs for path-scoped output (RD-2). Group
    names are a FIXED vocabulary; anything else fails closed."""
    if not PATHGROUPS_FILE.exists():
        _die("core/path-groups.yaml not found (required for path-scoped output)")
    data = _load_yaml(PATHGROUPS_FILE)
    if not isinstance(data, dict) or not isinstance(data.get("groups"), dict) \
            or not data["groups"]:
        _die("path-groups.yaml: must be a mapping with a non-empty 'groups' map")
    groups: dict[str, dict] = {}
    for name, spec in data["groups"].items():
        if name not in KNOWN_PATH_GROUPS:
            _die(f"path-groups.yaml: unknown group '{name}' (fixed vocabulary: "
                 f"{', '.join(KNOWN_PATH_GROUPS)})")
        if not isinstance(spec, dict):
            _die(f"path-groups.yaml: group '{name}' must be a mapping")
        paths = spec.get("paths")
        if not isinstance(paths, list) or not paths or \
                not all(isinstance(p, str) and p.strip() for p in paths):
            _die(f"path-groups.yaml: group '{name}' needs a non-empty list of "
                 f"path globs (non-empty strings)")
        groups[name] = {"summary": str(spec.get("summary", "")).strip(),
                        "paths": paths}
    return groups


def load_rules(known_targets: set[str],
               known_groups: set[str] | None = None) -> list[dict]:
    """Load, validate, and deterministically order every rule file."""
    rules: list[dict] = []
    seen_ids: dict[str, str] = {}
    for path in sorted(RULES_DIR.glob("*.yaml")):
        rule = _load_yaml(path)
        if not isinstance(rule, dict):
            _die(f"{path.name}: not a YAML mapping")
        missing = [f for f in RULE_FIELDS if f not in rule]
        if missing:
            _die(f"{path.name}: missing required field(s): {', '.join(missing)}")
        rid = rule["id"]
        if path.stem != rid:
            _die(f"{path.name}: filename stem '{path.stem}' must match id '{rid}'")
        if rid in seen_ids:
            _die(f"duplicate rule id '{rid}' in {seen_ids[rid]} and {path.name}")
        seen_ids[rid] = path.name
        if rule["severity"] not in KNOWN_SEVERITIES:
            _die(f"{path.name}: unknown severity '{rule['severity']}' "
                 f"(known: {', '.join(KNOWN_SEVERITIES)})")
        if rule["activation"] not in KNOWN_ACTIVATIONS:
            _die(f"{path.name}: unknown activation '{rule['activation']}' "
                 f"(known: {', '.join(KNOWN_ACTIVATIONS)})")
        if not isinstance(rule["applies_to"], list) or not rule["applies_to"]:
            _die(f"{path.name}: applies_to must be a non-empty list")
        unknown_targets = [t for t in rule["applies_to"] if t not in known_targets]
        if unknown_targets:
            _die(f"{path.name}: unknown target(s) in applies_to: "
                 f"{', '.join(unknown_targets)} (known: {', '.join(sorted(known_targets))})")
        reqs = rule.get("requires_capabilities", []) or []
        if not isinstance(reqs, list):
            _die(f"{path.name}: requires_capabilities must be a list")
        unknown_caps = [c for c in reqs if c not in KNOWN_CAPABILITIES]
        if unknown_caps:
            _die(f"{path.name}: unknown required capability(ies): "
                 f"{', '.join(unknown_caps)} (known: {', '.join(KNOWN_CAPABILITIES)})")
        rule["requires_capabilities"] = reqs
        # Optional path_group: routes the rule out of the repo-wide file into a
        # path-scoped surface (Copilot today). Must be a defined group.
        pg = rule.get("path_group")
        if pg is not None:
            if known_groups is None:
                _die(f"{path.name}: path_group set but no path-groups loaded")
            if not isinstance(pg, str) or pg not in known_groups:
                _die(f"{path.name}: path_group '{pg}' is not defined in "
                     f"core/path-groups.yaml (known: {', '.join(sorted(known_groups))})")
        rule["path_group"] = pg
        # Optional review_note: reviewer-framed "what to look for" text that
        # renders into the path-scoped REVIEW surface. Requires a path_group
        # (the review file is path-scoped, like the authoring one).
        rn = rule.get("review_note")
        if rn is not None:
            if not isinstance(rn, str) or not rn.strip():
                _die(f"{path.name}: review_note must be a non-empty string")
            if pg is None:
                _die(f"{path.name}: review_note requires a path_group")
        rule["review_note"] = rn
        # A rule that renders into no (profile, target) output is an error UNLESS
        # explicitly marked allow_unrendered, which then requires a reason.
        allow_unrendered = rule.get("allow_unrendered", False)
        if not isinstance(allow_unrendered, bool):
            _die(f"{path.name}: allow_unrendered must be true/false")
        if allow_unrendered and not str(rule.get("reason", "")).strip():
            _die(f"{path.name}: allow_unrendered: true requires a non-empty 'reason'")
        rule["allow_unrendered"] = allow_unrendered
        rules.append(rule)
    rules.sort(key=lambda r: (SEVERITY_RANK[r["severity"]],
                              ACTIVATION_RANK[r["activation"]], r["id"]))
    return rules


def load_profiles() -> list[dict]:
    """Load and validate every profile manifest, sorted by id."""
    profiles: list[dict] = []
    seen_ids: dict[str, str] = {}
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        prof = _load_yaml(path)
        if not isinstance(prof, dict):
            _die(f"{path.name}: not a YAML mapping")
        missing = [f for f in PROFILE_FIELDS if f not in prof]
        if missing:
            _die(f"{path.name}: missing required field(s): {', '.join(missing)}")
        pid = prof["id"]
        if path.stem != pid:
            _die(f"{path.name}: filename stem '{path.stem}' must match id '{pid}'")
        if pid in seen_ids:
            _die(f"duplicate profile id '{pid}' in {seen_ids[pid]} and {path.name}")
        seen_ids[pid] = path.name
        acts = prof.get("includes_activations")
        if not isinstance(acts, list) or not acts:
            _die(f"{path.name}: includes_activations must be a non-empty list")
        unknown_acts = [a for a in acts if a not in KNOWN_ACTIVATIONS]
        if unknown_acts:
            _die(f"{path.name}: unknown activation(s) in includes_activations: "
                 f"{', '.join(unknown_acts)} (known: {', '.join(KNOWN_ACTIVATIONS)})")
        prof.setdefault("render_note", None)
        prof.setdefault("allow_empty", False)
        prof.setdefault("compact", False)
        if not isinstance(prof["compact"], bool):
            _die(f"{path.name}: 'compact' must be true/false")
        profiles.append(prof)
    profiles.sort(key=lambda p: p["id"])
    return profiles


def load_modes() -> list[dict]:
    """Load + validate the mode contracts (core/modes/*.yaml), sorted by id.
    `may`/`may_not`/`must` are optional lists of action tokens."""
    modes: list[dict] = []
    seen: dict[str, str] = {}
    for path in sorted(MODES_DIR.glob("*.yaml")):
        m = _load_yaml(path)
        if not isinstance(m, dict):
            _die(f"{path.name}: not a YAML mapping")
        missing = [f for f in MODE_FIELDS if f not in m]
        if missing:
            _die(f"{path.name}: missing required field(s): {', '.join(missing)}")
        mid = m["id"]
        if path.stem != mid:
            _die(f"{path.name}: filename stem '{path.stem}' must match id '{mid}'")
        if mid in seen:
            _die(f"duplicate mode id '{mid}' in {seen[mid]} and {path.name}")
        seen[mid] = path.name
        if not str(m["summary"]).strip():
            _die(f"{path.name}: summary must be a non-empty string")
        for key in ("may", "may_not", "must"):
            val = m.get(key, []) or []
            if not isinstance(val, list) or not all(isinstance(x, str) and x.strip()
                                                    for x in val):
                _die(f"{path.name}: {key} must be a list of non-empty strings")
            m[key] = val
        modes.append(m)
    if not modes:
        _die("no mode contracts found in core/modes/")
    modes.sort(key=lambda m: m["id"])
    return modes


def load_roles(known_targets: set[str], known_modes: set[str]) -> list[dict]:
    """Load + validate the worker role contracts (core/roles/*.yaml), sorted by
    id. A role declares activation, applies_to targets, applicable_modes, and a
    per-target `render` note."""
    roles: list[dict] = []
    seen: dict[str, str] = {}
    for path in sorted(ROLES_DIR.glob("*.yaml")):
        role = _load_yaml(path)
        if not isinstance(role, dict):
            _die(f"{path.name}: not a YAML mapping")
        missing = [f for f in ROLE_FIELDS if f not in role]
        if missing:
            _die(f"{path.name}: missing required field(s): {', '.join(missing)}")
        rid = role["id"]
        if path.stem != rid:
            _die(f"{path.name}: filename stem '{path.stem}' must match id '{rid}'")
        if rid in seen:
            _die(f"duplicate role id '{rid}' in {seen[rid]} and {path.name}")
        seen[rid] = path.name
        if not str(role["summary"]).strip():
            _die(f"{path.name}: summary must be a non-empty string")
        if role["activation"] not in KNOWN_ACTIVATIONS:
            _die(f"{path.name}: unknown activation '{role['activation']}' "
                 f"(known: {', '.join(KNOWN_ACTIVATIONS)})")
        applies = role["applies_to"]
        if not isinstance(applies, list) or not applies:
            _die(f"{path.name}: applies_to must be a non-empty list")
        unknown = [t for t in applies if t not in known_targets]
        if unknown:
            _die(f"{path.name}: unknown target(s) in applies_to: "
                 f"{', '.join(unknown)} (known: {', '.join(sorted(known_targets))})")
        amodes = role["applicable_modes"]
        if not isinstance(amodes, list) or not amodes:
            _die(f"{path.name}: applicable_modes must be a non-empty list")
        unknown_modes = [mm for mm in amodes if mm not in known_modes]
        if unknown_modes:
            _die(f"{path.name}: unknown mode(s) in applicable_modes: "
                 f"{', '.join(unknown_modes)} (known: {', '.join(sorted(known_modes))})")
        render = role["render"]
        if not isinstance(render, dict):
            _die(f"{path.name}: render must be a mapping of target -> note")
        for t in applies:
            if not isinstance(render.get(t), str) or not render[t].strip():
                _die(f"{path.name}: render is missing a non-empty note for "
                     f"target '{t}' (every applies_to target needs one)")
        extra = [t for t in render if t not in applies]
        if extra:
            _die(f"{path.name}: render has note(s) for non-applies_to target(s): "
                 f"{', '.join(extra)}")
        roles.append(role)
    if not roles:
        _die("no role contracts found in core/roles/")
    roles.sort(key=lambda r: r["id"])
    return roles


def select(rules: list[dict], profile: dict, target: str,
           caps: set[str]) -> list[dict]:
    """Rules selected for (profile, target): activation matches, target is in
    applies_to, and the target satisfies the rule's required capabilities."""
    acts = set(profile.get("includes_activations", []))
    out = []
    for r in rules:
        if r["activation"] not in acts:
            continue
        if target not in r.get("applies_to", []):
            continue
        if not set(r.get("requires_capabilities", [])) <= caps:
            continue
        out.append(r)
    return out


# --- target renderers ---------------------------------------------------------

def _banner_lines() -> list[str]:
    return [f"<!-- {line} -->" for line in BANNER.splitlines()]


def _render_note_block(profile: dict) -> list[str]:
    note = profile.get("render_note")
    if not note:
        return []
    return ["> " + line if line.strip() else ">"
            for line in note.rstrip("\n").splitlines()] + [""]


def _compact_lo_block(lo: list[dict]) -> list[str]:
    """Medium/low-severity rules rendered as a short_form-only checklist (compact
    mode, D2). Nothing is dropped — the bulk is just deprioritized and terse so a
    small-context model spends its budget on the critical/high rules above. Each
    bullet keeps the `<!-- rule:id severity:s -->` marker the routing selftest
    looks for."""
    out = ["## Lower-priority rules (short form — follow; deprioritize only under "
           "hard context limits)",
           "<!-- compact: medium/low severity rendered as short_form only -->", ""]
    for r in lo:
        out.append(f"- {r['short_form']}  <!-- rule:{r['id']} severity:{r['severity']} -->")
    out.append("")
    return out


def _heading_block(rules: list[dict], heading_prefix: str = "**", bullet=False,
                   compact: bool = False):
    if compact:
        hi = [r for r in rules if r["severity"] in ("critical", "high")]
        lo = [r for r in rules if r["severity"] in ("medium", "low")]
        out = _heading_block(hi, heading_prefix, bullet, compact=False)
        if lo:
            out += _compact_lo_block(lo)
        return out
    out = []
    for r in rules:
        out.append(f"## {r['summary']}")
        out.append(f"<!-- rule:{r['id']} severity:{r['severity']} -->")
        out.append("")
        if bullet:
            out.append(f"- {r['short_form']}")
            for line in r["full_text"].rstrip("\n").splitlines():
                out.append(f"  {line}" if line.strip() else "")
        else:
            out.append(f"{heading_prefix}{r['short_form']}{heading_prefix}")
            out.append("")
            out.append(r["full_text"].rstrip("\n"))
        out.append("")
    return out


def render_claude(rules: list[dict], profile: dict) -> str:
    out = _banner_lines() + [
        "",
        "# CLAUDE.md (generated)",
        "",
        f"Operating rules for Claude Code in this repository. Profile: "
        f"**{profile['id']}**. Generated from `core/`; the spine `CLAUDE.md` at "
        f"the repo root is separate and authoritative.",
        "",
    ]
    out += _render_note_block(profile)
    out += _heading_block(rules, compact=profile.get("compact", False))
    return "\n".join(out).rstrip("\n") + "\n"


def render_codex_agents(rules: list[dict], profile: dict,
                        path_groups: dict[str, dict]) -> str:
    # Codex reads the nearest AGENTS.md (directory-based), but our path groups are
    # generic globs, so rather than fake directory nesting we keep one root
    # AGENTS.md and move path-grouped rules into a labeled, glob-annotated
    # "Path-scoped guidance" section (Epic A3, Option A).
    repo_wide = [r for r in rules if not r.get("path_group")]
    out = _banner_lines() + [
        "",
        "# AGENTS.md",
        "",
        f"Operating rules for AI coding agents working in this repository "
        f"(Codex and any AGENTS.md-aware agent). Profile: **{profile['id']}**. "
        f"Plain Markdown, per the AGENTS.md convention.",
        "",
    ]
    out += _render_note_block(profile)
    out += _heading_block(repo_wide, compact=profile.get("compact", False))
    by_group: dict[str, list[dict]] = {}
    for r in rules:
        if r.get("path_group"):
            by_group.setdefault(r["path_group"], []).append(r)
    if by_group:
        out += [
            "# Path-scoped guidance",
            "",
            "Apply these in addition to the rules above WHEN WORKING ON files in "
            "the listed paths.",
            "",
        ]
        for group in sorted(by_group):
            globs = ", ".join(f"`{g}`" for g in path_groups[group]["paths"])
            out.append(f"## {group} — {globs}")
            out.append("")
            for r in by_group[group]:
                out.append(f"### {r['summary']}")
                out.append(f"<!-- rule:{r['id']} severity:{r['severity']} "
                           f"path_group:{group} -->")
                out.append("")
                out.append(f"**{r['short_form']}**")
                out.append("")
                out.append(r["full_text"].rstrip("\n"))
                out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def render_copilot_instructions(rules: list[dict], profile: dict) -> str:
    out = _banner_lines() + [
        "",
        "# GitHub Copilot — repository custom instructions",
        "",
        f"Repository-wide instructions for GitHub Copilot. Profile: "
        f"**{profile['id']}**. Natural-language Markdown, per "
        f"`.github/copilot-instructions.md` conventions.",
        "",
    ]
    out += _render_note_block(profile)
    out += _heading_block(rules, bullet=True, compact=profile.get("compact", False))
    return "\n".join(out).rstrip("\n") + "\n"


def render_copilot_path_scoped(rules: list[dict], profile: dict, group: str,
                               path_groups: dict[str, dict]) -> str:
    """A Copilot path-scoped instruction file (.github/instructions/<group>.
    instructions.md): an applyTo frontmatter built from path-groups.yaml, then
    the group's rules in the same bullet form as the repo-wide file."""
    spec = path_groups[group]
    apply_to = ",".join(spec["paths"])
    summary = spec.get("summary", "")
    out = [
        "---",
        f'applyTo: "{apply_to}"',
        "---",
    ] + _banner_lines() + [
        "",
        f"# GitHub Copilot — path-scoped instructions: {group}",
        "",
        (f"Instructions applied only to files matching the **{group}** path "
         f"group.{(' ' + summary) if summary else ''} Profile: **{profile['id']}**."),
        "",
    ]
    out += _render_note_block(profile)
    out += _heading_block(rules, bullet=True)
    return "\n".join(out).rstrip("\n") + "\n"


def render_copilot_review_scoped(rules: list[dict], profile: dict, group: str,
                                 path_groups: dict[str, dict]) -> str:
    """A Copilot REVIEW instruction file (.github/instructions/review-<group>.
    instructions.md): the same group applyTo, but reviewer-framed review_note
    content ("what to look for"), distinct from the authoring file's full_text."""
    spec = path_groups[group]
    apply_to = ",".join(spec["paths"])
    out = [
        "---",
        f'applyTo: "{apply_to}"',
        "---",
    ] + _banner_lines() + [
        "",
        f"# GitHub Copilot — review instructions: {group}",
        "",
        (f"What to look for when REVIEWING changes to files matching the "
         f"**{group}** path group. Profile: **{profile['id']}**. (Review focus — "
         f"distinct from the authoring instructions in {group}.instructions.md.)"),
        "",
    ]
    out += _render_note_block(profile)
    for r in rules:
        out.append(f"## {r['summary']}")
        out.append(f"<!-- rule:{r['id']} severity:{r['severity']} review -->")
        out.append("")
        note_lines = r["review_note"].rstrip("\n").splitlines() or [""]
        out.append(f"- {note_lines[0]}")
        for line in note_lines[1:]:
            out.append(f"  {line}" if line.strip() else "")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def render_gemini_md(rules: list[dict], profile: dict) -> str:
    out = _banner_lines() + [
        "",
        "# GEMINI.md",
        "",
        f"Context for the Gemini CLI in this repository. Profile: "
        f"**{profile['id']}**. Markdown context file, per the GEMINI.md "
        f"convention (hierarchically loaded as model memory).",
        "",
    ]
    out += _render_note_block(profile)
    out += _heading_block(rules, compact=profile.get("compact", False))
    return "\n".join(out).rstrip("\n") + "\n"


# --- local target: three role-specific surfaces (small-context friendly) ------
# Local/small-context models get terse, role-separated prompts rather than one
# flat file: SYSTEM (always-on operating rules), TASK (the microtask packet
# contract), REVIEW (a clean-context review pass). Rules are rendered TERSELY
# (short_form only) so the prompts stay small.

def _terse_block(rules: list[dict], compact: bool = False) -> list[str]:
    def _bul(r):
        return f"- {r['short_form']}  <!-- rule:{r['id']} severity:{r['severity']} -->"
    if compact:
        hi = [r for r in rules if r["severity"] in ("critical", "high")]
        lo = [r for r in rules if r["severity"] in ("medium", "low")]
        out = [_bul(r) for r in hi]
        if lo:
            out += ["", "## Lower-priority (follow; deprioritize only under hard "
                    "context limits)"] + [_bul(r) for r in lo]
        return out
    return [_bul(r) for r in rules]


def _ns(rules: list[dict], *prefixes: str) -> list[dict]:
    return [r for r in rules if r["id"].split(".", 1)[0] in prefixes]


def render_local_system(rules: list[dict], profile: dict) -> str:
    # SYSTEM = the full operating baseline for this profile, rendered terse.
    out = _banner_lines() + [
        "",
        f"# SYSTEM — local-model operating rules (profile: {profile['id']})",
        "",
        "Stable operating rules — follow them at all times. Work one microtask at "
        "a time: see TASK.md for the packet contract and REVIEW.md for the review "
        "pass.",
        "",
    ]
    out += _render_note_block(profile)
    out += _terse_block(rules, compact=profile.get("compact", False))
    return "\n".join(out).rstrip("\n") + "\n"


def render_local_task(rules: list[dict], profile: dict) -> str:
    # TASK = the fixed microtask packet contract + terse task-execution rules.
    out = _banner_lines() + [
        "",
        f"# TASK — microtask packet contract (profile: {profile['id']})",
        "",
        "Fill one packet per microtask. Do only what the packet specifies, then "
        "stop and hand back.",
        "",
    ]
    out += _render_note_block(profile)
    out += [
        "## Packet",
        "- objective: <one concrete outcome>",
        "- allowed_files: <explicit minimal set you may read/edit>",
        "- forbidden_files: <files you must not touch>",
        "- context_budget: <ceiling for this packet>",
        "- max_edit_size: <cap, e.g. one function / <= N changed lines>",
        "- expected_output_format: <usually a patch/diff, not prose>",
        "- validation: <exact command to run, or manual check>",
        "- stop_condition: <stop after the one objective>",
        "- handoff_summary_format: <shape of the terse summary for the orchestrator>",
        "",
        "## Execution rules",
    ]
    out += _terse_block(_ns(rules, "local", "blockers")) or ["- (none for this profile)"]
    return "\n".join(out).rstrip("\n") + "\n"


def render_local_review(rules: list[dict], profile: dict) -> str:
    # REVIEW = a fixed clean-context review pass + terse review rules.
    out = _banner_lines() + [
        "",
        f"# REVIEW — clean-context review pass (profile: {profile['id']})",
        "",
        "Review in a fresh context, separate from whoever wrote the change.",
        "",
    ]
    out += _render_note_block(profile)
    out += [
        "## Steps",
        "- Inspect the diff — read only what changed.",
        "- Check each acceptance criterion against the change.",
        "- Identify risks (security, correctness, scope).",
        "- Do not broaden scope or start new work.",
        "- Report findings honestly; separate validated from not-validated.",
        "",
        "## Review rules",
    ]
    out += _terse_block(_ns(rules, "review")) or ["- (none for this profile)"]
    return "\n".join(out).rstrip("\n") + "\n"


# target id -> emit(selected, profile, path_groups) -> [(relpath, content)].
# Most targets emit a single file; `local` emits three role-specific surfaces;
# `copilot` emits the repo-wide file plus one path-scoped file per path_group
# present in its selected rules.

def _emit_single(relpath, renderer):
    def emit(selected, profile, _pg):
        return [(relpath, renderer(selected, profile))]
    return emit


def _emit_copilot(selected, profile, path_groups):
    # Repo-wide file carries only rules WITHOUT a path_group (so a path-scoped
    # rule lives in exactly one place — Copilot applies repo-wide PLUS matching
    # path-scoped, and we never want duplication).
    repo_wide = [r for r in selected if not r.get("path_group")]
    files = [("copilot/.github/copilot-instructions.md",
              render_copilot_instructions(repo_wide, profile))]
    by_group: dict[str, list[dict]] = {}
    for r in selected:
        if r.get("path_group"):
            by_group.setdefault(r["path_group"], []).append(r)
    for group in sorted(by_group):
        files.append((f"copilot/.github/instructions/{group}.instructions.md",
                      render_copilot_path_scoped(by_group[group], profile,
                                                 group, path_groups)))
    # Review surfaces (A4): rules carrying a review_note also emit a path-scoped
    # review file with reviewer-framed content.
    by_review: dict[str, list[dict]] = {}
    for r in selected:
        if r.get("review_note"):
            by_review.setdefault(r["path_group"], []).append(r)
    for group in sorted(by_review):
        files.append((f"copilot/.github/instructions/review-{group}.instructions.md",
                      render_copilot_review_scoped(by_review[group], profile,
                                                   group, path_groups)))
    return files


def _emit_local(selected, profile, _pg):
    return [
        ("local/SYSTEM.md", render_local_system(selected, profile)),
        ("local/TASK.md", render_local_task(selected, profile)),
        ("local/REVIEW.md", render_local_review(selected, profile)),
    ]


def _emit_codex(selected, profile, path_groups):
    return [("codex/AGENTS.md",
             render_codex_agents(selected, profile, path_groups))]


# --- roles & modes (Epic F): NEW artifacts, additive to the rule output -------
# Rendered under <target>/modes/<id>.md and <target>/roles/<id>.md. These do not
# touch any existing rule renderer, so the rule files stay byte-identical.

def render_mode(mode: dict, profile: dict, target: str) -> str:
    out = _banner_lines() + [
        "",
        f"# Mode: {mode['id']}  (profile: {profile['id']}, target: {target})",
        "",
        mode["summary"],
        "",
    ]
    if mode["may"]:
        out.append("May: " + ", ".join(mode["may"]))
    if mode["may_not"]:
        out.append("May NOT: " + ", ".join(mode["may_not"]))
    if mode["must"]:
        out.append("Must: " + ", ".join(mode["must"]))
    return "\n".join(out).rstrip("\n") + "\n"


def render_role(role: dict, profile: dict, target: str) -> str:
    out = _banner_lines() + [
        "",
        f"# Role: {role['id']}  (profile: {profile['id']}, target: {target})",
        "",
        role["summary"],
        "",
        "Modes: " + ", ".join(role["applicable_modes"]),
        "",
        "Contract: " + role["render"][target],
    ]
    return "\n".join(out).rstrip("\n") + "\n"


def _emit_roles_modes(profile: dict, target: str, roles: list[dict],
                      modes: list[dict]) -> list[tuple[str, str]]:
    """Role/mode files for one (profile, target). Modes are universal; roles are
    gated by activation and applies_to (target shape)."""
    acts = set(profile.get("includes_activations", []))
    files: list[tuple[str, str]] = []
    for m in modes:
        files.append((f"{target}/modes/{m['id']}.md", render_mode(m, profile, target)))
    for role in roles:
        if role["activation"] not in acts or target not in role["applies_to"]:
            continue
        files.append((f"{target}/roles/{role['id']}.md",
                      render_role(role, profile, target)))
    return files


TARGETS = {
    "claude": _emit_single("claude/CLAUDE.generated.md", render_claude),
    "codex": _emit_codex,
    "copilot": _emit_copilot,
    "gemini": _emit_single("gemini/GEMINI.md", render_gemini_md),
    "local": _emit_local,
}


def build() -> dict[Path, str]:
    targets = load_targets()
    path_groups = load_path_groups()
    rules = load_rules(set(targets), set(path_groups))
    profiles = load_profiles()
    modes = load_modes()
    roles = load_roles(set(targets), {m["id"] for m in modes})
    for tid in TARGETS:
        if tid not in targets:
            _die(f"render target '{tid}' has no core/targets/{tid}.yaml manifest")
    outputs: dict[Path, str] = {}
    rendered_ids: set[str] = set()
    for profile in profiles:
        for target, emit in TARGETS.items():
            selected = select(rules, profile, target, targets[target])
            if not selected and not profile.get("allow_empty", False):
                _die(f"profile '{profile['id']}' x target '{target}' selects no "
                     f"rules (set allow_empty: true on the profile to permit "
                     f"an empty render)")
            rendered_ids.update(r["id"] for r in selected)
            for relpath, content in emit(selected, profile, path_groups):
                out_path = ADAPTERS_DIR / profile["id"] / relpath
                outputs[out_path] = content
            # Epic F: additive role/mode surfaces (no impact on rule output).
            for relpath, content in _emit_roles_modes(profile, target, roles, modes):
                outputs[ADAPTERS_DIR / profile["id"] / relpath] = content
    # Catch rules that render nowhere unless intentionally deferred.
    for r in rules:
        if r["id"] not in rendered_ids and not r["allow_unrendered"]:
            _die(f"rule '{r['id']}' renders into no (profile, target) output; "
                 f"set allow_unrendered: true with a reason if this is intentional "
                 f"(e.g. one awaiting a deferred target)")
    return outputs


def _managed_files_on_disk() -> list[Path]:
    """Every file under adapters/ that carries the GENERATED sentinel —
    i.e. files this generator owns. Hand-authored files (no sentinel) are
    ignored, so adapters/local-models/microtask-protocol.md is never touched."""
    found: list[Path] = []
    if not ADAPTERS_DIR.exists():
        return found
    for path in ADAPTERS_DIR.rglob("*"):
        if not path.is_file():
            continue
        try:
            head = path.read_text(errors="ignore")[:200]
        except OSError:
            continue
        if SENTINEL in head:
            found.append(path)
    return found


def cmd_check() -> int:
    outputs = build()
    expected_paths = set(outputs)
    problems = 0

    for path, expected in outputs.items():
        rel = path.relative_to(REPO_ROOT)
        if not path.exists():
            print(f"DRIFT: {rel} is missing (run scripts/generate-adapters.py)")
            problems += 1
            continue
        if path.read_text() != expected:
            print(f"DRIFT: {rel} is out of sync with core/")
            diff = difflib.unified_diff(
                path.read_text().splitlines(), expected.splitlines(),
                fromfile=f"{rel} (on disk)", tofile=f"{rel} (expected)",
                lineterm="",
            )
            print("\n".join(list(diff)[:40]))
            problems += 1

    for path in _managed_files_on_disk():
        if path not in expected_paths:
            rel = path.relative_to(REPO_ROOT)
            print(f"STALE: {rel} is a generated file that is no longer expected "
                  f"(delete it or regenerate)")
            problems += 1

    if problems:
        print(f"\nadapter problems detected: {problems} file(s).")
        return 1
    print(f"adapters in sync ({len(outputs)} file(s)), no stale files.")
    return 0


def cmd_write() -> int:
    outputs = build()
    expected_paths = set(outputs)
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    for path in _managed_files_on_disk():
        if path not in expected_paths:
            path.unlink()
            print(f"removed stale {path.relative_to(REPO_ROOT)}")
    return 0


def cmd_selftest() -> int:
    """Verify the path-scoping routing invariant for the Copilot target, across
    every profile, derived from the real rules (not hardcoded): a path_group
    rule appears in its scoped file and NOT in the repo-wide file; an untagged
    rule appears in the repo-wide file; each scoped file's applyTo matches
    core/path-groups.yaml. (When `wf eval` lands in Epic G, this invariant
    migrates into the golden-eval corpus.)"""
    targets = load_targets()
    path_groups = load_path_groups()
    rules = load_rules(set(targets), set(path_groups))
    profiles = load_profiles()
    caps = targets["copilot"]
    codex_caps = targets["codex"]
    problems = 0
    checked_grouped = 0
    checked_review = 0
    checked_codex = 0
    suffix = ".instructions.md"
    for profile in profiles:
        selected = select(rules, profile, "copilot", caps)
        files = dict(_emit_copilot(selected, profile, path_groups))
        repo_wide = files["copilot/.github/copilot-instructions.md"]
        # Codex (A3): path-grouped rules live in the path-scoped section (marker
        # carries path_group:<group>) and NOT in the repo-wide flow.
        codex_sel = select(rules, profile, "codex", codex_caps)
        codex = dict(_emit_codex(codex_sel, profile, path_groups))["codex/AGENTS.md"]
        for r in codex_sel:
            plain = f"<!-- rule:{r['id']} severity:{r['severity']} -->"
            pg = r.get("path_group")
            if pg:
                checked_codex += 1
                sect = f"<!-- rule:{r['id']} severity:{r['severity']} path_group:{pg} -->"
                if sect not in codex:
                    print(f"FAIL[{profile['id']}]: codex rule {r['id']} missing "
                          f"from the path-scoped section")
                    problems += 1
                if plain in codex:
                    print(f"FAIL[{profile['id']}]: codex rule {r['id']} leaked "
                          f"into the repo-wide flow")
                    problems += 1
            elif plain not in codex:
                print(f"FAIL[{profile['id']}]: repo-wide codex rule {r['id']} "
                      f"missing from AGENTS.md")
                problems += 1
        for r in selected:
            marker = f"<!-- rule:{r['id']} "
            pg = r.get("path_group")
            if pg:
                checked_grouped += 1
                scoped_rel = f"copilot/.github/instructions/{pg}{suffix}"
                scoped = files.get(scoped_rel, "")
                if marker in repo_wide:
                    print(f"FAIL[{profile['id']}]: path-scoped rule {r['id']} "
                          f"leaked into the repo-wide Copilot file")
                    problems += 1
                if marker not in scoped:
                    print(f"FAIL[{profile['id']}]: path-scoped rule {r['id']} "
                          f"missing from {scoped_rel}")
                    problems += 1
            elif marker not in repo_wide:
                print(f"FAIL[{profile['id']}]: repo-wide rule {r['id']} missing "
                      f"from the repo-wide Copilot file")
                problems += 1
            # Review surface (A4): a review_note rule must appear, review-framed,
            # in review-<group>.instructions.md.
            if r.get("review_note"):
                checked_review += 1
                rev_rel = f"copilot/.github/instructions/review-{pg}{suffix}"
                rmarker = f"<!-- rule:{r['id']} severity:{r['severity']} review -->"
                if rmarker not in files.get(rev_rel, ""):
                    print(f"FAIL[{profile['id']}]: review_note rule {r['id']} "
                          f"missing from {rev_rel}")
                    problems += 1
        # NOTE: this applyTo clause reads the expected glob from the same
        # path_groups the renderer used, so it is a self-consistency check on the
        # frontmatter FORMAT (catches a renderer change to applyTo shape), not an
        # independent oracle on glob CONTENT. The teeth are the leak/missing
        # checks above, which independently re-derive the routing from path_group.
        for rel, content in files.items():
            if "/instructions/" in rel and rel.endswith(suffix):
                name = rel.rsplit("/", 1)[1][: -len(suffix)]
                group = name[len("review-"):] if name.startswith("review-") else name
                expected = 'applyTo: "' + ",".join(path_groups[group]["paths"]) + '"'
                if expected not in content:
                    print(f"FAIL[{profile['id']}]: {rel} applyTo does not match "
                          f"core/path-groups.yaml")
                    problems += 1
    if checked_grouped == 0:
        print("path-scoping selftest: WARNING — no path_group rules selected")

    # --- Epic F: roles & modes invariants -------------------------------------
    # (1) plan mode never grants edit in any rendered surface;
    # (2) every active role renders into each of its applies_to targets (no
    #     silent drop).
    modes = load_modes()
    roles = load_roles(set(targets), {m["id"] for m in modes})
    checked_roles = plan_checked = 0
    for profile in profiles:
        acts = set(profile.get("includes_activations", []))
        for target in TARGETS:
            rm = dict(_emit_roles_modes(profile, target, roles, modes))
            plan = rm.get(f"{target}/modes/plan.md")
            if plan is not None:
                plan_checked += 1
                may = next((l for l in plan.splitlines() if l.startswith("May: ")), "")
                if "edit" in may:
                    print(f"FAIL[{profile['id']}/{target}]: plan mode grants edit")
                    problems += 1
                if not any(l.startswith("May NOT:") and "edit" in l
                           for l in plan.splitlines()):
                    print(f"FAIL[{profile['id']}/{target}]: plan mode is missing "
                          f"its no-edit clause")
                    problems += 1
            for role in roles:
                if role["activation"] not in acts or target not in role["applies_to"]:
                    continue
                rel = f"{target}/roles/{role['id']}.md"
                txt = rm.get(rel, "")
                if f"# Role: {role['id']}" not in txt:
                    print(f"FAIL[{profile['id']}/{target}]: role {role['id']} did "
                          f"not render")
                    problems += 1
                else:
                    checked_roles += 1
    if plan_checked == 0:
        print("roles/modes selftest: WARNING — no plan mode rendered")
    if checked_roles == 0:
        print("roles/modes selftest: FAIL — no role rendered (toothless)")
        problems += 1

    # --- D2: compact render mode (Copilot main as the representative surface) ----
    compact_checked = 0
    for profile in profiles:
        sel = select(rules, profile, "copilot", caps)
        main = render_copilot_instructions(sel, profile)
        section = "Lower-priority rules (short form"
        lo = [r for r in sel if r["severity"] in ("medium", "low")]
        hi = [r for r in sel if r["severity"] in ("critical", "high")]
        if profile.get("compact"):
            compact_checked += 1
            if lo and section not in main:
                print(f"compact selftest: FAIL — {profile['id']} compact main lacks "
                      f"the lower-priority section"); problems += 1
            # a medium/low rule is short_form only (no full `## summary` heading)
            if lo and f"## {lo[0]['summary']}" in main:
                print(f"compact selftest: FAIL — {profile['id']} leaked full form of "
                      f"low-pri rule {lo[0]['id']}"); problems += 1
            if lo and lo[0]["short_form"] not in main:
                print(f"compact selftest: FAIL — {profile['id']} dropped low-pri rule "
                      f"{lo[0]['id']}"); problems += 1
            # critical/high stay in full (not compacted away)
            if hi and f"## {hi[0]['summary']}" not in main:
                print(f"compact selftest: FAIL — {profile['id']} compacted a high-pri "
                      f"rule {hi[0]['id']}"); problems += 1
        elif section in main:
            print(f"compact selftest: FAIL — {profile['id']} is not compact but "
                  f"rendered the compact section"); problems += 1
    if compact_checked == 0:
        print("compact selftest: WARNING — no compact profile exercised")

    if problems:
        print(f"\nadapter selftest: {problems} problem(s).")
        return 1
    print(f"path-scoping selftest OK ({checked_grouped} Copilot path-scoped + "
          f"{checked_review} review + {checked_codex} Codex section render(s) "
          f"across {len(profiles)} profile(s)); roles/modes OK ({checked_roles} "
          f"role render(s), {plan_checked} plan-mode no-edit check(s)); compact OK ({compact_checked} "
          f"profile(s): hi full, lo short-form).")
    return 0


USAGE = """usage: wf generate [--check | --selftest]

Render the adapters/ tree from core/ (rules x profiles x targets). With no flag
it WRITES the rendered files; the drift gate compares the committed tree.

options:
  -h, --help   show this help message and exit
  --check      verify the on-disk adapters are in sync without writing; exit
               non-zero on drift (used by wf-doctor)
  --selftest   run the generator's self-checks (path-scoping, roles/modes,
               compact render) and exit
"""


def main(argv: list[str]) -> int:
    # --help/-h is a PURE READ — print usage and exit WITHOUT writing. (Without
    # this, any non---check argv fell through to cmd_write(), so `wf generate
    # --help` silently re-rendered every adapter — a surprising side effect.)
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0
    if "--check" in argv:
        return cmd_check()
    if "--selftest" in argv:
        return cmd_selftest()
    return cmd_write()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
