// UNTESTED module. There is no discount.test.ts. This is the coverage gap that
// `automate` should fill, mirroring the pattern in tax.test.ts.

export type DiscountKind = 'percent' | 'flat';

export interface Discount {
  kind: DiscountKind;
  value: number; // for 'percent': 0..100 ; for 'flat': an absolute amount
}

/**
 * Apply a discount to a subtotal.
 * - percent: subtract value% of subtotal
 * - flat: subtract value, but never below 0 (no negative totals)
 * Throws on a negative subtotal, an unknown kind, or a percent value outside 0..100.
 */
export function applyDiscount(subtotal: number, discount: Discount): number {
  if (subtotal < 0) throw new Error('subtotal must be non-negative');

  if (discount.kind === 'percent') {
    if (discount.value < 0 || discount.value > 100) {
      throw new Error('percent value must be between 0 and 100');
    }
    const reduced = subtotal * (1 - discount.value / 100);
    return Math.round(reduced * 100) / 100;
  }

  if (discount.kind === 'flat') {
    const reduced = subtotal - discount.value;
    return reduced < 0 ? 0 : Math.round(reduced * 100) / 100;
  }

  throw new Error(`unknown discount kind: ${(discount as Discount).kind}`);
}
