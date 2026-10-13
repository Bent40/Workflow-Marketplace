#!/usr/bin/env python3
"""wf-scaffold.py — generate a minimal civilian BMAD project starter.

This is the capability that lets the standalone `claude-workflow` starter repo be
retired: instead of cloning a separate repo, `wf scaffold` emits a ready-to-use
project directory from the templates under `scaffolds/common/`, with the rendered
CLAUDE.md for the chosen profile.

    python3 scripts/wf-scaffold.py --out <dir> [--name <project>] [--owner <name>]
                                      [--stack <preset>] [--profile <id>]

Profiles: `civilian` (default) or `local-small-context` (via --profile). The
former `--secure` / `--team` postures (and their scaffolds/secure/ machinery)
were removed 2026-10-13 — core/DECISIONS.md D6.

What gets emitted:
  1. CLAUDE.md = the rendered adapters/<profile>/claude/CLAUDE.generated.md for the
     resolved profile. If that file is missing, the user is told to run
     scripts/generate-adapters.py first (or it is auto-run when possible).
  2. The common templates from scaffolds/common/: README.md, .gitignore,
     .env.example, and the BMAD config glue (_bmad/bmm/config.yaml,
     _bmad/core/config.yaml).
  3. Simple {{PLACEHOLDER}} substitution for project name / id / profile / date.

`--selftest` fails closed if a bare IP-shaped string ever appears in any emitted
file (secrets stay placeholders).

Multi-repo (contracts-first model):
    wf scaffold --multi-repo --contracts CONTRACTS --members a,b,c --out PARENT
    wf scaffold --multi-repo --from repos.yaml --out PARENT

In multi-repo mode `--out` is the PARENT directory holding every generated repo:
one shared **contracts** repo (the dependency root) plus N **member** repos that
depend on it. Each repo is emitted via the SAME single-dir scaffold path, so the
chosen profile carries through to EVERY repo. Always emitted at the parent level
(never touches the network):
  * <out>/<contracts>/ and <out>/<member>/ repo dirs;
  * <out>/repos.manifest.yaml — the repo-set manifest (nodes + edges +
    contracts-first topological build/merge order), matching the nodes/edges
    shape a cross-repo dependency tracker consumes;
  * <out>/PROVISIONING.md — the create-order / branch-protection / CI playbook.
Each member repo gets a `repo-deps.yaml` pinning its dependency on the contracts
repo. (Both filenames, the playbook's model label and its propagation-skill
pointer can be overridden by the optional private data file
core/private/scaffold.yaml; absent it, these generic defaults apply.) `--provision-github [--org ORG]` (default OFF) MAY create + push the remotes
(shell out to `gh`, fail closed if absent/offline).

Usage:
    wf scaffold --out DIR [--name NAME] [--profile ID]
    wf scaffold --multi-repo --contracts NAME --members a,b,c --out PARENT
    wf scaffold --selftest
"""
from __future__ import annotations

import argparse
import datetime
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAFFOLDS = REPO_ROOT / "scaffolds"
ADAPTERS = REPO_ROOT / "adapters"

VALID_PROFILES = {
    "civilian",
    "local-small-context",
}

# Default owner name filled into the BMAD config glue's `user_name`. A neutral
# fallback — never "Root" (which is what the installed bmad repo's own config
# carries and is exactly the value we don't want a scaffolded project to inherit).
DEFAULT_OWNER = "BMad"

# Tech-stack presets. `--stack` is validated against these and the chosen
# preset's fields are exposed as {{STACK_*}} placeholders to the templates (no
# common template consumes them today; `wf start` passes --stack through).
STACK_PRESETS = {
    "fastapi-react": {
        "backend": "fastapi",
        "frontend": "react-typescript",
        "frontend_simple": "vanilla-js",
        "database_relational": "postgresql",
        "database_document": "mongodb",
        "proxy": "nginx",
        "containerization": "docker",
        "auth": "jwt",
    },
    "node-express": {
        "backend": "node-express",
        "frontend": "react-typescript",
        "frontend_simple": "vanilla-js",
        "database_relational": "postgresql",
        "database_document": "mongodb",
        "proxy": "nginx",
        "containerization": "docker",
        "auth": "jwt",
    },
    "node-express-vue": {
        "backend": "node-express",
        "frontend": "vue-typescript",
        "frontend_simple": "vanilla-js",
        "database_relational": "postgresql",
        "database_document": "mongodb",
        "proxy": "nginx",
        "containerization": "docker",
        "auth": "jwt",
    },
}
DEFAULT_STACK = "node-express"

# A bare IPv4-looking string. Used by --selftest to fail closed if any emitted
# file leaks a real-looking address. Version strings like 1.2.3 are 3 octets, so
# the 4-octet shape avoids false positives on semver.
IP_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

def resolve_profile(profile: str | None) -> str:
    """Resolve --profile (default civilian)."""
    if profile:
        if profile not in VALID_PROFILES:
            raise ValueError(
                f"unknown profile {profile!r}; valid: {', '.join(sorted(VALID_PROFILES))}"
            )
        return profile
    return "civilian"


