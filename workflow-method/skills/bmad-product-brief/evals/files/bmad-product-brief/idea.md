# Product idea notes — "ShiftSwap" (raw brain dump)

Hourly shift workers (think cafes, retail, warehouses) constantly need to swap shifts,
and today it happens in chaotic group chats. A manager has to eyeball whether a swap is
even legal (overtime, certifications, minor work-hour rules) and approve it manually.
Stuff gets missed and people no-show.

What it is: a mobile-first app where a worker posts a shift they can't make, eligible
coworkers see it and claim it, and the swap goes to the manager for one-tap approval —
but the app pre-checks the obvious rules first so the manager only sees swaps that are
already legal.

Why now: the SMB scheduling tools that exist are heavyweight and built for HQ schedulers,
not for the floor worker on their phone. The wedge is the worker-initiated swap that is
pre-validated, not the full scheduling suite.

Target user: floor-level hourly workers and their shift managers at single-location or
small-chain businesses. NOT enterprise workforce-management buyers.

What I'm sure about:
- Worker posts an unwanted shift; eligible coworkers claim it.
- App pre-checks eligibility rules (overtime threshold, required certification for the
  role, minor work-hour limits) before the manager ever sees it.
- Manager gets a one-tap approve/deny on pre-validated swaps only.

What I'm unsure about:
- Where the rule definitions come from (manager-entered vs imported from an existing
  scheduler) — not decided.
- Whether v1 integrates with any existing scheduling tool or is standalone.
- Pricing model and target business size sweet spot.

Explicitly NOT v1:
- Not a full scheduling / shift-creation tool — swaps only.
- No payroll or time-clock integration.
- No web/desktop client in v1; mobile only.
