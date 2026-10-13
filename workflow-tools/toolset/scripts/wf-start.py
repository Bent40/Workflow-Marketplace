#!/usr/bin/env python3
"""wf-start.py — project boot scanner + creation mode (milestones M1+M2+M3).

Scans a project directory and reports, in one readout, everything the
workflow toolset knows how to see there:

  S0  mode        greenfield / brownfield, monorepo detection (repo-root
                  activation only — decision D4; --dir scopes to a package)
  S1  stack       languages, manifests/frameworks, test runners, CI,
                  containers, git ground truth
  S2  bmad        three-state install detector (full / glue / none), the
                  bmad-help artifact chain probed from the PROJECT'S OWN
                  config (never hardcoded paths), derived current phase +
                  next required step — a mid-flight project enters at its
                  phase, never back at phase 1
  S3  workflow    per-subsystem state: initialized / absent / opted_out
                  (opted_out only ever comes from a prior boot.json receipt)
  S4  readiness   memory / learn / audit always; profile-relative probes (M2)
  S5  size/risk   proposal in ambient-router vocabulary; --size persists
  S6  plan        envelope-scoped, authority-classed; --apply materializes
  M1 metrics      skills-with-a-firing-path vs installed, plus the
                  invocation-rate corpus emitter (--eval-corpus); the
                  model-graded baseline stays PENDING until a real run.

INVOLVEMENT ENVELOPE (M3, decision D5 — the user's ruling, question ZERO):
every plan is scoped to one of four envelopes and never pushes beyond it —
  observer   memory + learn + boot.json receipt ONLY (no packs, no block)
  satellite  observer + activation block (with absolute-path tool warnings
             baked in) + validation offer; NO install, packs auto-opted-out
  partial    satellite + user-chosen packs (--packs a,b subset)
  full       everything (install, block, config template, offers)
Unconfirmed, the envelope is PROPOSED from evidence (packs installed -> full;
activation block without packs -> satellite; else observer) and `--apply`
materializes only the observer-safe subset until it is ruled.

CREATION MODE (M3): a greenfield dir runs the interview — interactive on a
TTY, fully flag-driven otherwise (`--yes` accepts defaults) — with three
first-class variants: greenfield / takeover (the 103 question set, posture
FIRST; free-text answers recorded to boot.json takeover_notes) / satellite
adoption. Execution wraps the EXISTING tools (wf scaffold — greenfield
variant only — wf install, wf memory init, the block, boot.json). When
posture != civilian, `wf install --profile <posture>` runs BEFORE the block
render so the block reads the right posture (posture-first, 103 §2).

READ-ONLY by default: the scan never modifies the project; writes happen
only via --write / --apply / --decline / the confirmed creation plan.

FAIL-CLOSED LABELING: unparseable state is reported as `unparseable`/
`unknown`, never guessed and never a crash.

Usage:
  wf start [--dir DIR] [--json] [--write] [--new]
  wf start --involvement observer|satellite|partial|full   rule the envelope
  wf start --apply --involvement full --profile <p> --size <s> [--secure]
  wf start --dir <empty> [--variant takeover] [--yes] ...   creation mode
  wf start --eval-corpus [PATH]     emit the invocation-rate eval corpus
  wf start --selftest

Exit: scan -> 0 (a report is success even when the project is a mess);
2 on a config/usage error. selftest -> 0 PASS / 1 FAIL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:  # degrade per-probe, never die: this is a reporter
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = 1
BOOT_REL = Path("_workflow") / "boot.json"

# Directories never descended into during the stack walk.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", "target", ".next", ".nuxt", "coverage",
    "_bmad", "_bmad-output", ".claude", ".wf", ".bmad", "vendor", ".tox",
}
WALK_CAP = 20000  # files; beyond this the histogram is labeled "capped"

LANG_EXT = {
    ".py": "py", ".ts": "ts", ".tsx": "ts", ".js": "js", ".jsx": "js",
    ".go": "go", ".rs": "rs", ".rb": "rb", ".java": "java", ".kt": "kt",
    ".cs": "cs", ".cpp": "cpp", ".cc": "cpp", ".c": "c", ".swift": "swift",
    ".php": "php", ".ex": "ex", ".exs": "ex", ".gd": "gd", ".lua": "lua",
    ".sh": "sh", ".md": None, ".json": None, ".yaml": None, ".yml": None,
}

# Source extensions that make a dir "not greenfield" (docs alone don't).
SOURCE_EXTS = {e for e, l in LANG_EXT.items() if l is not None}

MANIFESTS = (
    "package.json", "pyproject.toml", "setup.py", "go.mod", "Cargo.toml",
    "Gemfile", "pom.xml", "build.gradle", "mix.exs", "project.godot",
)

TEST_CONFIG_HINTS = (
    ("pytest", ("pytest.ini", "conftest.py")),
    ("jest", ("jest.config.js", "jest.config.ts", "jest.config.mjs")),
    ("vitest", ("vitest.config.ts", "vitest.config.js", "vitest.config.mts")),
    ("playwright", ("playwright.config.ts", "playwright.config.js")),
    ("cypress", ("cypress.config.ts", "cypress.config.js")),
)

# package.json dependency name -> framework label (first match wins).
JS_FRAMEWORKS = (
    ("@nestjs/core", "nestjs"), ("next", "nextjs"), ("nuxt", "nuxt"),
    ("@sveltejs/kit", "sveltekit"), ("svelte", "svelte"), ("vue", "vue"),
    ("react", "react"), ("express", "express"), ("fastify", "fastify"),
)
PY_FRAMEWORKS = (
    ("django", "django"), ("fastapi", "fastapi"), ("flask", "flask"),
)

# The bmad-help artifact chain (§3 S2): probe order, phase reached when the
# artifact is present, and the skill that produces it when it is the gap.
ARTIFACT_CHAIN = (
    # key        phase-when-present     producer (= next_required when missing)
    ("brief",        "1-analysis",       "bmad-product-brief"),
    ("prd",          "2-plan",           "bmad-prd"),
    ("architecture", "3-solutioning",    "bmad-create-architecture"),
    ("epics",        "3-solutioning",    "bmad-create-epics-and-stories"),
    ("sprint",       "4-implementation", "bmad-sprint-planning"),
    ("stories",      "4-implementation", "bmad-create-story"),
)

INSTRUCTION_FILES = (
    "CLAUDE.md", "AGENTS.md", "GEMINI.md",
    ".github/copilot-instructions.md",
)

MEMORY_FILES = (
    "project-brief.md", "current-state.md", "decisions.md",
    "open-risks.md", "next-actions.md",
)


def _die(msg: str, code: int = 2) -> None:
    print(f"wf start: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml_text(text: str):
    """Parse YAML with PyYAML when available; else a minimal flat
    `key: value` fallback (enough for the scaffold's config glue). Returns
    None when the text cannot be parsed — callers label, never guess."""
    if yaml is not None:
        try:
            return yaml.safe_load(text)
        except Exception:
            return None
    flat: dict[str, object] = {}
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#") or line.startswith((" ", "\t")):
            continue
        if ":" not in line:
            return None  # structure the fallback can't represent
        key, _, val = line.partition(":")
        flat[key.strip()] = val.strip().strip("'\"") or None
    return flat


def _read_yaml(path: Path):
    try:
        return _load_yaml_text(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _git(root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


# ── S0 — mode detect ─────────────────────────────────────────────────────────


def detect_mode(root: Path, *, force_new: bool = False) -> dict:
    entries = [p for p in root.iterdir() if p.name != ".git"] if root.is_dir() else []
    has_source = False
    for p in root.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        if p.is_file() and p.suffix in SOURCE_EXTS:
            has_source = True
            break
    greenfield = force_new or not entries or not has_source and not any(
        p.is_file() and p.name in MANIFESTS for p in entries
    )

    mono_evidence: list[str] = []
    if (root / "pnpm-workspace.yaml").is_file():
        mono_evidence.append("pnpm-workspace.yaml")
    pkg = _read_json(root / "package.json")
    if isinstance(pkg, dict) and pkg.get("workspaces"):
        mono_evidence.append("package.json workspaces")
    depth1 = [
        d for d in entries
        if d.is_dir() and d.name not in SKIP_DIRS
        and any((d / m).is_file() for m in MANIFESTS)
    ]
    if len(depth1) >= 2 and not any((root / m).is_file() for m in MANIFESTS):
        mono_evidence.append(f"{len(depth1)} package dirs at depth 1, no root manifest")

    return {
        "mode": "greenfield" if greenfield else "brownfield",
        "monorepo": bool(mono_evidence),
        "monorepo_evidence": mono_evidence,
    }


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ── S1 — stack scan ──────────────────────────────────────────────────────────


def scan_stack(root: Path) -> dict:
    hist: dict[str, int] = {}
    seen = 0
    capped = False
    for p in root.rglob("*"):
        rel_parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if not p.is_file():
            continue
        seen += 1
        if seen > WALK_CAP:
            capped = True
            break
        lang = LANG_EXT.get(p.suffix)
        if lang:
            hist[lang] = hist.get(lang, 0) + 1
    langs = [l for l, _ in sorted(hist.items(), key=lambda kv: -kv[1])[:3]]

    manifests = [m for m in MANIFESTS if (root / m).is_file()]
    if (root / "ProjectSettings" / "ProjectVersion.txt").is_file():
        manifests.append("unity")
    if list(root.glob("*.uproject")):
        manifests.append("unreal")

    framework = None
    pkg = _read_json(root / "package.json")
    merged: dict = {}
    if isinstance(pkg, dict):
        merged.update(pkg.get("dependencies") or {})
        merged.update(pkg.get("devDependencies") or {})
        # 103 trace (§4.1): workspace-root blindness — react/express/pg live in
        # MEMBER manifests. Aggregate workspace members into the fingerprint.
        ws = pkg.get("workspaces")
        patterns = list(ws.get("packages") or []) if isinstance(ws, dict) else list(ws or [])
        pn = _read_yaml(root / "pnpm-workspace.yaml")
        if isinstance(pn, dict):
            patterns += list(pn.get("packages") or [])
        for pat in patterns[:20]:
            for mp in sorted(root.glob(str(pat).rstrip("/") + "/package.json"))[:20]:
                mj = _read_json(mp)
                if isinstance(mj, dict):
                    merged.update(mj.get("dependencies") or {})
                    merged.update(mj.get("devDependencies") or {})
        for dep, label in JS_FRAMEWORKS:
            if dep in merged:
                framework = label
                break
    # Field trace (102 takeover): a Next.js tree with NO UI surface is an
    # API service — web-app gates (browse/E2E/a11y) would be wrong for it.
    if framework == "nextjs":
        has_ui = ((root / "pages").is_dir() or (root / "public").is_dir()
                  or bool(list(root.glob("app/**/page.*"))))
        if not has_ui:
            framework = "nextjs-headless"
    if framework is None and (root / "pyproject.toml").is_file():
        try:
            pytext = (root / "pyproject.toml").read_text(encoding="utf-8")
        except OSError:
            pytext = ""
        for dep, label in PY_FRAMEWORKS:
            if re.search(rf'(?i)["\']{dep}', pytext):
                framework = label
                break

    tests: list[str] = []
    for runner, files in TEST_CONFIG_HINTS:
        if any((root / f).is_file() for f in files):
            tests.append(runner)
    if merged:
        for runner in ("vitest", "jest", "playwright", "cypress"):
            if runner in merged and runner not in tests:
                tests.append(runner)
    if (root / "pyproject.toml").is_file() and "pytest" not in tests:
        try:
            if "pytest" in (root / "pyproject.toml").read_text(encoding="utf-8"):
                tests.append("pytest")
        except OSError:
            pass

    ci = []
    if (root / ".github" / "workflows").is_dir():
        ci.append("github")
    if (root / ".gitlab-ci.yml").is_file():
        ci.append("gitlab")
    containers = bool(
        (root / "Dockerfile").is_file() or list(root.glob("docker-compose*"))
    )

    git_info: dict[str, object] = {"repo": False}
    if (root / ".git").exists():
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        status = _git(root, "status", "--porcelain")
        last = _git(root, "log", "-1", "--format=%ct")
        age_days = None
        if last and last.isdigit():
            age_days = max(0, int(
                (datetime.now(timezone.utc)
                 - datetime.fromtimestamp(int(last), tz=timezone.utc)).days
            ))
        git_info = {
            "repo": True,
            "branch": branch or "unknown",
            "dirty": bool(status) if status is not None else None,
            "last_commit_days": age_days,
        }

    return {
        "langs": langs,
        "framework": framework,
        "manifests": manifests,
        "tests": tests,
        "ci": ci,
        "containers": containers,
        "git": git_info,
        "file_count": seen,
        "walk_capped": capped,
        "merged_deps": sorted(merged),
    }


# ── S2 — BMAD situation ──────────────────────────────────────────────────────


def _bmad_paths(root: Path) -> tuple[Path, Path]:
    """(planning_artifacts, implementation_artifacts) resolved from the
    project's OWN _bmad/bmm/config.yaml — hardcoded fallback only when the
    config is absent/unparseable (and then labeled by the caller)."""
    cfg = _read_yaml(root / "_bmad" / "bmm" / "config.yaml")
    out = "_bmad-output"
    if isinstance(cfg, dict) and cfg.get("output_folder"):
        out = str(cfg["output_folder"])

    def _resolve(key: str, default: str) -> Path:
        raw = str(cfg.get(key)) if isinstance(cfg, dict) and cfg.get(key) else default
        raw = raw.replace("{project-root}", "").lstrip("/")
        return root / raw

    return (
        _resolve("planning_artifacts", f"{out}/planning-artifacts"),
        _resolve("implementation_artifacts", f"{out}/implementation-artifacts"),
    )


def scan_bmad(root: Path) -> dict:
    manifest = root / "_bmad" / "_config" / "manifest.yaml"
    glue_a = root / "_bmad" / "bmm" / "config.yaml"
    glue_b = root / "_bmad" / "core" / "config.yaml"

    if manifest.is_file():
        state = "full"
        m = _read_yaml(manifest)
        version = "unknown"
        if isinstance(m, dict):
            inst = m.get("installation")
            if isinstance(inst, dict) and inst.get("version"):
                version = str(inst["version"])
            elif m.get("version"):
                version = str(m["version"])
    elif glue_a.is_file() and glue_b.is_file():
        state, version = "glue", None
    else:
        note = None
        for alt in ("bmad", ".bmad-core"):
            if (root / alt).is_dir():
                note = (f"BMAD-like artifacts at nonstandard path {alt}/ — "
                        "not scanned (expected _bmad/); phase may be understated")
                break
        return {"state": "none", "version": None, "phase": None,
                "next_required": None, "artifacts": {}, "sprint_status": None,
                "note": note}

    planning, impl = _bmad_paths(root)

    def _found(pattern: str, base: Path) -> list[Path]:
        return sorted(base.rglob(pattern)) if base.is_dir() else []

    artifacts: dict[str, object] = {}
    artifacts["brief"] = bool(_found("*brief*.md", planning))
    prds = _found("*prd*.md", planning) or _found("PRD*.md", planning)
    prd_status = None
    if prds:
        head = prds[0].read_text(encoding="utf-8", errors="replace")[:2000]
        m2 = re.search(r"(?im)^status:\s*(\S+)", head)
        prd_status = m2.group(1) if m2 else "present"
    artifacts["prd"] = prd_status or False
    artifacts["architecture"] = bool(_found("*architecture*.md", planning))
    epics = _found("*epic*.md", planning)
    artifacts["epics"] = len(epics) if epics else False

    sprint_file = None
    for cand in _found("sprint-status.yaml", impl) + _found("sprint-status.yaml", planning):
        sprint_file = cand
        break
    sprint_summary = None
    sprint_stale_days = None
    if sprint_file:
        data = _read_yaml(sprint_file)
        dev = data.get("development_status") if isinstance(data, dict) else None
        if isinstance(dev, dict):
            counts: dict[str, int] = {}
            for v in dev.values():
                counts[str(v)] = counts.get(str(v), 0) + 1
            sprint_summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
        else:
            sprint_summary = "unparseable"
        try:
            mtime = datetime.fromtimestamp(sprint_file.stat().st_mtime, tz=timezone.utc)
            sprint_stale_days = max(0, (datetime.now(timezone.utc) - mtime).days)
        except OSError:
            pass
    artifacts["sprint"] = bool(sprint_file)
    stories = _found("*story*.md", impl)
    artifacts["stories"] = len(stories) if stories else False

    phase = "0-not-started"
    next_required = ARTIFACT_CHAIN[0][2]
    for key, phase_when_present, producer in ARTIFACT_CHAIN:
        if artifacts.get(key):
            phase = phase_when_present
            next_required = None
        elif next_required is None:
            next_required = producer
    if phase == "4-implementation" and next_required is None:
        next_required = "bmad-dev-story"  # in flight: the loop continues

    return {
        "state": state,
        "version": version,
        "phase": phase,
        "next_required": next_required,
        "artifacts": artifacts,
        "sprint_status": sprint_summary,
        "sprint_stale_days": sprint_stale_days,
    }


# ── S3 — workflow subsystem state ────────────────────────────────────────────


def _read_prior_boot(root: Path) -> dict:
    prior = _read_json(root / BOOT_REL)
    return prior if isinstance(prior, dict) else {}


def scan_subsystems(root: Path, prior: dict) -> dict:
    prior_subs = prior.get("subsystems") if isinstance(prior.get("subsystems"), dict) else {}

    def _state(key: str, initialized: bool, detail: object = None) -> dict:
        if initialized:
            st = "initialized"
        elif prior_subs.get(key, {}).get("state") == "opted_out" if isinstance(prior_subs.get(key), dict) else prior_subs.get(key) == "opted_out":
            st = "opted_out"
        else:
            st = "absent"
        entry: dict[str, object] = {"state": st}
        if detail is not None:
            entry["detail"] = detail
        return entry

    mem_dir = root / "memory"
    mem_ok = mem_dir.is_dir() and all((mem_dir / f).is_file() for f in MEMORY_FILES)

    learn_file = root / "_workflow" / "learnings.jsonl"
    learn_count = None
    if learn_file.is_file():
        try:
            learn_count = sum(
                1 for line in learn_file.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        except OSError:
            learn_count = None

    cfg = _read_yaml(root / "bmad.config.yaml")
    has_context = isinstance(cfg, dict) and bool(cfg.get("context"))
    has_validation = isinstance(cfg, dict) and bool(cfg.get("validation"))

    specs = sorted(
        d.name for d in (root / "specs").iterdir() if d.is_dir()
    ) if (root / "specs").is_dir() else []

    packs_manifest = _read_yaml(root / "workflow.packs.yaml")
    packs = targets = profile = None
    if isinstance(packs_manifest, dict):
        packs = packs_manifest.get("packs")
        targets = packs_manifest.get("targets")
        profile = packs_manifest.get("profile")

    guard = _read_json(root / ".wf" / "guard.json")
    guard_armed = bool(
        isinstance(guard, dict)
        and (guard.get("careful") or guard.get("freeze_dir") or guard.get("budget_max"))
    )
    leases = _read_json(root / ".bmad" / "locks" / "leases.json")
    lease_count = len(leases) if isinstance(leases, (list, dict)) else 0

    settings = _read_json(root / ".claude" / "settings.json")
    hooks = sorted(settings.get("hooks", {}).keys()) if isinstance(settings, dict) else []
    sandbox = bool(isinstance(settings, dict) and isinstance(settings.get("sandbox"), dict)
                   and settings["sandbox"].get("enabled"))

    instr = [f for f in INSTRUCTION_FILES if (root / f).is_file()]

    return {
        "memory": _state("memory", mem_ok),
        "learn": _state("learn", learn_file.is_file(), learn_count),
        "context": _state("context", has_context),
        "validation": _state("validation", has_validation),
        "spec": _state("spec", bool(specs), specs or None),
        "packs": _packs_entry(root, prior_subs, packs, targets, profile),
        "guard": {"state": "armed" if guard_armed else "off"},
        "locks": {"state": "held" if lease_count else "none", "count": lease_count},
        "hooks": {"state": "present" if hooks else "none", "hooks": hooks,
                  "sandbox": sandbox},
        "instruction_files": instr,
        "traces": {"state": "present" if (root / "_workflow" / "traces").is_dir() else "absent"},
    }


# ── S4 — tool readiness (M1: fixed always-relevant set) ─────────────────────


def _packs_entry(root: Path, prior_subs: dict, packs, targets, profile) -> dict:
    """Packs subsystem with opt-out readback (GPT-game trace: a recorded pack
    decline must survive every rescan) + satellite-adoption hint (activation
    block present without installed packs -> skills likely consumed from a
    Workflow checkout in session scope, not a wrong state)."""
    state = "initialized" if packs else "absent"
    prior_packs = prior_subs.get("packs")
    prior_state = (prior_packs.get("state") if isinstance(prior_packs, dict)
                   else prior_packs)
    if state == "absent" and prior_state == "opted_out":
        state = "opted_out"
    satellite = False
    if state != "initialized" and (root / "CLAUDE.md").is_file():
        try:
            satellite = BLOCK_START in (root / "CLAUDE.md").read_text(encoding="utf-8")
        except OSError:
            satellite = False
    return {"state": state, "packs": packs, "targets": targets,
            "profile": profile, "satellite_hint": satellite}


def scan_readiness(root: Path, subsystems: dict) -> dict:
    ready: dict[str, str] = {}
    ready["memory"] = (
        "READY" if subsystems["memory"]["state"] == "initialized"
        else "SETUP-NEEDED (wf memory init)"
    )
    ready["learn"] = (
        "READY" if subsystems["learn"]["state"] == "initialized"
        else "SETUP-NEEDED (first `wf learn add` creates _workflow/learnings.jsonl)"
    )
    _, impl = _bmad_paths(root)
    has_story = bool(impl.is_dir() and list(impl.rglob("*story*.md")))
    ready["audit"] = (
        "READY" if has_story
        else "SETUP-NEEDED (needs a story file with acceptance criteria)"
    )
    return ready


# ── M1 metrics ───────────────────────────────────────────────────────────────


def scan_metrics(root: Path) -> dict:
    skills_dir = root / ".claude" / "skills"
    installed = sorted(
        d.name for d in skills_dir.iterdir() if d.is_dir()
    ) if skills_dir.is_dir() else []

    always_loaded = ""
    for f in INSTRUCTION_FILES:
        p = root / f
        if p.is_file():
            try:
                always_loaded += p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

    referenced = [s for s in installed if s in always_loaded]
    pct = round(100 * len(referenced) / len(installed)) if installed else None
    return {
        # Definition (deterministic, stated so the number can't oversell):
        # a skill has a firing path when its NAME appears in an always-loaded
        # instruction file of the project. Conversational triggers the user
        # would never type are exactly what this metric is blind to — that is
        # the point; the M2 activation block targets this number.
        "skills_installed": len(installed),
        "skills_referenced_always_loaded": len(referenced),
        "firing_path_pct": pct,
        # Model-graded number; only ever written by an actual eval run.
        "invocation_rate_baseline": None,
    }


def emit_eval_corpus(root: Path) -> list[dict]:
    """The scripted-transcript invocation-rate corpus: every installed
    skill's triggers.json rows, flattened. Skills without triggers.json are
    listed with query=None so the denominator stays honest."""
    skills_dir = root / ".claude" / "skills"
    rows: list[dict] = []
    if not skills_dir.is_dir():
        return rows
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        tj = d / "evals" / "triggers.json"
        if not tj.is_file():
            tj = d / "triggers.json"
        data = _read_json(tj) if tj.is_file() else None
        if isinstance(data, list) and data:
            for row in data:
                if isinstance(row, dict) and "query" in row:
                    rows.append({
                        "skill": d.name,
                        "query": row.get("query"),
                        "should_trigger": bool(row.get("should_trigger")),
                    })
        else:
            rows.append({"skill": d.name, "query": None, "should_trigger": None})
    return rows


# ── M2: activation catalog · matcher · size · plan · block ──────────────────

ACTIVATIONS_DIR = REPO_ROOT / "core" / "activations"
BLOCK_START = "<!-- wf:activation:start — generated by `wf start`; edit via `wf start`, not by hand -->"
BLOCK_END = "<!-- wf:activation:end -->"
ENTRY_STAGES = ("discover", "plan", "solution", "build", "verify", "anytime")
TOOL_STAGES = ("spec", "build", "verify", "release")
SIZES = ("tiny", "small", "medium", "large")

# ── M3: involvement envelope (D5) + creation-mode vocabulary ─────────────────
INVOLVEMENTS = ("observer", "satellite", "partial", "full")
INVOLVEMENT_SCOPE = {
    "observer": "memory + learn + boot.json receipt ONLY (no packs, no block)",
    "satellite": "observer + activation block + validation offer · NO install (packs opted out)",
    "partial": "satellite + user-chosen packs (--packs subset)",
    "full": "everything (install, block, config template, offers)",
}
VARIANTS = ("greenfield", "takeover", "satellite")
CREATION_STACKS = ("node-express", "fastapi-react", "node-express-vue", "undecided")
POSTURES = ("civilian", "civilian-team", "secure", "secure-team")
STAGE_LABELS = {
    "discover": "starting out / ideating",
    "plan": "planning the product",
    "solution": "architecture / design",
    "build": "build / next story",
    "verify": "before merge / verify",
    "anytime": "anytime",
}


def load_catalog() -> tuple[dict, dict]:
    """(profiles by id, addons by id). Missing/unparseable files simply
    don't load — `--check` is where absence becomes an error."""
    profiles: dict[str, dict] = {}
    addons: dict[str, dict] = {}
    if not ACTIVATIONS_DIR.is_dir():
        return profiles, addons
    for f in sorted(ACTIVATIONS_DIR.glob("*.yaml")):
        data = _read_yaml(f)
        if f.name == "_addons.yaml":
            if isinstance(data, dict) and isinstance(data.get("addons"), dict):
                addons = data["addons"]
            continue
        if isinstance(data, dict) and data.get("id"):
            profiles[str(data["id"])] = data
    return profiles, addons


def _known_packs() -> set[str] | None:
    """Pack registry ground truth from `wf install --list-packs` (None on
    failure — callers fail closed)."""
    try:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "wf-install.py"), "--list-packs"],
            capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    packs = set(re.findall(r"(?m)^\s{2}([a-z0-9-]+)\s+\d+ skill\(s\)", proc.stdout))
    return packs or None


