---
applyTo: "src/components/**,src/pages/**,src/app/**,ui/**"
---
<!-- GENERATED FILE — do not edit by hand. -->
<!-- Source of truth: core/rules/*.yaml + core/profiles/*.yaml + core/targets/*.yaml. Regenerate with scripts/generate-adapters.py. -->

# GitHub Copilot — path-scoped instructions: frontend

Instructions applied only to files matching the **frontend** path group. Frontend views, components, pages, client-side validation. Profile: **civilian**.

## Don't store sensitive data in localStorage or unflagged cookies.
<!-- rule:rookie.no_unsafe_browser_storage severity:high -->

- Keep secrets/tokens out of localStorage and unflagged cookies.
  Do not place tokens, credentials, or sensitive data in localStorage or in
  cookies without the appropriate flags (HttpOnly, Secure, SameSite). Choose
  storage based on the data's sensitivity and the threat model.

## Handle loading, empty, and error states for async operations.
<!-- rule:rookie.no_missing_error_state severity:medium -->

- Async work needs loading, empty, and error handling — not just the happy path.
  Async operations must handle more than the success path: show a loading state,
  handle the empty result, and handle/report errors. On the backend, external
  calls need error handling (and timeouts/retries where appropriate); on the
  frontend, surface failures to the user instead of leaving a dead UI.
