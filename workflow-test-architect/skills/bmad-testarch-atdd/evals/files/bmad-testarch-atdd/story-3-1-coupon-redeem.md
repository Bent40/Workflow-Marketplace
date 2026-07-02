# Story 3-1: Redeem a discount coupon at checkout

**Status:** approved

## Story

As a shopper, I want to apply a discount coupon code at checkout, so that the
eligible discount is deducted from my order total before payment.

## Acceptance Criteria

1. **AC1 (happy path):** Given a cart with a subtotal, when the user POSTs a valid,
   active coupon code to `POST /api/cart/{cartId}/coupon`, the API returns `200` and
   the response body includes the recomputed `discountAmount` and `newTotal`.
2. **AC2 (invalid code):** When the coupon code does not exist, the API returns
   `404` with an error body `{ "error": "COUPON_NOT_FOUND" }` and the cart total is
   unchanged.
3. **AC3 (expired code):** When the coupon exists but is expired, the API returns
   `422` with `{ "error": "COUPON_EXPIRED" }` and the cart total is unchanged.
4. **AC4 (minimum spend not met):** When the cart subtotal is below the coupon's
   `minSpend`, the API returns `422` with `{ "error": "MIN_SPEND_NOT_MET" }`.
5. **AC5 (one coupon per cart):** Applying a second coupon to a cart that already
   has one returns `409` with `{ "error": "COUPON_ALREADY_APPLIED" }`.

## Notes

The endpoint is NOT implemented yet — this story is the next one to be built.
