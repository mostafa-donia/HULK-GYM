import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = ROOT / 'app.py'

spec = importlib.util.spec_from_file_location('hulk_gym_app', SPEC)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UnifiedEntryModeTests(unittest.TestCase):
    def test_unified_entry_modes_are_resolved_for_backend_pages(self):
        self.assertEqual(module.resolve_unified_entry_mode('new'), 'new_subscription')
        self.assertEqual(module.resolve_unified_entry_mode('renewal'), 'renewal')
        self.assertEqual(module.resolve_unified_entry_mode('remaining'), 'remaining')
        self.assertEqual(module.resolve_unified_entry_mode('unknown'), 'new_subscription')

    def test_unified_entry_query_has_search_suggestions(self):
        app = module.QApplication.instance() or module.QApplication([])
        store = module.Store.__new__(module.Store)
        store.members = [
            {'member_id': 'm1', 'name': 'أحمد', 'mobile': '01000000000'},
            {'member_id': 'm2', 'name': 'سارة', 'mobile': '01000000001'},
        ]
        store.settings = {'plans': [], 'payment_methods': ['نقدي']}
        store.whatsapp_messages = []
        page = module.UnifiedEntryPage(store, lambda: None, lambda: None)
        self.assertIsNotNone(page.query_input.completer())
        self.assertIn('أحمد - 01000000000', page.query_input.completer().model().stringList())

    def test_unified_entry_duplicate_mobile_returns_multiple_candidates(self):
        app = module.QApplication.instance() or module.QApplication([])
        store = module.Store.__new__(module.Store)
        store.members = [
            {'member_id': 'm1', 'name': 'أحمد', 'mobile': '01000000000', 'current_status': 'active'},
            {'member_id': 'm2', 'name': 'محمد', 'mobile': '01000000000', 'current_status': 'active'},
        ]
        store.settings = {'plans': [], 'payment_methods': ['نقدي']}
        store.whatsapp_messages = []
        page = module.UnifiedEntryPage(store, lambda: None, lambda: None)

        candidates = page._find_member_candidates('01000000000')

        self.assertEqual(len(candidates), 2)
        self.assertEqual({c['member_id'] for c in candidates}, {'m1', 'm2'})

    def test_unified_entry_exact_name_and_mobile_picks_single_candidate(self):
        app = module.QApplication.instance() or module.QApplication([])
        store = module.Store.__new__(module.Store)
        store.members = [
            {'member_id': 'm1', 'name': 'أحمد', 'mobile': '01000000000', 'current_status': 'active'},
            {'member_id': 'm2', 'name': 'محمد', 'mobile': '01000000000', 'current_status': 'active'},
        ]
        store.settings = {'plans': [], 'payment_methods': ['نقدي']}
        store.whatsapp_messages = []
        page = module.UnifiedEntryPage(store, lambda: None, lambda: None)

        candidates = page._find_member_candidates('محمد - 01000000000')

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['member_id'], 'm2')

    def test_unified_entry_reset_after_save_clears_query_and_form(self):
        app = module.QApplication.instance() or module.QApplication([])
        store = module.Store.__new__(module.Store)
        store.members = []
        store.settings = {'plans': [], 'payment_methods': ['نقدي']}
        store.whatsapp_messages = []
        page = module.UnifiedEntryPage(store, lambda: None, lambda: None)
        page.query_input.setText('أحمد')
        page.new_page.name.setText('أحمد')
        page.new_page.mobile.setText('01000000000')

        page.reset_after_save()

        self.assertEqual(page.query_input.text(), '')
        self.assertEqual(page.new_page.name.text(), '')
        self.assertEqual(page.new_page.mobile.text(), '')

    def test_google_contacts_queue_is_saved_and_retried(self):
        original_data_dir = module.DATA_DIR
        original_sync = module.sync_member_to_google_contacts
        with tempfile.TemporaryDirectory() as tmpdir:
            module.DATA_DIR = pathlib.Path(tmpdir) / 'data'
            module.DATA_DIR.mkdir(parents=True, exist_ok=True)
            store = module.Store.__new__(module.Store)
            store.google_contacts_queue = []
            store.google_contacts_queue_file = module.DATA_DIR / 'google_contacts_pending.json'
            store.queue_google_contact({'name': 'أحمد', 'mobile': '01000000000'})
            self.assertEqual(len(store.google_contacts_queue), 1)
            self.assertTrue(store.google_contacts_queue_file.exists())
            module.sync_member_to_google_contacts = lambda member, force=False: (False, 'offline')
            synced = store.flush_google_contacts_queue()
            self.assertEqual(synced, 0)
            self.assertEqual(len(store.google_contacts_queue), 1)
        module.DATA_DIR = original_data_dir
        module.sync_member_to_google_contacts = original_sync

    def test_sync_all_google_contacts_queues_all_members(self):
        original_sync = module.sync_member_to_google_contacts
        module.sync_member_to_google_contacts = lambda member, force=False: (True, 'ok')
        store = module.Store.__new__(module.Store)
        store.members = [
            {'name': 'أحمد', 'mobile': '01000000000'},
            {'name': 'سارة', 'mobile': '01000000001'},
        ]
        store.google_contacts_queue = []
        store.save_google_contacts_queue = lambda: None
        store.save_members = lambda: None

        queued_added, synced_count = store.sync_all_google_contacts()

        self.assertEqual(queued_added, 2)
        self.assertEqual(synced_count, 2)
        self.assertEqual(len(store.google_contacts_queue), 0)
        module.sync_member_to_google_contacts = original_sync

    def test_everyday_plan_allows_any_day_within_period(self):
        store = module.Store()
        member = {
            'member_id': 'm1',
            'name': 'أحمد',
            'mobile': '01000000000',
            'last_subscription_type': 'شهري شامل - كل يوم',
            'last_subscription_start': '2024-01-01',
            'last_subscription_end': '2024-01-31',
            'current_status': 'active',
        }
        allowed, reason = store.can_member_attend(member, module.date(2024, 1, 15))
        self.assertTrue(allowed)
        self.assertIn('مسموح', reason)

    def test_alternating_plan_only_allows_matching_days(self):
        store = module.Store()
        member = {
            'member_id': 'm2',
            'name': 'سالم',
            'mobile': '01000000001',
            'last_subscription_type': 'شهري شامل - يوم ويوم',
            'last_subscription_start': '2024-01-01',
            'last_subscription_end': '2024-01-31',
            'current_status': 'active',
        }
        self.assertTrue(store.can_member_attend(member, module.date(2024, 1, 1))[0])
        self.assertFalse(store.can_member_attend(member, module.date(2024, 1, 2))[0])

    def test_validate_mobile_accepts_normal_egyptian_number(self):
        valid, error = module.validate_mobile('01012345678')
        self.assertTrue(valid)
        self.assertEqual(error, '')

    def test_validate_mobile_rejects_numbers_longer_than_11_digits(self):
        valid, error = module.validate_mobile('010123456789')
        self.assertFalse(valid)
        self.assertIn('11 رقم', error)

    def test_normalize_clock_time_supports_single_digit_and_arabic_digits(self):
        self.assertEqual(module.normalize_clock_time('9:30'), '09:30')
        self.assertEqual(module.normalize_clock_time('٠٩:٣٠'), '09:30')
        self.assertEqual(module.normalize_clock_time('23:05'), '23:05')
        self.assertEqual(module.normalize_clock_time('24:00'), '')

    def test_google_contact_paths_are_resolved_from_project_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = pathlib.Path(tmpdir)
            data_dir = project_dir / 'data'
            data_dir.mkdir(parents=True, exist_ok=True)
            credential_file = data_dir / 'credentials.json'
            credential_file.write_text('{}', encoding='utf-8')
            original_base_dir = module.BASE_DIR
            original_data_dir = module.DATA_DIR
            module.BASE_DIR = project_dir
            module.DATA_DIR = data_dir
            try:
                credentials_path, token_path = module.resolve_google_contact_paths()
            finally:
                module.BASE_DIR = original_base_dir
                module.DATA_DIR = original_data_dir
            self.assertEqual(credentials_path, credential_file)
            self.assertEqual(token_path, data_dir / 'token.json')

    def test_member_whatsapp_requires_registered_mobile(self):
        store = module.Store.__new__(module.Store)
        store.members = []
        store.whatsapp_messages = []
        self.assertIsNone(store.queue_whatsapp_message(
            '01012345678', 'test', 'receipt', recipient_type='member', save=False
        ))

    def test_monthly_subscription_ends_on_the_day_before_next_month(self):
        store = module.Store()
        end, _, _, days = store.calculate_end(module.date(2026, 7, 18), 'شهري شامل - كل يوم', 400, 0)
        self.assertEqual(end, '2026-08-17')
        self.assertEqual(days, 30)

    def test_renewal_page_can_select_member_by_id(self):
        app = module.QApplication.instance() or module.QApplication([])
        store = module.Store.__new__(module.Store)
        store.members = [
            {'member_id': 'm1', 'name': 'أحمد', 'mobile': '01000000000', 'gender': 'male', 'current_remaining': 0},
        ]
        store.settings = {'plans': [], 'payment_methods': ['نقدي']}
        page = module.AddSubscriptionPage(store, 'renewal', lambda: None, lambda: None)
        page.select_member('m1')
        selected = page.selected_member()
        self.assertIsNotNone(selected)
        self.assertEqual(selected['member_id'], 'm1')

    def test_new_subscription_receipt_is_delayed(self):
        store = module.Store.__new__(module.Store)
        store.members = [{'member_id': 'm1', 'mobile': '01012345678'}]
        store.whatsapp_messages = []
        message = store.queue_receipt({
            'operation_type': 'new_subscription',
            'mobile': '01012345678',
            'name': 'أحمد',
            'invoice_no': 'INV-1',
        }, save=False)
        self.assertIsNotNone(message)
        self.assertFalse(store.whatsapp_message_ready(message))

    def test_member_whatsapp_is_scheduled_for_one_hour_for_new_number(self):
        store = module.Store.__new__(module.Store)
        store.members = [{'member_id': 'm1', 'mobile': '01012345678'}]
        store.whatsapp_messages = []
        message = store.queue_whatsapp_message(
            '01012345678',
            'test reminder',
            'reminder_1',
            recipient_type='member',
            reference_id='m1',
            save=False,
        )
        self.assertIsNotNone(message)
        self.assertEqual(message.get('status'), 'scheduled')
        self.assertFalse(store.whatsapp_message_ready(message))

    def test_member_whatsapp_becomes_pending_after_one_hour(self):
        store = module.Store.__new__(module.Store)
        store.members = [{'member_id': 'm1', 'mobile': '01012345678'}]
        store.whatsapp_messages = []
        message = store.queue_whatsapp_message(
            '01012345678',
            'test reminder',
            'reminder_1',
            recipient_type='member',
            reference_id='m1',
            save=False,
        )
        self.assertIsNotNone(message)
        self.assertEqual(message.get('status'), 'scheduled')
        message['send_after'] = (module.datetime.now() - module.timedelta(minutes=1)).strftime(module.DATETIME_FMT)

        promoted = store.promote_scheduled_whatsapp_messages(save=False)

        self.assertEqual(promoted, 1)
        self.assertEqual(message.get('status'), 'pending')
        self.assertTrue(store.whatsapp_message_ready(message))

    def test_existing_synced_number_receipt_is_ready_immediately(self):
        store = module.Store.__new__(module.Store)
        synced_at = (module.datetime.now() - module.timedelta(days=1)).strftime(module.DATETIME_FMT)
        store.members = [{'member_id': 'm1', 'mobile': '01012345678', 'google_contact_synced_at': synced_at}]
        store.whatsapp_messages = []
        store.google_contacts_synced_numbers = []
        message = store.queue_receipt({
            'operation_type': 'renewal',
            'mobile': '01012345678',
            'name': 'أحمد',
            'invoice_no': 'INV-READY',
        }, save=False)
        self.assertIsNotNone(message)
        self.assertTrue(store.whatsapp_message_ready(message))

    def test_cached_google_number_is_treated_as_registered(self):
        store = module.Store.__new__(module.Store)
        store.members = [{'member_id': 'm1', 'mobile': '01012345678'}]
        store.whatsapp_messages = []
        store.google_contacts_synced_numbers = ['01012345678']
        message = store.queue_receipt({
            'operation_type': 'renewal',
            'mobile': '01012345678',
            'name': 'أحمد',
            'invoice_no': 'INV-CACHED',
        }, save=False)
        self.assertIsNotNone(message)
        self.assertTrue(store.whatsapp_message_ready(message))

    def test_sent_reminder_is_not_purged_or_requeued_as_pending(self):
        store = module.Store.__new__(module.Store)
        end_date = (module.date.today() + module.timedelta(days=1)).strftime(module.DATE_FMT)
        sent_at = module.now_str()
        store.members = [
            {
                'member_id': 'm1',
                'name': 'أحمد',
                'mobile': '01012345678',
                'current_status': 'active',
                'last_subscription_end': end_date,
                'last_subscription_type': 'شهري شامل - كل يوم',
                'google_contact_synced_at': sent_at,
            }
        ]
        store.payments = []
        store.settings = {
            'plans': [{'name': 'شهري شامل - كل يوم', 'frequency': 'كل يوم'}],
            'payment_methods': ['نقدي'],
        }
        store.google_contacts_synced_numbers = ['01012345678']
        store.whatsapp_messages = [
            {
                'message_id': 'WA-1',
                'type': 'reminder_1',
                'recipient_type': 'member',
                'recipient_name': 'أحمد',
                'mobile': '01012345678',
                'message': 'تذكير',
                'status': 'sent',
                'created_at': sent_at,
                'send_after': '',
                'sent_at': sent_at,
                'error': '',
                'reference_id': 'm1',
                'dedup_key': f'reminder_1:m1:{end_date}',
            }
        ]
        store.save_whatsapp = lambda: None
        store.save_members = lambda: None

        removed = store.purge_old_whatsapp_messages(retention_days=7, save=False)
        added = store.queue_due_reminders(save=False)

        self.assertEqual(removed, 0)
        self.assertEqual(added, 0)
        self.assertEqual(len(store.whatsapp_messages), 1)
        self.assertEqual(store.whatsapp_messages[0].get('status'), 'sent')

    def test_sent_expired_message_for_same_cycle_is_not_requeued(self):
        store = module.Store.__new__(module.Store)
        end_date = (module.date.today() - module.timedelta(days=1)).strftime(module.DATE_FMT)
        sent_at = module.now_str()
        store.members = [
            {
                'member_id': 'm1',
                'name': 'أحمد',
                'mobile': '01012345678',
                'current_status': 'expired',
                'last_subscription_end': end_date,
                'last_subscription_type': 'شهري شامل - كل يوم',
                'google_contact_synced_at': sent_at,
            }
        ]
        store.payments = []
        store.settings = {
            'plans': [{'name': 'شهري شامل - كل يوم', 'frequency': 'كل يوم'}],
            'payment_methods': ['نقدي'],
        }
        store.google_contacts_synced_numbers = ['01012345678']
        store.whatsapp_messages = [
            {
                'message_id': 'WA-EXP-1',
                'type': 'expired',
                'recipient_type': 'member',
                'recipient_name': 'أحمد',
                'mobile': '01012345678',
                'message': 'انتهى الاشتراك',
                'status': 'sent',
                'created_at': sent_at,
                'send_after': '',
                'sent_at': sent_at,
                'error': '',
                'reference_id': 'm1',
                'dedup_key': f'expired:m1:{end_date}',
            }
        ]
        store.save_whatsapp = lambda: None
        store.save_members = lambda: None

        added = store.queue_due_reminders(save=False)

        self.assertEqual(added, 0)
        self.assertEqual(len(store.whatsapp_messages), 1)
        self.assertEqual(store.whatsapp_messages[0].get('status'), 'sent')

    def test_deleted_sent_reminder_still_not_recreated_due_to_history(self):
        store = module.Store.__new__(module.Store)
        end_date = (module.date.today() + module.timedelta(days=1)).strftime(module.DATE_FMT)
        store.members = [
            {
                'member_id': 'm1',
                'name': 'أحمد',
                'mobile': '01012345678',
                'current_status': 'active',
                'last_subscription_end': end_date,
                'last_subscription_type': 'شهري شامل - كل يوم',
                'google_contact_synced_at': module.now_str(),
            }
        ]
        store.payments = []
        store.settings = {
            'plans': [{'name': 'شهري شامل - كل يوم', 'frequency': 'كل يوم'}],
            'payment_methods': ['نقدي'],
        }
        store.google_contacts_synced_numbers = ['01012345678']
        store.whatsapp_messages = []
        store.whatsapp_sent_history = {
            f'reminder_1:m1:{end_date}': module.now_str(),
        }
        store.save_whatsapp = lambda: None
        store.save_members = lambda: None
        store.save_whatsapp_sent_history = lambda: None

        added = store.queue_due_reminders(save=False)

        self.assertEqual(added, 0)
        self.assertEqual(len(store.whatsapp_messages), 0)

    def test_new_subscription_allows_new_name_with_existing_phone(self):
        store = module.Store()
        store.members = [
            {
                'member_id': 'm1',
                'name': 'أحمد',
                'mobile': '01012345678',
                'gender': 'male',
                'current_status': 'expired',
                'last_subscription_start': '',
                'last_subscription_end': '',
                'last_subscription_type': '',
                'current_paid': 0,
                'current_remaining': 0,
                'total_paid': 0,
                'subscriptions_history': [],
            }
        ]
        payment = store.add_payment({
            'operation_type': 'new_subscription',
            'name': 'سليم',
            'mobile': '01012345678',
            'gender': 'male',
            'subscription_type': 'شهري شامل - كل يوم',
            'subscription_start': '2026-07-24',
            'paid_amount': 400,
            'payment_method': 'نقدي',
        })
        self.assertEqual(payment['name'], 'سليم')
        self.assertEqual(len(store.members), 2)

    def test_settings_unlock_survives_refresh_within_window(self):
        app = module.QApplication.instance() or module.QApplication([])
        store = module.Store.__new__(module.Store)
        store.settings = {
            'dashboard_password': '1234',
            'manager_mobile': '',
            'whatsapp_enabled': True,
            'expired_message_template': '',
            'plans': [],
            'payment_methods': ['نقدي'],
            'expense_categories': [],
        }
        page = module.SettingsPage(store)
        page.password_unlocked = True
        page.unlock_expires_at = module.datetime.now() + module.timedelta(seconds=30)
        page.refresh()
        self.assertTrue(page.password_unlocked)

    def test_settings_unlock_locks_after_window(self):
        app = module.QApplication.instance() or module.QApplication([])
        store = module.Store.__new__(module.Store)
        store.settings = {
            'dashboard_password': '1234',
            'manager_mobile': '',
            'whatsapp_enabled': True,
            'expired_message_template': '',
            'plans': [],
            'payment_methods': ['نقدي'],
            'expense_categories': [],
        }
        page = module.SettingsPage(store)
        page.password_unlocked = True
        page.unlock_expires_at = module.datetime.now() - module.timedelta(seconds=1)
        page.refresh()
        self.assertFalse(page.password_unlocked)


if __name__ == '__main__':
    unittest.main()
