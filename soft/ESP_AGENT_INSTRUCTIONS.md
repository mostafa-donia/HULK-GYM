# ESP Fingerprint Device Integration - Instructions for ESP Agent

> **Current contract override:** The active Python client uses the ESP32 root
> endpoints `GET /status`, `POST /members`, `POST /enroll`, and
> `DELETE /fingerprint`. Do not use the older `/api/...` paths or the older
> `member_permission.json`-only contract elsewhere in this document. The
> current `/members` payload contains only `member_id`, `fingerprint_id`, and
> `allowed`, with a maximum of 1000 records.

## Overview
The ESP device acts as a fingerprint access control system for HULK GYM. It communicates with the main application via HTTP over the same WiFi network. The ESP is responsible for:
- Managing member fingerprint enrollment
- Allowing/denying access based on membership status
- Maintaining a local database of fingerprint IDs
- Responding to commands from the main application

---

## Network Configuration

### ESP Connection Details
- **IP Address**: 192.168.1.254 (configured in Settings → إعدادات جهاز البصمة (ESP))
- **Port**: 80 (HTTP, also configurable in Settings)
- **Network**: Same WiFi network as the desktop application
- **Communication Protocol**: HTTP REST API

### How to Connect
1. ESP should connect to the same WiFi network as the main application
2. Assign static IP: 192.168.1.254 on the ESP device
3. Verify connectivity: `ping 192.168.1.254` from the desktop application machine
4. ESP must be running and listening on the root endpoints listed in the current contract override above.

---

## Communication Protocol

### Endpoint Base URL
```
http://192.168.1.254
```

---

## 1. Member Permissions File Update

### File Location (on Main App)
`v1/data/member_permission.json`

### File Structure
```json
{
  "last_update": "2026-09-01 16:24:30",
  "members": {
    "MEM-00001": false,
    "MEM-00002": true,
    "MEM-00003": false,
    "MEM-00004": true
  }
}
```

**Fields Explanation:**
- `last_update`: ISO format timestamp of when permissions were last updated
- `members`: Dictionary mapping member_id to boolean
  - `true`: Member can enter (active subscription)
  - `false`: Member cannot enter (expired/no subscription)

### Update Triggers
The `member_permission.json` file is automatically regenerated and updated when:
1. ✅ A new payment is processed (member activated)
2. ✅ Subscription status changes (active → expired or vice versa)
3. ✅ Member is deleted
4. ✅ Manual refresh of member statuses
5. ✅ Any member data is saved

### ESP Action on File Update
The main app now **pushes** the permissions to the ESP automatically (fire-and-forget, background thread) every time `member_permission.json` is regenerated — the ESP does not need to poll:
1. Main app sends `POST /api/permissions` with the full payload below whenever a payment, renewal, deletion, or status refresh changes the file.
2. ESP should reply immediately with `{"status": "ok"}` and update its local access control list from the request body.
3. `GET /api/permissions` is kept as a fallback the ESP can call on boot/reconnect to pull the current state.

### Endpoint: POST /api/permissions (main app → ESP push)
**Request:**
```http
POST /api/permissions HTTP/1.1
Host: 192.168.1.254
Content-Type: application/json

{
  "last_update": "2026-09-01 16:24:30",
  "members": {
    "MEM-00001": false,
    "MEM-00002": true
  }
}
```

**Expected Response (200 OK):**
```json
{
  "status": "ok",
  "message": "permissions updated"
}
```
If the ESP is unreachable, the main app logs the failure and continues — it does not retry automatically, since the next save will push again.

### Endpoint: GET /api/permissions (ESP pull fallback)
**Request:**
```http
GET /api/permissions HTTP/1.1
Host: 192.168.1.254
```

**Response (200 OK):**
```json
{
  "status": "ok",
  "permissions": {
    "MEM-00001": false,
    "MEM-00002": true
  },
  "last_update": "2026-09-01 16:24:30"
}
```

---

## 2. Fingerprint Enrollment Command

### When to Enroll
- **New Member**: When a new subscription is created
- **Renewal without Fingerprint ID**: When a member renews but hasn't been assigned a fingerprint ID yet
- **Re-enrollment**: If member requests new fingerprint registration

### Endpoint: POST /api/enroll
Only `member_id` is sent — the ESP never needs the member's name or mobile number, just enough to pair the new fingerprint slot with this ID.

