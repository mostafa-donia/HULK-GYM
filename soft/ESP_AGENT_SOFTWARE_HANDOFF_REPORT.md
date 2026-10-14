# HULK GYM ESP32 Integration
## Python Software Handoff Report

Updated: 2026-09-09

This report describes what has been implemented on the Python/PySide6 desktop application side for the HULK GYM ESP32 fingerprint terminal.

The ESP32 firmware remains a separate project. No ESP32 firmware code is included in this report, and the Python application does not decide access during fingerprint scanning.

---

## 1. Architecture

```text
Python/PySide6 Desktop App
        |
        | HTTP JSON over local WiFi
        v
ESP32 HTTP Server
        |
        v
R307 Fingerprint Sensor
        |
        v
ESP32 local authorization database
        |
        v
ESP32 decides ALLOWED / DENIED locally
```

Responsibilities:

### Python desktop application

- Master member database
- Member names, mobile numbers, payments, plans, and subscription dates
- Active/expired membership status
- Member IDs
- Fingerprint enrollment commands
- Fingerprint deletion commands
- Complete authorization database synchronization
- ESP connection/status display
- Error reporting when ESP is offline or rejects an operation

### ESP32

- R307 fingerprint sensor
- Fingerprint enrollment
- Fingerprint deletion
- Fingerprint matching
- Local authorization database
- Offline ALLOWED / DENIED decision
- TFT display
- WiFi and HTTP server

The Python application is not needed for every fingerprint scan.

---

## 2. Python Files Changed

### `v1/esp_client.py`

Centralized dependency-free HTTP client using Python's built-in `urllib` module.

Implemented functions:

```python
get_esp_status(settings)
push_members(settings, members)
enroll_member(settings, member_id)
delete_fingerprint(settings, fingerprint_id)
```

The ESP IP and port are read from the existing application settings.

Default configuration:

```text
IP: 192.168.1.254
Port: 80
Base URL: http://192.168.1.254:80
```

The application does not scatter the ESP IP across the codebase.

### `v1/app.py`

Integrated the ESP client with the existing application:

- ESP settings are loaded and saved through the existing Settings page.
- Existing member records support `fingerprint_id`.
- Existing member table displays the complete member ID and fingerprint ID.
- Existing member details page contains:
  - Register fingerprint
  - Delete fingerprint
  - Synchronize ESP
- Fingerprint page displays:
  - ESP status
  - Total members
  - Members with fingerprints
  - Members without fingerprints
  - Manual synchronization controls
- Startup synchronization runs in the background.
- Member saves can trigger complete ESP synchronization.
- Synchronization uses a shared lock to avoid overlapping sync operations.

### `v1/tests/test_esp_client_contract.py`

Contains mocked HTTP contract tests for status, synchronization, enrollment, deletion, validation, retry behavior, and invalid responses.

### `v1/tests/test_whatsapp_rate_limit.py`

Existing WhatsApp regression tests. The test loader was updated so dynamic `app.py` imports can resolve the sibling `esp_client.py` module.

---

## 3. Exact HTTP Contract

The ESP32 is the HTTP server.

The Python application is the HTTP client.

HTTP port:

```text
80
```

The endpoints are root endpoints. Do not add `/api` to the paths.

Correct:

```text
/status
/members
/enroll
/fingerprint
```

Incorrect for the current Python client:

```text
/api/status
/api/members
/api/enroll
/api/delete_fingerprint
```

---

## 4. GET `/status`

Python request:

```http
GET /status
```

Expected response:

```json
{
  "success": true,
  "device": "HULK_GYM",
  "wifi": "connected",
  "fingerprint": true,
  "members": 25
}
```

Allowed WiFi values:

```text
connected
hosting
reconnecting
disconnected
```

Python validates:

- `success` must be exactly `true`.
- `device` must be exactly `HULK_GYM`.

If either validation fails, Python reports:

```json
{
  "success": false,
  "error": "invalid_status_response"
}
```

The status request uses a normal 5-second timeout.

The fingerprint page displays the status result without redesigning the existing application.

---

## 5. POST `/members`

Purpose: send the complete authorization database to the ESP32.

Python sends the complete database, not only changed members.

Request:

```http
POST /members
Content-Type: application/json
```

Example body:

```json
{
  "members": {
    "MEM-00001": {
      "fingerprint_id": 7,
      "allowed": true
    },
    "MEM-00002": {
      "fingerprint_id": 12,
      "allowed": false
    }
  }
}
```

The ESP32 should respond with:

```json
{
  "success": true,
  "members": 2
}
```

The Python application only sends these fields:

- `member_id`
- `fingerprint_id`
- `allowed`

The Python application never sends:

- Member name
- Mobile number
- Payment amount
- Payment method
- Plan price
- Notes
- Personal data

### Payload validation performed by Python

