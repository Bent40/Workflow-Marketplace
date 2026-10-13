// EXISTING test pattern to mirror: jest + supertest against the Express app.
const request = require('supertest');
const express = require('express');
const { router } = require('./api-routes');

function buildApp() {
  const app = express();
  app.use(express.json());
  app.use(router);
  app.get('/healthz', (req, res) => res.status(200).json({ ok: true }));
  return app;
}

describe('GET /healthz', () => {
  it('returns 200 and ok:true', async () => {
    const app = buildApp();
    const res = await request(app).get('/healthz');
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ ok: true });
  });
});
