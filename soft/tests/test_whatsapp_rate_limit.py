import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = ROOT / 'whatsapp_sender.py'
APP_SPEC = ROOT / 'app.py'
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location('whatsapp_sender', SPEC)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

app_spec = importlib.util.spec_from_file_location('app_module', APP_SPEC)
app_module = importlib.util.module_from_spec(app_spec)
app_spec.loader.exec_module(app_module)


class WhatsAppRateLimiterTests(unittest.TestCase):
    def test_rate_limit_helper_allows_first_20_per_minute(self):
        helper = module.WhatsAppRateLimiter(limit_per_minute=20, limit_per_hour=120)
        for _ in range(20):
            self.assertTrue(helper.allow_send())
        self.assertFalse(helper.allow_send())

    def test_rate_limit_helper_allows_first_120_per_hour(self):
        helper = module.WhatsAppRateLimiter(limit_per_minute=120, limit_per_hour=120)
        for _ in range(120):
            self.assertTrue(helper.allow_send())
        self.assertFalse(helper.allow_send())

    def test_whatsapp_topic_uses_message_type_when_body_is_generated_text(self):
        message = {
            'type': 'reminder_3',
            'message': 'تنبيه من HULK GYM\nأهلاً احمد\nاشتراكك ينتهي غدًا\nيرجى تجديد الاشتراك.'
        }
        self.assertEqual(app_module.whatsapp_message_topic(message), 'reminder_3')

    def test_sender_uses_random_message_from_selected_topic_not_topic_name(self):
        bank = {
            'reminder_1': ['رسالة أ', 'رسالة ب'],
            'general': ['رسالة عامة']
        }
        original_ready = module.whatsupp_ready
        original_wait = module.WhatsAppRateLimiter.wait_until_allowed
        original_send = module.send_message
        original_layout = getattr(module, 'set_keyboard_layout_to_english', None)
        captured = {}

        module.whatsupp_ready = lambda: None
        module.WhatsAppRateLimiter.wait_until_allowed = lambda self, *args, **kwargs: True
        module.set_keyboard_layout_to_english = lambda: None

        def fake_send(phone, message, image=None, topic=None, message_bank=None, context=None):
            captured['phone'] = phone
            captured['topic'] = topic
            captured['message'] = message
            captured['chosen'] = module.choose_message_for_group(message, topic)
            captured['context'] = context

        module.send_message = fake_send
        try:
            module.sent = []
            module.unsent = []
            module.sending(['966500000001'], bank, groups=['reminder_1'])
            self.assertEqual(captured['topic'], 'reminder_1')
            self.assertEqual(captured['message'], bank)
            self.assertIn(captured['chosen'], bank['reminder_1'])
            self.assertNotEqual(captured['chosen'], 'reminder_1')
        finally:
            module.whatsupp_ready = original_ready
            module.WhatsAppRateLimiter.wait_until_allowed = original_wait
            module.send_message = original_send
            if original_layout is not None:
                module.set_keyboard_layout_to_english = original_layout

    def test_placeholder_formatting_substitutes_context_values(self):
        message_with_placeholders = "أهلاً {name}، شكراً لدفعك {amount_paid} ريال في {date}. المتبقي: {remaining_amount} ريال."
        context = {
            'name': 'أحمد',
            'amount_paid': '150',
            'date': '2026-09-01',
            'remaining_amount': '350'
        }
        formatted = app_module.format_message_with_context(message_with_placeholders, context)
        self.assertIn('أحمد', formatted)
        self.assertIn('150', formatted)
        self.assertIn('2026-09-01', formatted)
        self.assertIn('350', formatted)
        self.assertNotIn('{name}', formatted)
        self.assertNotIn('{amount_paid}', formatted)
        self.assertNotIn('{date}', formatted)
        self.assertNotIn('{remaining_amount}', formatted)

    def test_message_bank_accepts_double_equals_separator(self):
        text = "رسالة أولى\n\n==\nرسالة ثانية == رسالة ثالثة\n==\n == \nرسالة رابعة"
        parsed = app_module.split_message_bank_entries(text)
        self.assertEqual(parsed, [
            'رسالة أولى',
            'رسالة ثانية',
            'رسالة ثالثة',
            'رسالة رابعة',
        ])

    def test_receipt_messages_are_protected_from_bulk_delete(self):
        store = app_module.Store()
        store.whatsapp_messages = [
            {'message_id': 'WA-1', 'type': 'receipt', 'status': 'pending'},
            {'message_id': 'WA-2', 'type': 'reminder_1', 'status': 'pending'},
        ]
        deleted = store.delete_whatsapp_messages(['WA-1', 'WA-2'])
        self.assertEqual(deleted, 1)
        self.assertEqual([m['message_id'] for m in store.whatsapp_messages], ['WA-1'])


if __name__ == '__main__':
    unittest.main()
