# HULK GYM PySide6 Workspace Overview

## Purpose
This workspace contains a Windows desktop application for managing gym members, subscriptions, payments, and WhatsApp message automation using PySide6.

## Main components

- `app.py`
  - Main application code.
  - Builds a PySide6 desktop UI with pages for dashboard, members, payments, WhatsApp queue, and settings.
  - Stores data in JSON files under `data/`.
  - Includes a local queue for WhatsApp messages and a background send thread.

- `whatsapp_sender.py`
  - Contains the low-level WhatsApp Web automation.
  - Uses Chrome + WhatsApp Web + PyAutoGUI to search, paste, and send messages.
  - Uses `pygetwindow`, `pyautogui`, `pyperclip`, `Pillow`, and Windows clipboard APIs.
  - Designed to minimize focus-stealing popups and avoid blocking input during sending.

- `data/settings.json`
  - Current application settings.
  - Contains the dashboard password, manager mobile number, payment plans, and payment method list.

- `requirements.txt`
  - Python dependencies required for running the app.

- `assets/logo.png`
  - Application logo used by the sidebar.

## Functionality summary

### Member and payment management

- Members are stored in `data/members.json`.
- Payments are stored in `data/payments.json`.
- WhatsApp queued messages are stored in `data/whatsapp_messages.json`.
- UI pages include:
  - Dashboard: summary statistics and quick actions.
  - Members / active / expired: filtered member tables and search.
  - Payments: payment history and search.
  - WhatsApp: pending/sent/failed message queue.
  - Settings: manage plans, payment methods, manager mobile, and password.

### WhatsApp automation

- The app queues messages for:
  - payment receipts,
  - subscription reminders (3 days, 1 day),
  - expired subscription follow-up,
  - daily manager report.
- Messages remain in a local pending queue until sent.
- Sending is triggered manually or automatically after data changes and via a timer.
- The sending thread imports `whatsapp_sender.py` and executes the send flow with Chrome and WhatsApp Web.

### Data model and business logic

- Each member has:
  - `member_id`, `name`, `mobile`, `gender`, `current_status`, `last_subscription_start`, `last_subscription_end`, `current_paid`, `current_remaining`, `total_paid`, `follow_up_date`, `notes`, `subscriptions_history`.
- Payments include:
  - `payment_id`, `invoice_no`, `operation_type`, `member_id`, payment details, and status.
- WhatsApp messages include:
  - `message_id`, `type`, `mobile`, `message`, `status`, `created_at`, `sent_at`, `error`, `dedup_key`.
- `Store` handles JSON persistence, ID generation, migration, filtering, and message queueing.

## Running the app

1. Install dependencies:
   ```bat
   pip install -r requirements.txt
   ```
2. Run the app:
   ```bat
   python app.py
   ```

## Notes

- The app assumes Windows and Chrome with WhatsApp Web.
- While sending WhatsApp messages, do not move the mouse or type until sending completes.
- The manager mobile number is currently set in `data/settings.json`.
- The dashboard password is `1234` by default.
