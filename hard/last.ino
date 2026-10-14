#include <SPI.h>
#include <TFT_eSPI.h>
#include <LittleFS.h>
#include <Adafruit_Fingerprint.h>
#include <DFRobotDFPlayerMini.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <ArduinoJson.h>

// =====================================================
// SERIAL DEBUG
// =====================================================
#define SCAN_DEBUG 1
// =====================================================
// R307 MATCHING CONTROL
// =====================================================
// Security Level 1 = most forgiving internal matching.
// The final match is also checked manually using confidence.
//
// Change ONLY this number to tune recognition:
// Lower  = more forgiving
// Higher = stricter
#define R307_SECURITY_LEVEL FINGERPRINT_SECURITY_LEVEL_1
#define R307_MIN_MATCH_SCORE 50

// Result display timeouts
#define FINGERPRINT_NOT_FOUND_DELAY 2000UL
#define FINGERPRINT_KNOWN_RESULT_DELAY 5000UL

// V5: easier matching + 3 scan attempts + multi-angle enrollment retries

#if SCAN_DEBUG
  #define DBG(x) Serial.println(x)
  #define DBG_PRINT(x) Serial.print(x)
#else
  #define DBG(x)
  #define DBG_PRINT(x)
#endif

TFT_eSPI tft = TFT_eSPI();
WebServer server(80);
Preferences prefs;

String savedSSID;
String savedPassword;

bool setupMode = false;

enum WiFiState
{
  WIFI_DISCONNECTED,
  WIFI_RECONNECTING,
  WIFI_CONNECTED,
  WIFI_HOSTING
};

WiFiState wifiState = WIFI_DISCONNECTED;

unsigned long lastWiFiAttempt = 0;
unsigned long wifiConnectStart = 0;

