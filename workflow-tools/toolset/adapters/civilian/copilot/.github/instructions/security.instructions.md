---
applyTo: "server/auth/**,server/middleware/**,src/auth/**,**/security/**"
---
<!-- GENERATED FILE — do not edit by hand. -->
<!-- Source of truth: core/rules/*.yaml + core/profiles/*.yaml + core/targets/*.yaml. Regenerate with scripts/generate-adapters.py. -->

# GitHub Copilot — path-scoped instructions: security

Instructions applied only to files matching the **security** path group. Auth, permissions, input validation, secrets, data exposure. Profile: **civilian**.

## Protected routes and actions must enforce authentication and authorization.
<!-- rule:rookie.no_missing_auth_check severity:critical -->

- Don't leave protected routes/actions without an auth check.
  Every route, endpoint, or action that is meant to be protected must enforce
  authentication and the correct authorization check. Do not rely on the UI
  hiding a control as the only barrier.

## Never build queries by string concatenation — parameterize them.
<!-- rule:rookie.no_sql_injection severity:critical -->

- No string-built queries; use parameterized queries / safe query APIs.
  Do not assemble SQL (or any query language) by concatenating or interpolating
  user-influenced values — that is an injection risk. Use parameterized queries,
  bound parameters, or a vetted query builder/ORM.
