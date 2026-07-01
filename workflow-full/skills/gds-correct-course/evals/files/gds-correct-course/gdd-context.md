# Ironwood Duelists — GDD Context (excerpt)

**Game type:** action combat (high complexity)
**Platform:** PC, console

## Game Pillars

1. **Readable aggression** — combat is fast but every exchange is legible; the player who reads tells wins.
2. **Risk-reward stamina** — offense costs stamina, so overcommitting is punished and spacing matters.

## Core Gameplay Loop

Approach → bait an opening → commit an attack (spends stamina) → recover stamina → reset spacing.

## Mechanics

- **Stamina.** A regenerating bar (max 100). Light attack costs 20, heavy 40, dash 15. Regen 25/sec after a 0.8s idle delay. At 0 stamina the player is "winded" (can't attack for 1.2s). The HUD shows a green **Energy** bar under the health bar.
- **Light/heavy/dash.** Light attack 12 dmg (0.3s startup). Heavy 30 dmg (0.6s startup, armor on frames 8-14). Dash i-frames frames 1-6.
- **Parry window.** 8-frame parry; on success, attacker is stunned 0.5s and parrier refunds 30 stamina.
