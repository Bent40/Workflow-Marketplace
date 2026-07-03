# workflow-game-design

BMad Game Dev Studio — GDD, game architecture, narrative, playtest planning, and the game dev loop for Unity/Unreal/Godot/Phaser. Needs workflow-core.

This is a GENERATED Claude Code plugin artifact — do not hand-edit; it is
rebuilt by `wf plugin build` from the private workflow source.

## What it is

- 33 domain skill(s) under `skills/` — a pure à-la-carte pack.
- **No hook.** The operating model lives in `workflow-core`. Install that
  first for the discipline layer; on Claude Code **web** (where plugin hooks
  do not run) invoke the `workflow-operating-model` skill to load it.

## Install

1. Add the marketplace:
   ```
   /plugin marketplace add <github-owner>/<repo>
   ```
2. Install the foundation first, then this module:
   ```
   /plugin install workflow-core
   /plugin install workflow-game-design
   ```

## Skills

- `gds-agent-game-architect`
- `gds-agent-game-designer`
- `gds-agent-game-dev`
- `gds-agent-game-solo-dev`
- `gds-agent-tech-writer`
- `gds-brainstorm-game`
- `gds-create-game-brief`
- `gds-domain-research`
- `gds-create-narrative`
- `gds-gdd`
- `gds-prd`
- `gds-ux`
- `gds-check-implementation-readiness`
- `gds-create-epics-and-stories`
- `gds-game-architecture`
- `gds-generate-project-context`
- `gds-code-review`
- `gds-correct-course`
- `gds-create-story`
- `gds-dev-story`
- `gds-investigate`
- `gds-retrospective`
- `gds-sprint-planning`
- `gds-sprint-status`
- `gds-e2e-scaffold`
- `gds-performance-test`
- `gds-playtest-plan`
- `gds-test-automate`
- `gds-test-design`
- `gds-test-framework`
- `gds-test-review`
- `gds-document-project`
- `gds-quick-dev`
