# merQuery-trading-bot

บอทเทรดอัตโนมัติที่ใช้ AI สำหรับเทรดคู่เงิน XAUUSD (ทองคำ) บนแพลตฟอร์ม MetaTrader5 โดยใช้ Timeframe M15

## 📋 ภาพรวมโปรเจกต์

merQuery-trading-bot เป็นบอทเทรดอัตโนมัติที่ใช้ AI ในการวิเคราะห์ตลาดและตัดสินใจเทรด โดยใช้ตัวบ่งชี้ทางเทคนิค (Technical Indicators) ประกอบด้วย RSI, EMA20 และ ATR14 เพื่อช่วยในการตัดสินใจ

### ✨ คุณสมบัติหลัก

- 🤖 **AI-Powered Trading**: ใช้ AI (DeepSeek หรือ GLM) ในการวิเคราะห์และตัดสินใจเทรด
- ⚡ **Rule-Based Mode**: โหมดตัดสินใจแบบ Rule-based ที่เร็วกว่า 100x และไม่มีค่าใช้จ่าย API
- 📊 **Technical Indicators**: ใช้ตัวบ่งชี้ RSI14, EMA20 และ ATR14
- 🔄 **Trailing Stop**: ระบบ Trailing Stop อัตโนมัติที่ใช้ ATR เป็นฐาน
- ⚡ **Async Architecture**: สถาปัตยกรรมแบบ Asynchronous พร้อมการควบคุม Concurrency
- 🔒 **Thread-Safe**: การเรียก API ของ MT5 ที่ปลอดภัยด้วย Thread Lock
- 💾 **SQLite Logging**: บันทึกประวัติการเทรดลงฐานข้อมูล SQLite
- ⚠️ **Risk Management**: ระบบควบคุมความเสี่ยงด้วย Daily Loss Limit

## 📦 ความต้องการของระบบ (Prerequisites)

- Python 3.8 ขึ้นไป
- MetaTrader5 Terminal
- บัญชี Demo หรือ Live บน MT5 (แนะนำให้ทดสอบบน Demo ก่อน)
- API Key จาก DeepSeek หรือ GLM

## 🚀 การติดตั้ง

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/merQuery-trading-bot.git
cd merQuery-trading-bot
```

### 2. ติดตั้ง Dependencies

```bash
pip install -r requirements.txt
```

### 3. ตั้งค่า Environment Variables

คัดลอกไฟล์ `.env.example` เป็น `.env` และกรอกค่า API Keys:

```bash
copy .env.example .env
```

แก้ไขไฟล์ `.env`:

```env
DEEPSEEK_API_KEY=your_deepseek_key_here
GLM_API_KEY=your_glm_key_here

# Decision Mode: "AI" หรือ "RULE_BASED"
# RULE_BASED เร็วกว่า 100x, ประหยัดค่า API, และเสถียรกว่า
DECISION_MODE=AI

# Active AI Provider: "DEEPSEEK" หรือ "GLM" (ใช้เมื่อ DECISION_MODE=AI)
ACTIVE_AI=GLM

