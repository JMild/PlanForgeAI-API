const express = require('express');

module.exports = (db) => {
  const router = express.Router();

  // Orders
  router.get('/', (req, res) => {
    db.all('SELECT * FROM orders', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // Order Items by order_no query param ?order_no=123
  router.get('/items', (req, res) => {
    const { order_no } = req.query;
    if (!order_no) {
      return res.status(400).json({ error: "Missing order_no query parameter" });
    }
    db.all('SELECT * FROM order_items WHERE order_no = ?', [order_no], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // ====== Job ======
  router.get('/planned_jobs', (req, res) => {
    db.all('SELECT * FROM planned_jobs', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  router.get('/production_jobs', (req, res) => {
    db.all('SELECT * FROM production_jobs', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // ====== Scenario ======
  router.get('/scenario_steps', (req, res) => {
    db.all('SELECT * FROM scenario_steps', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  router.get('/scenario_kpis', (req, res) => {
    db.all('SELECT * FROM scenario_kpis', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  return router;
};
