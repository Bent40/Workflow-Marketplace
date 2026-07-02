---
title: GroceryCap
status: final
---

# PRD: GroceryCap

## 1. Vision
A mobile app that lets a household scan grocery receipts and instantly see how the
trip lands against a weekly spending cap.

## 3. Glossary
- **Trip** — a single grocery purchase captured from one receipt.
- **Weekly Cap** — the spending limit a Household sets for a calendar week.
- **Household** — the up-to-two users who share one Weekly Cap.
- **Remaining** — Weekly Cap minus the sum of this week's Trip totals.

## 4. Features

### 4.1 Receipt Capture
#### FR-1: Scan a receipt
A user can photograph a receipt; OCR extracts the Trip total, shown editable
before commit.

#### FR-2: Show remaining against cap
After a Trip commits, show Trip total, Weekly Cap, and Remaining.

### 4.2 Shared Household Cap
#### FR-3: Edit the weekly cap
A Household member can set or change the Weekly Cap; the change is reflected on
both members' devices.

#### FR-4: Sync across devices
Two devices in one Household stay consistent on the cap and the Remaining figure.

## Cross-Cutting NFRs
- **NFR-1 (Offline):** A Trip can be captured offline and synced later; conflicts
  resolved deterministically.
- **NFR-2 (Consistency):** Both Household devices must converge to the same
  Remaining after sync.
- **NFR-3 (Privacy):** Receipt images never leave the Household's own cloud space.

## Decided technical context (treat as already-settled inputs — do NOT re-litigate)
- Client: React Native (single codebase, iOS + Android). No web client in v1.
- Backend: a managed Backend-as-a-Service providing auth, a hosted Postgres
  database, and per-Household row-level isolation. No bespoke server in v1.
- OCR: an on-device OCR library; only the extracted total (a number), never the
  image, is sent to the backend.
- Offline/sync: a local store on each device with last-write-wins on the Weekly
  Cap and additive merge of Trips, reconciled on reconnect.