IPAddress local_IP(192, 168, 1, 254);
IPAddress gateway(192, 168, 1, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns1(8, 8, 8, 8);
IPAddress dns2(1, 1, 1, 1);

IPAddress apIP(192, 168, 4, 1);
IPAddress apGateway(192, 168, 4, 1);
IPAddress apSubnet(255, 255, 255, 0);

const char* AP_SSID = "HULK_GYM_SETUP";
const char* AP_PASSWORD = "12345678";

bool wifiStatusVisible = false;
String lastWiFiStatus = "";

// PC connection is tracked separately from WiFi.
// WiFi connected only means the ESP32 joined a WiFi network.
bool pcConnected = false;
unsigned long lastPcHeartbeat = 0;
const unsigned long PC_HEARTBEAT_TIMEOUT = 10000UL;
bool tftReady = false;



// =====================================================
// RGB LED + DFPLAYER MINI
// =====================================================
#define RGB_RED_PIN    25
#define RGB_GREEN_PIN  26
#define RGB_BLUE_PIN   27

#define DFPLAYER_RX_PIN 16   // ESP32 RX <- DFPlayer TX
#define DFPLAYER_TX_PIN 17   // ESP32 TX -> DFPlayer RX
#define DFPLAYER_BAUD   9600

HardwareSerial DFSerial(2);
DFRobotDFPlayerMini dfPlayer;
bool dfPlayerReady = false;
unsigned long blueBlinkTimer = 0;
bool blueBlinkState = false;
void updateBlueBlink()
{
  if (millis() - blueBlinkTimer >= 500)
  {
    blueBlinkTimer = millis();

    blueBlinkState = !blueBlinkState;

    digitalWrite(RGB_BLUE_PIN, blueBlinkState ? HIGH : LOW);
  }
}
void setRGB(bool red, bool green, bool blue)
{
  digitalWrite(RGB_RED_PIN, red ? HIGH : LOW);
  digitalWrite(RGB_GREEN_PIN, green ? HIGH : LOW);
  digitalWrite(RGB_BLUE_PIN, blue ? HIGH : LOW);
}

void playAudio(uint8_t track)
{
  if (dfPlayerReady) dfPlayer.play(track);
}

uint8_t acceptedAudioForDays(int daysLeft)
{
  if (daysLeft > 3) return 2;
  if (daysLeft >= 2) return 4;
  return 5;
}

void initRgbAndDfPlayer()
{
  pinMode(RGB_RED_PIN, OUTPUT);
  pinMode(RGB_GREEN_PIN, OUTPUT);
  pinMode(RGB_BLUE_PIN, OUTPUT);
  setRGB(false, false, false);

  DFSerial.begin(DFPLAYER_BAUD, SERIAL_8N1, DFPLAYER_RX_PIN, DFPLAYER_TX_PIN);

  if (dfPlayer.begin(DFSerial, true, true))
  {
    dfPlayerReady = true;
    dfPlayer.volume(5);
    Serial.println("[DFPLAYER] Ready");
  }
  else
  {
    dfPlayerReady = false;
    Serial.println("[DFPLAYER] Not detected - continuing without audio");
  }
}

// =====================================================
// R307
// =====================================================

HardwareSerial FingerSerial(1);
Adafruit_Fingerprint finger(&FingerSerial);

bool searchMode = true;
bool fingerprintSensorReady = false;

// =====================================================
// TEMPORARY MEMBER DISPLAY / SCAN EVENT
// Full member information is NEVER stored in LittleFS.
// It exists only temporarily in RAM for the 5-second display.
// =====================================================
bool memberDisplayActive = false;
unsigned long memberDisplayUntil = 0;
unsigned long scanSequence = 0;

String displayName = "";
String displayMemberID = "";
String displayPlanType = "";
String displayEndDate = "";
String displayLastPayment = "";
uint16_t displayFingerprintID = 0;
bool displayAllowed = false;
int displayDaysLeft = 0;


// =====================================================
// FINGERPRINT COLOR
// Change this one line whenever you want
// =====================================================

uint16_t fingerprintColor = TFT_GREEN;


// Examples:
// TFT_GREEN
// TFT_CYAN
// TFT_YELLOW
// TFT_ORANGE
// TFT_RED
// TFT_WHITE
//
// Custom:
// tft.color565(0, 255, 80)


// =====================================================
// Fingerprint position / size
// =====================================================

#define FP_X 100
#define FP_Y 190
#define FP_W 120
#define FP_H 120


// =====================================================
// Dynamic UI area
// =====================================================

#define UI_TOP 180
#define UI_BOTTOM 480


// =====================================================
// Animation
// =====================================================

bool fingerprintBright = true;
unsigned long lastPulse = 0;


// =====================================================
// Function declarations
// =====================================================

void drawImage(
  const char *filename,
  int x,
  int y,
  int w,
  int h
);

void drawFingerprint(
  uint16_t color
);

void drawStaticScreen();

void clearDynamicArea();

void showReady();
void showScanning();
void showGranted();
void showDenied(unsigned long duration = FINGERPRINT_KNOWN_RESULT_DELAY);

void showMemberInfo();
void updateMemberDisplay();
void handleLastScan();
void handleDisplayMember();
void handlePcHeartbeat();
void updatePcConnection();
bool findMemberByFingerprint(uint16_t fingerprintID, String &memberID, bool &allowed);

void showEnroll(int id);

void setStatus(
  String txt,
  uint16_t color
);

void setMessage(
  String txt
);

void processSerial();

void searchFingerprint();

bool enrollFingerprint(int id);

bool enrollmentInProgress = false;
volatile bool enrollmentCancelRequested = false;
String enrollmentMemberID = "";

// =====================================================
// ASYNCHRONOUS API ENROLLMENT STATE
// =====================================================
enum AsyncEnrollState {
  ENROLL_IDLE, ENROLL_WAIT_FIRST, ENROLL_REMOVE_FIRST,
  ENROLL_WAIT_SECOND, ENROLL_CREATE_MODEL, ENROLL_RETRY_REMOVE,
  ENROLL_SAVE, ENROLL_DONE, ENROLL_FAILED, ENROLL_CANCELLED
};

AsyncEnrollState asyncEnrollState = ENROLL_IDLE;
int asyncEnrollFingerprintID = -1;
uint8_t asyncEnrollSecondAttempts = 0;
uint8_t asyncEnrollMismatchRetries = 0;
unsigned long asyncEnrollStateStarted = 0;
String asyncEnrollError = "";

void handleCancelEnroll();

bool deleteFingerprint(int id);

void countFingerprints();

bool initFingerprint();
void handleStatus();
void handleMembers();
void handleEnroll();
void handleEnrollStatus();
void startAsyncEnrollment(int id, const String &memberID);
void processAsyncEnrollment();
void finishAsyncEnrollment(bool success, bool cancelled, const String &error);
void handleCancelEnroll()
{
  Serial.println("[API] /cancel_enroll");
  if (!enrollmentInProgress)
  {
    server.send(409, "application/json", "{\"success\":false,\"error\":\"no_enrollment_in_progress\"}");
    return;
  }
  JsonDocument request;
  DeserializationError error = deserializeJson(request, server.arg("plain"));
  if (error)
  {
    server.send(400, "application/json", "{\"success\":false,\"error\":\"invalid_json\"}");
    return;
  }
  String memberID = request["member_id"] | "";
  memberID.trim();
  if (memberID.length() > 0 && memberID != enrollmentMemberID)
  {
    server.send(409, "application/json", "{\"success\":false,\"error\":\"member_mismatch\"}");
    return;
  }
  enrollmentCancelRequested = true;
  Serial.println("[API] Enrollment cancellation requested");
  server.send(200, "application/json", "{\"success\":true,\"cancel_requested\":true}");
}

void handleDeleteFingerprint();
int findNextFingerprintID();
bool saveMembersDatabase(JsonDocument &doc);
int getMemberCount();

void drawWiFiStatus()
{
  if (!tftReady) return;

  String status;
  uint16_t color;

  // This box now represents the WiFi link only.
  if (wifiState == WIFI_CONNECTED)
  {
    status = "WIFI: CONNECTED";
    color = TFT_GREEN;
  }
  else if (wifiState == WIFI_RECONNECTING)
  {
    status = "WIFI: RECONNECTING";
    color = TFT_YELLOW;
  }
  else if (wifiState == WIFI_HOSTING)
  {
    status = "WIFI: HOSTING";
    color = TFT_CYAN;
  }
  else
  {
    status = "WIFI: DISCONNECTED";
    color = TFT_RED;
  }

  // Do not redraw the box every loop. This was causing visible flashing.
  if (status == lastWiFiStatus) return;
  lastWiFiStatus = status;

  tft.fillRect(40, 35, 240, 25, TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(color, TFT_BLACK);
  tft.drawString(status, 160, 45, 2);

}

void updateWiFiState()
{
  WiFiState newState;

  if (WiFi.status() == WL_CONNECTED)
  {
    newState = WIFI_CONNECTED;
  }
  else if (wifiState == WIFI_HOSTING)
  {
    newState = WIFI_HOSTING;
  }
  else if (savedSSID.length() == 0)
  {
    newState = WIFI_HOSTING;
  }
  else
  {
    newState = WIFI_RECONNECTING;

    if (millis() - wifiConnectStart >= 20000)
    {
      Serial.println("WiFi connection timeout");
      Serial.println("Starting WiFi HOSTING...");

      WiFi.softAPConfig(
        apIP,
        apGateway,
        apSubnet
      );

      WiFi.softAP(
        AP_SSID,
        AP_PASSWORD
      );

      newState = WIFI_HOSTING;

    }
    else if (millis() - lastWiFiAttempt >= 10000)
    {
      lastWiFiAttempt = millis();

      WiFi.begin(
        savedSSID.c_str(),
        savedPassword.c_str()
      );

      Serial.println("WiFi reconnect attempt");
    }
  }

  wifiState = newState;

  drawWiFiStatus();
}

void loadWiFiCredentials()
{
  prefs.begin("wifi", true);

  savedSSID = prefs.getString("ssid", "");
  savedPassword = prefs.getString("pass", "");

  prefs.end();

  Serial.print("Saved SSID: ");
  Serial.println(savedSSID);
}


void handleRoot()
{
    String html = R"rawliteral(

<!DOCTYPE html>

<html>

<head>

<meta name="viewport"
content="width=device-width, initial-scale=1">

<title>HULK GYM</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    min-height: 100vh;

    background:
        linear-gradient(
            135deg,
            #050505,
            #111111
        );

    color: white;

    font-family:
        Arial,
        sans-serif;

    display: flex;

    justify-content: center;

    align-items: center;
}


.card {

    width: 92%;

    max-width: 430px;

    background: #101010;

    border: 2px solid #9cff00;

    border-radius: 22px;

    padding: 30px;

    box-shadow:
        0 0 30px
        rgba(156,255,0,0.25);
}


.logo {

    text-align: center;

    color: #9cff00;

    font-size: 32px;

    font-weight: 900;

    letter-spacing: 2px;

    margin-bottom: 5px;
}


.title {

    text-align: center;

    font-size: 20px;

    font-weight: bold;

    margin-bottom: 8px;
}


.subtitle {

    text-align: center;

    color: #888;

    font-size: 14px;

    margin-bottom: 30px;
}


label {

    display: block;

    color: #9cff00;

    font-weight: bold;

    margin-bottom: 8px;
}


input {

    width: 100%;

    padding: 15px;

    margin-bottom: 20px;

    border-radius: 10px;

    border: 1px solid #444;

    background: #050505;

    color: white;

    font-size: 16px;

    outline: none;
}


input:focus {

    border-color: #9cff00;

    box-shadow:
        0 0 10px
        rgba(156,255,0,0.25);
}


button {

    width: 100%;

    padding: 16px;

    border: none;

    border-radius: 10px;

    background: #9cff00;

    color: #050505;

    font-size: 17px;

    font-weight: 900;

    cursor: pointer;
}


button:active {

    transform:
        scale(0.98);
}


.footer {

    text-align: center;

    color: #666;

    font-size: 12px;

    margin-top: 25px;
}

</style>

</head>


<body>

<div class="card">

    <div class="logo">
        HULK GYM
    </div>

    <div class="title">
        Wi-Fi Setup
    </div>

    <div class="subtitle">
        Connect your fingerprint terminal
    </div>


    <form
        action="/save"
        method="POST">


        <label>
            Wi-Fi Network
        </label>

        <input
            type="text"
            name="ssid"
            placeholder="Wi-Fi name"
            autocomplete="off"
            required>


        <label>
            Wi-Fi Password
        </label>

        <input
            type="password"
            name="password"
            placeholder="Wi-Fi password"
            required>


        <button type="submit">
            SAVE & CONNECT
        </button>


    </form>


    <div class="footer">
        HULK GYM Smart Fitness System
    </div>

</div>

</body>

</html>

)rawliteral";

    server.send(
        200,
        "text/html",
        html
    );
}

void handleSave()
{
  String ssid = server.arg("ssid");
  String password = server.arg("password");

  Serial.println("=== WIFI FORM RECEIVED ===");
  Serial.print("SSID: ");
  Serial.println(ssid);
  Serial.print("Password: ");
  Serial.println(password);

  prefs.begin("wifi", false);

  prefs.putString("ssid", ssid);
  prefs.putString("pass", password);

  prefs.end();

  server.send(
    200,
    "text/plain",
    "WiFi credentials saved"
  );
}

// =====================================================
// MEMBERS DATABASE + HTTP API
// =====================================================

int getMemberCount()
{
  File file = LittleFS.open("/members.json", "r");
  if (!file) return 0;

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, file);
  file.close();
  if (error) return 0;

  JsonObject members = doc["members"].as<JsonObject>();
  if (members.isNull()) return 0;
  return members.size();
}

