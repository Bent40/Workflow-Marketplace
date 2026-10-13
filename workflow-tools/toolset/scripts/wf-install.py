#!/usr/bin/env python3
"""wf-install.py — BMAD-installer-style pack + target picker that MATERIALIZES a
selection into a project directory.

`wf scaffold` makes the project SHELL (CLAUDE.md, README, config glue). `wf install` is COMPLEMENTARY: it POPULATES that project with the
PACKS (modules) the user wants, rendered for the AI agent TARGETS they want.

    wf install --out DIR [--packs a,b,c] [--targets claude,codex,...] [--profile P]
    wf install --list-packs
    wf install check --dir DIR
    wf install --selftest

PACKS (modules) -> a set of skill directories, resolved from the AUTHORITATIVE
skill->module map (`_bmad/_config/skill-manifest.csv`) plus a documented naming
fallback for OUR skills that are not in that manifest:

  * core, bmm, bmb, tea, cis, wds, gds  -> the manifest's `module` column.
  * <extra>  -> OPTIONAL extra packs declared in the private data file
                `core/private/packs.yaml` (a name-prefix and/or an explicit
                allowlist per pack). Absent in the public distribution, where
                only the packs below exist; present in a private install, where
                they claim that org's own non-manifest skills.
  * custom   -> the 6 owned `bmad-*` skills NOT in the manifest. An EXPLICIT
                allowlist (NOT a prefix), because they share the `bmad-` prefix
                with the 117 manifest skills — a prefix rule would over-capture.
  * workflow -> the workflow-native (non-bmad) skills we own, e.g.
                `workflow-operating-model`. Explicit allowlist.
  * wf-tools -> NOT skills: the `wf` CLI tool family (`scripts/wf` + `wf-*.py`).
                Materialized as scripts under <out>/scripts/, recorded in the
                manifest, and NOT counted toward the .claude/skills subset.

TARGETS (AI agents) -> rendered via the EXISTING adapter pipeline
(`scripts/generate-adapters.py`), which already emits per-(profile,target) files
under `adapters/<profile>/<target>/`. `wf install` copies the chosen target's
adapter tree for the chosen profile into <out>/<target>/ (claude's adapter goes
to <out>/.claude/CLAUDE.generated.md). It does NOT fork or re-implement that
renderer — drift in it is gated by wf-doctor check 11.

  claude  -> the SUBSET of selected packs' skill dirs is copied into
             <out>/.claude/skills/ (NOT all 131), + the rendered Claude adapter.
  codex / copilot / gemini / local -> that target's rendered adapter
             instruction file(s) for the profile, PLUS the PORTABLE skill tree:
             the selected skills copied to <out>/skills/ as plain markdown
             (evals/ and .decision-log.md stripped) with a generated
             skills/INDEX.md trigger->file map. Wiring is one documented line
             in the host's instruction file (AGENTS.md / GEMINI.md / prompt):
             "when a request matches a trigger in skills/INDEX.md, read that
             skill file and follow it."

FAIL CLOSED on an unknown pack, an unknown target, an unknown profile, a missing
manifest, or a materialized state that does not match workflow.packs.yaml.

Non-interactive default: when --packs / --targets are omitted and stdin is NOT a
TTY, we DEFAULT sensibly and ANNOUNCE it (packs -> `core`; targets -> `claude`)
rather than hang on a prompt. With a TTY, an interactive picker is shown.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime
import io
import itertools
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
ADAPTERS_DIR = REPO_ROOT / "adapters"
MANIFEST = REPO_ROOT / "_bmad" / "_config" / "skill-manifest.csv"

MANIFEST_VERSION = 1

# The seven modules carried by the manifest's `module` column.
MANIFEST_PACKS = ("core", "bmm", "bmb", "tea", "cis", "wds", "gds")

# Our owned skills that are NOT in the manifest. The custom bmad-* set MUST be
# an explicit allowlist (they share the bmad- prefix with the 117 manifest
# skills, so a prefix rule would over-capture). Extra org-specific packs are
# DATA, not code: they load from the optional private file below (see
# load_extra_packs). Kept in sync against ground truth by --selftest (every
# non-manifest skill must be claimed by exactly one pack — no orphan, no
# double-claim).
PRIVATE_DIR = REPO_ROOT / "core" / "private"
PRIVATE_PACKS_FILE = PRIVATE_DIR / "packs.yaml"
CUSTOM_BMAD_SKILLS = (
    "bmad-competitive-features",
    "bmad-decision-propagation",
    "bmad-eval-inline",
    "bmad-security-decision-framing",
    "bmad-skill-gap-retrospective",
    "bmad-skill-governance",
)

# Workflow-native (non-bmad) skills we own — explicit allowlist (distinct prefix
# so no over-capture risk, but kept explicit for the same reconciliation contract).
WORKFLOW_SKILLS = (
    "workflow-operating-model",
    "workflow-start",
    "workflow-find",
    "workflow-cli",
    "telegram-bridge",
    "telegram-bridge-setup",
)

# The writer-mode pack: the writer-mode loader + the lit-* literary skills
# (charter: docs/literary-pack.md). Explicit allowlist, same reconciliation
# contract — grows as the roadmap skills (lit-voice-contract, lit-canon, ...)
# are built.
WRITER_SKILLS = (
    "writer-mode",
    "writer-help",
    "lit-author-style-research",
    "lit-teach",
    "lit-genre-atlas",
)

# The 3D pack: the 3d-mode loader + the 3d-help guide + the 3d-create pipeline,
# plus 3d-setup (box readiness) and 3d-troubleshoot (failure diagnostic)
# (charter: docs/3d-pack.md). Install id is `3d` (what the user calls it);
# skills use the `3d-` prefix. Explicit allowlist, same reconciliation contract.
THREED_SKILLS = (
    "3d-mode",
    "3d-help",
    "3d-create",
    "3d-setup",
    "3d-troubleshoot",
)

# wf-tools is a SCRIPTS pack, not a skills pack.
WF_TOOLS_PACK = "wf-tools"

# Built-in (public) non-manifest packs, in listing order.
BUILTIN_OWNED_PACKS = ("custom", "workflow", "writer", "3d")

VALID_TARGETS = ("claude", "codex", "copilot", "gemini", "local")
VALID_PROFILES = (
    "civilian",
    "local-small-context",
)

DEFAULT_PACKS = ("core",)
DEFAULT_TARGETS = ("claude",)
DEFAULT_PROFILE = "civilian"

GENERATED_NOTE = (
    "GENERATED by `wf install`. Records the PACK + TARGET selection materialized "
    "into this directory. `wf install check --dir .` validates it against the "
    "on-disk state. Do not hand-edit the resolved inventory."
)


# --------------------------------------------------------------------------- #
# Errors / output
# --------------------------------------------------------------------------- #
class InstallError(Exception):
    """A fail-closed condition (unknown pack/target/profile, bad manifest)."""


def _die(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    sys.stderr.write(f"wf install: {msg}\n")
    raise SystemExit(2)


# --------------------------------------------------------------------------- #
# Optional extra packs (private data file — absent in the public distribution)
# --------------------------------------------------------------------------- #
_PACK_NAME_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def _parse_packs_minimal(text: str) -> dict:
    """Minimal parser (no PyYAML) for the exact packs.yaml shape:

        packs:
          <name>:
            prefix: "<prefix>"
            description: "<text>"
            skills: [a, b]        # or a `- item` block list
    """
    def unq(v: str) -> str:
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            return v[1:-1]
        return v

    packs: dict = {}
    in_packs = False
    cur: dict | None = None
    list_key: str | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if indent == 0:
            key, _, val = line.partition(":")
            if key.strip() == "packs" and val.strip():
                raise ValueError("`packs:` must be a block mapping")
            in_packs = key.strip() == "packs"
            cur, list_key = None, None
            continue
        if not in_packs:
            continue
        if indent == 2 and line.endswith(":"):
            cur = packs.setdefault(unq(line[:-1]), {})
            list_key = None
            continue
        if cur is None:
            raise ValueError(f"unexpected line: {raw!r}")
        if line.startswith("- ") and list_key:
            cur[list_key].append(unq(line[2:]))
            continue
        key, sep, val = line.partition(":")
        if not sep:
            raise ValueError(f"unexpected line: {raw!r}")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            cur[key] = [unq(x) for x in val[1:-1].split(",") if x.strip()]
            list_key = None
        elif val == "":
            cur[key] = []
            list_key = key
        else:
            cur[key] = unq(val)
            list_key = None
    return {"packs": packs}


def load_extra_packs(path: Path = PRIVATE_PACKS_FILE) -> dict[str, dict]:
    """Extra packs from the optional private data file, in file order:
    name -> {"prefix": str | None, "skills": tuple[str, ...], "description": str}.

    Absent file -> {} (the public, generic behaviour). A PRESENT but malformed
    file fails closed (InstallError) — a broken pack registry must never be
    silently ignored."""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        try:
            import yaml  # type: ignore
        except ImportError:
            data = _parse_packs_minimal(text)
        else:
            data = yaml.safe_load(text)
    except Exception as e:  # yaml.YAMLError / ValueError
        raise InstallError(f"{path}: invalid pack file: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("packs") or {}, dict):
        raise InstallError(f"{path}: expected a top-level `packs:` mapping")
    reserved = set(MANIFEST_PACKS) | set(BUILTIN_OWNED_PACKS) | {WF_TOOLS_PACK}
    out: dict[str, dict] = {}
    for name, spec in (data.get("packs") or {}).items():
        name = str(name)
        if not name or not set(name) <= _PACK_NAME_OK:
            raise InstallError(f"{path}: invalid pack name {name!r}")
        if name in reserved:
            raise InstallError(f"{path}: pack {name!r} collides with a built-in pack")
        if not isinstance(spec, dict):
            raise InstallError(f"{path}: pack {name!r} must be a mapping")
        prefix = spec.get("prefix")
        skills = spec.get("skills") or []
        if prefix is not None and (not isinstance(prefix, str) or not prefix):
            raise InstallError(f"{path}: pack {name!r}: `prefix` must be a non-empty string")
        if not isinstance(skills, list) or not all(isinstance(x, str) and x for x in skills):
            raise InstallError(f"{path}: pack {name!r}: `skills` must be a list of names")
        if not prefix and not skills:
            raise InstallError(f"{path}: pack {name!r} needs a `prefix` and/or `skills`")
        out[name] = {
            "prefix": prefix or None,
            "skills": tuple(skills),
            "description": str(spec.get("description") or ""),
        }
    return out


try:
    EXTRA_PACKS: dict[str, dict] = load_extra_packs()
    _EXTRA_PACKS_ERROR: str | None = None
except InstallError as _e:  # surfaced (fail closed) by _require_extra_packs()
    EXTRA_PACKS = {}
    _EXTRA_PACKS_ERROR = str(_e)

ALL_PACKS = MANIFEST_PACKS + tuple(EXTRA_PACKS) + BUILTIN_OWNED_PACKS + (WF_TOOLS_PACK,)


def _require_extra_packs() -> None:
    if _EXTRA_PACKS_ERROR:
        raise InstallError(_EXTRA_PACKS_ERROR)


def extra_pack_of(skill: str) -> str | None:
    """The extra (private-data) pack that claims `skill`, or None."""
    for name, spec in EXTRA_PACKS.items():
        if skill in spec["skills"] or (spec["prefix"] and skill.startswith(spec["prefix"])):
            return name
    return None


def _extra_pack_source(spec: dict) -> str:
    """Human label for how an extra pack resolves (used by --list-packs)."""
    if spec["prefix"] and spec["skills"]:
        return f"{spec['prefix']}* prefix + allowlist"
    if spec["prefix"]:
        return f"{spec['prefix']}* prefix"
    return "private allowlist"


# --------------------------------------------------------------------------- #
# Manifest + pack resolver
# --------------------------------------------------------------------------- #
def load_manifest_map() -> dict[str, str]:
    """skill canonicalId -> module, from the authoritative CSV. Fail closed if the
    manifest is missing or malformed (no silent empty map)."""
    _require_extra_packs()
    if not MANIFEST.is_file():
        raise InstallError(f"missing skill manifest: {MANIFEST}")
    out: dict[str, str] = {}
    with MANIFEST.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "canonicalId" not in reader.fieldnames or "module" not in reader.fieldnames:
            raise InstallError(
                f"malformed manifest {MANIFEST}: expected canonicalId,module columns"
            )
        for row in reader:
            cid = (row.get("canonicalId") or "").strip()
            mod = (row.get("module") or "").strip()
            if cid:
                out[cid] = mod
    if not out:
        raise InstallError(f"empty skill manifest: {MANIFEST}")
    return out


def installed_skill_dirs() -> set[str]:
    """Skill dir names actually present in the source .claude/skills/."""
    if not SKILLS_DIR.is_dir():
        raise InstallError(f"source skills dir not found: {SKILLS_DIR}")
    return {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}


def resolve_pack_skills(pack: str, manifest: dict[str, str], present: set[str]) -> list[str]:
    """Resolve ONE pack to the set of skill dir names it owns. Returns a sorted
    list of names that ALSO exist on disk. `wf-tools` owns no skills -> []."""
    if pack not in ALL_PACKS:
        raise InstallError(
            f"unknown pack '{pack}'. Known packs: {', '.join(ALL_PACKS)}"
        )
    if pack == WF_TOOLS_PACK:
        return []
    if pack in MANIFEST_PACKS:
        names = {cid for cid, mod in manifest.items() if mod == pack}
    elif pack in EXTRA_PACKS:
        spec = EXTRA_PACKS[pack]
        names = set(spec["skills"])
        if spec["prefix"]:
            names |= {n for n in present if n.startswith(spec["prefix"])}
    elif pack == "custom":
        names = set(CUSTOM_BMAD_SKILLS)
    elif pack == "workflow":
        names = set(WORKFLOW_SKILLS)
    elif pack == "writer":
        names = set(WRITER_SKILLS)
    elif pack == "3d":
        names = set(THREED_SKILLS)
    else:  # pragma: no cover - guarded above
        raise InstallError(f"unhandled pack '{pack}'")
    return sorted(n for n in names if n in present)


def resolve_packs(packs: list[str], manifest: dict[str, str], present: set[str]) -> dict[str, list[str]]:
    """pack -> sorted skill dir names, for a list of packs (deduped, order kept)."""
    seen: list[str] = []
    for p in packs:
        if p not in seen:
            seen.append(p)
    return {p: resolve_pack_skills(p, manifest, present) for p in seen}


def wf_tools_files() -> list[Path]:
    """The wf CLI tool family copied for the wf-tools pack: scripts/wf + every
    scripts/wf-*.py. Paths are repo-relative source files."""
    files = [SCRIPTS / "wf"]
    files += sorted(SCRIPTS.glob("wf-*.py"))
    return [f for f in files if f.is_file()]


# --------------------------------------------------------------------------- #
# Adapter target file mapping (reuse generate-adapters output tree)
# --------------------------------------------------------------------------- #
def adapter_src_dir(profile: str, target: str) -> Path:
    return ADAPTERS_DIR / profile / target


def ensure_adapters(profile: str) -> None:
    """Make sure adapters/<profile>/ exists; auto-run the renderer once if not.
    Mirrors wf-scaffold's claude_md_for() reuse — never forks the renderer."""
    if (ADAPTERS_DIR / profile).is_dir():
        return
    gen = SCRIPTS / "generate-adapters.py"
    if gen.is_file():
        subprocess.run(
            [sys.executable, str(gen)], cwd=str(REPO_ROOT),
            capture_output=True, text=True,
        )
    if not (ADAPTERS_DIR / profile).is_dir():
        raise InstallError(
            f"no rendered adapters for profile '{profile}' at "
            f"{ADAPTERS_DIR / profile}. Run `python3 scripts/generate-adapters.py` first."
        )