**Request:**
```http
POST /api/enroll HTTP/1.1
Host: 192.168.1.254
Content-Type: application/json

{
  "member_id": "MEM-00001"
}
```

**Response (200 OK - Success):**
```json
{
  "status": "success",
  "member_id": "MEM-00001",
  "fingerprint_id": 1,
  "message": "تم تسجيل البصمة بنجاح"
}
```

**Response (202 Accepted - In Progress):**
```json
{
  "status": "pending",
  "member_id": "MEM-00001",
  "message": "جاري تسجيل البصمة - ضع إصبعك على القارئ"
}
```

**Response (400 Bad Request - Error):**
```json
{
  "status": "error",
  "member_id": "MEM-00001",
  "error_code": "FINGERPRINT_FAILED",
  "message": "فشل التقاط البصمة - حاول مرة أخرى"
}
```

**Response (409 Conflict - Already Enrolled):**
```json
{
  "status": "error",
  "member_id": "MEM-00001",
  "error_code": "ALREADY_ENROLLED",
  "message": "هذا العضو مسجل بالفعل",
  "fingerprint_id": 1
}
```

### Fingerprint ID Assignment
- Each successfully enrolled fingerprint gets a unique numeric ID (1, 2, 3, ...)
- Store mapping: `member_id → fingerprint_id` in local ESP database — **this pair is the only thing the ESP needs to keep**, no names/mobiles, to keep the shared JSON and ESP storage small
- Return the `fingerprint_id` to the main app
- Main app stores this in member record under `fingerprint_id` field (name/mobile stay in the main app only)

### Retry Logic
- If enrollment fails, prompt user to try again
- Maximum 3 attempts per enrollment request
- If all attempts fail, return error to main app
- User can cancel enrollment at any time

---

## 3. Fingerprint Deletion Command

### When to Delete
- **Member Deletion**: When a member is permanently deleted from the system
- **Voluntary Cancellation**: When member requests to remove their fingerprint

### Endpoint: POST /api/delete_fingerprint
**Request:**
```http
POST /api/delete_fingerprint HTTP/1.1
Host: 192.168.1.254
Content-Type: application/json

{
  "member_id": "MEM-00001",
  "fingerprint_id": 1
}
```

**Response (200 OK - Success):**
```json
{
  "status": "success",
  "member_id": "MEM-00001",
  "fingerprint_id": 1,
  "message": "تم حذف البصمة بنجاح"
}
```

**Response (404 Not Found):**
```json
{
  "status": "error",
  "member_id": "MEM-00001",
  "error_code": "FINGERPRINT_NOT_FOUND",
  "message": "البصمة غير موجودة"
}
```

### Local ESP Action
- Remove fingerprint_id from ESP database
- Free up the fingerprint slot for future enrollment
- Log the deletion with timestamp
- Continue to deny access for this member_id if still in active list

---

## 4. Access Control Validation

### Endpoint: POST /api/validate_fingerprint
**Request (when fingerprint is scanned):**
```http
POST /api/validate_fingerprint HTTP/1.1
Host: 192.168.1.254
Content-Type: application/json

{
  "fingerprint_id": 1
}
```

**Response (200 OK - Access Granted):**
```json
{
  "status": "granted",
  "member_id": "MEM-00001",
  "message": "أهلاً، مرحباً بك",
  "access": true
}
```

**Response (403 Forbidden - Access Denied):**
```json
{
  "status": "denied",
  "member_id": "MEM-00001",
  "reason": "subscription_expired",
  "message": "الاشتراك منتهي - تحديث الاشتراك مطلوب",
  "access": false
}
```

The ESP only needs to echo back `member_id` (not a name) — the main app already has the name locally and doesn't need the ESP to resend it.

**Response (404 Not Found - Unknown Fingerprint):**
```json
{
  "status": "denied",
  "error_code": "FINGERPRINT_NOT_FOUND",
  "message": "البصمة غير مسجلة في النظام",
  "access": false
}
```

### Access Control Logic
```
IF fingerprint_id NOT in local database:
   DENY access → "Fingerprint not found"
ELSE IF member_id corresponding to fingerprint_id NOT in permissions list:
   DENY access → "Member not found in system"
ELSE IF permissions[member_id] == true:
   GRANT access → generic welcome message (no name needed, ESP doesn't store it)
ELSE IF permissions[member_id] == false:
   DENY access → "Subscription expired" or "Not active member"
```