bool saveMembersDatabase(JsonDocument &doc)
{
  JsonObject members = doc["members"].as<JsonObject>();

  if (members.isNull())
  {
    Serial.println("[MEMBERS] Missing members object");
    return false;
  }

  if (members.size() > 1000)
  {
    Serial.println("[MEMBERS] Too many members");
    return false;
  }

  bool used[1001] = {false};

  for (JsonPair member : members)
  {
    JsonObject data = member.value().as<JsonObject>();

    if (data.isNull())
    {
      Serial.println("[MEMBERS] Invalid member object");
      return false;
    }

    int fpID = data["fingerprint_id"] | 0;
    if (fpID < 1 || fpID > 1000)
    {
      Serial.println("[MEMBERS] Invalid fingerprint_id");
      return false;
    }

    if (used[fpID])
    {
      Serial.println("[MEMBERS] Duplicate fingerprint_id");
      return false;
    }
    used[fpID] = true;

    if (!data["allowed"].is<bool>())
    {
      Serial.println("[MEMBERS] Invalid allowed value");
      return false;
    }
  }

  File file = LittleFS.open("/members.tmp", "w");
  if (!file)
  {
    Serial.println("[MEMBERS] Failed to open temp file");
    return false;
  }

  size_t written = serializeJson(doc, file);
  file.close();

  if (written == 0)
  {
    LittleFS.remove("/members.tmp");
    Serial.println("[MEMBERS] Failed to write database");
    return false;
  }

  // Verify the file before replacing the live database.
  File verify = LittleFS.open("/members.tmp", "r");
  if (!verify)
  {
    LittleFS.remove("/members.tmp");
    return false;
  }

  JsonDocument verifyDoc;
  DeserializationError verifyError = deserializeJson(verifyDoc, verify);
  verify.close();

  if (verifyError || verifyDoc["members"].isNull())
  {
    LittleFS.remove("/members.tmp");
    Serial.println("[MEMBERS] Database verification failed");
    return false;
  }

  LittleFS.remove("/members.json");
  if (!LittleFS.rename("/members.tmp", "/members.json"))
  {
    Serial.println("[MEMBERS] Failed to activate database");
    return false;
  }

  Serial.print("[MEMBERS] Saved: ");
  Serial.println(members.size());
  return true;
}

bool isFingerprintAllowed(uint16_t fingerprintID)
{
  File file = LittleFS.open("/members.json", "r");

  if (!file)
  {
    Serial.println("[MEMBERS] Database not found");
    return false;
  }

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, file);
  file.close();

  if (error)
  {
    Serial.print("[MEMBERS] JSON error: ");
    Serial.println(error.c_str());
    return false;
  }

  JsonObject members = doc["members"].as<JsonObject>();
  if (members.isNull()) return false;

  for (JsonPair member : members)
  {
    JsonObject data = member.value().as<JsonObject>();
    int fpID = data["fingerprint_id"] | 0;
    bool allowed = data["allowed"] | false;

    if (fpID == fingerprintID)
      return allowed;
  }

  return false;
}

void handleStatus()
{
  Serial.println("[API] /status");

  JsonDocument response;
  response["success"] = true;
  response["device"] = "HULK_GYM";

  if (wifiState == WIFI_CONNECTED) response["wifi"] = "connected";
  else if (wifiState == WIFI_HOSTING) response["wifi"] = "hosting";
  else if (wifiState == WIFI_RECONNECTING) response["wifi"] = "reconnecting";
  else response["wifi"] = "disconnected";

  response["fingerprint"] = fingerprintSensorReady;
  response["pc_connected"] = pcConnected;
  response["members"] = getMemberCount();

  String output;
  serializeJson(response, output);
  server.send(200, "application/json", output);
}

void handleMembers()
{
  Serial.println("[API] /members received");

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, server.arg("plain"));

  if (error)
  {
    Serial.print("[API] JSON error: ");
    Serial.println(error.c_str());
    server.send(400, "application/json", "{\"success\":false,\"error\":\"invalid_json\"}");
    return;
  }

  if (!saveMembersDatabase(doc))
  {
    server.send(400, "application/json", "{\"success\":false,\"error\":\"invalid_members\"}");
    return;
  }

  JsonDocument response;
  response["success"] = true;
  response["members"] = getMemberCount();

  String output;
  serializeJson(response, output);
  server.send(200, "application/json", output);
}

int findNextFingerprintID()
{
  for (int id = 1; id <= 1000; id++)
  {
    uint8_t p = finger.loadModel(id);
    if (p != FINGERPRINT_OK)
      return id;
    delay(2);
  }
  return -1;
}

void handleEnroll()
{
  Serial.println("[API] /enroll");
  if (enrollmentInProgress)
  {
    server.send(409, "application/json", "{\"success\":false,\"error\":\"enrollment_in_progress\"}");
    return;
  }
  JsonDocument request;
  DeserializationError error = deserializeJson(request, server.arg("plain"));
  if (error)
  {
    server.send(400, "application/json", "{\"success\":false,\"error\":\"invalid_json\"}");
    return;
  }
  String memberID = request["member_id"] | "";
  memberID.trim();
  if (memberID.length() == 0)
  {
    server.send(400, "application/json", "{\"success\":false,\"error\":\"missing_member_id\"}");
    return;
  }
  int fingerprintID = findNextFingerprintID();
  if (fingerprintID < 1)
  {
    server.send(409, "application/json", "{\"success\":false,\"error\":\"fingerprint_storage_full\"}");
    return;
  }
  startAsyncEnrollment(fingerprintID, memberID);
  JsonDocument response;
  response["success"] = true;
  response["started"] = true;
  response["member_id"] = memberID;
  response["fingerprint_id"] = fingerprintID;
  String output;
  serializeJson(response, output);
  server.send(200, "application/json", output);
  Serial.println("[ENROLL] /enroll accepted - HTTP response sent immediately");
}

void handleDeleteFingerprint()
{
  Serial.println("[API] /fingerprint DELETE");

  JsonDocument request;
  DeserializationError error = deserializeJson(request, server.arg("plain"));

  if (error)
  {
    server.send(400, "application/json", "{\"success\":false,\"error\":\"invalid_json\"}");
    return;
  }

  int id = request["fingerprint_id"] | 0;
  if (id < 1 || id > 1000)
  {
    server.send(400, "application/json", "{\"success\":false,\"error\":\"invalid_fingerprint_id\"}");
    return;
  }

  bool success = deleteFingerprint(id);

  JsonDocument response;
  response["success"] = success;
  response["fingerprint_id"] = id;
  if (!success) response["error"] = "delete_failed";

  String output;
  serializeJson(response, output);
  server.send(success ? 200 : 404, "application/json", output);
}

// =====================================================
// FIND MEMBER BY FINGERPRINT ID
// Reads the lightweight local authorization database only.
// =====================================================

bool findMemberByFingerprint(
  uint16_t fingerprintID,
  String &memberID,
  bool &allowed
)
{
  memberID = "";
  allowed = false;

  File file = LittleFS.open("/members.json", "r");

  if (!file)
    return false;

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, file);
  file.close();

  if (error)
    return false;

  JsonObject members = doc["members"].as<JsonObject>();

  if (members.isNull())
    return false;

  for (JsonPair member : members)
  {
    JsonObject data = member.value().as<JsonObject>();
    int fpID = data["fingerprint_id"] | 0;

    if (fpID == fingerprintID)
    {
      memberID = member.key().c_str();
      allowed = data["allowed"] | false;
      return true;
    }
  }

  return false;
}


// =====================================================
// PC CONNECTION HEARTBEAT
// WiFi connection and PC connection are separate states.
// Python should POST /pc_heartbeat periodically while running.
// =====================================================

void handlePcHeartbeat()
{
  lastPcHeartbeat = millis();
  pcConnected = true;

  server.send(
    200,
    "application/json",
    "{\"success\":true,\"pc_connected\":true}"
  );
}

void updatePcConnection()
{
  if (pcConnected && millis() - lastPcHeartbeat > PC_HEARTBEAT_TIMEOUT)
  {
    pcConnected = false;
    Serial.println("[PC] OFFLINE");
  }
}

// =====================================================
// LAST SCAN API
// Python polls this endpoint.
// Only lightweight scan information is returned.
// =====================================================

