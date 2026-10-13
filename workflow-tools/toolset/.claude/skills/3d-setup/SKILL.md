---
name: 3d-setup
description: 'Guided box readiness for the 3D pack — escort the user through getting a machine ready to run the local concept-art → 3D pipeline: verify base software (ComfyUI, torch+CUDA, Blender), download the exact models to the right paths, and run the smoke test. Use when the user says "set up the 3D box", "3d setup", "which models do I need", "get my machine ready for 3D", or "why won''t the pipeline find its models". Downloads only — never pip-installs into the ComfyUI venv. Not for data-model/ML-training setup.'
---

# 3d-setup — get the box ready (downloads only, no venv edits)

Escort the user to a **ready** box: base software verified, the right models on
disk at the right paths, and a passing smoke test — before they try to generate
anything. **The exact repos/paths/sizes live in
[`models.md`](../../../docs/3d-modeling/models.md) and
[`hardware-scouting.md`](../../../docs/3d-modeling/hardware-scouting.md)**; read
them for the numbers. Charter + binding rules:
[`docs/3d-pack.md`](../../../docs/3d-pack.md).

## How to escort

Walk it **one step at a time**, confirming as you go; the user may be
non-technical. **Right-size to their goal** — a *print-only* box needs just
Hunyuan + U²-Net; textured/game needs TRELLIS + DINOv3; multiview is optional
and experimental. Don't download 30 GB when they only want prints.

## The one hard constraint

**Never `pip install`/uninstall into the ComfyUI `.venv`.** Never touch
torch/torchvision/torchaudio/xformers/flash_attn. **Model downloads are fine;
package installs are not** — the toolkit is install-free by design. A "fix" that
edits the venv is not a fix; rebuild the box, not the environment.

## Step 1 — Verify base software (before any download)

| Piece | Want | Check |
|---|---|---|
| ComfyUI tree | present, with `tools/pipeline.py` | the repo root |
| Python venv | **3.11** at `.venv` (ComfyUI's own — don't recreate) | — |
| torch | **2.8.0+cu128** (CUDA 12.8) | `torch.cuda.is_available()` must be **True** |
| Blender | **4.5 LTS**, auto-located (`BLENDER` env override) | — |
| ComfyUI-Trellis2 | present in `custom_nodes/` (only for texture/hybrid) | — |

Blackwell (50-series) **needs cu128+**. Older cards: any cu-build matching the
driver, as long as CUDA is available to torch. If `cuda.is_available()` is
False, stop — that's a box/driver/torch-build problem to fix outside the venv,
not something to paper over.

## Step 2 — Download the models for the chosen path (exact paths in `models.md`)

Pick by goal (total ~30 GB, ~35 GB with the experimental MV model):

- **Prints:** Hunyuan3D 2.1 single-view (`hunyuan_3d_v2.1.safetensors`, 7.37 GB)
  + U²-Net (~168 MB, auto-downloads on first `clean`).
- **Textured / game:** also TRELLIS.2-4B-FP8 (~9 GB) + DINOv3 ViT-L/16
  (~1.1 GB, required by TRELLIS).
- **🧪 Multiview (optional, experimental):** Hunyuan3D 2-mv
  (`hunyuan3d-dit-v2-mv_fp16.safetensors`, 4.93 GB) — skip unless specifically
  experimenting with turnarounds.

A download is **not** a pip install — fetch and copy into place:

```python
from huggingface_hub import hf_hub_download; import shutil
p = hf_hub_download("Comfy-Org/hunyuan3D_2.1_repackaged", "hunyuan_3d_v2.1.safetensors")
shutil.copy(p, "models/checkpoints/hunyuan_3d_v2.1.safetensors")
```

Confirm each file landed at the path `models.md` specifies (a wrong path reads
downstream as a "missing model").

## Step 3 — Verify, in order (don't declare ready on a partial check)

```bash
.venv/Scripts/python -c "import torch;print(torch.__version__, torch.cuda.is_available())"  # 2.8.0+cu128 True
.venv/Scripts/python tools/pipeline.py describe                                              # JSON manifest
.venv/Scripts/python tools/pipeline.py run --in input/test_rgba.png --use all               # ends in a watertight STL
```

The box is **ready** only when step 3 yields a `*_print.stl` reported
**WATERTIGHT** and a textured `*_hybrid.glb`. Report which models are present,
which are missing, and the exact next download — never claim ready on a smoke
test that didn't actually run.

## Does NOT do

- Run a real creation job (`3d-create`) or pick the output (`3d-help`).
- Diagnose a failure *after* generation (`3d-troubleshoot`).
- Install Python packages — downloads only, never into the ComfyUI `.venv`.
