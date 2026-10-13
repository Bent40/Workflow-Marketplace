export function orderTotal(lineItems: { price: number; qty: number }[]): number {
  return lineItems.reduce((sum, item) => sum + item.price * item.qty, 0);
}