---

## 5. Member Details Query

### When Used
- **Member Search**: When user searches for a member in the UI (name/mobile come from the main app's own data, the ESP is only asked to confirm the fingerprint side)
- **Member Details Page**: When viewing member profile details

### Endpoint: GET /api/member/{member_id}
The ESP only ever answers with `member_id`/`fingerprint_id` — it has no name or mobile to return.

**Request:**
```http
GET /api/member/MEM-00001 HTTP/1.1
Host: 192.168.1.254
```

**Response (200 OK):**
```json
{
  "status": "success",
  "member_id": "MEM-00001",
  "fingerprint_id": 1,
  "fingerprint_status": "enrolled",
  "has_fingerprint": true,
  "enrolled_at": "2026-08-15 10:30:00"
}
```

**Response (404 Not Found):**
```json
{
  "status": "error",
  "member_id": "MEM-00001",
  "error_code": "MEMBER_NOT_FOUND",
  "has_fingerprint": false,
  "fingerprint_id": null
}
```

### UI Integration
The main app will display in member details:
- ✅ Member ID
- ✅ Member Name
- ✅ Mobile
- ✅ **Fingerprint ID** (from ESP)
- ✅ **Fingerprint Status** (enrolled/not_enrolled)
- ✅ **Enrollment Date** (from ESP)

---

## 6. Error Codes Reference

| Error Code | HTTP Status | Meaning | Action |
|---|---|---|---|
| FINGERPRINT_FAILED | 400 | Fingerprint capture failed | Retry enrollment |
| ALREADY_ENROLLED | 409 | Member already has fingerprint | Use existing ID |
| FINGERPRINT_NOT_FOUND | 404 | Fingerprint ID doesn't exist | Check database |
| MEMBER_NOT_FOUND | 404 | Member ID not in system | Verify member exists |
| PERMISSION_DENIED | 403 | Member subscription expired | Update subscription |
| INVALID_REQUEST | 400 | Malformed request | Check JSON format |
| ESP_ERROR | 500 | Internal ESP error | Check ESP logs |
| NETWORK_ERROR | - | Cannot reach ESP | Verify WiFi/IP |

---

## 7. HTTP Status Codes

| Code | Meaning |
|---|---|
| 200 | Success - operation completed |
| 202 | Accepted - operation in progress |
| 400 | Bad Request - invalid input |
| 403 | Forbidden - access denied |
| 404 | Not Found - resource doesn't exist |
| 409 | Conflict - resource already exists |
| 500 | Internal Server Error - ESP error |
| 503 | Service Unavailable - ESP offline |

---

## 8. Implementation Timeline

### Phase 1 (Current - Web Config Only)
✅ Add ESP IP configuration to Settings page (IP: 192.168.1.254, Port: 80)  
✅ Create `member_permission.json` with last_update timestamp  
✅ ESP can read permissions from file  
✅ This prompt document ready for ESP agent  

### Phase 2 (Future - Full Integration)
🔲 Implement `/api/enroll` endpoint on ESP  
🔲 Implement `/api/delete_fingerprint` endpoint on ESP  
🔲 Implement `/api/validate_fingerprint` endpoint on ESP  
🔲 Implement `/api/member/{member_id}` endpoint on ESP  
🔲 Add fingerprint_id field to member records in main app  
🔲 Add "Enroll Fingerprint" button in member details page  
🔲 Add fingerprint status display in member details  
🔲 Add automatic enrollment after successful payment  
🔲 Handle fingerprint deletion when member is deleted  

### Phase 3 (Future - Optional Enhancements)
🔲 Real-time permission sync (WebSocket)  
🔲 Enrollment feedback UI (progress bar, retry counter)  
🔲 Fingerprint template backup/restore  
🔲 Access log query from main app  
🔲 Fingerprint matching statistics  
🔲 Backup ESP with failover  

---

## 9. Testing Checklist

### Before Production
- [ ] ESP connects to WiFi successfully
- [ ] ESP responds to ping on 192.168.1.254
- [ ] ESP listens on HTTP port 80
- [ ] Test all API endpoints with curl/Postman
- [ ] Verify fingerprint sensor working
- [ ] Test enrollment with 3+ members
- [ ] Test access denial for expired members
- [ ] Test member deletion cascade
- [ ] Verify file permissions (read/write)
- [ ] Check network timeout handling
- [ ] Test with various member IDs format (MEM-00001, etc.)

### Network Issues to Handle
- WiFi disconnection → Queue requests, retry on reconnect
- Network timeout (5s+) → Return error to user
- File not found → Create default empty permissions
- Corrupted JSON → Fall back to last known good state
- Port already in use → Use fallback port or fail gracefully

---

## 10. Security Considerations

⚠️ **IMPORTANT**
- ESP should validate member_id format before processing
- Implement rate limiting on enrollment attempts (3 per member)
- Log all access attempts (success/failure) with timestamp
- Fingerprint data should be encrypted at rest on ESP
- Use HTTPS in future (currently HTTP for simplicity)
- Consider adding API key/token authentication if on public network
- Never expose raw fingerprint templates to main app
- Always verify ESP is on trusted network (192.168.x.x)

---

## 11. File Locations Reference

### Main Application (Python)
- Member data: `v1/data/members.json`
- Permissions file: `v1/data/member_permission.json` ← **ESP reads this**
- Settings: `v1/data/settings.json` (contains ESP IP/port config)

### ESP Device
- Local fingerprint database: (implementation dependent)
- Access logs: (implementation dependent)
- Configuration: (implementation dependent)

---

## 12. Command Flow Examples

### Example 1: New Member Subscription
```
1. User creates new member + subscription in main app
2. Payment processed → member status = "active"
3. member_permission.json regenerated with member_id: true
4. Main app prompts: "New member created - Enroll fingerprint?"
5. User scans fingerprint on ESP device
6. ESP calls POST /api/enroll with member_id, receives fingerprint_id
7. Main app stores fingerprint_id in member record
8. Member can now access via fingerprint
```

### Example 2: Membership Renewal
```
1. User renews existing member subscription
2. Payment processed → member status = "active"
3. member_permission.json updated (member_id still true, or changed from false to true)
4. If member has no fingerprint_id yet:
   a. Prompt: "Complete registration - Enroll fingerprint?"
   b. Follow enrollment flow (same as Example 1)
5. If member has fingerprint_id:
   a. Access automatically enabled via updated permissions
   b. No action needed
```

### Example 3: Membership Expiration
```
1. System detects subscription expired (automatic or manual)
2. member_permission.json regenerated with member_id: false
3. ESP updates local permissions list
4. Next fingerprint scan attempt:
   a. ESP recognizes fingerprint
   b. Checks permissions → false
   c. Returns "Subscription expired" message
   d. Access DENIED
```

### Example 4: Member Deletion
```
1. User deletes member from system
2. Member removed from members.json
3. member_permission.json regenerated (member_id removed)
4. Main app detects member deleted
5. Main app calls POST /api/delete_fingerprint with member_id + fingerprint_id
6. ESP removes fingerprint from database
7. Fingerprint slot freed for future use
```

---

## 13. Ready for Implementation

This document contains everything the ESP agent needs to know:
- ✅ Network configuration (IP, port, WiFi)
- ✅ File formats (member_permission.json structure)
- ✅ API endpoints (enroll, delete, validate, query)
- ✅ Request/response formats (JSON payloads)
- ✅ Error handling (status codes, error messages)
- ✅ Access control logic (permission validation)
- ✅ Testing checklist
- ✅ Security considerations
- ✅ Real-world flow examples

**The ESP agent can now implement the firmware without waiting for main app changes!**

---

## 14. Main App Integration Status (Implemented)

The main app now includes:
1. ✅ `fingerprint_id` field on member records (empty string until enrolled)
2. ✅ Automatic enrollment prompt right after a successful new/renewal payment (`start_fingerprint_enrollment`, with retry/cancel on failure)
3. ✅ Automatic `delete_fingerprint` call when a member is deleted (background thread, best-effort)
4. ✅ Automatic `permissions` push to the ESP every time `member_permission.json` is regenerated (background thread, best-effort)
5. ✅ Fingerprint column in the members table + fingerprint number shown in the member details dialog
6. ⏳ Not yet implemented: dedicated "Enroll/Delete Fingerprint" buttons for manual re-trigger, and querying `GET /api/member/{id}` from the main app UI

**All ESP calls are no-ops until "تشغيل الاتصال بـ ESP" is enabled in Settings and the ESP actually implements the endpoints above.**

