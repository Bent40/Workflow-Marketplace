# Local-model microtask contract (definition)

**Status:** this file defines the *shape* of a local-model work packet. The
packet contract is consumed by the generated `adapters/<profile>/local/TASK.md`
surface and by `scripts/split-task.py` (the deterministic packet scaffolder);
`scripts/compress-context.py` provides the compact repo context that accompanies
a packet for local workers.

## Why local models get a different task shape

Local / small-context models typically have less context, weaker tool use,
weaker long-horizon planning, and less reliable instruction-following than
frontier models. They should **not** receive broad, story-level tasks. They
receive narrow, self-contained work packets. The **orchestrator** (a stronger
model) remains responsible for decomposition, integration, final verification,
and acceptance.

## The microtask contract

Every local-model microtask MUST specify:

| Field | Meaning |
|---|---|
| `objective` | One concrete outcome. Exactly one. |
| `allowed_files` | The explicit, minimal set of files the model may read/edit. |
| `forbidden_files` | Files it must not touch (e.g. shared routers, migrations, config). |
| `context_budget` | Token/context ceiling for the packet (so it fits the model). |
| `max_edit_size` | Cap on the diff (e.g. "≤ 40 changed lines / one function"). |
| `expected_output_format` | Usually a patch/diff, not prose commentary. |
| `validation` | The exact command to run, or the manual check to perform. |
| `stop_condition` | When to stop (after the one objective — do not continue). |
| `handoff_summary_format` | The terse summary the orchestrator will consume. |

## Core rules for local microtasks

- One objective per task.
- Small file set; explicit allowed and forbidden files.
- No architecture changes unless asked.
- No broad refactors unless asked.
- Prefer patch/diff output over broad commentary.
- Stop after each microtask; do not chain.
- Explicit acceptance criteria per microtask.
- Include verification instructions per microtask.
- The orchestrator model composes results and owns final verification.

## Decomposition example

A frontier model would accept:

```
Implement story 3.2.
```

A local model receives that story split into work packets:

```
Task 3.2-A: Inspect ONLY these files and report current behavior.
Task 3.2-B: Modify ONLY file X to add function Y.
Task 3.2-C: Add tests ONLY for behavior Z.
Task 3.2-D: Run or describe validation.
Task 3.2-E: Review the diff against the acceptance criteria.
```

Each packet is one microtask carrying the full contract above. The orchestrator
sequences them, integrates the diffs, and performs the final acceptance check —
the local model never sees the whole story at once.

## Built

- `scripts/split-task.py` — turns a story's `## Microtasks` list (the
  orchestrator's decomposition) into ordered, contract-conformant packet files
  plus an orchestration index. Deterministic scaffolder, not an LLM splitter; the
  decomposition is the orchestrator's, the packet generation is the tool's.
  Run: `scripts/split-task.py <story.md> [--out <dir>] [--profile <name>]`, or
  `--selftest`. See `example-story.md` for the input format.
- The rendered local surfaces `adapters/<profile>/local/{SYSTEM,TASK,REVIEW}.md`
  are generated from `core/` by `scripts/generate-adapters.py` (Phase 4A.5).
- `scripts/compress-context.py` — produces a compact context map (file inventory
  + top-level Python/Markdown symbols) so a small-context worker gets useful
  context without a repo dump. Run: `scripts/compress-context.py [root]
  [--out <file>]`, or `--selftest`. Deterministic; lists what exists rather than
  ranking importance.

## Not yet built (future phases)

- Multi-language symbol extraction in `compress-context.py` (beyond
  Python/Markdown), and Aider-style importance ranking.
