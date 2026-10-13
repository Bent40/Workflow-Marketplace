# Hollow Ascent — GDD Excerpt (Mechanics & Systems)

**Game type:** action-platformer (high complexity)
**Platform:** PC (Steam), Steam Deck verified target

## Game Pillars

1. **Momentum-as-mastery** — every traversal mechanic feeds back into combat and the player who reads terrain fastest wins.
2. **Punishing-but-fair death** — runs end, but every death is legible and the player keeps meta-progress.

## Core Mechanics (player-facing capabilities)

- **M1 — Double-jump.** The player can jump a second time mid-air. Jump height 3 tiles; second jump 2.2 tiles; coyote time 6 frames; input buffer 8 frames.
- **M2 — Wall-slide.** When pressing toward a wall mid-fall, descent slows to 4 tiles/sec and the player may wall-jump off at a 55-degree launch angle.
- **M3 — Three-phase boss: The Tide Warden.** A gate boss with three phases. Phase 1: melee sweeps (telegraph 0.5s). Phase 2: ranged spore volleys (3 projectiles, 1.2s cooldown). Phase 3: arena flood, platforms submerge on a 4s cycle. Each phase triggers at 66% and 33% HP.
- **M4 — Save system.** The player can save progress at Ember shrines. Saving records meta-currency, unlocked traversal upgrades, and current biome checkpoint. Autosave fires on biome transition.

## Out of Scope (v1.0)

- Online co-op (deferred to post-launch).
- Procedural level generation (levels are hand-authored for v1.0).
