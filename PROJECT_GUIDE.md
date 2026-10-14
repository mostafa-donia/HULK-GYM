# HULK GYM — Comprehensive Project Architecture & Developer Guide

> **Version**: V6  
> **Date**: October 2026  
> **Target Audience**: Developers & AI Agents modifying or extending the system.

---

## 1. System Overview & Repository Map

**HULK GYM** is an integrated gym management system comprising two primary subsystems:
1. **Desktop Client (`soft/`)**: A PySide6 (Qt for Python) desktop application featuring member management, financial tracking, receipts, automated WhatsApp messaging, Google Contacts synchronization, and remote hardware management.
2. **Biometric Hardware Terminal (`hard/`)**: An ESP32 microcontroller with an R307 optical fingerprint scanner, 320x480 TFT display (ST7796/ILI9488 via TFT_eSPI), DFPlayer Mini audio module, and RGB indicator LED. It acts as an autonomous HTTP server for offline-capable access control.

### Repository Layout

```text
v6/
├── hard/
│   ├── last.ino                # Complete ESP32 Arduino/C++ firmware (~3200 lines)
│   └── data/                   # LittleFS assets flashed to ESP32 SPIFFS/LittleFS
│       ├── background.bin      # Raw UI background graphic
│       ├── fingerprint.bin     # Biometric scanner UI icon
│       └── logo.bin            # Gym logo graphic
├── soft/
│   ├── app.py                  # Core desktop application entrypoint & Store (~8400+ lines)
│   ├── esp_client.py           # Dependency-free HTTP client for ESP32 REST API (~300 lines)
│   ├── whatsapp_sender.py      # PyAutoGUI WhatsApp Web screen automation engine (~640 lines)
│   ├── requirements.txt        # Python dependency manifest
│   ├── assets/                 # App icons and graphics (logo.png, logo.ico)
│   ├── data/                   # Runtime JSON databases (members, payments, settings, etc.)
│   │   ├── members.json
│   │   ├── payments.json
│   │   ├── expenses.json
│   │   ├── settings.json
│   │   ├── whatsapp_messages.json
│   │   ├── whatsapp_message_bank.json
│   │   ├── whatsapp_sent_history.json
│   │   ├── google_contacts_pending.json
│   │   ├── google_contacts_synced_numbers.json
│   │   └── member_permission.json
│   ├── tests/                  # Unittest suite
│   │   ├── test_esp_client_contract.py
│   │   ├── test_unified_entry.py
│   │   └── test_whatsapp_rate_limit.py
│   ├── output/                 # Build artifacts and release EXEs
│   └── UI_STYLE_GUIDE.md       # Styling notes for dark theme palette
└── PROJECT_GUIDE.md            # This reference manual
```

---

## 2. Desktop Application Architecture (`soft/app.py`)

`soft/app.py` is the monolithic core of the desktop software. It contains:
1. Utility functions (formatting, date calculations, validation, JSON I/O).
2. `Store` class (data layer & business logic).
3. UI widgets, base page abstractions (`BasePage`), dialogs, and threads.
4. `MainWindow` (navigation, page stacking, dynamic styling, auto-check timers).

### 2.1 The `Store` Data Layer

The `Store` class (lines ~640–2350) coordinates all business operations and file persistence:
- **Paths & Persistence**: All paths point to `DATA_DIR` (`soft/data/`). File reads/writes go through `read_json` and `write_json`.
- **Entity ID Generation**:
  - Members: `MEM-XXXXX` (5-digit padded sequence based on max existing numeric ID).
  - Payments: `PAY-XXXXX`.
  - Invoices: `INV-XXXXX`.
  - Expenses: `EXP-XXXXX`.
- **Member Status Logic**:
  - `active`: Today $\le$ `last_subscription_end`.
  - `expired`: Today $>$ `last_subscription_end`.
  - Status recalculation is triggered via `refresh_statuses(save=...)`.
- **Membership Operations**:
  - `add_member(data)`: Validates phone (`validate_mobile`), generates ID, saves record, enqueues Google Contact sync, and synchronizes with ESP32 if enabled.
  - `add_payment(data)` / `pay_remaining(data)`: Updates member status, creates payment record, queues receipt WhatsApp message, triggers ESP sync.
  - `queue_due_reminders()`: Evaluates members due in 3 days (`reminder_3`), 1 day (`reminder_1`), or expired (`expired`), checking against `whatsapp_sent_history` to prevent duplicates.
  - `queue_daily_report_if_due()`: Scheduled at `settings["daily_report_time"]` (defaults to "01:30" or configured time) to compose a financial summary for the manager.

### 2.2 UI Page Hierarchy (`QStackedWidget`)

