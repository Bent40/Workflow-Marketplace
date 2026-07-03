---
title: EmberFall — Game Design Document (excerpt)
status: final
engine: Godot 4
---

# GDD: EmberFall

## Vision & Core Fantasy
A single-player top-down action-roguelite for PC. The fantasy: a nimble ember-knight
who gets stronger by mastering tight dodge-and-strike combat across short, lethal runs.
Pillars: tight melee-dodge combat; build variety via stackable relics; 20-minute runs
that reward incremental mastery.

## Core Loop
Clear a room of enemies to unlock its doors, choose the next room from 2-3 visible
options, fight a floor boss, descend. On death, return to the Hub and spend Embers.

## Mechanics (design owned by this GDD)
- Combat: melee attack, dash-dodge with i-frames, stamina governs dashes.
- Relics: passive modifiers picked up in treasure rooms; duplicate relics stack
  additively, capped at five stacks.
- Permadeath: a run ends on death; relics/gold are lost; Embers are banked.
- Hub: the Forge spends banked Embers to unlock permanent starting-relic options.

## Target Players
PC players who enjoy skill-expressive roguelites (Hades / Dead Cells fans) and play in
short sessions. NOT a casual idle-game audience.

## Settled technical context
- Godot 4, GDScript. Single PC build (Windows/Linux).
- Seeded procedural generation; the seed is saved with the run.
- Single JSON save file in user://; one resumable run slot.

## Out of scope for v1
- No online multiplayer / co-op.
- No daily-challenge / leaderboard mode.
- No mobile or console port in v1.
