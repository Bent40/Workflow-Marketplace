import { test, expect } from '@playwright/test';

// Shared mutable state across tests (isolation anti-pattern).
let createdOrderId: string;

test.describe('Checkout', () => {
  test('creates an order', async ({ page, request }) => {
    await page.goto('/checkout');

    // Non-deterministic data generation (determinism anti-pattern).
    const cartId = `cart-${Math.random()}`;
    // Time dependency without mocking (determinism anti-pattern).
    const placedAt = new Date().toISOString();

    await page.getByTestId('place-order').click();

    // Hard wait instead of a condition (flakiness anti-pattern).
    await page.waitForTimeout(5000);

    const res = await request.post('/api/orders', {
      data: { cartId, placedAt },
    });
    const body = await res.json();
    // Test B below depends on this value (test-order dependency anti-pattern).
    createdOrderId = body.id;
    expect(res.status()).toBe(201);
  });

  test('shows the confirmed order', async ({ page }) => {
    // Depends on the previous test having populated createdOrderId.
    await page.goto(`/orders/${createdOrderId}`);

    // No assertion — this test can never fail (missing-assertion anti-pattern).
    await page.getByTestId('order-status');
  });

  test('handles an optional discount', async ({ page }) => {
    await page.goto('/checkout');

    // Conditional control flow — behavior varies, test asserts nothing reliable.
    const hasDiscount = await page.getByTestId('discount-banner').isVisible();
    if (hasDiscount) {
      await page.getByTestId('apply-discount').click();
      // Testing an implementation detail (an internal CSS class) instead of behavior.
      await expect(page.locator('.discount--applied-internal')).toBeVisible();
    }
  });
});
