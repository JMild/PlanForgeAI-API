const express = require('express');

module.exports = (db) => {
  const router = express.Router();

  // downtime_events
  router.get('/downtime_events', (req, res) => {
    db.all('SELECT * FROM downtime_events', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });
 
  // Maintenance
  router.get('/', (req, res) => {
    const data = [
      {
        id: 'PM001',
        machineCode: 'M001',
        machineName: 'CNC Mill 1',
        planType: 'Preventive',
        title: 'Monthly Lubrication & Inspection',
        description: 'Complete lubrication of all moving parts and general inspection',
        frequency: 'Monthly',
        durationMinutes: 120,
        lastExecuted: '2025-09-15',
        nextDue: '2025-10-15',
        status: 'Active',
        priority: 'High',
        assignedTo: 'Maintenance Team A',
        spareParts: ['Lubricant Oil', 'Cleaning Supplies'],
        workCenter: 'WC001',
        checklist: [
          { id: 'c1', task: 'Check oil levels', completed: true },
          { id: 'c2', task: 'Lubricate bearings', completed: true },
          { id: 'c3', task: 'Inspect belts and chains', completed: false },
          { id: 'c4', task: 'Clean coolant system', completed: false },
          { id: 'c5', task: 'Check alignment', completed: false },
        ],
        createdAt: '2025-01-10'
      },
      {
        id: 'PM002',
        machineCode: 'M001',
        machineName: 'CNC Mill 1',
        planType: 'Preventive',
        title: 'Quarterly Deep Maintenance',
        description: 'Comprehensive maintenance including spindle check and calibration',
        frequency: 'Quarterly',
        durationMinutes: 480,
        lastExecuted: '2025-07-01',
        nextDue: '2025-10-01',
        status: 'Active',
        priority: 'Critical',
        assignedTo: 'Senior Technician',
        spareParts: ['Spindle Bearings', 'Seals Kit', 'Filters'],
        workCenter: 'WC001',
        checklist: [
          { id: 'c6', task: 'Spindle inspection', completed: false },
          { id: 'c7', task: 'Replace filters', completed: false },
          { id: 'c8', task: 'Calibrate axes', completed: false },
          { id: 'c9', task: 'Check electrical connections', completed: false },
        ],
        createdAt: '2025-01-10'
      },
      {
        id: 'PM003',
        machineCode: 'M006',
        machineName: 'Assembly Station 1',
        planType: 'Inspection',
        title: 'Weekly Safety Inspection',
        description: 'Safety systems check and emergency stop testing',
        frequency: 'Weekly',
        durationMinutes: 30,
        lastExecuted: '2025-09-25',
        nextDue: '2025-10-02',
        status: 'Active',
        priority: 'Critical',
        assignedTo: 'Safety Officer',
        workCenter: 'WC002',
        checklist: [
          { id: 'c10', task: 'Test emergency stop', completed: false },
          { id: 'c11', task: 'Check safety guards', completed: false },
          { id: 'c12', task: 'Inspect warning labels', completed: false },
        ],
        createdAt: '2025-01-15'
      },
      {
        id: 'PM004',
        machineCode: 'M002',
        machineName: 'CNC Mill 2',
        planType: 'Predictive',
        title: 'Vibration Analysis',
        description: 'Predictive maintenance based on vibration monitoring',
        frequency: 'By Hours',
        frequencyValue: 500,
        durationMinutes: 60,
        lastExecuted: '2025-08-20',
        nextDue: '2025-10-10',
        status: 'Active',
        priority: 'Medium',
        assignedTo: 'Predictive Maintenance Team',
        workCenter: 'WC001',
        createdAt: '2025-01-12'
      },
      {
        id: 'PM005',
        machineCode: 'M008',
        machineName: 'QC Scanner 1',
        planType: 'Calibration',
        title: 'Semi-Annual Calibration',
        description: 'Precision calibration and measurement verification',
        frequency: 'Semi-Annual',
        durationMinutes: 180,
        lastExecuted: '2025-04-01',
        nextDue: '2025-10-01',
        status: 'Active',
        priority: 'Critical',
        assignedTo: 'Calibration Specialist',
        spareParts: ['Calibration Standards', 'Test Pieces'],
        workCenter: 'WC003',
        checklist: [
          { id: 'c13', task: 'Warm-up scanner', completed: false },
          { id: 'c14', task: 'Run calibration routine', completed: false },
          { id: 'c15', task: 'Verify measurements', completed: false },
          { id: 'c16', task: 'Document results', completed: false },
        ],
        createdAt: '2025-01-20'
      },
      {
        id: 'PM006',
        machineCode: 'M004',
        machineName: 'CNC Lathe 2',
        planType: 'Corrective',
        title: 'Chuck Mechanism Repair',
        description: 'Replace worn chuck jaws and alignment',
        frequency: 'Monthly',
        durationMinutes: 240,
        nextDue: '2025-10-05',
        status: 'Active',
        priority: 'High',
        assignedTo: 'Maintenance Team B',
        spareParts: ['Chuck Jaws Set', 'Alignment Tools'],
        workCenter: 'WC001',
        createdAt: '2025-09-01'
      },
    ];
    res.json(data);
  });


  router.get('/plans', (req, res) => {
    db.all('SELECT * FROM maintenance_plans', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  // Maintenance History
  router.get('/history', (req, res) => {
    db.all('SELECT * FROM maintenance_history', [], (err, rows) => {
      if (err) return res.status(500).json({ error: err.message });
      res.json(rows);
    });
  });

  return router;
};
