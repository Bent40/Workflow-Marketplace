# Feature Spec: Password Reset

## Summary
Users who forget their password can request a reset link by email.

## Behavior
1. User enters their email on the "Forgot password" page and clicks Submit.
2. The system generates a reset token and emails a link containing the token.
3. The user clicks the link and is taken to a "Set new password" page.
4. The user enters a new password twice and submits; the password is updated.
5. The user is redirected to the login page.

## Notes
- The reset link looks like `https://app.example.com/reset?token=<token>`.
- The token is a UUID.
- We will store the token in the `users` table in a `reset_token` column.
- The new password must be at least 8 characters.

## Out of scope
- Multi-factor auth changes.
