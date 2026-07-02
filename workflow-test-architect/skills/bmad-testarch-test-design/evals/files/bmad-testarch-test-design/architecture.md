# Architecture Notes: Funds Transfer

## Components

- **transfer-service** — owns the transfer use cases. Stateless HTTP service.
- **ledger-db** — Postgres. Transfers use a single DB transaction with
  `SELECT ... FOR UPDATE` on the source account row to prevent lost updates
  (relevant to NFR-3).
- **limits-cache** — Redis. Caches the running daily external-transfer total per
  user keyed by `user_id:UTC_date`. Source of truth remains ledger-db; the cache
  is a read-through optimization.
- **audit-log** — append-only table in ledger-db; no UPDATE/DELETE grants.

## Testability characteristics

- transfer-service exposes a `/healthz` and a test-only seeding endpoint behind a
  feature flag to seed account balances deterministically.
- Clocks are injected (the daily-limit window depends on UTC date), so tests can
  pin "now" — the limit boundary is controllable and observable.
- limits-cache has no fault-injection hook today: there is no documented way to
  simulate a Redis outage or a stale cache entry, so cache/ledger divergence is
  hard to observe in test. This is a known testability gap.
- Step-up auth (NFR-1) is delegated to an external IdP; the IdP has no sandbox
  reachable from CI, so step-up flows cannot be exercised end-to-end in CI today.

## Constraints

- Daily-limit accounting is keyed on **UTC** date, not local time.
- External payee transfers MUST go through step-up auth before the ledger write.
