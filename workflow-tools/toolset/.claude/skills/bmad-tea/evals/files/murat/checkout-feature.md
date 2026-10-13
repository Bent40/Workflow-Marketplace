# Feature for Test Design: Guest Checkout + Discount Codes

## Context
An e-commerce web app is adding a guest checkout flow with discount-code support.
We want a risk-based test plan / test strategy before writing any tests.

## What the feature does
1. A guest (not logged in) can buy a cart of physical items without creating an account.
2. At checkout the guest enters: shipping address, email, and payment (via a third-party
   payment provider, Stripe-like, tokenized — we never see raw card data).
3. The guest can apply a discount code:
   - Percentage codes (e.g. 15% off the cart subtotal).
   - Fixed-amount codes (e.g. $10 off).
   - Codes can be expired, usage-capped (e.g. first 100 uses), or limited to a minimum
     cart subtotal.
   - Only one code per order.
4. Tax and shipping are calculated server-side after the discount is applied.
5. On successful payment, an order is created and a confirmation email is sent.

## Known risk areas / concerns from the team
- Discount math: percentage vs fixed, rounding, interaction with tax/shipping order of
  operations, and ensuring a discount can never make the order total negative.
- Race condition on usage-capped codes (two guests redeeming the 100th use at once).
- Payment edge cases: card declined, payment provider timeout, double-submit of the
  pay button, and ensuring no order/charge mismatch.
- Inventory: an item going out of stock between adding to cart and paying.
- Security: the discount and totals must be recomputed server-side; a client must not be
  able to forge a price or stack codes.

## Constraints
- This is a regression-prone money path; correctness and security weigh heavily.
- Existing stack uses Playwright for E2E and has an API layer that can be tested directly.
