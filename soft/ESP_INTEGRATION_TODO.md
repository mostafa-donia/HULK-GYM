# HULK GYM ESP32 Integration TODO

Updated from the latest software-agent prompt on 2026-09-09.

Scope: Python/PySide6 desktop application only. ESP32 firmware is developed separately and is not modified or reviewed as part of this checklist.

## Architecture

- Python desktop app is the master database.
- ESP32 is the HTTP server and keeps a local authorization copy for offline access decisions.
- Python sends only `member_id`, `fingerprint_id`, and `allowed` to the ESP32.
- The ESP32 independently decides ALLOWED/DENIED during fingerprint scanning.
- ESP32 address comes from the existing Settings page, not scattered hardcoded values.

## Already Implemented On Python Side

- [x] ESP IP, port, and enable toggle exist in Settings.
- [x] Centralized dependency-free HTTP helper exists in `v1/esp_client.py`.
- [x] `get_esp_status(settings)` exists for `GET /status`.
- [x] `push_members(settings, members)` exists for `POST /members`.
- [x] Minimal ESP payload builder exists as `Store.esp_members_payload()`.
- [x] Members without a fingerprint are excluded from the ESP authorization payload.
- [x] Existing **جهاز البصمة** page has ESP status and two-member test controls.
- [x] Existing Python member records/display support `fingerprint_id`.
- [x] HTTP responses are parsed as JSON and network/HTTP/invalid-JSON failures are represented as unsuccessful results.

## Remaining Python Tasks

### Task 1 - Verify the current client contract

File: `v1/esp_client.py`

- [x] Confirm `get_esp_status()` calls exactly `GET /status`.
- [x] Confirm status success requires `success == true` and `device == "HULK_GYM"`.
- [x] Confirm `push_members()` calls exactly `POST /members`.
- [x] Confirm normal requests use a 5-second timeout.
- [x] Confirm normal connection failures may retry at most two times.
- [x] Confirm HTTP 400/404/409/500 JSON error bodies remain visible to the caller.
- [x] Confirm no personal information is included in any ESP payload.

**Gate:** passed with 7 mocked tests in `v1/tests/test_esp_client_contract.py`, covering success, connection failure, timeout, HTTP error JSON, invalid JSON, strict status validation, and the minimal push body.

### Task 2 - Implement enrollment client

File: `v1/esp_client.py`

- [x] Add `enroll_member(settings, member_id)` for exactly `POST /enroll`.
- [x] Send exactly `{ "member_id": "MEM-XXXXX" }`.
- [x] Use an approximately 90-second timeout to allow the ESP to finish the R307 operation and return its final response.
- [x] Do not automatically retry enrollment.
- [x] Return the parsed ESP response.
- [x] Treat `success == true` as valid only when `fingerprint_id` is an integer from 1 through 1000.
- [x] Return clear failure data for timeout, connection failure, HTTP failure, invalid JSON, and `enrollment_failed`.

**Gate:** passed with 4 additional enrollment tests (11 total in `test_esp_client_contract.py`), covering payload, timeout, no retry, valid success, missing/invalid ID, and failure/transport responses.

### Task 3 - Implement deletion client

File: `v1/esp_client.py`

- [x] Add `delete_fingerprint(settings, fingerprint_id)` for exactly `DELETE /fingerprint`.
- [x] Send exactly `{ "fingerprint_id": 13 }`.
- [x] Use the normal 5-second timeout and normal network retry policy.
- [x] Validate that the ID is an integer in the valid range.
- [x] Return parsed success/failure response without hiding ESP errors.

**Gate:** passed with 3 deletion tests in `test_esp_client_contract.py` (14 total), covering method/body, ID validation, timeout, retry policy, and ESP failure responses.

### Task 4 - Add non-blocking enrollment workflow

Files: `v1/app.py`, `v1/esp_client.py`

- [x] Reuse the existing `QThread`/worker pattern.
- [x] Add or reuse the minimum existing GUI control for **Enroll Fingerprint**.
- [x] Check ESP status before starting enrollment.
- [x] Show `ENROLLING` / waiting-for-fingerprint state.
- [x] Keep the GUI responsive for the full 60–70-second request.
- [x] On confirmed success, read and validate the returned `fingerprint_id`.
- [x] Save only the returned ID to the selected Python member record.
- [x] Preserve the existing membership status logic when calculating `allowed`.
- [x] Push the complete updated authorization database after saving the ID.
- [x] On any failure, leave the member record unchanged and show `ENROLL FAILED`.
- [x] Do not automatically retry an enrollment that may still be running; retry only after explicit user action.

**Gate:** Python workflow and client tests pass locally. Physical enrollment, returned ID, full sync, and GUI responsiveness on the real ESP/R307 remain pending manual test.

### Task 5 - Synchronize membership state

Files: `v1/app.py`, `v1/esp_client.py`

- [x] Keep `Store.esp_members_payload()` limited to enrolled members and:
  - `member_id`
  - `fingerprint_id`
  - `allowed`
- [x] Ensure `allowed` is derived from the existing active/expired business logic.
- [x] Add or reuse a visible **Sync ESP32** action on the existing fingerprint page.
- [x] Sync the complete database, never only changed members.
- [x] Show `SYNC SUCCESS` only after ESP returns `success == true`.
- [x] Show `SYNC FAILED` / offline state with the actual reason otherwise.
- [x] Ensure member creation, payment, renewal, expiration, activation, deactivation, and suspension can trigger a complete sync.
- [x] Keep the Python database as master if synchronization fails.
- [x] Do not claim the ESP copy is synchronized after a failed request.

**Gate:** Python implementation and regression tests pass. Physical push/reboot/access verification remains pending manual ESP test.

### Task 6 - Add safe permanent deletion workflow

