# Story 1.1: Clear a room to unlock doors

Status: done

As a player, I want a room's doors to unlock when I defeat every enemy, so that
clearing combat is what lets me advance.

## Acceptance Criteria
- Given a room with enemies, When the last enemy dies, Then all doors unlock with an
  audible and visual cue. — MET

## Dev Notes
- Implemented an EnemyTracker that decrements on each enemy death and emits
  `room_cleared`. Doors subscribe to the signal.
- The "all enemies" count was hardcoded as a literal in the room script during early
  spiking.

## Code Review
- Approved. Reviewer flagged a magic number (the enemy count) hardcoded in the room
  script and asked that gameplay constants move to a shared config; left as a follow-up.

## Lessons Learned
- The signal-based clear worked cleanly and is reusable for the boss gate.
