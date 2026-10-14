# HULK GYM — Smart Fitness Management System 🏋️‍♂️

An integrated fitness center management platform combining a **PySide6 desktop management suite** with an **autonomous ESP32 biometric access control terminal**.

---

## 🚀 Key Features

### 🖥️ Desktop Management Software (`soft/`)
- **Member Management**: Flexible plans, subscriptions, renewals, frozen periods, and debt tracking.
- **Financial Accounting**: Invoices, receipts, expense categories, revenue reports, and safe balance.
- **WhatsApp Automation**: Automated messaging for receipts, renewals, end-of-subscription alerts, and custom campaigns via PyAutoGUI.
- **Google Contacts Sync**: Background batched queue synchronization for member contact details.
- **Biometric Integration**: Real-time bi-directional sync with the ESP32 access control terminal.

### ⚡ Biometric Access Control Hardware (`hard/`)
- **ESP32 Microcontroller**: Runs an embedded HTTP REST server for standalone access control.
- **Optical Fingerprint Sensor (R307)**: Enrolls, identifies, and validates member access against an internal LittleFS database.
- **TFT Display (320x480)**: Visual feedback with custom UI showing member status, expiration dates, and remaining sessions.
- **Audio & Visual Indicators**: DFPlayer Mini for audio cues and RGB LED for entry status.

---

## 📂 Repository Structure

```text
├── hard/                # ESP32 C++ firmware (last.ino) & LittleFS assets
├── soft/                # PySide6 desktop application, tests, and configuration
│   ├── app.py           # Core application & Store architecture
│   ├── esp_client.py    # ESP32 REST API client
│   ├── whatsapp_sender.py # WhatsApp Web automation
│   ├── tests/           # Unit test suite
│   └── requirements.txt # Python dependencies
├── PROJECT_GUIDE.md     # Detailed architecture, APIs, and developer guide
└── README.md
```

---

## 🛠️ Getting Started

### 1. Desktop Application Setup

1. Install Python 3.11+:
   ```bash
   python --version
   ```
2. Navigate to `soft/` and install dependencies:
   ```bash
   cd soft
   pip install -r requirements.txt
   ```
3. Run the desktop application:
   ```bash
   python app.py
   ```
4. Run tests:
   ```bash
   python -m unittest discover -s tests -p "test_*.py"
   ```

### 2. ESP32 Hardware Setup

1. Open `hard/last.ino` in Arduino IDE.
2. Install required libraries: `TFT_eSPI`, `Adafruit_Fingerprint`, `ArduinoJson` (v7), `DFRobotDFPlayerMini`.
3. Configure Wi-Fi via the `HULK_GYM_SETUP` hotspot portal or flash with pre-configured credentials.
4. Upload SPIFFS/LittleFS filesystem data from `hard/data/`.

---

## 📖 Detailed Documentation

For full architecture details, hardware pinouts, API endpoints, and development guidelines, refer to **[PROJECT_GUIDE.md](PROJECT_GUIDE.md)**.