void handleLastScan()
{
  String memberID;
  bool allowed = false;

  bool found = findMemberByFingerprint(
    displayFingerprintID,
    memberID,
    allowed
  );

  String json;

  json.reserve(180);

  json += "{";
  json += "\"success\":true,";
  json += "\"sequence\":";
  json += String(scanSequence);
  json += ",";
  json += "\"fingerprint_id\":";
  json += String(displayFingerprintID);
  json += ",";
  json += "\"member_id\":";
  json += "\"";
  json += found ? memberID : "";
  json += "\",";
  json += "\"allowed\":";
  json += displayAllowed ? "true" : "false";
  json += ",";
  json += "\"scan_active\":";
  json += memberDisplayActive ? "true" : "false";
  json += "}";

  server.send(200, "application/json", json);
}


// =====================================================
// TEMPORARY FULL MEMBER DISPLAY API
//
// Python sends the full member information ONLY after
// receiving a scan event.
//
// Nothing is saved to LittleFS.
// =====================================================

void handleDisplayMember()
{
  if (!server.hasArg("plain"))
  {
    server.send(
      400,
      "application/json",
      "{\"success\":false,\"error\":\"Missing JSON body\"}"
    );
    return;
  }

  JsonDocument doc;

  DeserializationError error =
    deserializeJson(
      doc,
      server.arg("plain")
    );

  if (error)
  {
    server.send(
      400,
      "application/json",
      "{\"success\":false,\"error\":\"Invalid JSON\"}"
    );
    return;
  }

  const char* name =
    doc["name"] | "";

  const char* memberID =
    doc["member_id"] | "";

  const char* plan =
    doc["plan_type"] | "";

  const char* endDate =
    doc["end_date"] | "";

  const char* lastPayment =
    doc["last_payment"] | "";

  int fingerprintID =
    doc["fingerprint_id"] | 0;

  bool allowed =
    doc["allowed"] | false;

  int daysLeft =
    doc["days_left"] | 0;

  unsigned long requestedSequence =
    doc["sequence"] | 0UL;

  // Ignore stale responses from an older scan.
  if (
    requestedSequence != 0 &&
    requestedSequence != scanSequence
  )
  {
    server.send(
      409,
      "application/json",
      "{\"success\":false,\"error\":\"Stale scan\"}"
    );
    return;
  }

  if (
    memberID[0] == '\0' ||
    fingerprintID < 1 ||
    fingerprintID > 1000
  )
  {
    server.send(
      400,
      "application/json",
      "{\"success\":false,\"error\":\"Invalid member data\"}"
    );
    return;
  }

  // Temporary RAM only.
  displayName = name;
  displayMemberID = memberID;
  displayPlanType = plan;
  displayEndDate = endDate;
  displayLastPayment = lastPayment;
  displayFingerprintID = fingerprintID;
  displayAllowed = allowed;
  displayDaysLeft = daysLeft;

  memberDisplayActive = true;
  memberDisplayUntil = millis() + FINGERPRINT_KNOWN_RESULT_DELAY;

  showMemberInfo();

  // ESP32 controls result hardware. Python only supplies member data.
  if (displayAllowed)
  {
    setRGB(false, true, false);
    playAudio(acceptedAudioForDays(displayDaysLeft));
        Serial.println(
      "playing audio"
        );

    Serial.println(acceptedAudioForDays(displayDaysLeft));
    delay(1000);

  }
  else
  {
    setRGB(true, false, false);
            Serial.println(
      "playing audio"
        );
    playAudio(3);
    delay(1000);
  }

  server.send(
    200,
    "application/json",
    "{\"success\":true}"
  );
}


// =====================================================
// MEMBER INFORMATION DISPLAY
//
// IMPORTANT:
// Fingerprint image area = Y 190..309.
// Member text starts below it.
// =====================================================

void showMemberInfo()
{
  searchMode = false;

  tft.fillRect(40, 320, 240, 155, TFT_BLACK);
  tft.setTextDatum(MC_DATUM);

  if (displayAllowed)
  {
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
    tft.drawString("Welcome", 160, 332, 4);

    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    String name = displayName;
    if (name.length() > 24) name = name.substring(0, 24);
    tft.drawString(name, 160, 370, 4);

    tft.drawString("Days left: " + String(displayDaysLeft), 160, 405, 4);
  }
  else
  {
    tft.setTextColor(TFT_RED, TFT_BLACK);
    tft.drawString("Sorry", 160, 332, 4);

    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    String name = displayName;
    if (name.length() > 24) name = name.substring(0, 24);
    tft.drawString(name, 160, 370, 2);

    String endLine = "Ended at: " + displayEndDate;
    if (endLine.length() > 30) endLine = endLine.substring(0, 30);
    tft.drawString(endLine, 160, 405, 4);
  }
}



// =====================================================
// NON-BLOCKING 5 SECOND TIMER
// =====================================================

void updateMemberDisplay()
{
  if (!memberDisplayActive)
    return;

  // IMPORTANT:
  // Never let the normal 5-second scan display timer overwrite
  // the enrollment screen.
  if (enrollmentInProgress)
    return;

  if (
    (long)(millis() - memberDisplayUntil) >= 0
  )
  {
    DBG("[DISPLAY] 5-second timer EXPIRED -> showReady()");
    memberDisplayActive = false;

    displayName = "";
    displayMemberID = "";
    displayPlanType = "";
    displayEndDate = "";
    displayLastPayment = "";
    displayFingerprintID = 0;
    displayAllowed = false;
    displayDaysLeft = 0;

    showReady();
  }
}


// =====================================================
// SETUP
// =====================================================

void setup()
{
  WiFi.mode(WIFI_AP_STA);
  WiFi.config(
  local_IP,
  gateway,
  subnet,
  dns1,
  dns2
);
loadWiFiCredentials();
if (savedSSID.length() > 0)
{
WiFi.begin(
  savedSSID.c_str(),
  savedPassword.c_str()
);

wifiState = WIFI_RECONNECTING;
wifiConnectStart = millis();
lastWiFiAttempt = millis();
}
else
{
  WiFi.softAPConfig(
    apIP,
    apGateway,
    apSubnet
  );

  WiFi.softAP(
    AP_SSID,
    AP_PASSWORD
  );

  wifiState = WIFI_HOSTING;
}
server.on("/", handleRoot);
server.on("/save", HTTP_POST, handleSave);
server.on("/status", HTTP_GET, handleStatus);
server.on("/members", HTTP_POST, handleMembers);
server.on("/enroll", HTTP_POST, handleEnroll);
server.on("/enroll_status", HTTP_GET, handleEnrollStatus);
server.on("/cancel_enroll", HTTP_POST, handleCancelEnroll);
server.on("/fingerprint", HTTP_DELETE, handleDeleteFingerprint);
server.on("/last_scan", HTTP_GET, handleLastScan);
server.on("/display_member", HTTP_POST, handleDisplayMember);
server.on("/pc_heartbeat", HTTP_POST, handlePcHeartbeat);
server.begin();
  Serial.begin(115200);
  initRgbAndDfPlayer();



  // ===================================================
  // TFT
  // ===================================================

  tft.init();
  tftReady = true;

  tft.setRotation(0);

  tft.fillScreen(TFT_BLACK);
  tft.fillRect(
    40,
    330,
    240,
    40,
    TFT_CYAN
  );


  tft.setTextDatum(
    MC_DATUM
  );

  tft.setTextColor(
    TFT_WHITE,
    TFT_BLUE
  );


  tft.drawString(
    "allowed",
    160,
    350,
    4
  );
  delay(2000);

  // ===================================================
  // LITTLEFS
  // ===================================================

  if (!LittleFS.begin(true))
  {
    Serial.println("LittleFS ERROR");

    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(TFT_RED);

    tft.drawString(
      "LittleFS ERROR",
      160,
      240,
      2
    );

    while (1);
  }

  Serial.println("LittleFS OK");

Serial.print("[MEMBERS] Loaded: ");
  Serial.println(getMemberCount());

  // ===================================================
  // R307
  //
  // ESP32 GPIO 22 = RX
  // ESP32 GPIO 23 = TX
  // ===================================================

  FingerSerial.begin(
    57600,
    SERIAL_8N1,
    22,
    23
  );

  finger.begin(57600);

  delay(500);


  // ===================================================
  // Static screen
  // ===================================================

  drawStaticScreen();
  lastWiFiStatus = "";
  updateWiFiState();


  // ===================================================
  // Fingerprint initialization
  // ===================================================

  if (!initFingerprint())
  {
    Serial.println("R307 NOT FOUND");

    clearDynamicArea();

    setStatus(
      "SENSOR ERROR",
      TFT_RED
    );

    setMessage(
      "Fingerprint sensor not found"
    );

    while (1);
  }


  Serial.println("R307 FOUND");
  fingerprintSensorReady = true;


  // ===================================================
  // READY
  // ===================================================

  showReady();
  drawWiFiStatus();

  // ===================================================
  // Serial menu
  // ===================================================

  Serial.println();
  Serial.println("==============================");
  Serial.println("Fingerprint Terminal READY");
  Serial.println("==============================");
  Serial.println("e 1 = enroll");
  Serial.println("d 1 = delete");
  Serial.println("c   = count");
  Serial.println("s   = search");
Serial.print("WiFi status: ");
Serial.println(WiFi.status());

  playAudio(2);
  Serial.print("done playin 2");

}


