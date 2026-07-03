# workflow-full

Every stock BMAD skill (all upstream modules) — the one-shot everything bundle, on top of workflow-core.

This is a GENERATED Claude Code plugin artifact — do not hand-edit; it is
rebuilt by `wf plugin build` from the private workflow source.

## What it is

- A `SessionStart` hook that makes the workflow **operating model** ambient
  (the plugin embeds the civilian operating-model spine and injects it as
  `additionalContext` at session start — no external dependency). Ships both
  a bash hook (macOS/Linux) and a PowerShell hook (Windows), so the operating
  model loads on every platform, not just Unix.
- 121 skill(s) under `skills/`.

## Install

1. Add the marketplace:
   ```
   /plugin marketplace add <github-owner>/<repo>
   ```
2. Install this plugin:
   ```
   /plugin install workflow-full
   ```
3. Start (or restart) your session — the SessionStart hook injects the
   operating model and offers to run the workflow session-start checks.

## Skills

- `bmad-advanced-elicitation`
- `bmad-brainstorming`
- `bmad-customize`
- `bmad-editorial-review-prose`
- `bmad-editorial-review-structure`
- `bmad-help`
- `bmad-index-docs`
- `bmad-party-mode`
- `bmad-review-adversarial-general`
- `bmad-review-edge-case-hunter`
- `bmad-shard-doc`
- `bmad-spec`
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
- `bmad-create-prd`
- `bmad-edit-prd`
- `bmad-prd`
- `bmad-ux`
- `bmad-validate-prd`
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
- `bmad-tea`
- `bmad-teach-me-testing`
- `bmad-testarch-atdd`
- `bmad-testarch-automate`
- `bmad-testarch-ci`
- `bmad-testarch-framework`
- `bmad-testarch-nfr`
- `bmad-testarch-test-design`
- `bmad-testarch-test-review`
- `bmad-testarch-trace`
- `bmad-agent-builder`
- `bmad-bmb-setup`
- `bmad-eval-runner`
- `bmad-module-builder`
- `bmad-workflow-builder`
- `bmad-cis-agent-brainstorming-coach`
- `bmad-cis-agent-creative-problem-solver`
- `bmad-cis-agent-design-thinking-coach`
- `bmad-cis-agent-innovation-strategist`
- `bmad-cis-agent-presentation-master`
- `bmad-cis-agent-storyteller`
- `bmad-cis-design-thinking`
- `bmad-cis-innovation-strategy`
- `bmad-cis-problem-solving`
- `bmad-cis-storytelling`
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
- `wds-agent-freya-ux`
- `wds-agent-mimir-builder`
- `wds-agent-saga-analyst`
- `memory`
- `sync`
- `wds-0-alignment-signoff`
- `wds-0-project-setup`
- `wds-1-project-brief`
- `wds-2-trigger-mapping`
- `wds-3-scenarios`
- `wds-4-ux-design`
- `wds-5-agentic-development`
- `wds-6-asset-generation`
- `wds-7-design-system`
- `wds-8-product-evolution`
- `workflow-operating-model`
- `bmad-competitive-features`
- `bmad-decision-propagation`
- `bmad-security-decision-framing`
