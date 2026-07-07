# workflow — Claude Code plugin marketplace

The **workflow** operating model + BMAD skill suite, packaged as **à-la-carte Claude Code plugins**. Install the thin foundation once, then add only the domain modules you need.

- **Operating model** — authority boundaries, autonomy, honesty gating, right-sizing, subagent policy, and the report frame — shipped by `workflow-core` (a `SessionStart` hook on desktop/CLI; the `workflow-operating-model` skill on web).
- **Skills** — the BMAD agile SDLC, game design, test architecture, creative, web design, builders, and editorial suites — as separate opt-in modules.

## Install

1. Add this marketplace:
   ```
   /plugin marketplace add Bent40/Workflow-Marketplace
   ```
2. Install the foundation first (it carries the operating model):
   ```
   /plugin install workflow-core
   ```
3. Add any modules you want (see the list below), e.g.:
   ```
   /plugin install workflow-method
   ```

On Claude Code **web**, plugin `SessionStart` hooks do not run — invoke the `workflow-operating-model` skill (shipped in `workflow-core` and `workflow-full`) to load the operating model into context.

## Plugins

- **workflow-core** — The workflow operating model (ambient router, honesty gates, right-sizing) + a thin set of universal helpers. Install this first; add domain modules à la carte.
- **workflow-full** — Every stock BMAD skill (all upstream modules) — the one-shot everything bundle, on top of workflow-core.
- **workflow-method** — BMad Method — the agile SDLC: analyst/PM/architect/dev/UX agents, PRD, epics, stories, sprints, and the dev/review loop. Needs workflow-core. *(needs workflow-core)*
- **workflow-game-design** — BMad Game Dev Studio — GDD, game architecture, narrative, playtest planning, and the game dev loop for Unity/Unreal/Godot/Phaser. Needs workflow-core. *(needs workflow-core)*
- **workflow-test-architect** — BMad Test Architect — quality strategy, ATDD, CI gates, traceability, NFR audits, and test automation. Needs workflow-core. *(needs workflow-core)*
- **workflow-creative** — Creative Intelligence Suite — storytelling, design thinking, innovation strategy, and creative problem-solving coaches. Needs workflow-core. *(needs workflow-core)*
- **workflow-web-design** — Whiteport Design Studio — the strategic, design-first UX methodology (project brief → trigger mapping → scenarios → UX → design system → evolution). Needs workflow-core. *(needs workflow-core)*
- **workflow-builders** — BMad Builder — meta-tooling for authors of AI agents, workflows, and skills (agent/workflow/module builders, eval runner, customize). Needs workflow-core. *(needs workflow-core)*
- **workflow-editorial** — Editorial & review — prose and structural copy-editing plus adversarial and edge-case content review. Needs workflow-core. *(needs workflow-core)*
- **workflow-3d** — Concept-art → 3D — a guided LOCAL pipeline (ComfyUI + Blender) that turns one image into a watertight 3D print, a textured game asset, or a Minecraft build. Escorts each step with a human-review gate at the watertight check. Needs workflow-core. *(needs workflow-core)*
- **workflow-writer** — Writer's studio — a literary posture loader (writer mode), a state-aware writing guide, and craft skills for author-style study, genre positioning/comps, and teaching. Reroutes the toolset for writing fiction/prose. Needs workflow-core. *(needs workflow-core)*

## License

MIT — see [`LICENSE`](./LICENSE). © 2026 B.T..

> Generated artifact — this marketplace is regenerated from source and republished as a whole; do not hand-edit individual files here.