// =====================================================
// LOOP
// =====================================================

void loop()
{
  static unsigned long debugLoopCounter = 0;
  debugLoopCounter++;
updateBlueBlink();
  server.handleClient();
  processAsyncEnrollment();
  updateWiFiState();
  updatePcConnection();
  processSerial();
  updateMemberDisplay();

  if (debugLoopCounter % 500 == 0)
  {
    DBG_PRINT("[LOOP] alive, count=");
    DBG_PRINT(debugLoopCounter);
    DBG_PRINT(" searchMode=");
    DBG_PRINT(searchMode);
    DBG_PRINT(" display=");
    DBG_PRINT(memberDisplayActive);
    DBG_PRINT(" WiFi=");
    DBG(WiFi.status() == WL_CONNECTED ? "CONNECTED" : "NOT_CONNECTED");
  }


  if (searchMode)
  {
    searchFingerprint();


    // -----------------------------------------------
    // Fingerprint pulse
    // -----------------------------------------------

    if (millis() - lastPulse > 700)
    {
      lastPulse = millis();

      fingerprintBright =
        !fingerprintBright;

      if (fingerprintBright)
      {
        drawFingerprint(
          fingerprintColor
        );
      }
      else
      {
        uint16_t dimColor =
          tft.color565(
            0,
            70,
            0
          );

        drawFingerprint(
          dimColor
        );
      }
    }
  }
}


// =====================================================
// DRAW IMAGE FROM LITTLEFS
// =====================================================

void drawImage(
  const char *filename,
  int x,
  int y,
  int w,
  int h
)
{
  fs::File file =
    LittleFS.open(
      filename,
      "r"
    );

  if (!file)
  {
    Serial.print("NOT FOUND: ");
    Serial.println(filename);
    return;
  }


  tft.startWrite();

  tft.setAddrWindow(
    x,
    y,
    w,
    h
  );


  for (int i = 0; i < w * h; i++)
  {
    uint8_t lo =
      file.read();

    uint8_t hi =
      file.read();

    uint16_t color =
      lo | (hi << 8);

    tft.pushColor(color);
  }


  tft.endWrite();

  file.close();
}


// =====================================================
// DRAW FINGERPRINT
// Recolors bright pixels
// =====================================================

void drawFingerprint(
  uint16_t color
)
{
  fs::File file =
    LittleFS.open(
      "/fingerprint.bin",
      "r"
    );

  if (!file)
  {
    Serial.println(
      "fingerprint.bin NOT FOUND"
    );

    return;
  }


  tft.startWrite();

  tft.setAddrWindow(
    FP_X,
    FP_Y,
    FP_W,
    FP_H
  );


  for (
    int i = 0;
    i < FP_W * FP_H;
    i++
  )
  {
    uint8_t lo =
      file.read();

    uint8_t hi =
      file.read();

    uint16_t original =
      lo | (hi << 8);


    // -----------------------------------------------
    // White / bright pixels = fingerprint
    // -----------------------------------------------

    if (original > 0xF000)
    {
      tft.pushColor(color);
    }
    else
    {
      tft.pushColor(original);
    }
  }


  tft.endWrite();

  file.close();
}


// =====================================================
// STATIC SCREEN
// This is called ONLY ONCE
// =====================================================

void drawStaticScreen()
{
  tft.fillScreen(
    TFT_BLACK
  );


  // ===================================================
  // Background
  // ===================================================

  drawImage(
    "/background.bin",
    0,
    0,
    320,
    480
  );


  // ===================================================
  // Logo
  // ===================================================

  drawImage(
    "/logo.bin",
    70,
    45,
    180,
    120
  );
}


// =====================================================
// CLEAR ONLY LOWER AREA
// =====================================================

void clearDynamicArea()
{
  tft.fillRect(
    40,
    UI_TOP,
    240,
    UI_BOTTOM - UI_TOP-40,
    TFT_BLACK
  );
}


// =====================================================
// STATUS
// =====================================================

void setStatus(
  String txt,
  uint16_t color
)
{
  // Only status region

  tft.fillRect(
    40,
    330,
    240,
    40,
    TFT_BLACK
  );


  tft.setTextDatum(
    MC_DATUM
  );

  tft.setTextColor(
    color,
    TFT_BLACK
  );


  tft.drawString(
    txt,
    160,
    350,
    4
  );
}


// =====================================================
// MESSAGE
// =====================================================

void setMessage(
  String txt
)
{
  // Only message region

  tft.fillRect(
    40,
    390,
    240,
    35,
    TFT_BLACK
  );


  tft.setTextDatum(
    MC_DATUM
  );

  tft.setTextColor(
    TFT_WHITE,
    TFT_BLACK
  );


  tft.drawString(
    txt,
    160,
    407,
    4
  );
}

// =====================================================
// READY
// =====================================================

void showReady()
{
  setRGB(false, false, false);
  searchMode = true;

  clearDynamicArea();


  drawFingerprint(
    fingerprintColor
  );


  setStatus(
    "READY",
    TFT_GREEN
  );


  setMessage(
    "Place Your Finger"
  );


  Serial.println(
    "READY - Place finger"
  );
}


// =====================================================
// SCANNING
// =====================================================

void showScanning()
{
  drawFingerprint(
    TFT_YELLOW
  );


  setStatus(
    "SCANNING",
    TFT_YELLOW
  );


  setMessage(
    "Reading Finger..."
  );
}


// =====================================================
// GRANTED
// =====================================================

void showGranted()
{
  setRGB(false, true, false);
  searchMode = false;


  // Only lower area

  clearDynamicArea();


  drawFingerprint(
    TFT_GREEN
  );


  setStatus(
    "ACCESS GRANTED",
    TFT_GREEN
  );


  tft.setTextDatum(
    MC_DATUM
  );


  tft.setTextColor(
    TFT_WHITE,
    TFT_BLACK
  );

      setMessage(
    "ID : " +
    String(finger.fingerID)  );



  Serial.print(
    "MATCH ID : "
  );

  Serial.println(
    finger.fingerID
  );


  Serial.print(
    "Confidence : "
  );

  Serial.println(
    finger.confidence
  );


  // Return to READY is handled by the non-blocking member display timer.

}


// =====================================================
// DENIED
// =====================================================

