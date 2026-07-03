# EmberFall - Architecture (excerpt)

## Engine & Language
- Godot 4, GDScript only. No C# in this project.

## Relic system (Story 2.1 established this)
- `RelicSystem` (autoload singleton) owns the active relic loadout for the current
  run. It exposes `add_relic(relic_id)`, `get_loadout()`, and the signal
  `relic_changed`. Story 2.2 MUST reuse `RelicSystem` and MUST NOT introduce a second
  source of truth for the loadout.
- A relic's effect is a `RelicModifier` resource; modifiers are applied by summing
  their contributions, so additive stacking is the intended model — do not special-case
  stacking with bespoke per-relic code.
- The loadout is part of the run save state; any change to the loadout must go through
  `RelicSystem` so the save stays consistent. [Source: architecture.md#Relic-system]

## Determinism & RNG
- The run uses a single seeded RNG (`RunRng`). Any randomness introduced by the
  conversion-to-gold overflow rule MUST draw from `RunRng`, never from `randi()` /
  `randf()` directly, or run determinism (NFR-2) breaks. [Source: architecture.md#Determinism]

## UI conventions
- Pause-screen widgets live under `ui/pause/`. The loadout widget reads from
  `RelicSystem.get_loadout()` and must not poll node state directly.

## Testing standards
- GUT (Godot Unit Test) specs live under `test/unit/`. Each system change ships a
  unit test. [Source: architecture.md#Testing-standards]