MAX_DAILY_LOSS_USD=100.0
MAGIC_NUMBER=100100
TRAILING_MIN_PROFIT_ATR=0.5
TRAILING_DISTANCE_ATR=0.4
BAR_WATCHER_POLL_S=1.0
TRAILING_INTERVAL_S=15.0
```

## ⚙️ การตั้งค่า (Configuration)

### ตัวแปรหลักในไฟล์ `.env`

| ตัวแปร | คำอธิบาย | ค่าเริ่มต้น |
|--------|----------|-------------|
| `DECISION_MODE` | โหมดการตัดสินใจ (AI หรือ RULE_BASED) | AI |
| `ACTIVE_AI` | ระบุ AI ที่จะใช้ (DEEPSEEK หรือ GLM) | GLM |
| `DEEPSEEK_API_KEY` | API Key สำหรับ DeepSeek | - |
| `GLM_API_KEY` | API Key สำหรับ GLM | - |
| `MAX_DAILY_LOSS_USD` | ขีดจำกัดการขาดทุนต่อวัน (USD) | 100.0 |
| `MAGIC_NUMBER` | Magic Number สำหรับระบุออเดอร์ของบอท | 100100 |
| `TRAILING_MIN_PROFIT_ATR` | กำไรขั้นต่ำก่อนเริ่ม Trailing (ATR) | 0.5 |
| `TRAILING_DISTANCE_ATR` | ระยะห่าง Trailing Stop (ATR) | 0.4 |
| `BAR_WATCHER_POLL_S` | ช่วงเวลาตรวจสอบแท่งเทียน (วินาที) | 1.0 |
| `TRAILING_INTERVAL_S` | ช่วงเวลาอัปเดต Trailing Stop (วินาที) | 15.0 |

### โหมดการตัดสินใจ (Decision Mode)

บอทรองรับ 2 โหมดการตัดสินใจ:

#### AI Mode (ค่าเริ่มต้น)
- ใช้ LLM (DeepSeek หรือ GLM) ในการวิเคราะห์ตลาด
- มีค่าใช้จ่าย API
- ใช้เวลา ~1-5 วินาทีต่อการวิเคราะห์
- เหมาะสำหรับการทดลองและการพัฒนา

#### Rule-Based Mode
- ใช้กฎที่กำหนดไว้ล่วงหน้า (RSI + EMA20)
- ไม่มีค่าใช้จ่าย API
- ใช้เวลา < 1 มิลลิวินาที
- เสถียรและน่าเชื่อถือกว่า
- เหมาะสำหรับ Production ที่ใช้เงินจริง

**วิธีเปลี่ยนโหมด:**
```env
# ใช้ AI Mode
DECISION_MODE=AI

# ใช้ Rule-Based Mode (แนะนำสำหรับ Production)
DECISION_MODE=RULE_BASED
```

### การตั้งค่าใน `src/config.py`

```python
SYMBOL = "XAUUSD"        # คู่เงินที่จะเทรด
LOT_SIZE = 0.01          # ขนาดล็อต
MAX_SL_POINTS = 500      # ระยะห่าง Stop Loss สูงสุด (points)
DB_NAME = "trading_bot.db"  # ชื่อฐานข้อมูล
```

### โครงสร้างโปรเจกต์

```
src/
├── __init__.py          # Python package
├── config.py            # Configuration, constants, logging
├── database.py          # Database operations
├── mt5_client.py        # MT5 API wrappers (รวม mt5_lock)
├── analysis.py          # Market data & AI decision
├── execution.py         # Trade execution & trailing stop
└── bot.py               # Bot routine & workers
main.py                  # Entry point (main_async, semaphore, signal handler)
```

## 🎯 การใช้งาน

### เริ่มต้นบอท

```bash
python main.py
```

### การทำงานของบอท

1. **Bar Watcher**: ตรวจสอบแท่งเทียน M15 ทุก 1 วินาที
2. **เมื่อแท่งเทียนปิด**: บอทจะวิเคราะห์ข้อมูลตลาด
3. **Decision Making**:
   - **AI Mode**: ส่งข้อมูลตลาดให้ AI วิเคราะห์ (~1-5 วินาที)
   - **Rule-Based Mode**: ใช้กฎ RSI + EMA20 ในการตัดสินใจ (< 1 มิลลิวินาที)
4. **Trade Execution**: ดำเนินการเทรดตามคำสั่ง
5. **Trailing Stop**: ปรับ Stop Loss อัตโนมัติทุก 2 วินาที

### การหยุดบอท

กด `Ctrl + C` เพื่อหยุดบอทอย่างปลอดภัย

## 🏗️ สถาปัตยกรรมระบบ

```mermaid
graph TB
    A[main.py] -->|Initialize| B[trading_semaphore]
    A -->|Start Workers| C[bar_watcher_worker]
    A -->|Start Workers| D[trailing_stop_worker]
    C -->|New M15 Bar| E[get_market_data]
    E --> F{DECISION_MODE?}
    F -->|AI| G[get_ai_decision]
    F -->|RULE_BASED| H[get_rule_based_decision]
    G --> I[bot_routine]
    H --> I
    I --> J[execute_trade]
    J --> K[log_trade]
    D --> L[apply_trailing_stop_sync]
    M[mt5_client.py] -->|mt5_lock| E
    M -->|mt5_lock| J
    M -->|mt5_lock| L
    N[database.py] --> K
    O[config.py] -->|Constants| E
    O -->|Constants| L
    O -->|Logger| C
    O -->|Logger| D
    P[analysis.py] --> E
    P --> G
    P --> H
    Q[execution.py] --> J
    Q --> L
    R[bot.py] --> C
    R --> D
