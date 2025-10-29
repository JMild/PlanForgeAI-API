const express = require('express');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');
const { randomUUID } = require('crypto');
const axios = require('axios');

module.exports = (db) => {
  const router = express.Router();

  // ===== Paths =====
  const ROOT = path.resolve(__dirname, '..');
  const ENGINE_DIR = path.join(ROOT, 'engine');
  const ENGINE_PY = path.join(ENGINE_DIR, 'engine_bom.py');

  // ===== Utils =====
  const pickPython = () => {
    if (process.env.PYTHON) return process.env.PYTHON;
    return process.platform === 'win32' ? 'python' : 'python3';
  };

  // ===== Health =====
  router.get('/ping', (req, res) => {
    res.json({ ok: true, route: 'ai', msg: 'AI router is alive' });
  });

router.post('/map_fields', async (req, res) => {
  const { internalData, externalFields } = req.body;

  if (!internalData || !externalFields) {
    return res.status(400).json({
      ok: false,
      error: 'missing_input',
      detail: 'internalData and externalFields are required',
    });
  }

  // --- สร้าง prompt สำหรับโมเดล ---
  const prompt = `
คุณมี internal field names:
${JSON.stringify(internalData)}

และ external field names:
${JSON.stringify(externalFields)}

กรุณาสร้าง mapping JSON array ให้ key เป็น external field และ value เป็น internal field ที่ตรงที่สุด
พร้อมเพิ่มความมั่นใจ confidence ระหว่าง 0–1 สำหรับแต่ละ mapping
สำหรับ field ที่ไม่แน่ใจ ให้ map เป็น "__user_choose__"
ตอบ JSON ตรง ๆ เช่น:
[
  { "external": "machineCode", "internal": "machine_code", "confidence": 0.95 },
  { "external": "assignedTo", "internal": "__user_choose__", "confidence": 0.4 }
]
`;

  try {
    const response = await axios.post('http://192.168.11.87:11434/api/generate', {
      model: 'scb10x/typhoon2.1-gemma3-4b',
      prompt,
      stream: false,
    });

    let text = response.data.response || '';
    text = text.replace(/```json|```/g, '').trim();

    let mappedData = [];
    try {
      mappedData = JSON.parse(text);
    } catch (parseErr) {
      console.error('JSON parse error:', parseErr.message, text);
      return res.status(500).json({
        ok: false,
        error: 'invalid_json',
        detail: 'Ollama API returned invalid JSON',
        raw: text,
      });
    }

    // --- กำหนด threshold เพิ่ม safety ---
    const confidenceThreshold = 0.8;
    mappedData = mappedData.map(m => {
      if (m.confidence < confidenceThreshold) {
        return { ...m, internal: "__user_choose__" }; 
      }
      return m;
    });

    res.json({ ok: true, mappedData });
  } catch (err) {
    console.error('Ollama API error:', err.message);
    res.status(500).json({ ok: false, error: 'ollama_error', detail: err.message });
  }
});

  router.get('/diag', (req, res) => {
    res.json({
      ok: true,
      cwd: process.cwd(),
      ROOT,
      ENGINE_PY,
      python_cmd: process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
      engine_exists: fs.existsSync(ENGINE_PY),
    });
  });

  // ===== Core (JSON-only) =====
  router.post("/plan", async (req, res) => {
    const raw = req.body || {};
    const payload = raw.engine_v1 || raw.full || raw;

    const must = ["process_defs", "product_defs", "machines", "calendar"];
    const missing = must.filter((k) => !payload || !payload[k]);
    if (missing.length) {
      return res.status(400).json({
        ok: false,
        error: "bad_input",
        detail: `missing keys: ${missing.join(", ")}`,
        hint: "ส่ง schema ตรง หรือหุ้มด้วย {engine_v1:{...}} / {full:{...}}",
      });
    }

    const day0 = (req.query.day0 || raw.day0 || "2025-09-22").toString();
    const jobId = randomUUID();

    if (!fs.existsSync(ENGINE_PY)) {
      return res
        .status(500)
        .json({ ok: false, error: "engine_not_found", detail: ENGINE_PY });
    }

    try {
      const py = pickPython();

      // ✅ ใช้ stdin อย่างเดียว
      // (ถ้าจะใช้ --input - ก็เปลี่ยนเป็น ["--day0", day0, "--input", "-"] ได้เช่นกัน)
      const args = [ENGINE_PY, "--day0", day0, "--stdin"];

      const proc = spawn(py, args, {
        cwd: path.dirname(ENGINE_PY),
        env: process.env,
        shell: process.platform === "win32",
      });

      let stdout = "";
      let stderr = "";

      const KILL_MS = Number(process.env.AI_PLAN_TIMEOUT_MS || 5 * 60 * 1000);
      const killer = setTimeout(() => {
        try {
          proc.kill("SIGKILL");
        } catch {}
      }, KILL_MS);

      proc.stdout.on("data", (d) => (stdout += d.toString()));
      proc.stderr.on("data", (d) => (stderr += d.toString()));

      proc.on("error", (err) => {
        clearTimeout(killer);
        try {
          proc.kill("SIGKILL");
        } catch {}
        return res.status(500).json({
          ok: false,
          error: "spawn_error",
          detail: String(err),
          hint: "เช็ค PYTHON command / dependency",
        });
      });

      proc.on("close", (code) => {
        clearTimeout(killer);

        if (code !== 0) {
          console.error("engine stderr:\n", stderr);
          return res
            .status(500)
            .json({ ok: false, error: "engine_failed", detail: stderr || stdout });
        }

        let result = null;
        try {
          result = JSON.parse(stdout);
        } catch {
          result = { raw_output: stdout.trim() };
        }

        return res.json({
          ok: true,
          mode: "stdin",
          jobId,
          day0,
          result,
        });
      });

      // ✅ ส่ง payload เข้า stdin แล้วปิด
      proc.stdin.write(JSON.stringify(payload));
      proc.stdin.end();
    } catch (err) {
      console.error(err);
      return res
        .status(500)
        .json({ ok: false, error: "server_error", detail: String(err) });
    }
  });

  return router;
};