def target_out_root(out: Path, target: str) -> Path:
    """Where a target's adapter tree lands in <out>. Claude is special-cased to
    .claude/ (its CLAUDE.generated.md sits beside the copied skills subset);
    every other target gets its own <out>/<target>/ subtree, preserving the
    renderer's internal layout (e.g. codex/AGENTS.md, copilot/.github/...)."""
    if target == "claude":
        return out / ".claude"
    return out / target


def copy_target_adapter(out: Path, profile: str, target: str) -> list[str]:
    """Copy the rendered adapter tree for (profile, target) into <out>. Returns
    the list of out-relative file paths written."""
    src = adapter_src_dir(profile, target)
    if not src.is_dir():
        raise InstallError(
            f"no rendered adapter for target '{target}' / profile '{profile}' "
            f"(expected {src}). Run `python3 scripts/generate-adapters.py`."
        )
    written: list[str] = []
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        if target == "claude":
            # claude/CLAUDE.generated.md -> <out>/.claude/CLAUDE.generated.md
            dst = out / ".claude" / rel
        else:
            dst = out / target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        written.append(dst.relative_to(out).as_posix())
    return written


# --------------------------------------------------------------------------- #
# Manifest (workflow.packs.yaml) read/write
# --------------------------------------------------------------------------- #
def manifest_path(out: Path) -> Path:
    return out / "workflow.packs.yaml"


