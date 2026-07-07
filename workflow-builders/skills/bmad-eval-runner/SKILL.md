---
name: bmad-eval-runner
description: Run a skill's evals in a clean, isolated environment and report results. Use when the user wants to evaluate a skill, run evals, benchmark a skill, validate triggers, or grade skill outputs.
---

# Skill Eval Runner

## Overview

Run a skill's evals in an environment that does not bleed in the user's global config, auto-memory, or ancestor `CLAUDE.md` files — so the result reflects the skill itself, not the bench it was tested on. Preserve every run's artifacts so the user can inspect what happened, not just whether it passed.

The **preferred (hermetic)** path runs each eval in a fresh Docker container or a HOME-isolated local workspace via `claude -p`, which needs Docker or an `ANTHROPIC_API_KEY`. When **neither** is available — typical in web/remote containers — this runner does **not** give up: it falls back to an in-session **degraded mode** (see `## Degraded mode` below) so a skill can still be validated. This makes the runner self-sufficient everywhere; there is no longer a separate skill for the no-sandbox case.

Two eval shapes are supported and run independently:

- **Artifact evals** (`evals.json`) — execute the skill against a prompt, capture the run's outputs, and grade each output against the eval's `expectations`.
- **Trigger evals** (`triggers.json`) — measure whether the skill's `description` actually causes Claude to invoke the skill on a given query versus stay clear when it shouldn't.
- **Counterfactual evals** (`counterfactual.json`, `--mode counterfactual`) — run each prompt WITH vs WITHOUT the skill and grade the *delta*: does the skill measurably change the output, or only inflate context? Opt-in, priority-scoped. See **Counterfactual mode**.

You are an experienced eval engineer. The user wants signal, not theatre. Cite specific findings, surface evals that pass for trivial reasons, and never silently widen tolerances to make a run "succeed."

## Args

- Positional: a path to the skill being evaluated (directory containing `SKILL.md`).
- `--evals <path>` — explicit path to evals folder or a specific `evals.json` / `triggers.json` file. If omitted, discover.
- `--mode artifact|trigger|counterfactual|both` — which eval kind to run. Default: `both` if both files are found, else whichever exists. `counterfactual` is **opt-in** (never part of `both`, since it doubles model spend); see **Counterfactual mode**.
- `--isolation docker|local|auto` — sandbox strategy. Default: `auto` (Docker when available, otherwise local).
- `--project-root <path>` — root of the project the skill belongs to. Default: walk up from skill path looking for `_bmad/` or `.git/`.
- `--output-dir <path>` — where run folders are written. Default: `{bmad_builder_reports}/eval-runs/` if configured, else `~/bmad-evals/`.
- `--workers <n>` — parallel evals. Default: 4.
- `--headless` / `-H` — non-interactive; emit final JSON only.

## On Activation

1. Resolve config the same way `bmad-workflow-builder` does (`{project-root}/_bmad/config.yaml` then `config.user.yaml`, falling back to `bmb/config.yaml`). Resolve `{user_name}`, `{communication_language}`, `{bmad_builder_reports}`. Apply throughout the session.

2. If `--headless` was passed, set `{headless_mode}=true` and skip every confirmation below; pick the safest defaults and proceed.

3. Locate the skill. Verify `<skill-path>/SKILL.md` exists; halt with a clear error if it doesn't.

4. Discover evals — see `## Eval Discovery` below.

5. Choose isolation — see `## Isolation` below. On the first Docker run on this machine, the image will need to be built; surface that, ask once unless headless, then cache.

6. Confirm the run summary with the user (skill, evals found, mode, isolation, output dir) unless headless. Then execute.

## Eval Discovery

Look in this order, taking the first match:

1. `--evals` argument if provided. May point to a folder (containing `evals.json` and/or `triggers.json`) or a specific JSON file.
2. `<skill-path>/evals/` — colocated with the skill.
3. `<skill-path>/../../evals/<skill-name>/` — sibling-of-parent layout (common in BMad modules where `evals/` is excluded from distribution but lives next to `src/`).
4. `<project-root>/evals/<skill-name>/` — top-level evals tree.
5. `<project-root>/evals/**/<skill-name>/` — anywhere under project evals.

Surface what you found and where. If no evals are discovered, halt with a clear message — do not attempt to fabricate evals.

## Isolation

Run each eval in a fresh workspace so memory, project CLAUDE.md, prior runs, and host shell config cannot bias the result. Two hermetic strategies, picked automatically by default (and, when neither can authenticate, the in-session `## Degraded mode` fallback below):

- **Docker** (preferred when available): each eval runs in a fresh container off `bmad-eval-runner:latest`. The host's `ANTHROPIC_API_KEY` is the only env passed in. The skill's project is bind-mounted read-only and copied into a writable scratch dir inside the container; `HOME` is a fresh in-container directory; there is no auto-memory and no host CLAUDE.md.