def _known_tools() -> set[str]:
    """wf subcommand names parsed from the dispatcher itself (no drift)."""
    try:
        text = (REPO_ROOT / "scripts" / "wf").read_text(encoding="utf-8")
    except OSError:
        return set()
    m = re.search(r"COMMANDS[^=]*=\s*\{(.*?)\n\}", text, re.S)
    if not m:
        return set()
    return set(re.findall(r'"([a-z0-9-]+)":', m.group(1))) | {"doctor"}


def check_catalog() -> list[str]:
    """Fail-closed catalog validation (joins doctor check 42): every skill,
    pack, wf tool, gate, and addon ref must exist; shapes must be sane."""
    problems: list[str] = []
    profiles, addons = load_catalog()
    if not profiles:
        return [f"no activation profiles found under {ACTIVATIONS_DIR}"]
    if "generic" not in profiles:
        problems.append("catalog: the `generic` zero-match fallback profile is missing")
    packs = _known_packs()
    if packs is None:
        problems.append("catalog: could not resolve the pack registry (wf install --list-packs failed)")
    tools = _known_tools()
    skills_dir = REPO_ROOT / ".claude" / "skills"
    rules_dir = REPO_ROOT / "core" / "rules"

    for pid, p in sorted(profiles.items()):
        where = f"activation {pid}"
        for field in ("summary", "packs", "default_size", "entry_skills", "wf_tools"):
            if not p.get(field):
                problems.append(f"{where}: missing required field `{field}`")
        if p.get("default_size") not in SIZES:
            problems.append(f"{where}: default_size {p.get('default_size')!r} not in {SIZES}")
        for pk in list(p.get("packs") or []) + list((p.get("optional_packs") or {}).keys()):
            if packs is not None and pk not in packs:
                problems.append(f"{where}: unknown pack {pk!r}")
        es = p.get("entry_skills") or {}
        for stage, skills in es.items():
            if stage not in ENTRY_STAGES:
                problems.append(f"{where}: unknown entry stage {stage!r}")
            for s in skills or []:
                if not (skills_dir / str(s)).is_dir():
                    problems.append(f"{where}: entry skill {s!r} does not exist")
        wt = p.get("wf_tools") or {}
        for t in list(wt.get("always") or []):
            if tools and t not in tools:
                problems.append(f"{where}: unknown wf tool {t!r}")
        for stage, ts in (wt.get("by_stage") or {}).items():
            if stage not in TOOL_STAGES:
                problems.append(f"{where}: unknown tool stage {stage!r}")
            for t in ts or []:
                if tools and t not in tools:
                    problems.append(f"{where}: unknown wf tool {t!r}")
        for g in p.get("gates") or []:
            if not (rules_dir / f"{g}.yaml").is_file():
                problems.append(f"{where}: gate {g!r} has no rule at core/rules/{g}.yaml")

    for aid, a in sorted((addons or {}).items()):
        where = f"addon {aid}"
        unit, ref = a.get("unit"), a.get("ref")
        if unit not in ("pack", "skill"):
            problems.append(f"{where}: unit must be pack|skill, got {unit!r}")
        elif unit == "pack":
            if packs is not None and ref not in packs:
                problems.append(f"{where}: unknown pack ref {ref!r}")
        elif not (skills_dir / str(ref)).is_dir():
            problems.append(f"{where}: unknown skill ref {ref!r}")
    return problems


# lang -> the stack_hints token it corroborates
_LANG_HINT = {"ts": "node", "js": "node", "py": "python", "go": "go", "rs": "rust", "rb": "rails"}


def match_profiles(profiles: dict, *, stack: dict | None = None,
                   intent: str | None = None) -> list[tuple[str, float]]:
    """Deterministic scoring: framework hit 0.6 · other stack hit 0.2 each ·
    intent phrase hit 0.5 each (capped 0.99). Returns [(id, score), ...]
    sorted desc; zero-match callers fall back to `generic`."""
    tokens: set[str] = set()
    framework = None
    if stack:
        framework = stack.get("framework")
        for lang in stack.get("langs") or []:
            if lang in _LANG_HINT:
                tokens.add(_LANG_HINT[lang])
            tokens.add(lang)
        for t in stack.get("tests") or []:
            tokens.add(t)
        for m in stack.get("manifests") or []:
            tokens.add(m.replace(".", " ").split()[0] if "." in m else m)
    intent_l = (intent or "").lower()

    scored: list[tuple[str, float]] = []
    for pid, p in profiles.items():
        if pid == "generic":
            continue
        score = 0.0
        for hint in p.get("stack_hints") or []:
            h = str(hint).lower()
            if framework and h == str(framework).lower():
                score += 0.6
            elif h in tokens:
                score += 0.2
        for kw in p.get("intent_keywords") or []:
            if intent_l and str(kw).lower() in intent_l:
                score += 0.5
        if score > 0:
            scored.append((pid, round(min(score, 0.99), 2)))
    scored.sort(key=lambda kv: (-kv[1], kv[0]))
    return scored


