# Story 1.3: Show Remaining Against Cap

Status: done

As a Household member, I want to see Remaining after a Trip commits, So that I know how the week is tracking.

## Acceptance Criteria
- Given a committed Trip, When viewing the summary, Then Remaining equals Weekly Cap minus this week's committed Trip totals. — MET
- Given two devices, When a sync completes, Then both devices show the same Remaining. — NOT MET

## Dev Notes
- The single-device Remaining calculation works correctly and is well tested.
- Cross-device sync (the second AC) was NOT delivered. Sync turned out to need a conflict-resolution
  strategy we had not designed. To keep the story moving we marked it done with the sync AC deferred.
- This means two devices can currently show DIFFERENT Remaining values until a manual refresh.

## Code Review
- Approved for the single-device behavior only. Reviewer explicitly noted the sync AC is unmet and
  flagged it as carry-over risk into Epic 2, which assumes sync works.
- Input-validation comments came up again here (third story with this feedback).

## Technical Debt
- Cross-device sync / conflict resolution is undesigned. This is a real gap, not a polish item —
  Epic 2 depends on sync being reliable.

## Lessons Learned
- We marked a story "done" with an acceptance criterion unmet. We should not call a story done when an
  AC is deferred without an explicit, tracked follow-up story.
- Recurring input-validation review feedback across all three stories suggests a missing shared validation utility.