`MainWindow` embeds pages into a `QStackedWidget` controlled by a custom sidebar:

| Page Class | Page Purpose | Key Interactions |
|---|---|---|
| `DashboardPage` | Overview dashboard | Metrics cards, revenue counters, quick entry shortcuts |
| `UnifiedEntryPage` | Rapid member action | Single search bar for new memberships, renewals, and remaining payments with auto-completion |
| `MembersTablePage` | Full member directory | Search query, status filter (all/active/expired), sort by name/date/remaining, pagination, actions |
| `MemberDetailsPage` | Member detail & history | Subscription timeline, payment list, edit dialog, ESP fingerprint registration/deletion |
| `AddSubscriptionPage` | Add subscription form | Plan selector, pricing, discount, start/end date calculation, partial payment support |
| `RemainingPaymentPage` | Pay balance form | Member balance lookup and payment settlement |
| `AddExpensePage` | Log expenses | Categorized gym expense recording |
| `PaymentsPage` | Financial ledger | Tabular log of payments and expenses with date filtering |
| `ManagerPage` | Financial reporting | Password-protected analytics, daily/monthly breakdown, manager reports |
| `WhatsAppPage` | WhatsApp message hub | Pending/sent/failed queue, message bank manager, batch sender runner, manual status toggles |
| `FingerprintDevicePage`| ESP32 hardware terminal | IP/Port config, connection status check, push test members, full member database sync |
| `SettingsPage` | System settings | Plans CRUD, payment methods, expense categories, manager mobile, report schedule |

### 2.3 Multithreading Model (`QThread`)

To prevent GUI freezing, heavy asynchronous workflows are isolated in `QThread` subclasses:
- `WhatsAppSendThread`: Executes `whatsapp_sender.sending(...)`. Emits progress and finished signals.
- `ESPOperationThread`: Performs network requests (`push_members`, `enroll_member`, `delete_fingerprint`) via `esp_client.py`.
- `GoogleContactsSyncThread`: Calls Google People API in the background.
- `GoogleContactsQueueFlushThread`: Processes batched contact insertions.

> **CRITICAL RULE**: Never manipulate GUI widgets directly from inside worker threads. Always emit Qt signals and connect them to slots on the main thread.

---

## 3. ESP32 Hardware Integration & REST Contract

### 3.1 Division of Responsibility
- **ESP32 is the autonomous gatekeeper**: It stores a local cache in LittleFS (`/members.json`) and directly matches fingerprint scans on the R307 sensor. If allowed, it triggers a green LED, audio chime 1, and unlocks the gate. The PC does NOT need to be on for member check-in.
- **Python App is the master authority**: Manages full names, subscriptions, payments, and decides `allowed: true/false`. It pushes the minimal authorization payload to the ESP.

### 3.2 ESP32 Pinout (`hard/last.ino`)

| Hardware Component | ESP32 GPIO Pins | Configuration / Notes |
|---|---|---|
| **R307 Fingerprint Sensor** | RX = `GPIO 22`, TX = `GPIO 23` | HardwareSerial(1), 57600 baud, 8N1 |
| **DFPlayer Mini Audio** | RX = `GPIO 16`, TX = `GPIO 17` | HardwareSerial(2), 9600 baud |
| **RGB Status LED** | Red = `25`, Green = `26`, Blue = `27`| Active HIGH digital outputs |
| **TFT Display (ST7796)** | SPI pins (MISO/MOSI/SCK/CS/DC/RST)| Configured in `TFT_eSPI/User_Setup.h` |

### 3.3 Audio File Mapping (DFPlayer Mini on SD Card)

| Track # | Event Description |
|---|---|
| **0001.mp3** | Access Granted ("Allowed / تفضل") |
| **0002.mp3** | System Ready / Initialized |
| **0003.mp3** | Access Denied / Subscription Expired ("اشتراكك منتهي") |
| **0004.mp3** | Fingerprint Not Found ("البصمة غير مسجلة") |
| **0005.mp3** | Sensor Error / Re-try ("أعد المحاولة") |

### 3.4 REST Endpoints (`esp_client.py` $\leftrightarrow$ `last.ino`)

All endpoints are at root (`/`), never prefixed with `/api`. Default server is `http://192.168.1.254:80` (or configured port).

#### 1. `GET /status`
- **Request**: Empty GET.
- **Response**:
  ```json
  {"success": true, "device": "HULK_GYM", "wifi": "connected", "fingerprint": true, "members": 25}
  ```
- **Validation**: Python enforces `success == true` and `device == "HULK_GYM"`.

