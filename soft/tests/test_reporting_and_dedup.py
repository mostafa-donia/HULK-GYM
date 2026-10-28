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

from app import Store, date_to_str


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


if __name__ == "__main__":
    unittest.main()
