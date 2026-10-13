# Story 5-2: Password reset

**Status:** in-review

## Acceptance Criteria (the coverage oracle)

- **AC1 [P0] Request reset:** A user can request a reset for a known email; the
  system sends a single-use, time-limited reset token. (security-critical)
- **AC2 [P0] Token expiry / reuse rejected:** An expired or already-used reset
  token is rejected and cannot set a new password. (security-critical, negative
  path)
- **AC3 [P1] Set new password:** With a valid token, the user can set a new
  password that meets the password policy; the token is invalidated afterward.
- **AC4 [P1] Weak password rejected:** A new password that fails the policy
  (too short / breached) is rejected with a clear error.
- **AC5 [P2] Unknown email is a no-op:** Requesting a reset for an unknown email
  returns the same generic response (no account enumeration) and sends no email.

## Notes

These ACs are the requirements to trace against. Map each to the existing tests
and decide the quality gate.