def _yaml_list(items) -> str:
    if not items:
        return " []"
    return "\n" + "\n".join(f"  - {i}" for i in items)


def write_packs_manifest(
    out: Path, profile: str, packs: dict[str, list[str]], targets: list[str]
) -> Path:
    """Emit workflow.packs.yaml. Hand-rolled emitter (flat, deterministic) so the
    file is readable and stable; consumed back by a tolerant reader below."""
    skills = sorted({s for names in packs.values() for s in names})
    lines: list[str] = []
    lines.append(f"# {GENERATED_NOTE}")
    lines.append(f"version: {MANIFEST_VERSION}")
    lines.append(f"generated: {datetime.date.today().isoformat()}")
    lines.append(f"profile: {profile}")
    lines.append("packs:" + _yaml_list(list(packs.keys())))
    lines.append("targets:" + _yaml_list(targets))
    # Per-pack resolved skills + counts (the contract `check` validates against).
    lines.append("resolved:")
    for pack, names in packs.items():
        lines.append(f"  {pack}:")
        lines.append(f"    count: {len(names)}")
        lines.append("    skills:" + (_yaml_list(names).replace("\n  - ", "\n      - ") if names else " []"))
    lines.append(f"skills_total: {len(skills)}")
    lines.append("skills:" + _yaml_list(skills))
    text = "\n".join(lines) + "\n"
    mpath = manifest_path(out)
    mpath.write_text(text, encoding="utf-8")
    return mpath


