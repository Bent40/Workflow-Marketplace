---
title: EmberFall — GDD + technical context for architecture
status: final
---

# EmberFall — Design & Technical Context

## What the game is
A single-player, top-down action-roguelite for PC. Short seeded runs through
procedurally-arranged rooms, permadeath per run, meta-progression via Embers spent
in a Hub between runs. Target: 60 FPS on minimum spec with up to 30 active enemies
in a room.

## Epics this architecture must support
- Epic 1 — Combat & Room Flow: room-clear door unlock, branching room choice, per-floor boss gate.
- Epic 2 — Relics & Builds: relic pickup, additive stacking, loadout display.
- Epic 3 — Permadeath & Hub Meta: run reset on death, banked Embers across runs, Forge unlocks.
- Epic 4 — Save/Resume: resume an in-progress single-slot run; seeded determinism.

## Settled technical context (treat as already-decided inputs — do NOT re-litigate)
- **Engine:** Godot 4, GDScript only. No C#. Single PC build (Windows + Linux).
- **Architecture style:** scene-tree composition with a small set of autoload
  singletons for cross-cutting run state (run RNG, relic loadout, save).
- **Procedural generation:** seeded; the run seed is stored in the save so a resumed
  run reproduces the same layout and reward options (determinism is load-bearing).
- **Persistence:** a single JSON save file in the Godot user:// data directory; one
  resumable run slot.
- **No networking:** the game is fully offline; no server, no online services.

## Cross-cutting concerns the architecture must address
- **Determinism:** all run randomness must flow through one seeded RNG so a resumed
  run is identical to the original. Direct engine RNG calls are forbidden.
- **Performance:** the room/enemy update path must hold 60 FPS with 30 enemies on
  minimum spec; pooling or equivalent is expected for enemies and projectiles.
- **Save integrity:** a corrupt or partial save must never crash the game on launch;
  it falls back to "no resumable run".
