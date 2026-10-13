---
name: workflow-cli
description: 'Use the workflow `wf` command-line tools on the current project: boot scan and adoption plan (wf start), structural map instead of grepping (wf map), function catalog and probes (wf describe), spec pack, story-completion audit, learnings store, memory pack, guardrails, file leases, real-browser E2E (wf browse), mutation gate, usage readout. Use when the user says "wf <command>", asks to map/scan/audit the project with workflow, or a task matches one of the tools below. Distinct from workflow-find (finds skills) and bmad-help (BMAD phase routing).'
---

# workflow-cli — the `wf` tools

`wf` is the workflow toolset's single command. With the **workflow-tools**
plugin installed it is on PATH and runs in the project you are in. Inside the
workflow repo itself, run it as `./wf` or `python3 scripts/wf`.

Before relying on it, run `wf help`: it lists exactly the commands this
install ships. If `wf` is not found, the workflow-tools plugin is not
installed; say so in one line (`/plugin install workflow-tools@workflow`) and
carry on without it. The tools need Python 3 and PyYAML (`pip install pyyaml`).

## Which tool for which job

| Need | Command |
|---|---|
| Scan a project and propose how much of the workflow to adopt | `wf start --dir <abs path>` (read-only; `--apply` only after the user approves) |
| Find where something lives without reading the tree | `wf map build`, then `wf map query <term>` |
| Catalog Python/JS functions, flag risky I/O, run a real probe | `wf describe --dir <abs path>` |
| Compact repo map for a small-context prompt | `wf compress-context <root>` |
| Spec pack for a feature: constitution gate, marker scan, coverage sweep | `wf spec init|check|analyze <feature>` |
| Check a story's acceptance criteria against the actual diff | `wf audit <story.md> --base <ref>` |
| Durable project learnings (add, search, supersede, retract) | `wf learn add|search|list` |
| Project memory pack (state, decisions, risks, next actions) | `wf memory init|check|refresh` |
| Run the project's declared validation commands | `wf validate` |
| Context-tag bundles of paths for a task | `wf context list|show|pack` |
| Split a story into small local-model task packets | `wf split-task <story.md>` |
| Leases so parallel agents don't edit the same module | `wf lock claim|release|check|list` |
| Command-safety guardrails (speed bump, path freeze, budget) | `wf guard status|careful|freeze` |
| Real-browser screenshot, snapshot or E2E flow with console/a11y checks | `wf browse setup` once, then `wf browse run <steps>` |
| Prove tests have teeth by mutating code | `wf mutate <file.py> --test "<cmd>"` |
| Local token/usage readout | `wf cost` |
| Recurring friction candidates from session history | `wf reflect signals|digest` |
| Ground-truth process trail of a run | `wf trace start|stage|end` |

Each command takes `--help`. Use absolute paths for `--dir`, `--file` and
`--out`.

## Rules

- Read-only scans (`start`, `map query`, `describe`, `compress-context`,
  `audit`, `cost`) are safe to run without asking.
- Anything that writes project files (`start --apply`, `memory init`,
  `spec init`, `learn add`) follows the user's approval, as for any edit.
- Report what a tool actually printed; never claim a check passed when you
  did not run it.
