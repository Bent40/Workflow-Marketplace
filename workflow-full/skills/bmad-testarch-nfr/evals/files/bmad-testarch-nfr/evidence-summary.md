# Checkout Service — Implementation Evidence Summary (Story 7-3)

This file is the ONLY evidence available for the NFR audit. It is deliberately
incomplete: some NFR attributes have measured evidence, some have partial/weak
evidence, and some have no evidence at all.

## Performance

- **NFR-P1 (p95 < 500ms):** k6 load test executed at 50 concurrent users.
  Result file `artifacts/k6-checkout-2026-06-10.json` reports
  **p95 = 412ms**. Threshold met.
- **NFR-P2 (error rate < 1%):** Same k6 run reports **error rate = 0.3%**.
  Threshold met.

## Security

- **NFR-S1 (auth required):** Playwright API test
  `tests/nfr/checkout-auth.spec.ts` asserts that an unauthenticated
  `POST /api/checkout` returns **401**. Test is green in CI run #4821.
- **NFR-S2 (card data encrypted / not logged):** No evidence. No TLS
  configuration audit was performed and no log-scrubbing test exists for this
  service. (TODO — owner unassigned.)
- **NFR-S3 (zero critical/high vulns):** `npm audit` was last run on a previous
  release; **no scan was run against the current dependency set**. The stale
  report from two releases ago showed 0 critical and 2 high — those two highs
  have not been re-checked since.

## Reliability

- **NFR-R1 (graceful degradation on payment 5xx):** No automated test exercises
  the payment-provider-5xx path. A developer manually observed a generic error
  page once during local testing, but this was not recorded or reproduced.
- **NFR-R2 (/health reports db + payment provider):** Endpoint `GET /health`
  exists and returns `{ "status": "ok" }`. It does **not** include per-dependency
  status for the database or payment provider. Confirmed by reading
  `src/routes/health.ts`.

## Scalability

- **NFR-SC1 (sustain 2x spike at 100 users):** Not tested. The k6 run only went
  to 50 concurrent users; no 100-user spike scenario was executed.

## Notes

- No SLO/threshold was defined anywhere for memory or CPU usage, so those are out
  of scope for this story.
