# Story 2-3 — Brief invincibility after taking damage

## Status

ready-for-dev

## Story

**As a** player,
**I want** a short window of invincibility after I take a hit,
**so that** a single enemy can't drain my whole health bar in one overlap frame.

## Acceptance Criteria

1. Given the player is vulnerable, when `apply_damage(amount)` is called with a
   positive amount, then health is reduced by that amount via the existing
   `HealthComponent` and an invincibility window begins.
2. Given the player is currently within the invincibility window, when
   `apply_damage(amount)` is called again, then no health is lost and the call is
   ignored.
3. Given the invincibility window has elapsed (its duration passed), when
   `apply_damage(amount)` is called, then damage applies normally again.
4. The invincibility duration is a designer-tunable `@export` value, not a
   hardcoded constant.

## Tasks / Subtasks

- [ ] In `scripts/player_damage.gd`, add an `@export var invincibility_seconds`
      tunable and an internal timer/flag tracking the active window (AC: 4)
- [ ] In `PlayerDamage.apply_damage`, ignore the call while invincible, otherwise
      reduce health through the existing `HealthComponent.take_damage` and start
      the invincibility window (AC: 1, 2)
- [ ] Clear the invincibility flag when the window elapses so damage applies
      again afterward (AC: 3)
- [ ] Add unit tests covering: damage applies when vulnerable, a second hit
      during the window is ignored, and damage applies again after the window
      elapses (AC: 1, 2, 3)

## Dev Notes

- **Reuse, do not reinvent.** `HealthComponent`
  (`scripts/health_component.gd`) already exposes
  `take_damage(amount: int) -> void` which clamps health at 0 and emits
  `health_changed`. Call it; do NOT mutate a separate health field or add a
  second health store in `PlayerDamage`.
- **`PlayerDamage` owns only the invincibility gate** — it decides whether a hit
  is allowed through, then delegates the actual health change to the
  `HealthComponent` it holds a reference to.
- Treat elapsed time as injectable for tests: the timer should advance from a
  `tick(delta)` call (or equivalent) so a unit test can simulate the window
  expiring without real wall-clock waiting. Do NOT block on a real-time wait.
- [Source: architecture.md#Components] and [Source: architecture.md#Combat]

## Dev Agent Record

### Debug Log

### Completion Notes

## File List

## Change Log
