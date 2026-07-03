# workflow-method

BMad Method — the agile SDLC: analyst/PM/architect/dev/UX agents, PRD, epics, stories, sprints, and the dev/review loop. Needs workflow-core.

This is a GENERATED Claude Code plugin artifact — do not hand-edit; it is
rebuilt by `wf plugin build` from the private workflow source.

## What it is

- 30 domain skill(s) under `skills/` — a pure à-la-carte pack.
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
   /plugin install workflow-method
   ```

## Skills

- `bmad-agent-analyst`
- `bmad-agent-tech-writer`
- `bmad-document-project`
- `bmad-prfaq`
- `bmad-product-brief`
- `bmad-domain-research`
- `bmad-market-research`
- `bmad-technical-research`
- `bmad-agent-pm`
- `bmad-agent-ux-designer`
- `bmad-prd`
- `bmad-ux`
- `bmad-agent-architect`
- `bmad-check-implementation-readiness`
- `bmad-create-architecture`
- `bmad-create-epics-and-stories`
- `bmad-generate-project-context`
- `bmad-agent-dev`
- `bmad-checkpoint-preview`
- `bmad-code-review`
- `bmad-correct-course`
- `bmad-create-story`
- `bmad-dev-story`
- `bmad-investigate`
- `bmad-qa-generate-e2e-tests`
- `bmad-quick-dev`
- `bmad-retrospective`
- `bmad-sprint-planning`
- `bmad-sprint-status`
- `bmad-competitive-features`