- **Local fallback** (when Docker is unavailable or the user opts out): each eval runs in a fresh `~/bmad-evals/<run-id>/<eval-id>/workspace/` directory with `HOME=<workspace>/.home` overridden so global memory and global CLAUDE.md do not leak. The project is copied (or hardlinked where supported) into the workspace. Tell the user this is the active mode and acknowledge that local isolation is best-effort, not hermetic.

The first time Docker is selected on this machine, build the image — `python3 {skill-root}/scripts/docker_setup.py --build` — and tell the user this is happening once.

Details and the exact mount layout live in `references/isolation.md`. Read that file when you need to debug an isolation issue or explain to the user what is being isolated.

## Degraded mode — no Docker and no API key (in-session fallback)

When **neither** Docker nor `ANTHROPIC_API_KEY` is available, the hermetic path above cannot authenticate the `claude -p` subprocess. **Do not fail silently** — that would collide with the honesty rule that a skill is not done until it is validated. Instead, fall back to **in-session execution** using fresh **subagents** as the isolation boundary and the **ambient model** as executor and grader. This runs the *same* evals (the identical `evals.json` / `triggers.json`, discovered the same way) and reuses this runner's own grader rubric (`agents/grader.md`) verbatim, so a PASS means the same thing — modulo the honesty caveats below. This fallback is what makes the runner self-sufficient in web/remote containers where the sandbox cannot run. (This folds in the former `bmad-eval-inline` skill, now deprecated.)

The discovery/aggregation helper is shared: `python3 {bmad-eval-inline-skill}/scripts/inline_eval.py` (the script currently lives under the deprecated `bmad-eval-inline/scripts/` dir). Use its `discover` and `report` subcommands; it never calls a model and has no third-party deps.

**Procedure:**

1. **Sandbox check first (prefer the hermetic path).** If `docker info` works **or** `ANTHROPIC_API_KEY` is set, run the hermetic path above — degraded mode is the fallback, not the default. Only enter degraded mode when both are absent (or the user explicitly requests an in-session run).
2. **Discover & validate evals.** `python3 {…}/scripts/inline_eval.py discover <skill-path> [--evals P]` locates the eval files, validates the JSON, and prints a plan. Halt on no-evals (exit 2) or malformed JSON (exit 3) with the script's diagnostics — never fabricate evals.
3. **Create the run folder.** `<run-dir>/<run-id>/` with an `eval-<id>/` subfolder per artifact eval and a `triggers/` subfolder; record the skill path, eval source, and sandbox-check result in `run.json`. Default run dir `~/bmad-evals/inline/<run-id>/`. Artifacts are forever.
4. **Artifact evals — one EXECUTOR subagent each (parallel).** For each eval in `evals.json`, spawn a fresh executor subagent (Agent tool) with the eval `prompt` verbatim, its `files` fixtures (read-only), the target skill path, and an `artifacts/` output dir. Instruct it to actually run the target skill, write every output under `artifacts/`, and append a `toolcalls.md` log (ordered tools/skills invoked + files written) — the in-session stand-in for the stream-JSON transcript the grader expects.
5. **Grade each eval — one fresh GRADER subagent each (parallel).** Each grader's prompt is this runner's `agents/grader.md` plus the eval's `expectations`, the `artifacts/` dir, and the `toolcalls.md` path (used wherever the rubric says "scan the transcript"). It writes `grading.json` in the rubric's schema. **No silent fallback:** a grader error → mark that eval `grading_error`, never a default verdict. Relay weak-assertion feedback.
6. **Trigger evals — APPROXIMATE routing proxy (parallel).** In-session there is no description-based dispatcher to measure, so spawn `runs-per-query` (default 3) **router subagents** per query, each given the candidate `description` plus realistic sibling descriptions, and asked which one skill would fire. `trigger_rate` = fraction naming the candidate; pass when `should_trigger=true` and rate ≥ 0.5, or `should_trigger=false` and rate < 0.5. Write `triggers/triggers-result.json` and mark the whole section **APPROXIMATE**.
7. **Aggregate.** `python3 {…}/scripts/inline_eval.py report <run-dir>/<run-id>` reads every `grading.json` + `triggers-result.json` and writes `report.md` (per-expectation pass/fail with evidence, the APPROXIMATE trigger table, the honesty caveats, the sandbox-check result). Tell the user the run folder + report path.

**Mandatory honesty caveats (state these in every degraded-mode report):**

- **In-session is NOT hermetic.** Each executor/grader runs in a fresh context window (no main-conversation bleed), but it still shares the repo, ancestor `CLAUDE.md`, the installed skill set, and the ambient model. It is a reasonable isolation *proxy*, not the clean room the Docker/local hermetic path gives.
- **Artifact evals are real but lower-fidelity.** A subagent really runs the skill and writes artifacts that get graded — useful validation evidence, **not** equivalent to a hermetic container / API-key eval.
- **Trigger evals are APPROXIMATE.** They proxy routing via router subagents, not a real dispatcher — **label every trigger result `APPROXIMATE`** and never report it as a measured trigger rate equivalent to the sandboxed `run_triggers.py`.
- **Never fake a green.** A grader failure is a FAIL; a missing artifact is a FAIL with that as the evidence. Do not widen a tolerance to make a run pass. If the environment cannot spawn subagents at all, print that and stop — do not self-grade from the main context.

