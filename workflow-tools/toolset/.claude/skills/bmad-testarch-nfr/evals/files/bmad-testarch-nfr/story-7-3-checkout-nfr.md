# Story 7-3: Checkout Service — Non-Functional Requirements

**Story ID:** 7-3
**Feature:** Checkout / order-placement service
**Status:** Implemented — pending pre-release NFR sign-off

This story defines the non-functional requirements (NFRs) for the checkout
service. Implementation is complete; this audit must grade each NFR attribute
against the evidence in `evidence-summary.md`.

## NFR Requirements & Thresholds

### Performance (P0)

- **NFR-P1:** Checkout API p95 response time MUST be < 500ms under expected load
  (50 concurrent users).
- **NFR-P2:** Error rate under load MUST be < 1%.

### Security (P0)

- **NFR-S1:** All checkout endpoints MUST require authentication; unauthenticated
  requests MUST be rejected (401).
- **NFR-S2:** Payment card data MUST be encrypted in transit (TLS) and never
  logged in plaintext.
- **NFR-S3:** The service MUST have zero critical and zero high dependency
  vulnerabilities at release.

### Reliability (P1)

- **NFR-R1:** The checkout flow MUST degrade gracefully when the payment
  provider returns 5xx (user sees a retry path, no crash).
- **NFR-R2:** A `/health` endpoint MUST report the status of the database and the
  payment provider.

### Scalability (P1)

- **NFR-SC1:** The service MUST sustain a 2x traffic spike (100 concurrent users)
  without error-rate regression beyond the NFR-P2 threshold.

## Acceptance Criteria for this Audit

- Every NFR attribute above is graded PASS, CONCERNS, or FAIL.
- A grade of PASS requires concrete supporting evidence in the evidence summary.
- An attribute with no evidence, or with evidence that does not meet its
  threshold, MUST NOT be graded PASS.