def read_packs_manifest(out: Path) -> dict:
    """Parse workflow.packs.yaml. Prefer PyYAML; fall back to a minimal parser
    covering exactly the shape we emit. Fail closed on a missing/garbage file."""
    mpath = manifest_path(out)
    if not mpath.is_file():
        raise InstallError(f"no workflow.packs.yaml in {out}")
    text = mpath.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise InstallError(f"{mpath}: not a YAML mapping")
        return data
    except ImportError:
        pass
    return _parse_packs_manifest_minimal(text, mpath)


def _parse_packs_manifest_minimal(text: str, mpath: Path) -> dict:
    """Tiny parser for the exact (flat + one nested `resolved`) shape we write."""
    data: dict = {"packs": [], "targets": [], "skills": [], "resolved": {}}
    section = None  # None | 'packs' | 'targets' | 'skills' | 'resolved'
    cur_pack = None
    cur_skills_field = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        s = raw.strip()
        if indent == 0:
            cur_pack = None
            cur_skills_field = False
            if s.startswith("packs:"):
                section = "packs"
                _inline_list(s, data, "packs")
            elif s.startswith("targets:"):
                section = "targets"
                _inline_list(s, data, "targets")
            elif s.startswith("skills:"):
                section = "skills"
                _inline_list(s, data, "skills")
            elif s == "resolved:":
                section = "resolved"
            elif ":" in s:
                k, _, v = s.partition(":")
                data[k.strip()] = _scalar(v.strip())
            continue
        if section in ("packs", "targets", "skills") and s.startswith("- "):
            data[section].append(s[2:].strip())
            continue
        if section == "resolved":
            if indent == 2 and s.endswith(":"):
                cur_pack = s[:-1].strip()
                data["resolved"][cur_pack] = {"count": 0, "skills": []}
                cur_skills_field = False
            elif indent == 4 and s.startswith("count:"):
                data["resolved"].setdefault(cur_pack, {"skills": []})["count"] = _scalar(
                    s.split(":", 1)[1].strip()
                )
                cur_skills_field = False
            elif indent == 4 and s.startswith("skills:"):
                cur_skills_field = True
                rest = s.split(":", 1)[1].strip()
                if rest == "[]":
                    data["resolved"][cur_pack]["skills"] = []
            elif cur_skills_field and s.startswith("- "):
                data["resolved"][cur_pack]["skills"].append(s[2:].strip())
    return data


def _inline_list(s: str, data: dict, key: str) -> None:
    rest = s.split(":", 1)[1].strip()
    if rest == "[]":
        data[key] = []


def _scalar(v: str):
    v = v.strip().strip('"').strip("'")
    if v.isdigit():
        return int(v)
    return v


# --------------------------------------------------------------------------- #
# Materialize
# --------------------------------------------------------------------------- #
def _skill_description(name: str) -> str:
    """Best-effort frontmatter `description:` extraction for the portable
    INDEX. Tolerant: returns the skill name on any parse miss (never raises)."""
    try:
        text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        in_fm = False
        for line in text.splitlines():
            if line.strip() == "---":
                if in_fm:
                    break
                in_fm = True
                continue
            if in_fm and line.startswith("description:"):
                desc = line.split(":", 1)[1].strip().strip("'\"")
                desc = desc.replace("''", "'")  # YAML single-quote escape
                return desc or name
    except OSError:
        pass
    return name


def write_portable_index(dst_root: Path, names: list[str]) -> Path:
    """Emit skills/INDEX.md: the trigger->file map + the one-line wiring
    instruction for non-Claude hosts (AGENTS.md / GEMINI.md / system prompt)."""
    lines = [
        "# Skills index (portable)",
        "",
        f"<!-- {GENERATED_NOTE} -->",
        "",
        "Each directory below is a self-contained markdown playbook (SKILL.md",
        "plus any references/ it loads). To wire these into a non-Claude agent",
        "(Codex/GPT via AGENTS.md, Gemini via GEMINI.md, Copilot instructions,",
        "or any system prompt), add ONE line to the instruction file:",
        "",
        "> When a request matches a trigger in `skills/INDEX.md`, read that",
        "> skill's `SKILL.md` and follow it for the rest of the task.",
        "",
        "| Skill | Fires when | File |",
        "|---|---|---|",
    ]
    for name in names:
        desc = _skill_description(name).replace("|", "\\|")
        lines.append(f"| `{name}` | {desc} | `{name}/SKILL.md` |")
    ipath = dst_root / "INDEX.md"
    ipath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ipath