def propose_addons(addons: dict, profile: dict, intent: str | None) -> list[tuple[str, dict]]:
    """Add-ons whose intent keywords hit AND whose pack isn't already in the
    profile. Proposals only — same confirm rule as the profile itself."""
    if not intent:
        return []
    intent_l = intent.lower()
    out: list[tuple[str, dict]] = []
    have = set(profile.get("packs") or [])
    for aid, a in sorted((addons or {}).items()):
        if a.get("unit") == "pack" and a.get("ref") in have:
            continue
        if any(str(kw).lower() in intent_l for kw in a.get("intent_keywords") or []):
            out.append((aid, a))
    return out


# ── M3: involvement envelope (D5) + posture resolution ──────────────────────


def propose_involvement(subsystems: dict) -> str:
    """D5 evidence rule: packs installed -> full; an activation block present
    without installed packs (satellite hint) -> satellite; else observer.
    A PROPOSAL only — the envelope is the USER'S ruling and requires
    confirmation (--involvement) exactly like --profile/--size."""
    pk = subsystems.get("packs") or {}
    if pk.get("state") == "initialized":
        return "full"
    if pk.get("satellite_hint"):
        return "satellite"
    return "observer"


def _posture_from_flags(secure: bool, team: bool) -> str | None:
    if secure and team:
        return "secure-team"
    if secure:
        return "secure"
    if team:
        return "civilian-team"
    return None


def _parse_posture(raw: str) -> str | None:
    a = (raw or "").strip().lower().replace(" ", "-").replace("+", "-")
    return {
        "civilian": "civilian", "team": "civilian-team",
        "civilian-team": "civilian-team", "team-civilian": "civilian-team",
        "secure": "secure", "secure-team": "secure-team",
        "team-secure": "secure-team",
    }.get(a)


def _resolve_posture(root: Path, flag: str | None, prior: dict | None = None) -> str:
    """Posture precedence: explicit flag > the project's workflow.packs.yaml
    profile > a prior boot.json receipt > civilian. A given posture flag is
    NEVER silently downgraded to a civilian stamp (103 trace §2)."""
    if flag:
        return flag
    pk = _read_yaml(root / "workflow.packs.yaml")
    if isinstance(pk, dict) and pk.get("profile"):
        return str(pk["profile"])
    if isinstance(prior, dict) and prior.get("posture"):
        return str(prior["posture"])
    return "civilian"


_RISK_PATTERNS = (
    ("auth", re.compile(r"(?i)\b(oauth|jwt|passport|bcrypt|argon2|next-auth|devise)\b")),
    ("payments", re.compile(r"(?i)\b(stripe|paypal|braintree|adyen|square)\b")),
    ("user-data", re.compile(r"(?i)\b(postgres|postgresql|mysql|prisma|sqlalchemy|mongoose|mongodb|typeorm|pg|psycopg2)\b")),
)
_DEP_FILES = ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Gemfile", "Cargo.toml")


def classify_size(root: Path, stack: dict) -> dict:
    """S5 heuristic — a PROPOSAL in ambient-router vocabulary; the human
    confirms (--size), and boot.json persists the confirmation."""
    n = stack.get("file_count") or 0
    if n < 15:
        proposed = "tiny"
    elif n < 150:
        proposed = "small"
    elif n < 1500:
        proposed = "medium"
    else:
        proposed = "large"
    dep_text = ""
    for f in _DEP_FILES:
        p = root / f
        if p.is_file():
            try:
                dep_text += p.read_text(encoding="utf-8", errors="replace")[:20000]
            except OSError:
                pass
    # 103 trace: risk markers in workspace-member manifests count too (pg in
    # backend/package.json missed the user-data bump on the persistence tier).
    dep_text += " " + " ".join(stack.get("merged_deps") or [])
    risk = [name for name, rx in _RISK_PATTERNS if rx.search(dep_text)]
    if risk and SIZES.index(proposed) < SIZES.index("medium"):
        proposed = "medium"
    return {"proposed": proposed, "risk": risk}


def _profile_tools(profile: dict) -> list[str]:
    wt = profile.get("wf_tools") or {}
    seen: list[str] = []
    for t in list(wt.get("always") or []):
        if t not in seen:
            seen.append(t)
    for ts in (wt.get("by_stage") or {}).values():
        for t in ts or []:
            if t not in seen:
                seen.append(t)
    return seen


def profile_readiness(root: Path, subsystems: dict, profile: dict) -> dict:
    """S4, profile-relative: preconditions per tool the profile lists."""
    ready = scan_readiness(root, subsystems)  # fixed set stays first
    cfg = _read_yaml(root / "bmad.config.yaml")
    has_validation = isinstance(cfg, dict) and bool(cfg.get("validation"))
    has_context = isinstance(cfg, dict) and bool(cfg.get("context"))
    pkg = _read_json(root / "package.json")
    has_test_cmd = bool(
        has_validation
        or (isinstance(pkg, dict) and (pkg.get("scripts") or {}).get("test"))
        or (root / "pytest.ini").is_file() or (root / "conftest.py").is_file()
    )
    try:
        import importlib.util
        has_playwright = importlib.util.find_spec("playwright") is not None
    except Exception:  # noqa: BLE001
        has_playwright = False

    probes = {
        "validate": ("READY" if has_validation else "SETUP-NEEDED (seed the validation: block)"),
        "context": ("READY" if has_context else "SETUP-NEEDED (seed context: tags)"),
        "browse": ("READY" if has_playwright else "SETUP-NEEDED (wf browse setup)"),
        "mutate": ("READY" if has_test_cmd else "SETUP-NEEDED (needs a runnable test command)"),
        "spec": ("READY" if subsystems["spec"]["state"] == "initialized"
                 else "SETUP-NEEDED (wf spec init <feature>)"),
        "orchestra": "SETUP-NEEDED (model endpoint at runtime)",
        "calibrate": "SETUP-NEEDED (model endpoint at runtime)",
        "finetune": "SETUP-NEEDED (model endpoint at runtime)",
    }
    for t in _profile_tools(profile):
        if t in ready:
            continue
        ready[t] = probes.get(t, "READY")
    return ready


def build_plan(root: Path, boot: dict, profile: dict, want_packs: list[str],
               profile_confirmed: bool, *, envelope: str = "full",
               posture: str = "civilian") -> dict:
    """S6: diff current state vs the profile (+ selected addon packs already
    folded into want_packs) -> ordered steps, each tagged with its authority
    class, SCOPED to the involvement envelope (D5: steps outside the envelope
    never appear). NOTHING here writes."""
    subs = boot["subsystems"]
    auto: list[dict] = []
    offers: list[dict] = []
    yours: list[str] = []

    def _auto(desc: str, action: str) -> None:
        auto.append({"id": f"A{len(auto)+1}", "desc": desc, "action": action})

    if subs["memory"]["state"] != "initialized":
        _auto("wf memory init (5-file resume pack)", "memory-init")
    if envelope == "full" and not (root / "bmad.config.yaml").is_file():
        _auto("copy bmad.config.example.yaml -> bmad.config.yaml (validation/context templates)",
              "config-template")

    # Install comes BEFORE the block (posture-first — 103 trace §2): the block
    # reads posture back from workflow.packs.yaml, so a same-run install must
    # precede its render; a non-civilian posture states the ordering out loud.
    have_packs = set((subs["packs"].get("packs") or []))
    missing_packs = [p for p in want_packs if p not in have_packs]
    if envelope in ("partial", "full") and missing_packs and root != REPO_ROOT \
            and subs["packs"].get("state") != "opted_out":
        note = ("" if posture == "civilian" else
                f" — runs BEFORE the block render so the block reads posture {posture} "
                "(posture-first, 103 §2; never a silent civilian stamp)")
        _auto(f"wf install --packs {','.join(want_packs)} --targets claude "
              f"--profile {posture} (requires the Workflow toolset checkout){note}",
              "install")

    if envelope != "observer":
        block_note = "" if profile_confirmed else " [needs confirmed --profile]"
        sat = " + satellite path warnings" if envelope in ("satellite", "partial") else ""
        _auto(f"append/refresh activation block ({profile.get('id')}{sat}) in CLAUDE.md{block_note}",
              "block")
    _auto("write _workflow/boot.json receipt", "boot")

    readiness = boot.get("readiness") or {}
    if envelope == "full":
        if readiness.get("validate", "").startswith("SETUP-NEEDED") and (root / "bmad.config.yaml").is_file():
            offers.append({"id": f"O{len(offers)+1}",
                           "desc": "seed validation: block in bmad.config.yaml (from the example template)",
                           "action": "offer-validate"})
        if "browse" in readiness and readiness["browse"].startswith("SETUP-NEEDED"):
            offers.append({"id": f"O{len(offers)+1}",
                           "desc": "wf browse setup (real-browser E2E gate)", "action": "offer-browse"})
        if readiness.get("context", "").startswith("SETUP-NEEDED"):
            offers.append({"id": f"O{len(offers)+1}",
                           "desc": "seed context: work-area tags from the stack scan",
                           "action": "offer-context"})

        mcp = profile.get("mcp_recommend_categories") or []
        if mcp:
            yours.append(f"MCP: recommend {', '.join(mcp)} (see README §MCP servers — never auto-connected)")
        yours.append("wf guard arming / .claude/settings.json hook changes (always yours)")
        for g in profile.get("gates") or []:
            yours.append(f"gate {g}: strongest rung available is advisory until wired (wf audit --block / CI)")
    elif envelope in ("satellite", "partial"):
        # Satellite semantics (gpt-game trace §2): wire validation from the
        # detected test command; nothing else is inside the envelope.
        if subs["validation"]["state"] == "absent":
            offers.append({"id": f"O{len(offers)+1}",
                           "desc": "seed validation: block in bmad.config.yaml (scaffolded from the detected test command)",
                           "action": "offer-validate"})
    # observer: memory + receipt only — no offers, no stop-and-ask items.

    return {"auto": auto, "offers": offers, "yours": yours, "envelope": envelope}


def render_block(boot: dict, profile: dict, addons_sel: list[tuple[str, dict]],
                 size: str, posture: str, involvement: str = "full") -> str:
    """The ~20-line always-loaded router note (§6). Claude-only in M2.
    M3: a satellite/partial envelope bakes the absolute-path tool warnings
    into the block itself (gpt-game trace §3 — the usage knowledge that
    otherwise gets re-learned from CLI errors every session)."""
    addon_suffix = "".join(f" +{a.get('ref')}" for _, a in addons_sel)
    inv_suffix = f" · involvement: {involvement}" if involvement != "full" else ""
    lines = [BLOCK_START]
    lines.append(f"## Active workflow toolset — profile: {profile.get('id')}{addon_suffix} · "
                 f"size: {size} · posture: {posture}{inv_suffix}")
    b = boot.get("bmad") or {}
    phase_bit = ""
    if b.get("phase") and b.get("state") != "none":
        nxt = f", next: `{b['next_required']}`" if b.get("next_required") else ""
        phase_bit = f" · current phase: **{b['phase']}**{nxt}"
    lines.append(f"Entry points: **bmad-help** (BMAD phase router) · `wf start` (re-scan){phase_bit}")
    lines.append("| when | reach for |")
    lines.append("|---|---|")
    es = profile.get("entry_skills") or {}
    wt = (profile.get("wf_tools") or {}).get("by_stage") or {}
    stage_tools = {"plan": wt.get("spec"), "build": wt.get("build"), "verify": wt.get("verify")}
    for stage in ENTRY_STAGES:
        skills = list(es.get(stage) or [])
        tools = [f"wf {t}" for t in (stage_tools.get(stage) or [])]
        for _, a in addons_sel:
            if a.get("unit") == "skill" and stage == "anytime":
                skills.append(str(a.get("ref")))
        if not skills and not tools:
            continue
        lines.append(f"| {STAGE_LABELS[stage]} | {' · '.join(skills + tools)} |")
    always = (profile.get("wf_tools") or {}).get("always") or []
    if always:
        bits = []
        if "memory" in always:
            bits.append("wf memory refresh")
        if "learn" in always:
            # usage carried in the block itself — field trace: three agents had
            # to rediscover the flag shape from CLI errors
            bits.append('wf learn list · new fact: wf learn add --type T --key K --insight "…"')
        if bits:
            lines.append(f"| session start | {' · '.join(bits)} |")
    if involvement == "satellite":
        lines.append("Satellite mode: skills come from the Workflow checkout in session "
                     "scope — packs NOT installed (recorded opt-out; `wf install` is out of envelope).")
    if involvement in ("satellite", "partial"):
        lines.append("Path warning: wf tools resolve relative paths against the TOOLSET "
                     "checkout — always pass absolute --dir/--file paths "
                     "(wf learn · wf trace · wf install check).")
    gates = profile.get("gates") or []
    tail = f"Gates on: {' · '.join(gates)}. " if gates else ""
    lines.append(f"{tail}Re-scan: `wf start`.")
    lines.append(BLOCK_END)
    return "\n".join(l for l in lines if l != "")


def upsert_block(claude_md: Path, block: str) -> str:
    """Insert or refresh the marker-fenced block; NEVER touches text outside
    the markers. Returns 'created' | 'refreshed' | 'appended'."""
    if not claude_md.is_file():
        claude_md.write_text(block + "\n", encoding="utf-8")
        return "created"
    text = claude_md.read_text(encoding="utf-8")
    if BLOCK_START in text and BLOCK_END in text:
        pre, _, rest = text.partition(BLOCK_START)
        _, _, post = rest.partition(BLOCK_END)
        claude_md.write_text(pre + block + post, encoding="utf-8")
        return "refreshed"
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    claude_md.write_text(text + sep + block + "\n", encoding="utf-8")
    return "appended"


def _claude_md_dirty(root: Path) -> bool | None:
    """True/False from git; None when git can't answer (no repo)."""
    if not (root / ".git").exists():
        return None
    out = _git(root, "status", "--porcelain", "--", "CLAUDE.md")
    return bool(out) if out is not None else None


# ── assemble · render · write ────────────────────────────────────────────────


def scan(root: Path, *, force_new: bool = False) -> dict:
    prior = _read_prior_boot(root)
    mode = detect_mode(root, force_new=force_new)
    boot: dict[str, object] = {
        "schema": SCHEMA_VERSION,
        "generated": _now_iso(),
        "mode": mode["mode"],
        "monorepo": mode["monorepo"],
        "monorepo_evidence": mode["monorepo_evidence"],
    }
    if mode["mode"] == "greenfield":
        boot["note"] = (
            "greenfield — creation mode (M3): interview + plan; interactive on "
            "a TTY, flag-driven otherwise (--yes accepts defaults and executes; "
            "--involvement is question ZERO — D5)"
        )
        return boot

    boot["stack"] = scan_stack(root)
    boot["bmad"] = scan_bmad(root)
    subsystems = scan_subsystems(root, prior)
    boot["subsystems"] = subsystems
    boot["readiness"] = scan_readiness(root, subsystems)
    boot["metrics"] = scan_metrics(root)
    prior_metrics = prior.get("metrics") if isinstance(prior.get("metrics"), dict) else {}
    if prior_metrics.get("invocation_rate_baseline") is not None:
        boot["metrics"]["invocation_rate_baseline"] = prior_metrics["invocation_rate_baseline"]
    boot["receipts"] = {"last_scan": _now_iso()}
    return boot


def is_ambiguous(matches: list[tuple[str, float]]) -> bool:
    """Top-2 within 0.15 -> surface top-3 and require --profile (§3 S6)."""
    return len(matches) >= 2 and (matches[0][1] - matches[1][1]) < 0.15


