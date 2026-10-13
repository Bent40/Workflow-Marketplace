---
applyTo: "src/components/**,src/pages/**,src/app/**,ui/**"
---
<!-- GENERATED FILE — do not edit by hand. -->
<!-- Source of truth: core/rules/*.yaml + core/profiles/*.yaml + core/targets/*.yaml. Regenerate with scripts/generate-adapters.py. -->

# GitHub Copilot — review instructions: frontend

What to look for when REVIEWING changes to files matching the **frontend** path group. Profile: **civilian**. (Review focus — distinct from the authoring instructions in frontend.instructions.md.)

## Don't store sensitive data in localStorage or unflagged cookies.
<!-- rule:rookie.no_unsafe_browser_storage severity:high review -->

- Flag tokens, credentials, or sensitive data placed in localStorage or in cookies missing HttpOnly/Secure/SameSite; confirm storage matches the data's sensitivity.

## Handle loading, empty, and error states for async operations.
<!-- rule:rookie.no_missing_error_state severity:medium review -->

- Confirm async paths handle loading, empty, and error states; flag happy-path-only UIs and unhandled external-call failures.