#### 2. `POST /members`
- **Purpose**: Upload complete authorization database.
- **Security Invariant**: **NEVER** include names, phone numbers, or financial data in this payload. Only `member_id`, `fingerprint_id`, and `allowed`.
- **Payload**:
  ```json
  {
    "members": {
      "MEM-00001": {"fingerprint_id": 7, "allowed": true},
      "MEM-00002": {"fingerprint_id": 12, "allowed": false}
    }
  }
  ```
- **Constraints**: Maximum 1000 records. `fingerprint_id` must be an integer $1 \le ID \le 1000$.

#### 3. `POST /enroll`
- **Purpose**: Triggers physical R307 fingerprint enrollment on the terminal.
- **Payload**: `{"member_id": "MEM-00003"}`
- **Timeout**: 90 seconds (sensor active waiting for finger). Retries: **0** (never auto-retry enrollment).
- **Response**: `{"success": true, "member_id": "MEM-00003", "fingerprint_id": 13}`

#### 4. `POST /cancel_enroll`
- **Purpose**: Aborts an active enrollment loop on the ESP.
- **Payload**: `{"member_id": "MEM-00003"}`

#### 5. `DELETE /fingerprint`
- **Payload**: `{"fingerprint_id": 13}`
- **Workflow**: Python calls DELETE first. Only after ESP returns `success: true` does Python clear the local `fingerprint_id` from member records.

#### 6. `GET /last_scan` & `POST /display_member`
- Used to poll the latest scan event and send temporary display details (name, days left) for RAM-only display on the TFT screen.

---

## 4. WhatsApp Automation Subsystem (`soft/whatsapp_sender.py`)

### 4.1 Automation Mechanism
- Leverages `pyautogui`, `pyperclip`, `pygetwindow`, and `win32clipboard`.
- Interacts with Chrome running **WhatsApp Web**:
  1. Finds Chrome / WhatsApp window using `getAllWindows()`.
  2. Activates window and moves mouse safely.
  3. Uses shortcut `Ctrl + Alt + /` to focus the search bar.
  4. Types target phone number and hits `Enter`.
  5. Pastes or types the message:
     - **Paste Mode (`whatsapp_send_mode: "paste"`)**: Uses clipboard `Ctrl + V` (fastest & most reliable).
     - **Typing Mode (`whatsapp_send_mode: "typing"`)**: Simulates keystrokes via virtual keyboard mapping dictionary (`arabic_keys`).
  6. If attachment image path is passed, copies image to Windows clipboard and pastes (`Ctrl + V`).
  7. Sends message via `Enter`.

### 4.2 Rate Limiting (`WhatsAppRateLimiter`)
- Prevents WhatsApp spam banning:
  - Default: Max 20 messages per minute.
  - Max 120 messages per hour.
  - Implements sliding window queue tracking timestamps in `minute_window` and `hour_window`.

### 4.3 Deduplication, Message Bank & Protection Invariants
- **Deduplication**: `whatsapp_sent_history.json` records hashes of sent messages (`type:reference_id:cycle_key`).
- **Templates**: `whatsapp_message_bank.json` contains message variants per category (`receipt`, `reminder_3`, `reminder_1`, `expired`, `daily_report`). Dynamic placeholders:
  - `{name}` $\rightarrow$ Member name.
  - `{end_date}` $\rightarrow$ Subscription end date.
  - `{paid_amount}` $\rightarrow$ Amount paid.
  - `{remaining_amount}` $\rightarrow$ Remaining debt.
- **Message Protection Rule (`is_receipt_protected_whatsapp_message`)**:
  - **Protected (NEVER DELETED)**: Receipts (`receipt`), expired notices when subscription ended (`expired`), renewals (`renewal`), invoices (`invoice`), and manager reports (`daily_report`). These records are preserved across monthly rollovers, automated cleanups, and bulk purges.
  - **Prunable**: Only cycle reminders (`reminder_1`, `reminder_3`) can be purged when a member renews or after expiration.
- **Send Unsent Options**:
  - `send_unsent_btn` ("إرسال غير المرسل"): Gathers all pending and failed messages, resets failed to pending, and opens the selection dialog for streamlined bulk transmission.
  - `retry_failed_btn` ("إعادة الفاشل للمعلق"): Resets all failed messages back to pending status.

---

## 5. Google Contacts Sync Subsystem

- Uses Google People API (`googleapiclient.discovery`, `google-auth-oauthlib`).
- File credentials located in `soft/data/credentials.json` and `soft/data/token.json`.
- **Service Reuse**: Authenticates and builds the Google People API service once per batch session via `get_google_contacts_service()`, accelerating bulk uploads by orders of magnitude.
- **Force Sync**:
  - Invoked via `sync_all_google_contacts(force=True)`.
  - Resets `google_contacts_synced_numbers`, clears `google_contacts_queue`, clears `google_contact_synced_at` on members, and freshly pushes all gym members to Google Contacts.
