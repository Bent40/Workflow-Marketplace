# Prototype Architecture (excerpt)

## Engine

Godot 4.x, GDScript. Gameplay logic lives under `scripts/`. Tests are plain
GDScript test scripts that instantiate the systems directly and assert on their
public methods/signals — no scene tree required for logic-only systems.

## Components

The player is composed of small single-responsibility component nodes. Each
component owns exactly one concern and exposes a narrow public API. Components
never reach into each other's private state; they call each other's public
methods or react to each other's signals.

- `HealthComponent` is the single source of truth for current health. It is the
  ONLY place health is mutated. Other systems request changes through its public
  methods and listen to its `health_changed` signal.

## Combat

Damage flows one direction: a hit source calls into the player's damage gate
(`PlayerDamage`), which decides whether the hit is currently allowed (e.g. the
player is not invincible) and, if so, delegates the health change to the
`HealthComponent`. The damage gate must never bypass the `HealthComponent` to
edit health directly, and must never keep its own duplicate health value.

Time-based gameplay state (cooldowns, invincibility windows) advances from an
explicit delta tick so it can be unit-tested deterministically.
