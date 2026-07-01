import { describe, it, expect } from 'vitest';
import { applyTax } from './tax';

// EXISTING test — establishes the project's pattern: describe/it, expect, AAA,
// covers happy path + boundary + error throw. New tests should mirror this style.
describe('applyTax', () => {
  it('adds tax and rounds to 2 decimals', () => {
    expect(applyTax(100, 0.2)).toBe(120);
    expect(applyTax(9.99, 0.1)).toBe(10.99);
  });

  it('rejects a negative amount', () => {
    expect(() => applyTax(-1, 0.2)).toThrow('amount must be non-negative');
  });

  it('rejects an out-of-range rate', () => {
    expect(() => applyTax(100, 1.5)).toThrow('rate must be between 0 and 1');
  });
});
