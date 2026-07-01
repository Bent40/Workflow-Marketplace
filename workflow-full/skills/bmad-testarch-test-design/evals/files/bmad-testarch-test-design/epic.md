# Epic 4: Funds Transfer

**Epic goal:** Let an authenticated account holder move money between their own
accounts and to an external payee, with limits and an audit trail.

## Functional Requirements

- **FR-1 (Internal transfer):** An authenticated user can transfer funds between
  two of their own accounts. The source balance must be sufficient; the transfer
  is atomic (both ledger rows commit or neither does).
- **FR-2 (External payee transfer):** A user can transfer to a saved external
  payee. External transfers above the daily limit are rejected.
- **FR-3 (Daily limit enforcement):** The cumulative external-transfer amount per
  user per UTC day must not exceed the configured `daily_limit` (default 5000).
  A transfer that would breach the limit is rejected with a clear error.
- **FR-4 (Audit trail):** Every transfer attempt (success or failure) writes an
  immutable audit record with actor, amount, timestamp, and outcome.

## Non-Functional Requirements

- **NFR-1 (Security):** Transfer endpoints require a valid session AND a
  re-authentication step (step-up auth) for external transfers. An unauthenticated
  or under-authenticated request must be rejected.
- **NFR-2 (Performance):** p95 latency for an internal transfer must be < 400ms
  under nominal load (50 req/s).
- **NFR-3 (Data integrity):** Concurrent transfers from the same source account
  must never overdraw the balance (no lost updates).

## Out of scope for this epic

- Currency conversion / multi-currency accounts (handled by Epic 6).
- Scheduled / recurring transfers (Epic 7).
