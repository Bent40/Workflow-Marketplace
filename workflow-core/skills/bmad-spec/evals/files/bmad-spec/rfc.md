# RFC / brain dump: "Quarter Drop" promo-code redemption service

We need a small service that lets our mobile app redeem promo codes during quarterly
marketing drops. Here's the unsorted thinking.

Why we're doing it: last quarter's drop melted the checkout service because promo
validation was inline in checkout. We want redemption isolated so a viral code can't
take down purchases. The drop happens four times a year and traffic spikes hard for
about an hour each time.

What a user does: enters a code at checkout; the app calls the redemption service; the
service says valid/invalid and, if valid, reserves the discount for that cart so it
can't be double-spent. On purchase completion the reservation is committed; if the cart
is abandoned the reservation expires after 30 minutes.

Hard rules we already know:
- A single code can be redeemed at most once per customer account. This is
  non-negotiable — finance has been burned by double-redemption before.
- The service must stay up and correct under the spike even if the recommendations and
  reviews services are degraded; redemption cannot depend on them.
- Codes are case-insensitive but stored uppercase.

Code types we support (each behaves differently):
- PERCENT — N% off the cart subtotal, capped at a max-discount amount.
- FIXED — a flat amount off, never exceeding the subtotal.
- BOGO — buy-one-get-one on a specific SKU; requires two qualifying items in the cart.
- FREESHIP — waives shipping; stacks with at most one other non-FREESHIP code.

We measure success by: zero checkout outages attributable to redemption during the next
drop, and zero double-redemptions reported by finance for the quarter.

Things we are explicitly NOT doing here:
- Not building the campaign/code-generation admin tool — codes are imported from the
  existing marketing system.
- Not handling refunds/reversal of a committed redemption in v1.
- Not a general loyalty/points system.

Open: do we need per-code rate-limiting separate from the per-account-once rule? Not
sure yet. Also unsure whether FREESHIP-plus-one stacking applies across all code types
or only PERCENT/FIXED.
