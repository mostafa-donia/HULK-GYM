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
#define DEFAULT_MIN_MATCH_SCORE 50
uint16_t minMatchScore = DEFAULT_MIN_MATCH_SCORE;

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
#include "arabic_font.h"
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

IPAddress local_IP(192, 168, 0, 254);
IPAddress gateway(192, 168, 0, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns1(8, 8, 8, 8);
IPAddress dns2(1, 1, 1, 1);

String savedStaticIP = "192.168.0.254";

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
// LIVE WEB DIAGNOSTIC LOGS
// =====================================================
const int MAX_WEB_LOGS = 50;
String webLogs[MAX_WEB_LOGS];
int webLogIndex = 0;
int webLogCount = 0;

void logDiag(const String &tag, const String &msg)
{
  unsigned long totalSec = millis() / 1000;
  unsigned long mins = totalSec / 60;
  unsigned long secs = totalSec % 60;
  char timeBuf[16];
  snprintf(timeBuf, sizeof(timeBuf), "[%02lum:%02lus]", mins, secs);

  String entry = String(timeBuf) + " " + tag + " " + msg;
  Serial.println(entry);

  webLogs[webLogIndex] = entry;
  webLogIndex = (webLogIndex + 1) % MAX_WEB_LOGS;
  if (webLogCount < MAX_WEB_LOGS) webLogCount++;
}

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

uint16_t lastScanFingerprintID = 0;
bool lastScanAllowed = false;
unsigned long lastScanTimestamp = 0;


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
void showExpired(unsigned long duration = FINGERPRINT_KNOWN_RESULT_DELAY);
void showDenied(unsigned long duration = FINGERPRINT_NOT_FOUND_DELAY);

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
  ENROLL_IDLE,
  ENROLL_WAIT_FIRST, ENROLL_REMOVE_FIRST,
  ENROLL_WAIT_SECOND, ENROLL_REMOVE_SECOND,
  ENROLL_WAIT_THIRD, ENROLL_REMOVE_THIRD,
  ENROLL_WAIT_FOURTH,
  ENROLL_CREATE_MODEL, ENROLL_RETRY_REMOVE,
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
void handleLogs();
void handleClearLogs();

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

  if (newState != wifiState)
  {
    if (newState == WIFI_CONNECTED)
    {
      logDiag("[WIFI]", "Connected to " + savedSSID + " | IP: " + WiFi.localIP().toString());
    }
    else if (newState == WIFI_HOSTING)
    {
      logDiag("[WIFI]", "Hosting Setup AP: HULK_GYM_SETUP (192.168.4.1)");
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
  savedStaticIP = prefs.getString("ip", "192.168.0.254");
  minMatchScore = prefs.getUInt("confid", DEFAULT_MIN_MATCH_SCORE);

  prefs.end();

  if (savedStaticIP.length() > 0)
  {
    IPAddress parsedIP;
    if (parsedIP.fromString(savedStaticIP))
    {
      local_IP = parsedIP;
      gateway = IPAddress(local_IP[0], local_IP[1], local_IP[2], 1);
    }
  }

  Serial.print("Saved SSID: ");
  Serial.println(savedSSID);
  Serial.print("Saved Static IP: ");
  Serial.println(local_IP);
  Serial.print("Configured Gateway: ");
  Serial.println(gateway);
  Serial.print("Saved Confidence: ");
  Serial.println(minMatchScore);
}


void handleLogs()
{
  JsonDocument doc;
  doc["wifi"] = (wifiState == WIFI_CONNECTED) ? "connected" : "hosting";
  doc["ip"] = (wifiState == WIFI_CONNECTED) ? WiFi.localIP().toString() : local_IP.toString();
  doc["confidence_threshold"] = minMatchScore;
  doc["members"] = getMemberCount();
  doc["pc_connected"] = pcConnected;

  JsonArray arr = doc["logs"].to<JsonArray>();
  int start = (webLogCount < MAX_WEB_LOGS) ? 0 : webLogIndex;
  for (int i = 0; i < webLogCount; i++)
  {
    int idx = (start + i) % MAX_WEB_LOGS;
    arr.add(webLogs[idx]);
  }

  String output;
  serializeJson(doc, output);
  server.send(200, "application/json", output);
}

void handleClearLogs()
{
  webLogCount = 0;
  webLogIndex = 0;
  logDiag("[SYSTEM]", "Web console logs cleared");
  server.send(200, "application/json", "{\"success\":true}");
}

void handleRoot()
{
    String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HULK GYM - Terminal</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: #050505; color: white; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; display: flex; justify-content: center; align-items: flex-start; padding: 20px 10px; }
.card { width: 100%; max-width: 520px; background: #101010; border: 2px solid #9cff00; border-radius: 20px; padding: 20px; box-shadow: 0 0 30px rgba(156,255,0,0.15); }
.header { text-align: center; margin-bottom: 14px; }
.logo { color: #9cff00; font-size: 26px; font-weight: 900; letter-spacing: 2px; }
.subtitle { font-size: 13px; color: #888; margin-top: 2px; }
.status-bar { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; margin-bottom: 16px; }
.pill { padding: 5px 10px; border-radius: 16px; font-size: 11px; font-weight: bold; }
.pill-green { background: #003311; color: #00ff88; border: 1px solid #00aa44; }
.pill-cyan { background: #002b33; color: #00e5ff; border: 1px solid #0099aa; }
.pill-dark { background: #181818; color: #ccc; border: 1px solid #333; }
.terminal-container { background: #080808; border: 1px solid #2a2a2a; border-radius: 12px; overflow: hidden; margin-bottom: 18px; }
.terminal-bar { display: flex; justify-content: space-between; align-items: center; background: #141414; padding: 8px 12px; border-bottom: 1px solid #242424; }
.terminal-title { font-size: 12px; font-weight: bold; color: #eee; display: flex; align-items: center; gap: 6px; }
.live-dot { color: #00ff88; font-size: 11px; animation: pulse 1.5s infinite; }
@keyframes pulse { 0%{opacity:1;} 50%{opacity:0.3;} 100%{opacity:1;} }
.terminal-actions { display: flex; gap: 6px; }
.btn-sm { background: #202020; border: 1px solid #444; color: #9cff00; font-size: 11px; font-weight: bold; padding: 4px 8px; border-radius: 6px; cursor: pointer; }
.btn-sm:hover { background: #2a2a2a; }
.terminal-box { height: 260px; overflow-y: auto; padding: 10px 12px; font-family: Consolas, 'Courier New', monospace; font-size: 12px; line-height: 1.5; color: #ddd; background: #040404; word-break: break-all; }
.terminal-box .line { margin-bottom: 4px; }
details { background: #121212; border: 1px solid #2a2a2a; border-radius: 12px; padding: 12px 14px; margin-top: 10px; }
summary { font-size: 14px; font-weight: bold; color: #9cff00; cursor: pointer; outline: none; list-style: none; display: flex; justify-content: space-between; align-items: center; }
summary::-webkit-details-marker { display: none; }
summary::after { content: '▾'; font-size: 16px; }
details[open] summary::after { content: '▴'; }
.form-content { margin-top: 14px; border-top: 1px solid #222; padding-top: 14px; }
label { display: block; color: #9cff00; font-size: 12px; font-weight: bold; margin-bottom: 6px; }
input { width: 100%; padding: 11px; margin-bottom: 12px; border-radius: 8px; border: 1px solid #3a3a3a; background: #060606; color: white; font-size: 14px; outline: none; }
input:focus { border-color: #9cff00; }
.btn-row { display: flex; gap: 8px; margin-top: -6px; margin-bottom: 12px; }
.btn-preset { flex: 1; padding: 8px 4px; background: #181818; color: #9cff00; border: 1px solid #333; border-radius: 6px; font-size: 12px; font-weight: bold; cursor: pointer; }
.btn-preset:hover { background: #222; }
.hint { display: block; color: #666; font-size: 11px; margin-top: -8px; margin-bottom: 12px; }
.btn-submit { width: 100%; padding: 13px; border: none; border-radius: 8px; background: #9cff00; color: #050505; font-size: 15px; font-weight: 900; cursor: pointer; margin-top: 8px; }
.btn-submit:active { transform: scale(0.98); }
.footer { text-align: center; color: #555; font-size: 11px; margin-top: 18px; }
</style>
</head>
<body>
<div class="card">
    <div class="header">
        <div class="logo">HULK GYM</div>
        <div class="subtitle">Live Biometric Terminal & Diagnostics</div>
    </div>

    <div class="status-bar">
        <span class="pill {{WIFI_PILL_CLASS}}">{{WIFI_STATUS}}</span>
        <span class="pill pill-dark">IP: <span id="stat-ip">{{LOCAL_IP}}</span></span>
        <span class="pill pill-dark">Threshold: <span id="stat-conf">{{CONFIDENCE}}</span></span>
        <span class="pill pill-dark">Members: <span id="stat-mem">{{MEMBERS}}</span></span>
        <span class="pill {{PC_PILL_CLASS}}" id="stat-pc">{{PC_STATUS}}</span>
    </div>

    <div class="terminal-container">
        <div class="terminal-bar">
            <div class="terminal-title">
                <span class="live-dot" id="live-dot">● LIVE</span>
                <span>DIAGNOSTIC MONITOR</span>
            </div>
            <div class="terminal-actions">
                <button type="button" class="btn-sm" id="btn-pause" onclick="togglePause()">⏸️ Pause</button>
                <button type="button" class="btn-sm" onclick="clearConsole()">🗑️ Clear</button>
            </div>
        </div>
        <div id="console" class="terminal-box">
            <div class="line" style="color:#666;">Connecting to diagnostic feed...</div>
        </div>
    </div>

    <details {{SETTINGS_OPEN}}>
        <summary>⚙️ Wi-Fi & System Settings</summary>
        <div class="form-content">
            <form action="/save" method="POST">
                <label>Wi-Fi Network</label>
                <input type="text" name="ssid" placeholder="Wi-Fi name" value="{{SSID}}" autocomplete="off" required>

                <label>Wi-Fi Password</label>
                <input type="password" name="password" placeholder="Wi-Fi password" required>

                <label>Fixed IP Address</label>
                <input type="text" id="static_ip" name="static_ip" placeholder="e.g. 192.168.0.254" value="{{STATIC_IP}}" required>
                <div class="btn-row">
                    <button type="button" class="btn-preset" onclick="document.getElementById('static_ip').value='192.168.0.254'">192.168.0.254 (0.x)</button>
                    <button type="button" class="btn-preset" onclick="document.getElementById('static_ip').value='192.168.1.254'">192.168.1.254 (1.x)</button>
                </div>
                <span class="hint">Gateway is set automatically to .1 (e.g. 192.168.0.1 or 192.168.1.1)</span>

                <label>Fingerprint Confidence Level</label>
                <input type="number" name="confidence" min="10" max="255" value="{{CONFIDENCE}}" required>
                <span class="hint">Default: 50 (Lower = easier match / Higher = stricter)</span>

                <label>Admin Password (كلمة السر)</label>
                <input type="password" name="admin_pass" placeholder="Enter 1234 to save" required>
                <span class="hint">Protected: Enter 1234 to apply changes</span>

                <button type="submit" class="btn-submit">SAVE & REBOOT</button>
            </form>
        </div>
    </details>

    <div class="footer">
        HULK GYM Smart Fitness System
    </div>
</div>

<script>
let isPaused = false;
let lastLogText = "";

function togglePause() {
    isPaused = !isPaused;
    let btn = document.getElementById("btn-pause");
    btn.innerText = isPaused ? "▶️ Resume" : "⏸️ Pause";
    btn.style.color = isPaused ? "#ffaa00" : "#9cff00";
    let dot = document.getElementById("live-dot");
    dot.innerText = isPaused ? "⏸️ PAUSED" : "● LIVE";
    dot.style.color = isPaused ? "#ffaa00" : "#00ff88";
}

function clearConsole() {
    fetch('/clear_logs', { method: 'POST' }).catch(()=>{});
    document.getElementById("console").innerHTML = '<div class="line" style="color:#666;">--- Console Cleared ---</div>';
    lastLogText = "";
}

function formatLine(line) {
    let esc = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    esc = esc.replace(/\[([0-9]+m:[0-9]+s)\]/g, '<span style="color:#666;">[$1]</span>');
    esc = esc.replace(/\[ALLOWED\]/g, '<span style="color:#00ff88;font-weight:bold;">[ALLOWED]</span>');
    esc = esc.replace(/\[MATCH\]/g, '<span style="color:#9cff00;font-weight:bold;">[MATCH]</span>');
    esc = esc.replace(/\[REJECT\]/g, '<span style="color:#ff9900;font-weight:bold;">[REJECT]</span>');
    esc = esc.replace(/\[DENIED\]/g, '<span style="color:#ff4444;font-weight:bold;">[DENIED]</span>');
    esc = esc.replace(/\[NOT_FOUND\]/g, '<span style="color:#ffff00;font-weight:bold;">[NOT_FOUND]</span>');
    esc = esc.replace(/\[ERROR\]/g, '<span style="color:#ff3333;font-weight:bold;background:#330000;padding:1px 4px;border-radius:3px;">[ERROR]</span>');
    esc = esc.replace(/\[SCAN\]/g, '<span style="color:#00e5ff;font-weight:bold;">[SCAN]</span>');
    esc = esc.replace(/\[SENSOR\]/g, '<span style="color:#e066ff;font-weight:bold;">[SENSOR]</span>');
    esc = esc.replace(/\[WIFI\]/g, '<span style="color:#33bbff;font-weight:bold;">[WIFI]</span>');
    esc = esc.replace(/\[PC\]/g, '<span style="color:#77aaff;font-weight:bold;">[PC]</span>');
    return '<div class="line">' + esc + '</div>';
}

function pollLogs() {
    if (isPaused) {
        setTimeout(pollLogs, 1200);
        return;
    }
    fetch('/logs')
        .then(res => res.json())
        .then(data => {
            if (data.ip) document.getElementById("stat-ip").innerText = data.ip;
            if (data.confidence_threshold) document.getElementById("stat-conf").innerText = data.confidence_threshold;
            if (data.members !== undefined) document.getElementById("stat-mem").innerText = data.members;
            if (data.pc_connected !== undefined) {
                let pc = document.getElementById("stat-pc");
                if (pc) {
                    pc.innerText = data.pc_connected ? "PC: OK" : "PC: OFFLINE";
                    pc.className = "pill " + (data.pc_connected ? "pill-green" : "pill-dark");
                }
            }
            if (data.logs && Array.isArray(data.logs)) {
                let joined = data.logs.join("\n");
                if (joined !== lastLogText) {
                    lastLogText = joined;
                    let html = data.logs.map(formatLine).join("");
                    let c = document.getElementById("console");
                    c.innerHTML = html || '<div class="line" style="color:#555;">Waiting for events...</div>';
                    c.scrollTop = c.scrollHeight;
                }
            }
        })
        .catch(err => {})
        .finally(() => {
            setTimeout(pollLogs, 1200);
        });
}

document.addEventListener("DOMContentLoaded", () => {
    pollLogs();
});
</script>
</body>
</html>
)rawliteral";

    html.replace("{{SSID}}", savedSSID);
    html.replace("{{STATIC_IP}}", savedStaticIP);
    html.replace("{{LOCAL_IP}}", (wifiState == WIFI_CONNECTED) ? WiFi.localIP().toString() : local_IP.toString());
    html.replace("{{CONFIDENCE}}", String(minMatchScore));
    html.replace("{{MEMBERS}}", String(getMemberCount()));
    html.replace("{{WIFI_STATUS}}", (wifiState == WIFI_CONNECTED) ? "CONNECTED" : "AP MODE");
    html.replace("{{WIFI_PILL_CLASS}}", (wifiState == WIFI_CONNECTED) ? "pill-green" : "pill-cyan");
    html.replace("{{PC_STATUS}}", pcConnected ? "PC: OK" : "PC: OFFLINE");
    html.replace("{{PC_PILL_CLASS}}", pcConnected ? "pill-green" : "pill-dark");
    html.replace("{{SETTINGS_OPEN}}", (wifiState == WIFI_CONNECTED) ? "" : "open");

    server.send(
        200,
        "text/html",
        html
    );
}


void handleSave()
{
  String admin_pass = server.arg("admin_pass");
  admin_pass.trim();

  // Protect changes with password 1234
  if (admin_pass != "1234")
  {
    Serial.println("[WIFI] Unauthorized save attempt - incorrect password");
    String errHtml = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HULK GYM - Error</title>
<style>
body { margin:0; min-height:100vh; background:#050505; color:white; font-family:Arial,sans-serif; display:flex; justify-content:center; align-items:center; }
.card { width:92%; max-width:420px; background:#101010; border:2px solid #ff3333; border-radius:22px; padding:30px; text-align:center; box-shadow:0 0 30px rgba(255,51,51,0.25); }
.logo { color:#ff3333; font-size:28px; font-weight:900; margin-bottom:10px; }
p { color:#ccc; font-size:15px; line-height:1.6; margin-bottom:25px; }
a { display:inline-block; width:100%; box-sizing:border-box; padding:15px; border-radius:10px; background:#ff3333; color:white; font-size:16px; font-weight:bold; text-decoration:none; }
</style>
</head>
<body>
<div class="card">
<div class="logo">ACCESS DENIED</div>
<p>Incorrect Admin Password! You must enter <b>1234</b> to modify network and system settings.</p>
<a href="/">Try Again</a>
</div>
</body>
</html>
)rawliteral";
    server.send(403, "text/html", errHtml);
    return;
  }

  String ssid = server.arg("ssid");
  String password = server.arg("password");
  String static_ip = server.arg("static_ip");
  String confidence_str = server.arg("confidence");

  ssid.trim();
  static_ip.trim();
  confidence_str.trim();

  Serial.println("=== WIFI & SYSTEM SETTINGS RECEIVED ===");
  Serial.print("SSID: "); Serial.println(ssid);
  Serial.print("Static IP: "); Serial.println(static_ip);
  Serial.print("Confidence: "); Serial.println(confidence_str);

  prefs.begin("wifi", false);

  if (ssid.length() > 0)
  {
    prefs.putString("ssid", ssid);
    prefs.putString("pass", password);
    savedSSID = ssid;
    savedPassword = password;
  }

  if (static_ip.length() > 0)
  {
    IPAddress parsedIP;
    if (parsedIP.fromString(static_ip))
    {
      prefs.putString("ip", static_ip);
      savedStaticIP = static_ip;
      local_IP = parsedIP;
      gateway = IPAddress(local_IP[0], local_IP[1], local_IP[2], 1);
    }
  }

  int confVal = confidence_str.toInt();
  if (confVal >= 10 && confVal <= 255)
  {
    minMatchScore = (uint16_t)confVal;
    prefs.putUInt("confid", minMatchScore);
  }

  prefs.end();

  String okHtml = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HULK GYM - Saved</title>
<style>
body { margin:0; min-height:100vh; background:#050505; color:white; font-family:Arial,sans-serif; display:flex; justify-content:center; align-items:center; }
.card { width:92%; max-width:420px; background:#101010; border:2px solid #9cff00; border-radius:22px; padding:30px; text-align:center; box-shadow:0 0 30px rgba(156,255,0,0.25); }
.logo { color:#9cff00; font-size:28px; font-weight:900; margin-bottom:10px; }
.info { background:#181818; border-radius:10px; padding:15px; margin:20px 0; text-align:left; font-size:14px; line-height:1.8; border-left:3px solid #9cff00; }
.val { color:#9cff00; font-weight:bold; }
.spinner { margin:20px auto; width:36px; height:36px; border:3px solid #333; border-top:3px solid #9cff00; border-radius:50%; animation:spin 1s linear infinite; }
@keyframes spin { 0% { transform:rotate(0deg); } 100% { transform:rotate(360deg); } }
</style>
</head>
<body>
<div class="card">
<div class="logo">HULK GYM</div>
<h3>Settings Saved!</h3>
<div class="info">
Wi-Fi: <span class="val">)rawliteral" + savedSSID + R"rawliteral(</span><br>
Static IP: <span class="val">)rawliteral" + local_IP.toString() + R"rawliteral(</span><br>
Gateway: <span class="val">)rawliteral" + gateway.toString() + R"rawliteral(</span><br>
Confidence: <span class="val">)rawliteral" + String(minMatchScore) + R"rawliteral(</span>
</div>
<div class="spinner"></div>
<p style="color:#aaa;font-size:13px;">Rebooting terminal and connecting now...</p>
</div>
</body>
</html>
)rawliteral";

  server.send(200, "text/html", okHtml);

  delay(1500);
  ESP.restart();
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
  response["ip"] = WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : local_IP.toString();
  response["confidence"] = minMatchScore;

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

  uint16_t targetFpId = (lastScanFingerprintID > 0) ? lastScanFingerprintID : displayFingerprintID;
  bool targetAllowed = (lastScanFingerprintID > 0) ? lastScanAllowed : displayAllowed;

  bool found = findMemberByFingerprint(
    targetFpId,
    memberID,
    allowed
  );

  bool scanActive = (targetFpId > 0) && (millis() - lastScanTimestamp < 15000);

  String json;

  json.reserve(180);

  json += "{";
  json += "\"success\":true,";
  json += "\"sequence\":";
  json += String(scanSequence);
  json += ",";
  json += "\"fingerprint_id\":";
  json += String(targetFpId);
  json += ",";
  json += "\"member_id\":";
  json += "\"";
  json += found ? memberID : "";
  json += "\",";
  json += "\"allowed\":";
  json += targetAllowed ? "true" : "false";
  json += ",";
  json += "\"scan_active\":";
  json += scanActive ? "true" : "false";
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

  if (displayAllowed)
  {
    drawBitmap1BitFast(160 - (AR_MSG_WELCOME_W / 2), 325, AR_MSG_WELCOME_DATA, AR_MSG_WELCOME_W, AR_MSG_WELCOME_H, TFT_GREEN);

    String name = displayName;
    if (name.length() > 0)
    {
      drawArabicDynamicText(name, 160, 360, TFT_WHITE);
    }

    String daysLine = "متبقي: " + String(displayDaysLeft) + " يوم";
    drawArabicDynamicText(daysLine, 160, 400, TFT_CYAN);
  }
  else
  {
    drawBitmap1BitFast(160 - (AR_STATUS_EXPIRED_W / 2), 325, AR_STATUS_EXPIRED_DATA, AR_STATUS_EXPIRED_W, AR_STATUS_EXPIRED_H, TFT_RED);

    String name = displayName;
    if (name.length() > 0)
    {
      drawArabicDynamicText(name, 160, 360, TFT_WHITE);
    }

    String expLine;
    if (displayDaysLeft < 0)
    {
      expLine = "منتهي منذ: " + String(-displayDaysLeft) + " يوم";
    }
    else if (displayDaysLeft == 0)
    {
      expLine = "انتهى الاشتراك اليوم";
    }
    else
    {
      expLine = "انتهى: " + displayEndDate;
    }
    drawArabicDynamicText(expLine, 160, 400, TFT_YELLOW);
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
  loadWiFiCredentials();

  WiFi.mode(WIFI_AP_STA);
  WiFi.config(
    local_IP,
    gateway,
    subnet,
    dns1,
    dns2
  );
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
server.on("/logs", HTTP_GET, handleLogs);
server.on("/clear_logs", HTTP_POST, handleClearLogs);
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
  tft.fillRect(40, 330, 240, 40, TFT_BLACK);

  if (txt == "READY" || txt == "جاهز") {
    drawBitmap1BitFast(160 - (AR_STATUS_READY_W / 2), 340, AR_STATUS_READY_DATA, AR_STATUS_READY_W, AR_STATUS_READY_H, color);
  } else if (txt == "SCANNING" || txt == "جاري القراءة") {
    drawBitmap1BitFast(160 - (AR_STATUS_SCANNING_W / 2), 340, AR_STATUS_SCANNING_DATA, AR_STATUS_SCANNING_W, AR_STATUS_SCANNING_H, color);
  } else if (txt == "ACCESS GRANTED" || txt == "GRANTED" || txt == "مسموح بالدخول") {
    drawBitmap1BitFast(160 - (AR_STATUS_GRANTED_W / 2), 340, AR_STATUS_GRANTED_DATA, AR_STATUS_GRANTED_W, AR_STATUS_GRANTED_H, color);
  } else if (txt == "EXPIRED" || txt == "الاشتراك منتهي") {
    drawBitmap1BitFast(160 - (AR_STATUS_EXPIRED_W / 2), 340, AR_STATUS_EXPIRED_DATA, AR_STATUS_EXPIRED_W, AR_STATUS_EXPIRED_H, color);
  } else if (txt == "NOT FOUND" || txt == "غير مسجل") {
    drawBitmap1BitFast(160 - (AR_STATUS_NOT_FOUND_W / 2), 340, AR_STATUS_NOT_FOUND_DATA, AR_STATUS_NOT_FOUND_W, AR_STATUS_NOT_FOUND_H, color);
  } else if (txt == "ENROLL [1/4]" || txt == "STEP [1/4]" || txt == "تسجيل [1/4]" || txt == "ENROLL [1/2]") {
    drawBitmap1BitFast(160 - (AR_STATUS_ENROLL_1_W / 2), 340, AR_STATUS_ENROLL_1_DATA, AR_STATUS_ENROLL_1_W, AR_STATUS_ENROLL_1_H, color);
  } else if (txt == "ENROLL [2/4]" || txt == "STEP [2/4]" || txt == "تسجيل [2/4]" || txt == "ENROLL [2/2]" || txt == "STEP [2/2]") {
    drawBitmap1BitFast(160 - (AR_STATUS_ENROLL_2_W / 2), 340, AR_STATUS_ENROLL_2_DATA, AR_STATUS_ENROLL_2_W, AR_STATUS_ENROLL_2_H, color);
  } else if (txt == "ENROLL [3/4]" || txt == "STEP [3/4]" || txt == "تسجيل [3/4]") {
    drawBitmap1BitFast(160 - (AR_STATUS_ENROLL_3_W / 2), 340, AR_STATUS_ENROLL_3_DATA, AR_STATUS_ENROLL_3_W, AR_STATUS_ENROLL_3_H, color);
  } else if (txt == "ENROLL [4/4]" || txt == "STEP [4/4]" || txt == "تسجيل [4/4]") {
    drawBitmap1BitFast(160 - (AR_STATUS_ENROLL_4_W / 2), 340, AR_STATUS_ENROLL_4_DATA, AR_STATUS_ENROLL_4_W, AR_STATUS_ENROLL_4_H, color);
  } else if (txt.startsWith("STEP [1/4] OK") || txt.startsWith("STEP [1/2] OK") || txt == "تم الالتقاط بنجاح") {
    drawBitmap1BitFast(160 - (AR_STATUS_STEP_OK_W / 2), 340, AR_STATUS_STEP_OK_DATA, AR_STATUS_STEP_OK_W, AR_STATUS_STEP_OK_H, color);
  } else if (txt == "PROCESSING" || txt == "جاري المعالجة") {
    drawBitmap1BitFast(160 - (AR_STATUS_PROCESSING_W / 2), 340, AR_STATUS_PROCESSING_DATA, AR_STATUS_PROCESSING_W, AR_STATUS_PROCESSING_H, color);
  } else if (txt == "SAVING" || txt == "جاري الحفظ") {
    drawBitmap1BitFast(160 - (AR_STATUS_SAVING_W / 2), 340, AR_STATUS_SAVING_DATA, AR_STATUS_SAVING_W, AR_STATUS_SAVING_H, color);
  } else if (txt == "SUCCESS" || txt == "تم بنجاح") {
    drawBitmap1BitFast(160 - (AR_STATUS_SUCCESS_W / 2), 340, AR_STATUS_SUCCESS_DATA, AR_STATUS_SUCCESS_W, AR_STATUS_SUCCESS_H, color);
  } else if (txt == "FAILED" || txt == "فشل التسجيل") {
    drawBitmap1BitFast(160 - (AR_STATUS_FAILED_W / 2), 340, AR_STATUS_FAILED_DATA, AR_STATUS_FAILED_W, AR_STATUS_FAILED_H, color);
  } else if (txt == "MISMATCH" || txt == "غير متطابق") {
    drawBitmap1BitFast(160 - (AR_STATUS_MISMATCH_W / 2), 340, AR_STATUS_MISMATCH_DATA, AR_STATUS_MISMATCH_W, AR_STATUS_MISMATCH_H, color);
  } else if (txt == "CANCELLED" || txt == "تم الإلغاء") {
    drawBitmap1BitFast(160 - (AR_STATUS_CANCELLED_W / 2), 340, AR_STATUS_CANCELLED_DATA, AR_STATUS_CANCELLED_W, AR_STATUS_CANCELLED_H, color);
  } else {
    drawArabicDynamicText(txt, 160, 340, color);
  }
}


// =====================================================
// MESSAGE
// =====================================================

void setMessage(
  String txt
)
{
  tft.fillRect(40, 390, 240, 35, TFT_BLACK);

  if (txt == "Place Your Finger" || txt == "ضع إصبعك على القارئ") {
    drawBitmap1BitFast(160 - (AR_MSG_PLACE_FINGER_W / 2), 398, AR_MSG_PLACE_FINGER_DATA, AR_MSG_PLACE_FINGER_W, AR_MSG_PLACE_FINGER_H, TFT_WHITE);
  } else if (txt == "Reading Finger..." || txt == "جاري قراءة البصمة...") {
    drawBitmap1BitFast(160 - (AR_MSG_READING_W / 2), 398, AR_MSG_READING_DATA, AR_MSG_READING_W, AR_MSG_READING_H, TFT_WHITE);
  } else if (txt == "Welcome" || txt == "أهلاً بك") {
    drawBitmap1BitFast(160 - (AR_MSG_WELCOME_W / 2), 398, AR_MSG_WELCOME_DATA, AR_MSG_WELCOME_W, AR_MSG_WELCOME_H, TFT_WHITE);
  } else if (txt == "Subscription Expired" || txt == "يرجى تجديد الاشتراك") {
    drawBitmap1BitFast(160 - (AR_MSG_PLEASE_RENEW_W / 2), 398, AR_MSG_PLEASE_RENEW_DATA, AR_MSG_PLEASE_RENEW_W, AR_MSG_PLEASE_RENEW_H, TFT_WHITE);
  } else if (txt == "Fingerprint Not Found" || txt == "البصمة غير موجودة") {
    drawBitmap1BitFast(160 - (AR_MSG_NOT_FOUND_MSG_W / 2), 398, AR_MSG_NOT_FOUND_MSG_DATA, AR_MSG_NOT_FOUND_MSG_W, AR_MSG_NOT_FOUND_MSG_H, TFT_WHITE);
  } else if (txt == "Place Finger Firmly" || txt == "ضع الإصبع بثبات") {
    drawBitmap1BitFast(160 - (AR_MSG_FIRM_FINGER_W / 2), 398, AR_MSG_FIRM_FINGER_DATA, AR_MSG_FIRM_FINGER_W, AR_MSG_FIRM_FINGER_H, TFT_WHITE);
  } else if (txt == "Lift Finger Now" || txt == "ارفع إصبعك الآن") {
    drawBitmap1BitFast(160 - (AR_MSG_LIFT_FINGER_W / 2), 398, AR_MSG_LIFT_FINGER_DATA, AR_MSG_LIFT_FINGER_W, AR_MSG_LIFT_FINGER_H, TFT_WHITE);
  } else if (txt == "Place Same Finger" || txt == "ضع نفس الإصبع") {
    drawBitmap1BitFast(160 - (AR_MSG_SAME_FINGER_W / 2), 398, AR_MSG_SAME_FINGER_DATA, AR_MSG_SAME_FINGER_W, AR_MSG_SAME_FINGER_H, TFT_WHITE);
  } else if (txt == "Creating Template..." || txt == "جاري دمج الصور...") {
    drawBitmap1BitFast(160 - (AR_MSG_CREATING_TEMPLATE_W / 2), 398, AR_MSG_CREATING_TEMPLATE_DATA, AR_MSG_CREATING_TEMPLATE_W, AR_MSG_CREATING_TEMPLATE_H, TFT_WHITE);
  } else if (txt == "Saving To Sensor..." || txt == "جاري الحفظ في الحساس...") {
    drawBitmap1BitFast(160 - (AR_MSG_SAVING_SENSOR_W / 2), 398, AR_MSG_SAVING_SENSOR_DATA, AR_MSG_SAVING_SENSOR_W, AR_MSG_SAVING_SENSOR_H, TFT_WHITE);
  } else if (txt == "Enrollment Complete" || txt == "تم تسجيل البصمة بنجاح") {
    drawBitmap1BitFast(160 - (AR_MSG_ENROLL_COMPLETE_W / 2), 398, AR_MSG_ENROLL_COMPLETE_DATA, AR_MSG_ENROLL_COMPLETE_W, AR_MSG_ENROLL_COMPLETE_H, TFT_GREEN);
  } else if (txt == "Enrollment Failed" || txt == "فشل تسجيل البصمة") {
    drawBitmap1BitFast(160 - (AR_MSG_ENROLL_FAILED_MSG_W / 2), 398, AR_MSG_ENROLL_FAILED_MSG_DATA, AR_MSG_ENROLL_FAILED_MSG_W, AR_MSG_ENROLL_FAILED_MSG_H, TFT_RED);
  } else if (txt == "Enrollment Cancelled" || txt == "تم إلغاء التسجيل") {
    drawBitmap1BitFast(160 - (AR_MSG_ENROLL_CANCEL_MSG_W / 2), 398, AR_MSG_ENROLL_CANCEL_MSG_DATA, AR_MSG_ENROLL_CANCEL_MSG_W, AR_MSG_ENROLL_CANCEL_MSG_H, TFT_YELLOW);
  } else if (txt == "Lift Finger Then Place" || txt == "Lift & Try Again" || txt == "ارفع وحاول ثانية") {
    drawBitmap1BitFast(160 - (AR_MSG_RETRY_MSG_W / 2), 398, AR_MSG_RETRY_MSG_DATA, AR_MSG_RETRY_MSG_W, AR_MSG_RETRY_MSG_H, TFT_YELLOW);
  } else {
    drawArabicDynamicText(txt, 160, 398, TFT_WHITE);
  }
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
    "Welcome"
  );



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
// EXPIRED (KNOWN MEMBER, BUT SUBSCRIPTION EXPIRED)
// =====================================================

void showExpired(unsigned long duration)
{
  setRGB(true, false, false);
  searchMode = false;

  clearDynamicArea();

  drawFingerprint(
    TFT_RED
  );

  setStatus(
    "EXPIRED",
    TFT_RED
  );

  setMessage(
    "Subscription Expired"
  );

  Serial.println(
    "[STATUS] SUBSCRIPTION EXPIRED"
  );

  memberDisplayActive = true;
  memberDisplayUntil = millis() + duration;
}


// =====================================================
// DENIED (NOT FOUND / LOW SCORE / NO MATCH)
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
    "NOT FOUND",
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
  playAudio(1);
  logDiag("[SCAN]", "Finger detected on sensor");

  DBG("[SCAN] FINGER DETECTED -> showScanning()");
  showScanning();
  DBG("[SCAN] showScanning() DONE");


  // Wait a moment for stable finger contact, then re-acquire image
  delay(100);
  p = finger.getImage();
  if (p != FINGERPRINT_OK)
  {
    delay(50);
    p = finger.getImage();
  }


  if (
    p != FINGERPRINT_OK
  )
  {
    logDiag("[ERROR]", "Finger image capture error (code " + String(p) + ")");
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
    logDiag("[SENSOR]", "Feature extraction failed - check finger placement (code " + String(p) + ")");
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

  // Fallback: if fast heuristic search fails to match, do a full database search
  if (p == FINGERPRINT_NOTFOUND)
  {
    DBG("[SCAN] Fast search returned NOTFOUND, trying full fingerSearch()...");
    p = finger.fingerSearch();
    DBG_PRINT("[SCAN] fingerSearch fallback result = ");
    DBG(p);
  }


  if (
    p == FINGERPRINT_OK
  )
  {
    uint16_t fingerprintID =
      finger.fingerID;

    uint16_t confidence =
      finger.confidence;

    Serial.print("[R307] ID: ");
    Serial.print(fingerprintID);
    Serial.print(" | Confidence: ");
    Serial.print(confidence);
    Serial.print(" (Min: ");
    Serial.print(minMatchScore);
    Serial.println(")");

    // =================================================
    // MANUAL MATCH SCORE CHECK
    // =================================================
    // R307 can return a candidate ID with a low score.
    // Reject it manually if confidence is below the
    // threshold configured at the top of this file.
    if (confidence < minMatchScore)
    {
      logDiag("[REJECT]", "Candidate ID #" + String(fingerprintID) + " | Confidence: " + String(confidence) + " < " + String(minMatchScore) + " (Score Too Low)");
      Serial.print("[ACCESS] MATCH SCORE TOO LOW: ");
      Serial.print(confidence);
      Serial.print(" < ");
      Serial.println(minMatchScore);

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

    // Store lightweight scan event.
    DBG("[SCAN] Setting scan display state");
    displayFingerprintID = fingerprintID;
    displayAllowed = allowed;
    lastScanFingerprintID = fingerprintID;
    lastScanAllowed = allowed;
    lastScanTimestamp = millis();
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
      logDiag("[ALLOWED]", "Match ID #" + String(fingerprintID) + " | Confidence: " + String(confidence) + " >= " + String(minMatchScore) + " -> ACCESS GRANTED");
      Serial.println("[ACCESS] ALLOWED");
    }
    else
    {
      logDiag("[DENIED]", "Match ID #" + String(fingerprintID) + " | Confidence: " + String(confidence) + " -> SUBSCRIPTION EXPIRED");
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
      showExpired(FINGERPRINT_KNOWN_RESULT_DELAY);
    }
    DBG("[SCAN] local access display DONE");
  }
  else if (p == FINGERPRINT_NOTFOUND)
  {
    logDiag("[NOT_FOUND]", "No match found in fingerprint database");
    DBG("[SCAN] FINGERPRINT NOT FOUND");
    Serial.println("[ACCESS] FINGERPRINT NOT FOUND (No match in database)");

    DBG("[SCAN] Calling showDenied()");
    showDenied(FINGERPRINT_NOT_FOUND_DELAY);
    DBG("[SCAN] showDenied() DONE");
  }
  else
  {
    logDiag("[ERROR]", "Finger search failed (error code " + String(p) + ")");
    showDenied(FINGERPRINT_NOT_FOUND_DELAY);
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
  setStatus("ENROLL [1/4]", TFT_CYAN);
  setMessage("Place Finger Firmly");
  Serial.println("[ENROLL] ASYNC START (4-Sample Engine)");
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
        delay(120); // Settling delay for stable skin contact
        finger.getImage();
        p = finger.image2Tz(1);
        if (p == FINGERPRINT_OK)
        {
          Serial.println("[ENROLL] SAMPLE 1 OK: Image captured");
          playAudio(1);
          setStatus("STEP [1/4] OK", TFT_GREEN);
          setMessage("Lift Finger Now");
          asyncEnrollState = ENROLL_REMOVE_FIRST;
          asyncEnrollStateStarted = millis();
        }
        else
        {
          Serial.println("[ENROLL] SAMPLE 1 ERROR: Feature extraction failed");
          finishAsyncEnrollment(false, false, "first_scan_failed"); delay(1000); showReady();
        }
      }
      else if (elapsed >= ASYNC_FIRST_TIMEOUT)
      {
        Serial.println("[ENROLL] TIMEOUT: First finger not placed");
        finishAsyncEnrollment(false, false, "first_scan_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_REMOVE_FIRST:
      p = finger.getImage();
      if (p == FINGERPRINT_NOFINGER)
      {
        Serial.println("[ENROLL] FINGER REMOVED: Ready for sample 2");
        setStatus("ENROLL [2/4]", TFT_CYAN);
        setMessage("Place Same Finger");
        asyncEnrollState = ENROLL_WAIT_SECOND;
        asyncEnrollStateStarted = millis();
      }
      else if (elapsed >= ASYNC_REMOVE_TIMEOUT)
      {
        Serial.println("[ENROLL] TIMEOUT: Finger not lifted");
        finishAsyncEnrollment(false, false, "remove_finger_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_WAIT_SECOND:
      p = finger.getImage();
      if (p == FINGERPRINT_OK)
      {
        delay(120);
        finger.getImage();
        p = finger.image2Tz(2);
        if (p == FINGERPRINT_OK)
        {
          Serial.println("[ENROLL] SAMPLE 2 OK: Checking model");
          playAudio(1);
          p = finger.createModel();
          if (p == FINGERPRINT_OK)
          {
            Serial.println("[ENROLL] Match on sample 2! Saving template model");
            setStatus("SAVING", TFT_CYAN);
            setMessage("Saving To Sensor...");
            asyncEnrollState = ENROLL_SAVE;
            asyncEnrollStateStarted = millis();
          }
          else
          {
            Serial.println("[ENROLL] Sample 2 not yet matching - proceeding to sample 3");
            setStatus("ENROLL [3/4]", TFT_YELLOW);
            setMessage("Lift Finger Now");
            asyncEnrollState = ENROLL_REMOVE_SECOND;
            asyncEnrollStateStarted = millis();
          }
        }
        else
        {
          setStatus("RETRY [2/4]", TFT_YELLOW);
          setMessage("Lift Finger Then Place");
          asyncEnrollState = ENROLL_REMOVE_FIRST;
          asyncEnrollStateStarted = millis();
        }
      }
      else if (elapsed >= ASYNC_SECOND_TIMEOUT)
      {
        Serial.println("[ENROLL] TIMEOUT: Second finger not placed");
        finishAsyncEnrollment(false, false, "second_scan_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_REMOVE_SECOND:
      p = finger.getImage();
      if (p == FINGERPRINT_NOFINGER)
      {
        Serial.println("[ENROLL] FINGER REMOVED: Ready for sample 3");
        setStatus("ENROLL [3/4]", TFT_CYAN);
        setMessage("Place Same Finger");
        asyncEnrollState = ENROLL_WAIT_THIRD;
        asyncEnrollStateStarted = millis();
      }
      else if (elapsed >= ASYNC_REMOVE_TIMEOUT)
      {
        finishAsyncEnrollment(false, false, "remove_finger_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_WAIT_THIRD:
      p = finger.getImage();
      if (p == FINGERPRINT_OK)
      {
        delay(120);
        finger.getImage();
        p = finger.image2Tz(2);
        if (p == FINGERPRINT_OK)
        {
          playAudio(1);
          p = finger.createModel();
          if (p == FINGERPRINT_OK)
          {
            Serial.println("[ENROLL] Match on sample 3! Saving template model");
            setStatus("SAVING", TFT_CYAN);
            setMessage("Saving To Sensor...");
            asyncEnrollState = ENROLL_SAVE;
            asyncEnrollStateStarted = millis();
          }
          else
          {
            // Also store sample 3 in Buffer 1 to compare with sample 4
            finger.image2Tz(1);
            Serial.println("[ENROLL] Sample 3 stored in Buffer 1 - proceeding to sample 4");
            setStatus("ENROLL [4/4]", TFT_YELLOW);
            setMessage("Lift Finger Now");
            asyncEnrollState = ENROLL_REMOVE_THIRD;
            asyncEnrollStateStarted = millis();
          }
        }
      }
      else if (elapsed >= ASYNC_SECOND_TIMEOUT)
      {
        finishAsyncEnrollment(false, false, "second_scan_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_REMOVE_THIRD:
      p = finger.getImage();
      if (p == FINGERPRINT_NOFINGER)
      {
        Serial.println("[ENROLL] FINGER REMOVED: Ready for sample 4");
        setStatus("ENROLL [4/4]", TFT_CYAN);
        setMessage("Place Same Finger");
        asyncEnrollState = ENROLL_WAIT_FOURTH;
        asyncEnrollStateStarted = millis();
      }
      else if (elapsed >= ASYNC_REMOVE_TIMEOUT)
      {
        finishAsyncEnrollment(false, false, "remove_finger_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_WAIT_FOURTH:
      p = finger.getImage();
      if (p == FINGERPRINT_OK)
      {
        delay(120);
        finger.getImage();
        p = finger.image2Tz(2);
        if (p == FINGERPRINT_OK)
        {
          playAudio(1);
          p = finger.createModel();
          if (p == FINGERPRINT_OK)
          {
            Serial.println("[ENROLL] Match on sample 4! Saving template model");
            setStatus("SAVING", TFT_CYAN);
            setMessage("Saving To Sensor...");
            asyncEnrollState = ENROLL_SAVE;
            asyncEnrollStateStarted = millis();
          }
          else
          {
            Serial.println("[ENROLL] ERROR: Prints do not match after 4 samples");
            finishAsyncEnrollment(false, false, "template_mismatch"); delay(1500); showReady();
          }
        }
      }
      else if (elapsed >= ASYNC_SECOND_TIMEOUT)
      {
        finishAsyncEnrollment(false, false, "second_scan_timeout"); delay(1000); showReady();
      }
      break;

    case ENROLL_SAVE:
      p = finger.storeModel(asyncEnrollFingerprintID);
      if (p == FINGERPRINT_OK)
      {
        Serial.print("[ENROLL] SUCCESS: Saved as ID #"); Serial.println(asyncEnrollFingerprintID);
        logDiag("[ENROLL]", "Fingerprint enrolled successfully as ID #" + String(asyncEnrollFingerprintID));
        playAudio(2);
        finishAsyncEnrollment(true, false, "");
        delay(2000);
        showReady();
      }
      else
      {
        Serial.print("[ENROLL] ERROR: Failed to store template (code "); Serial.print(p); Serial.println(")");
        logDiag("[ERROR]", "Failed to store fingerprint model (code " + String(p) + ")");
        finishAsyncEnrollment(false, false, "save_failed");
        delay(1500);
        showReady();
      }
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
    case ENROLL_WAIT_FIRST: step = "waiting_sample_1"; break;
    case ENROLL_REMOVE_FIRST: step = "waiting_remove_1"; break;
    case ENROLL_WAIT_SECOND: step = "waiting_sample_2"; break;
    case ENROLL_REMOVE_SECOND: step = "waiting_remove_2"; break;
    case ENROLL_WAIT_THIRD: step = "waiting_sample_3"; break;
    case ENROLL_REMOVE_THIRD: step = "waiting_remove_3"; break;
    case ENROLL_WAIT_FOURTH: step = "waiting_sample_4"; break;
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

  delay(120);
  finger.getImage();
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

    delay(120);
    finger.getImage();
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