# workflow-test-architect

BMad Test Architect — quality strategy, ATDD, CI gates, traceability, NFR audits, and test automation. Needs workflow-core.

This is a GENERATED Claude Code plugin artifact — do not hand-edit; it is
rebuilt by `wf plugin build` from the private workflow source.

## What it is

- 10 domain skill(s) under `skills/` — a pure à-la-carte pack.
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
   /plugin install workflow-test-architect
   ```

## Skills

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