## Run Execution

For artifact evals, invoke `python3 {skill-root}/scripts/run_evals.py` with the resolved arguments. The script handles isolation per eval, runs `claude -p` in the sandbox with the eval's prompt and any staged fixture files, and writes a per-eval folder with `prompt.txt`, `transcript.jsonl`, `artifacts/`, and `metrics.json`.

For trigger evals, invoke `python3 {skill-root}/scripts/run_triggers.py`. The script measures whether the skill's description causes the skill to fire for each query, with `runs-per-query` repeats for stability, and writes `triggers-result.json`. Trigger evals should run under Docker isolation when available — local mode can have the host's installed skills bleed in via cwd-based skill discovery, biasing the trigger signal. If Docker is unavailable, run trigger evals locally but say so explicitly.

After artifact runs complete, grade each eval. Spawn a grader subagent per eval in parallel (Agent tool, prompt loaded from `{skill-root}/agents/grader.md` plus the eval's `expectations` and the path to its outputs). Each grader writes `grading.json` next to the artifacts. The grader has license to flag weak assertions — relay that feedback to the user.

After all grading is done, generate the aggregate report — `python3 {skill-root}/scripts/generate_report.py --run-dir <run-id>` — which produces `report.html`. Tell the user where the run folder is and where the HTML report is.

## Counterfactual mode (`--mode counterfactual`)

A skill that is *present* is not necessarily a skill that *helps*. Counterfactual evals measure whether the skill's content actually changes the agent's output — the antidote to a skill that only inflates the always-loaded surface and erodes the instruction-adherence ceiling. **Opt-in and priority-scoped** (it doubles model spend); never a default gate, never part of `both`.

**Format.** `counterfactual.json` has the *same shape as `evals.json`* — an object with a non-empty `evals` list of `{id, prompt, files, expectations}` — discovered the same way (`<skill>/evals/counterfactual.json` or colocated). `wf eval coverage` recognizes it as a third artifact kind.

**Procedure (per eval).** Run the prompt **twice** in two fresh, isolated workspaces, `runs-per-prompt` times each (default 3, mirroring trigger-eval stability):
- **WITH** — the target skill present in the workspace's `.claude/skills/`.
- **WITHOUT** — the *same* workspace with the target skill's dir removed.

Then one grader subagent (this runner's `agents/grader.md` plus a counterfactual addendum) reads **both** transcripts + the `expectations` and emits a 3-way verdict with cited evidence:
- `WITH-better` — the skill measurably improved the output (the win we want);
- `NO-DELTA` — output is materially the same with or without (the skill earned its context cost only if some *other* eval shows a win);
- `WITHOUT-better` — the skill made it *worse* (a regression to investigate).

**Reporting.** Surface `NO-DELTA` and `WITHOUT-better` as a **WARN-LIST** (like `wf audit`) — do **not** auto-fail; a skill can be net-positive across its eval set even with one no-delta prompt. Aggregate the per-prompt verdict as the majority over the `runs-per-prompt` repeats.

**Honesty caveat (state it every run).** The WITHOUT arm is **APPROXIMATE**: a removed skill's influence can still leak via overlapping skills, the always-loaded `CLAUDE.md` spine, or the ambient model's priors — so `NO-DELTA` means "no *isolable* delta," not proof the skill is inert. Mirror the trigger-eval APPROXIMATE labelling. In the in-session/degraded path the two arms are two executor subagents (one given the skill, one explicitly told it is unavailable); the hermetic path reuses `run_evals.py` twice (skill present, then its dir removed from the copied workspace).

## Outcomes

- Every eval's prompt, transcript, artifacts, and grading land on disk and stay there. Nothing is silently cleaned up.
- The run honestly reflects the skill's behavior in a clean room — not the behavior of the host shell with its memories and configs.
- The user knows whether Docker or local was used and why.
- Failures cite specific expectations and evidence; passes that look superficial are flagged, not papered over.

## Constraints

- **Artifacts are forever.** Never delete, overwrite, or rotate run folders. Disk usage is the user's call.
- **Auth boundary is narrow.** On macOS, the host's Claude Code OAuth credential is staged into each isolated `.claude/.credentials.json` so the subprocess can authenticate without inheriting host config. `ANTHROPIC_API_KEY`, if set, is also forwarded. Nothing else crosses.
- **Trigger evals do not need real artifacts.** They use a stub command file and only measure description firing — keep them cheap and parallel.
- **No silent fallbacks on grading.** If a grader subagent errors, mark that eval `grading_error` rather than substituting a default verdict.
- **Stop when evals are missing.** If discovery returns nothing, halt with diagnostics — the runner does not invent test cases.