Files: `v1/app.py`, `v1/esp_client.py`

- [x] Add or reuse the minimum existing **Delete Fingerprint** control.
- [x] Require a selected member with a valid `fingerprint_id`.
- [x] Confirm deletion using existing dialog conventions.
- [x] Call `DELETE /fingerprint` before clearing the local ID.
- [x] Clear the local `fingerprint_id` only after ESP returns `success == true`.
- [x] Push the complete updated authorization database after clearing the ID.
- [x] Leave the Python member record unchanged if ESP deletion fails.
- [x] Show `DELETE SUCCESS` only after ESP confirmation.
- [x] Never delete a fingerprint because a membership expired; expiration only changes `allowed` to false.

**Gate:** Python workflow and regression tests pass. Physical R307 deletion and NOT FOUND/DENIED scan remain pending manual ESP test.

### Task 7 - Startup and manual synchronization

Files: `v1/app.py`, `v1/esp_client.py`

- [x] On startup, attempt status/sync without blocking application startup.
- [x] If ESP is offline, continue normal PC operation.
- [x] Show ESP offline/not-synchronized state instead of crashing or claiming success.
- [x] Add/reuse a manual sync action that performs:
  1. `GET /status`
  2. Build complete minimal payload
  3. `POST /members`
  4. Display ESP status and synchronized count
- [x] Avoid duplicate concurrent sync requests.

**Gate:** Python implementation and regression tests pass. Offline startup and physical ESP sync remain pending manual test.

### Task 8 - Database and payload safety

Files: `v1/app.py`, `v1/esp_client.py`

- [x] Validate payload IDs are integers from 1 through 1000.
- [x] Validate no names, phone numbers, payments, or other personal fields enter the request body.
- [x] Ensure no test data overwrites the Python database.
- [x] Ensure a failed sync does not mutate or corrupt the Python master database.
- [x] Generate a fake 1000-record payload without real personal data.
- [x] Push the 1000-record payload only after the smaller workflow tests pass.

**Gate:** local payload validation and 1000-record generation are tested. Physical 1000-record acceptance/responsiveness remains pending manual ESP test.


### Task 9 - Member and fingerprint UI safety

File: `v1/app.py`

- [x] Members table shows the complete member ID in its ID column instead of an abbreviated suffix.
- [x] Fingerprint page shows total members, members with fingerprints, and members without fingerprints.
- [x] Enrollment never starts automatically after payment or renewal.
- [x] Enrollment requires explicit confirmation from the member details page.
- [x] Enrollment failure offers explicit Retry or Cancel actions.
- [x] Enrollment progress cancellation suppresses later success UI and never writes a fingerprint ID.

The previously suggested scan-information popup is not implemented because the current ESP API has no scan-event/status endpoint for the Python app. The ESP remains the local ALLOWED/DENIED authority.

**Gate:** Python UI and regression tests pass. Physical enrollment confirmation, failure retry/cancel, and fingerprint scan behavior remain pending manual ESP test.

### Task 10 - Logging and final verification

Files: `v1/app.py`, `v1/esp_client.py`

- [x] Log useful non-sensitive events:
  - `[ESP] Connecting...`
  - `[ESP] Status OK`
  - `[ESP] ESP32 offline`
  - `[ESP] Syncing N members...`
  - `[ESP] Sync successful`
  - `[ESP] Sync failed`
  - `[ESP] Enrollment started: MEMBER_ID`
  - `[ESP] Enrollment successful: fingerprint_id=N`
  - `[ESP] Fingerprint deletion successful`
- [x] Never log passwords or unnecessary personal data.
- [x] Update stale Python-side ESP documentation to the final `/status`, `/members`, `/enroll`, and `/fingerprint` contract.
- [x] Confirm no new Python package is required if `urllib` remains the HTTP implementation.

**Gate:** Python logging, documentation, syntax, and regression checks pass. Physical ESP end-to-end checks remain pending manual test.

## Final End-to-End Test Sequence

Do not mark any test passed until it is run against the physical ESP32/R307 device.

1. **Status:** call `GET /status`; verify `success`, device `HULK_GYM`, WiFi state, fingerprint state, and member count.
2. **Initial push:** push `MEM-00001` with fingerprint `7`, allowed `true`; push `MEM-00002` with fingerprint `12`, allowed `false`.
3. **Reboot persistence:** reboot the ESP and verify both records remain.
4. **Allowed scan:** scan fingerprint `7`; expect ALLOWED.
5. **Deactivate:** push member 1 with allowed `false`; scan fingerprint `7`; expect DENIED.
6. **Reactivate:** push member 1 with allowed `true`; scan fingerprint `7`; expect ALLOWED.
7. **Enrollment:** enroll one test member; verify ESP returns a real `fingerprint_id`.
8. **Save and sync:** verify Python saves the returned ID and pushes the complete database.
9. **New scan:** scan the enrolled finger; expect ALLOWED when existing membership logic says active.
10. **Delete:** call delete fingerprint and verify ESP confirms R307 deletion.
11. **Deleted scan:** scan the deleted finger; expect NOT FOUND/DENIED.
12. **Stress:** generate and push 1000 fake records; verify request success, `/status` reports 1000, ESP remains responsive, and existing scanning still works.
13. **Offline safety:** disconnect ESP; verify the PC app continues working and reports sync failure/offline without claiming synchronization success.
14. **GUI responsiveness:** perform an enrollment taking 30–60 seconds; verify the desktop UI remains interactive.

## Known Constraints

- Physical ESP/R307 tests require the ESP firmware to implement the exact contract.
- ESP firmware is outside this software checklist and must not be edited from the Python task.
- The Python app may save local master data even when ESP synchronization is unavailable, but it must visibly report that the ESP copy is not synchronized.
