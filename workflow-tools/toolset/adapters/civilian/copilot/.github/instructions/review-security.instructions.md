---
applyTo: "server/auth/**,server/middleware/**,src/auth/**,**/security/**"
---
<!-- GENERATED FILE — do not edit by hand. -->
<!-- Source of truth: core/rules/*.yaml + core/profiles/*.yaml + core/targets/*.yaml. Regenerate with scripts/generate-adapters.py. -->

# GitHub Copilot — review instructions: security

What to look for when REVIEWING changes to files matching the **security** path group. Profile: **civilian**. (Review focus — distinct from the authoring instructions in security.instructions.md.)

## Protected routes and actions must enforce authentication and authorization.
<!-- rule:rookie.no_missing_auth_check severity:critical review -->

- Verify every protected route/handler/action enforces authentication AND the correct per-resource authorization; flag UI-only gating and authentication-without-authorization.

## Never build queries by string concatenation — parameterize them.
<!-- rule:rookie.no_sql_injection severity:critical review -->

- Flag any query assembled by string concatenation/interpolation of request-derived values; confirm parameterized queries, bound parameters, or a vetted ORM/query builder.