def enrich(boot: dict, root: Path, *, intent: str | None = None,
           profile_arg: str | None = None, addons_arg: list[str] | None = None,
           size_arg: str | None = None, involvement_arg: str | None = None,
           packs_arg: list[str] | None = None,
           posture_arg: str | None = None) -> dict:
    """M2+M3: add S5 size, the involvement envelope (D5 — resolved BEFORE the
    profile proposal is allowed to shape any plan step), activation proposal,
    profile-relative S4, and the envelope-scoped S6 plan to a brownfield scan.
    Pure — nothing here writes."""
    prior = _read_prior_boot(root)
    profiles, addons = load_catalog()
    if not profiles:
        boot["activation"] = {"error": "no activation catalog found (core/activations/)"}
        return boot

    size = classify_size(root, boot["stack"])
    prior_size = prior.get("size") if isinstance(prior.get("size"), dict) else {}
    confirmed_size = size_arg or prior_size.get("confirmed")
    boot["size"] = {"proposed": size["proposed"], "risk": size["risk"],
                    "confirmed": confirmed_size,
                    "at": _now_iso()[:10] if confirmed_size else prior_size.get("at")}

    # ── D5: involvement envelope — question ZERO. Confirmed like size/profile
    # (flag now, or a prior receipt's confirmed ruling); otherwise PROPOSED
    # from evidence and never silently escalated.
    prior_act = prior.get("activation") if isinstance(prior.get("activation"), dict) else {}
    if packs_arg and not involvement_arg:
        involvement_arg = "partial"  # an explicit pack subset IS the partial ruling
    if involvement_arg and involvement_arg not in INVOLVEMENTS:
        _die(f"unknown involvement {involvement_arg!r} — one of {', '.join(INVOLVEMENTS)}")
    if packs_arg and involvement_arg != "partial":
        _die("--packs is the PARTIAL envelope's subset — use --involvement partial")
    if packs_arg:
        known = _known_packs()
        if known:
            bad = sorted(set(packs_arg) - known)
            if bad:
                _die(f"unknown pack(s) {', '.join(bad)} — known: {', '.join(sorted(known))}")
    prior_inv = (prior_act.get("involvement")
                 if prior_act.get("involvement_confirmed") else None)
    inv = involvement_arg or prior_inv
    inv_confirmed = bool(inv)
    proposed_inv = propose_involvement(boot["subsystems"])
    if not inv:
        inv = proposed_inv
    posture = _resolve_posture(root, posture_arg, prior)
    boot["posture"] = posture
    boot["_posture_flag"] = posture_arg

    # A confirmed satellite ruling records the pack opt-out (its semantics —
    # gpt-game trace: the decline must be expressible AND survive rescans).
    if inv_confirmed and inv == "satellite":
        pk = boot["subsystems"]["packs"]
        if pk.get("state") == "absent":
            pk["state"] = "opted_out"

    matches = match_profiles(profiles, stack=boot["stack"], intent=intent)
    chosen = profile_arg or prior_act.get("profile")
    confirmed_profile = bool(chosen)
    if chosen and chosen not in profiles:
        _die(f"unknown profile {chosen!r} — known: {', '.join(sorted(profiles))}")
    if not chosen:
        chosen = matches[0][0] if matches else "generic"
    profile = profiles[chosen]

    sel: list[tuple[str, dict]] = []
    for aid in addons_arg or []:
        if aid not in addons:
            _die(f"unknown addon {aid!r} — known: {', '.join(sorted(addons))}")
        sel.append((aid, addons[aid]))
    proposed_addons = [] if addons_arg else propose_addons(addons, profile, intent)

    boot["activation"] = {
        "profile": chosen,
        "confirmed": confirmed_profile,
        "involvement": inv,
        "involvement_confirmed": inv_confirmed,
        "involvement_proposed": proposed_inv,
        "score": matches[0][1] if matches and matches[0][0] == chosen else None,
        "alternates": [{"profile": p, "score": s} for p, s in matches[:3] if p != chosen],
        "ambiguous": is_ambiguous(matches),
        "addons": [aid for aid, _ in sel],
        "addons_proposed": [aid for aid, _ in proposed_addons],
        "applied_at": prior_act.get("applied_at"),
    }
    boot["readiness"] = profile_readiness(root, boot["subsystems"], profile)
    want_packs = list(profile.get("packs") or [])
    for _, a in sel:
        if a.get("unit") == "pack" and a.get("ref") not in want_packs:
            want_packs.append(str(a["ref"]))
    if inv == "partial" and packs_arg:
        want_packs = list(packs_arg)
    boot["_plan"] = build_plan(root, boot, profile, want_packs, confirmed_profile,
                               envelope=inv, posture=posture)
    boot["_profile_obj"] = profile
    boot["_addons_sel"] = sel
    boot["_want_packs"] = want_packs
    return boot


VALID_DECLINE = ("memory", "learn", "context", "validation", "spec", "traces", "packs")


def apply_plan(root: Path, boot: dict, *, accept: list[str],
               force_block: bool) -> list[str]:
    """Execute ONLY auto-do steps + explicitly accepted offers, inside the
    involvement envelope. Returns the log of what ran. Stop-and-ask items are
    never executed here. D5: without a CONFIRMED envelope only the
    observer-safe subset (memory + receipt) materializes — stated, not
    silent."""
    plan = boot["_plan"]
    profile = boot["_profile_obj"]
    log: list[str] = []
    accepted = {a.strip() for a in accept if a.strip()}

    act = boot.get("activation") or {}
    steps = plan["auto"]
    envelope_confirmed = bool(act.get("involvement_confirmed"))
    if not envelope_confirmed:
        proposed = act.get("involvement_proposed") or act.get("involvement") or "observer"
        log.append("involvement envelope NOT confirmed — applying the observer-safe "
                   "subset only (memory + receipt); confirm with --involvement "
                   f"{proposed} to materialize the rest (D5: the envelope is your ruling)")
        steps = [s for s in steps if s["action"] in ("memory-init", "boot")]

    for step in steps:
        action = step["action"]
        if action == "memory-init":
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "wf-memory.py"), "init",
                 "--dir", str(root / "memory")],
                capture_output=True, text=True, timeout=60,
            )
            log.append(f"{step['id']} memory init: {'ok' if proc.returncode == 0 else 'FAILED — ' + proc.stderr.strip()[:200]}")
        elif action == "config-template":
            src = REPO_ROOT / "bmad.config.example.yaml"
            dst = root / "bmad.config.yaml"
            if src.is_file() and not dst.is_file():
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                log.append(f"{step['id']} bmad.config.yaml seeded from example")
            else:
                log.append(f"{step['id']} config template skipped (already present or example missing)")
        elif action == "block":
            if not boot["activation"]["confirmed"]:
                log.append(f"{step['id']} activation block SKIPPED — profile not confirmed "
                           "(pass --profile <id>)")
                continue
            dirty = _claude_md_dirty(root)
            if dirty and not force_block:
                log.append(f"{step['id']} activation block REFUSED — CLAUDE.md has uncommitted "
                           "changes (commit it or pass --force-block)")
                continue
            # Posture is read LIVE (flag > workflow.packs.yaml > prior receipt)
            # so a same-run install that just stamped it is what the block
            # reads — never a stale pre-scan value (posture-first, 103 §2).
            posture = _resolve_posture(root, boot.get("_posture_flag"),
                                       _read_prior_boot(root))
            size = boot["size"].get("confirmed") or boot["size"]["proposed"]
            involvement = boot["activation"].get("involvement") or "full"
            block = render_block(boot, profile, boot["_addons_sel"], size, posture,
                                 involvement=involvement)
            verb = upsert_block(root / "CLAUDE.md", block)
            boot["activation"]["applied_at"] = _now_iso()[:10]
            log.append(f"{step['id']} activation block {verb} in CLAUDE.md (posture {posture})")
        elif action == "boot":
            pass  # written once, after all steps, by the caller
        elif action == "install":
            posture = boot.get("posture") or "civilian"
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "wf-install.py"),
                 "--out", str(root), "--packs", ",".join(boot["_want_packs"]),
                 "--targets", "claude", "--profile", posture],
                capture_output=True, text=True, timeout=600, cwd=str(REPO_ROOT),
            )
            log.append(f"{step['id']} wf install (--profile {posture}): {'ok' if proc.returncode == 0 else 'FAILED — ' + (proc.stderr or proc.stdout).strip()[:200]}")

    if not envelope_confirmed:
        return log  # offers are beyond the observer-safe subset too

    for offer in plan["offers"]:
        name = offer["action"].removeprefix("offer-")
        if offer["id"] not in accepted and name not in accepted:
            continue
        if offer["action"] == "offer-validate":
            dst = root / "bmad.config.yaml"
            text = dst.read_text(encoding="utf-8") if dst.is_file() else ""
            if "validation:" not in text:
                dst.write_text(text + "\n# seeded by wf start --accept (edit commands to fit)\n"
                               "validation:\n  test:\n    - echo 'wire your test command here'\n",
                               encoding="utf-8")
                log.append(f"{offer['id']} validation: block seeded")
            else:
                log.append(f"{offer['id']} validation: already present — nothing to do")
        elif offer["action"] == "offer-browse":
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "wf-browse.py"), "setup"],
                capture_output=True, text=True, timeout=600,
            )
            log.append(f"{offer['id']} browse setup: {'ok' if proc.returncode == 0 else 'FAILED — ' + proc.stderr.strip()[:200]}")
        elif offer["action"] == "offer-context":
            dst = root / "bmad.config.yaml"
            text = dst.read_text(encoding="utf-8") if dst.is_file() else ""
            if "context:" not in text:
                dst.write_text(text + "\n# seeded by wf start --accept (refine paths)\n"
                               "context:\n  tags:\n    app:\n      type: work_area\n"
                               "      description: main application code\n      paths: [\"src/**\"]\n"
                               "      allow_empty: true\n", encoding="utf-8")
                log.append(f"{offer['id']} context: tags seeded")
            else:
                log.append(f"{offer['id']} context: already present — nothing to do")
    return log


def record_decisions(boot: dict, *, decline: list[str], accept: list[str]) -> None:
    """--decline records opted_out (the ONLY way an opt-out is written);
    --accept <subsystem> reverses a recorded opt-out."""
    subs = boot["subsystems"]
    for name in decline:
        name = name.strip()
        if not name:
            continue
        if name not in VALID_DECLINE:
            _die(f"--decline {name!r}: not a declinable subsystem {VALID_DECLINE}")
        if isinstance(subs.get(name), dict) and subs[name].get("state") != "initialized":
            subs[name]["state"] = "opted_out"
    for name in accept:
        name = name.strip()
        if name in VALID_DECLINE and isinstance(subs.get(name), dict) \
                and subs[name].get("state") == "opted_out":
            subs[name]["state"] = "absent"


def _fmt_subsystem(name: str, entry: dict) -> str:
    st = entry.get("state")
    if st == "initialized":
        detail = entry.get("detail")
        show = detail is not None and detail is not True
        return f"{name} ✓" + (f" ({detail})" if show else "")
    if st == "opted_out":
        return f"{name} — opted-out"
    return f"{name} — absent"


def render_report(boot: dict, root: Path) -> str:
    lines: list[str] = []
    lines.append("wf start · scan (read-only) " + "·" * 33)
    if boot["mode"] == "greenfield":
        lines.append(f"  mode        greenfield ({root})")
        lines.append(f"  note        {boot['note']}")
        return "\n".join(lines)

    st = boot["stack"]
    git = st["git"]
    bits = ["/".join(st["langs"]) or "no source detected"]
    if st["framework"]:
        bits[0] = f"{st['framework']}/{bits[0]}"
    if st["tests"]:
        bits.append(",".join(st["tests"]))
    if st["ci"]:
        bits.append(f"{'+'.join(st['ci'])}-ci")
    if git.get("repo"):
        dirty = "dirty" if git.get("dirty") else "clean"
        bits.append(f"git {dirty} @ {git.get('branch')}")
    mono = " · MONOREPO (repo-root activation only — scope with --dir)" if boot["monorepo"] else ""
    lines.append(f"  mode        brownfield ({' · '.join(bits)}){mono}")

    b = boot["bmad"]
    if b["state"] == "none":
        lines.append("  bmad        none (no _bmad/ install or scaffold glue)")
        if b.get("note"):
            lines.append(f"              note: {b['note']}")
    else:
        v = f" ({b['version']})" if b.get("version") else ""
        lines.append(f"  bmad        {b['state']}{v} · phase {b['phase']}")
        a = b["artifacts"]

        def _mark(v_: object) -> str:
            if v_ is False:
                return "✗"
            if v_ is True:
                return "✓"
            return f"✓({v_})"

        lines.append(
            "              artifacts: "
            + "  ".join(f"{k} {_mark(a[k])}" for k in ("brief", "prd", "architecture", "epics"))
        )
        if b.get("sprint_status"):
            stale = f" · updated {b['sprint_stale_days']}d ago" if b.get("sprint_stale_days") is not None else ""
            flag = " (STALE >7d)" if (b.get("sprint_stale_days") or 0) > 7 else ""
            lines.append(f"              sprint-status: {b['sprint_status']}{stale}{flag}")
        if b.get("next_required"):
            lines.append(f"              next: {b['next_required']}")

    s = boot["subsystems"]
    lines.append(
        "  workflow    "
        + "   ".join(_fmt_subsystem(k, s[k]) for k in ("memory", "learn"))
    )
    lines.append(
        "              "
        + "   ".join(_fmt_subsystem(k, s[k]) for k in ("context", "validation", "spec"))
    )
    p = s["packs"]
    if p["state"] == "initialized":
        packs_line = (f"packs {','.join(p['packs'])} · target "
                      f"{','.join(p['targets'] or [])} · profile {p['profile']}")
    elif p["state"] == "opted_out":
        packs_line = "packs — opted-out (recorded decline; install never re-proposed)"
    else:
        packs_line = "packs — none recorded (workflow.packs.yaml absent)"
    if p.get("satellite_hint"):
        packs_line += (" · satellite adoption? (activation block present without "
                       "installed packs — skills via session-scope checkout)")
    lines.append(f"              {packs_line}")
    hooks = s["hooks"]
    lines.append(
        f"              guard {s['guard']['state']} · locks {s['locks']['state']} · "
        f"hooks {','.join(hooks['hooks']) if hooks['hooks'] else 'none'}"
        + (" · sandbox ON" if hooks["sandbox"] else "")
    )

    r = boot["readiness"]
    lines.append("  readiness   " + " · ".join(f"{k} {v}" for k, v in r.items()))

    m = boot["metrics"]
    if m["skills_installed"]:
        lines.append(
            f"  metrics     skills installed {m['skills_installed']} · "
            f"named in always-loaded files {m['skills_referenced_always_loaded']} "
            f"({m['firing_path_pct']}% have a firing path)"
        )
        baseline = m["invocation_rate_baseline"]
        lines.append(
            "              invocation-rate baseline: "
            + (f"{baseline}" if baseline is not None
               else "PENDING (emit corpus: wf start --eval-corpus; grade via bmad-eval-runner)")
        )
    else:
        lines.append("  metrics     no .claude/skills installed — nothing to measure")

    sz = boot.get("size")
    if sz:
        conf = (f"confirmed {sz['confirmed']}" if sz.get("confirmed")
                else "proposed — confirm with --size to persist")
        risk = f" · risk: {', '.join(sz['risk'])}" if sz.get("risk") else ""
        lines.append(f"  size        {sz['proposed']} ({conf}){risk}")
        if sz["proposed"] == "tiny" and not sz.get("confirmed"):
            lines.append("              (router guardrail: a throwaway repo may not need "
                         "the workflow at all — nothing to do is a valid verdict)")

    act = boot.get("activation")
    if act and not act.get("error") and act.get("involvement"):
        inv = act["involvement"]
        inv_state = ("confirmed" if act.get("involvement_confirmed")
                     else "proposed from evidence — confirm with --involvement (D5: question zero)")
        lines.append(f"  involvement {inv} ({inv_state})")
        lines.append(f"              envelope: {INVOLVEMENT_SCOPE.get(inv, '?')}")
    if act and not act.get("error"):
        score = f" {act['score']}" if act.get("score") is not None else ""
        alts = " · alt: " + ", ".join(
            f"{a['profile']} {a['score']}" for a in act.get("alternates") or []
        ) if act.get("alternates") else ""
        state = "confirmed" if act["confirmed"] else (
            "AMBIGUOUS — confirm with --profile" if act.get("ambiguous")
            else "proposed — confirm with --profile")
        lines.append(f"  activation  profile {act['profile']}{score} ({state}){alts}")
        addon_bits = []
        if act.get("addons"):
            addon_bits.append("selected: " + ", ".join(act["addons"]))
        if act.get("addons_proposed"):
            addon_bits.append("proposed: " + ", ".join(act["addons_proposed"]) + " (D3 — --addons to select)")
        if addon_bits:
            lines.append("              add-ons " + " · ".join(addon_bits))

    plan = boot.get("_plan")
    if plan:
        lines.append("")
        lines.append("  plan (nothing has been written):")
        for step in plan["auto"]:
            lines.append(f"  auto-do   {step['id']} {step['desc']}")
        for offer in plan["offers"]:
            lines.append(f"  offers    {offer['id']} {offer['desc']}")
        for i, item in enumerate(plan["yours"], 1):
            lines.append(f"  yours     Y{i} {item}")
        # The next: hint is scoped to the (proposed or confirmed) envelope —
        # it always names --involvement and NEVER suggests more than the
        # envelope allows (D5).
        act2 = boot.get("activation") or {}
        inv = act2.get("involvement") or "full"
        prof = act2.get("profile", "generic")
        sz_val = (boot.get("size") or {}).get("confirmed") or (boot.get("size") or {}).get("proposed", "small")
        cmd = f"wf start --apply --involvement {inv} --size {sz_val}"
        if inv != "observer":
            cmd += f" --profile {prof}"
        if inv == "partial":
            cmd += f" --packs {','.join(boot.get('_want_packs') or [])}"
        posture_bits = {"secure": " --secure", "civilian-team": " --team",
                        "secure-team": " --secure --team"}.get(boot.get("posture") or "", "")
        cmd += posture_bits
        accept_hint = f" [--accept {','.join(o['id'] for o in plan['offers'])}]" if plan["offers"] else ""
        lines.append("")
        lines.append(f"  next: {cmd}{accept_hint}")
        lines.append("        (--decline <subsystem> records an opt-out · --json for the machine view)")

    lines.append("")
    lines.append("  this scan wrote nothing" + (
        f" — record the receipt with: wf start --write ({BOOT_REL})"
        if not (root / BOOT_REL).is_file() else
        f" — receipt exists at {BOOT_REL} (refresh with --write)"
    ))
    return "\n".join(lines)


