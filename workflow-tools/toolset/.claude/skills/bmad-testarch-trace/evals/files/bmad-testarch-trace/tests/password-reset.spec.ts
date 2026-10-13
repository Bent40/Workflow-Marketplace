import { test, expect } from '@playwright/test';

// The ONLY existing tests for the password-reset story.
// Note what is and is NOT covered here when building the traceability matrix.
test.describe('Password reset', () => {
  // Covers AC1 (request reset, happy path).
  test('[P0] requests a reset token for a known email', async ({ request }) => {
    const res = await request.post('/api/auth/reset/request', {
      data: { email: 'known@example.com' },
    });
    expect(res.status()).toBe(202);
  });

  // Covers AC3 (set new password with a valid token).
  test('[P1] sets a new compliant password with a valid token', async ({ request }) => {
    const res = await request.post('/api/auth/reset/confirm', {
      data: { token: 'valid-token', newPassword: 'Str0ng-Passw0rd!' },
    });
    expect(res.status()).toBe(200);
  });

  // Covers AC4 (weak password rejected).
  test('[P1] rejects a password that fails the policy', async ({ request }) => {
    const res = await request.post('/api/auth/reset/confirm', {
      data: { token: 'valid-token', newPassword: 'short' },
    });
    expect(res.status()).toBe(422);
  });

  // NOTE: There is NO test for AC2 (expired/reused token rejection) — a P0
  // security negative path — and NO test for AC5 (unknown-email no-op).
});
