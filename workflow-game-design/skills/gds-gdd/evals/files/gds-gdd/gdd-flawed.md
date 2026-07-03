---
title: Skybound Lancers
game_type: action-platformer
platforms: [PC]
created: 2026-06-01
updated: 2026-06-01
---

# Skybound Lancers — Game Design Document

## Executive Summary

Skybound Lancers is a fast aerial action-platformer where players dash between floating islands and duel rival lancers. It's going to be really fun and addictive.

## Game Pillars

1. **Make it fun.** The whole game should feel fun and rewarding to play.
2. **Aerial combat.** Players fight in the air.

## Core Gameplay Loop

Players fly around, fight enemies, and collect loot, then repeat.

## Game Mechanics

- **Dash.** The player can dash through the air. The dash feels floaty and good, giving a real sense of speed and momentum that players will love.
- **Lance strike.** A melee attack. It hits enemies in front of the player.
- **Loot pickups.** Defeated enemies drop loot that the player picks up.

### Implementation Notes

The dash is driven by a Unity `CharacterController` component and the air-friction is handled in a custom `AirDragShader` applied to the velocity vector each FixedUpdate. The lance hitbox uses a `BoxCollider2D` trigger.

## Progression and Balance

Players get stronger over time as they collect more loot. Enemies get harder deeper into the run.

## Art and Audio Direction

Bright, colorful sky vistas with a synthwave soundtrack.
