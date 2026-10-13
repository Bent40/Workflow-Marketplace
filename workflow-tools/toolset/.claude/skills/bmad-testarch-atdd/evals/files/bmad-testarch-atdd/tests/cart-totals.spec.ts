import { test, expect } from '@playwright/test';

// Existing API test — the project's established pattern for cart endpoints.
// New ATDD scaffolds should follow this style (request fixture, status + body asserts).
test.describe('Cart totals API', () => {
  test('[P0] recomputes total when an item quantity changes', async ({ request }) => {
    const res = await request.patch('/api/cart/cart_123/items/item_9', {
      data: { quantity: 2 },
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ newTotal: expect.any(Number) });
  });
});
