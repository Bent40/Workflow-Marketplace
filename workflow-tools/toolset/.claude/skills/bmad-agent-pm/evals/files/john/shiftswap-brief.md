# ShiftSwap — Product Context for a PRD

## The idea
Small restaurants and cafes run their staff schedule in a spreadsheet or a group chat.
When someone can't work a shift, finding a replacement is a chaotic flurry of texts.
ShiftSwap is a lightweight mobile-first web app where an employee can post a shift they
need covered, eligible coworkers get notified, someone claims it, and the manager
approves the swap in one tap.

## Who it's for
- **Primary:** hourly staff at single-location restaurants/cafes (5–40 employees).
- **Secondary:** the shift manager / owner who has to approve changes.
- Not for: large multi-location chains with existing workforce-management software.

## The core problem (validated by 12 manager interviews)
- Managers spend real time every week chasing replacements over text.
- Shifts sometimes go uncovered because the request never reached the right person.
- There's no record of who agreed to what, leading to no-show disputes.

## What v1 must do (founder's must-haves)
- An employee posts "I need Friday 5–10pm covered."
- Only coworkers who are eligible (same role, not already scheduled that block) are notified.
- A coworker claims the shift.
- The manager approves or rejects the swap; nothing is final until the manager approves.
- Everyone involved sees the current state; there's an auditable record of the swap.

## Constraints
- Must work on a phone browser; many staff won't install a native app.
- Managers are not technical; setup must be near-zero.
- Pilot with 3 cafes in one city before any paid rollout.

## Deliberately undecided (founder has NOT chosen)
- Pricing/monetization model.
- Whether to integrate with any existing POS or payroll system.
- Notification channel (SMS vs push vs email) — open.
- Whether managers can also originate shifts, or only approve swaps.
