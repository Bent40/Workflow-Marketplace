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

### 4.1 Household & Accounts
#### FR-1: Create a household account
A user can create a Household and invite one other person to join it.

#### FR-2: Join a household by invite
An invited user can accept and become the second member of a Household.

### 4.2 Receipt Capture
#### FR-3: Scan a receipt
A user can photograph a receipt; OCR extracts the Trip total, shown editable
before commit.

#### FR-4: Correct an OCR total
A user can edit the extracted total before the Trip is committed.

#### FR-5: Same-day duplicate prompt
If a receipt was already scanned earlier the same day, the app asks whether this
Trip replaces or adds to the earlier one before counting it.

### 4.3 Cap & Remaining
#### FR-6: Set and edit the weekly cap
A Household member can set or change the Weekly Cap.

#### FR-7: Show remaining against cap
After a Trip commits, show Trip total, Weekly Cap, and Remaining; Remaining equals
Weekly Cap minus the sum of this week's committed Trip totals.

#### FR-8: Sync the cap and remaining across both devices
Both Household devices converge to the same Weekly Cap and Remaining after sync.

## Cross-Cutting NFRs
- **NFR-1 (Offline):** A Trip can be captured offline and synced later.
- **NFR-2 (Mobile):** iOS and Android only; no web client in v1.
