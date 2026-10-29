"""HTTP client for the HULK GYM ESP32 fingerprint terminal.

The ESP32 is the HTTP server and always makes the ALLOWED/DENIED decision
locally; this module is a thin, dependency-free (urllib only) client used
by the desktop app to keep the ESP32's authorization cache in sync and to
manage fingerprint enrollment/deletion. Every public function here never
raises - failures are always returned as {"success": False, ...} so the
app never has to guess whether the ESP32 actually confirmed an operation.
"""
from __future__ import annotations

import json
import http.client
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class ESPRequestError(Exception):
    """Raised by _request() for any failure talking to the ESP32.

    `kind` is one of: "connection_error", "timeout", "http_error", "invalid_json".
    """

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}")


def _log(message: str) -> None:
    print(f"[ESP] {message}")


def is_enabled(settings: Dict[str, Any]) -> bool:
    return bool(settings.get("esp_enabled", False)) and bool(str(settings.get("esp_ip", "")).strip())


def base_url(settings: Dict[str, Any]) -> str:
    ip = str(settings.get("esp_ip", "192.168.1.254")).strip() or "192.168.1.254"
    try:
        port = int(settings.get("esp_port", 80) or 80)
    except Exception:
        port = 80
    if port <= 0 or port > 65535:
        port = 80
    return f"http://{ip}:{port}"


def _request(
    settings: Dict[str, Any],
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 5.0,
    retries: int = 2,
) -> Dict[str, Any]:
    """Low-level JSON request; retries only connection failures for normal calls."""
    url = f"{base_url(settings)}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    attempts = max(0, int(retries)) + 1
    _log(f"Connecting {method} {path}")
    for attempt in range(attempts):
        try:
            if path == "/enroll":
                _log("POST /enroll waiting for ESP enrollment_complete response...")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
            response_code = getattr(response, "status", None)
            if response_code is None and hasattr(response, "getcode"):
                response_code = response.getcode()
            _log(f"Response received: {method} {path} HTTP {response_code or '-'} body={body[:500]!r}")
            if not body:
                return {}
            try:
                return json.loads(body)
            except ValueError as exc:
                raise ESPRequestError("invalid_json", f"Could not parse ESP response: {body[:200]!r}") from exc
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8", errors="replace")
            except Exception:
                raw = ""
            try:
                parsed = json.loads(raw) if raw else None
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and "success" in parsed:
                return parsed
            raise ESPRequestError("http_error", f"HTTP {exc.code}: {raw}") from exc
        except (urllib.error.URLError, http.client.RemoteDisconnected, ConnectionResetError, TimeoutError) as exc:
            reason = str(getattr(exc, "reason", exc))
            kind = "timeout" if isinstance(exc, TimeoutError) or "timed out" in reason.lower() else "connection_error"
            _log(f"Response not received: {method} {path} reason={reason!r} attempt={attempt + 1}/{attempts}")
            if attempt + 1 < attempts:
                continue
            _log(f"ESP32 offline: {kind}")
            raise ESPRequestError(kind, reason) from exc


