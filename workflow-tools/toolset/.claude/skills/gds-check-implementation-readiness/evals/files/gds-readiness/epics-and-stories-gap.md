# Hollow Ascent — Epics & Stories (current backlog)

This backlog covers the planned development work for the v1.0 vertical slice.

## Epic 1 — Core Traversal

Goal: deliver the movement feel that the Momentum-as-mastery pillar depends on.

- **Story 1.1 — Double-jump.** As a player I can perform a second jump mid-air. AC: second jump height ~2.2 tiles; coyote time 6 frames; input buffer 8 frames; second jump consumed until ground/wall contact. (Covers M1.)
- **Story 1.2 — Wall-slide & wall-jump.** As a player I can slide down a wall and launch off it. AC: descent capped at 4 tiles/sec while pressing toward wall; wall-jump launches at 55-degree angle; chains into double-jump. (Covers M2.)

## Epic 2 — Boss Encounters

Goal: deliver the gate-boss fight that closes the vertical slice.

- **Story 2.1 — Tide Warden phase 1 (melee).** Melee sweeps with 0.5s telegraph; transition to phase 2 at 66% HP. (Covers M3 phase 1.)
- **Story 2.2 — Tide Warden phase 2 (ranged).** Spore volleys: 3 projectiles, 1.2s cooldown; transition to phase 3 at 33% HP. (Covers M3 phase 2.)
- **Story 2.3 — Tide Warden phase 3 (arena flood).** Platforms submerge on a 4s cycle; encounter resolves on boss death. (Covers M3 phase 3.)

## Notes

- Art and audio tasks tracked separately in the art backlog.
- No story currently scopes persistence/save work.
