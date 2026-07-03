// Express router for a simple "todos" REST API.
// Backed by an in-memory store (the project uses supertest against the app).
const express = require('express');
const router = express.Router();

let todos = [];
let nextId = 1;

// GET /api/todos  -> 200 with array of todos
router.get('/api/todos', (req, res) => {
  res.status(200).json(todos);
});

// GET /api/todos/:id -> 200 with todo, or 404 if not found
router.get('/api/todos/:id', (req, res) => {
  const todo = todos.find((t) => t.id === Number(req.params.id));
  if (!todo) {
    return res.status(404).json({ error: 'not found' });
  }
  res.status(200).json(todo);
});

// POST /api/todos -> 201 with created todo.
// Body must include a non-empty string "title"; otherwise 400.
router.post('/api/todos', (req, res) => {
  const { title } = req.body || {};
  if (typeof title !== 'string' || title.trim() === '') {
    return res.status(400).json({ error: 'title is required' });
  }
  const todo = { id: nextId++, title: title.trim(), done: false };
  todos.push(todo);
  res.status(201).json(todo);
});

// DELETE /api/todos/:id -> 204 on success, 404 if not found
router.delete('/api/todos/:id', (req, res) => {
  const idx = todos.findIndex((t) => t.id === Number(req.params.id));
  if (idx === -1) {
    return res.status(404).json({ error: 'not found' });
  }
  todos.splice(idx, 1);
  res.status(204).end();
});

// test-only reset helper
function _reset() {
  todos = [];
  nextId = 1;
}

module.exports = { router, _reset };
