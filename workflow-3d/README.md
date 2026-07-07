# workflow-3d

Concept-art → 3D — a guided LOCAL pipeline (ComfyUI + Blender) that turns one image into a watertight 3D print, a textured game asset, or a Minecraft build. Escorts each step with a human-review gate at the watertight check. Needs workflow-core.

This is a GENERATED Claude Code plugin artifact — do not hand-edit; it is
regenerated from source and republished as a whole.

## What it is

- 5 domain skill(s) under `skills/` — a pure à-la-carte pack.
- **No hook.** The operating model lives in `workflow-core`. Install that
  first for the discipline layer; on Claude Code **web** (where plugin hooks
  do not run) invoke the `workflow-operating-model` skill to load it.

## Install

1. Add the marketplace:
   ```
   /plugin marketplace add Bent40/Workflow-Marketplace
   ```
2. Install the foundation first, then this module:
   ```
   /plugin install workflow-core
   /plugin install workflow-3d
   ```

## Skills

- `3d-mode`
- `3d-help`
- `3d-create`
- `3d-setup`
- `3d-troubleshoot`
