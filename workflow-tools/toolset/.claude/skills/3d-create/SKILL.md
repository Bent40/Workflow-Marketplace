---
name: 3d-create
description: 'Guided concept-art → 3D pipeline — walk the user from an image to a watertight print, a textured game asset, or a Minecraft build on the local ComfyUI + Blender setup. Use when the user (in 3d mode or not) says "turn this image into a print / game asset / Minecraft build", "make a 3D model from this art", "print this character", or "voxelize this for Minecraft". Routes the engine by output, applies the right settings, and validates watertightness. Not for data-model/ML-model work.'
---

# 3d-create — image → the thing you actually want

Take the user from a piece of concept art (or a photo) to their chosen output,
choosing the engine by what the output needs and catching the traps that cost
real hours on the box. **You carry the routing and trap-avoidance judgment;
the exact numbers live in [`docs/3d-modeling/`](../../../docs/3d-modeling/)** —
read `settings.md` for the per-stage values, `models.md` for what must be on
disk, `rules.md` for the constraints. Charter + binding rules:
[`docs/3d-pack.md`](../../../docs/3d-pack.md).

One CLI drives it (hides the venv-vs-Blender split):

```
python tools/pipeline.py run --in input/<name>.png --use all|print|game|minecraft
python tools/pipeline.py describe          # machine-readable manifest / readiness
```

## How to escort (this skill's job)

Walk the user through the steps below **one at a time** — this is a guided
escort, not a batch run. The user may be a non-technical artist:

- **Confirm before each consequential action** — before a long GPU generation,
  before a Blender finish pass, and before declaring anything done. Say what
  you're about to run and why, in plain language, then proceed.
- **Never skip past a gate.** The clean step (Step 2) and the watertight
  validation (Step 5) are not optional; do not batch through them to "save
  time".
- **Offer the next step at each stage** — after each step, say what just
  happened, what it produced, and the single next move. One decision at a time.
- **Stop and surface, don't guess** — if readiness fails, a model is missing,
  or a result looks wrong, say so and hand back; never fake a run or a result.

## Step 0 — Readiness (once)

Confirm the box is ready before generating: `torch.cuda.is_available()` True,
the models for the chosen path on disk (see `models.md`), Blender locatable. If
something's missing, say so and stop — hand off to `3d-setup` (guided box
readiness). Don't fake a run.

## Step 1 — Decide the output → this picks the engine

Ask (or infer) which one, then route (`--engine auto` encodes this):

| Output the user wants | Engine | Why |
|---|---|---|
| **Print** they'll paint (watertight STL, real mm) | **Hunyuan3D 2.1** (single-view) | SDF/occupancy → watertight by construction → a fine remesh holds |
| **Game asset / textured GLB** | **Hybrid** (Hunyuan geometry + TRELLIS texture) | clean solid geometry + a fitted PBR texture |
| **Minecraft** build / blocks | **TRELLIS.2** → voxelize | voxelization discards fine geometry anyway; cheapest path |
| **all** | Hybrid + Hunyuan (shares one Hunyuan shape) | one shape → both a print and a textured asset |

"More print detail" comes from the **generator**, not the remesh — a remesh can
only preserve/bridge geometry, never invent it.

## Step 2 — Clean (ALWAYS, before generate)

Run `clean` (U²-Net) to put the subject on a clean background, **tight-cropped
and square-padded with margin**. **Trap:** a tall subject centre-cropped by the
image encoder gets *decapitated* (a real headless-torso incident). Never skip
this even if the background looks clean.

## Step 3 — Generate (engine-specific settings from `settings.md`)

- **print → Hunyuan single-view**: watertight solid; `--detail 256` holds
  (watertight). This is the **shipped shape engine**.
- **game/raw → Hybrid**: run Hunyuan first, **free VRAM**
  (`mm.unload_all_models()`), then TRELLIS textures that geometry. Never load
  shape+texture together on 16 GB.
- **minecraft → TRELLIS**: `--detail 128` (open shell shreds above ~160);
  detail is discarded by voxelization anyway.
- **TRELLIS constraint:** attention backend `sdpa` (never flash_attn/xformers
  at runtime), model `visualbruno/TRELLIS.2-4B-FP8` (`use_fp8=True`).
- **🧪 Multiview is EXPERIMENTAL and off this default path.** Only consider it
  for a *clean neutral turnaround* (front/side/back of one pose). It needs its
  **own** 4.93 GB model — feeding MV conditioning to the single-view DiT
  collapses the shape into a thin ~57 K-tri sliver (the #1 trap). See
  [`multiview-experimental.md`](../../../docs/3d-modeling/multiview-experimental.md)
  before using; otherwise use single-view.

## Step 4 — Finish (per output)

- **print** (`print_prep.py`, Blender): `remove_small_islands` keep-frac ~2%
  (shed floating flakes — AI "soup" leaves disconnected shells that read as
  holes / snap on a print); `--height-mm` sets real size; `--min-wall 1.2` for
  FDM (resin ~0.5, `--hollow`).
- **game** (`finish_asset.py`, Blender): voxel remesh ~112 + island cull →
  decimate to a role×tier LOD0 budget → LOD chain → optional normal bake.
- **minecraft**: voxelize the mesh → colored voxels → `.nbt`/`.schem`.
- **Blender stages run SEQUENTIALLY, never `&`-parallel** — parallel Blender
  corrupted a mesh into thousands of islands.

## Step 5 — VALIDATE (the honesty gate — do not skip for a print)

**Watertight is a claim you verify, never assert.** Never trust `trimesh`:
`trimesh.load(force='mesh')` silently repairs and reports a *repaired copy*
watertight. A print is printable only when **both**:

1. a Blender `bmesh` **manifold/boundary audit** reports no boundary edges /
   non-manifold geometry, **and**
2. a **backface-cull render** shows no see-through holes or inverted faces.

Report the mesh as "generated" until both pass; only then "validated
printable / WATERTIGHT". Mind Y-up vs Z-up when rendering (STLs from
`print_prep` are Z-up; glTF import converts Y-up→Z-up) or the render comes out
lying down / empty and misreads as a failure.

**Human-review checkpoint (prints):** before declaring a print print-ready,
run `bmad-checkpoint-preview` so the user actually *looks at* the
backface-cull render and the audit result and confirms — a hard gate against a
novice shipping a non-watertight print on the tool's say-so. Filament and cure
time are real; the human eyes the render before the printer starts.

## Step 6 — Deliver

Outputs land under `output/<name>/` (cleaned inputs under `input/`). A `print`
run should end in a `*_print.stl` reported WATERTIGHT; a `game`/`all` run in a
textured `*_hybrid.glb`. Commit/push if in a repo (containers are ephemeral).
State plainly what was produced and what was validated vs. merely generated.

## Hard constraints (never violate — `rules.md`)

- **No `pip install`/uninstall into the ComfyUI `.venv`** — never touch
  torch/torchvision/xformers/flash_attn. Model downloads only.
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` and `ATTN_BACKEND=sdpa`
  are set by the tools — don't strip them.
- Everything is **local** — no cloud services.

## Does NOT do

- Install the models / set up the box → `3d-setup`.
- Diagnose an already-failed run in depth → `3d-troubleshoot`.
- Load the posture (`3d-mode`) or recommend which output to pick
  (`3d-help`).
