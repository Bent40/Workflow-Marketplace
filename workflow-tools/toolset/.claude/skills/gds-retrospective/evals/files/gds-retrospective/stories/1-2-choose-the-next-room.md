# Story 1.2: Choose the next room

Status: done

As a player, I want to see each adjacent room's type before I pick a door, so that I
can route my run deliberately.

## Acceptance Criteria
- Given unlocked doors, When I look at the map, Then each adjacent option shows its room
  type (combat / treasure / shop / elite). — MET
- Given I pick a door, When the room loads, Then the unchosen options are discarded for
  the floor. — MET

## Dev Notes
- Room-type icons are driven by the floor graph. Required a small rework: the first cut
  generated the adjacency lazily and could show a type that changed after selection;
  re-architected to generate the floor graph up front from the run seed.
- Room-type tuning values (spawn weights) were hardcoded inline again.

## Code Review
- Approved after the lazy-generation rework. Reviewer repeated the earlier note: spawn
  weights are magic numbers hardcoded inline; should live in a shared balance config.

## Technical Debt
- Floor-graph generation is correct but not yet covered by a determinism test.

## Lessons Learned
- Generating the floor graph up front from the seed is the right call for determinism;
  the lazy approach fought the seeded-resume requirement.
