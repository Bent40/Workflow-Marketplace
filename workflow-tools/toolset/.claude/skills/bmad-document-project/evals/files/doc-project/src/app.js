// src/app.js
// Application entry point. Wires middleware and mounts resource routers.
const express = require('express');
const config = require('./config');
const orders = require('./routes/orders');

const app = express();
app.use(express.json());

// All API resources are mounted under /api.
app.use('/api/orders', orders);

// Central error handler — every router forwards errors here via next(err).
app.use((err, req, res, next) => {
  const status = err.status || 500;
  res.status(status).json({ error: err.code || 'internal_error' });
});

app.listen(config.port, () => {
  // eslint-disable-next-line no-console
  console.log(`listening on :${config.port}`);
});

module.exports = app;