void showDenied(unsigned long duration)
{
  setRGB(true, false, false);
  searchMode = false;


  clearDynamicArea();


  drawFingerprint(
    TFT_RED
  );


  setStatus(
    "ACCESS DENIED",
    TFT_RED
  );


  setMessage(
    "Fingerprint Not Found"
  );


  Serial.println(
    "NO MATCH"
  );


  // Return to READY is handled by the normal scan flow.



  // Every DENIED / NOT FOUND result gets its own 5-second timer.
  memberDisplayActive = true;
  memberDisplayUntil = millis() + duration;
  DBG_PRINT("[DISPLAY] DENIED timer STARTED: ");
  DBG_PRINT(duration);
  DBG(" ms");
}


// =====================================================
// SEARCH
// =====================================================

void searchFingerprint()
{

  uint8_t p =
    finger.getImage();




  if (
    p == FINGERPRINT_NOFINGER
  )
  {
    return;
  }


  // Finger detected

  // One physical scan = one beep.
  playAudio(1);

  DBG("[SCAN] FINGER DETECTED -> showScanning()");
  showScanning();
  DBG("[SCAN] showScanning() DONE");


  // Wait a little so the
  // scanner has a stable image

  delay(50);


  if (
    p != FINGERPRINT_OK
  )
  {
    showDenied(FINGERPRINT_NOT_FOUND_DELAY);

    return;
  }


  // ===================================================
  // Convert image
  // ===================================================

  DBG("[SCAN] Calling image2Tz()");
  p =
    finger.image2Tz();
  DBG_PRINT("[SCAN] image2Tz result = ");
  DBG(p);


  if (
    p != FINGERPRINT_OK
  )
  {
    showDenied(FINGERPRINT_NOT_FOUND_DELAY);

    return;
  }


  // ===================================================
  // Search
  // ===================================================

  DBG("[SCAN] Calling fingerFastSearch()");
  p =
    finger.fingerFastSearch();
  DBG_PRINT("[SCAN] fingerFastSearch result = ");
  DBG(p);


  if (
    p == FINGERPRINT_OK
  )
  {
    uint16_t fingerprintID =
      finger.fingerID;

    uint16_t confidence =
      finger.confidence;

    Serial.print("[R307] ID: ");
    Serial.println(fingerprintID);

    Serial.print("[R307] Confidence: ");
    Serial.println(confidence);

    // =================================================
    // MANUAL MATCH SCORE CHECK
    // =================================================
    // R307 can return a candidate ID with a low score.
    // Reject it manually if confidence is below the
    // threshold configured at the top of this file.
    if (confidence < R307_MIN_MATCH_SCORE)
    {
      Serial.print("[ACCESS] MATCH SCORE TOO LOW: ");
      Serial.print(confidence);
      Serial.print(" < ");
      Serial.println(R307_MIN_MATCH_SCORE);

      // Low score = NOT FOUND.
      showDenied(FINGERPRINT_NOT_FOUND_DELAY);
      return;
    }


    // =================================================
    // Check local JSON authorization
    // =================================================

    DBG("[SCAN] Calling isFingerprintAllowed()");
    bool allowed =
      isFingerprintAllowed(fingerprintID);
    DBG_PRINT("[SCAN] isFingerprintAllowed = ");
    DBG(allowed ? "TRUE" : "FALSE");

    // Store ONLY the lightweight scan event.
    DBG("[SCAN] Setting scan display state");
    displayFingerprintID = fingerprintID;
    displayAllowed = allowed;
    scanSequence++;
    DBG_PRINT("[SCAN] scanSequence = ");
    DBG(scanSequence);

    // Start a non-blocking 5-second result window.
    // Python can replace this with the full member display.
    memberDisplayActive = true;
    memberDisplayUntil = millis() + FINGERPRINT_KNOWN_RESULT_DELAY;
    DBG("[SCAN] 5-second display timer STARTED");

    // The Python software can now poll /last_scan.
    // Full member information is sent back temporarily
    // through /display_member and is never persisted on ESP32.

    if (allowed)
    {
      Serial.println("[ACCESS] ALLOWED");
    }
    else
    {
      Serial.println("[ACCESS] DENIED");
    }

    // Keep the existing local access result visible until
    // Python sends the temporary member information.
    DBG("[SCAN] Calling local access display");
    if (allowed)
    {
      showGranted();
    }
    else
    {
      showDenied(FINGERPRINT_KNOWN_RESULT_DELAY);
    }
    DBG("[SCAN] local access display DONE");
  }
  else
  {
    DBG("[SCAN] FINGERPRINT NOT FOUND");
    Serial.println("[ACCESS] FINGERPRINT NOT FOUND");

    DBG("[SCAN] Calling showDenied()");
    showDenied(FINGERPRINT_NOT_FOUND_DELAY);
    DBG("[SCAN] showDenied() DONE");
  }

}
// =====================================================
// SERIAL COMMANDS
// =====================================================

void processSerial()
{
  if (!Serial.available())
  {
    return;
  }


  char cmd =
    Serial.read();


  int id =
    Serial.parseInt();


  switch (cmd)
  {
    case 'e':

      if (id > 0)
      {
        enrollFingerprint(id);
      }

      break;


    case 'd':

      if (id > 0)
      {
        deleteFingerprint(id);
      }

      break;


    case 'c':

      countFingerprints();

      break;

    case 'k':

    finger.emptyDatabase();

    break;

    case 's':

      showReady();

      break;
  }
}


// =====================================================
// COUNT
// =====================================================

void countFingerprints()
{
  searchMode = false;


  finger.getTemplateCount();


  Serial.print(
    "Stored fingerprints : "
  );

  Serial.println(
    finger.templateCount
  );


  clearDynamicArea();


  setStatus(
    "COUNT",
    TFT_CYAN
  );


  tft.setTextDatum(
    MC_DATUM
  );

  tft.setTextColor(
    TFT_WHITE,
    TFT_BLACK
  );


  tft.drawString(
    "STORED USERS",
    160,
    220,
    4
  );


  tft.drawNumber(
    finger.templateCount,
    160,
    275,
    7
  );


  setMessage(
    "Count Completed"
  );


  delay(2000);


  showReady();
}


// =====================================================
// DELETE
// =====================================================

bool deleteFingerprint(
  int id
)
{
  searchMode = false;


  Serial.print(
    "Deleting ID : "
  );

  Serial.println(id);


  clearDynamicArea();


  setStatus(
    "DELETE",
    TFT_ORANGE
  );


  setMessage(
    "Deleting..."
  );


  uint8_t p =
    finger.deleteModel(id);


  if (
    p == FINGERPRINT_OK
  )
  {
    Serial.println(
      "Deleted"
    );


    setStatus(
      "SUCCESS",
      TFT_GREEN
    );


    tft.setTextDatum(
      MC_DATUM
    );

    tft.setTextColor(
      TFT_GREEN,
      TFT_BLACK
    );


    tft.drawString(
      "DELETED",
      160,
      250,
      4
    );


    tft.setTextColor(
      TFT_WHITE,
      TFT_BLACK
    );


    tft.drawString(
      "ID : " +
      String(id),
      160,
      290,
      4
    );


    setMessage(
      "Fingerprint Removed"
    );
  }
  else
  {
    Serial.println(
      "Delete Failed"
    );


    setStatus(
      "FAILED",
      TFT_RED
    );


    setMessage(
      "Delete Failed"
    );
  }


  delay(2000);

  showReady();
  return p == FINGERPRINT_OK;
}


// =====================================================
// ASYNCHRONOUS API ENROLLMENT IMPLEMENTATION
// =====================================================

const unsigned long ASYNC_FIRST_TIMEOUT = 70000UL;
const unsigned long ASYNC_REMOVE_TIMEOUT = 70000UL;
const unsigned long ASYNC_SECOND_TIMEOUT = 70000UL;
const unsigned long ASYNC_RETRY_REMOVE_TIMEOUT = 10000UL;

