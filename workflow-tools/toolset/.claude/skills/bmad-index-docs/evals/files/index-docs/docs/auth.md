# Authentication

How users sign in: email + password, with optional TOTP two-factor. Sessions are JWTs that expire after 24 hours and are refreshed via a rotating refresh token.
