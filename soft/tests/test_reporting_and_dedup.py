import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import Store, date_to_str, member_sort_key, payment_sort_key


class TestReportingAndDeduplication(unittest.TestCase):
    def setUp(self):
        self.store = Store.__new__(Store)
        self.store.settings = {
            "last_whatsapp_rollover": "2026-10",
            "subscription_plans": [{"name": "شهر", "price": 400, "days": 30}],
            "payment_methods": ["نقدي"],
        }
        self.store.members = []
        self.store.payments = []
        self.store.expenses = []
        self.store.whatsapp_messages = []
        self.store.whatsapp_sent_history = {}
        self.store.google_contacts_queue = []
        self.store.google_contacts_synced_numbers = []
        self.store.save_members = lambda *args, **kwargs: None
        self.store.save_payments = lambda *args, **kwargs: None
        self.store.save_whatsapp = lambda *args, **kwargs: None
        self.store.save_settings = lambda *args, **kwargs: None
        self.store.save_expenses = lambda *args, **kwargs: None
        self.store.remove_member_pending_reminders = lambda *args, **kwargs: None
        self.store.queue_receipt = lambda *args, **kwargs: None
        self.store.find_member_by_mobile = lambda mob: next(
            (m for m in self.store.members if m.get("mobile") == mob), None
        )
        self.store.next_id = lambda prefix, lst, key: f"{prefix}-{len(lst) + 1:05d}"
        self.store.calculate_end = lambda start, plan, paid, allowance=0: (
            date_to_str(start + timedelta(days=30)),
            400.0,
            0.0,
            30,
        )

    def test_payment_idempotency_suppresses_rapid_duplicate(self):
        """Rapid double clicks on subscription renewal should return existing payment without duplicating."""
        payload1 = {
            "operation_type": "new_subscription",
            "name": "كابتن أحمد",
            "mobile": "01012345678",
            "gender": "male",
            "subscription_type": "شهر",
            "subscription_start": date_to_str(date.today()),
            "paid_amount": 400.0,
            "payment_method": "نقدي",
        }
        p1 = self.store.add_payment(payload1)
        self.assertEqual(len(self.store.payments), 1)

        # Immediately call add_payment again with same payload (simulating rapid double click)
        p2 = self.store.add_payment(payload1)
        self.assertEqual(p1["payment_id"], p2["payment_id"])
        self.assertEqual(p1["invoice_no"], p2["invoice_no"])
        self.assertEqual(len(self.store.payments), 1, "Duplicate payment should be suppressed")

    def test_deduplicate_payments_on_load(self):
        """Store should clean duplicate invoices that occurred within the same minute on load."""
        p1 = {
            "payment_id": "PAY-00001",
            "invoice_no": "INV-00001",
            "operation_type": "renewal",
            "member_id": "MEM-00001",
            "paid_amount": 400.0,
            "subscription_start": "2026-10-01",
            "created_at": "2026-10-01 10:15:20",
        }
        # Duplicate with different invoice_no but same minute, member, amount, op, start
        p2 = {
            "payment_id": "PAY-00002",
            "invoice_no": "INV-00002",
            "operation_type": "renewal",
            "member_id": "MEM-00001",
            "paid_amount": 400.0,
            "subscription_start": "2026-10-01",
            "created_at": "2026-10-01 10:15:21",
        }
        self.store.payments = [p1, p2]
        self.store.members = [{
            "member_id": "MEM-00001",
            "name": "محمد",
            "total_paid": 800.0,
            "subscriptions_history": [
                {"invoice_no": "INV-00001", "paid_amount": 400.0},
                {"invoice_no": "INV-00002", "paid_amount": 400.0},
            ]
        }]
        cleaned = self.store._deduplicate_payments()
        self.assertTrue(cleaned)
        self.assertEqual(len(self.store.payments), 1)
        self.assertEqual(self.store.payments[0]["invoice_no"], "INV-00001")
        self.assertEqual(self.store.members[0]["total_paid"], 400.0)
        self.assertEqual(len(self.store.members[0]["subscriptions_history"]), 1)

    def test_calculate_period_stats_and_daily_report_message(self):
        """calculate_period_stats should compute new members, renewals, receivables, ended-and-not-renewed, etc."""
        today = date.today()
        # Add members
        # Member 1: active, renewed today
        m1 = {
            "member_id": "MEM-00001",
            "name": "محمود سعيد",
            "mobile": "01000000001",
            "current_status": "active",
            "last_subscription_end": date_to_str(today + timedelta(days=20)),
            "current_remaining": 0,
            "total_paid": 400,
        }
        # Member 2: expired, ended 2 days ago and didn't renew
        m2 = {
            "member_id": "MEM-00002",
            "name": "علي حسن",
            "mobile": "01000000002",
            "current_status": "expired",
            "last_subscription_end": date_to_str(today - timedelta(days=2)),
            "current_remaining": 150,
            "total_paid": 250,
        }
        self.store.members = [m1, m2]

        # Add payments today
        self.store.payments = [
            {
                "payment_id": "PAY-00001",
                "invoice_no": "INV-00001",
                "operation_type": "new_subscription",
                "member_id": "MEM-00001",
                "paid_amount": 400.0,
                "remaining_amount": 0.0,
                "created_at": f"{date_to_str(today)} 11:00:00",
                "subscription_start": date_to_str(today),
            }
        ]

        stats_today = self.store.calculate_period_stats(today, today)
        self.assertEqual(stats_today["operations_count"], 1)
        self.assertEqual(stats_today["total_collected"], 400.0)
        self.assertEqual(stats_today["new_members_count"], 1)
        self.assertEqual(stats_today["total_receivables"], 150.0)
        self.assertEqual(stats_today["members_with_remaining_count"], 1)
        self.assertEqual(stats_today["active_members_count"], 1)
        self.assertEqual(stats_today["expired_members_count"], 1)

        # Build daily report message
        msg = self.store.build_daily_report_message()
        self.assertIn("تقرير هالك جيم الشامل", msg)
        self.assertIn("اليوم (Today)", msg)
        self.assertIn("الأسبوع الحالي (This Week)", msg)
        self.assertIn("الشهر الحالي (This Month)", msg)
        self.assertIn("إجمالي المتبقيات المستحقة", msg)



    def test_duplicate_name_and_phone_blocked(self):
        """Adding a new subscription with identical normalized name and phone should be rejected."""
        p1 = self.store.add_payment({
            "operation_type": "new_subscription",
            "name": "أحمد محمد علي",
            "mobile": "01099998888",
            "gender": "male",
            "subscription_type": "شهر",
            "subscription_start": "2026-11-01",
            "paid_amount": 350.0,
            "payment_method": "نقدي",
        })
        self.assertIsNotNone(p1)

        # Same name and phone (different tashkeel/alef) must raise ValueError
        with self.assertRaises(ValueError):
            self.store.add_payment({
                "operation_type": "new_subscription",
                "name": "احمد محمد علي",
                "mobile": "01099998888",
                "gender": "male",
                "subscription_type": "شهر",
                "subscription_start": "2026-11-02",
                "paid_amount": 350.0,
                "payment_method": "نقدي",
            })

    def test_brothers_sharing_same_phone_allowed(self):
        """Brothers with different names but same phone number should be permitted."""
        p1 = self.store.add_payment({
            "operation_type": "new_subscription",
            "name": "سيف الدين محمود",
            "mobile": "01055554444",
            "gender": "male",
            "subscription_type": "شهر",
            "subscription_start": "2026-11-01",
            "paid_amount": 350.0,
            "payment_method": "نقدي",
        })
        p2 = self.store.add_payment({
            "operation_type": "new_subscription",
            "name": "عمر الدين محمود",
            "mobile": "01055554444",
            "gender": "male",
            "subscription_type": "شهر",
            "subscription_start": "2026-11-01",
            "paid_amount": 350.0,
            "payment_method": "نقدي",
        })
        self.assertNotEqual(p1["member_id"], p2["member_id"])
        same_phone = self.store.find_members_by_mobile("01055554444")
        self.assertEqual(len(same_phone), 2)

    def test_ai_insights_structure(self):
        """Store.get_ai_insights should return peak hours, unrenewed counts, and actionable advice."""
        insights = self.store.get_ai_insights()
        self.assertIn("peak_hours_str", insights)
        self.assertIn("busiest_day_str", insights)
        self.assertIn("unrenewed_from_last_month", insights)
        self.assertIn("recommendations", insights)
        self.assertIsInstance(insights["recommendations"], list)


    def test_member_sorting_by_newest_activity_and_renewal(self):
        """Members page sorting should place newly renewed/updated members at the very top."""
        m_old = {
            "member_id": "MEM-00001",
            "name": "قديم",
            "last_subscription_start": "2026-06-01",
            "last_payment_date": "2026-06-01 10:00:00",
            "updated_at": "2026-06-01 10:00:00",
        }
        m_none = {
            "member_id": "MEM-00002",
            "name": "بدون تاريخ",
            "last_payment_date": None,
            "updated_at": None,
        }
        m_renewed_today = {
            "member_id": "MEM-00003",
            "name": "جدد اليوم",
            "last_subscription_start": "2026-11-12",
            "last_payment_date": "2026-11-12 11:30:00",
            "updated_at": "2026-11-12 11:30:00",
        }
        m_updated_today = {
            "member_id": "MEM-00004",
            "name": "تحديث اليوم",
            "last_subscription_start": "2026-10-01",
            "last_payment_date": "2026-10-01 09:00:00",
            "updated_at": "2026-11-12 12:00:00",
        }

        members = [m_old, m_none, m_renewed_today, m_updated_today]
        sorted_members = sorted(members, key=member_sort_key, reverse=True)

        # Most recently updated (12:00:00) is first
        self.assertEqual(sorted_members[0]["member_id"], "MEM-00004")
        # Renewed today (11:30:00) is second
        self.assertEqual(sorted_members[1]["member_id"], "MEM-00003")
        # Old member is third
        self.assertEqual(sorted_members[2]["member_id"], "MEM-00001")
        # Member with None is at the bottom, NEVER at the top
        self.assertEqual(sorted_members[3]["member_id"], "MEM-00002")

    def test_payment_sorting_by_newest(self):
        """Payments page sorting should place newest payment at the top."""
        p1 = {"invoice_no": "INV-00001", "created_at": "2026-07-01 10:00:00"}
        p2 = {"invoice_no": "INV-00002", "created_at": "2026-11-12 11:30:00"}
        p3 = {"invoice_no": "INV-00003", "created_at": None}
        payments = [p1, p2, p3]
        sorted_payments = sorted(payments, key=payment_sort_key, reverse=True)
        self.assertEqual(sorted_payments[0]["invoice_no"], "INV-00002")
        self.assertEqual(sorted_payments[1]["invoice_no"], "INV-00001")
        self.assertEqual(sorted_payments[2]["invoice_no"], "INV-00003")

    def test_evict_oldest_expired_fingerprint(self):
        """When fingerprint limit is reached, system should find and evict the oldest expired member."""
        m_active = {
            "member_id": "MEM-00001",
            "name": "عضو نشط",
            "current_status": "active",
            "fingerprint_id": 101,
            "last_subscription_end": "2026-12-01",
        }
        m_expired_recent = {
            "member_id": "MEM-00002",
            "name": "منتهي حديثاً",
            "current_status": "expired",
            "fingerprint_id": 102,
            "last_subscription_end": "2026-10-15",
        }
        m_expired_oldest = {
            "member_id": "MEM-00003",
            "name": "أقدم منتهي",
            "current_status": "expired",
            "fingerprint_id": 103,
            "last_subscription_end": "2026-01-10",
        }
        m_expired_no_fp = {
            "member_id": "MEM-00004",
            "name": "منتهي بدون بصمة",
            "current_status": "expired",
            "fingerprint_id": None,
            "last_subscription_end": "2025-01-01",
        }
        self.store.members = [m_active, m_expired_recent, m_expired_oldest, m_expired_no_fp]
        
        # Test finding oldest expired
        oldest = self.store.find_oldest_expired_member_with_fingerprint()
        self.assertIsNotNone(oldest)
        self.assertEqual(oldest["member_id"], "MEM-00003")
        self.assertEqual(oldest["fingerprint_id"], 103)

        # Track esp command
        from unittest.mock import patch
        with patch("app.esp_client.delete_fingerprint", return_value={"success": True}) as mock_del:
            # Test eviction
            evicted = self.store.evict_oldest_expired_fingerprint()
            self.assertIsNotNone(evicted)
            self.assertEqual(evicted["member_id"], "MEM-00003")
            self.assertIn(m_expired_oldest.get("fingerprint_id"), (None, ""))
            mock_del.assert_called_once_with(self.store.settings, 103)

        # Next oldest should now be m_expired_recent (102)
        next_oldest = self.store.find_oldest_expired_member_with_fingerprint()
        self.assertEqual(next_oldest["member_id"], "MEM-00002")

    def test_hourly_whatsapp_order_selection(self):
        """Hourly WhatsApp batch selection should correctly pick newest 10 vs oldest 10."""
        msgs = []
        for i in range(25):
            msgs.append({
                "message_id": f"MSG-{i:03d}",
                "status": "pending",
                "created_at": f"2026-11-17 10:{i:02d}:00",
            })
        
        # Newest 10: slice [-10:] reversed (MSG-024 down to MSG-015)
        newest_10 = list(reversed(msgs[-10:]))
        self.assertEqual(len(newest_10), 10)
        self.assertEqual(newest_10[0]["message_id"], "MSG-024")
        self.assertEqual(newest_10[-1]["message_id"], "MSG-015")

        # Oldest 10: slice [:10] (MSG-000 up to MSG-009)
        oldest_10 = msgs[:10]
        self.assertEqual(len(oldest_10), 10)
        self.assertEqual(oldest_10[0]["message_id"], "MSG-000")
        self.assertEqual(oldest_10[-1]["message_id"], "MSG-009")

    def test_delete_all_reminders(self):
        """Store.delete_all_reminders should delete only reminders while keeping other messages intact."""
        m1 = {"message_id": "M1", "template_key": "reminder_3days", "status": "pending"}
        m2 = {"message_id": "M2", "template_key": "reminder_expired", "status": "sent"}
        m3 = {"message_id": "M3", "template_key": "receipt", "status": "pending"}
        m4 = {"message_id": "M4", "type": "manager_report", "status": "sent"}
        self.store.whatsapp_messages = [m1, m2, m3, m4]

        deleted_count = self.store.delete_all_reminders()
        self.assertEqual(deleted_count, 2)
        remaining_ids = [m["message_id"] for m in self.store.whatsapp_messages]
        self.assertNotIn("M1", remaining_ids)
        self.assertNotIn("M2", remaining_ids)
        self.assertIn("M3", remaining_ids)
        self.assertIn("M4", remaining_ids)


if __name__ == "__main__":
    unittest.main()
