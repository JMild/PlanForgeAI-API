const express = require('express');

module.exports = (db) => {
  const router = express.Router();

  // Dropdown - machineStatus
  router.get('/enum_values/machine-status', (req, res) => {
    db.all(
      'SELECT * FROM enum_values WHERE type = ? AND is_active = 1 ORDER BY sort_order',
      ['MACHINE_STATUS'],
      (err, rows) => {
        if (err) return res.status(500).json({ error: err.message });
        res.json(rows);
      }
    );
  });
  
  // Dropdown - unit
  router.get('/enum_values/unit', (req, res) => {
    db.all(
      'SELECT code, label FROM enum_values WHERE type = ? AND is_active = 1 ORDER BY sort_order',
      ['UNIT'],
      (err, rows) => {
        if (err) return res.status(500).json({ error: err.message });
        res.json(rows);
      }
    );
  });

  // Dropdown - productCategory
  router.get('/enum_values/product-category', (req, res) => {
    db.all(
      'SELECT code, label FROM enum_values WHERE type = ? AND is_active = 1 ORDER BY sort_order',
      ['PRODUCT_CATEGORY'],
      (err, rows) => {
        if (err) return res.status(500).json({ error: err.message });
        res.json(rows);
      }
    );
  });

  // Dropdown - all MATERIAL enums combined
  router.get('/enum_values/all-material', (req, res) => {
    const types = ['UNIT', 'MATERIAL_CATEGORY', 'MATERIAL_STATUS'];
    const result = {};

    const loadNext = (index) => {
      // เมื่อดึง enums ครบแล้ว → ดึง suppliers ต่อ
      if (index >= types.length) {
        db.all(
          "SELECT supplier_code, supplier_name FROM suppliers WHERE status = 'Active' ORDER BY supplier_name",
          [],
          (err, suppliers) => {
            if (err) return res.status(500).json({ error: err.message });
            result['SUPPLIERS'] = suppliers;
            res.json(result);
          }
        );
        return;
      }

      // ดึง enums ทีละ type
      db.all(
        'SELECT * FROM enum_values WHERE type = ? AND is_active = 1 ORDER BY sort_order',
        [types[index]],
        (err, rows) => {
          if (err) return res.status(500).json({ error: err.message });
          result[types[index]] = rows;
          loadNext(index + 1);
        }
      );
    };

    loadNext(0);
  });

  // Audit
  router.get('/audit', (req, res) => {
    db.all('SELECT * FROM audit_log', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // ====== intergrations ======
  
  // GET /integrations?type=MES&endpoint=machines
  router.get("/integrations", (req, res) => {
    const { type, endpoint } = req.query;

    let sql = `
      SELECT i.id as integration_id, i.name as integration_name, i.type as integration_type, i.status, 
            i.last_sync, i.health_status, i.created_date, i.updated_date,
            e.id as endpoint_id, e.key as endpoint_key, e.path as endpoint_path, e.method as endpoint_method, e.mapping
      FROM integrations i
      LEFT JOIN integration_endpoints e ON i.id = e.integration_id
    `;
    
    const conditions = [];
    const params = [];

    if (type) {
      conditions.push("i.type = ?");
      params.push(type);
    }

    if (endpoint) {
      conditions.push("e.key = ?");
      params.push(endpoint);
    }

    if (conditions.length > 0) {
      sql += " WHERE " + conditions.join(" AND ");
    }

    sql += " ORDER BY i.created_date DESC";

    db.all(sql, params, (err, rows) => {
      if (err) {
        console.error("❌ Error fetching integrations:", err.message);
        return res.status(500).json({ error: "Failed to fetch integrations." });
      }

      const integrationsMap = {};
      rows.forEach(row => {
        if (!integrationsMap[row.integration_id]) {
          integrationsMap[row.integration_id] = {
            integration_id: row.integration_id,
            integration_name: row.integration_name,
            integration_type: row.integration_type,
            status: row.status,
            last_sync: row.last_sync,
            health_status: row.health_status,
            created_date: row.created_date,
            updated_date: row.updated_date,
            endpoints: []
          };
        }

        if (row.endpoint_id) {
          integrationsMap[row.integration_id].endpoints.push({
            key: row.endpoint_key,
            path: row.endpoint_path,
            method: row.endpoint_method,
            mapping: row.mapping ? JSON.parse(row.mapping) : []
          });
        }
      });

      const data = Object.values(integrationsMap);

      res.json({
        success: true,
        count: data.length,
        data
      });
    });
  });

  return router;
  
};
