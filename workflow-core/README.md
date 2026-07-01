# workflow-core

The workflow operating model (ambient router, honesty gates, right-sizing) + a curated core skill set.

This is a GENERATED Claude Code plugin artifact — do not hand-edit; it is
rebuilt by `wf plugin build` from the private workflow source.

## What it is

- A `SessionStart` hook that makes the workflow **operating model** ambient
  (the plugin embeds the civilian operating-model spine and injects it as
  `additionalContext` at session start — no external dependency). Ships both
  a bash hook (macOS/Linux) and a PowerShell hook (Windows), so the operating
  model loads on every platform, not just Unix.
- 18 skill(s) under `skills/`.

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

- `bmad-help`
- `bmad-product-brief`
- `bmad-prd`
- `bmad-create-architecture`
- `bmad-create-epics-and-stories`
- `bmad-create-story`
- `bmad-dev-story`
- `bmad-code-review`
- `bmad-quick-dev`
- `bmad-investigate`
- `bmad-correct-course`
- `bmad-retrospective`
- `bmad-document-project`
- `bmad-brainstorming`
- `bmad-tea`
- `bmad-testarch-test-design`
- `bmad-agent-architect`
- `bmad-agent-dev`
