---
name: 3d-mode
description: 'Load 3d mode — reroute the workflow toolset for the local concept-art → 3D pipeline (image → watertight print / game asset / Minecraft build, all on-box, no cloud). Use when the user says "enter 3d mode" or "3d mode", or asks to set the session up for 3D modeling / turning art into 3D / printing a model. "exit 3d mode" drops it. Does NOT fire for data-model / database-schema work, ML-model training, or React/print-to-console "render"/"print".'
---

# 3d-mode — 3D-pipeline posture for the workflow toolset

You are now in 3D MODE: the user is turning concept art (or photos) into
**3D** — watertight prints, textured game assets, or Minecraft builds — on a
**local** ComfyUI + Blender setup, no cloud. They may be an artist, not an
engineer. The overrides below stay in force until the user says "exit 3d
mode". The measured numbers and full reasoning live in
[`docs/3d-modeling/`](../../../docs/3d-modeling/); the pack charter and binding
rules are [`docs/3d-pack.md`](../../../docs/3d-pack.md).

## Vocabulary guards (override the catalog's trigger phrases)

Engineering skills in this catalog fire on words a 3D artist uses constantly:

- **"model" / "create a model" / "3D model"** = the **mesh**. NEVER route to
  `bmad-create-architecture` (data model), ML-model training, or
  `bmad-data-model` framing.
- **"print"** = a **3D print** (watertight STL in real mm). Not console
  printing / logging.
- **"render"** = a **validation render** (a backface-cull image that reveals
  holes/inverted faces). Not React/UI rendering.
- **"asset"** = a **game/print asset** (GLB/FBX/STL). Not a generic build
  artifact or web asset.
- **"generate"** = run the image→3D generator. Not code generation.

## The 3D toolset (route here)

| Need | Use |
|---|---|
| Lost, "where do I start", "is my box ready", "what can I make" | `3d-help` (probes readiness + inputs, asks the output goal, routes) |
| "Turn this image into a print / game asset / Minecraft build" | `3d-create` (the guided concept→3D pipeline) |
| Exact settings / models / hardware numbers | [`docs/3d-modeling/`](../../../docs/3d-modeling/) — `settings.md`, `models.md`, `hardware-scouting.md` |
| Box setup — which models to install, verify torch+CUDA | `3d-setup` (reads [`docs/3d-modeling/models.md`](../../../docs/3d-modeling/models.md)) |
| Something failed (headless, sliver, holes, OOM, lying-down render) | `3d-troubleshoot` (reads [`docs/3d-modeling/rules.md`](../../../docs/3d-modeling/rules.md) + `settings.md`) |
| VRAM planning for a card/model | [`hardware-scouting.md`](../../../docs/3d-modeling/hardware-scouting.md) (measured VRAM per stage) |

## Behavior in 3d mode (the binding rules — full text in the charter)

- **Route the engine by OUTPUT** (not preference): print → **Hunyuan** (solid,
  watertight by construction); game/textured → **Hybrid** (Hunyuan geometry +
  TRELLIS texture); Minecraft → **TRELLIS** (voxelized anyway). "More print
  detail" comes from the *generator*, never the remesh.
- **Watertight is a claim to VERIFY, never assert.** Never trust `trimesh` — it
  silently repairs and reports a repaired *copy* watertight. A print is
  printable only when a Blender `bmesh` manifold/boundary audit **and** a
  backface-cull render both pass. Always separate "generated a mesh" from
  "validated printable."
- **Clean before generate — always.** Tight-crop + square-pad with margin; a
  tall subject centre-cropped by the encoder gets *decapitated*.
- **Single-view Hunyuan is the shipped shape engine.** Multiview is
  EXPERIMENTAL, off every default path, and needs its own model — feeding MV
  conditioning to the single-view DiT collapses the shape into a thin sliver.
- **Never `pip install` into the ComfyUI `.venv`** (never touch
  torch/xformers/flash_attn). Model downloads are fine; package installs are
  not. The toolkit is install-free by design.
- **Respect the 16 GB VRAM budget:** shape-only ~10 GB; texture is a *separate*
  stage — never load shape+texture together; keep `expandable_segments:True`.
- **Heavy Blender stages run SEQUENTIALLY, never `&`-parallel** (parallel
  Blender corrupts meshes into thousands of islands).
- **Local & offline, author-directed.** No cloud. Outputs under `output/<name>/`;
  commit/push at natural stops (remote containers are ephemeral). Right-size to
  the artist's goal — suppress engineering ceremony (no PRD/architecture/test
  offers, no session-start toolchain checks, no MCP recommendations) unless
  asked.
- **The honesty bar holds:** never claim a watertight result, a validation
  render, or a completed print-prep that didn't actually run.

## Session-end harvest (feeds the 3D pack roadmap)

Before the session closes (or on "wrap up"), if real friction showed up (a
misroute, a trap the pack should have caught, a missing capability like guided
setup or troubleshooting), run `bmad-skill-gap-retrospective` over it and append
the result — proposed-skill specs / misroutes / missing capabilities — under a
date-stamped heading in `{project-root}/_workflow/3d-mode-feedback.md`.
PROCESS SIGNAL ONLY — never the user's art or private paths. Ask before
committing the file; it exists to grow the roadmap (`3d-setup`,
`3d-troubleshoot`) from real sessions.

## Exit

On "exit 3d mode": drop the overrides above, confirm in one line, and
offer the session-end harvest if it hasn't run.