def _strip_transient(boot: dict) -> dict:
    return {k: v for k, v in boot.items() if not k.startswith("_")}


def write_boot(root: Path, boot: dict) -> Path:
    dest = root / BOOT_REL
    prior = _read_prior_boot(root)
    # Creation-mode facts survive later rescans: a rescan's boot dict doesn't
    # re-derive them, so carry them forward rather than silently dropping a
    # recorded interview answer.
    for carry in ("takeover_notes", "variant", "stack_choice"):
        if boot.get(carry) is None and prior.get(carry) is not None:
            boot[carry] = prior[carry]
    # Preserve prior opt-outs verbatim: --write must never launder a recorded
    # human decision into "absent".
    if isinstance(prior.get("subsystems"), dict) and isinstance(boot.get("subsystems"), dict):
        for key, entry in prior["subsystems"].items():
            prior_state = entry.get("state") if isinstance(entry, dict) else entry
            ours = boot["subsystems"].get(key)
            if prior_state == "opted_out" and isinstance(ours, dict) and ours.get("state") == "absent":
                ours["state"] = "opted_out"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(_strip_transient(boot), indent=2, sort_keys=False) + "\n",
                    encoding="utf-8")
    return dest


# ── M3: creation mode — greenfield / takeover / satellite interview ─────────


def _ask(prompt_fn, asked: list[str], q: str, default: str, *,
         interactive: bool, flag: str | None = None) -> tuple[str, bool]:
    """One interview slot. A flag answers it silently; otherwise prompt when
    interactive; otherwise take the default (the --yes non-interactive path).
    Returns (answer, explicit) — explicit means a human actually chose (flag
    or a typed answer), not a default. `asked` records slot ORDER so tests
    can assert D5's question-zero and 103's posture-first ordering."""
    asked.append(q)
    if flag not in (None, "", False):
        return str(flag).strip(), True
    if interactive:
        raw = (prompt_fn(q) or "").strip()
        if raw:
            return raw, True
    return default, False


def run_creation(root: Path, args, *, prompt_fn=input,
                 interactive: bool | None = None) -> int:
    """M3 creation mode: the interview + plan for a greenfield dir (or --new).
    Interactive on a TTY; fully flag-driven otherwise (--yes accepts the
    defaults and executes). D5: involvement is question ZERO — every later
    question and every plan step is scoped to the envelope and never pushes
    beyond it. Three first-class variants (field traces 102/103/gpt-game):
    greenfield / takeover (103 question set, posture FIRST) / satellite."""
    profiles, _addons = load_catalog()
    if not profiles:
        _die("no activation catalog found (core/activations/) — creation mode needs it")
    if interactive is None:
        interactive = sys.stdin.isatty() and not args.yes
    asked: list[str] = []
    print(f"wf start · creation mode ({root})")

    # Q0 — involvement envelope (D5: the user's ruling, asked before ANYTHING).
    inv, inv_explicit = _ask(
        prompt_fn, asked, "0/5 involvement? [observer/satellite/partial/FULL] ",
        "full", interactive=interactive, flag=args.involvement)
    inv = inv.lower()
    if inv not in INVOLVEMENTS:
        _die(f"involvement {inv!r} not one of {', '.join(INVOLVEMENTS)}")
    if args.packs and inv != "partial":
        if inv_explicit:
            _die("--packs is the PARTIAL envelope's subset — use --involvement partial")
        inv, inv_explicit = "partial", True

    # Q1 — variant (greenfield / takeover / satellite adoption).
    variant, _ = _ask(
        prompt_fn, asked, "1/5 variant? [GREENFIELD/takeover/satellite] ",
        "greenfield", interactive=interactive, flag=args.variant)
    variant = variant.lower()
    if variant not in VARIANTS:
        _die(f"variant {variant!r} not one of {', '.join(VARIANTS)}")
    if variant == "satellite" and inv in ("partial", "full"):
        if inv_explicit:
            _die("--variant satellite means NO install (skills via session-scope "
                 "checkout) — incompatible with --involvement partial/full")
        inv = "satellite"
        print("  (variant satellite caps the envelope at satellite — no install)")

    posture_flag = _posture_from_flags(args.secure, args.team)
    posture = posture_flag or "civilian"
    takeover_notes = None
    if variant == "takeover":
        # 103 §2: the takeover question set — POSTURE FIRST, because it
        # decides the install-before-block ordering (secure needs
        # `wf install --profile secure` to run before the block render).
        pa, _ = _ask(
            prompt_fn, asked,
            "takeover · posture? [CIVILIAN/secure/team/secure-team] "
            "(asked FIRST — it decides install ordering) ",
            posture_flag or "civilian", interactive=interactive, flag=posture_flag)
        posture = _parse_posture(pa)
        if posture is None:
            _die(f"posture {pa!r} not one of {', '.join(POSTURES)}")
        seams, _ = _ask(prompt_fn, asked,
                        "takeover · contract seams / canonical ownership? (free text) ",
                        "", interactive=interactive, flag=args.seams)
        deploy, _ = _ask(prompt_fn, asked,
                         "takeover · deploy targets? (free text) ",
                         "", interactive=interactive, flag=args.deploy_targets)
        ports, _ = _ask(prompt_fn, asked,
                        "takeover · port contracts? (free text) ",
                        "", interactive=interactive, flag=args.port_contracts)
        takeover_notes = {"contract_seams": seams or None,
                          "deploy_targets": deploy or None,
                          "port_contracts": ports or None}

    # Q2 — what to make (only when the envelope includes a block or packs).
    profile_id = None
    match_note = ""
    if inv != "observer":
        intent, _ = _ask(prompt_fn, asked,
                         "2/5 what do you want to make? (free text; empty -> generic) ",
                         "", interactive=interactive, flag=args.intent)
        if args.profile:
            if args.profile not in profiles:
                _die(f"unknown profile {args.profile!r} — known: {', '.join(sorted(profiles))}")
            profile_id = args.profile
        else:
            matches = match_profiles(profiles, intent=intent or None)
            if not matches:
                profile_id = "generic"
            elif is_ambiguous(matches):
                top3 = " · ".join(f"{p} {s}" for p, s in matches[:3])
                if interactive:
                    pick, _ = _ask(prompt_fn, asked,
                                   f"    ambiguous ({top3}) — which profile? [{matches[0][0]}] ",
                                   matches[0][0], interactive=True)
                    if pick not in profiles:
                        _die(f"unknown profile {pick!r}")
                    profile_id = pick
                else:
                    _die(f"intent is ambiguous ({top3}) — pass --profile "
                         "(the CLI never guesses silently)")
            else:
                profile_id = matches[0][0]
                match_note = f" ({matches[0][1]})"
    profile = profiles.get(profile_id) if profile_id else None

    # Q3 — size (stakes).
    default_size = str((profile or {}).get("default_size") or "medium")
    size, _ = _ask(prompt_fn, asked,
                   f"3/5 size? [tiny/small/medium/large — default {default_size.upper()}] ",
                   default_size, interactive=interactive, flag=args.size)
    size = size.lower()
    if size not in SIZES:
        _die(f"size {size!r} not one of {', '.join(SIZES)}")

    # Q4 — posture (already asked FIRST for the takeover variant).
    if variant != "takeover":
        pa, _ = _ask(prompt_fn, asked,
                     "4/5 posture? [CIVILIAN/secure/team/secure-team] ",
                     posture_flag or "civilian", interactive=interactive,
                     flag=posture_flag)
        posture = _parse_posture(pa)
        if posture is None:
            _die(f"posture {pa!r} not one of {', '.join(POSTURES)}")

    # Q5 — targets + stack (greenfield variant only; stack needs the full
    # envelope because only full scaffolds).
    targets, stack = "claude", None
    if variant == "greenfield" and inv in ("partial", "full"):
        targets, _ = _ask(prompt_fn, asked,
                          "5/5 agent targets? [CLAUDE/+codex/+copilot/+gemini/+local — comma-separated] ",
                          "claude", interactive=interactive, flag=args.targets)
        if inv == "full":
            stack, _ = _ask(prompt_fn, asked,
                            "5/5 stack? [NODE-EXPRESS/fastapi-react/node-express-vue/undecided] ",
                            "node-express", interactive=interactive, flag=args.stack)
            stack = stack.lower()
            if stack not in CREATION_STACKS:
                _die(f"stack {stack!r} not one of {', '.join(CREATION_STACKS)}")

    packs: list[str] = []
    if inv in ("partial", "full") and profile:
        packs = [p.strip() for p in (args.packs or "").split(",") if p.strip()] \
            or list(profile.get("packs") or [])
        if args.packs:
            known = _known_packs()
            if known:
                bad = sorted(set(packs) - known)
                if bad:
                    _die(f"unknown pack(s) {', '.join(bad)} — known: {', '.join(sorted(known))}")

    # ── the answers + envelope-scoped plan (printed before anything runs) ──
    print(f"  involvement {inv}"
          + ("" if inv_explicit else " (default — rule it with --involvement)"))
    print(f"              envelope: {INVOLVEMENT_SCOPE[inv]}")
    print(f"  variant     {variant}"
          + (f" · posture {posture} (asked first — decides install ordering)"
             if variant == "takeover" else ""))
    if takeover_notes:
        for k, v in takeover_notes.items():
            print(f"              {k.replace('_', ' ')}: {v or '—'}")
    if profile_id:
        print(f"  profile     {profile_id}{match_note} · size {size} · posture {posture}")
    else:
        print(f"  size        {size} · posture {posture}")

    steps: list[tuple[str, str]] = []
    if variant == "greenfield" and inv == "full":
        pbits = {"secure": " --secure", "civilian-team": " --team",
                 "secure-team": " --secure --team"}.get(posture, "")
        sbit = f" --stack {stack}" if stack and stack != "undecided" else ""
        snote = (" (stack undecided — scaffold seeds its default; settle at architecture)"
                 if stack == "undecided" else "")
        steps.append(("scaffold", f"wf scaffold --out {root}{pbits}{sbit}{snote}"))
    if packs:
        onote = ("" if posture == "civilian" else
                 f" — runs BEFORE the block render so the block reads posture {posture} "
                 "(posture-first, 103 §2; never a silent civilian stamp)")
        steps.append(("install", f"wf install --out {root} --packs {','.join(packs)} "
                                 f"--targets {targets} --profile {posture}{onote}"))
    steps.append(("memory", "wf memory init (5-file resume pack)"))
    if inv != "observer" and profile_id:
        sat = " + satellite path warnings" if inv in ("satellite", "partial") else ""
        steps.append(("block", f"append activation block (profile {profile_id} · "
                               f"posture {posture}{sat}) to CLAUDE.md"))
    steps.append(("receipt", f"write _workflow/boot.json receipt (envelope {inv} confirmed "
                             f"· size {size} confirmed"
                             + (" · takeover_notes recorded" if takeover_notes else "") + ")"))

    print(f"\n  plan (scoped to envelope {inv}; nothing has been written):")
    for i, (_, desc) in enumerate(steps, 1):
        print(f"    {i}. {desc}")
    if profile and inv != "observer":
        disc = list((profile.get("entry_skills") or {}).get("discover") or [])
        first = ("bmad-competitive-features" if "bmad-competitive-features" in disc
                 else (disc[0] if disc else None))
        if first:
            overlay = (" (before any brief — planning-consumes-competitive-features overlay)"
                       if first == "bmad-competitive-features" else "")
            print(f"  first move: {first}{overlay}")

    # ── consent: interactive y / --yes / --apply with an explicit envelope ──
    if interactive:
        asked.append("run it? [y/N] ")
        go = (prompt_fn("  run it? [y/N] ") or "").strip().lower()
        if go not in ("y", "yes"):
            print("  nothing written.")
            return 0
    elif args.yes or (args.apply and inv_explicit):
        pass
    else:
        print("\n  nothing written — re-run with --yes to accept these answers "
              "(or --apply with an explicit --involvement; any flag answers "
              "its question).")
        return 0

    log, ok = _execute_creation(
        root, variant=variant, inv=inv, profile=profile, profile_id=profile_id,
        size=size, posture=posture, targets=targets, stack=stack, packs=packs,
        takeover_notes=takeover_notes, force_block=args.force_block)
    print("\n  applied:")
    for line in log:
        print(f"    {line}")
    return 0 if ok else 1


