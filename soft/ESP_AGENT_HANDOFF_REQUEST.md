# Message for the ESP Agent

I have a desktop app (Python/PySide6) that manages gym members and needs to control a fingerprint-based entry system on an ESP32/ESP8266 (already connected to WiFi + has a fingerprint sensor wired up, but no access-control logic yet).

Here's what my app can already do on its side:
- It knows each member by a `member_id` string (e.g. `"MEM-00001"`) and a `fingerprint_id` (whatever numeric/string ID your enrollment gives back). It does **not** need to store or receive member names/mobile numbers on your side — keep it minimal, just `member_id` ↔ `fingerprint_id`.
- It knows the ESP's IP and port from a settings screen (currently `192.168.1.254:80`, both configurable).
- Whenever a member's active/expired status changes (new payment, renewal, expiry, deletion), my app can immediately send you an updated `{member_id: true/false}` map over HTTP.
- When a member pays for a new/renewed subscription and doesn't have a `fingerprint_id` yet, my app wants to trigger an enrollment and wait for a result (success + new fingerprint_id, or a failure it can retry).
- When a member is deleted, my app wants to tell you to remove their fingerprint.

Please tell me exactly:
1. What HTTP endpoints/methods/ports you want my app to call (or does your ESP call out to my app instead? — either way is fine, just tell me which).
2. The exact JSON request/response shape for: pushing the permissions map, enrolling a new fingerprint, deleting a fingerprint, and (if needed) checking status.
3. Timeouts/retry expectations (e.g. how long enrollment can take, whether it's synchronous or you need me to poll a status endpoint).
4. Any authentication or error-code conventions you want to use.

Once you give me that contract, I'll wire my Python client to match it exactly.