def materialize(
    out: Path, profile: str, packs: dict[str, list[str]], targets: list[str]
) -> dict:
    """Write the selection into <out>. Returns a small summary dict."""
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {
        "skills_copied": [],
        "portable_skills": [],
        "target_files": {},
        "wf_tools": [],
    }

    selected_skills = sorted({s for names in packs.values() for s in names})

    # claude target -> copy the SUBSET of skills + the claude adapter.
    if "claude" in targets:
        dst_skills = out / ".claude" / "skills"
        dst_skills.mkdir(parents=True, exist_ok=True)
        for name in selected_skills:
            src = SKILLS_DIR / name
            if not src.is_dir():
                raise InstallError(f"selected skill not found on disk: {src}")
            dst = dst_skills / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            summary["skills_copied"].append(name)

    # Non-claude target(s) -> materialize the PORTABLE skill tree: plain
    # markdown copies of the selected skills (SKILL.md + references/assets/
    # scripts; evals/ and .decision-log.md are harness-internal) plus a
    # generated skills/INDEX.md mapping trigger phrases to files. Codex/GPT,
    # Gemini, Copilot, and local agents consume it via one documented line in
    # their instruction file (see the INDEX.md header).
    if any(t != "claude" for t in targets) and selected_skills:
        dst_root = out / "skills"
        dst_root.mkdir(parents=True, exist_ok=True)
        ignore = shutil.ignore_patterns("evals", ".decision-log.md")
        for name in selected_skills:
            src = SKILLS_DIR / name
            if not src.is_dir():
                raise InstallError(f"selected skill not found on disk: {src}")
            dst = dst_root / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=ignore)
            summary["portable_skills"].append(name)
        write_portable_index(dst_root, selected_skills)

    # Every chosen target -> render its adapter tree.
    for t in targets:
        summary["target_files"][t] = copy_target_adapter(out, profile, t)

    # wf-tools pack -> copy the wf CLI scripts.
    if WF_TOOLS_PACK in packs:
        dst_scripts = out / "scripts"
        dst_scripts.mkdir(parents=True, exist_ok=True)
        for f in wf_tools_files():
            dst = dst_scripts / f.name
            shutil.copy2(f, dst)
            summary["wf_tools"].append(f.name)

    write_packs_manifest(out, profile, packs, targets)
    return summary


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
def _expected_target_files(out: Path, profile: str, target: str) -> list[Path]:
    src = adapter_src_dir(profile, target)
    root = target_out_root(out, target)
    expected: list[Path] = []
    if not src.is_dir():
        return expected
    for p in sorted(src.rglob("*")):
        if p.is_file():
            expected.append(root / p.relative_to(src))
    return expected


def check_install(out: Path) -> int:
    """Validate workflow.packs.yaml is well-formed AND the on-disk state matches.
    FAIL CLOSED (exit 1) on any mismatch / unknown pack / unknown target."""
    try:
        data = read_packs_manifest(out)
    except InstallError as e:
        print(f"wf install check: FAIL — {e}")
        return 1

    problems: list[str] = []
    packs = data.get("packs") or []
    targets = data.get("targets") or []
    if not packs:
        problems.append("manifest lists no packs")
    if not targets:
        problems.append("manifest lists no targets")

    for p in packs:
        if p not in ALL_PACKS:
            problems.append(f"unknown pack in manifest: {p}")
    for t in targets:
        if t not in VALID_TARGETS:
            problems.append(f"unknown target in manifest: {t}")
    profile = data.get("profile")
    if profile not in VALID_PROFILES:
        problems.append(f"unknown/absent profile in manifest: {profile!r}")

    # Re-resolve the recorded packs against the LIVE manifest and compare to the
    # recorded `resolved` block, so a tampered inventory is caught.
    if not problems:
        try:
            mmap = load_manifest_map()
            present = installed_skill_dirs()
            live = resolve_packs(list(packs), mmap, present)
        except InstallError as e:
            print(f"wf install check: FAIL — {e}")
            return 1
        recorded = data.get("resolved") or {}
        for pack, names in live.items():
            rec = recorded.get(pack) or {}
            rec_skills = sorted(rec.get("skills") or [])
            if rec_skills != names:
                problems.append(
                    f"pack '{pack}': manifest records {len(rec_skills)} skills "
                    f"but resolver gives {len(names)}"
                )

        expected_skills = sorted({s for names in live.values() for s in names})

        # Non-claude target(s): the PORTABLE skill tree must be present with
        # exactly the selection + INDEX.md; no leaked extras.
        if any(t != "claude" for t in targets) and expected_skills:
            pdir = out / "skills"
            if not pdir.is_dir():
                problems.append("non-claude target selected but <out>/skills missing")
            else:
                p_disk = sorted(d.name for d in pdir.iterdir() if d.is_dir())
                for m in [s for s in expected_skills if s not in p_disk]:
                    problems.append(f"missing portable skill: {m}")
                for x in [s for s in p_disk if s not in expected_skills]:
                    problems.append(f"unexpected portable skill (not in selection): {x}")
                if not (pdir / "INDEX.md").is_file():
                    problems.append("portable skills INDEX.md missing")

        # claude: the recorded skill SUBSET must be present, and NO non-selected
        # skill may have leaked into <out>/.claude/skills.
        if "claude" in targets:
            sk_dir = out / ".claude" / "skills"
            if not sk_dir.is_dir():
                problems.append("claude selected but <out>/.claude/skills missing")
            else:
                on_disk = sorted(d.name for d in sk_dir.iterdir() if d.is_dir())
                missing = [s for s in expected_skills if s not in on_disk]
                extra = [s for s in on_disk if s not in expected_skills]
                for m in missing:
                    problems.append(f"missing materialized skill: {m}")
                for x in extra:
                    problems.append(f"unexpected skill present (not in selection): {x}")

        # Every target's adapter files must exist.
        for t in targets:
            for ef in _expected_target_files(out, profile, t):
                if not ef.is_file():
                    problems.append(
                        f"missing {t} adapter file: {ef.relative_to(out).as_posix()}"
                    )

        # wf-tools, if selected, must have its scripts.
        if WF_TOOLS_PACK in packs:
            for f in wf_tools_files():
                if not (out / "scripts" / f.name).is_file():
                    problems.append(f"missing wf-tools script: scripts/{f.name}")

    if problems:
        print(f"wf install check: FAIL ({len(problems)} issue(s))")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(
        f"wf install check: OK ({len(packs)} pack(s), {len(targets)} target(s), "
        f"profile {profile}, {data.get('skills_total', '?')} skill(s) materialized)"
    )
    return 0


