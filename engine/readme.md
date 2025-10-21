## 💡 **แนวคิดหลัก**

### มีเป้าหมายเพื่อ:

* วางตารางการผลิตสินค้าหลายชนิด (รวมทั้งแบบ Multiline Order)
* หาวิธีจัดการ batch สินค้าให้เหมาะกับทรัพยากร (เครื่องจักร, พนักงาน, เวลาทำงาน)
* ลดค่าใช้จ่ายจากการตั้งเครื่อง (setup), ลดเวลาส่งล่าช้า (tardiness), และลด makespan

---

## 🧠 **สรุปการทำงาน (โครงสร้างใหญ่)**
### 1. **โหลดข้อมูล (`load_data`)**

โหลดข้อมูลจำลอง (`mock.json`) หรือสร้าง sample data ถ้ายังไม่มี

### 2. **เตรียมข้อมูล (pre-processing)**

เช่น:
* ดึงข้อมูลสินค้า / routing / work center / เครื่องจักร
* สร้าง batches จาก orders
* จัดการเวลา setup และ processing ให้อยู่ในหน่วย “นาที”

### 3. **Genetic Algorithm (GA) + Local Search**

ใช้หลักการ GA เพื่อสร้างและพัฒนา “โครโมโซม” ซึ่งคือ batch sequence ที่ต่างกัน:
* **random_chromosome**: shuffle batch เพื่อเริ่มต้น
* **crossover**: ผสมสองโครโมโซม
* **mutate**: สลับตำแหน่ง batch
* **local_search**: ปรับปรุงด้วย Simulated Annealing + Tabu Search

### 4. **Decode**

แปลงโครโมโซมให้กลายเป็น **แผนการผลิตจริง** โดย:
* ตรวจสอบความพร้อมของเครื่องจักร
* ตรวจสอบ operator ถ้าจำเป็น
* เลือกเวลาที่เหมาะสมใน shift windows
* ป้องกันไม่ให้เครื่องทำงานซ้ำซ้อนหรือผิดเวลา

### 5. **Evaluate**

ให้คะแนนโครโมโซมจาก:
* makespan (เวลาทั้งหมดที่ใช้ผลิต)
* tardiness (เวลาที่ผลิตเกินกำหนด)
* setup cost (เวลาตั้งเครื่อง)
* จำนวน batch ที่ถูกข้ามเพราะหาเครื่องไม่ได้ (`skipped`)

### 6. **Output**

* แสดงตารางการผลิต
* แสดงแผนงานแยกตามเครื่อง
* คำนวณ utilization เบื้องต้นของแต่ละเครื่อง

---

## 🧩 **ฟีเจอร์เด่น**

| ฟีเจอร์                                               | รายละเอียด                                         |
| ----------------------------------------------------- | -------------------------------------------------- |
| ✅ รองรับ Multi-line Order                             | Order เดียวมีหลาย product ได้                      |
| ✅ รองรับหน่วยเวลาแบบชั่วโมงและนาที                    | คำนวณอัตโนมัติ                                     |
| ✅ ใช้ Work Center → หาเครื่องใน parallel_machines ได้ |                                                    |
| ✅ ระบบ batch-aware (min/max batch qty)                |                                                    |
| ✅ Matrix-based Setup Time                             | ใช้ state transition matrix เพื่อลดเวลาตั้งเครื่อง |
| ✅ พิจารณา operator availability                       | โดยใช้ shift windows                               |
| ✅ Local Search: Simulated Annealing + Tabu            | ปรับปรุง solution                                  |
| ✅ Output schedule + utilization                       | ดูผลลัพธ์ได้ชัดเจน                                 |

---

## 🔄 **กระบวนการที่ทำซ้ำ**

ในฟังก์ชัน `ga_scheduler`:

* สำหรับแต่ละ generation:

  1. ผสมพ่อแม่ (crossover)
  2. กลายพันธุ์ (mutate)
  3. ใช้ local search ปรับปรุง
  4. ประเมินผล
  5. อัปเดต best solution

---

## 🛠️ **การใช้งาน (สรุป flow)**

```bash
python mock.py
```

จะได้ตารางการผลิตที่ปรับ optimize โดยใช้ GA+SA และแสดงผลทาง console

---

## 📝 ข้อสังเกตเพิ่มเติม

* โค้ดนี้เป็น **scheduling engine ขนาดเล็ก** ที่ยืดหยุ่นและรองรับการตั้งค่าต่าง ๆ ได้ดี
* เหมาะกับการทดลองวางแผนการผลิตหลายรูปแบบ เช่น single-machine, multi-line, multi-product
* ไม่มี GUI หรือไฟล์ output CSV แต่สามารถนำข้อมูลไปแสดงต่อได้ง่าย

---

หากคุณต้องการคำอธิบายเพิ่มเติมในส่วนใด เช่น:

* การปรับแต่ง objective weights
* การเพิ่มกะ (shift) และ break
* การรองรับ machine downtime

สามารถถามเพิ่มเติมได้ครับ!