void startAsyncEnrollment(int id, const String &memberID)
{
  setRGB(false, false, true);
  enrollmentMemberID = memberID;
  enrollmentCancelRequested = false;
  enrollmentInProgress = true;
  asyncEnrollFingerprintID = id;
  asyncEnrollSecondAttempts = 0;
  asyncEnrollMismatchRetries = 0;
  asyncEnrollError = "";
  asyncEnrollState = ENROLL_WAIT_FIRST;
  asyncEnrollStateStarted = millis();
  searchMode = false;

  memberDisplayActive = false;
  displayName = "";
  displayMemberID = "";
  displayPlanType = "";
  displayEndDate = "";
  displayLastPayment = "";
  displayFingerprintID = 0;
  displayAllowed = false;
  displayDaysLeft = 0;

  clearDynamicArea();
  setStatus("ENROLL", TFT_CYAN);
  setMessage("Place Finger");
  Serial.println("[ENROLL] ASYNC START");
  Serial.print("[ENROLL] Member ID: "); Serial.println(memberID);
  Serial.print("[ENROLL] Fingerprint ID: "); Serial.println(id);
}

void finishAsyncEnrollment(bool success, bool cancelled, const String &error)
{
  setRGB(false, false, false);
  asyncEnrollError = error;
  if (cancelled) asyncEnrollState = ENROLL_CANCELLED;
  else if (success) asyncEnrollState = ENROLL_DONE;
  else asyncEnrollState = ENROLL_FAILED;
  enrollmentInProgress = false;
  enrollmentCancelRequested = false;

  if (cancelled) { setStatus("CANCELLED", TFT_YELLOW); setMessage("Enrollment Cancelled"); }
  else if (success) { setStatus("SUCCESS", TFT_GREEN); setMessage("Enrollment Complete"); }
  else { setStatus("FAILED", TFT_RED); setMessage(error.length() ? error : "Enrollment Failed"); }
}

