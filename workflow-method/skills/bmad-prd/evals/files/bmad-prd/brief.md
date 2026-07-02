# Product Brief: GroceryCap

## One-liner
A mobile app that lets a household scan grocery receipts and instantly see how
the trip lands against a weekly spending cap.

## Problem
People on a fixed weekly grocery budget only discover they overspent days later,
when it's too late to adjust. There is no in-the-moment signal at or right after
checkout.

## Target user
Priya — budgets on a single income with a new baby. She wants to know, the moment
she finishes a grocery run, whether she's still under her weekly cap. A secondary
user is her partner, who shares the same household cap.

## What it does (intended scope, v1)
- Scan a paper receipt with the phone camera; OCR the total.
- Show a single overlay: this trip's total, the weekly cap, the amount remaining,
  and days left in the week.
- A household can set and edit its weekly cap.
- Two people in the same household share one cap and see the same remaining figure.
- If a receipt was already scanned earlier the same day, ask whether this trip
  replaces or adds to the earlier one before counting it against the cap.

## Explicitly NOT in v1
- No bank or card-account linking — receipt scan only.
- No per-item categorization or nutrition data.
- No multi-week budgeting, forecasting, or reports.
- Not a general personal-finance app.

## Constraints / concerns
- Mobile-first (iOS + Android). No web client in v1.
- Receipts may OCR imperfectly; the user must be able to correct the total before
  it counts.
- Household data is shared between two people — privacy of who scanned what is not
  a concern within a household, but the cap and totals must stay consistent across
  both devices.

## Success (rough)
- Priya checks the app after most grocery runs and keeps using it past the first
  month.
- The "remaining this week" figure is something she trusts enough to act on.
