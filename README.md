### 🧠 **PlanForgeAI API (Backend)**

ยินดีต้อนรับสู่ Backend ของ **PlanForge.AI** 🚀\! ระบบนี้สร้างด้วย **Node.js** และทำงานร่วมกับ **Python Engine** เพื่อสร้างตารางการผลิตอัจฉริยะโดยอัตโนมัติ

-----

### 🛠️ **การติดตั้งและเริ่มต้นใช้งาน (Setup & Run)**

ทำตามขั้นตอนต่อไปนี้เพื่อติดตั้งและรันโปรเจกต์บนเครื่องของคุณ

#### **1. ติดตั้ง Dependencies สำหรับ Node.js**

เริ่มต้นด้วยการติดตั้งแพ็กเกจที่จำเป็นทั้งหมดสำหรับฝั่ง Node.js

```bash
npm install
```

#### **2. สร้าง Python Virtual Environment**

เราจะสร้างสภาพแวดล้อมเสมือน (Virtual Environment) เพื่อแยกแพ็กเกจ Python ของโปรเจกต์นี้ออกจากระบบหลัก

```bash
python -m venv .venv
```

#### **3. เปิดใช้งาน Virtual Environment**

เลือกคำสั่งตามระบบปฏิบัติการที่คุณใช้:

  * **Windows (Command Prompt / PowerShell):**
    ```bash
    .\.venv\Scripts\activate
    ```
  * **macOS / Linux:**
    ```bash
    source .venv/bin/activate
    ```

> **💡 Tip:** เมื่อเปิดใช้งานสำเร็จ คุณจะเห็น `(.venv)` นำหน้าชื่อ path ใน Terminal

#### **4. ติดตั้ง Dependencies สำหรับ Python**

ติดตั้งไลบรารี Python ที่จำเป็นทั้งหมดจากไฟล์ `requirements.txt`

```bash
pip install -r requirements.txt
```

#### **5. รันเซิร์ฟเวอร์**

หลังจากติดตั้งทุกอย่างเรียบร้อยแล้ว ให้รันเซิร์ฟเวอร์ Node.js

```bash
node app.js
```

-----

### ✅ **ตรวจสอบสถานะ**

  * **API Server:** เปิดเว็บเบราว์เซอร์แล้วไปที่ 👉 **[http://localhost:3000](https://www.google.com/search?q=http://localhost:3000)**
  * **AI Engine:** ทดสอบการเชื่อมต่อกับ AI Engine ผ่านคำสั่ง `curl` ใน Terminal
    ```bash
    curl http://localhost:3000/api/ai/ping
    ```

หากทุกอย่างทำงานถูกต้อง ระบบจะพร้อมใช้งาน\! ✨
