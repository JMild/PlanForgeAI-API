// app.js (มีของคุณอยู่แล้ว ด้านล่างคือสิ่งสำคัญที่ต้องมี)
const express = require('express');
const sqlite3 = require('sqlite3').verbose();
const bodyParser = require('body-parser');
const cors = require('cors');
const path = require('path');

const app = express();
const PORT = 4001;

app.use(cors());
app.use(bodyParser.json());

// SQLite
const db = new sqlite3.Database('./production_planning.db', (err) => {
  if (err) return console.error(err.message);
  console.log('Connected to the SQLite database.');
});

// Routers
const masterRouter = require('./routes/master')(db);
const ordersRouter = require('./routes/orders')(db);
const maintenanceRouter = require('./routes/maintenance')(db);
const usersRouter = require('./routes/users')(db);
const configRouter = require('./routes')(db);
const aiRouter = require('./routes/ai')(db);

// Mount
app.use('/api/master', masterRouter);
app.use('/api/orders', ordersRouter);
app.use('/api/maintenance', maintenanceRouter);
app.use('/api/users', usersRouter);
app.use('/api', configRouter);
app.use('/api/ai', aiRouter);

// (ออปชัน) ให้โหลดไฟล์จากโฟลเดอร์ tmp ได้ตรงๆ ด้วย
app.use('/files', express.static(path.join(__dirname, 'tmp')));

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
  console.log(`POST http://localhost:${PORT}/api/ai/plan`);
});
