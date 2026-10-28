import json
import http.client
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError


V1_DIR = Path(__file__).resolve().parents[1]
if str(V1_DIR) not in sys.path:
    sys.path.insert(0, str(V1_DIR))

import app
import esp_client


class FakeResponse:
    def __init__(self, body: str):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body.encode("utf-8")


class ESPClientContractTests(unittest.TestCase):
    SETTINGS = {"esp_ip": "192.168.1.254", "esp_port": 80, "esp_enabled": True}

    @patch("esp_client.urllib.request.urlopen")
    def test_status_uses_get_status_and_validates_device(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({
            "success": True,
            "device": "HULK_GYM",
            "wifi": "connected",
            "fingerprint": True,
            "members": 2,
        }))

        result = esp_client.get_esp_status(self.SETTINGS)

        self.assertTrue(result["success"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url, "http://192.168.1.254:80/status")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5.0)

    @patch("esp_client.urllib.request.urlopen")
    def test_status_rejects_wrong_device_or_missing_success(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({"device": "OTHER", "members": 2}))

        result = esp_client.get_esp_status(self.SETTINGS)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_status_response")

    @patch("esp_client.urllib.request.urlopen")
    def test_push_members_uses_post_and_only_minimal_payload(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({"success": True, "members": 2}))
        members = {
            "MEM-00001": {"fingerprint_id": 7, "allowed": True},
            "MEM-00002": {"fingerprint_id": 12, "allowed": False},
        }

        result = esp_client.push_members(self.SETTINGS, members)

        self.assertTrue(result["success"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "http://192.168.1.254:80/members")
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent, {"members": members})
        self.assertNotIn("name", json.dumps(sent))
        self.assertNotIn("mobile", json.dumps(sent))
        self.assertNotIn("payment", json.dumps(sent))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5.0)

    @patch("esp_client.urllib.request.urlopen")
    def test_normal_connection_failure_retries_twice(self, urlopen):
        urlopen.side_effect = URLError("connection refused")

        result = esp_client.push_members(self.SETTINGS, {})

        self.assertFalse(result["success"])
        self.assertEqual(result["error_kind"], "connection_error")
        self.assertEqual(urlopen.call_count, 3)

    @patch("esp_client.urllib.request.urlopen")
    def test_timeout_retries_normal_request_and_reports_timeout(self, urlopen):
        urlopen.side_effect = URLError(socket.timeout("timed out"))

        result = esp_client.push_members(self.SETTINGS, {})

        self.assertFalse(result["success"])
        self.assertEqual(result["error_kind"], "timeout")
        self.assertEqual(urlopen.call_count, 3)

    @patch("esp_client.urllib.request.urlopen")
    def test_http_json_error_is_visible(self, urlopen):
        body = json.dumps({"success": False, "error": "invalid_members"})
        urlopen.side_effect = HTTPError(
            "http://192.168.1.254:80/members", 400, "Bad Request", {}, FakeResponse(body)
        )

        result = esp_client.push_members(self.SETTINGS, {})

        self.assertEqual(result, {"success": False, "error": "invalid_members"})
        self.assertEqual(urlopen.call_count, 1)

    @patch("esp_client.urllib.request.urlopen")
    def test_invalid_json_is_reported(self, urlopen):
        urlopen.return_value = FakeResponse("not-json")

        result = esp_client.push_members(self.SETTINGS, {})

        self.assertFalse(result["success"])
        self.assertEqual(result["error_kind"], "invalid_json")

    @patch("esp_client.urllib.request.urlopen")
    def test_enroll_uses_exact_endpoint_payload_and_75_second_timeout(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({
            "success": True,
            "member_id": "MEM-00003",
            "fingerprint_id": 13,
        }))

        result = esp_client.enroll_member(self.SETTINGS, " MEM-00003 ")

        self.assertTrue(result["success"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "http://192.168.1.254:80/enroll")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"member_id": "MEM-00003"})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 90.0)
        self.assertEqual(urlopen.call_count, 1)

    @patch("esp_client.urllib.request.urlopen")
    def test_enroll_rejects_missing_or_invalid_fingerprint_id(self, urlopen):
        for fingerprint_id in (None, 0, 1001, True, "13"):
            response = {"success": True, "member_id": "MEM-00003"}
            if fingerprint_id is not None:
                response["fingerprint_id"] = fingerprint_id
            urlopen.return_value = FakeResponse(json.dumps(response))

            result = esp_client.enroll_member(self.SETTINGS, "MEM-00003")

            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "invalid_fingerprint_id")

    @patch("esp_client.urllib.request.urlopen")
    def test_enroll_preserves_esp_failure_without_retry(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({
            "success": False,
            "member_id": "MEM-00003",
            "error": "enrollment_failed",
        }))

        result = esp_client.enroll_member(self.SETTINGS, "MEM-00003")

        self.assertEqual(result["error"], "enrollment_failed")
        self.assertEqual(urlopen.call_count, 1)

    @patch("esp_client.urllib.request.urlopen")
    def test_enroll_reports_transport_failure_without_retry(self, urlopen):
        urlopen.side_effect = URLError(socket.timeout("timed out"))

        result = esp_client.enroll_member(self.SETTINGS, "MEM-00003")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_kind"], "timeout")
        self.assertEqual(urlopen.call_count, 1)

    @patch("esp_client.time.sleep")
    @patch("esp_client.urllib.request.urlopen")
    def test_enroll_reports_remote_disconnect_without_worker_exception(self, urlopen, sleep):
        urlopen.side_effect = http.client.RemoteDisconnected("ESP closed the connection")

        result = esp_client.enroll_member(self.SETTINGS, "MEM-00003")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "enrollment_response_lost")
        self.assertEqual(urlopen.call_count, 1)

    @patch("esp_client.urllib.request.urlopen")
    def test_delete_uses_exact_endpoint_payload_and_normal_timeout(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({
            "success": True,
            "fingerprint_id": 13,
        }))

        result = esp_client.delete_fingerprint(self.SETTINGS, 13)

        self.assertTrue(result["success"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "DELETE")
        self.assertEqual(request.full_url, "http://192.168.1.254:80/fingerprint")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"fingerprint_id": 13})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5.0)

    @patch("esp_client.urllib.request.urlopen")
    def test_delete_rejects_invalid_fingerprint_ids_without_network_call(self, urlopen):
        for fingerprint_id in (None, 0, 1001, True, "13"):
            result = esp_client.delete_fingerprint(self.SETTINGS, fingerprint_id)

            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "invalid_fingerprint_id")

        urlopen.assert_not_called()

    @patch("esp_client.urllib.request.urlopen")
    def test_delete_preserves_esp_failure_response(self, urlopen):
        body = json.dumps({
            "success": False,
            "fingerprint_id": 13,
            "error": "delete_failed",
        })
        urlopen.side_effect = HTTPError(
            "http://192.168.1.254:80/fingerprint", 500, "Server Error", {}, FakeResponse(body)
        )

        result = esp_client.delete_fingerprint(self.SETTINGS, 13)

        self.assertEqual(result, {
            "success": False,
            "fingerprint_id": 13,
            "error": "delete_failed",
        })
        self.assertEqual(urlopen.call_count, 1)

    @patch("esp_client.urllib.request.urlopen")
    def test_last_scan_uses_get_endpoint(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({
            "success": True,
            "sequence": 12,
            "fingerprint_id": 17,
            "member_id": "MEM-00001",
            "allowed": True,
            "scan_active": True,
        }))

        result = esp_client.get_last_scan(self.SETTINGS)

        self.assertEqual(result["sequence"], 12)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url, "http://192.168.1.254:80/last_scan")

    @patch("esp_client.urllib.request.urlopen")
    def test_display_member_posts_full_display_payload(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({"success": True}))
        payload = {
            "sequence": 12,
            "name": "Test Member",
            "member_id": "MEM-00001",
            "plan_type": "Monthly",
            "end_date": "15/10/2026",
            "last_payment": "01/09/2026",
            "fingerprint_id": 17,
            "allowed": True,
        }

        result = esp_client.display_member(self.SETTINGS, payload)

        self.assertTrue(result["success"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "http://192.168.1.254:80/display_member")
        self.assertEqual(json.loads(request.data.decode("utf-8")), payload)

    @patch("esp_client.urllib.request.urlopen")
    def test_push_rejects_personal_or_extra_fields_before_network(self, urlopen):
        result = esp_client.push_members(self.SETTINGS, {
            "MEM-00001": {"fingerprint_id": 7, "allowed": True, "name": "Test"},
        })

        self.assertEqual(result, {"success": False, "error": "invalid_member_record"})
        urlopen.assert_not_called()

    @patch("esp_client.urllib.request.urlopen")
    def test_push_rejects_invalid_ids_and_more_than_1000_records(self, urlopen):
        invalid_id = esp_client.push_members(self.SETTINGS, {
            "MEM-00001": {"fingerprint_id": 0, "allowed": True},
        })
        self.assertEqual(invalid_id["error"], "invalid_fingerprint_id")

        too_large = {
            f"MEM-{index:05d}": {"fingerprint_id": index, "allowed": True}
            for index in range(1, 1002)
        }
        too_large_result = esp_client.push_members(self.SETTINGS, too_large)
        self.assertEqual(too_large_result, {"success": False, "error": "database_too_large"})
        urlopen.assert_not_called()


    @patch("esp_client.urllib.request.urlopen")
    def test_clear_all_fingerprints_posts_to_correct_endpoint(self, urlopen):
        urlopen.return_value = FakeResponse(json.dumps({"success": True}))
        result = esp_client.clear_all_fingerprints(self.SETTINGS)
        self.assertEqual(result, {"success": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://192.168.1.254:80/clear_fingerprints")
        self.assertEqual(request.method, "POST")

    def test_calculate_days_left_matches_membership_end_date(self):
        today = app.date.today()
        self.assertEqual(app.calculate_days_left(today.strftime("%d/%m/%Y")), 0)
        self.assertEqual(app.calculate_days_left((today + app.timedelta(days=2)).strftime("%d/%m/%Y")), 2)
        self.assertEqual(app.calculate_days_left((today - app.timedelta(days=1)).strftime("%d/%m/%Y")), -1)
        self.assertEqual(app.calculate_days_left(""), 0)


if __name__ == "__main__":
    unittest.main()
