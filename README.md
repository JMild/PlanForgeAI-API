# 🧠 PlanForgeAI API (Backend)

ระบบ Backend สำหรับ PlanForge.AI — ใช้ Node.js เชื่อมกับ Python Engine เพื่อสร้างตารางการผลิตอัตโนมัติ

---

## 🚀 วิธีติดตั้งและรันระบบ

### 1️⃣ ติดตั้ง Node.js dependencies
```bash
npm install
```

### 2️⃣ สร้าง Virtual Environment สำหรับ Python
```bash
python -m venv .venv
```

### 3️⃣ เปิดใช้งาน venv 
## Windows
```bash
python -m venv .venv
```
## macOS / Linux
```bash
source .venv/bin/activate
```

### 4️⃣ ติดตั้ง Python packages ที่จำเป็น
```bash
pip install -r requirements.txt
```

### 5️⃣ รันเซิร์ฟเวอร์
```bash
node app.js
```
---
API จะอยู่ที่ 👉 http://localhost:3000
ตรวจสอบว่า AI Router ทำงาน: curl http://localhost:3000/api/ai/ping