# --------------------------------------------------------------------------- #
# Interactive picker
# --------------------------------------------------------------------------- #
def _pick(prompt: str, options: tuple[str, ...], default: tuple[str, ...]) -> list[str]:
    print(prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    print(f"  (comma-separated numbers or names; Enter = {','.join(default)})")
    try:
        raw = input("> ").strip()
    except EOFError:
        raw = ""
    if not raw:
        return list(default)
    chosen: list[str] = []
    for tok in raw.replace(" ", "").split(","):
        if not tok:
            continue
        if tok.isdigit():
            idx = int(tok) - 1
            if 0 <= idx < len(options):
                chosen.append(options[idx])
            else:
                _die(f"selection out of range: {tok}")
        else:
            chosen.append(tok)
    return chosen


# --------------------------------------------------------------------------- #
# list-packs
# --------------------------------------------------------------------------- #
def list_packs() -> int:
    try:
        mmap = load_manifest_map()
        present = installed_skill_dirs()
    except InstallError as e:
        _die(str(e))
    print("Available packs (pack -> skill count):")
    for pack in ALL_PACKS:
        names = resolve_pack_skills(pack, mmap, present)
        if pack == WF_TOOLS_PACK:
            n = len(wf_tools_files())
            print(f"  {pack:10s}  {n:3d} script(s)  (the wf CLI tool family; not skills)")
        else:
            if pack in MANIFEST_PACKS:
                src = "manifest"
            elif pack in EXTRA_PACKS:
                src = _extra_pack_source(EXTRA_PACKS[pack])
            else:
                src = "owned bmad-* allowlist"
            print(f"  {pack:10s}  {len(names):3d} skill(s)  (resolved via {src})")
    print(f"\nTargets: {', '.join(VALID_TARGETS)}")
    print(f"Profiles: {', '.join(VALID_PROFILES)}")
    return 0


# --------------------------------------------------------------------------- #
# install (the default action)
# --------------------------------------------------------------------------- #
def do_install(args: argparse.Namespace) -> int:
    out = Path(args.out).resolve()
    try:
        mmap = load_manifest_map()
        present = installed_skill_dirs()
    except InstallError as e:
        _die(str(e))

    interactive = sys.stdin is not None and sys.stdin.isatty()

    # Packs
    if args.packs:
        packs = [p for p in args.packs.split(",") if p]
    elif interactive:
        packs = _pick("Choose PACKS (modules) to install:", ALL_PACKS, DEFAULT_PACKS)
    else:
        packs = list(DEFAULT_PACKS)
        print(f"wf install: no --packs given (non-interactive) — defaulting to {','.join(packs)}")

    # Targets
    if args.targets:
        targets = [t for t in args.targets.split(",") if t]
    elif interactive:
        targets = _pick("Choose AI agent TARGETS to install for:", VALID_TARGETS, DEFAULT_TARGETS)
    else:
        targets = list(DEFAULT_TARGETS)
        print(f"wf install: no --targets given (non-interactive) — defaulting to {','.join(targets)}")

    # Profile
    profile = args.profile or DEFAULT_PROFILE

    # Fail closed on unknown selections BEFORE touching the filesystem.
    if profile not in VALID_PROFILES:
        _die(f"unknown profile '{profile}'. Valid: {', '.join(VALID_PROFILES)}")
    for t in targets:
        if t not in VALID_TARGETS:
            _die(f"unknown target '{t}'. Valid: {', '.join(VALID_TARGETS)}")
    try:
        resolved = resolve_packs(packs, mmap, present)  # raises on unknown pack
        ensure_adapters(profile)
        summary = materialize(out, profile, resolved, targets)
    except InstallError as e:
        _die(str(e))

    total_skills = len(summary["skills_copied"]) if "claude" in targets else len(
        {s for names in resolved.values() for s in names}
    )
    print(f"wf install: materialized into {out}")
    print(f"  profile: {profile}")
    print(f"  packs:   {', '.join(resolved.keys())}")
    print(f"  targets: {', '.join(targets)}")
    if "claude" in targets:
        print(f"  copied {len(summary['skills_copied'])} skill(s) into .claude/skills/")
    if summary["portable_skills"]:
        print(f"  copied {len(summary['portable_skills'])} skill(s) into skills/ "
              f"(portable tree + INDEX.md for non-Claude agents)")
    elif "claude" not in targets:
        print(f"  {total_skills} skill(s) selected (no skills in selection to materialize)")
    if summary["wf_tools"]:
        print(f"  copied {len(summary['wf_tools'])} wf-tools script(s) into scripts/")
    for t in targets:
        print(f"  {t}: {len(summary['target_files'][t])} adapter file(s)")
    print(f"  manifest: {manifest_path(out).relative_to(out)}")
    print("Run `wf install check --dir <out>` to validate.")
    return 0


# --------------------------------------------------------------------------- #
# selftest (with teeth)
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def _quiet(stderr: bool = False):
    """Suppress stdout (and optionally stderr) from the inner do_install/
    check_install calls so the selftest emits only its final PASS/FAIL line
    (keeps doctor's grep clean)."""
    with contextlib.redirect_stdout(io.StringIO()):
        if stderr:
            with contextlib.redirect_stderr(io.StringIO()):
                yield
        else:
            yield


def selftest() -> int:
    problems: list[str] = []

    # Resolver coverage: every non-manifest skill claimed by exactly one of
    # the extra (private-data) packs + custom/workflow/writer/3d (no orphan, no
    # double-claim) — keeps the fallback honest.
    try:
        mmap = load_manifest_map()
        present = installed_skill_dirs()
    except InstallError as e:
        print(f"wf install selftest: FAIL — {e}")
        return 1
    manifest_skills = set(mmap)
    non_manifest = {s for s in present if s not in manifest_skills}
    pairs = tuple(
        (p, set(resolve_pack_skills(p, mmap, present)))
        for p in tuple(EXTRA_PACKS) + BUILTIN_OWNED_PACKS
    )
    claimed: set[str] = set().union(*(s for _, s in pairs))
    for (an, a), (bn, b) in itertools.combinations(pairs, 2):
        if a & b:
            problems.append(f"{an}/{bn} double-claim: {sorted(a & b)}")
    orphan = non_manifest - claimed
    if orphan:
        problems.append(f"non-manifest skills no pack claims: {sorted(orphan)}")
    overclaim = claimed - present
    if overclaim:
        problems.append(f"custom allowlist names a skill not on disk: {sorted(overclaim)}")

    # Extra-pack data file: parses (PyYAML and the minimal fallback agree),
    # absent file -> no extra packs, malformed / colliding file fails closed.
    with tempfile.TemporaryDirectory(prefix="wf-install-packs-") as td:
        pf = Path(td) / "packs.yaml"
        if load_extra_packs(pf) != {}:
            problems.append("absent extra-pack file did not yield an empty registry")
        fixture = (
            "packs:\n"
            "  acme:\n"
            '    prefix: "acme-"\n'
            '    description: "fixture prefix pack"\n'
            "  tools:\n"
            "    skills:\n"
            "      - tool-a\n"
            "      - tool-b\n"
        )
        pf.write_text(fixture, encoding="utf-8")
        want = {
            "acme": {"prefix": "acme-", "skills": (), "description": "fixture prefix pack"},
            "tools": {"prefix": None, "skills": ("tool-a", "tool-b"), "description": ""},
        }
        try:
            got = load_extra_packs(pf)
            if got != want or list(got) != ["acme", "tools"]:
                problems.append(f"extra-pack file parsed wrong: {got}")
        except InstallError as e:
            problems.append(f"valid extra-pack file rejected: {e}")
        if _parse_packs_minimal(fixture) != {"packs": {
            "acme": {"prefix": "acme-", "description": "fixture prefix pack"},
            "tools": {"skills": ["tool-a", "tool-b"]},
        }}:
            problems.append("minimal extra-pack parser disagrees with the fixture")
        for bad in ("packs:\n  custom:\n    prefix: x-\n",   # built-in collision
                    "packs:\n  acme:\n    description: d\n",  # no prefix/skills
                    "packs: [1, 2]\n"):                        # wrong shape
            pf.write_text(bad, encoding="utf-8")
            try:
                load_extra_packs(pf)
                problems.append(f"malformed extra-pack file accepted: {bad!r}")
            except InstallError:
                pass

    with tempfile.TemporaryDirectory(prefix="wf-install-selftest-") as td:
        out = Path(td) / "proj"
        # Install core+tea for claude+codex.
        ns = argparse.Namespace(
            out=str(out), packs="core,tea", targets="claude,codex", profile="civilian"
        )
        try:
            with _quiet():
                rc = do_install(ns)
        except SystemExit as e:
            problems.append(f"do_install raised SystemExit({e.code})")
            rc = 1
        if rc != 0:
            problems.append("do_install returned non-zero on a valid selection")

        sk = out / ".claude" / "skills"
        on_disk = {d.name for d in sk.iterdir() if d.is_dir()} if sk.is_dir() else set()

        # TEETH 1: ONLY selected packs materialized. A bmm/gds skill must be ABSENT.
        core_set = set(resolve_pack_skills("core", mmap, present))
        tea_set = set(resolve_pack_skills("tea", mmap, present))
        expected = core_set | tea_set
        if on_disk != expected:
            problems.append(
                f"materialized skill set != core+tea "
                f"(missing {sorted(expected - on_disk)}, extra {sorted(on_disk - expected)})"
            )
        bmm_set = set(resolve_pack_skills("bmm", mmap, present))
        gds_set = set(resolve_pack_skills("gds", mmap, present))
        leaked = on_disk & (bmm_set | gds_set)
        if leaked:
            problems.append(f"NON-selected pack skills leaked in: {sorted(leaked)}")
        # Concrete witnesses: a known bmm skill and a known gds skill are absent.
        for witness in ("bmad-create-prd", "gds-gdd"):
            if witness in present and witness in on_disk:
                problems.append(f"non-selected witness skill present: {witness}")

        # TEETH 2: chosen target adapters exist.
        if not (out / ".claude" / "CLAUDE.generated.md").is_file():
            problems.append("claude adapter (CLAUDE.generated.md) missing")
        if not (out / "codex" / "AGENTS.md").is_file():
            problems.append("codex adapter (AGENTS.md) missing")

        # TEETH 2b: codex selected -> portable skill tree exists with exactly
        # the selection + INDEX.md, and INDEX names a witness skill; check
        # fails closed when INDEX.md is deleted.
        pdir = out / "skills"
        p_disk = {d.name for d in pdir.iterdir() if d.is_dir()} if pdir.is_dir() else set()
        if p_disk != expected:
            problems.append(
                f"portable skill set != core+tea "
                f"(missing {sorted(expected - p_disk)}, extra {sorted(p_disk - expected)})"
            )
        idx = pdir / "INDEX.md"
        if not idx.is_file():
            problems.append("portable skills INDEX.md missing")
        else:
            idx_text = idx.read_text(encoding="utf-8")
            witness = next(iter(expected), None)
            if witness and f"`{witness}`" not in idx_text:
                problems.append(f"INDEX.md does not list witness skill {witness}")
            if any((pdir / n / "evals").is_dir() for n in p_disk):
                problems.append("portable tree leaked an evals/ dir (harness-internal)")
            idx.unlink()
            with _quiet():
                noidx_rc = check_install(out)
            if noidx_rc == 0:
                problems.append("check PASSED with portable INDEX.md deleted (no teeth)")
            idx.write_text(idx_text, encoding="utf-8")

        # TEETH 3: workflow.packs.yaml records the choices.
        try:
            data = read_packs_manifest(out)
            if sorted(data.get("packs") or []) != ["core", "tea"]:
                problems.append(f"manifest packs wrong: {data.get('packs')}")
            if sorted(data.get("targets") or []) != ["claude", "codex"]:
                problems.append(f"manifest targets wrong: {data.get('targets')}")
        except InstallError as e:
            problems.append(f"manifest unreadable: {e}")

        # TEETH 4: check passes on the good install.
        with _quiet():
            good_rc = check_install(out)
        if good_rc != 0:
            problems.append("check FAILED on a known-good install")

        # TEETH 5: fail closed on a planted mismatch (delete a required skill).
        victim = next(iter(expected & on_disk), None)
        if victim:
            shutil.rmtree(sk / victim)
            with _quiet():
                broke_rc = check_install(out)
            if broke_rc == 0:
                problems.append("check PASSED after a required skill was deleted (no teeth)")
            # restore so later teeth aren't confused
            shutil.copytree(SKILLS_DIR / victim, sk / victim)

        # TEETH 6: fail closed on an unexpected (non-selected) skill present.
        intruder = next((s for s in (bmm_set | gds_set) if s in present), None)
        if intruder:
            shutil.copytree(SKILLS_DIR / intruder, sk / intruder)
            with _quiet():
                intr_rc = check_install(out)
            if intr_rc == 0:
                problems.append("check PASSED with a non-selected skill present (no teeth)")
            shutil.rmtree(sk / intruder)

        # TEETH 7: fail closed on an unknown pack / unknown target at install time.
        try:
            with _quiet(stderr=True):
                do_install(argparse.Namespace(
                    out=str(Path(td) / "bad"), packs="core,boguspack",
                    targets="claude", profile="civilian"))
            problems.append("install accepted an unknown pack (no fail-closed)")
        except SystemExit as e:
            if e.code != 2:
                problems.append(f"unknown pack exit code {e.code}, expected 2")
        try:
            with _quiet(stderr=True):
                do_install(argparse.Namespace(
                    out=str(Path(td) / "bad2"), packs="core",
                    targets="claude,bogustarget", profile="civilian"))
            problems.append("install accepted an unknown target (no fail-closed)")
        except SystemExit as e:
            if e.code != 2:
                problems.append(f"unknown target exit code {e.code}, expected 2")

        # TEETH 8: a non-selected pack (e.g. bmm) is fully absent from <out>.
        if bmm_set and (bmm_set & on_disk):
            problems.append("bmm pack present despite not being selected")

    if problems:
        print("wf install selftest: FAIL — " + "; ".join(problems))
        return 1
    print(
        f"wf install selftest: PASS (extra-pack data file parsed + fails closed "
        f"when malformed; {len(EXTRA_PACKS)} extra pack(s) loaded; "
        f"core+tea materialized for claude+codex; "
        f"only-selected-packs verified [bmm/gds absent]; portable skills/ tree "
        f"+ INDEX.md for the codex target [evals stripped, fails closed on "
        f"deleted INDEX]; check fails closed on deleted skill, intruder skill, "
        f"unknown pack, unknown target; manifest records the choices)"
    )
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wf install",
        description="Pick PACKS (modules) + AI agent TARGETS and materialize them into a project.",
    )
    ap.add_argument("--out", help="output directory to materialize into")
    ap.add_argument("--packs", help="comma-separated packs (default: interactive / core)")
    ap.add_argument("--targets", help="comma-separated targets (default: interactive / claude)")
    ap.add_argument("--profile", help=f"profile id (default {DEFAULT_PROFILE}); one of {', '.join(VALID_PROFILES)}")
    ap.add_argument("--list-packs", action="store_true", help="list packs + skill counts and exit")
    ap.add_argument("--selftest", action="store_true", help="run built-in self-test and exit")
    return ap


def main(argv: list[str]) -> int:
    # `wf install check --dir DIR` subcommand (kept separate from the flag flow).
    if argv and argv[0] == "check":
        sub = argparse.ArgumentParser(prog="wf install check")
        sub.add_argument("--dir", required=True, help="installed project dir to validate")
        a = sub.parse_args(argv[1:])
        try:
            return check_install(Path(a.dir).resolve())
        except InstallError as e:
            print(f"wf install check: FAIL — {e}")
            return 1

    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest()
    if args.list_packs:
        return list_packs()
    if not args.out:
        build_parser().error("--out is required (or use --list-packs / --selftest / `check --dir`)")
    return do_install(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