```

### คอมโพเนนต์หลัก

- **[`src/config.py`](src/config.py)**: จัดการ configuration, constants ทั้งหมด และ logging setup
- **[`src/database.py`](src/database.py)**: ฟังก์ชันจัดการฐานข้อมูล SQLite
- **[`src/mt5_client.py`](src/mt5_client.py)**: MT5 API wrappers และ `mt5_lock` สำหรับ thread-safe operations
- **[`src/analysis.py`](src/analysis.py)**: ดึงข้อมูลตลาด, ตัดสินใจด้วย AI (DeepSeek หรือ GLM), และ Rule-based decision
- **[`src/execution.py`](src/execution.py)**: ดำเนินการเทรดและ trailing stop
- **[`src/bot.py`](src/bot.py)**: Bot routine และ async workers (bar_watcher_worker, trailing_stop_worker)
- **[`main.py`](main.py)**: Entry point ที่จัดการ lifecycle ของบอท

## 📊 ตัวบ่งชี้ทางเทคนิค

### RSI14 (Relative Strength Index)
- ใช้ระบุสภาพ Overbought (>70) และ Oversold (<30)
- สัญญาณซื้อ: RSI ต่ำกว่า 30 และเริ่มเด้งกลับขึ้น
- สัญญาณขาย: RSI สูงกว่า 70 และเริ่มลดลง

### EMA20 (Exponential Moving Average)
- ใช้ระบุแนวโน้มราคา
- ราคาเหนือ EMA20 = แนวโน้มขาขึ้น
- ราคาต่ำกว่า EMA20 = แนวโน้มขาลง

### ATR14 (Average True Range)
- ใช้วัดความผันผวนของตลาด
- ใช้คำนวณระยะ Stop Loss และ Trailing Stop

## 🎨 กลยุทธ์การเทรด

### เงื่อนไขการเทรด

**สัญญาณ BUY**:
- RSI อยู่ในสภาพ Oversold (<30) และเริ่มเด้งกลับขึ้น
- ราคาเหนือ EMA20 หรือกำลังข้ามขึ้น

**สัญญาณ SELL**:
- RSI อยู่ในสภาพ Overbought (>70) และเริ่มลดลง
- ราคาต่ำกว่า EMA20 หรือกำลังข้ามลง

**HOLD**:
- ไม่มีสัญญาณชัดเจน
- มีออเดอร์เปิดอยู่แล้ว

### การจัดการความเสี่ยง

- **Stop Loss**: คำนวณจาก ATR × 1.5 (สูงสุด 500 points)
- **Take Profit**: Risk:Reward = 1:1.5
- **Trailing Stop**: เริ่มเมื่อกำไร ≥ 0.5 ATR
- **Daily Loss Limit**: หยุดเทรดเมื่อขาดทุนถึงขีดจำกัด

## 🔧 การปรับปรุงล่าสุด (Recent Improvements)

บอทได้รับการปรับปรุงเพื่อแก้ไขปัญหาที่พบในการรีวิวโค้ด Production:

### 1. แก้ไข Daily PnL Bug
- **ปัญหา**: ระบบคำนวณ PnL รวมทุก trades ไม่ว่าจะมาจากบอทนี้หรือไม่
- **วิธีแก้**: เพิ่มการกรองด้วย `MAGIC_NUMBER` และ `comment` เพื่อนับเฉพาะ trades ของบอทนี้
- **ผลกระทบ**: ป้องกันบอทหยุดทำงานผิดพลาดเมื่อมีบอทอื่นหรือเทรดมือรวมอยู่

### 2. แก้ไข Concurrency Bottleneck
- **ปัญหา**: AI API call อยู่ใต้ semaphore ทำให้ trailing stop ถูก block ระหว่างรอ AI
- **วิธีแก้**: ย้าย AI call ออกจาก semaphore ให้ trailing stop ทำงานได้ตลอด
- **ผลกระทบ**: ไม่เสียโอกาส lock profit ระหว่างรอ AI ตอบกลับ

### 3. เพิ่ม Hysteresis สำหรับ Trailing Stop
- **ปัญหา**: Hysteresis เล็กเกินไป (0.005 USD) ทำให้ spam broker
- **วิธีแก้**: เพิ่มเป็น 10 pips (0.10 USD สำหรับ XAUUSD)
- **ผลกระทบ**: ลดจำนวน Modify SL requests ลงอย่างมาก ปลอดภัยจากการโดนแบน

### 4. ปรับปรุง AI Parser
- **ปัญหา**: ใช้ simple replace ง่ายๆ พังเมื่อ AI ตอบผิด format
- **วิธีแก้**: ใช้ regex พร้อม fallback mechanism ที่ robust กว่า
- **ผลกระทบ**: รองรับ AI response ที่หลากหลาย format มากขึ้น

### 5. เพิ่ม Rule-Based Decision Mode
- **ปัญหา**: AI mode ช้าและมีค่าใช้จ่าย API
- **วิธีแก้**: เพิ่ม Rule-based mode ที่เร็วกว่า 100x และไม่มีค่าใช้จ่าย
- **ผลกระทบ**: มีตัวเลือกที่เหมาะสำหรับ Production ที่ใช้เงินจริง

### เงื่อนไขการเทรด

**สัญญาณ BUY**:
- RSI อยู่ในสภาพ Oversold (<30) และเริ่มเด้งกลับขึ้น
- ราคาเหนือ EMA20 หรือกำลังข้ามขึ้น

**สัญญาณ SELL**:
- RSI อยู่ในสภาพ Overbought (>70) และเริ่มลดลง
- ราคาต่ำกว่า EMA20 หรือกำลังข้ามลง

**HOLD**:
- ไม่มีสัญญาณชัดเจน
- มีออเดอร์เปิดอยู่แล้ว

### การจัดการความเสี่ยง

- **Stop Loss**: คำนวณจาก ATR × 1.5 (สูงสุด 500 points)
- **Take Profit**: Risk:Reward = 1:1.5
- **Trailing Stop**: เริ่มเมื่อกำไร ≥ 0.5 ATR
- **Daily Loss Limit**: หยุดเทรดเมื่อขาดทุนถึงขีดจำกัด

## 📝 การบันทึกข้อมูล (Logging)

บอทจะบันทึกข้อมูลลงไฟล์ `bot.log` และฐานข้อมูล `trading_bot.db`

### โครงสร้างฐานข้อมูล

```sql
CREATE TABLE trade_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME,
    symbol TEXT,
    action TEXT,
    price REAL,
    sl REAL,
    tp REAL,
    ai_reason TEXT
)
```

## ⚠️ คำเตือนสำคัญ

- ⚠️ **ทดสอบบนบัญชี Demo ก่อน**: อย่าเทรดด้วยเงินจริงโดยไม่ได้ทดสอบก่อน
- ⚠️ **ความเสี่ยงในการเทรด**: การเทรดมีความเสี่ยงสูง อาจสูญเสียเงินทุนได้ทั้งหมด
- ⚠️ **ไม่รับประกันผลกำไร**: บอทนี้ไม่รับประกันว่าจะทำกำไรได้
- ⚠️ **ตรวจสอบ MT5 Build**: ยืนยันรูปแบบ API ของ MT5 กับโบรกเกอร์ของคุณ
- ⚠️ **ติดตามบอท**: ควรติดตามการทำงานของบอทอย่างสม่ำเสมอ

## 🛠️ การแก้ปัญหา (Troubleshooting)

### MT5 ไม่เชื่อมต่อ
- ตรวจสอบว่า MT5 Terminal ทำงานอยู่
- ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต
- ลองรีสตาร์ท MT5 Terminal

### AI API ผิดพลาด
- ตรวจสอบ API Key ในไฟล์ `.env`
- ตรวจสอบว่า API Key ยังใช้งานได้
- ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต

### ไม่มีการเทรด
- ตรวจสอบว่ามีเงินทุนเพียงพอ
- ตรวจสอบว่าไม่มีออเดอร์เปิดอยู่
- ตรวจสอบ Daily Loss Limit
- ตรวจสอบ Log ใน `bot.log`

## 📄 License

โปรเจกต์นี้ใช้ License ตามที่ระบุในไฟล์ [LICENSE](LICENSE)

## 🤝 การมีส่วนร่วม (Contributing)

การมีส่วนร่วมและข้อเสนอแนะเป็นที่ยินดี โปรดสร้าง Pull Request หรือ Issue

## 📧 ติดต่อ

หากมีข้อสงสัยหรือต้องการติดต่อ สามารถสร้าง Issue ใน Repository ได้

---

**ข้อควรจำ**: การเทรดมีความเสี่ยง ควรศึกษาและทำความเข้าใจก่อนลงทุน
