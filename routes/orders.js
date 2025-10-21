const express = require('express');

module.exports = (db) => {
  const router = express.Router();

  // Orders
  router.get('/', (req, res) => {
    db.all( `SELECT
      o.*,
      COALESCE(oi.item_count, 0)        AS item_count,
      COALESCE(oa.attachment_count, 0)  AS attachment_count
    FROM "orders" o
    LEFT JOIN (
      SELECT order_no, COUNT(*) AS item_count
      FROM "order_items"
      GROUP BY order_no
    ) oi USING (order_no)
    LEFT JOIN (
      SELECT order_no, COUNT(*) AS attachment_count
      FROM "order_attachments"
      GROUP BY order_no
    ) oa USING (order_no)
    ORDER BY o.order_no;
    `, [], (err, rows) => {
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
  
  router.get('/attachments', (req, res) => {
    const { order_no } = req.query;
    if (!order_no) {
      return res.status(400).json({ error: "Missing order_no query parameter" });
    }
    db.all('SELECT * FROM order_attachments WHERE order_no = ?', [order_no], (err, rows) => {
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
