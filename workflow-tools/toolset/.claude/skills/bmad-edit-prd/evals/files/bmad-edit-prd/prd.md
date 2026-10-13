---
title: GroceryCap
status: final
created: 2026-05-01
updated: 2026-05-01
---

# PRD: GroceryCap

## 0. Document Purpose
For the PM and downstream UX/architecture/epics workflows. Vocabulary is anchored
in the Glossary; features are grouped with FRs nested; assumptions are tagged
inline.

## 1. Vision
GroceryCap gives a household an at-the-moment signal of whether a grocery trip
fits inside its weekly cap, so overspending is caught at checkout rather than days
later.

## 2. Target User

### 2.1 Jobs To Be Done
- Know, right after a grocery run, whether I'm still under my weekly cap.
- Share one budget with my partner without double-counting.

### 2.3 Key User Journeys
- **UJ-1. Priya checks the trip damage before she's even home.** She scans the
  receipt, the app OCRs the total and shows this trip, the cap, and what remains.

## 3. Glossary
- **Trip** — a single grocery purchase captured from one receipt.
- **Weekly Cap** — the spending limit a Household sets for a calendar week.
- **Household** — the set of users (up to two in v1) who share one Weekly Cap.
- **Remaining** — Weekly Cap minus the sum of this week's Trip totals.

## 4. Features

### 4.1 Receipt Capture
**Description:** A user scans a paper receipt; the app OCRs the Trip total and
lets the user correct it before it counts. Realizes UJ-1.

**Functional Requirements:**

#### FR-1: Scan a receipt
A user can photograph a receipt and have its Trip total extracted by OCR.

**Consequences (testable):**
- The extracted total is shown in an editable field before it is committed.
- If OCR fails, the user can enter the total manually.

#### FR-2: Show remaining against cap
After a Trip is committed, the app shows the Trip total, the Weekly Cap, and
Remaining.

**Consequences (testable):**
- Remaining equals Weekly Cap minus the sum of committed Trip totals this week.

### 4.2 Shared Household Cap
**Description:** Two users in one Household share a single Weekly Cap and see the
same Remaining. Realizes UJ-1.

**Functional Requirements:**

#### FR-3: Edit the weekly cap
A Household member can set or change the Weekly Cap.

**Consequences (testable):**
- A cap change is reflected on both members' devices.

## 5. Non-Goals (Explicit)
- No bank or card-account linking.
- No per-item categorization or nutrition data.

## 6. MVP Scope

### 6.1 In Scope
- Receipt scan, editable total, shared weekly cap, remaining display.

### 6.2 Out of Scope for MVP
- Multi-week budgeting and reports.
- Web client.

## 7. Success Metrics

**Primary**
- **SM-1**: Weekly active retention past 30 days. Validates FR-1, FR-2.

## 8. Open Questions
1. How are Trips reconciled when both members scan offline and later sync?

## 9. Assumptions Index
- §4.1 — OCR accuracy is good enough that manual correction is the exception.