def _execute_creation(root: Path, *, variant: str, inv: str, profile: dict | None,
                      profile_id: str | None, size: str, posture: str,
                      targets: str, stack: str | None, packs: list[str],
                      takeover_notes: dict | None,
                      force_block: bool) -> tuple[list[str], bool]:
    """Execute the confirmed creation plan by WRAPPING the existing tools
    (scaffold — greenfield variant + full envelope only — install, memory
    init, block, boot.json). Install runs BEFORE the block render so the
    block reads the right posture (posture-first, 103 §2)."""
    log: list[str] = []
    ok = True
    claude_pre = (root / "CLAUDE.md").is_file()

    def _tool(script: str, argv: list[str], label: str, timeout: int = 600) -> bool:
        try:
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / script), *argv],
                capture_output=True, text=True, timeout=timeout, cwd=str(REPO_ROOT))
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.append(f"{label}: FAILED — {exc!r}")
            return False
        good = proc.returncode == 0
        detail = "" if good else " — " + (proc.stderr or proc.stdout).strip()[:200]
        log.append(f"{label}: {'ok' if good else 'FAILED' + detail}")
        return good

    if variant == "greenfield" and inv == "full":
        argv = ["--out", str(root)]
        if posture in ("secure", "secure-team"):
            argv.append("--secure")
        if posture in ("civilian-team", "secure-team"):
            argv.append("--team")
        if stack and stack != "undecided":
            argv += ["--stack", stack]
        ok &= _tool("wf-scaffold.py", argv, "scaffold")

    installed = False
    if packs:
        installed = _tool(
            "wf-install.py",
            ["--out", str(root), "--packs", ",".join(packs),
             "--targets", targets, "--profile", posture],
            f"wf install --profile {posture} (BEFORE the block — posture-first)")
        ok &= installed

    mem_ok = _tool("wf-memory.py", ["init", "--dir", str(root / "memory")],
                   "memory init", 60)
    ok &= mem_ok

    block_written = False
    if inv != "observer" and profile is not None:
        dirty = _claude_md_dirty(root)
        if claude_pre and dirty and not force_block:
            ok = False
            log.append("activation block REFUSED — pre-existing CLAUDE.md has "
                       "uncommitted changes (commit it or pass --force-block)")
        else:
            block = render_block({"bmad": scan_bmad(root)}, profile, [], size,
                                 posture, involvement=inv)
            verb = upsert_block(root / "CLAUDE.md", block)
            log.append(f"activation block {verb} in CLAUDE.md (posture {posture})")
            block_written = True

    today = _now_iso()[:10]
    if installed:
        pk_entry: dict[str, object] = {
            "state": "initialized", "packs": packs,
            "targets": [t.strip() for t in targets.split(",") if t.strip()],
            "profile": posture, "satellite_hint": False}
    elif inv == "satellite":
        pk_entry = {"state": "opted_out",
                    "note": "satellite envelope — skills via session-scope checkout; install out of envelope"}
    else:
        pk_entry = {"state": "absent"}
    receipt: dict[str, object] = {
        "schema": SCHEMA_VERSION, "generated": _now_iso(),
        "mode": "greenfield", "variant": variant, "posture": posture,
        "size": {"proposed": size, "confirmed": size, "at": today},
        "subsystems": {"memory": {"state": "initialized" if mem_ok else "absent"},
                       "packs": pk_entry},
        "activation": {"profile": profile_id, "confirmed": bool(profile_id),
                       "involvement": inv, "involvement_confirmed": True,
                       "involvement_proposed": inv, "addons": [],
                       "applied_at": today if block_written else None},
        "receipts": {"created": today, "creator": "wf start creation mode (M3)"},
    }
    if takeover_notes:
        receipt["takeover_notes"] = takeover_notes
    if stack:
        receipt["stack_choice"] = stack
    write_boot(root, receipt)
    log.append(f"receipt written: {BOOT_REL} (envelope {inv} confirmed)")
    return log, ok


# ── selftest ─────────────────────────────────────────────────────────────────


