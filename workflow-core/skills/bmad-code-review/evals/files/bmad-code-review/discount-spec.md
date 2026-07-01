---
title: 'Cart percentage discount'
status: 'in-review'
---

## Intent

**Problem:** Carts have no way to apply a promotional percentage discount.

**Approach:** Add `Cart.apply_discount(percent)` that returns the discounted total.

## Boundaries & Constraints

**Always:**
- Reject invalid input: `apply_discount` MUST raise `ValueError` when `percent`
  is negative or greater than 100. A discount outside 0–100 is never valid.
- The discount must not mutate `self.items`.

**Never:**
- Do not change the rounding behavior of `subtotal()`.

## Tasks & Acceptance

**Acceptance Criteria:**
- Given a cart with subtotal 100, when `apply_discount(10)` is called, then it
  returns 90.
- Given any cart, when `apply_discount(150)` or `apply_discount(-5)` is called,
  then it raises `ValueError`.