Before sending, Python validates:

- Payload is a dictionary.
- Maximum 1000 records.
- Member ID is a non-empty string.
- Each member record contains exactly `fingerprint_id` and `allowed`.
- `fingerprint_id` is an integer from 1 through 1000.
- `allowed` is a real boolean.
- Extra fields are rejected before any HTTP request.

Examples of invalid payloads rejected locally:

```json
{
  "MEM-00001": {
    "fingerprint_id": 0,
    "allowed": true
  }
}
```

```json
{
  "MEM-00001": {
    "fingerprint_id": 7,
    "allowed": true,
    "name": "Private data that must not be sent"
  }
}
```

Expected ESP error responses should remain JSON:

```json
{
  "success": false,
  "error": "invalid_members"
}
```

Other expected error values may include:

```text
invalid_json
invalid_members
invalid_member_id
invalid_fingerprint_id
invalid_allowed
database_too_large
storage_error
```

Python does not report synchronization success unless the ESP response contains `success: true`.

---

## 6. POST `/enroll`

Purpose: start physical R307 enrollment.

Request:

```http
POST /enroll
Content-Type: application/json
```

Body:

```json
{
  "member_id": "MEM-00003"
}
```

Only `member_id` is sent.

The ESP32 should perform the complete physical enrollment process and return only after the operation finishes.

Expected success response:

```json
{
  "success": true,
  "member_id": "MEM-00003",
  "fingerprint_id": 13
}
```

Expected failure response:

```json
{
  "success": false,
  "member_id": "MEM-00003",
  "error": "enrollment_failed"
}
```

Possible error values:

```text
timeout
enrollment_failed
finger_already_exists
sensor_error
invalid_member_id
```

### Enrollment timing

- Python timeout: 90 seconds, allowing the ESP time to finish enrollment and return its final JSON response.
- Python does not automatically retry enrollment.
- The GUI runs enrollment in a `QThread`, so the desktop application remains responsive.
- The user must explicitly choose Retry after a failure.
- The user can choose Cancel.

### Important database behavior

The ESP32 must not modify `/members.json` from `/enroll`.

The enrollment endpoint only enrolls the R307 fingerprint and returns the assigned ID.

After Python receives the ID:

1. Python validates that it is an integer from 1 through 1000.
2. Python saves it to the local member record.
3. Python derives `allowed` from the existing membership status.
4. Python sends the complete `/members` database to the ESP32.

The ESP32 should not assume enrollment means the member is allowed.

### Enrollment cancellation requirement

The current Python GUI Cancel button sends an optional request to:

```http
POST /cancel_enroll
Content-Type: application/json
```

Body:

```json
{
  "member_id": "MEM-00003"
}
```

The ESP firmware must implement this endpoint if Cancel must physically stop an
enrollment that is already running. It should stop the R307 enrollment loop,
restore normal fingerprint scanning, and return:

```json
{
  "success": true,
  "member_id": "MEM-00003"
}
```

If the endpoint is not implemented, Python can only cancel the local waiting UI;
it cannot remotely interrupt a synchronous HTTP request already being processed
by the ESP. Python reports this as `cancel_unsupported`/HTTP 404 and does not
pretend that the ESP stopped.

---

## 7. DELETE `/fingerprint`

Purpose: remove one R307 fingerprint template.

Request:

```http
DELETE /fingerprint
Content-Type: application/json
```

Body:

```json
{
  "fingerprint_id": 13
}
```

Expected success response:

```json
{
  "success": true,
  "fingerprint_id": 13
}
```

Expected failure response:

```json
{
  "success": false,
  "fingerprint_id": 13,
  "error": "delete_failed"
}
```

Possible errors:

```text
invalid_fingerprint_id
not_found
sensor_error
delete_failed
```

Python validates the ID before sending:

- Integer only
- Range 1 through 1000
- Boolean and string values are rejected

### Delete workflow

Python follows this order:

1. Read the member's local `fingerprint_id`.
2. Call `DELETE /fingerprint`.
3. Wait for ESP confirmation.
4. Only after `success: true`, clear the local fingerprint ID.
5. Push the complete updated `/members` database.

If ESP deletion fails:

- Python member data remains unchanged.
- Python does not report success.
- The user sees a deletion failure message.

Membership expiration does not delete the fingerprint. Expiration only changes `allowed` to `false`.

The ESP32 should not modify `/members.json` from the fingerprint deletion endpoint.

---

## 8. Synchronization Behavior

The Python member database is the master database.

The ESP32 keeps a local copy for offline authorization.

Synchronization happens through the complete `/members` payload.

Synchronization can be triggered by:

- Manual Sync ESP32 button
- Startup background synchronization
- Member save operations
- Enrollment success
- Fingerprint deletion success
- Membership status changes through existing save/status paths

The synchronization worker performs:

