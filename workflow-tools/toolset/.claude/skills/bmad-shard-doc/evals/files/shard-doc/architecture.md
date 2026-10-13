# Payments Service Architecture

Intro paragraph describing the overall payments service and its responsibilities.

## Overview

The payments service handles charge creation, refunds, and webhook delivery. It is a stateless HTTP service backed by Postgres.

### Responsibilities

- Create and capture charges
- Issue refunds
- Deliver webhooks to merchants

## Data Model

The core tables are `charges`, `refunds`, and `webhook_events`. Charges reference a merchant and carry an idempotency key.

### charges table

Columns: id, merchant_id, amount_cents, currency, status, idempotency_key.

## API Endpoints

- `POST /charges` — create a charge
- `POST /charges/:id/refunds` — refund a charge
- `GET /charges/:id` — fetch a charge

## Failure Handling

Webhook delivery retries with exponential backoff up to 24 hours. Charges use idempotency keys to make retries safe.