def get_esp_status(settings: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
    """GET /status - device/WiFi/fingerprint-sensor health + loaded member count.

    Never raises: on any failure returns {"success": False, "error_kind", "error_detail"}
    instead, so callers can always just check result["success"].
    """
    try:
        result = _request(settings, "GET", "/status", timeout=timeout)
        if result.get("success") is not True or result.get("device") != "HULK_GYM":
            _log("Invalid status response")
            return {
                "success": False,
                "error": "invalid_status_response",
                "response": result,
            }
        _log("Status OK")
        return result
    except ESPRequestError as exc:
        _log(f"Status failed: {exc.kind}")
        return {"success": False, "error_kind": exc.kind, "error_detail": exc.detail}


def validate_members_payload(members: Dict[str, Any]) -> Optional[str]:
    """Ensure the payload matches the strict schema the ESP32 expects.

    Members must be a dict mapping member_id -> {fingerprint_id: int, allowed: bool}.
    Any unexpected fields, names, or non-int fingerprint IDs are rejected here before
    wasting an HTTP round-trip. Returns None on success or an error string on error.
    """
    if not isinstance(members, dict):
        return "invalid_members"
    if len(members) > 1000:
        return "database_too_large"
    for member_id, record in members.items():
        if not isinstance(member_id, str) or not member_id.strip():
            return "invalid_member_id"
        if not isinstance(record, dict):
            return "invalid_member_record"
        if set(record.keys()) != {"fingerprint_id", "allowed"}:
            return "invalid_member_record"
        fingerprint_id = record.get("fingerprint_id")
        if isinstance(fingerprint_id, bool) or not isinstance(fingerprint_id, int) or not 1 <= fingerprint_id <= 1000:
            return "invalid_fingerprint_id"
        if not isinstance(record.get("allowed"), bool):
            return "invalid_allowed_flag"
    return None


def push_members(settings: Dict[str, Any], members: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
    """POST /members - push the complete {member_id: {fingerprint_id, allowed}} database."""
    validation_error = validate_members_payload(members)
    if validation_error:
        _log(f"Sync failed before request: {validation_error}")
        return {"success": False, "error": validation_error}
    try:
        _log(f"Syncing {len(members)} members")
        result = _request(
            settings,
            "POST",
            "/members",
            payload={"members": members},
            timeout=timeout,
            retries=2,
        )
        result.setdefault("success", False)
        _log("Sync successful" if result.get("success") else "Sync failed")
        return result
    except ESPRequestError as exc:
        _log(f"Sync failed: {exc.kind}")
        return {"success": False, "error_kind": exc.kind, "error_detail": exc.detail}


def enroll_member(settings: Dict[str, Any], member_id: str, timeout: float = 90.0) -> Dict[str, Any]:
    """POST /enroll with no automatic retry because the sensor may be active."""
    member_id = str(member_id).strip()
    if not member_id:
        return {"success": False, "error": "invalid_member_id"}
    enrollment_started_at = time.monotonic()
    try:
        _log(f"Enrollment started: {member_id}")
        result = _request(
            settings,
            "POST",
            "/enroll",
            payload={"member_id": member_id},
            timeout=timeout,
            retries=0,
        )
        if result.get("success") is True:
            fingerprint_id = result.get("fingerprint_id")
            if isinstance(fingerprint_id, bool) or not isinstance(fingerprint_id, int) or not 1 <= fingerprint_id <= 1000:
                return {
                    "success": False,
                    "member_id": member_id,
                    "error": "invalid_fingerprint_id",
                    "response": result,
                }
        else:
            result["success"] = False
        _log(
            f"Enrollment successful: fingerprint_id={result.get('fingerprint_id')}"
            if result.get("success") else "Enrollment failed"
        )
        return result
    except ESPRequestError as exc:
        _log(f"Enrollment failed: {exc.kind}")
        if exc.kind == "connection_error" and "closed" in exc.detail.lower():
            remaining_wait = max(0.0, 60.0 - (time.monotonic() - enrollment_started_at))
            _log(f"Enrollment connection closed; continuing to wait {remaining_wait:.1f}s before reporting unknown result")
            if remaining_wait:
                time.sleep(remaining_wait)
            return {
                "success": False,
                "member_id": str(member_id),
                "error": "enrollment_response_lost",
                "error_detail": "ESP closed the enrollment connection before returning the final response",
            }
        return {
            "success": False,
            "member_id": str(member_id),
            "error_kind": exc.kind,
            "error_detail": exc.detail,
        }


def get_enroll_status(settings: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
    """Read the short-lived asynchronous enrollment state from the ESP."""
    try:
        result = _request(settings, "GET", "/enroll_status", timeout=timeout, retries=0)
        _log(f"Enrollment status: {result}")
        return result
    except ESPRequestError as exc:
        _log(f"Enrollment status failed: {exc.kind}")
        return {"success": False, "error_kind": exc.kind, "error_detail": exc.detail}


def cancel_enrollment(settings: Dict[str, Any], member_id: str, timeout: float = 5.0) -> Dict[str, Any]:
    """Request cancellation of the active ESP enrollment, if firmware supports it."""
    member_id = str(member_id).strip()
    if not member_id:
        return {"success": False, "error": "invalid_member_id"}
    try:
        _log(f"Enrollment cancellation requested: {member_id}")
        result = _request(
            settings,
            "POST",
            "/cancel_enroll",
            payload={"member_id": member_id},
            timeout=timeout,
            retries=0,
        )
        result.setdefault("success", False)
        return result
    except ESPRequestError as exc:
        return {
            "success": False,
            "member_id": member_id,
            "error_kind": exc.kind,
            "error_detail": exc.detail,
        }


def get_last_scan(settings: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
    """Read the latest lightweight scan event from the ESP."""
    try:
        return _request(settings, "GET", "/last_scan", timeout=timeout, retries=0)
    except ESPRequestError as exc:
        return {"success": False, "error_kind": exc.kind, "error_detail": exc.detail}


def display_member(settings: Dict[str, Any], member_data: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
    """Send full display-only member data to the ESP after a new scan."""
    try:
        result = _request(settings, "POST", "/display_member", payload=member_data, timeout=timeout, retries=0)
        result.setdefault("success", False)
        return result
    except ESPRequestError as exc:
        return {"success": False, "error_kind": exc.kind, "error_detail": exc.detail}


def delete_fingerprint(settings: Dict[str, Any], fingerprint_id: Any, timeout: float = 5.0) -> Dict[str, Any]:
    """DELETE /fingerprint by R307 fingerprint ID."""
    if isinstance(fingerprint_id, bool) or not isinstance(fingerprint_id, int) or not 1 <= fingerprint_id <= 1000:
        return {"success": False, "error": "invalid_fingerprint_id"}
    try:
        _log(f"Deleting fingerprint: {fingerprint_id}")
        result = _request(
            settings,
            "POST" if settings.get("use_post_for_delete") else "DELETE",
            "/fingerprint",
            payload={"fingerprint_id": fingerprint_id},
            timeout=timeout,
            retries=2,
        )
        result.setdefault("success", False)
        _log("Fingerprint deletion successful" if result.get("success") else "Fingerprint deletion failed")
        return result
    except ESPRequestError as exc:
        _log(f"Fingerprint deletion failed: {exc.kind}")
        return {
            "success": False,
            "fingerprint_id": fingerprint_id,
            "error_kind": exc.kind,
            "error_detail": exc.detail,
        }


def clear_all_fingerprints(settings: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
    """Wipe all fingerprint templates from the ESP R307 sensor database."""
    try:
        _log("Wiping all fingerprints from sensor...")
        result = _request(
            settings,
            "POST",
            "/clear_fingerprints",
            timeout=timeout,
            retries=1,
        )
        result.setdefault("success", False)
        _log("All fingerprints wiped successfully" if result.get("success") else "Fingerprints wipe failed")
        return result
    except ESPRequestError as exc:
        _log(f"Fingerprints wipe failed: {exc.kind}")
        return {
            "success": False,
            "error_kind": exc.kind,
            "error_detail": exc.detail,
        }
