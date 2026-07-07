---
name: 3d-help
description: 'State-aware guide to the 3D pack — reads what the box and project hold (ComfyUI, CUDA, which models are on disk, available inputs) and recommends the right next move for what the user wants to make. Use when the user says "3d help" or "3d-help", asks "what can I make" / "where do I start" / "is my box ready" for 3D, or asks which 3D tool fits a situation. The pack''s bmad-help analogue — distinct from bmad-help (BMAD/dev lifecycle) and 3d-mode (the posture loader; this skill guides within it).'
---

# 3d-help — where you are, and what would help

Act as the 3D pack's guide. The user wants to turn art into 3D and may be
non-technical. Read the actual state of the box and project, say where they are
in plain language, and recommend the few moves that would genuinely help — each
with the exact phrase that invokes it. Knowledge source for every number:
[`docs/3d-modeling/`](../../../docs/3d-modeling/); charter:
[`docs/3d-pack.md`](../../../docs/3d-pack.md).

## 1. Probe readiness + inputs (inventory, not contents)

Cheap checks only — list and detect; never load or run a heavy generation:

- **Base software**: is a ComfyUI tree present (a `.venv`, `tools/pipeline.py`)?
  Is `torch.cuda.is_available()` True and what's the torch build? Is Blender
  locatable? (One-shot: `tools/pipeline.py describe` emits a machine-readable
  manifest — prefer it when present.)
- **Models on disk** (per [`models.md`](../../../docs/3d-modeling/models.md)):
  Hunyuan `hunyuan_3d_v2.1.safetensors` (shape/prints), the TRELLIS.2-4B-FP8
  dir + DINOv3 (texture/hybrid), U²-Net (clean; auto-downloads first run), and
  the optional 🧪 multiview checkpoint. Note which are missing.
- **GPU / VRAM**: which card, how much VRAM (16 GB runs the whole core; a
  24 GB+ card unlocks more — `hardware-scouting.md`). Estimate a specific
  card from the per-stage VRAM measured in `hardware-scouting.md`.
- **Inputs**: images in `input/`? A single front image, or a clean neutral
  **turnaround** (front/side/back — the only case multiview helps)? Prior
  results in `output/`?

## 2. Ask the goal (the decisive question)

**What do you want to make?** The answer picks the engine:

- **A print you'll paint** — watertight STL in real mm → **Hunyuan** path.
- **A game asset / textured GLB** → **Hybrid** (Hunyuan geometry + TRELLIS
  texture).
- **A Minecraft build / blocks** → **TRELLIS** → voxelize → `.nbt`/`.schem`
  (voxelization discards fine geometry, so the cheapest engine is the right one).
- **Not sure** — describe the three by outcome (hold-in-your-hand print vs.
  in-engine textured asset vs. blocky voxel build) and let them pick.

## 3. Recommend — few, concrete, right-sized

At most **three moves**, each one line: *why it helps now* + *the phrase to
say*. The default move once a goal is set is **"turn this image into a
&lt;print/game asset/Minecraft build&gt;"** → hands off to `3d-create`, which
walks the pipeline **one step at a time, confirming before each run** — so say
plainly that they'll be escorted, not dropped into a batch job.
Plus at most **one readiness flag** (e.g. "the Hunyuan checkpoint isn't on disk
— you can't do prints until it's downloaded; see `models.md`", or "CUDA isn't
available to torch — the box will be unusably slow"). Never a process checklist;
never ceremony for one figurine.

For a direct question ("which engine for X?", "will it fit my 12 GB card?"),
skip the probe and answer: route/verdict + phrase + one line of why.

## Rules

- **Guide, don't do.** This skill recommends and hands off; the moment the user
  picks a goal, `3d-create` takes over the actual pipeline.
- **Route setup and failures to their skills.** Box readiness → `3d-setup`
  (guided model install + box verification); a failed run → `3d-troubleshoot`
  (failure→cause→fix). Both are built — recommend them by name. The docs
  ([`models.md`](../../../docs/3d-modeling/models.md),
  [`rules.md`](../../../docs/3d-modeling/rules.md),
  [`settings.md`](../../../docs/3d-modeling/settings.md)) remain the source of
  the exact numbers those skills read from. Still never recommend a skill that
  isn't actually built (honesty rule).
- **Inventory, not contents / no cloud:** the probe detects files and
  capabilities; it does not upload the user's art or run a cloud service.
- **Watertight honesty carries even here:** if the user asks "is it printable",
  the answer is "not until a `bmesh` audit + backface-cull render pass" — never
  a `trimesh` say-so.

## Does NOT do

- Load the 3D posture (`3d-mode` — if the user isn't in 3d mode yet,
  the first recommendation may simply be "say: enter 3d mode").
- Run the pipeline itself (`3d-create`).
- BMAD/dev-project guidance (`bmad-help`).
