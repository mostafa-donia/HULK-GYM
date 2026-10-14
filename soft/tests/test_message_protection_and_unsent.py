import pathlib
import unittest
from unittest.mock import MagicMock

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as module


class MessageProtectionAndUnsentTests(unittest.TestCase):
    def setUp(self):
        self.store = module.Store.__new__(module.Store)
        self.store.settings = {"last_whatsapp_rollover": "2026-09"}
        self.store.members = []
        self.store.whatsapp_messages = []
        self.store.save_whatsapp = lambda: None
        self.store.save_settings = lambda: None

    def test_protection_rules_protect_all_non_reminders(self):
        # Protected: receipts, invoices, renewals, subscriptions, expired (sub ended), daily reports
        self.assertTrue(module.is_receipt_protected_whatsapp_message({"type": "receipt"}))
        self.assertTrue(module.is_receipt_protected_whatsapp_message({"type": "expired"}))
        self.assertTrue(module.is_receipt_protected_whatsapp_message({"type": "renewal"}))
        self.assertTrue(module.is_receipt_protected_whatsapp_message({"type": "invoice"}))
        self.assertTrue(module.is_receipt_protected_whatsapp_message({"type": "daily_report"}))

        # NOT protected (subject to automated cleanup/purging): reminders
        self.assertFalse(module.is_receipt_protected_whatsapp_message({"type": "reminder_1"}))
        self.assertFalse(module.is_receipt_protected_whatsapp_message({"type": "reminder_3"}))

    def test_delete_sent_messages_never_deletes_receipts_or_expired(self):
        self.store.whatsapp_messages = [
            {"message_id": "WA-1", "type": "receipt", "status": "sent", "sent_at": "2026-01-01 10:00:00"},
            {"message_id": "WA-2", "type": "expired", "status": "sent", "sent_at": "2026-01-01 10:00:00"},
            {"message_id": "WA-3", "type": "reminder_1", "status": "sent", "sent_at": "2026-01-01 10:00:00"},
            {"message_id": "WA-4", "type": "reminder_3", "status": "sent", "sent_at": "2026-01-01 10:00:00"},
        ]
        removed = self.store.delete_sent_whatsapp_messages(older_than_hours=0, save=False)
        self.assertEqual(removed, 2)
        remaining_ids = {m["message_id"] for m in self.store.whatsapp_messages}
        self.assertEqual(remaining_ids, {"WA-1", "WA-2"})

    def test_purge_blocked_pending_never_deletes_receipts_or_expired(self):
        self.store.whatsapp_messages = [
            {"message_id": "WA-1", "type": "receipt", "status": "pending", "mobile": "01000000000"},
            {"message_id": "WA-2", "type": "expired", "status": "pending", "mobile": "01000000001"},
            {"message_id": "WA-3", "type": "reminder_1", "status": "pending", "mobile": "01000000002"},
        ]
        self.store.refresh_statuses = lambda save=False: None
        self.store.is_whatsapp_message_allowed = lambda msg, refresh_statuses_first=False: False

        removed = self.store.purge_blocked_pending_whatsapp_messages(save=False)
        self.assertEqual(removed, 1)
        remaining_ids = {m["message_id"] for m in self.store.whatsapp_messages}
        self.assertEqual(remaining_ids, {"WA-1", "WA-2"})

    def test_rollover_preserves_receipts_and_expired(self):
        self.store.whatsapp_messages = [
            {"message_id": "WA-1", "type": "receipt", "status": "sent"},
            {"message_id": "WA-2", "type": "expired", "status": "sent"},
            {"message_id": "WA-3", "type": "reminder_1", "status": "sent"},
            {"message_id": "WA-4", "type": "reminder_3", "status": "sent"},
        ]
        self.store.rollover_whatsapp_messages_if_needed()
        remaining_ids = {m["message_id"] for m in self.store.whatsapp_messages}
        self.assertEqual(remaining_ids, {"WA-1", "WA-2"})

    def test_google_contacts_force_sync_resets_and_queues_all(self):
        self.store.members = [
            {"name": "عضو 1", "mobile": "01011111111", "google_contact_synced_at": "2026-09-01 10:00:00"},
            {"name": "عضو 2", "mobile": "01022222222", "google_contact_synced_at": "2026-09-01 10:00:00"},
        ]
        self.store.google_contacts_synced_numbers = ["01011111111", "01022222222"]
        self.store.google_contacts_queue = []
        self.store.save_google_contacts_synced_numbers = lambda: None
        self.store.save_google_contacts_queue = lambda: None
        self.store.save_members = lambda: None
        self.store.flush_google_contacts_queue = lambda progress_callback=None, total_override=None: 2

        queued_added, synced_count = self.store.sync_all_google_contacts(force=True)
        self.assertEqual(queued_added, 2)
        self.assertEqual(synced_count, 2)
        # All members should have their synced flags reset during force sync
        for m in self.store.members:
            self.assertEqual(m["google_contact_synced_at"], "")


if __name__ == "__main__":
    unittest.main()
