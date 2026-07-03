// Already covered by tax.test.ts — do NOT re-test this.
export function applyTax(amount: number, rate: number): number {
  if (amount < 0) throw new Error('amount must be non-negative');
  if (rate < 0 || rate > 1) throw new Error('rate must be between 0 and 1');
  return Math.round(amount * (1 + rate) * 100) / 100;
}
