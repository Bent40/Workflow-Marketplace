# workflow-core

The workflow operating model (ambient router, honesty gates, right-sizing) + a thin set of universal helpers. Install this first; add domain modules à la carte.

This is a GENERATED Claude Code plugin artifact — do not hand-edit; it is
rebuilt by `wf plugin build` from the private workflow source.

## What it is

- A `SessionStart` hook that makes the workflow **operating model** ambient
  (the plugin embeds the civilian operating-model spine and injects it as
  `additionalContext` at session start — no external dependency). Ships both
  a bash hook (macOS/Linux) and a PowerShell hook (Windows), so the operating
  model loads on every platform, not just Unix.
- 8 skill(s) under `skills/`.

## Install

1. Add the marketplace:
   ```
   /plugin marketplace add <github-owner>/<repo>
   ```
2. Install this plugin:
   ```
   /plugin install workflow-core
   ```
3. Start (or restart) your session — the SessionStart hook injects the
   operating model and offers to run the workflow session-start checks.

## Skills

- `workflow-operating-model`
- `bmad-help`
- `bmad-advanced-elicitation`
- `bmad-brainstorming`
- `bmad-spec`
- `bmad-shard-doc`
- `bmad-index-docs`
- `bmad-party-mode`
