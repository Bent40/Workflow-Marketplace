---
title: Skybound Lancers
game_type: action-platformer
platforms: [PC]
created: 2026-06-01
updated: 2026-06-10
---

# Skybound Lancers — Game Design Document

## Executive Summary

Skybound Lancers is an aerial action-platformer. The player chains air-dashes across floating islands and duels rival lancers in fast, readable melee exchanges. The core fantasy is being an untouchable aerial duelist who never has to land.

## Game Pillars

1. **Air is home, ground is death.** Every system rewards staying airborne — dash, strike, and recovery all chain in the air, and touching ground costs momentum. This steers level layout (gaps everywhere), enemy design (ground-bait lures), and the economy (air-time multiplier).
2. **Readable lethal exchanges.** Melee is fast but every attack has a visible tell and a counter; the player who reads the tell first wins. This steers tell timings, hit windows, and the no-random-damage rule.
3. **Momentum compounding.** Speed begets speed: chaining clean actions raises a momentum meter that increases damage and dash distance, so mastery is mechanically rewarded.

## Core Gameplay Loop

Dash to engage (0.4s i-frames) -> read the enemy tell -> land a lance strike inside the 6-frame counter window -> chain into the next dash before momentum decays (2.5s decay timer) -> repeat across the island arena until cleared.

## Game Mechanics

- **Air-dash.** The player dashes a fixed 5 tiles in the aim direction over 0.25s, with i-frames on frames 1-6 (of 15). Cooldown 0.6s; refreshed on a clean lance hit. Max 2 chained dashes before requiring a hit or ground touch.
- **Lance strike.** Melee attack: 18 damage, 0.18s startup, 0.3s recovery, reach 1.5 tiles. Hitting an enemy refunds the dash cooldown and adds +1 to the momentum meter.
- **Momentum meter.** 0-5 stacks. Each stack adds +8% lance damage and +0.5 tiles dash distance. Decays one stack per 2.5s without a hit.
- **Counter window.** Each enemy attack has a 6-frame parry window opening at its tell; a successful counter deals 2x damage and resets the enemy's tell.

## Progression and Balance

Difficulty scales by arena: arena N spawns N+2 lancers with +5% HP each. The player's max momentum cap rises from 3 to 5 across the first three arenas. No stat grind — power comes from momentum mastery, not loot.

## Art and Audio Direction

High-contrast sky vistas with a driving synthwave score; combat audio emphasizes the counter-window "ping" so the tell is audible as well as visual.

## Technical Specifications

Target: 60 FPS sustained on a mid-range PC (GTX 1060 / 1080p), measured over a 5-minute combat arena.

## Out of Scope (v1.0)

- Online multiplayer / PvP duels (deferred to post-launch).
- Procedurally generated arenas (v1.0 arenas are hand-authored).
- A loot/equipment economy (intentionally cut — progression is momentum-based, not gear-based).
