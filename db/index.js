const sqlite3 = require('sqlite3').verbose();

const db = new sqlite3.Database('./production_planning.db', (err) => {
  if (err) {
    console.error('❌ Error connecting to database:', err.message);
  } else {
    console.log('✅ Connected to SQLite database');
  }
});

module.exports = db;
