// src/routes/orders.js
// REST routes for the Orders resource. Mounted at /api/orders by src/app.js.
const express = require('express');
const router = express.Router();

const Order = require('../models/order');
const { requireAuth } = require('../middleware/auth');

// GET /api/orders  — list the authenticated customer's orders
router.get('/', requireAuth, async (req, res, next) => {
  try {
    const orders = await Order.findByCustomer(req.user.id);
    res.json(orders.map((o) => o.toJSON()));
  } catch (err) {
    next(err);
  }
});

// GET /api/orders/:id
router.get('/:id', requireAuth, async (req, res, next) => {
  try {
    const order = await Order.findById(req.params.id);
    if (!order || order.customerId !== req.user.id) {
      return res.status(404).json({ error: 'order_not_found' });
    }
    res.json(order.toJSON());
  } catch (err) {
    next(err);
  }
});

// POST /api/orders  — create an order. amount is dollars in the request,
// stored internally as integer cents (see models/order.js).
router.post('/', requireAuth, async (req, res, next) => {
  try {
    const { items, amountDollars } = req.body;
    const order = await Order.create({
      customerId: req.user.id,
      items,
      amountCents: Math.round(amountDollars * 100),
    });
    res.status(201).json(order.toJSON());
  } catch (err) {
    next(err);
  }
});

module.exports = router;
