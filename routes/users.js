const express = require('express');

module.exports = (db) => {
  const router = express.Router();

  // Users List
  router.get('/', (req, res) => {
    const sql = `
      SELECT 
        u.user_id,
        u.username,
        u.email,
        u.first_name,
        u.last_name,
        u.phone,
        u.department,
        u.role_id,
        u.status,
        u.last_login,
        u.created_date,
        u.updated_date,
        u.notes,
        r.role_name
      FROM users u
      LEFT JOIN roles r ON u.role_id = r.role_id
    `;
    
    db.all(sql, [], (err, rows) => {
      if (err) {
        return res.status(500).json({ error: err.message });
      }
      res.json(rows);
    });
  });

  router.get('/departments', (req, res) => {
    db.all('SELECT DISTINCT department FROM users WHERE department IS NOT NULL', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  
  router.get('/roles', (req, res) => {
    db.all(`SELECT   
        r.*,
        COUNT(u.role_id) AS user_count
        FROM "roles" r
        LEFT JOIN "users" u ON r.role_id = u.role_id
        GROUP BY r.role_id, r.role_name
        ORDER BY user_count DESC;
      `, [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  
  router.get('/all_permission', (req, res) => {
    const sql = `SELECT * FROM view_all_permissions`;

    db.all(sql, [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  router.get('/role_id', (req, res) => {
    const { role_id } = req.query;
    if (!role_id) {
      return res.status(400).json({ error: "Missing role_id query parameter" });
    }
    const sql = `
      SELECT *
      FROM view_role_permissions
      WHERE role_id = ?
      ORDER BY screen_code, permission_name
    `;

    db.all(sql, [role_id], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  return router;
};
