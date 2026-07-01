import { describe, it, expect } from 'vitest';
import { orderTotal } from '../src/total.js';

describe('orderTotal', () => {
  it('sums price * qty across line items', () => {
    const total = orderTotal([
      { price: 10, qty: 2 },
      { price: 5, qty: 3 },
    ]);
    expect(total).toBe(35);
  });

  it('returns 0 for an empty cart', () => {
    expect(orderTotal([])).toBe(0);
  });
});
