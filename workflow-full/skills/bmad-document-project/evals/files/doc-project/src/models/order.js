// src/models/order.js
// Order data model. All persistence goes through the shared db pool in
// src/db.js — routes and services NEVER import `pg` or open their own client.
const db = require('../db');

class Order {
  constructor(row) {
    this.id = row.id;
    this.customerId = row.customer_id;
    this.items = row.items;
    // Money is stored in the DB as integer cents; never as a float.
    this.amountCents = row.amount_cents;
    this.status = row.status;
    this.createdAt = row.created_at;
  }

  static async findById(id) {
    const { rows } = await db.query('SELECT * FROM orders WHERE id = $1', [id]);
    return rows[0] ? new Order(rows[0]) : null;
  }

  static async findByCustomer(customerId) {
    const { rows } = await db.query(
      'SELECT * FROM orders WHERE customer_id = $1 ORDER BY created_at DESC',
      [customerId]
    );
    return rows.map((r) => new Order(r));
  }

  static async create({ customerId, items, amountCents }) {
    const { rows } = await db.query(
      `INSERT INTO orders (customer_id, items, amount_cents, status)
       VALUES ($1, $2, $3, 'pending') RETURNING *`,
      [customerId, JSON.stringify(items), amountCents]
    );
    return new Order(rows[0]);
  }

  // API responses expose dollars; cents stay internal.
  toJSON() {
    return {
      id: this.id,
      customerId: this.customerId,
      items: this.items,
      amount: this.amountCents / 100,
      status: this.status,
      createdAt: this.createdAt,
    };
  }
}

module.exports = Order;