- **Auth Change Detection**:
  `Store._google_auth_fingerprint()` computes SHA-256 of `credentials.json` + `token.json`. If credentials change, all sync tracking flags are invalidated, prompting full resync.
- Background sync puts numbers in `google_contacts_pending.json` and records completed numbers in `google_contacts_synced_numbers.json`.

---

## 6. Data Formats & Schemas (`soft/data/`)

### 6.1 `members.json` Schema
```json
[
  {
    "member_id": "MEM-00001",
    "member_type": "member",
    "name": "أحمد محمد",
    "mobile": "01000000000",
    "gender": "male",
    "current_status": "active",
    "last_subscription_start": "2026-10-01",
    "last_subscription_end": "2026-10-31",
    "last_subscription_type": "شهري شامل - كل يوم",
    "last_payment_date": "2026-10-01 14:00",
    "current_paid": 400.0,
    "current_remaining": 0.0,
    "total_paid": 400.0,
    "fingerprint_id": 7,
    "google_contact_synced_at": "2026-10-01 14:05:00",
    "subscriptions_history": [
      {
        "payment_id": "PAY-00001",
        "invoice_no": "INV-00001",
        "operation_type": "new_subscription",
        "subscription_start": "2026-10-01",
        "subscription_end": "2026-10-31",
        "subscription_type": "شهري شامل - كل يوم",
        "plan_price": 400.0,
        "paid_amount": 400.0,
        "remaining_amount": 0.0,
        "payment_method": "نقدي",
        "created_at": "2026-10-01 14:00:00"
      }
    ]
  }
]
```

### 6.2 `settings.json` Schema
```json
{
  "dashboard_password": "1234",
  "manager_mobile": "01080922432",
  "daily_report_time": "01:30",
  "esp_enabled": true,
  "esp_ip": "192.168.1.254",
  "esp_port": 80,
  "whatsapp_enabled": true,
  "whatsapp_send_mode": "paste",
  "whatsapp_letter_delay": 0.001,
  "plans": [
    {
      "name": "شهري شامل - كل يوم",
      "price": 400.0,
      "duration_days": 28,
      "months": 1,
      "frequency": "كل يوم"
    }
  ],
  "payment_methods": ["نقدي", "انستاباي", "فودافون كاش", "تحويل بنكي"],
  "expense_categories": ["إيجار", "فاتورة كهرباء", "صيانة", "معدات", "اخري"]
}
```

---

## 7. Developer Guidelines: Making Changes Safely

When modifying this repository, follow these cardinal rules:

### 1. Data Integrity & Backups
- Before altering logic that modifies `members.json` or `payments.json`, ensure changes maintain field type consistency (`paid_amount` as float, IDs as strings).
- Always use `write_json(path, data)` which ensures standard indentation and UTF-8 encoding.

### 2. Preserving ESP32 Security & Privacy
- **DO NOT** add member names, phone numbers, or amounts to `esp_client.push_members()` or `/members` endpoint. The ESP has limited RAM and flash, and must never receive PII.
- Keep timeouts generous for enrollment (90s) and brief for status (5s).

### 3. UI Styling & Theme Consistency
- All UI colors follow the dark theme defined in `MainWindow.apply_styles()` (lines ~3800–4100):
  - Primary Background: `#050B10`
  - Sidebar Background: `#070D12`
  - Accent / Primary Buttons: `#FFB300` / `#F0A500`
  - Text: `#E9EEF2`
  - Secondary / Borders: `#1C2430` / `#232C38`
- Refer to `UI_STYLE_GUIDE.md` when adding or restyling widgets.

### 4. Running Tests
Run unit tests from the project root:
```powershell
python -m unittest soft.tests.test_esp_client_contract
python -m unittest soft.tests.test_unified_entry
python -m unittest soft.tests.test_whatsapp_rate_limit
```

### 5. Packaging into Standalone Executable
The application is packaged with PyInstaller:
```bat
cd soft
pyinstaller --noconfirm --onedir --windowed --name "HULK_GYM" --icon "assets/logo.ico" --add-data "assets;assets" app.py
```
Or for single-file executable:
```bat
pyinstaller --noconfirm --onefile --windowed --name "HULK_GYM" --icon "assets/logo.ico" --add-data "assets;assets" app.py
```
> Note: On runtime, `bundled_resource_path()` checks `sys._MEIPASS` when frozen, and falls back to disk path when running as raw script.