def _mk(root: Path, rel: str, text: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _fixture_brownfield(root: Path) -> None:
    """A mid-flight glue project: ts/nextjs, vitest, PRD done, sprint running."""
    _mk(root, "package.json", json.dumps({
        "name": "demo", "dependencies": {"next": "14.0.0", "react": "18"},
        "devDependencies": {"vitest": "1.0.0"},
    }))
    _mk(root, "src/index.ts", "export const x = 1\n")
    _mk(root, ".github/workflows/ci.yml", "on: push\n")
    _mk(root, "_bmad/bmm/config.yaml",
        "project_name: demo\noutput_folder: _bmad-output\n"
        "planning_artifacts: '{project-root}/_bmad-output/planning-artifacts'\n"
        "implementation_artifacts: '{project-root}/_bmad-output/implementation-artifacts'\n")
    _mk(root, "_bmad/core/config.yaml", "project_name: demo\n")
    _mk(root, "_bmad-output/planning-artifacts/product-brief.md", "# brief\n")
    _mk(root, "_bmad-output/planning-artifacts/prd.md", "status: final\n# PRD\n")
    _mk(root, "_bmad-output/planning-artifacts/architecture.md", "# arch\n")
    _mk(root, "_bmad-output/planning-artifacts/epic-1.md", "# e1\n")
    _mk(root, "_bmad-output/planning-artifacts/epic-2.md", "# e2\n")
    _mk(root, "_bmad-output/implementation-artifacts/sprint-status.yaml",
        "development_status:\n  story-1: in-progress\n  story-2: in-progress\n"
        "  story-3: backlog\n  story-4: backlog\n  story-5: backlog\n")
    _mk(root, "_bmad-output/implementation-artifacts/story-1.md",
        "# story\n## Acceptance Criteria\n- AC1\n")
    _mk(root, "memory/project-brief.md", "## Purpose\n")
    _mk(root, "memory/current-state.md", "## Done\n")
    _mk(root, "memory/decisions.md", "## Decisions\n")
    _mk(root, "memory/open-risks.md", "## Open risks\n")
    _mk(root, "memory/next-actions.md", "## Next actions\n")
    _mk(root, ".claude/skills/bmad-dev-story/SKILL.md", "# s\n")
    _mk(root, ".claude/skills/bmad-dev-story/evals/triggers.json",
        json.dumps([{"query": "dev this story", "should_trigger": True}]))
    _mk(root, ".claude/skills/bmad-prd/SKILL.md", "# s\n")
    _mk(root, "pages/index.tsx", "export default function H() { return null }\n")
    _mk(root, "CLAUDE.md", "# demo\nUse bmad-dev-story for stories.\n")


def selftest() -> int:
    problems: list[str] = []

    # Greenfield: empty dir.
    with tempfile.TemporaryDirectory(prefix="wfstart-green-") as td:
        boot = scan(Path(td))
        if boot["mode"] != "greenfield":
            problems.append(f"greenfield: empty dir classified {boot['mode']!r}")
        if "creation mode" not in str(boot.get("note", "")):
            problems.append("greenfield: note does not point at creation mode")
        report = render_report(boot, Path(td))
        if "greenfield" not in report:
            problems.append("greenfield: report missing mode line")

    # Docs-only dir is still greenfield (no source files).
    with tempfile.TemporaryDirectory(prefix="wfstart-docs-") as td:
        _mk(Path(td), "README.md", "# hi\n")
        if scan(Path(td))["mode"] != "greenfield":
            problems.append("docs-only dir should classify greenfield")

    # Brownfield glue fixture: stack, phase, subsystems, readiness, metrics.
    with tempfile.TemporaryDirectory(prefix="wfstart-brown-") as td:
        root = Path(td)
        _fixture_brownfield(root)
        boot = scan(root)
        if boot["mode"] != "brownfield":
            problems.append("brownfield fixture classified greenfield")
        st = boot["stack"]
        if st["framework"] != "nextjs" or "ts" not in st["langs"]:
            problems.append(f"stack: expected nextjs/ts, got {st['framework']}/{st['langs']}")
        if "vitest" not in st["tests"] or "github" not in st["ci"]:
            problems.append(f"stack: tests/ci wrong: {st['tests']}/{st['ci']}")
        b = boot["bmad"]
        if b["state"] != "glue":
            problems.append(f"bmad: expected glue, got {b['state']}")
        if b["phase"] != "4-implementation" or b["next_required"] != "bmad-dev-story":
            problems.append(f"bmad: phase/next wrong: {b['phase']}/{b['next_required']}")
        if b["artifacts"].get("prd") != "final" or b["artifacts"].get("epics") != 2:
            problems.append(f"bmad: artifact detail wrong: {b['artifacts']}")
        if "2 in-progress" not in (b["sprint_status"] or "") or "3 backlog" not in (b["sprint_status"] or ""):
            problems.append(f"bmad: sprint summary wrong: {b['sprint_status']}")
        s = boot["subsystems"]
        if s["memory"]["state"] != "initialized" or s["learn"]["state"] != "absent":
            problems.append(f"subsystems: memory/learn wrong: {s['memory']}/{s['learn']}")
        r = boot["readiness"]
        if r["memory"] != "READY" or not r["learn"].startswith("SETUP-NEEDED") or r["audit"] != "READY":
            problems.append(f"readiness wrong: {r}")
        m = boot["metrics"]
        if m["skills_installed"] != 2 or m["skills_referenced_always_loaded"] != 1 or m["firing_path_pct"] != 50:
            problems.append(f"metrics wrong: {m}")
        if m["invocation_rate_baseline"] is not None:
            problems.append("metrics: baseline must be PENDING (None), never fabricated")
        corpus = emit_eval_corpus(root)
        with_q = [c for c in corpus if c["query"]]
        without_q = [c for c in corpus if c["query"] is None]
        if len(with_q) != 1 or len(without_q) != 1:
            problems.append(f"eval corpus wrong: {corpus}")

        # Phase derivation enters where the project is: remove sprint+stories
        # -> next is sprint-planning at 3-solutioning, never back to phase 1.
        (root / "_bmad-output/implementation-artifacts/sprint-status.yaml").unlink()
        (root / "_bmad-output/implementation-artifacts/story-1.md").unlink()
        b2 = scan_bmad(root)
        if b2["phase"] != "3-solutioning" or b2["next_required"] != "bmad-sprint-planning":
            problems.append(f"phase derivation wrong after sprint removal: {b2['phase']}/{b2['next_required']}")

        # --write receipt + opt-out preservation across rescans.
        boot3 = scan(root)
        dest = write_boot(root, boot3)
        if not dest.is_file():
            problems.append("--write did not create boot.json")
        receipt = _read_json(dest)
        receipt["subsystems"]["context"] = {"state": "opted_out"}
        dest.write_text(json.dumps(receipt), encoding="utf-8")
        boot4 = scan(root)
        if boot4["subsystems"]["context"]["state"] != "opted_out":
            problems.append("rescan did not honor a recorded opt-out")
        write_boot(root, boot4)
        receipt2 = _read_json(dest)
        if receipt2["subsystems"]["context"]["state"] != "opted_out":
            problems.append("--write laundered a recorded opt-out into absent")

        # Report renders the load-bearing lines.
        rep = render_report(boot4, root)
        for needle in ("brownfield", "glue", "phase", "readiness", "firing path"):
            if needle not in rep:
                problems.append(f"report missing {needle!r}")

    # Monorepo detection + full-install detection + unparseable fail-closed.
    with tempfile.TemporaryDirectory(prefix="wfstart-mono-") as td:
        root = Path(td)
        _mk(root, "pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n")
        _mk(root, "apps/web/package.json", "{}")
        _mk(root, "apps/web/src/a.ts", "1\n")
        mode = detect_mode(root)
        if not mode["monorepo"]:
            problems.append("monorepo: pnpm-workspace.yaml not detected")
    with tempfile.TemporaryDirectory(prefix="wfstart-full-") as td:
        root = Path(td)
        _mk(root, "src/a.py", "x=1\n")
        _mk(root, "_bmad/_config/manifest.yaml",
            "installation:\n  version: 6.8.0\n")  # the real installer's shape
        b = scan_bmad(root)
        if b["state"] != "full" or b["version"] != "6.8.0":
            problems.append(f"full-install detection wrong: {b['state']}/{b['version']}")
    with tempfile.TemporaryDirectory(prefix="wfstart-unparse-") as td:
        root = Path(td)
        _mk(root, "src/a.py", "x=1\n")
        _mk(root, "_bmad/bmm/config.yaml", "foo: [unclosed\n")
        _mk(root, "_bmad/core/config.yaml", "ok: 1\n")
        try:
            b = scan_bmad(root)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"unparseable config crashed the scan: {exc!r}")
        else:
            if b["state"] != "glue":
                problems.append(f"unparseable config changed state detection: {b['state']}")

    # ── M2: catalog, matcher, size, plan authority, block, apply ────────────
    cat_problems = check_catalog()
    if cat_problems:
        problems.append(f"M2 catalog: shipped catalog invalid: {cat_problems[:3]}")
    profiles, addons = load_catalog()
    if len(profiles) != 13 or "generic" not in profiles:
        problems.append(f"M2 catalog: expected 13 profiles incl generic, got {len(profiles)}")
    if "writer-kit" not in addons:
        problems.append("M2 catalog: writer-kit addon missing")

    m = match_profiles(profiles, stack={"framework": "nextjs", "langs": ["ts"], "tests": ["vitest"]})
    if not m or m[0][0] != "web-app":
        problems.append(f"M2 matcher: nextjs stack should top web-app, got {m[:2]}")
    m2 = match_profiles(profiles, intent="I want to make a roguelike deckbuilder game")
    if not m2 or m2[0][0] != "game":
        problems.append(f"M2 matcher: game intent wrong: {m2[:2]}")
    if match_profiles(profiles, stack={"langs": []}, intent=""):
        problems.append("M2 matcher: empty input must zero-match (generic fallback)")
    if not is_ambiguous([("a", 0.5), ("b", 0.45)]) or is_ambiguous([("a", 0.9), ("b", 0.2)]):
        problems.append("M2 matcher: ambiguity rule wrong")
    game = profiles["game"]
    props = propose_addons(addons, game, "a roguelike where the story matters")
    if not any(aid == "writer-kit" for aid, _ in props):
        problems.append(f"M2 addons: 'story matters' should propose writer-kit, got {props}")
    web = profiles["web-app"]
    props2 = propose_addons(addons, web, "with strong test strategy")
    if any(a.get("ref") == "tea" for _, a in props2):
        problems.append("M2 addons: must not propose a pack the profile already has")

    # Field-trace hardening (docs/traces/102-takeover-boot-trace.md):
    with tempfile.TemporaryDirectory(prefix="wfstart-nest-") as td:
        root = Path(td)
        _mk(root, "package.json", json.dumps({"dependencies": {"@nestjs/core": "10.0.0"}}))
        _mk(root, "src/main.ts", "1\n")
        st = scan_stack(root)
        m = match_profiles(profiles, stack=st)
        if st["framework"] != "nestjs" or not m or m[0][0] != "api-service":
            problems.append(f"trace-fix: nestjs should fingerprint + top api-service: {st['framework']}/{m[:1]}")
    with tempfile.TemporaryDirectory(prefix="wfstart-headless-") as td:
        root = Path(td)
        _mk(root, "package.json", json.dumps({"dependencies": {"next": "14.0.0"}}))
        _mk(root, "src/route.ts", "1\n")
        st = scan_stack(root)
        m = match_profiles(profiles, stack=st)
        if st["framework"] != "nextjs-headless" or not m or m[0][0] != "api-service":
            problems.append(f"trace-fix: UI-less next should be headless->api-service: {st['framework']}/{m[:1]}")
    with tempfile.TemporaryDirectory(prefix="wfstart-altbmad-") as td:
        root = Path(td)
        _mk(root, "src/a.py", "1\n")
        _mk(root, "bmad/config.yaml", "x: 1\n")
        b = scan_bmad(root)
        if b["state"] != "none" or "nonstandard" not in (b.get("note") or ""):
            problems.append(f"trace-fix: nonstandard BMAD layout note missing: {b}")
    blk = render_block({"bmad": {}, "subsystems": {"packs": {}}},
                       profiles["web-app"], [], "small", "civilian")
    if "wf learn add --type" not in blk:
        problems.append("trace-fix: activation block must carry wf learn add usage")

    # GPT-game trace fixes: pack decline kills the install step forever;
    # satellite adoption (block without packs) is a stated hint, not silence.
    with tempfile.TemporaryDirectory(prefix="wfstart-satellite-") as td:
        root = Path(td)
        _fixture_brownfield(root)
        boot = scan(root)
        enrich(boot, root, profile_arg="web-app", involvement_arg="full")
        if not any(s["action"] == "install" for s in boot["_plan"]["auto"]):
            problems.append("gpt-fix: install step expected before any decline")
        boot = scan(root)
        record_decisions(boot, decline=["packs"], accept=[])
        enrich(boot, root, profile_arg="web-app", involvement_arg="full")
        if any(s["action"] == "install" for s in boot["_plan"]["auto"]):
            problems.append("gpt-fix: same-run --decline packs must kill the install step")
        write_boot(root, boot)
        boot2 = scan(root)
        enrich(boot2, root)
        if boot2["subsystems"]["packs"].get("state") != "opted_out":
            problems.append("gpt-fix: packs opt-out did not survive the rescan")
        if any(s["action"] == "install" for s in boot2["_plan"]["auto"]):
            problems.append("gpt-fix: rescan re-proposed install against a recorded decline")
        (root / "CLAUDE.md").write_text(
            "# x\n" + BLOCK_START + "\n| a | b |\n" + BLOCK_END + "\n", encoding="utf-8")
        boot3 = scan(root)
        if not boot3["subsystems"]["packs"].get("satellite_hint"):
            problems.append("gpt-fix: block-without-packs must raise the satellite hint")
        enrich(boot3, root)
        if "satellite adoption?" not in render_report(boot3, root):
            problems.append("gpt-fix: report missing the satellite note")

    # 103 trace fix: workspace-member deps feed framework, tests, AND risk.
    with tempfile.TemporaryDirectory(prefix="wfstart-ws-") as td:
        root = Path(td)
        _mk(root, "package.json", json.dumps({"name": "m", "workspaces": ["frontend", "backend"]}))
        _mk(root, "frontend/package.json", json.dumps(
            {"dependencies": {"react": "19.0.0"}, "devDependencies": {"vitest": "1.0.0"}}))
        _mk(root, "backend/package.json", json.dumps({"dependencies": {"pg": "8.0.0"}}))
        _mk(root, "frontend/src/a.tsx", "1\n")
        st = scan_stack(root)
        if st["framework"] != "react" or "vitest" not in st["tests"]:
            problems.append(f"103-fix: workspace deps invisible: {st['framework']}/{st['tests']}")
        m = match_profiles(profiles, stack=st)
        if not m or m[0][0] != "web-app":
            problems.append(f"103-fix: workspace react should top web-app, got {m[:1]}")
        sz = classify_size(root, st)
        if "user-data" not in sz["risk"]:
            problems.append(f"103-fix: workspace pg risk invisible: {sz}")

    with tempfile.TemporaryDirectory(prefix="wfstart-m2-") as td:
        root = Path(td)
        _fixture_brownfield(root)
        # record packs so the plan needs no wf install run in the selftest
        _mk(root, "workflow.packs.yaml",
            "version: 1\nprofile: civilian\npacks:\n  - core\n  - bmm\n  - tea\n"
            "targets:\n  - claude\n")
        # config present but bare: validate stays SETUP-NEEDED -> O1 offer
        _mk(root, "bmad.config.yaml", "project_name: demo\n")
        _mk(root, "src/pay.ts", "import Stripe from 'stripe'\n")
        _mk(root, "package.json", json.dumps({
            "name": "demo", "dependencies": {"next": "14.0.0", "stripe": "12.0.0"},
            "devDependencies": {"vitest": "1.0.0"}, "scripts": {"test": "vitest run"},
        }))

        boot = scan(root)
        enrich(boot, root)
        sz = boot["size"]
        if sz["proposed"] != "medium" or "payments" not in sz["risk"]:
            problems.append(f"M2 size: stripe fixture should be medium/payments, got {sz}")
        act = boot["activation"]
        if act["profile"] != "web-app" or act["confirmed"]:
            problems.append(f"M2 activation: expected unconfirmed web-app proposal, got {act}")
        r = boot["readiness"]
        if "browse" not in r or "validate" not in r or not r["validate"].startswith("SETUP-NEEDED"):
            problems.append(f"M2 readiness: profile-relative probes wrong: { {k: r.get(k) for k in ('browse', 'validate', 'mutate')} }")
        if r.get("mutate") != "READY":
            problems.append(f"M2 readiness: test script present, mutate should be READY: {r.get('mutate')}")
        plan = boot["_plan"]
        if any(s["action"] == "install" for s in plan["auto"]):
            problems.append("M2 plan: packs recorded — install step must not appear")
        if any(s["action"] == "memory-init" for s in plan["auto"]):
            problems.append("M2 plan: memory initialized — init step must not appear")
        if not any(o["action"] == "offer-validate" for o in plan["offers"]):
            problems.append("M2 plan: missing validation offer despite SETUP-NEEDED + config present")
        if not any("guard" in y for y in plan["yours"]):
            problems.append("M2 plan: guard/hook changes must be in the stop-and-ask class")

        # Block: bounded, marker-fenced, refresh-only-inside-markers.
        block = render_block(boot, profiles["web-app"], [("writer-kit", addons["writer-kit"])],
                             "medium", "civilian")
        if not (block.startswith(BLOCK_START) and block.rstrip().endswith(BLOCK_END)):
            problems.append("M2 block: markers missing")
        if len(block.splitlines()) > 25:
            problems.append(f"M2 block: too long ({len(block.splitlines())} lines; budget ~20)")
        if "+writer" not in block:
            problems.append("M2 block: selected addon not rendered in header")
        cm = root / "CLAUDE.md"
        before = "# demo\nUser text ABOVE.\n"
        cm.write_text(before, encoding="utf-8")
        if upsert_block(cm, block) != "appended":
            problems.append("M2 block: first upsert should append")
        text1 = cm.read_text(encoding="utf-8")
        if not text1.startswith(before):
            problems.append("M2 block: append touched text outside the markers")
        block2 = block.replace("size: medium", "size: large")
        if upsert_block(cm, block2) != "refreshed":
            problems.append("M2 block: second upsert should refresh")
        text2 = cm.read_text(encoding="utf-8")
        if text2.count(BLOCK_START) != 1 or "size: large" not in text2 \
                or not text2.startswith(before):
            problems.append("M2 block: refresh duplicated or leaked outside markers")

        # apply: unconfirmed ENVELOPE -> observer-safe subset only (D5), stated;
        # confirmed envelope + unconfirmed profile -> block skipped; confirmed
        # both -> written; --decline records opted_out; --accept reverses;
        # boot.json persists.
        log = apply_plan(root, boot, accept=[], force_block=False)
        if not any("observer-safe subset" in l for l in log):
            problems.append(f"M3 apply: unconfirmed envelope must state the observer-safe subset: {log}")
        if any("activation block" in l and ("appended" in l or "refreshed" in l) for l in log):
            problems.append(f"M3 apply: unconfirmed envelope must not write the block: {log}")
        boot_e = scan(root)
        enrich(boot_e, root, involvement_arg="full")
        log_e = apply_plan(root, boot_e, accept=[], force_block=False)
        if not any("SKIPPED — profile not confirmed" in l for l in log_e):
            problems.append(f"M2 apply: unconfirmed profile must skip the block: {log_e}")
        boot2 = scan(root)
        enrich(boot2, root, profile_arg="web-app", size_arg="medium",
               involvement_arg="full")
        record_decisions(boot2, decline=["spec"], accept=[])
        log2 = apply_plan(root, boot2, accept=["O1"], force_block=False)
        write_boot(root, boot2)
        if not any("activation block" in l and ("appended" in l or "refreshed" in l) for l in log2):
            problems.append(f"M2 apply: confirmed profile should write the block: {log2}")
        if "validation:" not in (root / "bmad.config.yaml").read_text(encoding="utf-8") \
                if (root / "bmad.config.yaml").is_file() else True:
            problems.append("M2 apply: accepted O1 did not seed the validation block")
        receipt = _read_json(root / BOOT_REL)
        if receipt["activation"]["profile"] != "web-app" or not receipt["activation"]["applied_at"]:
            problems.append(f"M2 apply: receipt activation wrong: {receipt.get('activation')}")
        if receipt["activation"].get("involvement") != "full" \
                or not receipt["activation"].get("involvement_confirmed"):
            problems.append(f"M3 apply: receipt envelope wrong: {receipt.get('activation')}")
        if receipt["subsystems"]["spec"]["state"] != "opted_out":
            problems.append("M2 apply: --decline spec not persisted")
        if receipt["size"]["confirmed"] != "medium":
            problems.append("M2 apply: --size medium not persisted")
        if "_plan" in receipt or "_profile_obj" in receipt:
            problems.append("M2 apply: transient keys leaked into boot.json")
        boot3 = scan(root)
        enrich(boot3, root)
        if not boot3["activation"]["confirmed"] or boot3["activation"]["profile"] != "web-app":
            problems.append("M2 apply: prior confirmed profile must survive a rescan")
        if boot3["activation"].get("involvement") != "full" \
                or not boot3["activation"].get("involvement_confirmed"):
            problems.append("M3 apply: confirmed envelope must survive a rescan")
        if boot3["subsystems"]["spec"]["state"] != "opted_out":
            problems.append("M2 apply: recorded opt-out did not survive the rescan")
        record_decisions(boot3, decline=[], accept=["spec"])
        if boot3["subsystems"]["spec"]["state"] != "absent":
            problems.append("M2 apply: --accept spec did not reverse the opt-out")

        # Dirty-tree policy: git repo + dirty CLAUDE.md -> block refused
        # without --force-block, written with it.
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=False)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=False,
                       capture_output=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c",
                        "user.name=t", "commit", "-qm", "base"], check=False,
                       capture_output=True)
        cm.write_text(cm.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")
        boot4 = scan(root)
        enrich(boot4, root, profile_arg="web-app", involvement_arg="full")
        log4 = apply_plan(root, boot4, accept=[], force_block=False)
        if not any("REFUSED" in l for l in log4):
            problems.append(f"M2 apply: dirty CLAUDE.md must refuse the block: {log4}")
        log5 = apply_plan(root, boot4, accept=[], force_block=True)
        if not any("refreshed" in l or "appended" in l for l in log5):
            problems.append(f"M2 apply: --force-block should write on a dirty tree: {log5}")

    # ── M3: involvement envelope (D5) — proposal from evidence + scoping ───
    with tempfile.TemporaryDirectory(prefix="wfstart-inv-") as td:
        root = Path(td)
        _fixture_brownfield(root)
        # bare evidence -> observer proposal; plan scoped to observer.
        boot = scan(root)
        enrich(boot, root, profile_arg="web-app")
        act = boot["activation"]
        if act["involvement"] != "observer" or act["involvement_confirmed"]:
            problems.append(f"M3 envelope: bare fixture should propose observer, got {act['involvement']}/{act['involvement_confirmed']}")
        actions = [s["action"] for s in boot["_plan"]["auto"]]
        if "install" in actions or "block" in actions:
            problems.append(f"M3 scoping: observer plan must have no install/block steps: {actions}")
        if boot["_plan"]["offers"] or boot["_plan"]["yours"]:
            problems.append("M3 scoping: observer plan must carry no offers/stop-and-ask items")
        rep = render_report(boot, root)
        next_line = next((l for l in rep.splitlines() if "next: wf start" in l), "")
        if "--involvement observer" not in next_line or "--profile" in next_line:
            problems.append(f"M3 hint: observer next-hint must name the envelope and nothing beyond it: {next_line!r}")
        # packs evidence -> full proposal.
        _mk(root, "workflow.packs.yaml",
            "version: 1\nprofile: civilian\npacks:\n  - core\ntargets:\n  - claude\n")
        boot = scan(root)
        enrich(boot, root)
        if boot["activation"]["involvement"] != "full":
            problems.append(f"M3 envelope: packs evidence should propose full, got {boot['activation']['involvement']}")
        # satellite hint (block without packs) -> satellite proposal.
        (root / "workflow.packs.yaml").unlink()
        (root / "CLAUDE.md").write_text(
            "# x\n" + BLOCK_START + "\n| a | b |\n" + BLOCK_END + "\n", encoding="utf-8")
        boot = scan(root)
        enrich(boot, root)
        if boot["activation"]["involvement"] != "satellite":
            problems.append(f"M3 envelope: satellite hint should propose satellite, got {boot['activation']['involvement']}")

    # M3: confirmed satellite — block-not-install, auto opt-out, persistence.
    with tempfile.TemporaryDirectory(prefix="wfstart-sat3-") as td:
        root = Path(td)
        _fixture_brownfield(root)
        boot = scan(root)
        enrich(boot, root, profile_arg="web-app", involvement_arg="satellite")
        actions = [s["action"] for s in boot["_plan"]["auto"]]
        if "install" in actions or "block" not in actions:
            problems.append(f"M3 satellite: plan must have the block and never install: {actions}")
        if boot["subsystems"]["packs"]["state"] != "opted_out":
            problems.append("M3 satellite: packs must be auto-marked opted_out")
        apply_plan(root, boot, accept=[], force_block=False)
        write_boot(root, boot)
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        if "Satellite mode" not in text or "absolute --dir/--file" not in text:
            problems.append("M3 satellite: block missing the baked absolute-path tool warnings")
        if "involvement: satellite" not in text:
            problems.append("M3 satellite: block header missing the involvement tag")
        boot2 = scan(root)
        enrich(boot2, root)
        act2 = boot2["activation"]
        if act2["involvement"] != "satellite" or not act2["involvement_confirmed"]:
            problems.append("M3 satellite: confirmed envelope did not survive the rescan")
        if boot2["subsystems"]["packs"]["state"] != "opted_out":
            problems.append("M3 satellite: pack opt-out did not survive the rescan")
        if any(s["action"] == "install" for s in boot2["_plan"]["auto"]):
            problems.append("M3 satellite: rescan re-proposed install inside a satellite envelope")

    # M3: partial — --packs implies the ruling; install carries ONLY the
    # subset; install precedes the block in the plan; real apply materializes
    # the subset.
    with tempfile.TemporaryDirectory(prefix="wfstart-part3-") as td:
        root = Path(td)
        _fixture_brownfield(root)
        boot = scan(root)
        enrich(boot, root, profile_arg="web-app", packs_arg=["core"])
        act = boot["activation"]
        if act["involvement"] != "partial" or not act["involvement_confirmed"]:
            problems.append(f"M3 partial: --packs must imply a confirmed partial envelope: {act['involvement']}/{act['involvement_confirmed']}")
        inst = [s for s in boot["_plan"]["auto"] if s["action"] == "install"]
        if not inst or "--packs core " not in inst[0]["desc"] or "bmm" in inst[0]["desc"]:
            problems.append(f"M3 partial: install step must carry ONLY the chosen subset: {inst}")
        idx = {s["action"]: i for i, s in enumerate(boot["_plan"]["auto"])}
        if "install" not in idx or "block" not in idx or idx["install"] > idx["block"]:
            problems.append(f"M3 ordering: install must precede the block in the plan: {idx}")
        rep = render_report(boot, root)
        next_line = next((l for l in rep.splitlines() if "next: wf start" in l), "")
        if "--involvement partial" not in next_line or "--packs core" not in next_line:
            problems.append(f"M3 partial: next-hint must carry the envelope + subset: {next_line!r}")
        apply_plan(root, boot, accept=[], force_block=False)
        pk = _read_yaml(root / "workflow.packs.yaml")
        if not isinstance(pk, dict) or pk.get("packs") != ["core"]:
            problems.append(f"M3 partial: applied install must materialize only the subset: {pk}")

    # ── M3: creation mode (flag-driven, real subprocess CLI runs) ──────────
    def _run_cli(argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), *argv],
            capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)

    # non-interactive without --yes: plan only, nothing written.
    with tempfile.TemporaryDirectory(prefix="wfstart-plan-") as td:
        r = _run_cli(["--dir", td, "--involvement", "full", "--profile", "web-app"])
        if r.returncode != 0 or "nothing written" not in r.stdout:
            problems.append(f"M3 create: plan-only run must write nothing and say so: rc={r.returncode}")
        if any(Path(td).iterdir()):
            problems.append("M3 create: plan-only run wrote files")

    # greenfield full: scaffold + install + memory + block + receipt.
    with tempfile.TemporaryDirectory(prefix="wfstart-create-") as td:
        root = Path(td)
        r = _run_cli(["--dir", td, "--involvement", "full", "--profile", "web-app",
                      "--size", "small", "--stack", "node-express", "--yes"])
        if r.returncode != 0:
            problems.append(f"M3 create: full greenfield run failed rc={r.returncode}: {(r.stderr or r.stdout)[-300:]}")
        pk = _read_yaml(root / "workflow.packs.yaml")
        if not isinstance(pk, dict) or pk.get("profile") != "civilian":
            problems.append(f"M3 create: packs manifest missing/wrong: {pk if not isinstance(pk, dict) else pk.get('profile')}")
        text = (root / "CLAUDE.md").read_text(encoding="utf-8") if (root / "CLAUDE.md").is_file() else ""
        if BLOCK_START not in text or "posture: civilian" not in text:
            problems.append("M3 create: activation block missing from the scaffolded CLAUDE.md")
        if not (root / "memory" / "project-brief.md").is_file():
            problems.append("M3 create: memory pack missing")
        if not (root / ".claude" / "skills" / "bmad-prd").is_dir():
            problems.append("M3 create: install did not materialize the pack skills")
        receipt = _read_json(root / BOOT_REL) or {}
        act = receipt.get("activation") or {}
        if act.get("profile") != "web-app" or act.get("involvement") != "full" \
                or not act.get("involvement_confirmed") \
                or (receipt.get("size") or {}).get("confirmed") != "small" \
                or receipt.get("variant") != "greenfield":
            problems.append(f"M3 create: receipt wrong: {act}/{receipt.get('size')}/{receipt.get('variant')}")
        if "first move: bmad-competitive-features" not in r.stdout:
            problems.append("M3 create: first-move line missing from the plan output")
        # the creation receipt survives the project's first REAL scan.
        _mk(root, "src/index.ts", "export const x = 1\n")
        boot = scan(root)
        enrich(boot, root)
        act = boot["activation"]
        if act["involvement"] != "full" or not act["involvement_confirmed"] \
                or act["profile"] != "web-app" or not act["confirmed"]:
            problems.append(f"M3 create: creation receipt did not survive the first real scan: {act}")

    # posture-first (103 §2): a --secure greenfield run installs --profile
    # secure BEFORE the block render, so the block reads posture secure.
    with tempfile.TemporaryDirectory(prefix="wfstart-sec3-") as td:
        root = Path(td)
        r = _run_cli(["--dir", td, "--involvement", "full", "--profile", "web-app",
                      "--size", "small", "--secure", "--yes"])
        if r.returncode != 0:
            problems.append(f"M3 posture-first: secure run failed rc={r.returncode}: {(r.stderr or r.stdout)[-300:]}")
        pk = _read_yaml(root / "workflow.packs.yaml")
        if not isinstance(pk, dict) or pk.get("profile") != "secure":
            problems.append(f"M3 posture-first: install did not stamp profile secure: {pk if not isinstance(pk, dict) else pk.get('profile')}")
        text = (root / "CLAUDE.md").read_text(encoding="utf-8") if (root / "CLAUDE.md").is_file() else ""
        if "posture: secure" not in text:
            problems.append("M3 posture-first: block did not read posture secure")
        if "BEFORE the block" not in r.stdout:
            problems.append("M3 posture-first: plan does not state the install-before-block ordering")

    # takeover variant: no scaffold; the 103 question set recorded to
    # boot.json takeover_notes; posture secure honored end to end.
    with tempfile.TemporaryDirectory(prefix="wfstart-take3-") as td:
        root = Path(td)
        r = _run_cli(["--dir", td, "--variant", "takeover", "--secure",
                      "--involvement", "full", "--profile", "api-service",
                      "--size", "medium",
                      "--seams", "shared wire contract vendored; api canonical",
                      "--deploy-targets", "edge bundle + openshift",
                      "--port-contracts", "3050/3051 fixed", "--yes"])
        if r.returncode != 0:
            problems.append(f"M3 takeover: run failed rc={r.returncode}: {(r.stderr or r.stdout)[-300:]}")
        receipt = _read_json(root / BOOT_REL) or {}
        notes = receipt.get("takeover_notes") or {}
        if notes.get("contract_seams") != "shared wire contract vendored; api canonical" \
                or notes.get("deploy_targets") != "edge bundle + openshift" \
                or notes.get("port_contracts") != "3050/3051 fixed":
            problems.append(f"M3 takeover: takeover_notes not recorded: {notes}")
        if receipt.get("variant") != "takeover" or receipt.get("posture") != "secure":
            problems.append(f"M3 takeover: variant/posture not recorded: {receipt.get('variant')}/{receipt.get('posture')}")
        if (root / "README.md").is_file():
            problems.append("M3 takeover: scaffold must not run for the takeover variant")
        pk = _read_yaml(root / "workflow.packs.yaml")
        if not isinstance(pk, dict) or pk.get("profile") != "secure":
            problems.append("M3 takeover: install did not run secure-first")

    # observer creation: memory + receipt ONLY — no block, no packs, no scaffold.
    with tempfile.TemporaryDirectory(prefix="wfstart-obs3-") as td:
        root = Path(td)
        r = _run_cli(["--dir", td, "--involvement", "observer", "--yes"])
        if r.returncode != 0:
            problems.append(f"M3 observer create: run failed rc={r.returncode}")
        if not (root / "memory" / "project-brief.md").is_file() or not (root / BOOT_REL).is_file():
            problems.append("M3 observer create: memory + receipt expected")
        if (root / "CLAUDE.md").is_file() or (root / "workflow.packs.yaml").is_file():
            problems.append("M3 observer create: wrote beyond the observer envelope")
        act = (_read_json(root / BOOT_REL) or {}).get("activation") or {}
        if act.get("involvement") != "observer" or not act.get("involvement_confirmed"):
            problems.append(f"M3 observer create: envelope not recorded: {act}")

    # interactive interview path (monkeypatched prompt): Q0 is involvement
    # (D5), takeover asks posture BEFORE seams (103), declining writes nothing.
    with tempfile.TemporaryDirectory(prefix="wfstart-tty3-") as td:
        import contextlib
        import io
        root = Path(td)
        prompts: list[str] = []
        answers = iter(["full", "takeover", "secure",
                        "api owns the contract", "edge+cloud", "3050/3051",
                        "", "", "n"])

        def _fake_prompt(q: str) -> str:
            prompts.append(q)
            return next(answers, "n")

        args = build_parser().parse_args(["--dir", td, "--profile", "api-service"])
        with contextlib.redirect_stdout(io.StringIO()):
            rc = run_creation(root, args, prompt_fn=_fake_prompt, interactive=True)
        if rc != 0:
            problems.append(f"M3 interview: declined run should exit 0, got {rc}")
        if not prompts or "involvement" not in prompts[0]:
            problems.append(f"M3 interview: Q0 must be involvement (D5 question zero), got {prompts[:1]}")
        p_post = next((i for i, q in enumerate(prompts) if "posture" in q), None)
        p_seam = next((i for i, q in enumerate(prompts) if "seams" in q), None)
        if p_post is None or p_seam is None or p_post > p_seam:
            problems.append(f"M3 interview: takeover must ask posture FIRST (103 §2): {prompts}")
        if any(root.iterdir()):
            problems.append("M3 interview: declining the run must write nothing")

    if problems:
        print("wf start selftest: FAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print(
        "wf start selftest: PASS "
        "(M1: greenfield/docs-only/brownfield modes; stack fingerprint; glue+full "
        "BMAD detection with config-resolved paths; phase enters mid-flight; "
        "opt-outs preserved; readiness fixed set; firing-path metric; eval corpus "
        "honest denominator; baseline never fabricated; fail-closed YAML labeling; "
        "monorepo detection. M2: shipped 13-profile catalog validates fail-closed; "
        "deterministic matcher + ambiguity rule + generic fallback; D3 add-on "
        "proposals never duplicate profile packs; size/risk proposal; plan "
        "authority classes (stop-and-ask never executed); ~20-line marker-fenced "
        "block never touches outside text; apply: unconfirmed-profile skip, "
        "dirty-CLAUDE.md refusal + --force-block, --decline/--accept opt-out "
        "round-trip, confirmed size/profile persisted and survive rescans. "
        "M3 (D5): envelope proposed from evidence (bare->observer, "
        "packs->full, block-without-packs->satellite), never auto-confirmed; "
        "plans scoped to the envelope (observer: no install/block; satellite: "
        "block + auto pack opt-out, never install; partial: --packs subset, "
        "install precedes block); unconfirmed --apply does only the "
        "observer-safe subset and says so; envelope survives rescans; the "
        "next-hint never suggests beyond the envelope; creation mode: "
        "flag-driven greenfield run scaffolds+installs+blocks+receipts, "
        "--secure runs install --profile secure BEFORE the block (posture-"
        "first, 103 §2), takeover records takeover_notes and never scaffolds, "
        "observer writes memory+receipt only, interactive interview asks "
        "involvement as question ZERO and posture FIRST for takeover, "
        "declining writes nothing)"
    )
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────


