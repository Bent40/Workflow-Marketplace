# Story 1.2: Join a Household by Invite

Status: done

As an invited user, I want to accept an invitation, So that I become the second member.

## Acceptance Criteria
- Given a valid invite, When accepted, Then the user is added as the second member. — MET

## Dev Notes
- Invite token expiry was underspecified; had to redo the token logic twice before review.
- Edge case: a user accepting a second invite while already in a Household was not in the spec. Handled defensively.

## Code Review
- Two rounds. First round flagged missing input validation on the invite token (recurring theme).
- Second round approved.

## Technical Debt
- Invite tokens are stored unencrypted at rest. Acceptable for now; flagged for hardening before launch.

## Lessons Learned
- Token/auth edge cases keep surfacing late in review. We should spec expiry and reuse rules up front.
