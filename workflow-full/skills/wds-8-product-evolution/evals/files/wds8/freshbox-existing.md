# FreshBox — Existing product state (excerpt for Product Evolution / brownfield)

FreshBox is already live (React web app, Stripe subscriptions). This is a brownfield improvement, not a new build.

## Observed problem (from analytics + support)
- The "Skip a week" control is buried two levels deep in account settings.
- 22% of cancellations cite "couldn't figure out how to skip" in the exit survey.
- Support still gets ~40 emails/week asking "how do I skip a week?".

## Improvement target requested
Make skipping a week obvious and one-tap from the subscriber's main dashboard, so fewer subscribers cancel and fewer email support.

## Constraints
- Live product — change must ship behind its own branch and be acceptance-tested before deploy.
- Single view in scope: the subscriber dashboard. Do NOT redesign the whole account area.
- Existing design tokens and components must be reused (leaf-green primary, cream cards, Inter).
