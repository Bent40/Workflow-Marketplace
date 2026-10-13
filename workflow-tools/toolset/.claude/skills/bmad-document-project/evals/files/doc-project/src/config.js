// src/config.js
// Central configuration. Every value comes from an environment variable;
// the app refuses to boot if a required one is missing (fail-fast).
function required(name) {
  const value = process.env[name];
  if (value === undefined || value === '') {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

module.exports = {
  port: parseInt(process.env.PORT || '3000', 10),
  databaseUrl: required('DATABASE_URL'),
  jwtSecret: required('JWT_SECRET'),
  // When true, /api/orders rejects requests without a valid bearer token.
  authEnabled: process.env.AUTH_ENABLED !== 'false',
};
