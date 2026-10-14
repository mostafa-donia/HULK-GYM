# Workspace Internal Notes

## High-level architecture

- `app.py` is the single main desktop application entrypoint.
- `Store` is the central data layer, responsible for JSON storage, migration, ID generation, and business logic.
- `MainWindow` builds the UI, sidebar navigation, and page stack.
- `WhatsAppSendThread` wraps the send process to avoid blocking the UI.
- `whatsapp_sender.py` is treated as an external automation module, not tightly coupled to the UI.

## Key data files

- `data/settings.json`
  - Contains `dashboard_password`, `manager_mobile`, `plans`, and `payment_methods`.
  - No explicit `daily_report_time` setting; report sending is hard-coded to 01:30 AM.

- `data/members.json`
  - Holds member records.
  - Member `member_type` is `member` or `lead`.
  - `subscriptions_history` stores each payment/subscription event.

- `data/payments.json`
  - Payment history, including new subscriptions, renewals, and remaining payments.

- `data/whatsapp_messages.json`
  - Pending, sent, and failed WhatsApp items.
  - Uses deduplication via `dedup_key`.

## WhatsApp automation behavior

- `whatsapp_sender.py` uses screen automation and clipboard operations.
- It opens Chrome and WhatsApp Web if not already present.
- It uses `ctrl+alt+/` to focus WhatsApp search, then types the phone, enters, pastes the message, and sends.
- If an image path is provided, it copies the image to the Windows clipboard and pastes it.
- The send pipeline is fragile and dependent on the browser title, focus, and timing.
- Failed numbers are detected by collecting the current WhatsApp search text after search and looking for invalid results.

## Important code paths

- `Store.add_payment()` and `Store.pay_remaining()` generate receipts and queue WhatsApp messages automatically.
- `Store.queue_due_reminders()` scans active members and queues reminders for 3-day, 1-day, and expired cases.
- `Store.queue_daily_report_if_due()` is time-gated to 01:30 AM, but can be forced manually.
- `MainWindow.run_auto_whatsapp_checks()` runs every 60 seconds and may enqueue reminders/reports.
- `MainWindow.send_pending_whatsapp()` starts `WhatsAppSendThread` and updates statuses after completion.

## Potential risk / maintenance notes

- The app assumes `data/` exists and will create it if missing.
- `whatsapp_sender.py` contains debugging prints and a weak stability model.
- `app.py` has no separate module structure, making careful edits important.
- `settings.json` currently stores the manager phone and password in cleartext.

## Immediate follow-up items

- Investigate whether `data/members.json`, `data/payments.json`, and `data/whatsapp_messages.json` exist and whether sample data is present.
- Review the `build_exe*.bat` scripts if packaging behavior needs inspection.
- Consider refactoring the WhatsApp automation into a more robust state machine or browser automation framework if reliability is required.
