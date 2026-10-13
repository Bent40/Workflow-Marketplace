---
title: EmberFall — Game Design Document (excerpt)
status: final
engine: Godot 4
---

# GDD: EmberFall

## Vision & Pillars
EmberFall is a single-player top-down action-roguelite for PC. Each run is a
descent through procedurally-arranged rooms; death is permanent for the run but
the player keeps a small amount of meta-currency ("Embers") to spend between runs.
Pillars: (1) tight melee-dodge combat, (2) build variety through stackable relics,
(3) short 20-minute runs that reward incremental mastery.

## Core Loop
Enter a room → clear all enemies → a door unlocks → choose the next room from 2-3
options shown on the map → at the end of a floor, fight a boss → descend. On death,
return to the Hub and spend Embers.

## Functional Requirements

### FR-1: Room clear and door unlock
A room's exit doors stay locked until every enemy in the room is defeated. When the
last enemy dies, all doors for that room unlock with an audible and visual cue.

### FR-2: Branching room choice
At each unlocked door the player sees the room type of each adjacent option
(combat / treasure / shop / elite) before committing. Selecting a door loads that
room; the unchosen options are discarded for that floor.

### FR-3: Relic pickup and stacking
Relics are picked up from treasure rooms. A relic applies a passive modifier (e.g.
"+15% melee damage"). Picking up a second copy of the same relic stacks its effect
additively. The active relic loadout is visible on the pause screen.

### FR-4: Permadeath and run reset
When the player's health reaches zero the run ends: the current floor, relics, and
gold are discarded and the player is returned to the Hub. The run's collected Embers
are banked and survive into the next run.

### FR-5: Meta-currency spend in Hub
In the Hub the player spends banked Embers at the Forge to unlock a permanent
starting-relic option for future runs. An unlock is permanent once purchased.

### FR-6: Boss gate per floor
A floor's final room is a boss room; its door does not appear until the player has
cleared the required number of rooms on that floor. Defeating the boss reveals the
descent stairs to the next floor.

### FR-7: Save and resume an in-progress run
A run can be paused and the game quit; on relaunch the player may resume the exact
in-progress run (current room, health, relics, gold) from where they left off. A run
is single-slot: starting a new run overwrites any resumable run.

### FR-8: Run summary on death
On death a summary screen reports the floor reached, run duration, enemies defeated,
relics held, and Embers banked, before returning to the Hub.

## Cross-Cutting Non-Functional Requirements
- **NFR-1 (Performance):** Maintain 60 FPS on the minimum spec during a room with up
  to 30 active enemies.
- **NFR-2 (Determinism):** A run seed reproduces the same room layout and reward
  options, so a resumed run is identical to the original.

## Out of scope for v1
- No online multiplayer or co-op.
- No controller remapping UI (a fixed default binding only).
- No daily-challenge / leaderboard mode.

## Decided technical context (already settled — do not re-litigate)
- Engine: Godot 4, GDScript. Single PC build (Windows/Linux).
- Save format: a single JSON save file written to the user data directory.
- Procedural generation is seeded; the seed is stored in the save.