1. `GET /status`
2. Build the complete minimal authorization payload
3. `POST /members`
4. Show or log success/failure

The application uses a shared synchronization lock so multiple sync operations do not overlap.

If ESP is offline:

- Python continues working locally.
- The Python master database is not corrupted.
- The UI reports ESP offline or synchronization failure.
- Python does not claim that the ESP database is current.

---

## 9. GUI Behavior

### Fingerprint page

The existing **جهاز البصمة** page contains:

- Test ESP connection
- Manual Sync ESP32
- Two-member test push controls
- Allow/deny test controls for `MEM-00001`
- Total member count
- Number of members with fingerprints
- Number of members without fingerprints
- Sync result state

### Member details page

The existing member details page contains:

- Register fingerprint
- Delete fingerprint
- Sync ESP

Enrollment behavior:

1. User selects a member.
2. User clicks تسجيل البصمة.
3. User confirms the enrollment dialog.
4. ESP status is checked.
5. Enrollment starts in a background thread.
6. The waiting dialog remains visible while the GUI stays responsive.
7. Success saves the returned fingerprint ID and synchronizes the complete database.
8. Failure leaves the local member unchanged.
9. Failure offers Retry or Cancel.

Enrollment is never started automatically after payment or renewal without user confirmation.

---

## 10. Error Handling

Normal requests use a 5-second timeout and may retry connection failures up to two times.

Enrollment uses a 90-second timeout and does not retry automatically.

The Python client handles:

- Connection refused
- ESP offline
- Timeout
- HTTP 400
- HTTP 404
- HTTP 409
- HTTP 500
- Invalid JSON
- Invalid status response
- Invalid member payload
- Missing fingerprint ID
- Invalid fingerprint ID
- Enrollment failure
- Fingerprint deletion failure
- Synchronization failure

Python never reports success based only on HTTP 200. The JSON response must confirm `success: true`.

---

## 11. Logging

The Python client logs non-sensitive events such as:

```text
[ESP] Connecting GET /status
[ESP] Status OK
[ESP] ESP32 offline: timeout
[ESP] Syncing 105 members
[ESP] Sync successful
[ESP] Sync failed
[ESP] Enrollment started: MEM-00003
[ESP] Enrollment successful: fingerprint_id=13
[ESP] Enrollment failed
[ESP] Deleting fingerprint: 13
[ESP] Fingerprint deletion successful
```

Names, phone numbers, passwords, payment data, and other unnecessary personal data are not logged by the ESP client.

---

## 12. Python Test Results

The local mocked Python tests currently pass:

```text
ESP client contract tests: 16 passed
WhatsApp regression tests: 5 passed
```

The tests cover:

- Exact HTTP methods and paths
- Status validation
- HULK_GYM device validation
- Minimal `/members` payload
- Retry count
- Timeout behavior
- HTTP JSON failures
- Invalid JSON
- Enrollment timeout and no-retry behavior
- Enrollment fingerprint ID validation
- Deletion ID validation
- Deletion failure response
- Maximum 1000 records
- Extra/personal fields rejected before network

These are software/mocked tests only. They do not prove the physical R307 or ESP firmware behavior.

---

## 13. Required ESP32 Verification

The ESP agent should verify the following against the real board:

1. `GET /status` returns `success: true` and `device: "HULK_GYM"`.
2. `POST /members` accepts the complete minimal database.
3. The ESP saves and reloads `/members.json` safely.
4. Reboot preserves the member authorization database.
5. Fingerprint ID 7 with `allowed: true` gives ALLOWED.
6. The same fingerprint with `allowed: false` gives DENIED.
7. `POST /enroll` returns a real R307 fingerprint ID within 60 seconds.
8. `POST /enroll` does not modify `/members.json`.
9. `DELETE /fingerprint` removes only the requested R307 template.
10. `DELETE /fingerprint` does not modify `/members.json`.
11. After deletion, scanning the deleted fingerprint gives NOT FOUND/DENIED.
12. 1000 valid lightweight records can be accepted without freezing or rebooting.
13. The ESP remains able to decide access while the Python PC is offline.
14. All root endpoints work in both WiFi connected and WiFi hosting modes.

Do not claim these physical tests passed until they are actually run on the ESP32/R307 device.

---

## 14. Important Contract Notes

- Use root endpoints, not `/api` endpoints.
- The ESP32 is the HTTP server.
- The Python desktop application is the HTTP client.
- The ESP32 must decide ALLOWED/DENIED locally.
- The Python application must not be queried during every fingerprint scan.
- The ESP32 should store only the minimum authorization data.
- The Python application is the source of truth for full member details.
- Enrollment returns an ID but does not decide authorization.
- Expiration changes `allowed` to false but does not delete the R307 template.
- Permanent deletion removes the R307 template first, then Python clears the local ID after confirmation.
