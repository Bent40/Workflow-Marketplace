# workflow-tools

The workflow `wf` command-line tools on your PATH: project boot scan (wf start), structural map, function catalog, spec pack, story audit, learnings store, guardrails, real-browser E2E, mutation gate and more. Needs Python 3 + PyYAML.

This is a GENERATED Claude Code plugin artifact — do not hand-edit; it is
regenerated from source and republished as a whole.

## What it is

- 1 domain skill(s) under `skills/` — a pure à-la-carte pack.
- **No hook.** The operating model lives in `workflow-core`. Install that
  first for the discipline layer; on Claude Code **web** (where plugin hooks
  do not run) invoke the `workflow-operating-model` skill to load it.

## Install

1. Add the marketplace:
   ```
   /plugin marketplace add Bent40/Workflow-Marketplace
   ```
2. Install the foundation first, then this module:
   ```
   /plugin install workflow-core
   /plugin install workflow-tools
   ```

## Skills

- `workflow-cli`
