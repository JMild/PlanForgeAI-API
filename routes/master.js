const express = require('express');
const _ = require('lodash');
const dayjs = require('dayjs');
const axios = require('axios');

function toCamelCase(obj) {
  const result = {};
  for (const key in obj) {
    const camelKey = key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
    result[camelKey] = obj[key];
  }
  return result;
}

module.exports = (db) => {
  const router = express.Router();

  // ====== Machines ======
  // router.get('/machines', async (req, res) => {
  //   try {
  //     const sql = `
  //       SELECT i.baseUrl, e.path, e.method, e.mapping
  //       FROM integrations i
  //       JOIN integration_endpoints e ON i.id = e.integration_id
  //       WHERE i.type = 'MES' AND e.key = 'machines'
  //     `;

  //     db.get(sql, [], async (err, row) => {
  //       if (err || !row) {
  //         return res.status(500).json({ success: false, data: [], error: 'Integration not found' });
  //       }

  //       const url = `${row.baseUrl}${row.path}`;
  //       let responseData = [];
  //       let success = true;

  //       try {
  //         const response = await axios.get(url, { timeout: 5000 });
  //         responseData = response.data.data;
  //       } catch (err) {
  //         console.warn('MES API not available, returning failure');
  //         success = false;
  //         responseData = [];
  //       }

  //       const mapping = JSON.parse(row.mapping);
  //       const data = responseData.map(item => {
  //         const mappedItem = {};
  //         mapping.forEach(m => {
  //           mappedItem[m.internalField] = item[m.externalField];
  //         });
  //         return mappedItem;
  //       });

  //       res.json({ success, data });
  //     });

  //   } catch (error) {
  //     // console.error(error);
  //     res.status(500).json({ success: false, data: [], error: 'Failed to fetch machines' });
  //   }
  // });

  router.get('/machines', (req, res) => {
    db.all('SELECT * FROM machines', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      const data = rows.map(row => toCamelCase(row));
      res.json(data);
    });
  });

  router.get('/machines-dropdown', (req, res) => {
    db.all('SELECT machine_code, machine_name FROM machines', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  router.get('/customers-dropdown', (req, res) => {
    db.all('SELECT customer_code, customer_name FROM customers', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  router.get('/machines_processes', (req, res) => {
    db.all('SELECT * FROM machines_processes', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  router.get('/machines_history', (req, res) => {
    db.all('SELECT * FROM machines_processes', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // ====== Products ======
  router.get('/products', (req, res) => {
    const sql = `
      SELECT 
        p.*, 
        COUNT(r.routing_step_id) AS count_step_routing 
      FROM products p 
      LEFT JOIN routing_steps r ON p.routing_id = r.routing_id 
      GROUP BY p.product_code
    `;

    db.all(sql, [], (err, rows) => {
      if (err) {
        return res.status(500).json({ error: err.message });
      }
      res.json(rows);
    });
  });

  router.get('/product-dropdown', (req, res) => {
    db.all('SELECT product_code, product_name FROM products', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

   // ====== BOM ======
  router.get('/bom', (req, res) => {
    db.all('SELECT * FROM bom_header h LEFT JOIN bom_line l ON h.bom_id = l.bom_id', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  router.get('/bom_id', (req, res) => {
    const { bom_id } = req.query;
    if (!bom_id) {
      return res.status(400).json({ error: "Missing bom_id query parameter" });
    }
    db.all('SELECT * FROM bom_lines WHERE bom_id = ?', [bom_id], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  })

  // ====== Customers ======
  router.get('/customers', (req, res) => {
    db.all('SELECT * FROM customers', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  router.get('/customers-dropdown', (req, res) => {
    db.all('SELECT customer_code, customer_name FROM customers', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // ====== Material ======
  router.get('/materials', (req, res) => {
    db.all('SELECT * FROM materials', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // ====== Work Centers ======
  router.get('/work_centers', (req, res) => {
    db.all(`SELECT 
        w.work_center_code,
        w.work_center_name,
        w.department,
        w.description,
        w.status,
        w.created_date,
        COUNT(m.machine_code) AS machine_count
      FROM work_centers w
      LEFT JOIN machines m ON w.work_center_code = m.work_center_code
      GROUP BY 
        w.work_center_code,
        w.work_center_name,
        w.department,
        w.description,
        w.status,
        w.created_date;
    `, [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  
  // ====== Products ======
  router.get('/materials', (req, res) => {
    db.all('SELECT * FROM materials', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  
  // ====== Routing ======
  router.get('/routings', (req, res) => {
    const sql = `
      SELECT 
        h.routing_id,
        h.routing_name,
        h.description,
        h.status,
        COUNT(d.routing_step_id) AS step_count,
        COALESCE(SUM(d.setup_time_min + d.run_time_per_unit), 0) AS total_minutes
      FROM routing_header h
      LEFT JOIN routing_steps d ON h.routing_id = d.routing_id
      GROUP BY 
        h.routing_id,
        h.routing_name,
        h.description,
        h.status
    `;

    db.all(sql, [], (err, rows) => {
      if (err) {
        return res.status(500).json({ error: err.message });
      }
      res.json(rows);
    });
  });

  router.get('/routing_step', (req, res) => {
    const { routing_id } = req.query;
    if (!routing_id) {
      return res.status(400).json({ error: "Missing routing_id query parameter" });
    }
    db.all('SELECT * FROM routing_steps WHERE routing_id = ?', [routing_id], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // ====== Personnel ======
  router.get('/personnel', (req, res) => {
    db.all('SELECT * FROM personnel', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
  
  // ====== Skill ======
  router.get('/skill_matrix', (req, res) => {
    db.all('SELECT * FROM skill_matrix', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // ====== Suppliers ======
  router.get('/suppliers', (req, res) => {
    db.all('SELECT * FROM suppliers', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // ====== Calendar ======
  router.get("/calendars_full", (req, res) => {
    const queries = {
      calendars: "SELECT * FROM calendars",
      holidays: "SELECT * FROM calendar_holidays",
      shifts: "SELECT * FROM calendar_shifts",
      breaks: "SELECT * FROM calendar_shift_breaks",
      workingDays: "SELECT * FROM calendar_working_days"
    };

    const results = {};

    Promise.all(
      Object.entries(queries).map(([key, sql]) => {
        return new Promise((resolve, reject) => {
          db.all(sql, [], (err, rows) => {
            if (err) reject(err);
            else {
              results[key] = rows;
              resolve();
            }
          });
        });
      })
    )
      .then(() => {
        const combined = results.calendars.map(cal => {
          const calendar_id = cal.calendar_id;

          return {
            ...cal,
            working_days: results.workingDays
              .filter(w => w.calendar_id === calendar_id)
              .map(w => w.day_of_week),
            holidays: results.holidays
              .filter(h => h.calendar_id === calendar_id)
              .map(h => ({
                holiday_date: h.holiday_date,
                holiday_name: h.holiday_name
              })),
            shifts: results.shifts
              .filter(s => s.calendar_id === calendar_id)
              .map(s => ({
                shift_id: s.shift_id,
                shift_name: s.shift_name,
                start_time: s.start_time,
                end_time: s.end_time,
                breaks: results.breaks
                  .filter(b => b.shift_id === s.shift_id)
                  .map(b => ({
                    break_name: b.break_name,
                    start_time: b.start_time,
                    end_time: b.end_time
                  }))
              }))
          };
        });

        res.json(combined);
      })
      .catch(err => res.status(500).json({ error: err.message }));
  });

  router.post("/calendars_full", (req, res) => {
    const { calendar_id, calendar_name, description, status, working_days, holidays, shifts } = req.body;

    db.run(
      `INSERT INTO calendars (calendar_id, calendar_name, description, status, created_date)
      VALUES (?, ?, ?, ?, datetime('now'))`,
      [calendar_id, calendar_name, description, status],
      err => {
        if (err) return res.status(500).json({ error: err.message });

        // เพิ่ม working_days
        working_days?.forEach(day => {
          db.run(`INSERT INTO calendar_working_days (calendar_id, day_of_week) VALUES (?, ?)`, [
            calendar_id,
            day
          ]);
        });

        // เพิ่ม holidays
        holidays?.forEach(h => {
          db.run(
            `INSERT INTO calendar_holidays (calendar_id, holiday_date, holiday_name)
            VALUES (?, ?, ?)`,
            [calendar_id, h.holiday_date, h.holiday_name]
          );
        });

        // เพิ่ม shifts และ breaks
        shifts?.forEach(shift => {
          db.run(
            `INSERT INTO calendar_shifts (calendar_id, shift_name, start_time, end_time)
            VALUES (?, ?, ?, ?)`,
            [calendar_id, shift.shift_name, shift.start_time, shift.end_time],
            function (err2) {
              if (!err2 && shift.breaks) {
                const shift_id = this.lastID;
                shift.breaks.forEach(br => {
                  db.run(
                    `INSERT INTO calendar_shift_breaks (shift_id, break_name, start_time, end_time)
                    VALUES (?, ?, ?, ?)`,
                    [shift_id, br.break_name, br.start_time, br.end_time]
                  );
                });
              }
            }
          );
        });

        res.json({ message: "Calendar created successfully" });
      }
    );
  });

  router.put("/calendars_full/:calendar_id", (req, res) => {
    const { calendar_id } = req.params;
    const { calendar_name, description, status, working_days, holidays, shifts } = req.body;

    db.run(
      `UPDATE calendars SET calendar_name=?, description=?, status=? WHERE calendar_id=?`,
      [calendar_name, description, status, calendar_id],
      err => {
        if (err) return res.status(500).json({ error: err.message });

        // ลบของเก่าออกก่อน
        db.run(`DELETE FROM calendar_working_days WHERE calendar_id=?`, [calendar_id]);
        db.run(`DELETE FROM calendar_holidays WHERE calendar_id=?`, [calendar_id]);
        db.run(
          `DELETE FROM calendar_shift_breaks WHERE shift_id IN (SELECT shift_id FROM calendar_shifts WHERE calendar_id=?)`,
          [calendar_id]
        );
        db.run(`DELETE FROM calendar_shifts WHERE calendar_id=?`, [calendar_id]);

        // เพิ่มข้อมูลใหม่
        working_days?.forEach(day =>
          db.run(`INSERT INTO calendar_working_days (calendar_id, day_of_week) VALUES (?, ?)`, [
            calendar_id,
            day
          ])
        );

        holidays?.forEach(h =>
          db.run(
            `INSERT INTO calendar_holidays (calendar_id, holiday_date, holiday_name)
            VALUES (?, ?, ?)`,
            [calendar_id, h.holiday_date, h.holiday_name]
          )
        );

        shifts?.forEach(shift => {
          db.run(
            `INSERT INTO calendar_shifts (calendar_id, shift_name, start_time, end_time)
            VALUES (?, ?, ?, ?)`,
            [calendar_id, shift.shift_name, shift.start_time, shift.end_time],
            function (err2) {
              if (!err2 && shift.breaks) {
                const shift_id = this.lastID;
                shift.breaks.forEach(br => {
                  db.run(
                    `INSERT INTO calendar_shift_breaks (shift_id, break_name, start_time, end_time)
                    VALUES (?, ?, ?, ?)`,
                    [shift_id, br.break_name, br.start_time, br.end_time]
                  );
                });
              }
            }
          );
        });

        res.json({ message: "Calendar updated successfully" });
      }
    );
  });

  router.delete("/calendars_full/:calendar_id", (req, res) => {
    const { calendar_id } = req.params;

    db.run(
      `DELETE FROM calendar_shift_breaks WHERE shift_id IN (SELECT shift_id FROM calendar_shifts WHERE calendar_id=?)`,
      [calendar_id]
    );
    db.run(`DELETE FROM calendar_shifts WHERE calendar_id=?`, [calendar_id]);
    db.run(`DELETE FROM calendar_holidays WHERE calendar_id=?`, [calendar_id]);
    db.run(`DELETE FROM calendar_working_days WHERE calendar_id=?`, [calendar_id]);
    db.run(`DELETE FROM calendars WHERE calendar_id=?`, [calendar_id], err => {
      if (err) return res.status(500).json({ error: err.message });
      res.json({ message: "Calendar deleted successfully" });
    });
  });

  // ====== Processes =====
  router.get('/processes', (req, res) => {
    db.all('SELECT * FROM processes', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  router.get('/work_centers-dropdown', (req, res) => {
    const sql = `
      SELECT 
        w.work_center_code AS code,
        w.work_center_name AS name,
        m.machine_code AS machine_code,
        m.machine_name AS machine_name
      FROM work_centers w
      LEFT JOIN machines m ON w.work_center_code = m.work_center_code
    `;

    db.all(sql, [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });

      const result = [];
      const map = new Map();

      for (const row of rows) {
        if (!map.has(row.code)) {
          map.set(row.code, {
            code: row.code,
            name: row.name,
            machines: row.machine_code
              ? [{ code: row.machine_code, name: row.machine_name }]
              : []
          });
          result.push(map.get(row.code));
        } else {
          if (row.machine_code) {
            map.get(row.code).machines.push({
              code: row.machine_code,
              name: row.machine_name
            });
          }
        }
      }

      res.json(result);
    });
  });  

  return router;

};