def _caller_dir(arg_dir: str | None) -> Path:
    """--dir > $WF_CALLER_CWD (exported by the `wf` dispatcher, which forces
    its own cwd to the toolset repo) > cwd."""
    if arg_dir:
        return Path(arg_dir).expanduser().resolve()
    env = os.environ.get("WF_CALLER_CWD")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="wf start",
        description="Project boot scanner + creation mode (S0-S6 + metrics; M1+M2+M3).",
    )
    ap.add_argument("--dir", dest="dir", help="project directory to scan "
                    "(default: the directory you invoked `wf` from)")
    ap.add_argument("--json", action="store_true", help="machine view (boot.json shape)")
    ap.add_argument("--write", action="store_true",
                    help="record the receipt at <dir>/_workflow/boot.json "
                    "(the scan's ONLY write; prior opt-outs preserved)")
    ap.add_argument("--new", action="store_true",
                    help="force greenfield classification (-> creation mode) in a non-empty dir")
    ap.add_argument("--check", action="store_true",
                    help="validate the activation catalog fail-closed (doctor check 42)")
    ap.add_argument("--involvement", choices=INVOLVEMENTS,
                    help="confirm the involvement envelope (D5, question ZERO): "
                    "observer=memory/learn/receipt only · satellite=+block, NO "
                    "install · partial=+chosen --packs · full=everything; "
                    "unconfirmed, --apply materializes only the observer-safe subset")
    ap.add_argument("--packs", help="comma-separated pack subset for the PARTIAL "
                    "envelope (implies --involvement partial)")
    ap.add_argument("--secure", action="store_true",
                    help="secure posture — install runs --profile secure BEFORE "
                    "the block render (posture-first, 103 §2)")
    ap.add_argument("--team", action="store_true",
                    help="team posture (composes with --secure -> secure-team)")
    ap.add_argument("--intent", help="what you want to make — feeds the profile "
                    "matcher and D3 add-on proposals")
    ap.add_argument("--profile", help="confirm the activation profile (required "
                    "before --apply will write the CLAUDE.md block)")
    ap.add_argument("--addons", help="comma-separated add-on ids to select (D3)")
    ap.add_argument("--size", choices=SIZES, help="confirm the size classification "
                    "(persisted in boot.json)")
    ap.add_argument("--apply", action="store_true",
                    help="materialize the plan's auto-do steps (+ any --accept "
                    "offers) inside the CONFIRMED envelope; stop-and-ask items "
                    "are never run")
    ap.add_argument("--accept", help="comma-separated offer ids (O1) or subsystem "
                    "names to run/reverse-opt-out")
    ap.add_argument("--decline", help="comma-separated subsystems to record as "
                    "opted_out (the only opt-out write path)")
    ap.add_argument("--force-block", action="store_true",
                    help="write the activation block even when CLAUDE.md has "
                    "uncommitted changes")
    # creation-mode (M3) interview flags — each answers its question.
    ap.add_argument("--variant", choices=VARIANTS,
                    help="creation mode Q1: greenfield / takeover / satellite adoption")
    ap.add_argument("--seams", help="takeover: contract seams / canonical "
                    "ownership (recorded in boot.json takeover_notes)")
    ap.add_argument("--deploy-targets", dest="deploy_targets",
                    help="takeover: deploy targets (recorded in takeover_notes)")
    ap.add_argument("--port-contracts", dest="port_contracts",
                    help="takeover: port contracts (recorded in takeover_notes)")
    ap.add_argument("--targets", help="creation mode Q5: agent targets for the "
                    "install (default claude)")
    ap.add_argument("--stack", choices=CREATION_STACKS,
                    help="creation mode Q5: scaffold stack preset ('undecided' is valid)")
    ap.add_argument("--yes", action="store_true",
                    help="creation mode: accept the interview defaults and "
                    "execute the plan non-interactively")
    ap.add_argument("--eval-corpus", nargs="?", const="-", metavar="PATH",
                    help="emit the invocation-rate eval corpus (JSONL) to "
                    "PATH or stdout; graded runs need bmad-eval-runner")
    ap.add_argument("--selftest", action="store_true", help="run built-in self-test")
    return ap


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    if args.selftest:
        return selftest()

    if args.check:
        problems = check_catalog()
        if problems:
            print("wf start --check: FAIL")
            for p in problems:
                print("  - " + p)
            return 1
        profiles, addons = load_catalog()
        print(f"wf start --check: OK ({len(profiles)} activation profiles + "
              f"{len(addons)} add-ons; every skill/pack/tool/gate verified)")
        return 0

    root = _caller_dir(args.dir)
    if not root.is_dir():
        _die(f"not a directory: {root}")

    if args.eval_corpus is not None:
        rows = emit_eval_corpus(root)
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        if args.eval_corpus == "-":
            print(text)
        else:
            out = Path(args.eval_corpus)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + ("\n" if text else ""), encoding="utf-8")
            with_q = sum(1 for r in rows if r["query"])
            print(f"wf start: wrote {with_q} corpus rows "
                  f"({len(rows) - with_q} skills without triggers.json) to {out}")
        return 0

    accept = [a for a in (args.accept or "").split(",") if a.strip()]
    decline = [d for d in (args.decline or "").split(",") if d.strip()]
    addons_arg = [a for a in (args.addons or "").split(",") if a.strip()]
    packs_arg = [p for p in (args.packs or "").split(",") if p.strip()]

    boot = scan(root, force_new=args.new)
    apply_log: list[str] = []
    if boot["mode"] != "greenfield":
        # decisions FIRST so the plan reflects a same-run --decline
        # (GPT-game trace: a declined pack set must never be re-planned)
        record_decisions(boot, decline=decline, accept=accept)
        enrich(boot, root, intent=args.intent, profile_arg=args.profile,
               addons_arg=addons_arg, size_arg=args.size,
               involvement_arg=args.involvement, packs_arg=packs_arg,
               posture_arg=_posture_from_flags(args.secure, args.team))
        if args.apply:
            apply_log = apply_plan(root, boot, accept=accept,
                                   force_block=args.force_block)
            write_boot(root, boot)
        elif args.write or decline:
            write_boot(root, boot)
    elif not args.json:
        # M3: greenfield -> creation mode (interview + envelope-scoped plan;
        # executes only on interactive consent, --yes, or --apply with an
        # explicit --involvement ruling).
        return run_creation(root, args)

    if args.json:
        print(json.dumps(_strip_transient(boot), indent=2, ensure_ascii=False))
        for line in apply_log:
            print(f"# applied: {line}", file=sys.stderr)
    else:
        report = render_report(boot, root)
        if apply_log:
            report = report.rsplit("\n  this scan wrote nothing", 1)[0]
            report += "\n  applied:\n" + "\n".join(f"    {l}" for l in apply_log)
            report += f"\n  receipt written: {BOOT_REL}"
        elif (args.write or decline) and boot["mode"] != "greenfield":
            report = report.rsplit("\n", 1)[0] + f"\n  receipt written: {BOOT_REL}"
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