void processAsyncEnrollment()
{
  if (!enrollmentInProgress) return;

  if (enrollmentCancelRequested)
  {
    Serial.println("[ENROLL] Cancel request received by state machine");
    finishAsyncEnrollment(false, true, "cancelled");
    showReady();
    return;
  }

  unsigned long elapsed = millis() - asyncEnrollStateStarted;
  int p;

  switch (asyncEnrollState)
  {
    case ENROLL_WAIT_FIRST:
      p = finger.getImage();
      if (p == FINGERPRINT_OK)
      {
        p = finger.image2Tz(1);
        if (p == FINGERPRINT_OK)
        {
          Serial.println("[ENROLL] FIRST IMAGE CAPTURED SUCCESSFULLY");
          setMessage("Remove Finger");
          asyncEnrollState = ENROLL_REMOVE_FIRST;
          asyncEnrollStateStarted = millis();
        }
        else
        {
          finishAsyncEnrollment(false, false, "first_scan_failed"); delay(1000); showReady();
        }
      }
      else if (elapsed >= ASYNC_FIRST_TIMEOUT)
      {
        finishAsyncEnrollment(false, false, "first_scan_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_REMOVE_FIRST:
      p = finger.getImage();
      if (p == FINGERPRINT_NOFINGER)
      {
        Serial.println("[ENROLL] FINGER REMOVED - MOVING TO SECOND SCAN");
        asyncEnrollSecondAttempts = 0;
        setMessage("Place Finger Again");
        asyncEnrollState = ENROLL_WAIT_SECOND;
        asyncEnrollStateStarted = millis();
      }
      else if (elapsed >= ASYNC_REMOVE_TIMEOUT)
      {
        finishAsyncEnrollment(false, false, "remove_finger_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_WAIT_SECOND:
      p = finger.getImage();
      if (p == FINGERPRINT_OK)
      {
        p = finger.image2Tz(2);
        if (p == FINGERPRINT_OK)
        {
          Serial.println("[ENROLL] SECOND IMAGE CAPTURED SUCCESSFULLY");
          setMessage("Creating Template...");
          asyncEnrollState = ENROLL_CREATE_MODEL;
          asyncEnrollStateStarted = millis();
        }
        else
        {
          asyncEnrollSecondAttempts++;
          Serial.print("[ENROLL] Second image failed, attempt "); Serial.println(asyncEnrollSecondAttempts);
          if (asyncEnrollSecondAttempts >= 3)
          {
            finishAsyncEnrollment(false, false, "second_scan_failed"); delay(1000); showReady();
          }
          else
          {
            setMessage("Remove Finger");
            asyncEnrollState = ENROLL_RETRY_REMOVE;
            asyncEnrollStateStarted = millis();
          }
        }
      }
      else if (elapsed >= ASYNC_SECOND_TIMEOUT)
      {
        finishAsyncEnrollment(false, false, "second_scan_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_RETRY_REMOVE:
      p = finger.getImage();
      if (p == FINGERPRINT_NOFINGER || elapsed >= ASYNC_RETRY_REMOVE_TIMEOUT)
      {
        setMessage("Place Finger Again");
        asyncEnrollState = ENROLL_WAIT_SECOND;
        asyncEnrollStateStarted = millis();
      }
      break;

    case ENROLL_CREATE_MODEL:
      p = finger.createModel();
      if (p == FINGERPRINT_OK)
      {
        Serial.println("[ENROLL] Template created successfully");
        setMessage("Saving...");
        asyncEnrollState = ENROLL_SAVE;
        asyncEnrollStateStarted = millis();
      }
      else if (asyncEnrollMismatchRetries < 2)
      {
        asyncEnrollMismatchRetries++;
        Serial.print("[ENROLL] Template mismatch - retry "); Serial.println(asyncEnrollMismatchRetries);
        setMessage("Try Different Angle");
        asyncEnrollState = ENROLL_RETRY_REMOVE;
        asyncEnrollStateStarted = millis();
      }
      else
      {
        finishAsyncEnrollment(false, false, "finger_mismatch"); delay(1000); showReady();
      }
      break;

    case ENROLL_SAVE:
      p = finger.storeModel(asyncEnrollFingerprintID);
      if (p == FINGERPRINT_OK)
      {
        Serial.println("[ENROLL] Saved Successfully");
        finishAsyncEnrollment(true, false, "");
      }
      else finishAsyncEnrollment(false, false, "store_failed");
      delay(1000); showReady();
      break;

    default: break;
  }
}

void handleEnrollStatus()
{
  JsonDocument response;
  response["success"] = true;
  response["in_progress"] = enrollmentInProgress;
  response["member_id"] = enrollmentMemberID;

  const char *step = "idle";
  switch (asyncEnrollState)
  {
    case ENROLL_WAIT_FIRST: step = "waiting_first_finger"; break;
    case ENROLL_REMOVE_FIRST: step = "waiting_finger_removal"; break;
    case ENROLL_WAIT_SECOND: step = "waiting_second_finger"; break;
    case ENROLL_RETRY_REMOVE: step = "waiting_retry_removal"; break;
    case ENROLL_CREATE_MODEL: step = "creating_template"; break;
    case ENROLL_SAVE: step = "saving"; break;
    case ENROLL_DONE: step = "completed"; break;
    case ENROLL_FAILED: step = "failed"; break;
    case ENROLL_CANCELLED: step = "cancelled"; break;
    default: break;
  }
  response["step"] = step;
  response["completed"] = (asyncEnrollState == ENROLL_DONE);
  response["cancelled"] = (asyncEnrollState == ENROLL_CANCELLED);
  if (asyncEnrollState == ENROLL_DONE) response["fingerprint_id"] = asyncEnrollFingerprintID;
  if (asyncEnrollState == ENROLL_FAILED) response["error"] = asyncEnrollError;

  String output; serializeJson(response, output);
  server.send(200, "application/json", output);
}

// =====================================================
// ORIGINAL SERIAL ENROLLMENT FUNCTION
// =====================================================


bool enrollFingerprint(int id)
{
  searchMode = false;


  clearDynamicArea();


  setStatus(
    "ENROLL",
    TFT_CYAN
  );


  setMessage(
    "Place Finger"
  );


  Serial.print(
    "Enrolling ID : "
  );

  Serial.println(id);


  int p = -1;


  Serial.println("[ENROLL] STEP 1: WAITING FOR FIRST FINGER");

  // ===================================================
  // FIRST SCAN
  // ===================================================

  unsigned long startTime = millis();

  while (
    (p = finger.getImage())
    != FINGERPRINT_OK
  )
  {
    server.handleClient();

    if (enrollmentCancelRequested)
    {
      Serial.println("[ENROLL] CANCELLED during first scan");
      showReady();
      return false;
    }

    if (millis() - startTime >= 70000)
    {
      setStatus("TIMEOUT", TFT_RED);
      setMessage("Enrollment Timeout");
      delay(1000);
      showReady();
      return false;
    }
    delay(20);
  }


  p =
    finger.image2Tz(1);

  server.handleClient();

  if (enrollmentCancelRequested)
  {
    Serial.println("[ENROLL] CANCELLED after first scan");
    showReady();
    return false;
  }

  if (
    p != FINGERPRINT_OK
  )
  {
    setStatus(
      "FAILED",
      TFT_RED
    );

    setMessage(
      "First Scan Failed"
    );


    delay(2000);

    showReady();

    return false;
  }


  Serial.println("[ENROLL] FIRST IMAGE CAPTURED SUCCESSFULLY");

  // ===================================================
  // REMOVE FINGER
  // ===================================================

  setStatus(
    "ENROLL",
    TFT_CYAN
  );

  setMessage(
    "Remove Finger"
  );


  Serial.println(
    "Remove Finger"
  );


  delay(1000);


  startTime = millis();
  while (
    finger.getImage()
    != FINGERPRINT_NOFINGER
  )
  {
    server.handleClient();

    if (enrollmentCancelRequested)
    {
      Serial.println("[ENROLL] CANCELLED while removing finger");
      showReady();
      return false;
    }

    if (millis() - startTime >= 70000)
    {
      setStatus("TIMEOUT", TFT_RED);
      setMessage("Remove Finger");
      delay(1000);
      showReady();
      return false;
    }
    delay(20);
  }


  Serial.println("[ENROLL] FINGER REMOVED - MOVING TO SECOND SCAN");

  // ===================================================
  // SECOND SCAN
  // ===================================================
  // R307 templates are built from two final character buffers.
  // We keep the first image in slot 1 and allow up to 3 attempts
  // for slot 2 so the user can change angle/pressure naturally.

  setMessage("Place Finger Again");
  Serial.println("Place Finger Again - slightly change angle");

  bool secondScanReady = false;

  for (uint8_t secondAttempt = 1; secondAttempt <= 3; secondAttempt++)
  {
    Serial.print("[ENROLL] Second scan attempt ");
    Serial.println(secondAttempt);

    p = -1;
    startTime = millis();

    while ((p = finger.getImage()) != FINGERPRINT_OK)
    {
      server.handleClient();

      if (enrollmentCancelRequested)
      {
        Serial.println("[ENROLL] CANCELLED during second scan");
        showReady();
        return false;
      }

      if (millis() - startTime >= 70000)
      {
        setStatus("TIMEOUT", TFT_RED);
        setMessage("Enrollment Timeout");
        delay(1000);
        showReady();
        return false;
      }
      delay(20);
    }

    p = finger.image2Tz(2);
    server.handleClient();

    if (enrollmentCancelRequested)
    {
      Serial.println("[ENROLL] CANCELLED after second scan");
      showReady();
      return false;
    }

    if (p == FINGERPRINT_OK)
    {
      secondScanReady = true;
      break;
    }

    Serial.println("[ENROLL] Second image failed - retrying");
    setMessage("Try Again");
    delay(500);

    // Remove the finger before the next capture.
    setMessage("Remove Finger");
    startTime = millis();

    while (finger.getImage() != FINGERPRINT_NOFINGER)
    {
      server.handleClient();

      if (enrollmentCancelRequested)
      {
        Serial.println("[ENROLL] CANCELLED while retrying second scan");
        showReady();
        return false;
      }

      if (millis() - startTime >= 10000)
        break;

      delay(20);
    }

    if (secondAttempt < 3)
    {
      setMessage("Place Finger Again");
      delay(300);
    }
  }

  if (!secondScanReady)
  {
    setStatus("FAILED", TFT_RED);
    setMessage("Second Scan Failed");
    delay(1500);
    showReady();
    return false;
  }

  // ===================================================
  // CREATE MODEL
  // ===================================================

  setMessage("Creating Template...");
  p = finger.createModel();

  server.handleClient();

  if (enrollmentCancelRequested)
  {
    Serial.println("[ENROLL] CANCELLED before save");
    showReady();
    return false;
  }

  if (p != FINGERPRINT_OK)
  {
    // The two images did not match well enough. Give the user up to
    // two more chances to recapture slot 2 from a slightly different angle.
    Serial.println("[ENROLL] Template mismatch - retrying second image");

    bool modelCreated = false;

    for (uint8_t retry = 1; retry <= 2 && !modelCreated; retry++)
    {
      setMessage("Try Different Angle");
      delay(500);

      setMessage("Remove Finger");
      startTime = millis();

      while (finger.getImage() != FINGERPRINT_NOFINGER)
      {
        server.handleClient();

        if (enrollmentCancelRequested)
        {
          Serial.println("[ENROLL] CANCELLED during mismatch retry");
          showReady();
          return false;
        }

        if (millis() - startTime >= 10000)
          break;

        delay(20);
      }

      setMessage("Place Finger Again");
      startTime = millis();

      while ((p = finger.getImage()) != FINGERPRINT_OK)
      {
        server.handleClient();

        if (enrollmentCancelRequested)
        {
          Serial.println("[ENROLL] CANCELLED during mismatch retry scan");
          showReady();
          return false;
        }

        if (millis() - startTime >= 15000)
          break;

        delay(20);
      }

      if (p != FINGERPRINT_OK)
        continue;

      p = finger.image2Tz(2);
      if (p != FINGERPRINT_OK)
        continue;

      p = finger.createModel();
      if (p == FINGERPRINT_OK)
        modelCreated = true;
    }

    if (!modelCreated)
    {
      setStatus("FAILED", TFT_RED);
      setMessage("Finger Mismatch");
      delay(1500);
      showReady();
      return false;
    }
  }

  // ===================================================
  // SAVE
  // ===================================================

  setMessage(
    "Saving..."
  );


  p =
    finger.storeModel(id);

  server.handleClient();

  if (enrollmentCancelRequested)
  {
    Serial.println("[ENROLL] CANCELLED after save command");
    showReady();
    return false;
  }

  if (
    p == FINGERPRINT_OK
  )
  {
    Serial.println(
      "Saved Successfully"
    );


    setStatus(
      "SUCCESS",
      TFT_GREEN
    );


    setMessage(
      "Enrollment Complete"
    );


    tft.setTextDatum(
      MC_DATUM
    );

    tft.setTextColor(
      TFT_GREEN,
      TFT_BLACK
    );


    tft.drawString(
      "SAVED",
      160,
      250,
      4
    );


    tft.setTextColor(
      TFT_WHITE,
      TFT_BLACK
    );


    tft.drawString(
      "ID : " +
      String(id),
      160,
      290,
      4
    );
  }
  else
  {
    Serial.println(
      "Store Failed"
    );


    setStatus(
      "FAILED",
      TFT_RED
    );


    setMessage(
      "Store Error"
    );
  }


  bool stored = (p == FINGERPRINT_OK);

  delay(2500);

  showReady();
  return stored;
}
// =====================================================
// FINGERPRINT INITIALIZATION
// =====================================================

bool initFingerprint()
{
  if (!finger.verifyPassword())
    return false;

  // R307 security level:
  // 1 = most forgiving, 5 = strictest.
  // Level 2 is easier for normal daily scanning than the default level 3.
  uint8_t p = finger.setSecurityLevel(R307_SECURITY_LEVEL);

  Serial.print("[R307] Security level set result = ");
  Serial.println(p);

  finger.getParameters();
  Serial.print("[R307] Security level = ");
  Serial.println(finger.security_level);

  return true;
}