def substitute(text: str, ctx: dict[str, str]) -> str:
    for key, val in ctx.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def claude_md_for(profile: str, *, auto_generate: bool = True) -> str:
    """Return the rendered CLAUDE.md for a profile, generating adapters if absent."""
    src = ADAPTERS / profile / "claude" / "CLAUDE.generated.md"
    if not src.exists() and auto_generate:
        gen = REPO_ROOT / "scripts" / "generate-adapters.py"
        if gen.exists():
            subprocess.run(
                [sys.executable, str(gen)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
    if not src.exists():
        raise FileNotFoundError(
            f"rendered CLAUDE.md not found at {src}. "
            f"Run `python3 scripts/generate-adapters.py` first."
        )
    return src.read_text(encoding="utf-8")


# Common templates that must be relocated to a different path in the output
# tree (flattened source name -> real path). The two
# BMAD config files are the "config glue" that makes the planning skills resolve
# to the scaffolded project (its own user_name/project_name/output paths) rather
# than falling through to the installed bmad repo's config.
COMMON_RELOCATIONS = {
    "bmad-bmm-config.yaml.tmpl": "_bmad/bmm/config.yaml",
    "bmad-core-config.yaml.tmpl": "_bmad/core/config.yaml",
}

def _emit_template(src: Path, dest: Path, ctx: dict[str, str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = src.read_text(encoding="utf-8")
    dest.write_text(substitute(raw, ctx), encoding="utf-8")
    # Preserve executable bit for shell scripts.
    if dest.suffix == ".sh" or dest.name.endswith(".sh"):
        dest.chmod(0o755)


class ScaffoldCollisionError(RuntimeError):
    """Raised (fail closed, before ANY write) when a scaffold would overwrite
    existing files — the boot-design M0 guard. `--force` overrides."""

    def __init__(self, out: Path, paths: list[Path]):
        self.out = out
        self.paths = paths
        shown = ", ".join(str(p) for p in paths[:8]) + (" …" if len(paths) > 8 else "")
        super().__init__(
            f"refusing to overwrite {len(paths)} existing file(s) under {out}: "
            f"{shown} — re-run with --force to overwrite"
        )


def _common_dest(out: Path, src: Path) -> Path:
    """Destination for a common/*.tmpl source.
    Single source of truth shared by scaffold() and plan_dests()."""
    if src.name in COMMON_RELOCATIONS:
        return out / COMMON_RELOCATIONS[src.name]
    return out / src.name[: -len(".tmpl")]


def plan_dests(out: Path, profile: str, ctx: dict[str, str]) -> list[Path]:
    """Every path a scaffold() run would write, computed WITHOUT writing.

    Backs the M0 overwrite guard. Kept in lockstep with scaffold() via the
    shared _common_dest helper; --selftest asserts planner == writer on a clean
    run so the two cannot drift silently."""
    dests: list[Path] = [out / "CLAUDE.md"]
    for src in sorted((SCAFFOLDS / "common").glob("*.tmpl")):
        dests.append(_common_dest(out, src))
    return dests


def scaffold(
    out: Path,
    profile: str,
    ctx: dict[str, str],
    *,
    force: bool = False,
) -> list[Path]:
    """Emit the project into `out`. Returns the list of files written.

    M0 overwrite guard: unless `force`, refuses — before ANY write — if any
    destination file already exists (an existing CLAUDE.md/.gitignore must
    never be silently clobbered on a non-empty dir).
    """
    if not force:
        collisions = [p for p in plan_dests(out, profile, ctx) if p.exists()]
        if collisions:
            raise ScaffoldCollisionError(out, collisions)

    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # 1. CLAUDE.md from the resolved profile's rendered adapter.
    claude_dest = out / "CLAUDE.md"
    claude_dest.write_text(claude_md_for(profile), encoding="utf-8")
    written.append(claude_dest)

    # 2. Common templates (README, .gitignore, .env.example) and the relocated
    # BMAD config glue (_bmad/bmm/config.yaml, _bmad/core/config.yaml).
    for src in sorted((SCAFFOLDS / "common").glob("*.tmpl")):
        dest = _common_dest(out, src)
        _emit_template(src, dest, ctx)
        written.append(dest)

    return written


def build_ctx(
    name: str,
    profile: str,
    *,
    owner: str = DEFAULT_OWNER,
    stack: str = DEFAULT_STACK,
) -> dict[str, str]:
    project_id = re.sub(r"[^a-z0-9-]", "-", name.lower())
    project_id = re.sub(r"-+", "-", project_id).strip("-") or "project"
    if stack not in STACK_PRESETS:
        raise ValueError(
            f"unknown stack {stack!r}; valid: {', '.join(sorted(STACK_PRESETS))}"
        )
    ctx = {
        "PROJECT_NAME": name,
        "PROJECT_ID": project_id,
        "PROFILE": profile,
        "DATE": datetime.date.today().isoformat(),
        "USER_NAME": owner or DEFAULT_OWNER,
    }
    for field, value in STACK_PRESETS[stack].items():
        ctx["STACK_" + field.upper()] = value
    return ctx


# ── multi-repo (contracts-first model) ──────────────────────────────────────────
#
# One shared `contracts` repo (the dependency ROOT) plus N `member` repos that
# each depend on it. Every repo is emitted through the SAME single-dir scaffold
# path, so the chosen profile carries through to all of them. At the PARENT level we
# always emit a machine manifest + a human provisioning playbook.
#
# Manifest shape (REPO_MANIFEST_FILENAME): a SUPERSET of the JSON shape a
# cross-repo dependency-tracker skill documents — same `verified` /
# `generated` / `nodes` / `edges` keys (edges are `[from, to]` pairs, member ->
# contracts), enriched with `repos` (name + role + relative path) and a
# contracts-FIRST `build_order` (topological). A consumer that only reads
# nodes/edges still works; the extra keys make the build/merge order explicit
# without re-deriving it. Chosen-and-documented, compatible with that shape.

# Per-member dependency pin file (written into each member repo root). Simple,
# documented, language-agnostic pointer to the contracts repo — never a network
# identifier, just a relative sibling path + the role edge.
#
# Org-specific naming is DATA, not code: the optional private file
# core/private/scaffold.yaml (absent in the public distribution) may override
# any of the generic defaults below. Keys:
#   repo_manifest_filename  parent-level repo-set manifest filename
#   member_deps_filename    per-member dependency pin filename
#   model_label             label used in PROVISIONING.md ("a <label> repo set")
#   propagation_skill       skill named in PROVISIONING.md for scoping a
#                           breaking contracts change (default: generic prose)
PRIVATE_SCAFFOLD_FILE = REPO_ROOT / "core" / "private" / "scaffold.yaml"
SCAFFOLD_DEFAULTS = {
    "repo_manifest_filename": "repos.manifest.yaml",
    "member_deps_filename": "repo-deps.yaml",
    "model_label": "contracts-first",
    "propagation_skill": "",
}


def load_scaffold_config(path: Path = PRIVATE_SCAFFOLD_FILE) -> dict:
    """Generic defaults, overridden by the optional private data file IF PRESENT.

    Flat `key: value` YAML. A present-but-malformed file (bad YAML, unknown key,
    a filename with a path separator) raises ValueError — fail closed."""
    cfg = dict(SCAFFOLD_DEFAULTS)
    if not path.is_file():
        return cfg
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ImportError:
        data: dict = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, val = line.partition(":")
            if not sep or raw[:1].isspace():
                raise ValueError(f"{path}: expected flat `key: value` lines, got {raw!r}")
            data[key.strip()] = val.strip().strip('"').strip("'")
    else:
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:  # type: ignore[attr-defined]
            raise ValueError(f"{path}: invalid YAML: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    for key, val in data.items():
        if key not in SCAFFOLD_DEFAULTS:
            raise ValueError(f"{path}: unknown key {key!r}")
        val = "" if val is None else str(val).strip()
        if key.endswith("_filename") and (not val or "/" in val or "\\" in val):
            raise ValueError(f"{path}: {key} must be a bare filename, got {val!r}")
        cfg[key] = val
    return cfg


try:
    SCAFFOLD_CONFIG = load_scaffold_config()
    _SCAFFOLD_CONFIG_ERROR: str | None = None
except (OSError, ValueError) as _e:  # surfaced (fail closed) by main()/selftest
    SCAFFOLD_CONFIG = dict(SCAFFOLD_DEFAULTS)
    _SCAFFOLD_CONFIG_ERROR = str(_e)

MEMBER_DEPS_FILENAME = SCAFFOLD_CONFIG["member_deps_filename"]

REPO_MANIFEST_FILENAME = SCAFFOLD_CONFIG["repo_manifest_filename"]
PROVISIONING_FILENAME = "PROVISIONING.md"


def _slug_repo(name: str) -> str:
    """Normalize a repo name to the same slug rule build_ctx uses for ids."""
    s = re.sub(r"[^a-z0-9-]", "-", name.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "repo"


def parse_members(raw: str | None) -> list[str]:
    """Split a comma-separated --members value into a clean, de-duped, slugged list."""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        name = _slug_repo(part.strip())
        if part.strip() and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def load_repo_set_from_file(path: Path) -> tuple[str, list[str]]:
    """Read the repo set from a manifest file.

    Accepts a small YAML/flat shape:
        contracts: <name>
        members: [a, b, c]   # or a `- item` block list
    Returns (contracts_name, members). Falls back to the minimal line parser
    when PyYAML is absent (handles `contracts:` and an inline `[..]` member list
    or `- item` block list)."""
    text = path.read_text(encoding="utf-8")
    contracts: str | None = None
    members: list[str] = []
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        if isinstance(data, dict):
            contracts = data.get("contracts")
            raw_members = data.get("members") or []
            if isinstance(raw_members, str):
                members = parse_members(raw_members)
            elif isinstance(raw_members, list):
                members = [_slug_repo(str(m).strip()) for m in raw_members if str(m).strip()]
    except ImportError:
        in_members = False
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("contracts:"):
                contracts = s.partition(":")[2].strip().strip('"').strip("'")
                in_members = False
                continue
            if s.startswith("members:"):
                rest = s.partition(":")[2].strip()
                if rest.startswith("[") and rest.endswith("]"):
                    members = parse_members(rest[1:-1])
                    in_members = False
                else:
                    in_members = True
                continue
            if in_members and s.startswith("-"):
                members.append(_slug_repo(s[1:].strip().strip('"').strip("'")))
    if not contracts:
        raise ValueError(f"{path}: no `contracts:` repo declared in manifest")
    contracts = _slug_repo(contracts)
    # De-dup members, drop any that collide with the contracts name.
    clean: list[str] = []
    seen: set[str] = set()
    for m in members:
        if m and m != contracts and m not in seen:
            seen.add(m)
            clean.append(m)
    return contracts, clean


def build_repo_manifest(contracts: str, members: list[str], profile: str) -> dict:
    """Build the repo-set manifest dict (contracts-first topological order).

    nodes/edges match the cross-repo dependency-tracker JSON shape; `repos`
    and `build_order` are the documented enrichment. `verified` is True because
    the dependency edges are declared by the scaffold, not derived by grep."""
    nodes = [contracts] + members
    edges = [[m, contracts] for m in members]  # member -> contracts
    repos = [{"name": contracts, "role": "contracts", "path": contracts}]
    repos += [{"name": m, "role": "member", "path": m} for m in members]
    return {
        "verified": True,
        "generated": datetime.date.today().isoformat(),
        "profile": profile,
        "contracts": contracts,
        "nodes": nodes,
        "edges": edges,
        "repos": repos,
        # Contracts FIRST, then members (any order among themselves). This is the
        # valid topological build/merge order for the star graph.
        "build_order": [contracts] + members,
    }


def _yaml_dump(data: dict) -> str:
    """Serialize the manifest to YAML. Prefer PyYAML; fall back to a small,
    deterministic emitter sufficient for this fixed manifest shape."""
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    except ImportError:
        pass

    def _scalar(v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)

    lines: list[str] = []
    for key, val in data.items():
        if isinstance(val, list) and val and isinstance(val[0], dict):
            lines.append(f"{key}:")
            for item in val:
                first = True
                for ik, iv in item.items():
                    prefix = "  - " if first else "    "
                    lines.append(f"{prefix}{ik}: {_scalar(iv)}")
                    first = False
        elif isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                if isinstance(item, list):
                    inner = ", ".join(_scalar(x) for x in item)
                    lines.append(f"  - [{inner}]")
                else:
                    lines.append(f"  - {_scalar(item)}")
        else:
            lines.append(f"{key}: {_scalar(val)}")
    return "\n".join(lines) + "\n"


def member_deps_text(contracts: str, member: str) -> str:
    """The per-member dependency pin: a documented pointer to the contracts repo."""
    return (
        f"# Dependency pin for member repo `{member}` (wf scaffold --multi-repo).\n"
        f"# This repo depends on the shared contracts repo. Build/merge contracts\n"
        f"# FIRST. No network identifier here — just the role edge + sibling path.\n"
        f"role: member\n"
        f"depends_on:\n"
        f"  - name: {contracts}\n"
        f"    role: contracts\n"
        f"    path: ../{contracts}\n"
    )


def provisioning_text(contracts: str, members: list[str], profile: str) -> str:
    """The PROVISIONING.md playbook (create order, branch protection, CI)."""
    member_lines = "\n".join(f"   - `{m}` (member, depends on `{contracts}`)" for m in members)
    if not member_lines:
        member_lines = "   - (no member repos declared)"
    propagation = (
        f"`{SCAFFOLD_CONFIG['propagation_skill']}`"
        if SCAFFOLD_CONFIG["propagation_skill"]
        else "a contract-change propagation pass"
    )
    order_lines = "\n".join(
        f"{i}. `{name}`" + ("  ← create FIRST (dependency root)" if i == 1 else "")
        for i, name in enumerate([contracts] + members, start=1)
    )
    return f"""# Provisioning playbook — multi-repo set

> Generated by `wf scaffold --multi-repo` (profile: `{profile}`).

This is a {SCAFFOLD_CONFIG['model_label']} repo set: one shared **contracts** repo (the dependency
root) plus {len(members)} **member** repo(s) that depend on it. The machine-
readable repo set is in [`{REPO_MANIFEST_FILENAME}`](./{REPO_MANIFEST_FILENAME})
(nodes + edges + contracts-first `build_order`).

## Repos

1. `{contracts}` (contracts — the dependency ROOT; nothing builds before it)
{member_lines}

## Create order (contracts FIRST)

Create, build, and merge in this topological order so dependents never precede
the contract they import:

{order_lines}

## Branch protection guidance

- Protect the default branch on **every** repo (require PR review + green CI).
- `{contracts}` is the highest-leverage repo: a change there ripples to all
  members. Require an extra reviewer and run the dependents' contract tests
  before merging a contracts change.
- Members pin their dependency on `{contracts}` in `{MEMBER_DEPS_FILENAME}`; bump
  that pin in a dedicated PR after a contracts release.

## CI wiring

- Contracts repo: publish/tag a versioned artifact on merge to the default branch.
- Member repos: on CI, resolve the pinned `{contracts}` version, then build/test.
- Roll a breaking contracts change out in `build_order` (contracts first), using
  {propagation} to scope the per-repo migration.
"""


def emit_multi_repo(
    parent: Path,
    contracts: str,
    members: list[str],
    profile: str,
    *,
    owner: str = DEFAULT_OWNER,
    stack: str = DEFAULT_STACK,
    force: bool = False,
) -> dict:
    """Emit the full multi-repo set into `parent`. Returns a summary dict.

    Reuses the single-dir `scaffold()` for EVERY repo (contracts + members) so
    each gets its own profile-correct CLAUDE.md. Always writes the
    parent-level manifest + PROVISIONING.md, and a per-member dependency pin.
    Never touches the network.

    M0 overwrite guard: unless `force`, the collision check runs over the
    WHOLE set (every repo's planned files + the parent-level files) before a
    single write — one member's existing CLAUDE.md refuses the entire run."""

    contracts_out = parent / contracts
    ctx = build_ctx(contracts, profile, owner=owner, stack=stack)
    member_plans = [
        (member, parent / member, build_ctx(member, profile, owner=owner, stack=stack))
        for member in members
    ]

    if not force:
        planned = plan_dests(contracts_out, profile, ctx)
        for member, member_out, mctx in member_plans:
            planned += plan_dests(member_out, profile, mctx)
            planned.append(member_out / MEMBER_DEPS_FILENAME)
        planned += [parent / REPO_MANIFEST_FILENAME, parent / PROVISIONING_FILENAME]
        collisions = [p for p in planned if p.exists()]
        if collisions:
            raise ScaffoldCollisionError(parent, collisions)

    parent.mkdir(parents=True, exist_ok=True)
    repo_dirs: list[Path] = []

    # 1. Contracts repo (the root).
    scaffold(contracts_out, profile, ctx, force=force)
    repo_dirs.append(contracts_out)

    # 2. Member repos — each via the same single-dir path, each pinned to contracts.
    for member, member_out, mctx in member_plans:
        scaffold(member_out, profile, mctx, force=force)
        (member_out / MEMBER_DEPS_FILENAME).write_text(
            member_deps_text(contracts, member), encoding="utf-8"
        )
        repo_dirs.append(member_out)

    # 3. Parent-level manifest (machine) + PROVISIONING.md (human).
    manifest = build_repo_manifest(contracts, members, profile)
    (parent / REPO_MANIFEST_FILENAME).write_text(_yaml_dump(manifest), encoding="utf-8")
    (parent / PROVISIONING_FILENAME).write_text(
        provisioning_text(contracts, members, profile), encoding="utf-8"
    )

    return {
        "parent": parent,
        "contracts": contracts,
        "members": members,
        "profile": profile,
        "repo_dirs": repo_dirs,
        "manifest": manifest,
    }


# ── GitHub provisioning (opt-in, fail-closed) ───────────────────────


def _gh_available() -> bool:
    """True if the `gh` CLI is on PATH."""
    return shutil.which("gh") is not None


def provision_github(
    summary: dict,
    *,
    org: str | None = None,
) -> int:
    """Opt-in: create the remote repos contracts-first and push.

    MAY create + push (shell out to `gh`); fail CLOSED with a clear,
    PROVISIONING.md-pointing message if `gh` is missing OR a call fails.
    Returns 0 on success; 1 on a fail-closed error."""
    parent: Path = summary["parent"]
    ordered: list[str] = summary["manifest"]["build_order"]  # contracts first

    if not _gh_available():
        print(
            "error: --provision-github requires the `gh` CLI, which was not found "
            "on PATH. No remote was created.",
            file=sys.stderr,
        )
        print(
            f"  Fall back to the manual playbook: {parent / PROVISIONING_FILENAME}",
            file=sys.stderr,
        )
        return 1

    for name in ordered:
        full = f"{org}/{name}" if org else name
        cmd = ["gh", "repo", "create", full, "--private", "--source", str(parent / name), "--push"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as exc:  # gh vanished / not executable
            print(f"error: failed to invoke gh for {full!r}: {exc}", file=sys.stderr)
            print(
                f"  Fall back to the manual playbook: {parent / PROVISIONING_FILENAME}",
                file=sys.stderr,
            )
            return 1
        if res.returncode != 0:
            print(
                f"error: `gh repo create {full}` failed (network/auth?). "
                f"No further repos created.",
                file=sys.stderr,
            )
            if res.stderr:
                print("  " + res.stderr.strip(), file=sys.stderr)
            print(
                f"  Fall back to the manual playbook: {parent / PROVISIONING_FILENAME}",
                file=sys.stderr,
            )
            return 1
        print(f"  created + pushed: {full}")
    return 0


def topo_order_ok(manifest: dict) -> bool:
    """Validate the manifest's build_order is a valid topological order with
    contracts FIRST: every edge [from, to] must have `to` appear before `from`,
    and the first node must be the contracts root."""
    order = manifest.get("build_order") or []
    if not order:
        return False
    if order[0] != manifest.get("contracts"):
        return False
    pos = {name: i for i, name in enumerate(order)}
    for edge in manifest.get("edges", []):
        if len(edge) != 2:
            return False
        src, dst = edge
        if src not in pos or dst not in pos:
            return False
        if pos[dst] >= pos[src]:  # dependency must come BEFORE dependent
            return False
    return True


# ── selftest ──────────────────────────────────────────────────────────────────

def _load_yaml(text: str) -> dict | None:
    """Parse a flat YAML config to a dict. Uses PyYAML if available, else a
    minimal `key: value` parser (sufficient for the flat config glue). Returns
    None if the text cannot be parsed into a mapping."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else None
    except ImportError:
        pass
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or ":" not in s:
            continue
        key, _, val = s.partition(":")
        val = val.strip().strip('"').strip("'")
        out[key.strip()] = val
    return out or None


def _rel_names(root: Path) -> set[str]:
    """Posix-relative names of every file under root, plus dir markers."""
    names: set[str] = set()
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        names.add(rel)
        if p.is_dir():
            names.add(rel + "/")
    return names


# The exact file set every single-dir scaffold emits (the minimal civilian
# starter). Anything beyond it is a leak of removed machinery.
EXPECTED_FILES = {
    "CLAUDE.md",
    "README.md",
    ".gitignore",
    ".env.example",
    "_bmad/bmm/config.yaml",
    "_bmad/core/config.yaml",
}


def selftest() -> int:
    problems: list[str] = []

    cases = {
        "civilian": ("civilian", None),
        "local-small-context": ("local-small-context", "local-small-context"),
    }

    rendered: dict[str, str] = {}  # case -> CLAUDE.md text

    for label, (expected_profile, prof) in cases.items():
        profile = resolve_profile(prof)
        if profile != expected_profile:
            problems.append(
                f"{label}: profile resolution gave {profile!r}, expected {expected_profile!r}"
            )
        with tempfile.TemporaryDirectory(prefix=f"scaffold-{label}-") as td:
            out = Path(td) / "proj"
            ctx = build_ctx("demo", profile)
            try:
                written = scaffold(out, profile, ctx)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{label}: scaffold raised {exc!r}")
                continue

            # M0 guard integrity: the planner that backs the overwrite guard
            # must name EXACTLY the files the writer writes (no silent drift).
            planned = {p.relative_to(out).as_posix() for p in plan_dests(out, profile, ctx)}
            actual = {p.relative_to(out).as_posix() for p in written}
            if planned != actual:
                problems.append(
                    f"{label}: plan_dests drifted from scaffold() "
                    f"(planned-only: {sorted(planned - actual)}, "
                    f"written-only: {sorted(actual - planned)})"
                )

            # Exactly the minimal starter — no removed (secure/team) machinery.
            files_on_disk = {
                p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
            }
            if files_on_disk != EXPECTED_FILES:
                problems.append(
                    f"{label}: emitted file set != minimal starter "
                    f"(extra: {sorted(files_on_disk - EXPECTED_FILES)}, "
                    f"missing: {sorted(EXPECTED_FILES - files_on_disk)})"
                )

            # CLAUDE.md exists, is non-empty, and is the profile's render.
            claude = out / "CLAUDE.md"
            if not claude.exists() or claude.stat().st_size == 0:
                problems.append(f"{label}: CLAUDE.md missing or empty")
            else:
                rendered[label] = claude.read_text(encoding="utf-8")
                if rendered[label] != claude_md_for(profile, auto_generate=False):
                    problems.append(
                        f"{label}: CLAUDE.md is not adapters/{profile}/claude/"
                        f"CLAUDE.generated.md"
                    )

            # BMAD config glue: every scaffold emits _bmad/bmm/config.yaml and
            # _bmad/core/config.yaml so planning skills resolve to THIS project,
            # not the installed bmad repo (whose user_name is "Root").
            for cfg_rel in ("_bmad/bmm/config.yaml", "_bmad/core/config.yaml"):
                cfg_path = out / cfg_rel
                if not cfg_path.exists() or cfg_path.stat().st_size == 0:
                    problems.append(f"{label}: {cfg_rel} missing or empty")
                    continue
                parsed = _load_yaml(cfg_path.read_text(encoding="utf-8"))
                if parsed is None:
                    problems.append(f"{label}: {cfg_rel} is not valid YAML")
                    continue
                if parsed.get("project_name") != "demo":
                    problems.append(
                        f"{label}: {cfg_rel} project_name == "
                        f"{parsed.get('project_name')!r}, expected 'demo' "
                        f"(must be the scaffold --name, not 'bmad')"
                    )
                if parsed.get("user_name") == "Root":
                    problems.append(
                        f"{label}: {cfg_rel} user_name == 'Root' "
                        f"(must NOT inherit the bmad repo's owner)"
                    )
                if parsed.get("output_folder") != "_bmad-output":
                    problems.append(
                        f"{label}: {cfg_rel} output_folder == "
                        f"{parsed.get('output_folder')!r}, expected '_bmad-output'"
                    )

            # No leftover {{PLACEHOLDER}} and no bare IP in any emitted file.
            for f in out.rglob("*"):
                if not f.is_file():
                    continue
                try:
                    content = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if f.name != "CLAUDE.md" and re.search(r"\{\{[A-Z_]+\}\}", content):
                    problems.append(
                        f"{label}: unsubstituted placeholder in "
                        f"{f.relative_to(out).as_posix()}"
                    )
                for match in IP_RE.findall(content):
                    problems.append(
                        f"{label}: bare IP-shaped string {match!r} in "
                        f"{f.relative_to(out).as_posix()} — secrets must be $ENV:/placeholders"
                    )

    # The profiles render distinct CLAUDE.md files (proves --profile wiring).
    if rendered.get("civilian") and rendered.get("civilian") == rendered.get(
        "local-small-context"
    ):
        problems.append(
            "local-small-context CLAUDE.md is identical to civilian — --profile wiring not proven"
        )

    # Removed postures are rejected, not silently mapped.
    for gone in ("secure", "secure-team", "civilian-team"):
        try:
            resolve_profile(gone)
            problems.append(f"--profile {gone}: removed profile was accepted")
        except ValueError:
            pass

    # --stack: every preset is accepted and fills its STACK_* placeholders;
    # an unknown --stack must error (exit non-zero via build_ctx ValueError).
    for stack, backend in (("node-express", "node-express"), ("fastapi-react", "fastapi")):
        if build_ctx("demo", "civilian", stack=stack).get("STACK_BACKEND") != backend:
            problems.append(f"--stack {stack}: STACK_BACKEND != {backend!r}")
    try:
        build_ctx("demo", "civilian", stack="bogus")
        problems.append("--stack bogus: build_ctx accepted unknown stack (no error)")
    except ValueError:
        pass

    # ── multi-repo mode ─────────────────────────────────────────────────────
    # Civilian multi-repo: contracts + members emitted, manifest topo-orderable
    # with contracts first, each member references contracts.
    with tempfile.TemporaryDirectory(prefix="scaffold-multi-civ-") as td:
        parent = Path(td) / "set"
        contracts = "demo-contracts"
        members = ["demo-core", "demo-shell"]
        try:
            summary = emit_multi_repo(parent, contracts, members, "civilian")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"multi-repo civilian: emit raised {exc!r}")
            summary = None
        if summary is not None:
            # Contracts + member dirs emitted (each a real scaffold w/ CLAUDE.md).
            for repo in [contracts] + members:
                repo_dir = parent / repo
                if not repo_dir.is_dir():
                    problems.append(f"multi-repo civilian: repo dir {repo!r} not emitted")
                elif not (repo_dir / "CLAUDE.md").exists():
                    problems.append(f"multi-repo civilian: {repo!r} has no CLAUDE.md")
            # Parent-level manifest + playbook emitted.
            man_path = parent / REPO_MANIFEST_FILENAME
            prov_path = parent / PROVISIONING_FILENAME
            if not prov_path.exists() or prov_path.stat().st_size == 0:
                problems.append("multi-repo civilian: PROVISIONING.md missing or empty")
            if not man_path.exists():
                problems.append(f"multi-repo civilian: {REPO_MANIFEST_FILENAME} missing")
            else:
                parsed_man = _load_yaml(man_path.read_text(encoding="utf-8"))
                # The flat _load_yaml fallback can't represent nested lists, so
                # validate topology against the in-memory manifest (the emitted
                # value), and the manifest FILE just for presence + contracts-first.
                if not topo_order_ok(summary["manifest"]):
                    problems.append(
                        "multi-repo civilian: manifest build_order not a valid "
                        "contracts-first topological order"
                    )
                if summary["manifest"]["build_order"][0] != contracts:
                    problems.append(
                        "multi-repo civilian: contracts is not FIRST in build_order"
                    )
                if parsed_man is None or parsed_man.get("contracts") != contracts:
                    problems.append(
                        f"multi-repo civilian: manifest file contracts field != "
                        f"{contracts!r}"
                    )
            # Each member references the contracts repo.
            for member in members:
                deps = parent / member / MEMBER_DEPS_FILENAME
                if not deps.exists():
                    problems.append(
                        f"multi-repo civilian: member {member!r} missing "
                        f"{MEMBER_DEPS_FILENAME}"
                    )
                elif contracts not in deps.read_text(encoding="utf-8"):
                    problems.append(
                        f"multi-repo civilian: member {member!r} does not reference "
                        f"contracts repo {contracts!r}"
                    )

    # --members / --from parsing.
    if parse_members("a, b, ,a,c") != ["a", "b", "c"]:
        problems.append("parse_members: did not clean/dedupe comma list correctly")

    # ── M0 overwrite guard: fail closed BEFORE any write; --force overrides ──
    with tempfile.TemporaryDirectory(prefix="scaffold-guard-") as td:
        out = Path(td) / "proj"
        out.mkdir(parents=True)
        ctx = build_ctx("demo", "civilian")

        # An existing CLAUDE.md refuses the run and stays byte-identical.
        sentinel = "# existing user CLAUDE.md — must never be clobbered\n"
        (out / "CLAUDE.md").write_text(sentinel, encoding="utf-8")
        try:
            scaffold(out, "civilian", ctx)
            problems.append("guard: scaffold over existing CLAUDE.md did not raise")
        except ScaffoldCollisionError:
            pass
        if (out / "CLAUDE.md").read_text(encoding="utf-8") != sentinel:
            problems.append("guard: refused scaffold still modified CLAUDE.md")
        extras = [n for n in _rel_names(out) if n != "CLAUDE.md"]
        if extras:
            problems.append(f"guard: refused scaffold still wrote files: {extras}")

        # An existing .gitignore alone also refuses — and writes NOTHING else.
        (out / "CLAUDE.md").unlink()
        (out / ".gitignore").write_text("node_modules\n", encoding="utf-8")
        try:
            scaffold(out, "civilian", ctx)
            problems.append("guard: scaffold over existing .gitignore did not raise")
        except ScaffoldCollisionError:
            pass
        if (out / "CLAUDE.md").exists():
            problems.append("guard: refused scaffold (.gitignore case) still wrote CLAUDE.md")

        # --force proceeds and overwrites.
        try:
            scaffold(out, "civilian", ctx, force=True)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"guard: --force scaffold raised {exc!r}")
        else:
            if (out / ".gitignore").read_text(encoding="utf-8") == "node_modules\n":
                problems.append("guard: --force did not overwrite .gitignore")
            if not (out / "CLAUDE.md").exists():
                problems.append("guard: --force run did not write CLAUDE.md")

    # Multi-repo: ONE member's existing CLAUDE.md refuses the WHOLE set
    # before any write (no contracts repo, no manifest, no other member).
    with tempfile.TemporaryDirectory(prefix="scaffold-guard-multi-") as td:
        parent = Path(td) / "set"
        (parent / "svc-a").mkdir(parents=True)
        (parent / "svc-a" / "CLAUDE.md").write_text("keep\n", encoding="utf-8")
        try:
            emit_multi_repo(parent, "contracts", ["svc-a", "svc-b"], "civilian")
            problems.append("guard: multi-repo over existing member CLAUDE.md did not raise")
        except ScaffoldCollisionError:
            pass
        if (
            (parent / REPO_MANIFEST_FILENAME).exists()
            or (parent / PROVISIONING_FILENAME).exists()
            or (parent / "contracts").exists()
            or (parent / "svc-b").exists()
        ):
            problems.append("guard: refused multi-repo still wrote parent/member files")
        if (parent / "svc-a" / "CLAUDE.md").read_text(encoding="utf-8") != "keep\n":
            problems.append("guard: refused multi-repo modified the member's CLAUDE.md")

    # Private naming data file: absent -> generic defaults; a valid file
    # overrides; a malformed one fails closed.
    if _SCAFFOLD_CONFIG_ERROR:
        problems.append(f"scaffold config: {_SCAFFOLD_CONFIG_ERROR}")
    with tempfile.TemporaryDirectory(prefix="scaffold-cfg-") as td:
        cf = Path(td) / "scaffold.yaml"
        if load_scaffold_config(cf) != SCAFFOLD_DEFAULTS:
            problems.append("scaffold config: absent file did not yield the generic defaults")
        cf.write_text(
            "# fixture\nrepo_manifest_filename: acme-repos.yaml\n"
            'member_deps_filename: "acme-deps.yaml"\n',
            encoding="utf-8",
        )
        got = load_scaffold_config(cf)
        if (got["repo_manifest_filename"], got["member_deps_filename"],
                got["model_label"]) != ("acme-repos.yaml", "acme-deps.yaml",
                                        SCAFFOLD_DEFAULTS["model_label"]):
            problems.append(f"scaffold config: override parsed wrong: {got}")
        for bad in ("bogus_key: x\n", "member_deps_filename: ../escape.yaml\n"):
            cf.write_text(bad, encoding="utf-8")
            try:
                load_scaffold_config(cf)
                problems.append(f"scaffold config: malformed file accepted: {bad!r}")
            except ValueError:
                pass

    if problems:
        print("wf scaffold selftest: FAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print(
        "wf scaffold selftest: PASS "
        "(civilian|local-small-context scaffolded; exact minimal file set, "
        "no-IP/placeholder leak, profile-distinct CLAUDE.md, removed postures "
        "rejected; multi-repo contracts+members + manifest topo order + "
        "member->contracts pin verified; "
        "M0 overwrite guard: fail-closed on existing CLAUDE.md/.gitignore incl. "
        "whole-set multi-repo refusal, --force override, planner==writer; "
        "private naming data file defaults/override/fail-closed)"
    )
    return 0


def main(argv: list[str]) -> int:
    if _SCAFFOLD_CONFIG_ERROR and "--selftest" not in argv:
        sys.stderr.write(f"wf scaffold: {_SCAFFOLD_CONFIG_ERROR}\n")
        return 2
    ap = argparse.ArgumentParser(
        prog="wf scaffold",
        description="Generate a minimal civilian BMAD project starter from scaffolds/common/.",
    )
    ap.add_argument("--out", help="output directory for the generated project")
    ap.add_argument("--name", default="my-project", help="project display name")
    ap.add_argument(
        "--owner",
        default=DEFAULT_OWNER,
        help=f"owner name for the BMAD config user_name (default: {DEFAULT_OWNER!r})",
    )
    ap.add_argument(
        "--stack",
        default=DEFAULT_STACK,
        help=f"tech stack preset (default: {DEFAULT_STACK!r}); "
        f"choices: {', '.join(sorted(STACK_PRESETS))}",
    )
    ap.add_argument(
        "--profile",
        help=f"rendered profile for CLAUDE.md (default: civilian); "
        f"choices: {', '.join(sorted(VALID_PROFILES))}",
    )
    # ── multi-repo (contracts-first model) ────────────────────────────────────
    ap.add_argument(
        "--multi-repo",
        action="store_true",
        help="emit a contracts-first repo SET: one shared contracts repo + N members "
        "that depend on it (--out becomes the PARENT directory)",
    )
    ap.add_argument("--contracts", help="multi-repo: the root contracts repo name")
    ap.add_argument(
        "--members", help="multi-repo: comma-separated member repo names (a,b,c)"
    )
    ap.add_argument(
        "--from",
        dest="from_file",
        help="multi-repo: declare the repo set in a YAML file instead of flags "
        "(contracts: <name>; members: [a, b, c])",
    )
    ap.add_argument(
        "--provision-github",
        action="store_true",
        help="multi-repo: opt in to creating the remote repos contracts-first and "
        "pushing via `gh` (OFF by default; fails closed if gh/network absent)",
    )
    ap.add_argument("--org", help="multi-repo: GitHub org/owner for --provision-github")
    ap.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing files the scaffold would write; without it the "
        "scaffold FAILS CLOSED before any write if a destination file already "
        "exists (M0 overwrite guard — an existing CLAUDE.md/.gitignore is "
        "never silently clobbered)",
    )
    ap.add_argument("--selftest", action="store_true", help="run built-in self-test")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if not args.out:
        ap.error("--out is required (or use --selftest)")

    try:
        profile = resolve_profile(args.profile)
    except ValueError as exc:
        ap.error(str(exc))

    out = Path(args.out).expanduser().resolve()

    # ── multi-repo mode ────────────────────────────────────────────────────────
    if args.multi_repo:
        if args.from_file:
            try:
                contracts, members = load_repo_set_from_file(Path(args.from_file))
            except (OSError, ValueError) as exc:
                ap.error(str(exc))
        else:
            if not args.contracts:
                ap.error("--multi-repo requires --contracts <name> (or --from <file>)")
            contracts = _slug_repo(args.contracts)
            members = parse_members(args.members)
            members = [m for m in members if m != contracts]
        if not members:
            ap.error("--multi-repo requires at least one member repo (--members or --from)")

        try:
            summary = emit_multi_repo(
                out,
                contracts,
                members,
                profile,
                owner=args.owner,
                stack=args.stack,
                force=args.force,
            )
        except (FileNotFoundError, ValueError, ScaffoldCollisionError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        print(f"Scaffolded multi-repo set (profile: {profile})")
        print(f"  parent:    {out}")
        print(f"  contracts: {contracts}")
        print(f"  members:   {', '.join(members)}")
        print(f"  manifest:  {out / REPO_MANIFEST_FILENAME}")
        print(f"  playbook:  {out / PROVISIONING_FILENAME}")

        if args.provision_github:
            return provision_github(summary, org=args.org)
        print(
            "  (no --provision-github: local repos only — see PROVISIONING.md to "
            "create remotes)"
        )
        return 0

    try:
        ctx = build_ctx(args.name, profile, owner=args.owner, stack=args.stack)
    except ValueError as exc:
        ap.error(str(exc))
    try:
        written = scaffold(out, profile, ctx, force=args.force)
    except (FileNotFoundError, ScaffoldCollisionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Scaffolded project '{ctx['PROJECT_NAME']}' (id: {ctx['PROJECT_ID']})")
    print(f"  profile: {profile}")
    print(f"  output:  {out}")
    print(f"  files:   {len(written)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
