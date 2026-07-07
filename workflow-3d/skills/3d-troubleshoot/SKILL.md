---
name: 3d-troubleshoot
description: 'Diagnose a FAILED concept-art → 3D run — match a symptom (headless/decapitated subject, thin sliver, holes / not watertight, floating flakes, OOM, lying-down or empty render, corrupted many-island mesh, super-slow decode, TRELLIS attention error) to its known cause and the fix. Use when the user says "3d troubleshoot", "my print has holes", "the mesh came out mangled/tiny", "it OOMed", "the render is empty/lying down", or "why did the generation fail". Never fixes by editing the ComfyUI venv. Not for data-model/ML debugging.'
---

# 3d-troubleshoot — symptom → cause → fix

Something already went wrong; find *why* and the fix. Each failure below was hit
on the box and costs hours if misdiagnosed. **Exact numbers live in
[`rules.md`](../../../docs/3d-modeling/rules.md),
[`settings.md`](../../../docs/3d-modeling/settings.md),
[`hardware-scouting.md`](../../../docs/3d-modeling/hardware-scouting.md), and
[`multiview-experimental.md`](../../../docs/3d-modeling/multiview-experimental.md)**.
Charter + binding rules: [`docs/3d-pack.md`](../../../docs/3d-pack.md).

## How to diagnose

Get three things first: the **symptom** (what the output looks like), the
**engine + output** used (print/game/minecraft; Hunyuan/Hybrid/TRELLIS/MV), and
the **actual error or observation**. Then match below. **Never propose a
`pip install` into the ComfyUI `.venv` as a fix** (hard constraint) — the fix is
in inputs, settings, sequencing, or the box, not the venv.

## Symptom → cause → fix

| Symptom | Cause | Fix |
|---|---|---|
| **Headless / decapitated subject** (missing head, torso only) | Tall subject **centre-cropped** by the image encoder | Always `clean` first: **tight-crop + square-pad with margin** — never feed a raw tall image. |
| **Thin ~57 K-tri sliver / collapsed shape** (the #1 trap) | **Multiview conditioning fed to the single-view DiT** | Use the **MV model** (`hunyuan3d-dit-v2-mv`) for multiview; for a single image use **single-view Hunyuan**. Octree can't recover it — the shape is baked at sampling. |
| **"Watertight" but holes on the printer / print fails** | Trusted **`trimesh`** (silently repairs a *copy* and reports it watertight), **or** used TRELLIS (open shell) for a print | Verify with a Blender **`bmesh` manifold/boundary audit + backface-cull render**; use **Hunyuan** for prints (watertight by construction). |
| **Floating flakes / speckles reading as holes** | Voxel-remeshed AI "soup" leaves small disconnected shells | `remove_small_islands`, keep only components **≥2%** of the largest. |
| **OOM during generate/decode** | Shape+texture loaded together, 4-view MV, or VRAM fragmentation | Keep `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`; texture is a **separate stage** (free VRAM between models); lower `octree_resolution`; MV → **front+back only**. |
| **Render comes out lying down / empty** (misreads as failure) | **Y-up vs Z-up** mismatch | Get the camera up-axis right — STLs from `print_prep` are **Z-up**; glTF import converts **Y-up→Z-up**. |
| **Mesh corrupted into thousands of islands** | **Parallel Blender** processes | Run heavy Blender stages **SEQUENTIALLY**, never `&`-parallel — one at a time. |
| **Decode extremely slow / wildly variable** (25 s–335 s; MV 10–24 min) | **RAM offload** under VRAM pressure — *not hung* (GPU at 99% = working) | Expected variance, not a bug; more system RAM = fewer stalls; lower octree (**192** for MV). |
| **Print shreds above ~160 detail** | TRELLIS open shell can't hold a fine remesh | `--detail 128` for TRELLIS, **256** for Hunyuan (per engine, set automatically by `pipeline.py`). |
| **TRELLIS runtime / attention error** | Wrong attention backend (flash_attn/xformers at runtime) | `ATTN_BACKEND=sdpa`; model `visualbruno/TRELLIS.2-4B-FP8` (`use_fp8=True`). |
| **`torch.cuda.is_available()` False / Blackwell errors** | Wrong CUDA build for the card | **torch 2.8.0+cu128** for 50-series; fix the box/driver/build — **do not** pip-change the venv. |

## The honesty rule this skill enforces

If the reported symptom is "it says watertight," treat that as **unverified**
until the `bmesh` audit + backface-cull render both pass (a `trimesh` say-so is
the classic false positive). "More print detail" is never a remesh fix — it
comes from the **generator**; a remesh only preserves/bridges geometry.

## Does NOT do

- Run or re-run the pipeline happy path (`3d-create`).
- Install models / set up the box (`3d-setup`).
- Pick the output or route (`3d-help`); load the posture (`3d-mode`).
- Any fix that edits the ComfyUI `.venv`.
