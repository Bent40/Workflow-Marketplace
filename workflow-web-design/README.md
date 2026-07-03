# workflow-web-design

Whiteport Design Studio — the strategic, design-first UX methodology (project brief → trigger mapping → scenarios → UX → design system → evolution). Needs workflow-core.

This is a GENERATED Claude Code plugin artifact — do not hand-edit; it is
rebuilt by `wf plugin build` from the private workflow source.

## What it is

- 15 domain skill(s) under `skills/` — a pure à-la-carte pack.
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
   /plugin install workflow-web-design
   ```

## Skills

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
