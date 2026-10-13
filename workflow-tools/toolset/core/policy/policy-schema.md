# `policy:` overlay schema (`core/policy/overlays/*.yaml`) — owned skill-policy layer

The per-skill-category **policy overlay** store consumed by `wf policy`
(`scripts/wf-policy.py`). A **policy overlay** attaches declarative
**obligations** to a *category* of skills (e.g. `ux`/`ui`/`design`) **without
editing the vendored skills**. The vendored skills under `.claude/skills/` are a
pinned, MIT fork: we do **not** modify them. Instead, this owned `core/` layer
imposes requirements on top, and the agent consults them at skill-invocation time
via `wf policy show <skill>`.

This mirrors the repo's other YAML-contract docs (`core/context/context-schema.md`,
`core/validation/validation-schema.md`, `core/memory/memory-contract.yaml`): one
fail-closed registry, validated by a `check` subcommand and a `--selftest`, wired
into `wf-doctor`.

## Where overlays live, and why they never touch the skills

- Overlays live at `core/policy/overlays/<id>.yaml` — our owned layer.
- They are **surfaced**, never **injected**: `wf policy show` resolves and prints
  the obligations; the always-on pointer in `CLAUDE.md` tells the agent to run it
  before invoking a governed skill. Nothing in `_bmad/` or `.claude/skills/` is
  edited.
- `enforcement: instructions` is the only enforcement mode today — overlays
  *inform* the agent; they do not (and must not) rewrite skill files.

## Shape (one overlay file = one overlay)

```yaml
id: ux-ui-design                 # REQUIRED slug, must equal the filename stem
title: <str>                     # REQUIRED human label
applies_to:                      # REQUIRED — at least one of skill_globs / categories
  skill_globs: ["bmad-*-ux*"]    # fnmatch globs over skill names under .claude/skills/
  categories: ["ux", "ui"]       # free-form category tags the caller can target
requirements:                    # REQUIRED non-empty list of obligation strings
  - "Generate the design with Claude headless (not prose)"
  - "Produce >= 2 independent design reviews before finalizing"
external_help:                   # OPTIONAL list — REQUIRED-complete when present
  - name: <str>                  # what the external help IS
    why: <str>                   # why the obligation leans on it
    availability: <str>          # that it is PAID/gated + its availability
    how_to_connect: <str>        # INSTRUCTIONS ONLY to connect (key/sub/MCP) — never auto-connect
    fallback: <str>              # graceful fallback that marks the req DEGRADED (never silently skipped)
enforcement: instructions        # OPTIONAL; only "instructions" is valid today (default)
```

## Field rules (what `check` enforces — fail-closed)

`wf policy check` validates **every** overlay and exits non-zero on the first
violation. It never silently skips a malformed overlay.

| Field | Rule |
|---|---|
| `id` | REQUIRED non-empty slug; **must equal the filename stem** (so `show` and listings are unambiguous). |
| `title` | REQUIRED non-empty string. |
| `applies_to` | REQUIRED mapping; must define a non-empty `skill_globs` **or** `categories` (or both). |
| `applies_to.skill_globs` | list of strings; **each glob must match ≥1 real skill** under `.claude/skills/`. A glob matching **zero** skills is a dead overlay → **fail closed** (the same "stale glob" rule as `wf context`). |
| `applies_to.categories` | list of non-empty strings. |
| `requirements` | REQUIRED non-empty list of non-empty strings. |
| `external_help` | OPTIONAL list. **When present, every entry is REQUIRED-complete** (see below). |
| `enforcement` | OPTIONAL; if set must be `instructions`. |

### `external_help` — the outside-help contract (the load-bearing part)

Outside help is **first-class**: any obligation that relies on a paid/external
capability (the worked example: "use Claude to generate the design" — only
available to Claude customers) MUST declare, in validated schema fields:

| Field | Required? | Meaning |
|---|---|---|
| `name` | **yes** | What the external help IS (e.g. "Claude design generation"). |
| `why` | recommended | Why the obligation leans on it. |
| `availability` | **yes** | That it is **paid/gated** + its availability ("Paid — requires Claude access …"). |
| `how_to_connect` | **yes** | Concrete **instructions only** to connect: API key / subscription / MCP server. This is a **recommendation**, never an auto-connect (CLAUDE.md working rule 2: *recommend MCPs, don't connect silently*). |
| `fallback` | **yes** | A **graceful fallback** that marks the requirement **DEGRADED** (honestly surfaced), **never silently skipped**. |

`check` **fails closed** if any `external_help` entry is missing `name`,
`availability`, `how_to_connect`, or `fallback`, or if any is empty/whitespace.
The rule: *an obligation may lean on paid/external help only if it tells you
exactly how to connect it AND how to degrade honestly without it.*

## Commands

| Invocation | Behavior |
|---|---|
| `wf policy list` | list overlays: id, title, what they apply to. |
| `wf policy show <skill-or-category>` | resolve the overlays that apply to that skill/category; print full obligations PLUS, prominently, any `external_help` (availability + how-to-connect + DEGRADED fallback). A skill with no overlay prints "no policy applies". |
| `wf policy check` | validate every overlay; **fail-closed** (non-zero) on a malformed overlay, a glob matching no real skill, or incomplete `external_help`. |
| `wf policy --selftest` | planted-fixture tests with teeth (wf-doctor check 30). |

`--overlays DIR` overrides the overlay directory (used by `--selftest` so it never
depends on the real overlays); `--skills DIR` overrides the skill catalog root.
The tool only **reads**: it never writes, never runs anything, and — by design —
**never connects** any external help. It only surfaces the connect instructions.

## How `show` resolves a skill → overlays

1. The argument is treated as **both** a skill name and a category.
2. An overlay **applies** if (a) any `skill_globs` entry `fnmatch`es the argument
   when read as a skill name, **or** (b) any `categories` entry equals the
   argument when read as a category.
3. All applying overlays are printed (obligations + external help). If none apply,
   `show` prints "no policy applies" and exits 0 — a benign skill is not a failure.

## How the agent consults this (the pointer)

Before invoking a skill in a **governed category** (ux/ui/design/…), the agent runs
`wf policy show <skill>` and **honors the obligations** it prints — including
connecting any required outside help (using the instructions there, never silently)
**or** honestly marking that requirement **DEGRADED**. This is wired as a short
always-on pointer in `CLAUDE.md` near the design/UI working rule, so it stays a
pointer to the query and does not bloat every-skill context with the full policy.

## Guardrail — overlays are OBLIGATIONS, not authorization

An overlay says *what you must do* before/while using a governed skill. It is
**never** an authorization scope, a trust signal, or a license to auto-connect an
external service. Connecting outside help is always a permissioned, instructed
action the human approves; the tool only points at the instructions.
