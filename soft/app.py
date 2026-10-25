# -*- coding: utf-8 -*-
"""
HULK GYM - PySide6 JSON Prototype V11
------------------------------------
Desktop maximized JSON prototype with protected settings, WhatsApp receipts, reminders, resend, daily manager report, dark popups, and safer WhatsApp sending.
Ready for Windows EXE packaging.
"""
from __future__ import annotations

import calendar
import ctypes
import faulthandler
import hashlib
import json
import math
import os
import re
import shutil
import sys
import threading
import time
import traceback
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Union

import esp_client

ESP_SYNC_LOCK = threading.Lock()

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except Exception:  # pragma: no cover - optional dependency
    Credentials = None  # type: ignore[assignment]
    InstalledAppFlow = None  # type: ignore[assignment]
    build = None  # type: ignore[assignment]
from html import escape
from pathlib import Path
from PySide6.QtCore import QDate, QSize, Qt, QEvent, QThread, QTimer, Signal, QStringListModel, QObject, QMarginsF, QRegularExpression, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QAction, QFont, QKeySequence, QPixmap, QTextDocument, QPdfWriter, QPainter, QRegularExpressionValidator, QPageSize, QPageLayout
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QBoxLayout,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QInputDialog,
    QProgressDialog,
    QPushButton,
    QCheckBox,
    QAbstractScrollArea,
    QScrollArea,
    QScroller,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QFileDialog,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "HULK GYM"
DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%d %H:%M"
DISPLAY_DATE_FMT = "dd/MM/yyyy"


def debug_log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        log_path = BASE_DIR / "app_debug.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# -----------------------------
# Paths / JSON helpers
# -----------------------------

def external_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_resource_path(relative: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / relative


def logo_path() -> Optional[Path]:
    external = external_base_dir() / "assets" / "logo.png"
    if external.exists():
        return external
    bundled = bundled_resource_path("assets/logo.png")
    if bundled.exists():
        return bundled
    return None


BASE_DIR = external_base_dir()
DATA_DIR = BASE_DIR / "data"
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)
GOOGLE_CONTACTS_SCOPES = ["https://www.googleapis.com/auth/contacts"]


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        # In onefile EXE, bundled sample data lives in _MEIPASS.
        # First run copies it beside the EXE, then the app writes normally there.
        try:
            if path.parent.name == "data":
                bundled = bundled_resource_path(f"data/{path.name}")
                if bundled.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(bundled.read_bytes())
                    with path.open("r", encoding="utf-8") as f:
                        return json.load(f)
        except Exception:
            pass
        write_json(path, default)
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        backup = path.with_suffix(path.suffix + ".broken")
        try:
            path.replace(backup)
        except Exception:
            pass
        write_json(path, default)
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def normalize_mobile(value: str) -> str:
    normalized = re.sub(r"\D+", "", value or "")
    if not normalized:
        return ""
    if normalized.startswith("00201") and len(normalized) == 14:
        normalized = "0" + normalized[4:]
    elif normalized.startswith("201") and len(normalized) == 12:
        normalized = "0" + normalized[2:]
    elif normalized.startswith("966") and len(normalized) >= 13:
        normalized = normalized[3:]
    if len(normalized) == 10 and normalized.startswith("1"):
        normalized = "0" + normalized
    if len(normalized) == 11 and normalized.startswith("0"):
        return normalized
    if len(normalized) == 11 and normalized.startswith("1"):
        return "0" + normalized[1:]
    if len(normalized) > 11:
        return normalized
    return normalized


def normalize_clock_time(value: str) -> str:
    """Normalize flexible time input to HH:MM (24-hour), else return empty string."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    raw = raw.replace(" ", "")
    match = re.fullmatch(r"(\d{1,2}):([0-5]\d)", raw)
    if not match:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 0 or hour > 23:
        return ""
    return f"{hour:02d}:{minute:02d}"


def whatsapp_message_topic(message: Dict[str, Any]) -> str:
    """Return the topic key used by the WhatsApp sender to choose a random template."""
    topic = str(message.get("type", "") or message.get("topic", "") or "").strip()
    return topic or "general"


def is_receipt_protected_whatsapp_message(message: Dict[str, Any]) -> bool:
    """Protected WhatsApp messages (receipt, invoice, renewal, sub ended/expired, daily report) must NEVER be deleted.

    Only reminders (reminder_1, reminder_3) are subject to automated deletion or bulk cleanup.
    """
    msg_type = str(message.get("type", "")).strip().lower()
    return msg_type not in ("reminder_1", "reminder_3")


def split_message_bank_entries(raw_text: str) -> List[str]:
    """Split a message-bank textarea into entries using == as the separator.

    Older data used one message per line, so we keep that as a fallback.
    """
    if raw_text is None:
        return []

    text = str(raw_text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    sections = [section.strip() for section in re.split(r"\s*==\s*", text) if section.strip()]
    if len(sections) > 1:
        return sections

    return [line.strip() for line in text.splitlines() if line.strip()]


def join_message_bank_entries(messages: List[str]) -> str:
    """Join bank entries back into the editor format using == separators."""
    cleaned = [str(item).strip() for item in messages if str(item).strip()]
    if not cleaned:
        return ""
    return "\n==\n".join(cleaned)


def load_whatsapp_message_bank(path: Optional[Path] = None) -> Dict[str, List[str]]:
    """Load the message bank from the app's data folder and normalize it to dict[str, list[str]]."""
    bank_path = path or (DATA_DIR / "whatsapp_message_bank.json")
    default_bank: Dict[str, List[str]] = {"general": []}

    if not bank_path.exists():
        return default_bank

    try:
        with bank_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        print(f"[whatsapp_message_bank] Failed to load {bank_path}: {exc}")
        return default_bank

    if not isinstance(payload, dict):
        return default_bank

    normalized: Dict[str, List[str]] = {}
    for key, variants in payload.items():
        if isinstance(variants, (list, tuple)):
            values = [str(item) for item in variants if str(item).strip()]
        else:
            values = [str(variants)] if str(variants).strip() else []
        normalized[str(key)] = values

    return normalized or default_bank


def save_whatsapp_message_bank(bank: Dict[str, List[str]], path: Optional[Path] = None) -> bool:
    """Save the message bank to JSON file."""
    bank_path = path or (DATA_DIR / "whatsapp_message_bank.json")
    try:
        write_json(bank_path, bank)
        print(f"[whatsapp_message_bank] Successfully saved {len(bank)} topics to {bank_path}")
        return True
    except Exception as exc:
        print(f"[whatsapp_message_bank] Failed to save {bank_path}: {exc}")
        return False


def format_message_with_context(message: str, context: Dict[str, Any]) -> str:
    """Replace placeholders in message template with actual context values.
    
    Supports placeholders:
    - {name}: member name
    - {end_date}: subscription end date
    - {amount_paid}: amount paid
    - {remaining_amount}: remaining balance
    - {date}: transaction/payment date
    """
    try:
        # Safe string formatting that handles missing keys
        formatted = message.format(**context)
        return formatted
    except KeyError as e:
        print(f"[format_message_with_context] Missing context key: {e}")
        return message
    except Exception as exc:
        print(f"[format_message_with_context] Error formatting message: {exc}")
        return message


def resolve_unified_entry_mode(value: Optional[str]) -> str:
    if value is None:
        return "new_subscription"
    normalized = str(value).strip().lower()
    if normalized in {"new", "new_member", "new_subscription", "signup"}:
        return "new_subscription"
    if normalized in {"renew", "renewal", "renew_sub"}:
        return "renewal"
    if normalized in {"remaining", "pay_remaining", "pay", "remaining_payment"}:
        return "remaining"
    return "new_subscription"
    return normalized


def validate_mobile(mobile: str) -> tuple[bool, str]:
    """
    Validate mobile number with strict local rules.
    Returns (is_valid, error_message)
    """
    cleaned = normalize_mobile(mobile)

    if not cleaned:
        return False, "الموبايل فارغ. اكتب رقم الموبايل بالأرقام فقط."

    if not cleaned.isdigit():
        return False, "رقم الموبايل يجب أن يحتوي أرقام فقط."

    if len(cleaned) > 11:
        return False, "رقم الموبايل غير صالح. يجب أن يكون 11 رقمًا بدءًا من 01."

    if not cleaned.startswith("0"):
        return False, "رقم الموبايل يجب أن يبدأ بـ 01 ويكون 11 رقمًا."

    if len(cleaned) != 11:
        return False, "رقم الموبايل غير صالح. يجب أن يكون 11 رقمًا بدءًا من 01."

    return True, ""


def resolve_google_contact_paths() -> tuple[Path, Path]:
    credentials_path = DATA_DIR / "credentials.json"
    token_path = DATA_DIR / "token.json"

    legacy_credentials = BASE_DIR / "credentials.json"
    legacy_token = BASE_DIR / "token.json"

    if not credentials_path.exists() and legacy_credentials.exists():
        try:
            credentials_path.write_bytes(legacy_credentials.read_bytes())
        except Exception:
            pass
    if not token_path.exists() and legacy_token.exists():
        try:
            token_path.write_bytes(legacy_token.read_bytes())
        except Exception:
            pass

    return credentials_path, token_path


def get_google_contacts_service() -> tuple[Optional[Any], str]:
    if Credentials is None or InstalledAppFlow is None or build is None:
        return None, "مكتبات Google Contacts غير مثبتة."

    credentials_path, token_path = resolve_google_contact_paths()
    if not credentials_path.exists():
        return None, f"ملف credentials.json غير موجود في {credentials_path}."

    creds = None
    try:
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_CONTACTS_SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        from google.auth.transport.requests import Request
                        creds.refresh(Request())
                    except Exception:
                        creds = None
                if not creds or not creds.valid:
                    try:
                        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GOOGLE_CONTACTS_SCOPES)
                        creds = flow.run_local_server(port=0)
                        token_path.write_text(creds.to_json(), encoding="utf-8")
                    except Exception as exc:
                        return None, f"فشل إعادة تسجيل Google Contacts: {exc}"
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GOOGLE_CONTACTS_SCOPES)
            creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json(), encoding="utf-8")

        if not creds or not creds.valid:
            return None, "لم يتم التحقق من Google Contacts بنجاح."

        service = build("people", "v1", credentials=creds)
        return service, ""
    except Exception as exc:
        return None, f"فشل الاتصال بـ Google Contacts: {exc}"


def sync_member_to_google_contacts(
    member: Dict[str, Any],
    *,
    force: bool = False,
    service: Optional[Any] = None,
    max_retries: int = 3,
) -> tuple[bool, str]:
    try:
        if service is None:
            svc, err = get_google_contacts_service()
            if not svc:
                return False, err
        else:
            svc = service

        name = str(member.get("name", "")).strip() or "عضو"
        mobile = str(member.get("mobile", "")).strip()
        contact = {
            "names": [{"givenName": name}],
            "phoneNumbers": [{"value": mobile}] if mobile else [],
        }

        last_error = ""
        for attempt in range(max_retries):
            try:
                svc.people().createContact(body=contact).execute()
                return True, "تم مزامنة العضو مع Google Contacts."
            except Exception as exc:
                err_str = str(exc).lower()
                is_rate_limit = (
                    "429" in err_str
                    or "resource_exhausted" in err_str
                    or "quota" in err_str
                    or "ratelimit" in err_str
                    or "503" in err_str
                )
                last_error = str(exc)
                if is_rate_limit and attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 2)
                    continue
                break
        return False, f"فشل مزامنة Google Contacts: {last_error}"
    except Exception as exc:
        return False, f"فشل مزامنة Google Contacts: {exc}"


def money(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        number = 0.0
    if number.is_integer():
        return f"{int(number):,} .ج"
    return f"{number:,.2f} .ج"


def parse_date(value: str) -> date:
    raw = str(value).strip()
    if not raw:
        return date.today()

    for fmt in (DATE_FMT, "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(raw).date()
    except Exception:
        return date.today()


def date_to_str(d: date) -> str:
    return d.strftime(DATE_FMT)


def display_date(value: Any) -> str:
    if not value:
        return "-"
    d = parse_date(str(value))
    return d.strftime("%d/%m/%Y")


def calculate_days_left(value: Any) -> int:
    if value is None:
        return 0
    raw = str(value).strip()
    if not raw:
        return 0

    try:
        end_date = parse_date(raw)
        return (end_date - date.today()).days
    except Exception:
        return 0


def subscription_days_text(end_date: str) -> str:
    if not end_date:
        return "-"
    end = parse_date(str(end_date))
    diff = (end - date.today()).days
    if diff < 0:
        days = abs(diff)
        if days == 0:
            return "انتهى اليوم"
        if days == 1:
            return "انتهى من يوم"
        return f"انتهى من {days} أيام"
    if diff == 0:
        return "ينتهي اليوم"
    if diff == 1:
        return "يتبقى يوم واحد"
    return f"يتبقى {diff} أيام"


def qdate_from_date(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def qdate_from_str(value: str) -> QDate:
    parsed = parse_date(value)
    return QDate(parsed.year, parsed.month, parsed.day)


def qdate_to_py(qd: QDate) -> date:
    return date(qd.year(), qd.month(), qd.day())


def now_str() -> str:
    return datetime.now().strftime(DATETIME_FMT)


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def gender_ar(value: str) -> str:
    return "أنثى" if value == "female" else "ذكر"


def status_ar(value: str) -> str:
    mapping = {
        "active": "مشترك حاليًا",
        "expired": "غير مشترك",
        "partial": "جزئي",
        "cancelled": "ملغي",
        "paid": "مدفوع",
    }
    return mapping.get(value or "", value or "-")


def operation_ar(value: str) -> str:
    mapping = {
        "new_subscription": "اشتراك جديد",
        "renewal": "تجديد اشتراك",
        "remaining_payment": "دفع المتبقي",
    }
    return mapping.get(value or "", value or "اشتراك جديد")


def whatsapp_type_ar(value: str) -> str:
    mapping = {
        "receipt": "إيصال دفع",
        "reminder_3": "تذكير 3 أيام",
        "reminder_1": "تذكير يوم واحد",
        "expired": "انتهاء اشتراك",
        "daily_report": "تقرير المدير",
        "custom": "رسالة",
    }
    return mapping.get(value or "", value or "رسالة")


def whatsapp_status_ar(value: str) -> str:
    mapping = {
        "pending": "معلق",
        "sent": "تم الإرسال",
        "failed": "فشل",
    }
    return mapping.get(value or "", value or "معلق")


def status_en_from_dates(end_date: str) -> str:
    try:
        parsed = datetime.strptime(str(end_date), DATE_FMT).date()
    except Exception:
        return "expired"
    return "active" if parsed >= date.today() else "expired"


def is_attendance_allowed_for_plan(plan_name: str, check_date: date, start_date: date) -> bool:
    plan = next((p for p in default_settings()["plans"] if str(p.get("name", "")) == plan_name), None)
    if plan is None:
        return True
    frequency = str(plan.get("frequency", "")).strip()
    if frequency == "يوم ويوم":
        delta = (check_date - start_date).days
        return delta >= 0 and delta % 2 == 0
    return True


def default_settings() -> Dict[str, Any]:
    return {
        "dashboard_password": "1234",
        "manager_mobile": "",
        "daily_report_time": "01:00",
        "plans": [
            {"name": "جلسة واحدة", "price": 50, "duration_days": 1, "months": 0, "frequency": "جلسة واحدة"},
            {"name": "شهري شامل - كل يوم", "price": 400, "duration_days": 29, "months": 0, "frequency": "كل يوم"},
            {"name": "شهري شامل - يوم ويوم", "price": 300, "duration_days": 13, "months": 0, "frequency": "يوم ويوم"},
            {"name": "شهري حديد - كل يوم", "price": 300, "duration_days": 29, "months": 0, "frequency": "كل يوم"},
            {"name": "شهري حديد - يوم ويوم", "price": 230, "duration_days": 13, "months": 0, "frequency": "يوم ويوم"},
        ],
        "payment_methods": ["نقدي", "انستاباي", "فودافون كاش", "تحويل بنكي", "بطاقة بنكية"],
        "expense_categories": [ "اخري", "إيجار", "معدات", "فاتورة كهرباء", "صيانة", "مستلزمات"],
        "expired_message_template": "تنبيه من HULK GYM\nأهلاً {name}\nاشتراكك انتهى بتاريخ: {end_date}\nنورتنا في أي وقت للتجديد والرجوع للتمرين 💪",
        "whatsapp_enabled": True,
        "whatsapp_send_mode": "typing",
        "whatsapp_letter_delay": 0.02,
    }


def search_blob(obj: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key, value in obj.items():
        if isinstance(value, (str, int, float)):
            parts.append(str(value))
    if "gender" in obj:
        parts.append(gender_ar(str(obj.get("gender"))))
    if "current_status" in obj:
        parts.append(status_ar(str(obj.get("current_status"))))
    if "status" in obj:
        parts.append(status_ar(str(obj.get("status"))))
    if "operation_type" in obj:
        parts.append(operation_ar(str(obj.get("operation_type"))))
    if "mobile" in obj:
        parts.append(normalize_mobile(str(obj.get("mobile"))))
    return " ".join(parts).lower()


def normalized_query(q: str) -> str:
    q = (q or "").strip().lower()
    replacements = {
        "انثى": "female أنثى",
        "انثي": "female أنثى",
        "بنت": "female أنثى",
        "سيدات": "female أنثى",
        "ذكر": "male ذكر",
        "راجل": "male ذكر",
        "رجال": "male ذكر",
        "نشط": "active مشترك حاليًا",
        "حالي": "active مشترك حاليًا",
        "منتهي": "expired غير مشترك",
        "غير مشترك": "expired غير مشترك",
        "مدفوع": "paid مدفوع",
        "جزئي": "partial جزئي",
        "تجديد": "renewal تجديد اشتراك",
        "اشتراك جديد": "new_subscription اشتراك جديد",
        "متبقي": "remaining_payment دفع المتبقي",
        "دفع المتبقي": "remaining_payment دفع المتبقي",
    }
    return replacements.get(q, q)


# -----------------------------
# Data store
# -----------------------------

class Store:
    def __init__(self) -> None:
        self.members_path = DATA_DIR / "members.json"
        self.payments_path = DATA_DIR / "payments.json"
        self.whatsapp_path = DATA_DIR / "whatsapp_messages.json"
        self.whatsapp_sent_history_path = DATA_DIR / "whatsapp_sent_history.json"
        self.expenses_path = DATA_DIR / "expenses.json"
        self.settings_path = DATA_DIR / "settings.json"
        self.members: List[Dict[str, Any]] = []
        self.payments: List[Dict[str, Any]] = []
        self.expenses: List[Dict[str, Any]] = []
        self.whatsapp_messages: List[Dict[str, Any]] = []
        self.whatsapp_sent_history: Dict[str, str] = {}
        self.settings: Dict[str, Any] = {}
        self.google_contacts_queue: List[Dict[str, Any]] = []
        self.google_contacts_queue_file = DATA_DIR / "google_contacts_pending.json"
        self.google_contacts_synced_numbers: List[str] = []
        self.google_contacts_synced_numbers_file = DATA_DIR / "google_contacts_synced_numbers.json"
        self.last_queued_receipt_message_id: str = ""
        self.esp_connected = False
        self.esp_status_checked_at = 0.0
        self.esp_enrollment_active = False
        self.load()

    def esp_command_allowed(self) -> bool:
        return (
            esp_client.is_enabled(self.settings)
            and self.esp_connected
            and time.monotonic() - self.esp_status_checked_at <= 65
        )

    def load(self) -> None:
        self.members = read_json(self.members_path, [])
        self.payments = read_json(self.payments_path, [])
        self.expenses = read_json(self.expenses_path, [])
        self.whatsapp_messages = read_json(self.whatsapp_path, [])
        history_data = read_json(self.whatsapp_sent_history_path, {})
        self.whatsapp_sent_history = history_data if isinstance(history_data, dict) else {}
        self.settings = read_json(self.settings_path, default_settings())
        self.google_contacts_queue = read_json(self.google_contacts_queue_file, [])
        self.google_contacts_synced_numbers = read_json(self.google_contacts_synced_numbers_file, [])
        self.migrate_settings()
        self._reset_google_sync_state_if_auth_changed()
        synced_set = self._get_google_synced_numbers()
        synced_changed = False
        for member in self.members:
            mobile = normalize_mobile(str(member.get("mobile", "") or ""))
            synced_raw = str(member.get("google_contact_synced_at", "")).strip()
            if mobile and synced_raw and mobile not in synced_set:
                synced_set.add(mobile)
                synced_changed = True
        if synced_changed:
            self._set_google_synced_numbers(synced_set)
            self.save_google_contacts_synced_numbers()
        self._bootstrap_sent_history_from_existing_messages(save=True)
        self.rollover_whatsapp_messages_if_needed()
        self.refresh_statuses(save=False)

    def _bootstrap_sent_history_from_existing_messages(self, save: bool = True) -> int:
        changed = 0
        for msg in self.whatsapp_messages:
            if str(msg.get("status", "")) != "sent":
                continue
            if self._remember_sent_whatsapp_message(msg, save=False):
                changed += 1
        if changed and save:
            self.save_whatsapp_sent_history()
        return changed

    def save_whatsapp_sent_history(self) -> None:
        write_json(self.whatsapp_sent_history_path, self.whatsapp_sent_history)

    def _member_cycle_history_key(self, member: Dict[str, Any], msg_type: str, cycle_key: str) -> str:
        msg_type = str(msg_type).strip()
        cycle_key = str(cycle_key).strip()
        member_id = str(member.get("member_id", "")).strip()
        mobile = normalize_mobile(str(member.get("mobile", "")))
        identity = member_id or mobile
        if not msg_type or not identity or not cycle_key:
            return ""
        return f"{msg_type}:{identity}:{cycle_key}"

    def _was_member_cycle_message_sent(self, member: Dict[str, Any], msg_type: str, cycle_key: str) -> bool:
        history = getattr(self, "whatsapp_sent_history", {})
        if not isinstance(history, dict):
            self.whatsapp_sent_history = {}
            history = self.whatsapp_sent_history
        key = self._member_cycle_history_key(member, msg_type, cycle_key)
        return bool(key and str(history.get(key, "")).strip())

    def _history_key_from_message(self, message: Dict[str, Any]) -> str:
        msg_type = str(message.get("type", "")).strip()
        if msg_type not in ("reminder_1", "reminder_3", "expired"):
            return ""

        identity = str(message.get("reference_id", "")).strip() or normalize_mobile(str(message.get("mobile", "")))
        if not identity:
            return ""

        cycle_key = ""
        dedup_key = str(message.get("dedup_key", "")).strip()
        parts = dedup_key.split(":", 2)
        if len(parts) == 3 and parts[0] == msg_type:
            cycle_key = str(parts[2]).strip()

        if not cycle_key:
            mobile = normalize_mobile(str(message.get("mobile", "")))
            member = self.find_member_by_mobile(mobile) if mobile else None
            if member is not None:
                cycle_key = str(member.get("last_subscription_end", "")).strip()

        if not cycle_key:
            return ""
        return f"{msg_type}:{identity}:{cycle_key}"

    def _remember_sent_whatsapp_message(self, message: Dict[str, Any], save: bool = True) -> bool:
        history = getattr(self, "whatsapp_sent_history", {})
        if not isinstance(history, dict):
            self.whatsapp_sent_history = {}
            history = self.whatsapp_sent_history
        key = self._history_key_from_message(message)
        if not key:
            return False
        sent_at = str(message.get("sent_at", "")).strip() or now_str()
        if str(history.get(key, "")).strip() == sent_at:
            return False
        history[key] = sent_at
        if save:
            self.save_whatsapp_sent_history()
        return True

    def _google_auth_fingerprint(self) -> str:
        credentials_path, token_path = resolve_google_contact_paths()
        hasher = hashlib.sha256()
        for label, path in (("credentials", credentials_path), ("token", token_path)):
            hasher.update(label.encode("utf-8"))
            hasher.update(str(path).encode("utf-8"))
            if not path.exists():
                hasher.update(b"missing")
                continue
            try:
                hasher.update(path.read_bytes())
            except Exception:
                hasher.update(b"read_error")
        return hasher.hexdigest()

    def _reset_google_sync_state_if_auth_changed(self) -> None:
        current_fingerprint = self._google_auth_fingerprint()
        settings = getattr(self, "settings", None)
        if not isinstance(settings, dict):
            return
        previous_fingerprint = str(settings.get("google_auth_fingerprint", "")).strip()

        auth_changed = bool(previous_fingerprint) and previous_fingerprint != current_fingerprint
        if auth_changed:
            self._set_google_synced_numbers(set())
            self.save_google_contacts_synced_numbers()

            members_changed = False
            for member in getattr(self, "members", []):
                if str(member.get("google_contact_synced_at", "")).strip():
                    member["google_contact_synced_at"] = ""
                    members_changed = True
            if members_changed:
                self.save_members()

        if previous_fingerprint != current_fingerprint:
            settings["google_auth_fingerprint"] = current_fingerprint
            self.save_settings()

    def _get_google_synced_numbers(self) -> set[str]:
        raw = getattr(self, "google_contacts_synced_numbers", [])
        values = raw if isinstance(raw, list) else list(raw)
        cleaned = {normalize_mobile(str(v)) for v in values if normalize_mobile(str(v))}
        self.google_contacts_synced_numbers = sorted(cleaned)
        return cleaned

    def _set_google_synced_numbers(self, numbers: set[str]) -> None:
        self.google_contacts_synced_numbers = sorted({normalize_mobile(str(v)) for v in numbers if normalize_mobile(str(v))})

    def save_google_contacts_synced_numbers(self) -> None:
        file_path = getattr(self, "google_contacts_synced_numbers_file", None)
        if file_path is None:
            return
        write_json(file_path, getattr(self, "google_contacts_synced_numbers", []))

    def save_google_contacts_queue(self) -> None:
        file_path = getattr(self, "google_contacts_queue_file", None)
        if file_path is None:
            return
        write_json(file_path, getattr(self, "google_contacts_queue", []))

    def queue_google_contact(self, member: Dict[str, Any], force: bool = False, save: bool = True) -> None:
        name = str(member.get("name", "") or "").strip()
        mobile = normalize_mobile(str(member.get("mobile", "") or ""))
        if not name or not mobile:
            return
        if not force and mobile in self._get_google_synced_numbers():
            return
        key = f"{name}|{mobile}"
        if any(str(item.get("key", "")) == key for item in getattr(self, "google_contacts_queue", [])):
            return
        self.google_contacts_queue.append({
            "key": key,
            "name": name,
            "mobile": mobile,
            "created_at": now_str(),
            "attempts": 0,
        })
        if save:
            self.save_google_contacts_queue()

    def flush_google_contacts_queue(
        self,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
        total_override: Optional[int] = None,
    ) -> int:
        self._reset_google_sync_state_if_auth_changed()
        queue = getattr(self, "google_contacts_queue", [])
        if not queue:
            if progress_callback is not None:
                total = max(0, int(total_override or 0))
                progress_callback(total, 0, total)
            self.last_google_sync_quota_hit = False
            return 0

        # Build Google Contacts service ONCE for the entire batch if available
        service, _ = get_google_contacts_service()

        remaining: List[Dict[str, Any]] = []
        synced_count = 0
        members_changed = False
        synced_numbers = self._get_google_synced_numbers()
        synced_numbers_changed = False
        processed_count = 0
        total_count = max(int(total_override or 0), len(queue))
        quota_hit = False

        for idx, entry in enumerate(queue):
            name = str(entry.get("name", "") or "").strip()
            mobile = normalize_mobile(str(entry.get("mobile", "") or ""))
            if not name or not mobile:
                processed_count += 1
                if progress_callback is not None:
                    progress_callback(processed_count, synced_count, total_count)
                continue

            # Polite pacing delay between writes to avoid burst quota errors
            if idx > 0:
                time.sleep(0.12)

            ok = False
            err = ""
            try:
                if service is not None:
                    ok, err = sync_member_to_google_contacts({"name": name, "mobile": mobile}, service=service)
                else:
                    ok, err = sync_member_to_google_contacts({"name": name, "mobile": mobile})
            except TypeError:
                ok, err = sync_member_to_google_contacts({"name": name, "mobile": mobile})
            except Exception as exc:
                ok, err = False, str(exc)

            if ok:
                synced_count += 1
                synced_at = now_str()
                if mobile not in synced_numbers:
                    synced_numbers.add(mobile)
                    synced_numbers_changed = True
                for member in getattr(self, "members", []):
                    if normalize_mobile(str(member.get("mobile", ""))) == mobile:
                        member["google_contact_synced_at"] = synced_at
                        members_changed = True
            else:
                new_entry = dict(entry)
                new_entry["attempts"] = int(entry.get("attempts", 0) or 0) + 1
                remaining.append(new_entry)
                err_lower = str(err).lower()
                if "429" in err_lower or "resource_exhausted" in err_lower or "quota" in err_lower or "ratelimit" in err_lower:
                    quota_hit = True
                    for unattempted in queue[idx + 1:]:
                        remaining.append(dict(unattempted))
                    processed_count += 1
                    if progress_callback is not None:
                        progress_callback(processed_count, synced_count, total_count)
                    break

            processed_count += 1
            if progress_callback is not None:
                progress_callback(processed_count, synced_count, total_count)

        self.google_contacts_queue = remaining
        self.save_google_contacts_queue()
        if synced_numbers_changed:
            self._set_google_synced_numbers(synced_numbers)
            self.save_google_contacts_synced_numbers()
        if members_changed:
            self.save_members()
        self.last_google_sync_quota_hit = quota_hit
        return synced_count

    def sync_all_google_contacts(
        self,
        force: bool = False,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
        total_for_progress: Optional[int] = None,
    ) -> tuple[int, int]:
        total_members = len(getattr(self, "members", []))
        if force:
            # Force sync: reset previous sync state so all members get re-synced cleanly
            self._set_google_synced_numbers(set())
            self.save_google_contacts_synced_numbers()
            self.google_contacts_queue = []
            for member in getattr(self, "members", []):
                member["google_contact_synced_at"] = ""
            self.save_members()

        queued_before = len(getattr(self, "google_contacts_queue", []))
        no_phone_count = 0
        duplicate_count = 0
        already_synced_count = 0
        existing_keys = {str(item.get("key", "")) for item in getattr(self, "google_contacts_queue", [])}
        existing_mobiles = {normalize_mobile(str(item.get("mobile", ""))) for item in getattr(self, "google_contacts_queue", [])}
        synced_numbers = self._get_google_synced_numbers()

        for member in getattr(self, "members", []):
            name = str(member.get("name", "") or "").strip()
            mobile = normalize_mobile(str(member.get("mobile", "") or ""))
            if not name or not mobile:
                no_phone_count += 1
                continue
            if not force and mobile in synced_numbers:
                already_synced_count += 1
                continue
            key = f"{name}|{mobile}"
            if key in existing_keys or mobile in existing_mobiles:
                duplicate_count += 1
                continue
            existing_keys.add(key)
            existing_mobiles.add(mobile)
            self.google_contacts_queue.append({
                "key": key,
                "name": name,
                "mobile": mobile,
                "created_at": now_str(),
                "attempts": 0,
            })

        self.save_google_contacts_queue()
        queued_added = len(self.google_contacts_queue) - queued_before
        total_to_process = len(self.google_contacts_queue)
        synced_count = self.flush_google_contacts_queue(
            progress_callback=progress_callback,
            total_override=total_to_process,
        )

        self.last_google_sync_stats = {
            "total_members": total_members,
            "queued_added": queued_added,
            "synced_count": synced_count,
            "no_phone_count": no_phone_count,
            "duplicate_count": duplicate_count,
            "already_synced_count": already_synced_count,
            "quota_hit": getattr(self, "last_google_sync_quota_hit", False),
            "remaining_in_queue": len(getattr(self, "google_contacts_queue", [])),
        }
        return queued_added, synced_count

    def migrate_settings(self) -> None:
        changed = False
        defaults = default_settings()
        if "dashboard_password" not in self.settings:
            self.settings["dashboard_password"] = "1234"
            changed = True
        if "manager_mobile" not in self.settings:
            self.settings["manager_mobile"] = ""
            changed = True
        report_time = normalize_clock_time(str(self.settings.get("daily_report_time", defaults["daily_report_time"])))
        if not report_time:
            report_time = defaults["daily_report_time"]
            changed = True
        if report_time != self.settings.get("daily_report_time"):
            self.settings["daily_report_time"] = report_time
            changed = True

        methods = [str(m).strip() for m in self.settings.get("payment_methods", []) if str(m).strip()]
        methods = ["بطاقة بنكية" if m == "مدى" else m for m in methods]
        if not methods:
            methods = defaults["payment_methods"][:]
            changed = True
        if methods != self.settings.get("payment_methods"):
            self.settings["payment_methods"] = methods
            changed = True

        if "expense_categories" not in self.settings:
            self.settings["expense_categories"] = defaults["expense_categories"][:]
            changed = True
        else:
            self.settings["expense_categories"] = [str(c).strip() for c in self.settings.get("expense_categories", []) if str(c).strip()]
            if not self.settings["expense_categories"]:
                self.settings["expense_categories"] = defaults["expense_categories"][:]
                changed = True

        if "expired_message_template" not in self.settings:
            self.settings["expired_message_template"] = defaults["expired_message_template"]
            changed = True
        if "whatsapp_send_mode" not in self.settings:
            self.settings["whatsapp_send_mode"] = defaults["whatsapp_send_mode"]
            changed = True
        if "whatsapp_letter_delay" not in self.settings:
            self.settings["whatsapp_letter_delay"] = defaults["whatsapp_letter_delay"]
            changed = True

        whatsapp_mode = str(self.settings.get("whatsapp_send_mode", defaults["whatsapp_send_mode"])).strip().lower()
        if whatsapp_mode not in {"typing", "paste"}:
            self.settings["whatsapp_send_mode"] = defaults["whatsapp_send_mode"]
            changed = True
        try:
            delay_value = float(self.settings.get("whatsapp_letter_delay", defaults["whatsapp_letter_delay"]) or defaults["whatsapp_letter_delay"])
            self.settings["whatsapp_letter_delay"] = max(0.0, min(0.5, delay_value))
        except Exception:
            self.settings["whatsapp_letter_delay"] = defaults["whatsapp_letter_delay"]
            changed = True

        plans = self.settings.get("plans")
        requested_names = {p["name"] for p in defaults["plans"]}
        existing_names = {str(p.get("name", "")) for p in plans or []}
        if not plans or len(requested_names.intersection(existing_names)) < 3:
            self.settings["plans"] = defaults["plans"][:]
            changed = True
        else:
            for p in self.settings.get("plans", []):
                name = str(p.get("name", ""))
                if "frequency" not in p:
                    p["frequency"] = "يوم ويوم" if "يوم ويوم" in name else "كل يوم"
                    changed = True
                if "months" not in p:
                    days = int(float(p.get("duration_days", 30) or 30))
                    p["months"] = 12 if days >= 360 else 3 if days >= 80 else 1
                    changed = True

        payments_changed = False
        for payment in self.payments:
            if str(payment.get("payment_method", "")).strip() == "مدى":
                payment["payment_method"] = "بطاقة بنكية"
                payments_changed = True
            if "operation_type" not in payment:
                payment["operation_type"] = "new_subscription"
                payments_changed = True
        if payments_changed:
            self.save_payments()
        if changed:
            self.save_settings()

    def rollover_whatsapp_messages_if_needed(self) -> None:
        settings = getattr(self, "settings", {})
        if not isinstance(settings, dict):
            return
        current_month = date.today().strftime("%Y-%m")
        last_rollover = str(settings.get("last_whatsapp_rollover", ""))
        if last_rollover == current_month:
            return

        if self.whatsapp_messages:
            backup_name = f"whatsapp_messages_backup_{last_rollover or 'init'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            backup_path = DATA_DIR / backup_name
            try:
                shutil.copy2(self.whatsapp_path, backup_path)
            except Exception:
                pass

        # Protect all non-reminder messages: receipts, renewals, invoices, expired/ended, and open messages.
        # Only remove old sent reminders from previous months.
        self.whatsapp_messages = [
            m for m in self.whatsapp_messages
            if is_receipt_protected_whatsapp_message(m) or str(m.get("status", "")) in ("pending", "scheduled")
        ]
        self.save_whatsapp()
        settings["last_whatsapp_rollover"] = current_month
        self.save_settings()

    def save_members(self, push_to_esp: bool = True) -> None:
        write_json(self.members_path, self.members)
        self.save_member_permissions()
        if push_to_esp and esp_client.is_enabled(self.settings):
            payload = self.esp_members_payload()
            threading.Thread(target=self._push_members_to_esp, args=(payload,), daemon=True).start()

    def delete_member(self, member_id: str) -> None:
        """Delete a member by ID."""
        member = next((m for m in self.members if m.get("member_id") == member_id), None)
        if member is None:
            return
        fingerprint_id = member.get("fingerprint_id")
        if fingerprint_id not in (None, ""):
            if not esp_client.is_enabled(self.settings):
                raise ValueError("لا يمكن حذف العضو قبل تفعيل الاتصال بجهاز ESP وحذف بصمته.")
            result = esp_client.delete_fingerprint(self.settings, fingerprint_id)
            if result.get("success") is not True:
                error = result.get("error", result.get("error_detail", "فشل حذف البصمة من جهاز ESP"))
                raise ValueError(f"لم يتم حذف العضو لأن جهاز ESP لم يؤكد حذف البصمة: {error}")
        self.members = [m for m in self.members if m.get("member_id") != member_id]
        self.save_members()

    def save_payments(self) -> None:
        write_json(self.payments_path, self.payments)

    def save_expenses(self) -> None:
        write_json(self.expenses_path, self.expenses)

    def save_whatsapp(self) -> None:
        write_json(self.whatsapp_path, self.whatsapp_messages)

    def save_whatsapp_message_bank(self, bank: Dict[str, List[str]]) -> bool:
        """Save the WhatsApp message bank to JSON file."""
        return save_whatsapp_message_bank(bank)

    def delete_whatsapp_messages(self, message_ids: List[str]) -> int:
        protected_ids = {
            str(m.get("message_id", ""))
            for m in self.whatsapp_messages
            if is_receipt_protected_whatsapp_message(m)
        }
        removable_ids = [msg_id for msg_id in message_ids if str(msg_id) not in protected_ids]
        cleaned = [m for m in self.whatsapp_messages if str(m.get("message_id", "")) not in set(removable_ids)]
        deleted_count = len(self.whatsapp_messages) - len(cleaned)
        if deleted_count:
            self.whatsapp_messages = cleaned
            self.save_whatsapp()
        return deleted_count

    def clear_whatsapp_messages(self) -> int:
        count = len(self.whatsapp_messages)
        if count:
            self.whatsapp_messages = []
            self.save_whatsapp()
        return count

    def remove_member_pending_reminders(self, member_id: str, mobile: str) -> int:
        mobile = normalize_mobile(mobile)
        keep: List[Dict[str, Any]] = []
        removed = 0
        for msg in self.whatsapp_messages:
            if str(msg.get("status", "")) in ("pending", "scheduled", "failed") and str(msg.get("mobile", "")) == mobile and str(msg.get("type", "")) in ("reminder_1", "reminder_3", "expired"):
                removed += 1
                continue
            keep.append(msg)
        if removed:
            self.whatsapp_messages = keep
            self.save_whatsapp()
        return removed

    def _member_is_single_session(self, member: Dict[str, Any]) -> bool:
        plan_name = str(member.get("last_subscription_type", "")).strip()
        if plan_name == "جلسة واحدة":
            return True
        plan = self.plan_by_name(plan_name)
        frequency = str(plan.get("frequency", "")).strip()
        return frequency == "جلسة واحدة"

    def _member_recently_paid(self, member: Dict[str, Any], within_days: int = 2) -> bool:
        today = date.today()
        member_id = str(member.get("member_id", "")).strip()
        mobile = normalize_mobile(str(member.get("mobile", "")))
        for payment in reversed(self.payments):
            payment_member_id = str(payment.get("member_id", "")).strip()
            payment_mobile = normalize_mobile(str(payment.get("mobile", "")))
            if member_id and payment_member_id == member_id:
                pass
            elif mobile and payment_mobile == mobile:
                pass
            else:
                continue
            created_raw = str(payment.get("created_at", "")).strip()
            if not created_raw:
                continue
            try:
                paid_date = datetime.strptime(created_raw, DATETIME_FMT).date()
            except ValueError:
                continue
            delta_days = (today - paid_date).days
            if 0 <= delta_days <= max(0, int(within_days)):
                return True
        return False

    def _has_recent_expired_sent_message(self, member: Dict[str, Any], within_days: int = 3) -> bool:
        """Return True only if an expired message was actually sent recently."""
        today = date.today()
        member_id = str(member.get("member_id", "")).strip()
        mobile = normalize_mobile(str(member.get("mobile", "")))
        max_days = max(0, int(within_days))

        for msg in reversed(self.whatsapp_messages):
            if str(msg.get("type", "")) != "expired":
                continue
            if str(msg.get("status", "")) != "sent":
                continue

            msg_ref = str(msg.get("reference_id", "")).strip()
            msg_mobile = normalize_mobile(str(msg.get("mobile", "")))
            if not ((member_id and msg_ref == member_id) or (mobile and msg_mobile == mobile)):
                continue

            sent_raw = str(msg.get("sent_at", "")).strip() or str(msg.get("created_at", "")).strip()
            if not sent_raw:
                continue
            try:
                sent_date = datetime.strptime(sent_raw, DATETIME_FMT).date()
            except ValueError:
                continue

            delta_days = (today - sent_date).days
            if 0 <= delta_days <= max_days:
                return True
        return False

    def _has_open_expired_message(self, member: Dict[str, Any]) -> bool:
        """Return True if there is already a pending/scheduled/failed expired message."""
        member_id = str(member.get("member_id", "")).strip()
        mobile = normalize_mobile(str(member.get("mobile", "")))
        for msg in self.whatsapp_messages:
            if str(msg.get("type", "")) != "expired":
                continue
            if str(msg.get("status", "")) not in ("pending", "scheduled", "failed"):
                continue
            msg_ref = str(msg.get("reference_id", "")).strip()
            msg_mobile = normalize_mobile(str(msg.get("mobile", "")))
            if (member_id and msg_ref == member_id) or (mobile and msg_mobile == mobile):
                return True
        return False

    def _has_recent_member_message_for_cycle(
        self,
        member: Dict[str, Any],
        msg_type: str,
        cycle_key: str,
        within_days: int = 7,
    ) -> bool:
        """Block re-queue of same reminder/warning for the same member cycle."""
        member_id = str(member.get("member_id", "")).strip()
        mobile = normalize_mobile(str(member.get("mobile", "")))
        cycle_key = str(cycle_key).strip()
        max_days = max(0, int(within_days))
        today = date.today()

        for msg in reversed(self.whatsapp_messages):
            if str(msg.get("type", "")) != msg_type:
                continue

            status = str(msg.get("status", ""))
            if status not in ("pending", "scheduled", "failed", "sent"):
                continue

            msg_ref = str(msg.get("reference_id", "")).strip()
            msg_mobile = normalize_mobile(str(msg.get("mobile", "")))
            if not ((member_id and msg_ref == member_id) or (mobile and msg_mobile == mobile)):
                continue

            # Prefer cycle-level dedup by last subscription end when present.
            dedup_key = str(msg.get("dedup_key", "")).strip()
            dedup_parts = dedup_key.split(":", 2)
            if cycle_key and len(dedup_parts) == 3:
                if dedup_parts[0] == msg_type and dedup_parts[2] == cycle_key:
                    return True

            # Fallback for old/legacy dedup keys: recent same-type message should
            # still prevent immediate auto re-queue loops.
            when_raw = str(msg.get("sent_at", "")).strip() or str(msg.get("created_at", "")).strip()
            if not when_raw:
                continue
            try:
                when_date = datetime.strptime(when_raw, DATETIME_FMT).date()
            except ValueError:
                continue
            delta_days = (today - when_date).days
            if 0 <= delta_days <= max_days:
                return True
        return False

    def is_whatsapp_message_allowed(self, message: Dict[str, Any], refresh_statuses_first: bool = False) -> bool:
        recipient_type = str(message.get("recipient_type", "")).strip() or "member"
        msg_type = str(message.get("type", "")).strip()
        if recipient_type != "member":
            return True

        mobile = normalize_mobile(str(message.get("mobile", "")))
        if not mobile:
            return False

        if refresh_statuses_first:
            self.refresh_statuses(save=False)

        member = self.find_member_by_mobile(mobile)
        if member is None:
            return False

        if msg_type in ("reminder_1", "reminder_3"):
            end_raw = str(member.get("last_subscription_end", "")).strip()
            if not end_raw:
                return False
            end_date = parse_date(end_raw)
            days_left = (end_date - date.today()).days
            if str(member.get("current_status", "")) != "active":
                return False
            if msg_type == "reminder_1" and self._member_is_single_session(member):
                return False
            expected_type = "reminder_3" if days_left == 3 else ("reminder_1" if days_left == 1 else "")
            return msg_type == expected_type

        if msg_type == "expired":
            end_raw = str(member.get("last_subscription_end", "")).strip()
            if not end_raw:
                return False
            end_date = parse_date(end_raw)
            return str(member.get("current_status", "")) == "expired" and end_date < date.today()

        if str(member.get("current_status", "")) == "active":
            return True

        # Allow sending only for members who just paid recently.
        return self._member_recently_paid(member, within_days=2)

    def get_whatsapp_unsendable_reason(
        self,
        message: Dict[str, Any],
        manual: bool = False,
        refresh_statuses_first: bool = False,
    ) -> Optional[str]:
        """Return None if message can be sent, or an explicit Arabic explanation why it cannot be sent."""
        mobile = normalize_mobile(str(message.get("mobile", "")))
        if not mobile:
            return "رقم الهاتف غير مسجل أو غير صحيح (فارغ)"

        text = str(message.get("message", "")).strip()
        if not text:
            return "نص الرسالة فارغ"

        status = str(message.get("status", "")).strip().lower()
        if status == "sent":
            return "تم إرسالها بنجاح بالفعل سابقاً"

        # Check send delay (send_after) or scheduled status
        send_after = str(message.get("send_after", "")).strip()
        if not manual:
            if send_after:
                dt_after = None
                for fmt in (DATETIME_FMT, "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt_after = datetime.strptime(send_after, fmt)
                        break
                    except ValueError:
                        continue
                if dt_after is not None and datetime.now() < dt_after:
                    mins = max(1, int((dt_after - datetime.now()).total_seconds() / 60))
                    return f"مجدولة بتأخير انتظار مزامنة Google (متبقي {mins} دقيقة حتى {send_after})"
            if status == "scheduled":
                return f"مجدولة بتأخير انتظار مزامنة Google ({send_after or 'قيد الانتظار'})"

        recipient_type = str(message.get("recipient_type", "")).strip() or "member"
        msg_type = str(message.get("type", "")).strip().lower()

        if recipient_type == "member":
            if refresh_statuses_first:
                self.refresh_statuses(save=False)

            member = self.find_member_by_mobile(mobile)
            if member is None:
                ref_id = str(message.get("reference_id", "")).strip()
                if ref_id:
                    member = next((m for m in self.members if str(m.get("member_id", "")) == ref_id), None)
                if member is None:
                    return "العضو غير مسجل في قاعدة البيانات (قد يكون تم حذفه)"

            member_status = str(member.get("current_status", "expired"))

            if msg_type in ("reminder_1", "reminder_3"):
                end_raw = str(member.get("last_subscription_end", "")).strip()
                if not end_raw:
                    return "العضو ليس لديه تاريخ انتهاء اشتراك مسجل"
                end_date = parse_date(end_raw)
                days_left = (end_date - date.today()).days
                if member_status != "active":
                    return f"العضو غير نشط حالياً (حالته: {status_ar(member_status)})"
                if msg_type == "reminder_1" and self._member_is_single_session(member):
                    return "عضو حصة واحدة (لا تنطبق عليه تذكيرات الاشتراك)"
                expected_type = "reminder_3" if days_left == 3 else ("reminder_1" if days_left == 1 else "")
                if msg_type != expected_type:
                    return f"تاريخ الاشتراك تغير (المتبقي {days_left} يوم، لا يوافق موعد تذكير {3 if msg_type == 'reminder_3' else 1} أيام)"

            elif msg_type == "expired":
                end_raw = str(member.get("last_subscription_end", "")).strip()
                if not end_raw:
                    return "العضو ليس لديه تاريخ انتهاء اشتراك مسجل"
                end_date = parse_date(end_raw)
                if member_status != "expired" or end_date >= date.today():
                    return f"العضو ليس منتهي الاشتراك حالياً (حالته: {status_ar(member_status)})"

            elif not manual:
                if member_status != "active" and not self._member_recently_paid(member, within_days=2):
                    return f"العضو منتهي الاشتراك ({status_ar(member_status)}) ولم يسدد خلال آخر يومين"

        if status == "failed" and not manual:
            err = str(message.get("error", "")).strip()
            return f"فشل الإرسال في محاولة سابقة ({err or 'تعذر التسليم'})"

        return None

    def force_rebuild_due_reminders(self, save: bool = True) -> tuple[int, int]:
        self.refresh_statuses(save=True)
        removable_types = {"reminder_1", "reminder_3", "expired"}
        keep: List[Dict[str, Any]] = []
        removed = 0
        for message in self.whatsapp_messages:
            status = str(message.get("status", ""))
            msg_type = str(message.get("type", ""))
            if status in ("pending", "scheduled", "failed") and msg_type in removable_types:
                removed += 1
                continue
            keep.append(message)
        if removed:
            self.whatsapp_messages = keep

        added = self.queue_due_reminders(save=False)
        if save and (removed or added):
            self.save_whatsapp()
        return removed, added

    def purge_blocked_pending_whatsapp_messages(self, save: bool = True) -> int:
        keep: List[Dict[str, Any]] = []
        removed = 0
        self.refresh_statuses(save=False)
        for message in self.whatsapp_messages:
            # Receipts, renewals, invoices, expired/ended, and reports are protected and NEVER purged!
            if is_receipt_protected_whatsapp_message(message):
                keep.append(message)
                continue
            status = str(message.get("status", ""))
            if status in ("pending", "scheduled", "failed") and not self.is_whatsapp_message_allowed(message, refresh_statuses_first=False):
                removed += 1
                continue
            keep.append(message)
        if removed:
            self.whatsapp_messages = keep
            if save:
                self.save_whatsapp()
        return removed

    def purge_old_whatsapp_messages(self, retention_days: int = 7, save: bool = True) -> int:
        threshold = datetime.now() - timedelta(days=max(0, int(retention_days)))
        keep: List[Dict[str, Any]] = []
        removed = 0
        self.refresh_statuses(save=False)

        def parse_created(raw_value: str) -> Optional[datetime]:
            raw_value = str(raw_value).strip()
            if not raw_value:
                return None
            try:
                return datetime.strptime(raw_value, DATETIME_FMT)
            except ValueError:
                return None

        for message in self.whatsapp_messages:
            # Receipts, renewals, invoices, sub ended (expired), and reports are protected and NEVER purged!
            if is_receipt_protected_whatsapp_message(message):
                keep.append(message)
                continue

            msg_type = str(message.get("type", "")).strip().lower()
            status = str(message.get("status", ""))
            created_at = parse_created(str(message.get("created_at", "")))
            recipient_type = str(message.get("recipient_type", "") or "member").strip()
            mobile = normalize_mobile(str(message.get("mobile", "")))

            # Only purge stale reminders for members who renewed / became active
            if recipient_type == "member" and mobile:
                member = self.find_member_by_mobile(mobile)
                if (
                    member is not None
                    and str(member.get("current_status", "")) == "active"
                    and msg_type in ("reminder_1", "reminder_3")
                    and status in ("pending", "scheduled", "failed")
                ):
                    removed += 1
                    continue

            if created_at is None:
                keep.append(message)
                continue

            is_older_than_retention = created_at < threshold
            if is_older_than_retention and msg_type in ("reminder_1", "reminder_3"):
                removed += 1
                continue

            keep.append(message)

        if removed:
            self.whatsapp_messages = keep
            if save:
                self.save_whatsapp()
        return removed

    def save_settings(self) -> None:
        file_path = getattr(self, "settings_path", None)
        if file_path is None:
            return
        write_json(file_path, getattr(self, "settings", {}))

    def save_member_permissions(self) -> None:
        """Generate and save member_permission.json file for ESP device.
        File contains: last_update timestamp and member access permissions (True/False based on current_status).
        """
        permissions_data = {
            "last_update": now_str(),
            "members": {}
        }
        
        for member in self.members:
            member_id = str(member.get("member_id", ""))
            if not member_id:
                continue
            
            # Member can enter if they have active subscription
            can_enter = str(member.get("current_status", "")) == "active"
            permissions_data["members"][member_id] = can_enter
        
        permissions_path = DATA_DIR / "member_permission.json"
        write_json(permissions_path, permissions_data)
        return permissions_path

    def esp_members_payload(self) -> Dict[str, Any]:
        """Build the minimal {member_id: {fingerprint_id, allowed}} payload for POST /members.

        Only enrolled members (fingerprint_id set) are included - a member with no
        fingerprint can't match on the ESP anyway. No names/mobiles/payment data ever go here.
        """
        payload: Dict[str, Any] = {}
        for member in self.members:
            member_id = str(member.get("member_id", ""))
            fingerprint_id = member.get("fingerprint_id")
            if not member_id or fingerprint_id in (None, ""):
                continue
            try:
                fingerprint_id = int(fingerprint_id)
            except (TypeError, ValueError):
                continue
            payload[member_id] = {
                "fingerprint_id": fingerprint_id,
                "allowed": str(member.get("current_status", "")) == "active",
            }
        return payload

    def sync_members_to_esp(self) -> Dict[str, Any]:
        """Push the complete current minimal authorization database to the ESP."""
        if not esp_client.is_enabled(self.settings):
            return {"success": False, "error": "ESP غير مفعل في الإعدادات"}
        if not ESP_SYNC_LOCK.acquire(blocking=False):
            return {"success": False, "error": "sync_in_progress"}
        try:
            return esp_client.push_members(self.settings, self.esp_members_payload())
        finally:
            ESP_SYNC_LOCK.release()

    def _push_members_to_esp(self, members_payload: Dict[str, Any]) -> None:
        if not self.esp_command_allowed():
            print("[ESP] SYNC SKIPPED: ESP is not connected")
            return
        if not ESP_SYNC_LOCK.acquire(blocking=False):
            print("[ESP] SYNC SKIPPED: another synchronization is in progress")
            return
        try:
            print(f"[ESP] Syncing {len(members_payload)} members...")
            result = esp_client.push_members(self.settings, members_payload)
            if result.get("success"):
                print(f"[ESP] Sync successful: {result.get('members', len(members_payload))} members")
            else:
                print(f"[ESP] SYNC FAILED: {result}")
        finally:
            ESP_SYNC_LOCK.release()

    def add_expense(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        amount = float(payload.get("amount", 0) or 0)
        expense_date = parse_date(str(payload.get("date", date.today())))
        notes = str(payload.get("notes", "")).strip()

        if not name:
            raise ValueError("اكتب وصفًا للمصروف.")
        if amount <= 0:
            raise ValueError("اكتب مبلغ مصروف صحيح أكبر من صفر.")

        expense = {
            "expense_id": self.next_id("EXP", self.expenses, "expense_id"),
            "name": name,
            "amount": amount,
            "date": date_to_str(expense_date),
            "notes": notes,
            "created_at": now_str(),
        }
        self.expenses.append(expense)
        self.save_expenses()
        return expense

    def next_id(self, prefix: str, items: List[Dict[str, Any]], key: str) -> str:
        highest = 0
        for item in items:
            raw = str(item.get(key, ""))
            m = re.search(r"(\d+)$", raw)
            if m:
                highest = max(highest, int(m.group(1)))
        return f"{prefix}-{highest + 1:05d}"

    def find_member_by_mobile(self, mobile: str) -> Optional[Dict[str, Any]]:
        n = normalize_mobile(mobile)
        for member in self.members:
            if normalize_mobile(str(member.get("mobile", ""))) == n:
                return member
        return None

    def find_member_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        query = str(name).strip().lower()
        if not query:
            return None
        for member in self.members:
            if str(member.get("name", "")).strip().lower() == query:
                return member
        return None

    def plan_by_name(self, name: str) -> Dict[str, Any]:
        for p in self.settings.get("plans", []):
            if p.get("name") == name:
                return p
        plans = self.settings.get("plans", [])
        return plans[0] if plans else {"name": "اشتراك", "price": 0, "duration_days": 0, "months": 0}

    def _is_monthly_plan(self, plan_name: str, plan: Dict[str, Any]) -> bool:
        name = str(plan_name or "").strip().lower()
        months = int(float(plan.get("months", 0) or 0))
        return months > 0 or "شهري" in name or "monthly" in name

    def _month_end(self, start: date, months: int = 1) -> date:
        target_months = max(int(months or 1), 1)
        return add_months(start, target_months) - timedelta(days=1)

    def _effective_months(self, plan: Dict[str, Any], plan_name: str) -> int:
        months = int(float(plan.get("months", 0) or 0))
        if months > 0:
            return months
        name = str(plan_name or "").strip().lower()
        if "شهري" in name or "monthly" in name:
            return 1
        return 0

    def calculate_end(self, start: date, plan_name: str, paid_amount: float, days_override: int = 0) -> tuple[str, float, float, int]:
        plan = self.plan_by_name(plan_name)
        price = float(plan.get("price", 0) or 0)
        duration = int(float(plan.get("duration_days", 0) or 0))
        frequency = str(plan.get("frequency", ""))
        months = self._effective_months(plan, plan_name)
        paid = float(paid_amount or 0)
        remaining = max(price - paid, 0)
        is_monthly_plan = self._is_monthly_plan(plan_name, plan)
        if days_override > 0:
            days = days_override
            end = start + timedelta(days=days_override)
        elif str(plan_name).strip() == "جلسة واحدة" or str(plan.get("frequency", "")).strip() == "جلسة واحدة":
            days = 1
            end = start
        elif price <= 0 or duration <= 0 or paid <= 0:
            days = 0
            end = start - timedelta(days=1)
        elif paid >= price:
            if is_monthly_plan:
                end = self._month_end(start, max(months, 1))
                days = (end - start).days
            elif frequency == "يوم ويوم":
                days = duration * 2
                end = start + timedelta(days=days)
            else:
                days = duration
                end = start + timedelta(days=days)
        else:
            days = 0
            end = start - timedelta(days=1)
        return date_to_str(end), price, remaining, days

    def can_member_attend(self, member: Dict[str, Any], check_date: date) -> tuple[bool, str]:
        if not member:
            return False, "لا يوجد عضو"

        plan_name = str(member.get("last_subscription_type", "")).strip()
        if not plan_name:
            return False, "لا يوجد اشتراك مسجل"

        start_date = parse_date(str(member.get("last_subscription_start", ""))) if str(member.get("last_subscription_start", "")).strip() else check_date
        end_date = parse_date(str(member.get("last_subscription_end", ""))) if str(member.get("last_subscription_end", "")).strip() else check_date
        if check_date < start_date:
            return False, "تاريخ الدخول قبل بداية الاشتراك"
        if check_date > end_date:
            return False, "انتهى الاشتراك"

        plan = self.plan_by_name(plan_name)
        frequency = str(plan.get("frequency", "")).strip()
        if frequency == "يوم ويوم":
            delta = (check_date - start_date).days
            allowed = delta >= 0 and delta % 2 == 0
            return (allowed, "مسموح للدخول اليوم" if allowed else "غير مسموح بالدخول اليوم حسب خطة يوم ويوم")
        return True, "مسموح للدخول اليوم"

    def suggested_renewal_start(self, member: Dict[str, Any]) -> date:
        last_end = parse_date(str(member.get("last_subscription_end", "")))
        today = date.today()
        if last_end >= today:
            # If only 1-2 days remain, allow early renewal to start immediately.
            if (last_end - today).days <= 2:
                return today
            return last_end + timedelta(days=1)
        return today

    def members_with_remaining(self) -> List[Dict[str, Any]]:
        return [m for m in self.members if float(m.get("current_remaining", 0) or 0) > 0]

    def reminder_members(self) -> List[Dict[str, Any]]:
        today = date.today()
        members = []
        for member in self.members:
            if not member.get("last_subscription_end") or not member.get("mobile"):
                continue
            end = parse_date(str(member.get("last_subscription_end", "")))
            days_left = (end - today).days
            if member.get("current_status") == "active" and 0 <= days_left <= 3:
                members.append(member)
        return members

    def calculate_remaining_extension(self, member: Dict[str, Any], paid_amount: float, days_override: int = 0) -> tuple[str, float, float, int]:
        paid = float(paid_amount or 0)
        remaining_before = float(member.get("current_remaining", 0) or 0)
        if remaining_before <= 0:
            raise ValueError("المشترك ده مفيش عليه متبقي.")
        if paid <= 0:
            raise ValueError("اكتب مبلغ مدفوع صحيح.")
        if paid > remaining_before:
            raise ValueError("المبلغ أكبر من المتبقي على المشترك.")

        plan = self.plan_by_name(str(member.get("last_subscription_type", "")))
        price = float(plan.get("price", 0) or 0)
        duration = int(float(plan.get("duration_days", 0) or 0))
        months = self._effective_months(plan, str(member.get("last_subscription_type", "")))
        start = parse_date(str(member.get("last_subscription_start", "")))
        current_end = parse_date(str(member.get("last_subscription_end", "")))
        remaining_after = max(remaining_before - paid, 0)

        if remaining_after <= 0:
            if price <= 0 or duration <= 0:
                new_end = current_end
            else:
                if months > 0:
                    full_end = self._month_end(start, months)
                else:
                    frequency = str(plan.get("frequency", ""))
                    effective_duration = duration * 2 if frequency == "يوم ويوم" else duration
                    full_end = start + timedelta(days=effective_duration)
                new_end = max(full_end, current_end)
            days_added = max(0, (new_end - current_end).days)
        else:
            if days_override <= 0:
                raise ValueError("اكتب عدد أيام تمديد صحيح عند دفع جزئي.")
            new_end = current_end + timedelta(days=days_override)
            days_added = days_override

        return date_to_str(new_end), remaining_before, remaining_after, days_added

    def pay_remaining(self, member_id: str, paid_amount: float, payment_method: str, days: int = 0) -> Dict[str, Any]:
        member = next((m for m in self.members if m.get("member_id") == member_id), None)
        if member is None:
            raise ValueError("اختار مشترك صحيح.")
        new_end, remaining_before, remaining_after, days_added = self.calculate_remaining_extension(member, paid_amount, days)

        payment = {
            "payment_id": self.next_id("PAY", self.payments, "payment_id"),
            "invoice_no": self.next_id("INV", self.payments, "invoice_no"),
            "operation_type": "remaining_payment",
            "member_id": member["member_id"],
            "name": member.get("name", ""),
            "mobile": member.get("mobile", ""),
            "gender": member.get("gender", "male"),
            "subscription_start": member.get("last_subscription_start", ""),
            "subscription_type": member.get("last_subscription_type", ""),
            "plan_price": float(member.get("current_paid", 0) or 0) + remaining_before,
            "paid_amount": float(paid_amount or 0),
            "remaining_amount": remaining_after,
            "subscription_end": new_end,
            "payment_method": payment_method,
            "status": "paid" if remaining_after <= 0 else "partial",
            "created_at": now_str(),
            "days_added": days_added,
        }
        self.payments.append(payment)

        self.remove_member_pending_reminders(member["member_id"], member.get("mobile", ""))

        member["last_subscription_end"] = new_end
        member["last_payment_date"] = payment["created_at"]
        member["current_paid"] = float(member.get("current_paid", 0) or 0) + float(paid_amount or 0)
        member["current_remaining"] = remaining_after
        member["total_paid"] = float(member.get("total_paid", 0) or 0) + float(paid_amount or 0)
        member["current_status"] = status_en_from_dates(new_end)
        member.setdefault("subscriptions_history", []).append(
            {
                "payment_id": payment["payment_id"],
                "invoice_no": payment["invoice_no"],
                "operation_type": "remaining_payment",
                "subscription_start": payment["subscription_start"],
                "subscription_end": payment["subscription_end"],
                "subscription_type": payment["subscription_type"],
                "plan_price": payment["plan_price"],
                "paid_amount": payment["paid_amount"],
                "remaining_amount": payment["remaining_amount"],
                "payment_method": payment["payment_method"],
                "created_at": payment["created_at"],
                "days_added": days_added,
            }
        )

        queued_receipt = self.queue_receipt(payment, save=False)
        self.last_queued_receipt_message_id = str(queued_receipt.get("message_id", "")) if queued_receipt else ""
        self.refresh_statuses(save=False)
        self.save_payments()
        self.save_members()
        self.save_whatsapp()
        return payment

    def add_lead(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        mobile = normalize_mobile(str(payload.get("mobile", "")).strip())
        gender = str(payload.get("gender", "male"))
        follow_up_date = str(payload.get("follow_up_date", "")).strip()
        notes = str(payload.get("notes", "")).strip()

        if not name:
            raise ValueError("اكتب اسم الشخص.")
        if not mobile:
            raise ValueError("اكتب رقم الموبايل.")
        if self.find_member_by_mobile(mobile) is not None:
            raise ValueError("رقم الموبايل ده مسجل بالفعل في الأعضاء.")

        member = {
            "member_id": self.next_id("MEM", self.members, "member_id"),
            "member_type": "lead",
            "name": name,
            "mobile": mobile,
            "gender": gender,
            "current_status": "expired",
            "last_subscription_start": "",
            "last_subscription_end": "",
            "last_subscription_type": "",
            "last_payment_date": "",
            "current_paid": 0,
            "current_remaining": 0,
            "total_paid": 0,
            "follow_up_date": follow_up_date,
            "notes": notes,
            "created_at": now_str(),
            "subscriptions_history": [],
        }
        self.members.append(member)
        self.save_members()
        return member

    def add_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        operation_type = str(payload.get("operation_type", "new_subscription"))
        name = str(payload["name"]).strip()
        mobile = normalize_mobile(str(payload["mobile"]).strip())
        gender = str(payload["gender"])
        subscription_type = str(payload["subscription_type"])
        start_date = parse_date(str(payload["subscription_start"]))
        paid_amount = float(payload["paid_amount"])
        payment_method = str(payload["payment_method"])

        member = self.find_member_by_mobile(mobile)
        if operation_type == "renewal" and member is None:
            raise ValueError("المشترك غير موجود. استخدم اشتراك جديد لو ده أول تسجيل له.")
        if operation_type == "renewal" and float(member.get("current_remaining", 0) or 0) > 0:
            raise ValueError("لا يمكن تجديد الاشتراك قبل دفع المتبقي. استخدم زر دفع المتبقي الأول.")

        days_override = int(payload.get("allowance_days", 0) or 0)
        subscription_end, plan_price, remaining, _days = self.calculate_end(start_date, subscription_type, paid_amount, days_override)
        payment_status = "paid" if remaining <= 0 else "partial"

        if operation_type == "new_subscription":
            member = {
                "member_id": self.next_id("MEM", self.members, "member_id"),
                "member_type": "member",
                "name": name,
                "mobile": mobile,
                "gender": gender,
                "current_status": "expired",
                "last_subscription_start": "",
                "last_subscription_end": "",
                "last_subscription_type": "",
                "last_payment_date": "",
                "current_paid": 0,
                "current_remaining": 0,
                "total_paid": 0,
                "follow_up_date": "",
                "notes": "",
                "subscriptions_history": [],
                "fingerprint_id": "",
            }
            self.members.append(member)
        elif member is None:
            member = {
                "member_id": self.next_id("MEM", self.members, "member_id"),
                "member_type": "member",
                "name": name,
                "mobile": mobile,
                "gender": gender,
                "current_status": "expired",
                "last_subscription_start": "",
                "last_subscription_end": "",
                "last_subscription_type": "",
                "last_payment_date": "",
                "current_paid": 0,
                "current_remaining": 0,
                "total_paid": 0,
                "follow_up_date": "",
                "notes": "",
                "subscriptions_history": [],
                "fingerprint_id": "",
            }
            self.members.append(member)
        else:
            member["name"] = name
            member["mobile"] = mobile
            member["gender"] = gender
            member["member_type"] = "member"

        payment = {
            "payment_id": self.next_id("PAY", self.payments, "payment_id"),
            "invoice_no": self.next_id("INV", self.payments, "invoice_no"),
            "operation_type": operation_type,
            "member_id": member["member_id"],
            "name": name,
            "mobile": mobile,
            "gender": gender,
            "subscription_start": date_to_str(start_date),
            "subscription_type": subscription_type,
            "plan_price": plan_price,
            "paid_amount": paid_amount,
            "remaining_amount": remaining,
            "subscription_end": subscription_end,
            "payment_method": payment_method,
            "status": payment_status,
            "created_at": now_str(),
        }
        self.payments.append(payment)

        self.remove_member_pending_reminders(member["member_id"], member.get("mobile", ""))

        member["last_subscription_start"] = payment["subscription_start"]
        member["last_subscription_end"] = payment["subscription_end"]
        member["last_subscription_type"] = payment["subscription_type"]
        member["last_payment_date"] = payment["created_at"]
        member["current_paid"] = paid_amount
        member["current_remaining"] = remaining
        member["total_paid"] = float(member.get("total_paid", 0) or 0) + paid_amount
        member["current_status"] = status_en_from_dates(subscription_end)
        member.setdefault("subscriptions_history", []).append(
            {
                "payment_id": payment["payment_id"],
                "invoice_no": payment["invoice_no"],
                "operation_type": operation_type,
                "subscription_start": payment["subscription_start"],
                "subscription_end": payment["subscription_end"],
                "subscription_type": payment["subscription_type"],
                "plan_price": plan_price,
                "paid_amount": paid_amount,
                "remaining_amount": remaining,
                "payment_method": payment_method,
                "created_at": payment["created_at"],
            }
        )

        queued_receipt = self.queue_receipt(payment, save=False)
        self.last_queued_receipt_message_id = str(queued_receipt.get("message_id", "")) if queued_receipt else ""
        self.refresh_statuses(save=False)
        self.save_payments()
        self.save_members()
        self.save_whatsapp()
        return payment

    def refresh_statuses(self, save: bool = True) -> None:
        changed = False
        for m in self.members:
            before = m.get("current_status")
            end = str(m.get("last_subscription_end", ""))
            m["current_status"] = status_en_from_dates(end) if end else "expired"
            changed = changed or (before != m.get("current_status"))
        if changed and save:
            self.save_members()

    def filtered_members(self, page_filter: str, gender_filter: str = "all", query: str = "") -> List[Dict[str, Any]]:
        self.refresh_statuses(save=True)
        rows = list(self.members)
        if page_filter == "active":
            rows = [m for m in rows if m.get("current_status") == "active"]
        elif page_filter == "expired":
            rows = [m for m in rows if m.get("current_status") == "expired"]
        elif page_filter == "reminder":
            rows = self.reminder_members()
        elif page_filter == "remaining":
            rows = [m for m in rows if float(m.get("current_remaining", 0) or 0) > 0]
        if gender_filter in ("male", "female"):
            rows = [m for m in rows if m.get("gender") == gender_filter]

        q = normalized_query(query)
        if q:
            compact_digits = normalize_mobile(q)
            rows = [
                m
                for m in rows
                if q in search_blob(m)
                or (compact_digits and compact_digits in normalize_mobile(str(m.get("mobile", ""))))
            ]
        return rows

    def filtered_payments(self, query: str = "") -> List[Dict[str, Any]]:
        rows = list(self.payments)
        q = normalized_query(query)
        if q:
            compact_digits = normalize_mobile(q)
            rows = [
                p
                for p in rows
                if q in search_blob(p)
                or (compact_digits and compact_digits in normalize_mobile(str(p.get("mobile", ""))))
            ]
        return rows

    def build_receipt_message(self, payment: Dict[str, Any]) -> str:
        return (
            "إيصال دفع من HULK GYM\n"
            f"رقم الإيصال: {payment.get('invoice_no', '-')}\n"
            f"الاسم: {payment.get('name', '-')}\n"
            f"نوع العملية: {operation_ar(str(payment.get('operation_type', 'new_subscription')))}\n"
            f"نوع الاشتراك: {payment.get('subscription_type', '-')}\n"
            f"المدفوع: {money(payment.get('paid_amount', 0))}\n"
            f"المتبقي: {money(payment.get('remaining_amount', 0))}\n"
            f"طريقة الدفع: {payment.get('payment_method', '-')}\n"
            f"بداية الاشتراك: {display_date(payment.get('subscription_start', ''))}\n"
            f"نهاية الاشتراك: {display_date(payment.get('subscription_end', ''))}\n"
            "شكراً لاشتراكك معانا 💪"
        )

    def build_reminder_message(self, member: Dict[str, Any], days_left: int) -> str:
        if days_left == 3:
            title = "تنبيه: باقي 3 أيام على انتهاء الاشتراك"
        elif days_left == 1:
            title = "تنبيه: باقي يوم واحد على انتهاء الاشتراك"
        else:
            title = "تنبيه قرب انتهاء الاشتراك"
        return (
            f"{title} من HULK GYM\n"
            f"أهلاً {member.get('name', '-')}\n"
            f"اشتراكك: {member.get('last_subscription_type', '-')}\n"
            f"ينتهي بتاريخ: {display_date(member.get('last_subscription_end', ''))}\n"
            "يرجى تجديد الاشتراك للاستمرار بدون توقف. 💪"
        )

    def build_expired_message(self, member: Dict[str, Any], template: Optional[str] = None) -> str:
        template = str(template or self.settings.get("expired_message_template", "")).strip()
        if not template: 
            template = (
                "تنبيه من HULK GYM\n"
                "أهلاً {name}\n"
                "اشتراكك انتهى بتاريخ: {end_date}\n"
                "نورتنا في أي وقت للتجديد والرجوع للتمرين 💪"
            )

        data = {
            "name": member.get("name", "-"),
            "mobile": member.get("mobile", "-"),
            "subscription_type": member.get("last_subscription_type", "-"),
            "end_date": display_date(member.get("last_subscription_end", "")),
            "last_subscription_end": display_date(member.get("last_subscription_end", "")),
        }
        try:
            return template.format(**data)
        except Exception:
            return (
                "تنبيه من HULK GYM\n"
                f"أهلاً {data['name']}\n"
                f"اشتراكك انتهى بتاريخ: {data['end_date']}\n"
                "نورتنا في أي وقت للتجديد والرجوع للتمرين 💪"
            )

    def build_daily_report_message(self) -> str:
        self.refresh_statuses(save=True)
        today = date.today()
        today_str = date_to_str(today)
        members = self.members
        #active = [m for m in members if m.get("current_status") == "active"]
        #expired = [m for m in members if m.get("current_status") == "expired"]
        #males = [m for m in members if m.get("gender") == "male"]
        #females = [m for m in members if m.get("gender") == "female"]
        payments_today = [p for p in self.payments if str(p.get("created_at", "")).startswith(today_str)]
        total_today = sum(float(p.get("paid_amount", 0) or 0) for p in payments_today)
        total_all = sum(float(p.get("paid_amount", 0) or 0) for p in self.payments)
        total_remaining = sum(float(m.get("current_remaining", 0) or 0) for m in members)
        #due_3 = [m for m in active if (parse_date(str(m.get("last_subscription_end", ""))) - today).days == 3]
        #due_1 = [m for m in active if (parse_date(str(m.get("last_subscription_end", ""))) - today).days == 1]
        #ended = [m for m in expired if parse_date(str(m.get("last_subscription_end", ""))) < today and m.get("last_subscription_end")]

        lines = [
            "تقرير هالك جيم اليومي",
            f"التاريخ: {today.strftime('%d/%m/%Y')} - الساعة: {datetime.now().strftime('%H:%M')}",
            "--------------------",
            f"إجمالي الأعضاء: {len(members)}",
            "--------------------",
            f"مدفوعات اليوم: {len(payments_today)} عملية",
            f"إيراد اليوم: {money(total_today)}",
            f"إجمالي الإيرادات: {money(total_all)}",
            f"إجمالي المتبقي: {money(total_remaining)}",
        ]

        lines.append("--------------------")
        lines.append("تفاصيل مدفوعات اليوم:")
        if payments_today:
            for p in payments_today:
                lines.append(
                    f"- {p.get('invoice_no', '-')[4:]} | {p.get('name', '-')} | {p.get('mobile', '-')} | "
                    f"{operation_ar(str(p.get('operation_type', '')))} | {money(p.get('paid_amount', 0))} | "
                    f"متبقي {money(p.get('remaining_amount', 0))} | {p.get('payment_method', '-')}"
                )
        else:
            lines.append("- لا توجد مدفوعات اليوم")

        lines.append("--------------------")
        return "\n".join(lines)

    def queue_whatsapp_message(
        self,
        mobile: str,
        message: str,
        msg_type: str,
        recipient_name: str = "",
        recipient_type: str = "member",
        reference_id: str = "",
        dedup_key: str = "",
        send_after: Optional[datetime] = None,
        save: bool = True,
        paid_amount: str = "",
        remaining_amount: str = "",
        subscription_end: str = "",
    ) -> Optional[Dict[str, Any]]:
        mobile = normalize_mobile(mobile)
        if not mobile or not message.strip():
            return None
        member = None
        initial_status = "pending"
        if recipient_type == "member":
            member = self.find_member_by_mobile(mobile)
            if member is None:
                return None
            synced_numbers = self._get_google_synced_numbers()
            synced_raw = str(member.get("google_contact_synced_at", "")).strip()
            # New numbers (no successful contact sync timestamp yet) are staged
            # for 1 hour, then moved to pending automatically.
            if mobile not in synced_numbers and not synced_raw:
                ready_at = datetime.now() + timedelta(hours=1)
                if send_after is None or send_after < ready_at:
                    send_after = ready_at
                initial_status = "scheduled"
        if not dedup_key:
            dedup_key = f"{msg_type}:{recipient_type}:{mobile}:{reference_id}"
        for msg in self.whatsapp_messages:
            if msg.get("dedup_key") == dedup_key:
                return None
        item_data = {
            "message_id": self.next_id("WA", self.whatsapp_messages, "message_id"),
            "type": msg_type,
            "recipient_type": recipient_type,
            "recipient_name": recipient_name,
            "mobile": mobile,
            "message": message,
            "status": initial_status,
            "created_at": now_str(),
            "send_after": send_after.strftime(DATETIME_FMT) if send_after else "",
            "sent_at": "",
            "error": "",
            "reference_id": reference_id,
            "dedup_key": dedup_key,
            "paid_amount": paid_amount,
            "remaining_amount": remaining_amount,
            "subscription_end": subscription_end,
        }
        self.whatsapp_messages.append(item_data)
        if save:
            self.save_whatsapp()
        return item_data

    def promote_scheduled_whatsapp_messages(self, save: bool = True) -> int:
        now = datetime.now()
        promoted = 0
        for message in self.whatsapp_messages:
            if str(message.get("status", "")) != "scheduled":
                continue
            send_after_raw = str(message.get("send_after", "")).strip()
            if not send_after_raw:
                created_raw = str(message.get("created_at", "")).strip()
                try:
                    created_at = datetime.strptime(created_raw, DATETIME_FMT)
                    message["send_after"] = (created_at + timedelta(hours=1)).strftime(DATETIME_FMT)
                except ValueError:
                    # If timestamp is malformed, keep it scheduled and wait for
                    # manual review instead of bypassing the one-hour rule.
                    continue
                continue
            try:
                send_after_at = datetime.strptime(send_after_raw, DATETIME_FMT)
            except ValueError:
                continue
            if now >= send_after_at:
                message["status"] = "pending"
                promoted += 1
        if promoted and save:
            self.save_whatsapp()
        return promoted

    def queue_receipt(self, payment: Dict[str, Any], save: bool = True) -> Optional[Dict[str, Any]]:
        return self.queue_whatsapp_message(
            mobile=str(payment.get("mobile", "")),
            message=self.build_receipt_message(payment),
            msg_type="receipt",
            recipient_name=str(payment.get("name", "")),
            recipient_type="member",
            reference_id=str(payment.get("invoice_no", "")),
            dedup_key=f"receipt:{payment.get('invoice_no', '')}",
            save=save,
            paid_amount=str(money(payment.get("paid_amount", 0))),
            remaining_amount=str(money(payment.get("remaining_amount", 0))),
            subscription_end=str(payment.get("subscription_end", "")),
        )

    def queue_due_reminders(self, save: bool = True) -> int:
        self.refresh_statuses(save=True)
        removed_stale = self.purge_blocked_pending_whatsapp_messages(save=False)
        today = date.today()
        added = 0
        for member in self.members:
            if not member.get("last_subscription_end") or not member.get("mobile"):
                continue
            end = parse_date(str(member.get("last_subscription_end", "")))
            days_left = (end - today).days
            if days_left == 1 and self._member_is_single_session(member):
                continue
            if member.get("current_status") == "active" and days_left in (1, 3):
                msg_type = "reminder_3" if days_left == 3 else "reminder_1"
                end_raw = str(member.get("last_subscription_end", "")).strip()
                if self._was_member_cycle_message_sent(member, msg_type=msg_type, cycle_key=end_raw):
                    continue
                if self._has_recent_member_message_for_cycle(member, msg_type=msg_type, cycle_key=end_raw, within_days=7):
                    continue
                queued = self.queue_whatsapp_message(
                    mobile=str(member.get("mobile", "")),
                    message=self.build_reminder_message(member, days_left),
                    msg_type=msg_type,
                    recipient_name=str(member.get("name", "")),
                    recipient_type="member",
                    reference_id=str(member.get("member_id", "")),
                    dedup_key=f"{msg_type}:{member.get('member_id', '')}:{end_raw}",
                    save=False,
                    subscription_end=end_raw,
                )
                added += 1 if queued else 0

            days_since_end = (today - end).days
            if member.get("current_status") == "expired" and 1 <= days_since_end <= 3:
                end_raw = str(member.get("last_subscription_end", "")).strip()
                if self._was_member_cycle_message_sent(member, msg_type="expired", cycle_key=end_raw):
                    continue
                if self._has_recent_member_message_for_cycle(member, msg_type="expired", cycle_key=end_raw, within_days=7):
                    continue
                if self._has_recent_expired_sent_message(member, within_days=3):
                    continue
                if self._has_open_expired_message(member):
                    continue
                queued = self.queue_whatsapp_message(
                    mobile=str(member.get("mobile", "")),
                    message=self.build_expired_message(member),
                    msg_type="expired",
                    recipient_name=str(member.get("name", "")),
                    recipient_type="member",
                    reference_id=str(member.get("member_id", "")),
                    dedup_key=f"expired:{member.get('member_id', '')}:{end_raw}",
                    save=False,
                    subscription_end=end_raw,
                )
                added += 1 if queued else 0
        if save and (added or removed_stale):
            self.save_whatsapp()
        return added

    def queue_expired_messages_for_members(self, members: List[Dict[str, Any]], save: bool = True, template: Optional[str] = None) -> List[Dict[str, Any]]:
        self.refresh_statuses(save=True)
        queued_items: List[Dict[str, Any]] = []
        for member in members:
            mobile = normalize_mobile(str(member.get("mobile", "")))
            if not mobile:
                continue
            if str(member.get("current_status", "")) != "expired":
                continue
            end_raw = str(member.get("last_subscription_end", "")).strip()
            if not end_raw:
                continue
            end_date = parse_date(end_raw)
            if end_date >= date.today():
                continue
            item = self.queue_whatsapp_message(
                mobile=mobile,
                message=self.build_expired_message(member, template=template),
                msg_type="expired",
                recipient_name=str(member.get("name", "")),
                recipient_type="member",
                reference_id=str(member.get("member_id", "")),
                dedup_key=f"expired:{member.get('member_id', '')}:{end_raw}",
                save=False,
            )
            if item is not None:
                queued_items.append(item)
        if save and queued_items:
            self.save_whatsapp()
        return queued_items

    def delete_sent_whatsapp_messages(self, older_than_hours: int = 0, save: bool = True) -> int:
        threshold: Optional[datetime] = None
        if older_than_hours > 0:
            threshold = datetime.now() - timedelta(hours=max(1, int(older_than_hours)))

        keep: List[Dict[str, Any]] = []
        removed = 0
        for message in self.whatsapp_messages:
            if is_receipt_protected_whatsapp_message(message):
                keep.append(message)
                continue
            if str(message.get("status", "")) != "sent":
                keep.append(message)
                continue

            if threshold is None:
                removed += 1
                continue

            sent_raw = str(message.get("sent_at", "")).strip() or str(message.get("created_at", "")).strip()
            sent_at: Optional[datetime] = None
            try:
                sent_at = datetime.strptime(sent_raw, DATETIME_FMT)
            except ValueError:
                sent_at = None

            if sent_at is not None and sent_at < threshold:
                removed += 1
                continue

            keep.append(message)

        if removed:
            self.whatsapp_messages = keep
            if save:
                self.save_whatsapp()
        return removed

    def queue_daily_report(self, force: bool = False, save: bool = True, allow_duplicate: bool = False) -> int:
        manager_mobile = normalize_mobile(str(self.settings.get("manager_mobile", "")))
        if not manager_mobile:
            return 0
        now = datetime.now()
        report_day = date_to_str(now.date())
        report_time = normalize_clock_time(str(self.settings.get("daily_report_time", "01:00")))
        if not report_time:
            report_time = "01:00"
        due_hour, due_minute = [int(part) for part in report_time.split(":", 1)]
        due_at = now.replace(hour=due_hour, minute=due_minute, second=0, microsecond=0)
        in_due_time = 0 <= (now - due_at).total_seconds() < 600
        if not force and not in_due_time:
            return 0
        dedup_key = f"daily_report:{report_day}"
        if allow_duplicate:
            dedup_key = f"daily_report:{report_day}:{now.strftime('%Y%m%d%H%M%S%f')}"
        queued = self.queue_whatsapp_message(
            mobile=manager_mobile,
            message=self.build_daily_report_message(),
            msg_type="daily_report",
            recipient_name="المدير",
            recipient_type="manager",
            reference_id=report_day,
            dedup_key=dedup_key,
            save=save,
        )
        return 1 if queued else 0

    def queue_daily_report_if_due(self, force: bool = False, save: bool = True) -> int:
        return self.queue_daily_report(force=force, save=save, allow_duplicate=False)

    def whatsapp_message_ready(self, message: Dict[str, Any]) -> bool:
        if message.get("status") != "pending":
            return False
        send_after = str(message.get("send_after", "")).strip()
        if send_after:
            try:
                if datetime.now() < datetime.strptime(send_after, DATETIME_FMT):
                    return False
            except ValueError:
                return False
        return True

    def pending_whatsapp_messages(self, ready_only: bool = False) -> List[Dict[str, Any]]:
        self.purge_blocked_pending_whatsapp_messages(save=True)
        pending = [m for m in self.whatsapp_messages if m.get("status") == "pending"]
        if ready_only:
            return [m for m in pending if self.whatsapp_message_ready(m)]
        return pending

    def mark_whatsapp_sent(self, message_ids: List[str], failed_ids: Optional[List[str]] = None, error: str = "") -> None:
        failed = set(failed_ids or [])
        target = set(message_ids)
        history_changed = False
        for msg in self.whatsapp_messages:
            if msg.get("message_id") in target:
                if msg.get("message_id") in failed:
                    msg["status"] = "failed"
                    msg["error"] = error or "فشل الإرسال"
                    msg["sent_at"] = ""
                else:
                    msg["status"] = "sent"
                    msg["error"] = ""
                    msg["sent_at"] = now_str()
                    history_changed = self._remember_sent_whatsapp_message(msg, save=False) or history_changed
        self.save_whatsapp()
        if history_changed:
            self.save_whatsapp_sent_history()

    def reset_failed_whatsapp(self) -> int:
        count = 0
        for msg in self.whatsapp_messages:
            if msg.get("status") == "failed":
                msg["status"] = "pending"
                msg["error"] = ""
                count += 1
        if count:
            self.save_whatsapp()
        return count

    def requeue_whatsapp_messages(self, message_ids: List[str]) -> int:
        """Create fresh pending copies for selected messages so old sent records stay saved."""
        wanted = {str(x) for x in message_ids if str(x).strip()}
        if not wanted:
            return 0
        count = 0
        original_messages = [m for m in self.whatsapp_messages if str(m.get("message_id", "")) in wanted]
        for msg in original_messages:
            fresh = dict(msg)
            fresh["message_id"] = self.next_id("WA", self.whatsapp_messages, "message_id")
            fresh["status"] = "pending"
            fresh["created_at"] = now_str()
            fresh["sent_at"] = ""
            fresh["error"] = ""
            fresh["dedup_key"] = f"manual_resend:{msg.get('message_id', '')}:{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            self.whatsapp_messages.append(fresh)
            count += 1
        if count:
            self.save_whatsapp()
        return count

    def filtered_whatsapp_messages(self, status_filter: str = "all", query: str = "") -> List[Dict[str, Any]]:
        rows = list(self.whatsapp_messages)
        if status_filter in ("pending", "sent", "failed"):
            rows = [m for m in rows if m.get("status") == status_filter]
        q = normalized_query(query)
        if q:
            compact_digits = normalize_mobile(q)
            rows = [
                m for m in rows
                if q in (search_blob(m) + " " + whatsapp_type_ar(str(m.get("type", ""))) + " " + whatsapp_status_ar(str(m.get("status", "")))).lower()
                or (compact_digits and compact_digits in normalize_mobile(str(m.get("mobile", ""))))
            ]
        return list(reversed(rows))


# -----------------------------
# UI helpers
# -----------------------------

def make_label(text: str, cls: str = "") -> QLabel:
    lbl = QLabel(text)
    if cls:
        lbl.setObjectName(cls)
        lbl.setProperty("class", cls)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    lbl.setWordWrap(True)
    return lbl


def make_card(title: str, value: str, icon: str = "") -> QFrame:
    card = QFrame()
    card.setObjectName("statCard")
    layout = QHBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(12)
    layout.setDirection(QBoxLayout.Direction.RightToLeft)

    icon_lbl = QLabel(icon)
    icon_lbl.setObjectName("cardIcon")
    icon_lbl.setAlignment(Qt.AlignCenter)
    icon_lbl.setFixedWidth(45)

    txt = QVBoxLayout()
    title_lbl = make_label(title, "muted")
    value_lbl = make_label(value, "statValue")
    txt.addWidget(title_lbl)
    txt.addWidget(value_lbl)

    layout.addWidget(icon_lbl)
    layout.addLayout(txt, 1)
    return card


def item(text: Any, align: Qt.AlignmentFlag = Qt.AlignCenter) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    it.setTextAlignment(align)
    return it


def configure_table(table: QTableWidget) -> None:
    table.setObjectName("darkTable")
    table.setLayoutDirection(Qt.RightToLeft)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.setWordWrap(True)
    table.setTextElideMode(Qt.ElideNone)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setFrameShape(QFrame.Shape.NoFrame)
    table.setFrameShadow(QFrame.Shadow.Plain)
    table.setStyleSheet(
        "QTableView, QTableWidget { border: 0px; padding: 0px; margin: 0px; }"
        "QHeaderView::section { padding: 0px; margin: 0px; border: 0px; }"
    )
    try:
        QScroller.grabGesture(table.viewport(), QScroller.LeftMouseButtonGesture)
    except Exception:
        pass


def fit_dialog_to_screen(dialog: QDialog, preferred_width: int, preferred_height: int) -> None:
    """Resize dialogs so bottom buttons never disappear behind the taskbar."""
    try:
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            preferred_width = min(preferred_width, max(640, geo.width() - 80))
            preferred_height = min(preferred_height, max(420, geo.height() - 90))
    except Exception:
        pass
    dialog.resize(preferred_width, preferred_height)


def create_dialog_shell(parent_layout: QVBoxLayout, max_width: int = 900) -> tuple[QVBoxLayout, QScrollArea]:
    """Create a centered scrollable dialog body with compact margins."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setObjectName("dialogScroll")
    try:
        QScroller.grabGesture(scroll.viewport(), QScroller.LeftMouseButtonGesture)
    except Exception:
        pass
    parent_layout.addWidget(scroll, 1)

    body = QWidget()
    scroll.setWidget(body)
    body_outer = QHBoxLayout(body)
    body_outer.setContentsMargins(14, 14, 14, 12)
    body_outer.setSpacing(0)
    body_outer.addStretch(1)

    dialog_shell = QWidget()
    dialog_shell.setObjectName("dialogShell")
    dialog_shell.setMaximumWidth(max_width)
    dialog_shell.setLayoutDirection(Qt.RightToLeft)
    body_outer.addWidget(dialog_shell, 12)
    body_outer.addStretch(1)

    layout = QVBoxLayout(dialog_shell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    return layout, scroll


def add_fixed_dialog_actions(parent_layout: QVBoxLayout, save_text: str, save_slot, cancel_slot) -> QPushButton:
    """Add fixed bottom action buttons outside the scroll area so they stay visible."""
    action_bar = QFrame()
    action_bar.setObjectName("dialogActionBar")
    actions = QHBoxLayout(action_bar)
    actions.setContentsMargins(14, 10, 14, 10)
    actions.setSpacing(10)
    actions.setDirection(QBoxLayout.Direction.RightToLeft)
    save = QPushButton(save_text)
    save.setObjectName("primaryButton")
    save.clicked.connect(save_slot)
    cancel = QPushButton("إلغاء")
    cancel.setObjectName("secondaryButton")
    cancel.clicked.connect(cancel_slot)
    actions.addWidget(save)
    actions.addWidget(cancel)
    actions.addStretch(1)
    parent_layout.addWidget(action_bar, 0)
    return save



class PasswordDialog(QDialog):
    def __init__(self, parent: QWidget, correct_password: str) -> None:
        super().__init__(parent)
        self.correct_password = correct_password
        self.ok = False
        self.setWindowTitle("كلمة سر الإيرادات")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(make_label("اكتب كلمة السر لإظهار الإيرادات في الرئيسية", "dialogTitleSmall"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("كلمة السر")
        layout.addWidget(self.password)
        actions = QHBoxLayout()
        actions.setDirection(QBoxLayout.Direction.RightToLeft)
        show = QPushButton("إظهار")
        show.setObjectName("primaryButton")
        cancel = QPushButton("إلغاء")
        cancel.setObjectName("secondaryButton")
        show.clicked.connect(self.check)
        cancel.clicked.connect(self.reject)
        actions.addWidget(show)
        actions.addWidget(cancel)
        layout.addLayout(actions)
        self.password.returnPressed.connect(self.check)

    def check(self) -> None:
        if self.password.text() == str(self.correct_password):
            self.ok = True
            self.accept()
        else:
            QMessageBox.warning(self, "خطأ", "كلمة السر غير صحيحة.")


class BasePage(QWidget):
    def __init__(self, store: Store, title: str, subtitle: str = "", max_width: Optional[int] = None) -> None:
        super().__init__()
        self.store = store
        self.setLayoutDirection(Qt.RightToLeft)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.page_shell = QWidget()
        self.page_shell.setObjectName("pageShell")
        self.page_shell.setLayoutDirection(Qt.RightToLeft)
        if max_width is not None:
            self.page_shell.setMaximumWidth(max_width)
        self.page_shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(self.page_shell, 1)

        self.root = QVBoxLayout(self.page_shell)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(8)

        if title or subtitle:
            head = QHBoxLayout()
            head.setDirection(QBoxLayout.Direction.RightToLeft)
            title_box = QVBoxLayout()
            title_box.setSpacing(4)
            if title:
                title_box.addWidget(make_label(title, "pageTitle"))
            if subtitle:
                title_box.addWidget(make_label(subtitle, "pageSubtitle"))
            head.addLayout(title_box, 1)
            self.root.addLayout(head)

    def refresh(self) -> None:
        pass


class MembersTablePage(BasePage):
    def __init__(
        self,
        store: Store,
        page_filter: str,
        title: str,
        subtitle: str,
        open_member_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        super().__init__(store, title, subtitle)
        self.page_filter = page_filter
        self.open_member_callback = open_member_callback
        controls = QHBoxLayout()
        controls.setDirection(QBoxLayout.Direction.RightToLeft)
        controls.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("ابحث بالاسم أو الموبايل أو نوع الاشتراك أو الحالة...")
        self.search.setObjectName("searchInput")
        self.search.setFont(QFont("Segoe UI", 11))
        self.search.setFixedHeight(34)
        self.search.textChanged.connect(self.refresh)
        controls.addWidget(self.search, 1)

        self.gender_filter = QComboBox()
        self.gender_filter.setFont(QFont("Segoe UI", 11))
        self.gender_filter.setFixedHeight(34)
        self.gender_filter.addItem("الكل", "all")
        self.gender_filter.addItem("ذكور", "male")
        self.gender_filter.addItem("إناث", "female")
        self.gender_filter.currentIndexChanged.connect(self.refresh)
        self.gender_filter.setFixedWidth(150)
        controls.addWidget(self.gender_filter)

        self.status_filter: Optional[QComboBox] = None
        if self.page_filter == "all":
            self.status_filter = QComboBox()
            self.status_filter.setFont(QFont("Segoe UI", 11))
            self.status_filter.setFixedHeight(34)
            self.status_filter.addItem("الكل", "all")
            self.status_filter.addItem("المشتركين", "active")
            self.status_filter.addItem("غير المشتركين", "expired")
            self.status_filter.addItem("عليهم متبقي", "remaining")
            self.status_filter.addItem("تذكير الاشتراكات", "reminder")
            self.status_filter.currentIndexChanged.connect(self.refresh)
            self.status_filter.setFixedWidth(180)
            controls.addWidget(self.status_filter)

        self.add_member_btn = QPushButton("+ إضافة عضو")
        self.add_member_btn.setObjectName("primaryButton")
        self.add_member_btn.setFixedHeight(34)
        self.add_member_btn.clicked.connect(self.open_add_member)
        controls.addWidget(self.add_member_btn)

        self.root.addLayout(controls)

        self.table = QTableWidget()
        configure_table(self.table)
        self.table.setFont(QFont("Segoe UI", 10))
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.cellDoubleClicked.connect(self.open_member)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        self.root.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        page_filter = self.page_filter
        if self.page_filter == "all" and self.status_filter is not None:
            page_filter = self.status_filter.currentData() if self.status_filter.currentData() else "all"
        rows = self.store.filtered_members(
            page_filter,
            self.gender_filter.currentData() if hasattr(self, "gender_filter") else "all",
            self.search.text() if hasattr(self, "search") else "",
        )
        if page_filter == "expired":
            def end_sort(member: Dict[str, Any]) -> date:
                end_date = str(member.get("last_subscription_end", ""))
                if not end_date:
                    return date.min
                return parse_date(end_date)

            rows = sorted(rows, key=end_sort, reverse=True)
        else:
            rows = sorted(rows, key=lambda m: str(m.get("last_payment_date", "")), reverse=True)
        headers = ["ID", "الاسم", "الموبايل", "نوع الاشتراك", "دفع", "متبقي", "البداية", "النهاية", "حالة الأيام", "الحالة", "رقم البصمة"]
        if self.page_filter == "expired":
            headers.extend(["تاريخ المتابعة", "ملاحظات"] )
        self.table.setUpdatesEnabled(False)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(3, 140)
        self.table.setColumnWidth(4, 90)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 100)
        self.table.setColumnWidth(7, 100)
        self.table.setColumnWidth(8, 100)
        self.table.setColumnWidth(9, 100)
        self.table.setColumnWidth(10, 110)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for r, m in enumerate(rows):
            member_id = str(m.get("member_id", ""))
            values = [
                member_id,
                m.get("name", ""),
                m.get("mobile", ""),
                m.get("last_subscription_type", ""),
                money(m.get("current_paid", 0)),
                money(m.get("current_remaining", 0)),
                display_date(m.get("last_subscription_start", "")),
                display_date(m.get("last_subscription_end", "")),
                subscription_days_text(str(m.get("last_subscription_end", ""))),
                status_ar(str(m.get("current_status", "expired"))),
                str(m.get("fingerprint_id", "")) or "غير مسجلة",
            ]
            if self.page_filter == "expired":
                values.extend([display_date(m.get("follow_up_date", "")), m.get("notes", "")])
            for c, v in enumerate(values):
                cell = item(v)
                if c == 0:
                    cell.setData(Qt.UserRole, m.get("member_id"))
                if c in (4, 5):
                    cell.setForeground(Qt.GlobalColor.green)
                self.table.setItem(r, c, cell)
        self.table.resizeRowsToContents()
        self.table.setUpdatesEnabled(True)

    def open_add_member(self) -> None:
        dlg = EditMemberDialog(self.store, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def open_context_menu(self, position) -> None:
        item = self.table.itemAt(position)
        if not item:
            return
        menu = QMenu(self)
        edit_action = menu.addAction("تعديل العضو")
        delete_action = menu.addAction("حذف العضو")
        action = menu.exec(self.table.mapToGlobal(position))
        if action == edit_action:
            row = self.table.row(item)
            self.open_edit_member(row)
        elif action == delete_action:
            row = self.table.row(item)
            self.delete_member(row)

    def open_edit_member(self, row: int) -> None:
        id_item = self.table.item(row, 0)
        if not id_item:
            return
        member_id = id_item.data(Qt.UserRole) or id_item.text()
        member = next((m for m in self.store.members if m.get("member_id") == member_id), None)
        if member:
            dlg = EditMemberDialog(self.store, self, member)
            if dlg.exec() == QDialog.Accepted:
                self.refresh()

    def delete_member(self, row: int) -> None:
        id_item = self.table.item(row, 0)
        if not id_item:
            return
        member_id = id_item.data(Qt.UserRole) or id_item.text()
        member = next((m for m in self.store.members if m.get("member_id") == member_id), None)
        if member:
            reply = QMessageBox.question(
                self,
                "تأكيد الحذف",
                f"هل أنت متأكد من حذف {member.get('name', '')}؟\nهذا الإجراء غير قابل للتراجع.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                try:
                    self.store.delete_member(member_id)
                    self.refresh()
                    QMessageBox.information(self, "تم", f"تم حذف {member.get('name', '')}.")
                except Exception as exc:
                    QMessageBox.warning(self, "خطأ", str(exc))
                    self.store.delete_member(member_id)
                    self.refresh()
                    QMessageBox.information(self, "تم", f"تم حذف {member.get('name', '')}")
                except Exception as exc:
                    QMessageBox.warning(self, "خطأ", str(exc))

    def open_member(self, row: int, _col: int) -> None:
        id_item = self.table.item(row, 0)
        if not id_item:
            return
        member_id = id_item.data(Qt.UserRole) or id_item.text()
        member = next((m for m in self.store.members if m.get("member_id") == member_id), None)
        if member:
            if self.open_member_callback:
                self.open_member_callback(member)
            else:
                MemberDetailsDialog(self.store, member, self).exec()

class ManagerPage(BasePage):
    """Password-locked manager dashboard with 9 stat cards and formatted reports."""

    def __init__(self, store: Store) -> None:
        super().__init__(store, "لوحة المدير", "إحصائيات وتقارير يومية، أسبوعية، وشهرية")

        # Make the manager page scrollable
        self.scroll = QScrollArea()
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        # 3x3 cards grid
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        def make_card(title: str) -> tuple[QFrame, QLabel]:
            f = QFrame()
            f.setObjectName("statCard")
            f.setMinimumHeight(130)
            l = QVBoxLayout(f)
            l.setContentsMargins(12, 10, 12, 10)
            l.setSpacing(6)
            l.addWidget(make_label(title, "smallMuted"))
            lbl = QLabel("0")
            lbl.setObjectName("statValue")
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lbl.setStyleSheet("font-size:24px; font-weight:800;")
            l.addWidget(lbl)
            return f, lbl

        cards = [
            "إجمالي الأعضاء",
            "الأعضاء المشتركين",
            "العضوية منتهية",
            "إيرادات اليوم",
            "إيرادات الأسبوع",
            "إيرادات الشهر",
            "إجمالي المتبقي",
            "أعضاء جدد هذا الشهر",
            "عدد عمليات اليوم",
        ]

        self.card_frames: List[QFrame] = []
        self.card_values: List[QLabel] = []
        for idx, title in enumerate(cards):
            f, lbl = make_card(title)
            r = idx // 3
            c = idx % 3
            grid.addWidget(f, r, c)
            self.card_frames.append(f)
            self.card_values.append(lbl)

        content_layout.addLayout(grid)

        # Reports controls
        controls = QHBoxLayout()
        controls.setDirection(QBoxLayout.Direction.RightToLeft)
        controls.setSpacing(8)

        self.day_btn = QPushButton("تقرير اليوم")
        self.day_btn.setObjectName("primaryButton")
        self.day_btn.setFixedHeight(30)
        self.day_btn.setProperty("reportActive", "true")
        self.day_btn.clicked.connect(self.report_day)
        controls.addWidget(self.day_btn)

        self.week_btn = QPushButton("تقرير الأسبوع")
        self.week_btn.setObjectName("secondaryButton")
        self.week_btn.setFixedHeight(30)
        self.week_btn.setProperty("reportActive", "false")
        self.week_btn.clicked.connect(self.report_week)
        controls.addWidget(self.week_btn)

        self.month_btn = QPushButton("تقرير الشهر")
        self.month_btn.setObjectName("secondaryButton")
        self.month_btn.setFixedHeight(30)
        self.month_btn.setProperty("reportActive", "false")
        self.month_btn.clicked.connect(self.report_month)
        controls.addWidget(self.month_btn)

        self.month_selector = QComboBox()
        self.month_selector.setObjectName("secondaryButton")
        self.month_selector.setFixedHeight(30)
        self.month_selector.setFont(QFont("Segoe UI", 9))
        self.month_selector.currentIndexChanged.connect(lambda _: self.report_selected_month())
        controls.addWidget(self.month_selector)

        self.pdf_export_btn = QPushButton("تصدير PDF")
        self.pdf_export_btn.setObjectName("primaryButton")
        self.pdf_export_btn.setFixedHeight(30)
        self.pdf_export_btn.setFont(QFont("Segoe UI", 9))
        self.pdf_export_btn.clicked.connect(self.export_current_report_pdf)
        controls.addWidget(self.pdf_export_btn)

        self.report_buttons = [self.day_btn, self.week_btn, self.month_btn]
        self._period_start = date.today()
        self._period_end = date.today()

        controls.addStretch(1)
        content_layout.addLayout(controls)

        # Report output (HTML formatted)
        self.report_output = QTextEdit()
        self.report_output.setReadOnly(True)
        self.report_output.setObjectName("detailCard")
        self.report_output.setMinimumHeight(260)
        self.report_output.setFont(QFont("Segoe UI", 11))
        content_layout.addWidget(self.report_output, 1)

        # attach content to scroll area and add to root
        self.scroll.setWidget(content_widget)
        self.root.addWidget(self.scroll, 1)

        self.refresh()
        self.populate_month_selector()
        self.report_day()

    def _payments_in_range(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        pays: List[Dict[str, Any]] = []
        for p in self.store.payments:
            created = str(p.get("created_at", ""))[:10]
            try:
                d = parse_date(created)
            except Exception:
                continue
            if start_date <= d <= end_date:
                pays.append(p)
        return pays

    def refresh(self) -> None:
        members = self.store.members
        total = len(members)
        active = sum(1 for m in members if str(m.get("current_status", "expired")) == "active")
        expired = total - active

        today = date.today()
        rev_today = sum(float(p.get("paid_amount", 0) or 0) for p in self._payments_in_range(today, today))
        rev_week = sum(float(p.get("paid_amount", 0) or 0) for p in self._payments_in_range(today - timedelta(days=6), today))
        rev_month = sum(float(p.get("paid_amount", 0) or 0) for p in self._payments_in_range(date(today.year, today.month, 1), today))

        outstanding = sum(float(m.get("current_remaining", 0) or 0) for m in members)

        # New members this month: try to parse timestamp from member_id 'member_{ms}'
        new_members_month = 0
        for m in members:
            mid = str(m.get("member_id", ""))
            if mid.startswith("member_"):
                try:
                    ts = int(mid.split("member_")[-1]) / 1000.0
                    created = datetime.fromtimestamp(ts).date()
                    if created >= date(today.year, today.month, 1):
                        new_members_month += 1
                except Exception:
                    pass

        payments_today_count = len(self._payments_in_range(today, today))

        values = [
            total,
            active,
            expired,
            money(rev_today),
            money(rev_week),
            money(rev_month),
            money(outstanding),
            new_members_month,
            payments_today_count,
        ]

        for lbl, val in zip(self.card_values, values):
            lbl.setText(str(val))

    def _set_active_report_button(self, active_btn: QPushButton) -> None:
        for btn in self.report_buttons:
            active = btn is active_btn
            btn.setProperty("reportActive", "true" if active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
            btn.repaint()

    def _render_payments_html(self, pays: List[Dict[str, Any]], title: str) -> str:
        today = date.today()
        total = sum(float(p.get("paid_amount", 0) or 0) for p in pays)
        count = len(pays)
        active = [m for m in self.store.members if str(m.get("current_status", "expired")) == "active"]
        expired = [m for m in self.store.members if str(m.get("current_status", "expired")) == "expired"]
        with_remaining = [m for m in self.store.members if float(m.get("current_remaining", 0) or 0) > 0]
        outstanding = sum(float(m.get("current_remaining", 0) or 0) for m in self.store.members)

        ended_today = 0
        ended_period = 0
        for m in self.store.members:
            last_end = str(m.get("last_subscription_end", "")).strip()
            if not last_end:
                continue
            try:
                end_date = parse_date(last_end)
            except Exception:
                continue
            if end_date == today:
                ended_today += 1
            if self._period_start <= end_date <= self._period_end:
                ended_period += 1

        period_expense = 0.0
        for expense in self.store.expenses:
            date_str = str(expense.get("date", "")).strip()
            try:
                exp_date = parse_date(date_str)
            except Exception:
                continue
            if self._period_start <= exp_date <= self._period_end:
                period_expense += float(expense.get("amount", 0) or 0)

        new_members = 0
        for m in self.store.members:
            mid = str(m.get("member_id", ""))
            if mid.startswith("member_"):
                try:
                    ts = int(mid.split("member_")[-1]) / 1000.0
                    created = datetime.fromtimestamp(ts).date()
                    if self._period_start <= created <= self._period_end:
                        new_members += 1
                except Exception:
                    pass

        renewals = sum(1 for p in pays if str(p.get("operation_type", "")) == "renewal")

        html = f"<h2 style='margin-bottom:12px;'>{title}</h2>"
        html += "<div style='display:grid; gap:18px; grid-template-columns:repeat(2, minmax(240px, 1fr)); margin-bottom:18px;'>"
        html += self._report_metric_card("عدد العمليات", str(count), "#FFFFFF")
        html += self._report_metric_card("إجمالي الإيراد", money(total), "#B7F56D")
        html += self._report_metric_card("إجمالي المصروف", money(period_expense), "#FFB8B8")
        html += self._report_metric_card("إجمالي المتبقي", money(outstanding), "#F3F8FB")
        html += self._report_metric_card("عليهم متبقي", str(len(with_remaining)), "#FFB8B8")
        html += self._report_metric_card("المشتركين", str(len(active)), "#7ED321")
        html += self._report_metric_card("غير المشتركين", str(len(expired)), "#A8B3BC")
        html += self._report_metric_card("مشتركين جدد", str(new_members), "#7ED321")
        html += self._report_metric_card("تجديدات", str(renewals), "#D64550")
        html += self._report_metric_card("انتهى اشتراكهم اليوم", str(ended_today), "#FFB8B8")
        html += self._report_metric_card("انتهى اشتراكهم خلال الفترة", str(ended_period), "#FFB8B8")
        html += "</div>"

        return html

    def _report_metric_card(self, title: str, value: str, color: str) -> str:
        return (
            f"<div style='background:#0F1B24; border:1px solid #23303B; border-radius:14px; padding:14px; direction:rtl;'>"
            f"<div style='color:#A8B3BC; margin-bottom:8px; text-align:center;'>{title}</div>"
            f"<div style='color:{color}; font-size:22px; font-weight:800; text-align:center;'>{value}</div>"
            "</div>"
        )

    def report_day(self) -> None:
        self._period_end = date.today()
        self._period_start = self._period_end
        self._set_active_report_button(self.day_btn)
        pays = self._payments_in_range(self._period_start, self._period_end)
        self.report_output.setHtml(self._render_payments_html(pays, f"تقرير اليوم - {display_date(date_to_str(self._period_end))}"))

    def report_week(self) -> None:
        self._period_end = date.today()
        self._period_start = self._period_end - timedelta(days=6)
        self._set_active_report_button(self.week_btn)
        pays = self._payments_in_range(self._period_start, self._period_end)
        self.report_output.setHtml(self._render_payments_html(pays, f"تقرير الأسبوع - {display_date(date_to_str(self._period_start))} إلى {display_date(date_to_str(self._period_end))}"))

    def populate_month_selector(self) -> None:
        self.month_selector.blockSignals(True)
        self.month_selector.clear()
        today = date.today()
        months: List[tuple[str, tuple[int, int]]] = []
        for i in range(0, 13):
            year = today.year
            month = today.month - i
            while month <= 0:
                month += 12
                year -= 1
            label = f"{month:02d}/{year}"
            months.append((label, (year, month)))
        for label, data in months:
            self.month_selector.addItem(label, data)
        self.month_selector.blockSignals(False)
        self.month_selector.setCurrentIndex(0)

    def report_selected_month(self) -> None:
        raw_data = self.month_selector.currentData()
        data = raw_data
        if data is None:
            data = self.month_selector.itemData(self.month_selector.currentIndex())
        if not isinstance(data, (tuple, list)):
            to_python = getattr(data, "toPython", None)
            if callable(to_python):
                try:
                    data = to_python()
                except Exception:
                    data = raw_data
        if not isinstance(data, (tuple, list)) or len(data) != 2:
            try:
                if isinstance(data, str) and "/" in data:
                    month_str, year_str = data.split("/")
                    data = (int(year_str.strip()), int(month_str.strip()))
            except Exception:
                data = None
        if not isinstance(data, (tuple, list)) or len(data) != 2:
            return
        year, month = data
        self._period_start = date(year, month, 1)
        self._period_end = date(year, month, calendar.monthrange(year, month)[1])
        self._set_active_report_button(self.month_btn)
        pays = self._payments_in_range(self._period_start, self._period_end)
        self.report_output.setHtml(self._render_payments_html(
            pays,
            f"تقرير شهر {display_date(date_to_str(self._period_start))} إلى {display_date(date_to_str(self._period_end))}",
        ))

    def report_month(self) -> None:
        if self.month_selector.count() == 0:
            return
        self.month_selector.setCurrentIndex(0)
        self.report_selected_month()

    def export_current_report_pdf(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "حفظ تقرير PDF",
            str(DATA_DIR / f"report_{self._period_start.strftime('%Y%m')}.pdf"),
            "ملفات PDF (*.pdf)",
        )
        if not filename:
            return
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        text_content = self.report_output.toPlainText().strip()
        if not text_content:
            QMessageBox.warning(self, "خطأ", "لا يوجد تقرير لتصديره.")
            return

        lines = [line.strip() for line in text_content.splitlines() if line.strip()]
        title = lines[0] if lines else "تقرير"
        body_lines = lines[1:]

        def render_line(line: str) -> str:
            important_keywords = [
                "إجمالي الإيراد",
                "إجمالي المصروف",
                "المتبقي",
                "إجمالي المتبقي",
                "عدد العمليات",
                "المشتركين",
                "غير المشتركين",
            ]
            escaped = escape(line)
            if any(keyword in line for keyword in important_keywords):
                return f"<p class='important'>{escaped}</p>"
            if ":" in line or "-" in line:
                parts = re.split(r"(?<=[\-:])\s*", escaped, maxsplit=1)
                if len(parts) == 2:
                    return f"<p><strong>{parts[0]}</strong> {parts[1]}</p>"
            return f"<p>{escaped}</p>"

        body_html = "".join(render_line(line) for line in body_lines)

        html = (
            "<html><head>"
            "<meta charset=\"utf-8\"/>"
            "<style>"
            "body{font-family:'Segoe UI','Tahoma',sans-serif; color:#111111; background:#FFFFFF; margin:0; padding:30px; direction:rtl;}"
            "h1{font-size:60px; font-weight:900; margin-bottom:32px; line-height:1.1;}"
            "p{font-size:32px; line-height:2.4; margin:18px 0;}"
            "p.important{font-size:38px; font-weight:900; color:#000000; margin:22px 0;}"
            "strong{font-weight:900;}"
            "div.detail{max-width:100%; width:100%;}"
            "</style></head><body>"
            f"<h1>{escape(title)}</h1>"
            f"<div class='detail'>{body_html}</div>"
            "</body></html>"
        )

        document = QTextDocument()
        document.setDefaultFont(QFont("Segoe UI", 24))
        document.setHtml(html)

        writer = QPdfWriter(filename)
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setResolution(300)
        writer.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Millimeter)

        painter = QPainter(writer)
        document.drawContents(painter)
        painter.end()

        QMessageBox.information(self, "تم", f"تم حفظ التقرير بصيغة PDF إلى:\n{filename}")

class MemberDetailsPage(BasePage):
    def __init__(
        self,
        store: Store,
        back_callback: Callable[[], None],
        renew_callback: Callable[[str], None],
    ) -> None:
        super().__init__(store, "تفاصيل المشترك", "عرض كامل ومنسق لكل بيانات المشترك")
        self.page_shell.setMaximumWidth(16777215)
        self.page_shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.back_callback = back_callback
        self.renew_callback = renew_callback
        self.member: Optional[Dict[str, Any]] = None

        header_layout = QHBoxLayout()
        header_layout.setDirection(QBoxLayout.Direction.RightToLeft)
        self.back_btn = QPushButton("رجوع")
        self.back_btn.setObjectName("secondaryButton")
        self.back_btn.clicked.connect(self.back_callback)
        header_layout.addWidget(self.back_btn)
        header_layout.addStretch(1)

        self.edit_btn = QPushButton("تعديل العضو")
        self.edit_btn.setObjectName("secondaryButton")
        self.edit_btn.clicked.connect(self.edit_member)
        header_layout.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("حذف العضو")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self.delete_member)
        header_layout.addWidget(self.delete_btn)

        self.enroll_fingerprint_btn = QPushButton("تسجيل البصمة")
        self.enroll_fingerprint_btn.setObjectName("secondaryButton")
        self.enroll_fingerprint_btn.clicked.connect(self.enroll_fingerprint)
        header_layout.addWidget(self.enroll_fingerprint_btn)

        self.delete_fingerprint_btn = QPushButton("حذف البصمة")
        self.delete_fingerprint_btn.setObjectName("dangerButton")
        self.delete_fingerprint_btn.clicked.connect(self.delete_fingerprint)
        header_layout.addWidget(self.delete_fingerprint_btn)

        self.sync_esp_btn = QPushButton("مزامنة ESP")
        self.sync_esp_btn.setObjectName("primaryButton")
        self.sync_esp_btn.clicked.connect(self.sync_esp)
        header_layout.addWidget(self.sync_esp_btn)

        self.root.addLayout(header_layout)

        self.renew_sub_btn = QPushButton("ـجديد الاشتراك")
        self.renew_sub_btn.setObjectName("primaryButton")
        self.renew_sub_btn.setMinimumHeight(54)
        self.renew_sub_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.renew_sub_btn.clicked.connect(self.renew_subscription)
        self.root.addWidget(self.renew_sub_btn)

        self.title_label = make_label("", "dialogTitle")
        self.root.addWidget(self.title_label)

        status_row = QHBoxLayout()
        status_row.setDirection(QBoxLayout.Direction.RightToLeft)
        status_row.addStretch(1)
        self.status_chip = make_label("", "statusChip")
        self.status_chip.setAlignment(Qt.AlignCenter)
        self.status_chip.setFixedHeight(44)
        status_row.addWidget(self.status_chip)
        self.root.addLayout(status_row)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content_widget = QWidget()
        content_widget.setLayoutDirection(Qt.RightToLeft)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(24)
        self.scroll.setWidget(content_widget)
        self.root.addWidget(self.scroll, 1)

        info_frame = QFrame()
        info_frame.setObjectName("detailCard")
        info_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info_layout = QHBoxLayout(info_frame)
        info_layout.setContentsMargins(20, 20, 20, 20)
        info_layout.setSpacing(24)

        left_frame = QFrame()
        left_frame.setObjectName("detailCard")
        left_layout = QGridLayout(left_frame)
        left_layout.setHorizontalSpacing(18)
        left_layout.setVerticalSpacing(16)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.summary_fields: Dict[str, QLabel] = {}
        row_labels = [
            ("الاسم", "name"),
            ("الموبايل", "mobile"),
            ("النوع", "gender"),
            ("الحالة", "status"),
            ("الاشتراك الحالي", "subscription"),
            ("بداية الاشتراك", "start"),
            ("نهاية الاشتراك", "end"),
            ("آخر دفع", "last_payment"),
            ("تاريخ المتابعة", "follow_up"),
            ("ملاحظات", "notes"),
        ]
        for idx, (label_text, key) in enumerate(row_labels):
            left_layout.addWidget(make_label(label_text, "fieldLabel"), idx, 1, Qt.AlignRight)
            value_label = make_label("-", "muted")
            value_label.setWordWrap(True)
            left_layout.addWidget(value_label, idx, 0)
            self.summary_fields[key] = value_label

        right_frame = QFrame()
        right_frame.setObjectName("metricCard")
        right_frame.setFrameShape(QFrame.Shape.StyledPanel)
        right_frame.setFrameShadow(QFrame.Shadow.Raised)
        right_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(18)
        self.paid_label = make_label("المدفوع\n-", "metricValue")
        self.remaining_label = make_label("المتبقي\n-", "metricValue")
        self.subscription_label = make_label("الاشتراك\n-", "metricValue")
        right_layout.addWidget(self.paid_label)
        right_layout.addWidget(self.remaining_label)
        right_layout.addWidget(self.subscription_label)
        right_layout.addStretch(1)

        info_layout.addWidget(left_frame, 3)
        info_layout.addWidget(right_frame, 2)
        content_layout.addWidget(info_frame)

        self.history_section_title = make_label("سجل المدفوعات والفواتير السابقة", "sectionTitle")
        content_layout.addWidget(self.history_section_title)

        self.history_table = QTableWidget()
        self.history_table.setObjectName("memberDetailTable")
        self.history_table.setLayoutDirection(Qt.LeftToRight)
        self.history_table.setWordWrap(True)
        self.history_table.setMinimumHeight(420)
        self.history_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.history_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.history_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        configure_table(self.history_table)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setMinimumSectionSize(90)
        self.history_table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.history_table.horizontalHeader().setStretchLastSection(False)
        self.history_table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        content_layout.addWidget(self.history_table, 1)

    def set_member(self, member: Dict[str, Any]) -> None:
        self.member = member
        self.title_label.setText(f"{member.get('name', '')} - {member.get('mobile', '')}")
        self.summary_fields["name"].setText(str(member.get("name", "-")))
        self.summary_fields["mobile"].setText(str(member.get("mobile", "-")))
        self.summary_fields["gender"].setText(gender_ar(str(member.get("gender", "male"))))
        status_text = status_ar(str(member.get("current_status", "expired")))
        self.summary_fields["status"].setText(status_text)
        self.status_chip.setText(status_text)
        self.summary_fields["subscription"].setText(str(member.get("last_subscription_type", "-")))
        self.summary_fields["start"].setText(display_date(member.get("last_subscription_start", "")))
        self.summary_fields["end"].setText(display_date(member.get("last_subscription_end", "")))
        self.summary_fields["last_payment"].setText(str(member.get("last_payment_date", "-")))
        self.summary_fields["follow_up"].setText(display_date(member.get("follow_up_date", "")) or "-")
        self.summary_fields["notes"].setText(str(member.get("notes", "-")) or "-")
        has_fingerprint = str(member.get("fingerprint_id", "")).strip() != ""
        self.enroll_fingerprint_btn.setEnabled(not has_fingerprint)
        self.delete_fingerprint_btn.setEnabled(has_fingerprint)
        self.renew_sub_btn.setEnabled(True)
        self.paid_label.setText(f"المدفوع\n{money(member.get('current_paid', 0))}")
        self.remaining_label.setText(f"المتبقي\n{money(member.get('current_remaining', 0))}")
        self.subscription_label.setText(f"الاشتراك\n{member.get('last_subscription_type', '-')}")

        history = member.get("subscriptions_history", [])
        headers = ["الفاتورة", "نوع العملية", "الاشتراك", "المدفوع", "المتبقي", "التاريخ", "البداية", "النهاية"]
        self.history_table.setColumnCount(len(headers))
        self.history_table.setHorizontalHeaderLabels(headers)
        self.history_table.setRowCount(len(history))
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.history_table.setColumnWidth(3, 100)
        self.history_table.setColumnWidth(4, 100)
        for r, entry in enumerate(history):
            values = [
                entry.get("invoice_no", "-"),
                operation_ar(str(entry.get("operation_type", "new_subscription"))),
                entry.get("subscription_type", "-"),
                money(entry.get("paid_amount", 0)),
                money(entry.get("remaining_amount", 0)),
                display_date(entry.get("created_at", "")),
                display_date(entry.get("subscription_start", "")),
                display_date(entry.get("subscription_end", "")),
            ]
            for c, value in enumerate(values):
                cell = item(value)
                if c in (3, 4):
                    cell.setForeground(Qt.GlobalColor.green)
                self.history_table.setItem(r, c, cell)
            self.history_table.setRowHeight(r, 46)

    def refresh(self) -> None:
        if self.member:
            self.set_member(self.member)

    def enroll_fingerprint(self) -> None:
        if not self.member:
            return
        if str(self.member.get("fingerprint_id", "")).strip():
            return
        reply = QMessageBox.question(
            self,
            "تأكيد تسجيل البصمة",
            f"هل تريد بدء تسجيل بصمة {self.member.get('name', '')}؟\n"
            "سيطلب الجهاز وضع الإصبع مرتين.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            start_fingerprint_enrollment(self, self.store, self.member)

    def sync_esp(self) -> None:
        start_members_sync(self, self.store)

    def renew_subscription(self) -> None:
        if self.member:
            self.renew_callback(str(self.member.get("member_id", "")))

    def delete_fingerprint(self) -> None:
        if not self.member:
            return
        fingerprint_id = self.member.get("fingerprint_id")
        if fingerprint_id in (None, ""):
            return
        reply = QMessageBox.question(
            self,
            "تأكيد حذف البصمة",
            f"هل تريد حذف البصمة رقم {fingerprint_id} من جهاز ESP؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if not self.store.esp_command_allowed():
            QMessageBox.warning(self, "فشل الحذف", "لا يمكن حذف البصمة قبل تحديث حالة ESP والتأكد من اتصاله.")
            return

        self.delete_fingerprint_btn.setEnabled(False)
        thread = ESPOperationThread("delete", self.store.settings, fingerprint_id=fingerprint_id)
        self._delete_fingerprint_thread = thread

        def finished(result: Dict[str, Any]) -> None:
            self.delete_fingerprint_btn.setEnabled(True)
            if not result.get("success"):
                error = result.get("error", result.get("error_detail", "delete_failed"))
                QMessageBox.warning(self, "فشل حذف البصمة", f"DELETE FAILED: {error}")
                return
            self.member["fingerprint_id"] = ""
            self.store.save_members(push_to_esp=False)
            start_members_sync(self, self.store, "تم حذف البصمة بنجاح.")
            self.set_member(self.member)

        thread.done.connect(finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def edit_member(self) -> None:
        if not self.member:
            return
        try:
            debug_log(f"MemberDetailsPage.edit_member:open member_id={self.member.get('member_id', '')}")
            dlg = EditMemberDialog(self.store, self, self.member)
            result = dlg.exec()
            debug_log(f"MemberDetailsPage.edit_member:dialog-result={int(result)}")
            if result == QDialog.Accepted:
                member_id = self.member.get("member_id")
                self.member = next((m for m in self.store.members if m.get("member_id") == member_id), self.member)
                self.set_member(self.member)
                debug_log("MemberDetailsPage.edit_member:refresh-after-accept-done")
        except Exception as exc:
            debug_log(f"MemberDetailsPage.edit_member:unhandled-error {exc}")
            debug_log(traceback.format_exc())
            QMessageBox.critical(self, "خطأ", f"حدث خطأ أثناء تحديث بيانات العضو:\n{exc}")

    def delete_member(self) -> None:
        if not self.member:
            return
        reply = QMessageBox.question(
            self,
            "تأكيد الحذف",
            f"هل أنت متأكد من حذف {self.member.get('name', '')}؟\nهذا الإجراء غير قابل للتراجع.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        member_id = self.member.get("member_id")
        try:
            self.store.delete_member(member_id)
        except ValueError as exc:
            QMessageBox.warning(self, "فشل حذف العضو", str(exc))
            return
        QMessageBox.information(self, "تم", f"تم حذف {self.member.get('name', '')}.")
        self.member = None
        self.back_callback()


class AddSubscriptionPage(BasePage):
    def __init__(
        self,
        store: Store,
        mode: str,
        back_callback: Callable[[], None],
        save_callback: Callable[[], None],
        pay_remaining_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(store, "", "")
        self.mode = mode
        self.is_renewal = mode == "renewal"
        self.is_smart = mode == "smart"
        self.back_callback = back_callback
        self.save_callback = save_callback
        self.pay_remaining_callback = pay_remaining_callback

        self.scroll = QScrollArea()
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setLayoutDirection(Qt.RightToLeft)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.scroll.setWidget(content)
        self.root.addWidget(self.scroll, 1)

        form_frame = QFrame()
        form_frame.setObjectName("detailCard")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(4)
        content_layout.addWidget(form_frame)

        if self.is_renewal:
            self.member_picker = QComboBox()
            self.member_picker.setEditable(True)
            self.member_picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            if self.member_picker.lineEdit():
                self.member_picker.lineEdit().setPlaceholderText("ابحث باسم المشترك أو الموبايل")
        else:
            self.member_picker = None

        self.name = QLineEdit()
        self.name.setPlaceholderText("اسم المشترك")
        self.mobile = QLineEdit()
        self.mobile.setPlaceholderText("الموبايل")
        self.name_completer_model = QStringListModel(self.build_name_suggestions())
        self.name_completer = QCompleter(self.name_completer_model, self)
        self.name_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.name_completer.setFilterMode(Qt.MatchContains)
        self.name_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.name.setCompleter(self.name_completer)
        self.gender = QComboBox()
        self.gender.addItem("ذكر", "male")
        self.gender.addItem("أنثى", "female")
        self.plan = QComboBox()
        for p in self.store.settings.get("plans", []):
            self.plan.addItem(str(p.get("name")), p)
        self.start = QDateEdit()
        self.start.setCalendarPopup(True)
        self.start.setDate(QDate.currentDate())
        self.start.setDisplayFormat(DISPLAY_DATE_FMT)
        self.paid = QDoubleSpinBox()
        self.paid.setRange(0, 1_000_000)
        self.paid.setDecimals(2)
        self.paid.setSingleStep(50)
        if self.store.settings.get("plans"):
            self.paid.setValue(float(self.store.settings["plans"][0].get("price", 0) or 0))
        self.allowance_days = QSpinBox()
        self.allowance_days.setRange(0, 365)
        self.allowance_days.setSingleStep(1)
        self.allowance_days.setValue(0)
        self.start_programmatic_change = False

        widgets = []
        if self.member_picker is not None:
            widgets.append(("اختار المشترك", self.member_picker))
        
        if self.is_renewal:
            self.name.setReadOnly(True)
            self.mobile.setReadOnly(True)
            self.gender.setEnabled(False)

        for lbl, w in widgets:
            field_container = QVBoxLayout()
            field_container.setSpacing(4)
            label = make_label(lbl, "fieldLabel")
            field_container.addWidget(label)
            field_container.addWidget(w)
            form_layout.addLayout(field_container)

        # صف واحد: الاسم والموبايل
        row_name_mobile = QHBoxLayout()
        row_name_mobile.setDirection(QBoxLayout.Direction.RightToLeft)
        row_name_mobile.setSpacing(6)
        for lbl, w in [("الاسم", self.name), ("الموبايل", self.mobile)]:
            field_container = QVBoxLayout()
            field_container.setSpacing(4)
            label = make_label(lbl, "fieldLabel")
            field_container.addWidget(label)
            field_container.addWidget(w)
            row_name_mobile.addLayout(field_container, 1)
        form_layout.addLayout(row_name_mobile)

        # صف ثاني: النوع والاشتراك
        row1 = QHBoxLayout()
        row1.setDirection(QBoxLayout.Direction.RightToLeft)
        row1.setSpacing(6)
        for lbl, w in [("النوع", self.gender), ("نوع الاشتراك", self.plan)]:
            field_container = QVBoxLayout()
            field_container.setSpacing(4)
            label = make_label(lbl, "fieldLabel")
            field_container.addWidget(label)
            field_container.addWidget(w)
            row1.addLayout(field_container, 1)
        form_layout.addLayout(row1)

        # صف ثالث: التاريخ والمدفوع وأيام السماح
        row2 = QHBoxLayout()
        row2.setDirection(QBoxLayout.Direction.RightToLeft)
        row2.setSpacing(6)
        for lbl, w in [
            ("بداية الاشتراك" if not self.is_renewal else "بداية التجديد", self.start),
            ("المدفوع .ج", self.paid),
            ("أيام السماح", self.allowance_days),
        ]:
            field_container = QVBoxLayout()
            field_container.setSpacing(4)
            label = make_label(lbl, "fieldLabel")
            field_container.addWidget(label)
            field_container.addWidget(w)
            row2.addLayout(field_container, 1)
        form_layout.addLayout(row2)

        self.calc = make_label("", "calcBox")
        self.calc.setWordWrap(True)
        content_layout.addWidget(self.calc)

        actions = QHBoxLayout()
        actions.setDirection(QBoxLayout.Direction.RightToLeft)
        actions.setSpacing(12)
        button_label = "تسجيل / تجديد" if self.is_smart else ("حفظ التجديد" if self.is_renewal else "حفظ الاشتراك")
        self.save_button = QPushButton(button_label)
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.save)
        cancel_button = QPushButton("رجوع")
        cancel_button.setObjectName("secondaryButton")
        cancel_button.clicked.connect(self.back_callback)
        actions.addWidget(self.save_button)
        actions.addWidget(cancel_button)
        actions.addStretch(1)
        content_layout.addLayout(actions)

        if self.member_picker is not None:
            self.member_picker.currentIndexChanged.connect(self.load_selected_member)
        if self.is_smart or self.mode == "new_subscription":
            self.name_completer.activated.connect(self.on_name_selected)
        self.plan.currentIndexChanged.connect(self.update_plan_price)
        self.plan.currentIndexChanged.connect(self.update_calc)
        self.paid.valueChanged.connect(self.update_calc)
        self.allowance_days.valueChanged.connect(self.update_calc)
        self.start.dateChanged.connect(self.on_start_date_changed)
        if self.is_renewal:
            self.refresh()
            self.load_selected_member()
        self.update_calc()

    def on_start_date_changed(self, date: QDate) -> None:
        if self.start_programmatic_change:
            self.start_programmatic_change = False
            self.update_calc()
            return
        # Only prompt about adjusting allowance days when the new start date
        # is in the future (suspicious) and allowance days is zero. If the
        # user sets a past date (e.g., back-dating a subscription), do not
        # interrupt with confirmation dialogs.
        try:
            new_date = qdate_to_py(self.start.date())
            if int(self.allowance_days.value()) == 0 and new_date > date.today():
                answer = QMessageBox.question(
                    self,
                    "تأكيد تعديل التاريخ",
                    "لقد عدّلت تاريخ بداية الاشتراك يدويًا. هل تريد تعديل أيام السماح يدويًا؟\nاختر نعم لتعيين أيام السماح، أو لا للاستمرار بدون فترة سماح.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer == QMessageBox.Yes:
                    self.allowance_days.setFocus()
        except Exception:
            pass
        self.update_calc()

    def refresh(self) -> None:
        if self.member_picker is None:
            return
        self.member_picker.blockSignals(True)
        current_text = self.member_picker.lineEdit().text() if self.member_picker.lineEdit() else ""
        selected_member_id = self.member_picker.currentData() if self.member_picker.currentIndex() >= 0 else None
        self.member_picker.clear()
        for member in sorted(self.store.members, key=lambda m: str(m.get("name", ""))):
            text = f"{member.get('name', '')} - {member.get('mobile', '')} - {status_ar(str(member.get('current_status', '')))}"
            self.member_picker.addItem(text, member.get("member_id"))
        restored_index = -1
        for idx in range(self.member_picker.count()):
            if self.member_picker.itemData(idx) == selected_member_id:
                restored_index = idx
                break
        if restored_index >= 0:
            self.member_picker.setCurrentIndex(restored_index)
        else:
            self.member_picker.setCurrentIndex(-1)
        if self.member_picker.lineEdit():
            self.member_picker.lineEdit().setText(current_text)
        self.member_picker.blockSignals(False)
        if restored_index >= 0:
            self.load_selected_member()
        if self.name.completer() is not None:
            self.name_completer_model.setStringList(self.build_name_suggestions())

    def build_mobile_suggestions(self) -> list[str]:
        return [normalize_mobile(str(m.get("mobile", ""))) for m in self.store.members if str(m.get("mobile", "")).strip()]

    def build_name_suggestions(self) -> list[str]:
        return [str(m.get("name", "")) for m in self.store.members if str(m.get("name", "")).strip()]

    def selected_member(self) -> Optional[Dict[str, Any]]:
        if not self.is_renewal or self.member_picker is None or self.member_picker.currentIndex() < 0:
            return None
        member_id = self.member_picker.currentData()
        return next((m for m in self.store.members if m.get("member_id") == member_id), None)

    def select_member(self, member_id: str) -> None:
        if self.member_picker is None:
            return
        for idx in range(self.member_picker.count()):
            if self.member_picker.itemData(idx) == member_id:
                self.member_picker.setCurrentIndex(idx)
                self.load_selected_member()
                return

    def current_member(self) -> Optional[Dict[str, Any]]:
        if self.is_renewal:
            return self.selected_member()
        if self.is_smart or self.mode == "new_subscription":
            mobile = normalize_mobile(self.mobile.text().strip())
            if not mobile:
                return None
            return self.store.find_member_by_mobile(mobile)
        return None

    def on_mobile_changed(self, text: str) -> None:
        member = self.current_member()
        if not member:
            return
        self.fill_member_from_existing(member)

    def on_name_selected(self, text: str) -> None:
        if not text.strip():
            return
        member = self.store.find_member_by_name(text)
        if not member:
            return
        self.mobile.setText(str(member.get("mobile", "")))
        self.fill_member_from_existing(member)

    def fill_member_from_existing(self, member: Dict[str, Any]) -> None:
        self.name.setText(str(member.get("name", "")))
        gender = str(member.get("gender", "male"))
        self.gender.setCurrentIndex(1 if gender == "female" else 0)
        plan_name = str(member.get("last_subscription_type", ""))
        if plan_name:
            idx = self.plan.findText(plan_name)
            if idx >= 0:
                self.plan.setCurrentIndex(idx)
        suggested = self.store.suggested_renewal_start(member)
        self.start_programmatic_change = True
        self.start.setDate(qdate_from_date(suggested))
        self.update_calc()

    def clear_form(self) -> None:
        self.name.clear()
        self.mobile.clear()
        if self.member_picker is not None:
            self.member_picker.blockSignals(True)
            self.member_picker.setCurrentIndex(-1)
            if self.member_picker.lineEdit():
                self.member_picker.lineEdit().clear()
            self.member_picker.blockSignals(False)
        self.gender.setCurrentIndex(0)
        self.plan.setCurrentIndex(0)
        self.start_programmatic_change = True
        self.start.setDate(QDate.currentDate())
        self.allowance_days.setValue(0)
        self.update_plan_price()
        self.update_calc()

    def update_plan_price(self) -> None:
        data = self.plan.currentData()
        if isinstance(data, dict):
            self.paid.setValue(float(data.get("price", 0) or 0))

    def load_selected_member(self) -> None:
        member = self.selected_member()
        if not member:
            # Keep any pre-filled name/mobile values intact when the picker is
            # briefly in a no-selection state during refreshes or mode switches.
            self.start_programmatic_change = True
            self.start.setDate(QDate.currentDate())
            self.update_calc()
            return
        self.name.setText(str(member.get("name", "")))
        self.mobile.setText(str(member.get("mobile", "")))
        self.gender.setCurrentIndex(1 if str(member.get("gender", "male")) == "female" else 0)
        suggested = self.store.suggested_renewal_start(member)
        self.start_programmatic_change = True
        self.start.setDate(qdate_from_date(suggested))
        self.update_calc()

    def update_calc(self) -> None:
        member = self.current_member() if self.is_smart else (self.selected_member() if self.is_renewal else None)
        if member and float(member.get("current_remaining", 0) or 0) > 0:
            self.calc.setText(
                f"لا يمكن تجديد الاشتراك لأن على المشترك متبقي {money(member.get('current_remaining', 0))}. استخدم دفع المتبقي أولًا."
            )
            self.save_button.setEnabled(False)
            return
        self.save_button.setEnabled(True)
        plan_name = self.plan.currentText()
        start = qdate_to_py(self.start.date())
        paid = float(self.paid.value())
        days_override = int(self.allowance_days.value())
        end, price, remaining, days = self.store.calculate_end(start, plan_name, paid, days_override)
        if self.is_smart:
            prefix = "تجديد" if member else "اشتراك جديد"
        else:
            prefix = "تجديد" if self.is_renewal else "اشتراك جديد"
        note = "" if days_override == 0 else f" | أيام السماح: {days_override}"
        self.calc.setText(
            f"{prefix}  |  سعر الخطة: {money(price)}  |  الأيام: {days} يوم  |  المتبقي: {money(remaining)}  |  النهاية: {display_date(end)}{note}"
        )

    def save(self) -> None:
        debug_log(f"AddSubscriptionPage.save:start mode={self.mode}")
        member = self.current_member() if self.is_smart else (self.selected_member() if self.is_renewal else None)
        if self.is_renewal and member is None:
            debug_log("AddSubscriptionPage.save:renewal-no-member")
            QMessageBox.warning(self, "تنبيه", "لا يوجد مشترك محدد للتجديد.")
            return
        name = str(member.get("name", "")).strip() if member else self.name.text().strip()
        mobile = str(member.get("mobile", "")).strip() if member else self.mobile.text().strip()
        gender = str(member.get("gender", "male")) if member else str(self.gender.currentData())
        if not name:
            QMessageBox.warning(self, "تنبيه", "اكتب اسم المشترك.")
            return
        
        is_valid, error_msg = validate_mobile(mobile)
        if not is_valid:
            QMessageBox.warning(self, "تنبيه", error_msg)
            return
        
        if self.plan.count() == 0:
            QMessageBox.warning(self, "تنبيه", "لا توجد خطط اشتراك في الإعدادات.")
            return
        if member and float(member.get("current_remaining", 0) or 0) > 0:
            reply = QMessageBox.question(
                self,
                "دفع المتبقي",
                f"المشترك عليه متبقي {money(member.get('current_remaining', 0))}. هل تريد الانتقال إلى صفحة دفع المتبقي؟",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes and self.pay_remaining_callback is not None:
                self.pay_remaining_callback(str(member.get("member_id", "")))
            return
        normalized_mobile = normalize_mobile(mobile)
        existing = member or self.store.find_member_by_mobile(normalized_mobile)
        try:
            payload = {
                "operation_type": "renewal" if (self.is_renewal or (self.is_smart and existing)) else "new_subscription",
                "name": name,
                "mobile": normalize_mobile(mobile),
                "gender": gender,
                "subscription_type": self.plan.currentText(),
                "subscription_start": date_to_str(qdate_to_py(self.start.date())),
                "paid_amount": self.paid.value(),
                "payment_method": str(self.store.settings.get("payment_methods", ["نقدي"])[0]),
            }
            if int(self.allowance_days.value()) > 0:
                payload["allowance_days"] = int(self.allowance_days.value())
            debug_log(f"AddSubscriptionPage.save:before-add-payment op={payload.get('operation_type')} mobile={payload.get('mobile')}")
            payment = self.store.add_payment(payload)
            debug_log(f"AddSubscriptionPage.save:payment-saved invoice={payment.get('invoice_no', '')}")
        except ValueError as exc:
            debug_log(f"AddSubscriptionPage.save:value-error {exc}")
            QMessageBox.warning(self, "تنبيه", str(exc))
            return
        saved_member = self.store.find_member_by_mobile(normalize_mobile(mobile))
        if saved_member and not str(saved_member.get("fingerprint_id", "")).strip():
            QTimer.singleShot(0, lambda m=saved_member: start_fingerprint_enrollment(self, self.store, m))
        if name and mobile:
            try:
                debug_log("AddSubscriptionPage.save:queue-google-contact")
                self.store.queue_google_contact({"name": name, "mobile": mobile})
            except Exception as exc:
                debug_log(f"AddSubscriptionPage.save:queue-google-contact-error {exc}")
        QMessageBox.information(self, "تم", f"تم الحفظ بنجاح رقم {payment['invoice_no']}")
        debug_log("AddSubscriptionPage.save:success-message-shown")
        try:
            self.clear_form()
            self.update_calc()
        except Exception as exc:
            debug_log(f"AddSubscriptionPage.save:clear-form-error {exc}")
        try:
            debug_log("AddSubscriptionPage.save:queue-save-callback")
            QTimer.singleShot(0, self.save_callback)
        except Exception as exc:
            debug_log(f"AddSubscriptionPage.save:save-callback-error {exc}")
            QMessageBox.warning(self, "تنبيه", f"تم حفظ التجديد لكن حدث خطأ بعد الحفظ: {exc}")
            return
        try:
            debug_log("AddSubscriptionPage.save:queue-back-callback")
            QTimer.singleShot(0, self.back_callback)
        except Exception as exc:
            debug_log(f"AddSubscriptionPage.save:back-callback-error {exc}")
            QMessageBox.warning(self, "تنبيه", f"تم الحفظ لكن تعذر الرجوع للصفحة الرئيسية: {exc}")


class RemainingPaymentPage(BasePage):
    def __init__(
        self,
        store: Store,
        back_callback: Callable[[], None],
        save_callback: Callable[[], None],
    ) -> None:
        super().__init__(store, "", "")
        self.back_callback = back_callback
        self.save_callback = save_callback

        self.scroll = QScrollArea()
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setLayoutDirection(Qt.RightToLeft)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)
        self.scroll.setWidget(content)
        self.root.addWidget(self.scroll, 1)

        form_frame = QFrame()
        form_frame.setObjectName("detailCard")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(8, 8, 8, 8)
        form_layout.setSpacing(4)
        content_layout.addWidget(form_frame)

        self.member_picker = QComboBox()
        self.member_picker.setEditable(True)
        self.member_picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if self.member_picker.lineEdit():
            self.member_picker.lineEdit().setPlaceholderText("ابحث باسم المشترك أو الموبايل")

        self.name = QLineEdit(); self.name.setReadOnly(True)
        self.mobile = QLineEdit(); self.mobile.setReadOnly(True)
        self.plan = QLineEdit(); self.plan.setReadOnly(True)
        self.current_end = QLineEdit(); self.current_end.setReadOnly(True)
        self.remaining_before = QLineEdit(); self.remaining_before.setReadOnly(True)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000)
        self.amount.setDecimals(2)
        self.amount.setSingleStep(50)
        self.days = QDoubleSpinBox()
        self.days.setRange(0, 365)
        self.days.setDecimals(0)
        self.days.setSingleStep(1)
        self.days.setValue(0)

        # اختار المشترك
        row_picker = QVBoxLayout()
        row_picker.setSpacing(4)
        row_picker.addWidget(make_label("اختار المشترك", "fieldLabel"))
        row_picker.addWidget(self.member_picker)
        form_layout.addLayout(row_picker)

        # الاسم والموبايل
        row_name_mobile = QHBoxLayout()
        row_name_mobile.setDirection(QBoxLayout.Direction.RightToLeft)
        row_name_mobile.setSpacing(6)
        for lbl, w in [("الاسم", self.name), ("الموبايل", self.mobile)]:
            field_container = QVBoxLayout()
            field_container.setSpacing(2)
            field_container.addWidget(make_label(lbl, "fieldLabel"))
            field_container.addWidget(w)
            row_name_mobile.addLayout(field_container, 1)
        form_layout.addLayout(row_name_mobile)

        # الخطة الحالية والنهاية الحالية
        row_plan_end = QHBoxLayout()
        row_plan_end.setDirection(QBoxLayout.Direction.RightToLeft)
        row_plan_end.setSpacing(6)
        for lbl, w in [("الخطة الحالية", self.plan), ("النهاية الحالية", self.current_end)]:
            field_container = QVBoxLayout()
            field_container.setSpacing(2)
            field_container.addWidget(make_label(lbl, "fieldLabel"))
            field_container.addWidget(w)
            row_plan_end.addLayout(field_container, 1)
        form_layout.addLayout(row_plan_end)

        # المتبقي الحالي والمبلغ المدفوع والأيام
        row_remaining_amount = QHBoxLayout()
        row_remaining_amount.setDirection(QBoxLayout.Direction.RightToLeft)
        row_remaining_amount.setSpacing(6)
        for lbl, w in [("المتبقي الحالي", self.remaining_before), ("المبلغ المدفوع", self.amount), ("أيام التمديد", self.days)]:
            field_container = QVBoxLayout()
            field_container.setSpacing(2)
            field_container.addWidget(make_label(lbl, "fieldLabel"))
            field_container.addWidget(w)
            row_remaining_amount.addLayout(field_container, 1)
        form_layout.addLayout(row_remaining_amount)

        self.calc = make_label("", "calcBox")
        self.calc.setWordWrap(True)
        content_layout.addWidget(self.calc)

        actions = QHBoxLayout()
        actions.setDirection(QBoxLayout.Direction.RightToLeft)
        actions.setSpacing(12)
        self.save_button = QPushButton("حفظ دفع المتبقي")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.save)
        self.extend_button = QPushButton("مد يوم")
        self.extend_button.setObjectName("secondaryButton")
        self.extend_button.clicked.connect(self.extend_one_day)
        cancel_button = QPushButton("رجوع")
        cancel_button.setObjectName("secondaryButton")
        cancel_button.clicked.connect(self.back_callback)
        actions.addWidget(self.save_button)
        actions.addWidget(self.extend_button)
        actions.addWidget(cancel_button)
        actions.addStretch(1)
        content_layout.addLayout(actions)

        self.member_picker.currentIndexChanged.connect(self.load_selected_member)
        self.amount.valueChanged.connect(self.update_calc)
        self.days.valueChanged.connect(self.update_calc)
        self.refresh()

    def refresh(self) -> None:
        self.member_picker.blockSignals(True)
        current_text = self.member_picker.lineEdit().text() if self.member_picker.lineEdit() else ""
        self.member_picker.clear()
        self.remaining_members = sorted(self.store.members_with_remaining(), key=lambda m: str(m.get("name", "")))
        for member in self.remaining_members:
            text = f"{member.get('name', '')} - {member.get('mobile', '')} - متبقي {money(member.get('current_remaining', 0))}"
            self.member_picker.addItem(text, member.get("member_id"))
        self.member_picker.setCurrentIndex(-1)
        if self.member_picker.lineEdit():
            self.member_picker.lineEdit().setText(current_text)
        self.member_picker.blockSignals(False)

    def selected_member(self) -> Optional[Dict[str, Any]]:
        if self.member_picker.count() == 0 or self.member_picker.currentIndex() < 0:
            return None
        member_id = self.member_picker.currentData()
        return next((m for m in self.store.members if m.get("member_id") == member_id), None)

    def select_member(self, member_id: str) -> None:
        for idx in range(self.member_picker.count()):
            if self.member_picker.itemData(idx) == member_id:
                self.member_picker.setCurrentIndex(idx)
                self.load_selected_member()
                return

    def clear_form(self) -> None:
        self.name.clear()
        self.mobile.clear()
        self.plan.clear()
        self.current_end.clear()
        self.remaining_before.clear()
        self.amount.blockSignals(True)
        self.amount.setRange(0, 1_000_000)
        self.amount.setValue(0)
        self.amount.blockSignals(False)
        self.days.blockSignals(True)
        self.days.setValue(0)
        self.days.blockSignals(False)
        self.calc.setText("اختار مشترك علشان تشوف الحساب والكلام ده")
        self.save_button.setEnabled(False)
        self.extend_button.setEnabled(False)

    def load_selected_member(self) -> None:
        member = self.selected_member()
        if not member:
            self.clear_form()
            return
        remaining = float(member.get("current_remaining", 0) or 0)
        self.name.setText(str(member.get("name", "")))
        self.mobile.setText(str(member.get("mobile", "")))
        self.plan.setText(str(member.get("last_subscription_type", "")))
        self.current_end.setText(display_date(member.get("last_subscription_end", "")))
        self.remaining_before.setText(money(remaining))
        self.amount.blockSignals(True)
        self.amount.setRange(0, remaining)
        self.amount.setValue(remaining)
        self.amount.blockSignals(False)
        self.days.blockSignals(True)
        self.days.setValue(0)
        self.days.blockSignals(False)
        self.update_calc()

    def extend_one_day(self) -> None:
        self.days.setValue(int(self.days.value()) + 1)
        self.update_calc()

    def update_calc(self) -> None:
        member = self.selected_member()
        if not member:
            self.calc.setText("لا يوجد أي مشترك ليتم عرض بياناته.")
            self.save_button.setEnabled(False)
            self.extend_button.setEnabled(False)
            return
        try:
            new_end, remaining_before, remaining_after, days_added = self.store.calculate_remaining_extension(member, float(self.amount.value()), int(self.days.value()))
            self.calc.setText(
                f"المتبقي قبل الدفع: {money(remaining_before)}  |  المدفوع الآن: {money(self.amount.value())}  |  المتبقي بعد الدفع: {money(remaining_after)}  |  تمديد: {days_added} يوم  |  النهاية الجديدة: {display_date(new_end)}"
            )
            self.save_button.setEnabled(True)
            self.extend_button.setEnabled(True)
        except ValueError as exc:
            self.calc.setText(str(exc))
            self.save_button.setEnabled(False)
            self.extend_button.setEnabled(False)

    def save(self) -> None:
        member = self.selected_member()
        if member is None:
            QMessageBox.warning(self, "تنبيه", "اختار مشترك صحيح.")
            return
        try:
            payment = self.store.pay_remaining(
                member.get("member_id", ""),
                float(self.amount.value()),
                str(self.store.settings.get("payment_methods", ["نقدي"])[0]),
                int(self.days.value()),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "تنبيه", str(exc))
            return
        saved_member = next(
            (m for m in self.store.members if str(m.get("member_id", "")) == str(member.get("member_id", ""))),
            member,
        )
        if not str(saved_member.get("fingerprint_id", "")).strip():
            QTimer.singleShot(0, lambda m=saved_member: start_fingerprint_enrollment(self, self.store, m))
        if member is not None and member.get("mobile"):
            try:
                self.store.queue_google_contact(member)
                synced_count = self.store.flush_google_contacts_queue()
                if synced_count > 0:
                    QMessageBox.information(self, "تم", "تم حفظ الرقم في جهات الاتصال.")
            except Exception:
                pass
        QMessageBox.information(self, "تم", f"تم حفظ دفع المتبقي رقم {payment['invoice_no']}")
        self.clear_form()
        self.save_callback()
        self.back_callback()

    def refresh(self) -> None:
        self.member_picker.blockSignals(True)
        self.member_picker.clear()
        self.remaining_members = sorted(self.store.members_with_remaining(), key=lambda m: str(m.get("name", "")))
        for member in self.remaining_members:
            text = f"{member.get('name', '')} - {member.get('mobile', '')} - متبقي {money(member.get('current_remaining', 0))}"
            self.member_picker.addItem(text, member.get("member_id"))
        self.member_picker.setCurrentIndex(-1)
        if self.member_picker.lineEdit():
            self.member_picker.lineEdit().clear()
        self.member_picker.blockSignals(False)
        self.clear_form()


class AddExpensePage(BasePage):
    def __init__(
        self,
        store: Store,
        back_callback: Callable[[], None],
        save_callback: Callable[[], None],
    ) -> None:
        super().__init__(store, "", "")
        self.back_callback = back_callback
        self.save_callback = save_callback

        self.scroll = QScrollArea()
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setLayoutDirection(Qt.RightToLeft)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)
        self.scroll.setWidget(content)
        self.root.addWidget(self.scroll, 1)

        form_frame = QFrame()
        form_frame.setObjectName("detailCard")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(12, 12, 12, 12)
        form_layout.setSpacing(6)
        content_layout.addWidget(form_frame)

        self.name = QComboBox()
        self.name.setEditable(False)
        self.name.addItem("اختر اسم المصروف")
        categories = [c for c in self.store.settings.get("expense_categories", []) if str(c).strip()]
        if not categories:
            categories = ["مصروف عام"]
        for category in categories:
            self.name.addItem(str(category))
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000)
        self.amount.setDecimals(2)
        self.amount.setSingleStep(50)
        self.amount.setValue(0)
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat(DISPLAY_DATE_FMT)
        self.date.setDate(QDate.currentDate())
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("ملاحظات إضافية (اختياري)")

        widgets = [
            ("اسم المصروف", self.name),
            ("المبلغ", self.amount),
            ("التاريخ", self.date),
            ("ملاحظات", self.notes),
        ]
        for lbl, w in widgets:
            field_container = QVBoxLayout()
            field_container.setSpacing(4)
            field_container.addWidget(make_label(lbl, "fieldLabel"))
            field_container.addWidget(w)
            form_layout.addLayout(field_container)

        actions = QHBoxLayout()
        actions.setDirection(QBoxLayout.Direction.RightToLeft)
        actions.setSpacing(12)
        self.save_button = QPushButton("حفظ المصروف")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self.save)
        cancel_button = QPushButton("رجوع")
        cancel_button.setObjectName("secondaryButton")
        cancel_button.clicked.connect(self.back_callback)
        actions.addWidget(self.save_button)
        actions.addWidget(cancel_button)
        actions.addStretch(1)
        content_layout.addLayout(actions)

    def save(self) -> None:
        try:
            if isinstance(self.name, QComboBox):
                if self.name.currentIndex() <= 0:
                    raise ValueError("اختار اسم مصروف من القائمة.")
                expense_name = self.name.currentText()
            else:
                expense_name = self.name.text()
            expense = self.store.add_expense(
                {
                    "name": expense_name,
                    "amount": self.amount.value(),
                    "date": date_to_str(qdate_to_py(self.date.date())),
                    "notes": self.notes.text(),
                }
            )
        except ValueError as exc:
            QMessageBox.warning(self, "تنبيه", str(exc))
            return
        QMessageBox.information(self, "تم", f"تم حفظ المصروف: {expense.get('name', '')}.")
        self.save_callback()
        self.back_callback()


class PaymentsPage(BasePage):
    def __init__(self, store: Store) -> None:
        super().__init__(store, "المدفوعات", "عرض وإدارة جميع المدفوعات المسجلة في النظام")
        controls = QHBoxLayout()
        controls.setDirection(QBoxLayout.Direction.RightToLeft)
        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText("ابحث برقم الفاتورة أو الاسم أو الموبايل أو طريقة الدفع...")
        self.search.textChanged.connect(self.refresh)
        controls.addWidget(self.search, 1)
        self.count_lbl = make_label("0 دفعة", "muted")
        self.count_lbl.setFixedWidth(130)
        controls.addWidget(self.count_lbl)
        self.root.addLayout(controls)

        self.table = QTableWidget()
        configure_table(self.table)
        self.root.addWidget(self.table, 1)
        self.refresh()

    def refresh(self) -> None:
        rows = self.store.filtered_payments(self.search.text() if hasattr(self, "search") else "")
        rows = sorted(rows, key=lambda p: str(p.get("created_at", "")), reverse=True)
        self.count_lbl.setText(f"{len(rows)} دفعة")
        headers = ["الفاتورة", "نوع العملية", "الاسم", "الموبايل", "الاشتراك", "المبلغ", "متبقي", "الدفع", "البداية", "النهاية", "الحالة"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            invoice_no = str(p.get("invoice_no", ""))
            short_invoice = invoice_no if len(invoice_no) <= 4 else f"...{invoice_no[-4:]}"
            values = [
                short_invoice,
                operation_ar(str(p.get("operation_type", "new_subscription"))),
                p.get("name", ""),
                p.get("mobile", ""),
                p.get("subscription_type", ""),
                money(p.get("paid_amount", 0)),
                money(p.get("remaining_amount", 0)),
                p.get("payment_method", ""),
                display_date(p.get("subscription_start", "")),
                display_date(p.get("subscription_end", "")),
                status_ar(str(p.get("status", ""))),
            ]
            for c, v in enumerate(values):
                cell = item(v)
                if c in (5, 6):
                    cell.setForeground(Qt.GlobalColor.green)
                self.table.setItem(r, c, cell)
        if self.table.columnCount() > 2:
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            self.table.setColumnWidth(2, 260)
        self.table.resizeRowsToContents()


class UnifiedEntryPage(BasePage):
    def __init__(
        self,
        store: Store,
        back_callback: Callable[[], None],
        save_callback: Callable[[], None],
    ) -> None:
        super().__init__(store, "", "")
        self.back_callback = back_callback
        self.save_callback = save_callback

        header = QHBoxLayout()
        header.setDirection(QBoxLayout.Direction.RightToLeft)
        header.setSpacing(10)
        title = make_label("إدارة العمليات", "pageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.root.addLayout(header)

        self.info_label = make_label("اكتب اسم العضو أو الموبايل وسيتم تحديد العملية تلقائيًا.", "muted")
        self.info_label.setWordWrap(True)
        self.root.addWidget(self.info_label)

        self.attendance_label = make_label("", "calcBox")
        self.attendance_label.setWordWrap(True)
        self.root.addWidget(self.attendance_label)

        search_row = QHBoxLayout()
        search_row.setDirection(QBoxLayout.Direction.RightToLeft)
        search_row.setSpacing(8)
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("ابحث بالاسم أو الموبايل")
        self.query_input.setObjectName("searchInput")
        self.query_input.setMinimumHeight(44)
        self.query_input.returnPressed.connect(self.resolve_member)
        self.query_completer_model = QStringListModel(self.build_suggestions())
        self.query_completer = QCompleter(self.query_completer_model, self)
        self.query_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.query_completer.setFilterMode(Qt.MatchContains)
        self.query_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.query_input.setCompleter(self.query_completer)
        self.query_completer.activated.connect(self.resolve_member)
        search_row.addWidget(self.query_input, 1)
        self.resolve_btn = QPushButton("بحث")
        self.resolve_btn.setObjectName("primaryButton")
        self.resolve_btn.clicked.connect(self.resolve_member)
        search_row.addWidget(self.resolve_btn)
        self.root.addLayout(search_row)

        self.stack = QStackedWidget()
        self.root.addWidget(self.stack, 1)

        self.new_page = AddSubscriptionPage(
            self.store,
            "new_subscription",
            self.back_callback,
            self.handle_save_complete,
        )
        self.renew_page = AddSubscriptionPage(
            self.store,
            "renewal",
            self.back_callback,
            self.handle_save_complete,
        )
        self.remaining_page = RemainingPaymentPage(
            self.store,
            self.back_callback,
            self.handle_save_complete,
        )

        self.stack.addWidget(self.new_page)
        self.stack.addWidget(self.renew_page)
        self.stack.addWidget(self.remaining_page)

        self.current_mode = "new_subscription"
        self.switch_mode(0)
        self.resolve_member()

    def build_suggestions(self) -> List[str]:
        suggestions: List[str] = []
        for member in self.store.members:
            name = str(member.get("name", "")).strip()
            mobile = str(member.get("mobile", "")).strip()
            if name and mobile:
                suggestions.append(f"{name} - {mobile}")
            elif name:
                suggestions.append(name)
            elif mobile:
                suggestions.append(mobile)
        return list(dict.fromkeys(suggestions))

    def _member_display_text(self, member: Dict[str, Any]) -> str:
        name = str(member.get("name", "")).strip() or "-"
        mobile = str(member.get("mobile", "")).strip() or "-"
        status = status_ar(str(member.get("current_status", "")))
        return f"{name} - {mobile} - {status}"

    def _find_member_candidates(self, query: str) -> List[Dict[str, Any]]:
        raw_query = str(query or "").strip()
        if not raw_query:
            return []

        query_lower = raw_query.lower()
        query_mobile = normalize_mobile(raw_query)

        parsed_name = ""
        parsed_mobile = ""
        if " - " in raw_query:
            parts = [p.strip() for p in raw_query.split(" - ") if p.strip()]
            if parts:
                parsed_name = parts[0].lower()
            if len(parts) >= 2:
                parsed_mobile = normalize_mobile(parts[1])

        matched: List[Dict[str, Any]] = []
        for member in self.store.members:
            member_name = str(member.get("name", "")).strip()
            member_name_lower = member_name.lower()
            member_mobile_raw = str(member.get("mobile", "")).strip()
            member_mobile = normalize_mobile(member_mobile_raw)
            combined = f"{member_name} - {member_mobile_raw}".lower()

            if parsed_name and parsed_mobile:
                if member_name_lower == parsed_name and member_mobile == parsed_mobile:
                    matched.append(member)
                continue

            if query_mobile and member_mobile == query_mobile:
                matched.append(member)
                continue

            if member_name_lower == query_lower:
                matched.append(member)
                continue

            if query_lower in member_name_lower:
                matched.append(member)
                continue

            if query_mobile and query_mobile in member_mobile:
                matched.append(member)
                continue

            if query_lower in combined:
                matched.append(member)

        unique_by_id: Dict[str, Dict[str, Any]] = {}
        for member in matched:
            member_id = str(member.get("member_id", "")).strip()
            key = member_id or f"{member.get('name', '')}|{member.get('mobile', '')}"
            unique_by_id[key] = member
        return list(unique_by_id.values())

    def _choose_member_from_candidates(self, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        ordered = sorted(candidates, key=lambda m: str(m.get("name", "")))
        labels = [self._member_display_text(member) for member in ordered]
        selected_label, ok = QInputDialog.getItem(
            self,
            "اختيار المشترك",
            "في أكثر من مشترك مطابق لنفس البحث. اختر الاسم الصحيح:",
            labels,
            0,
            False,
        )
        if not ok:
            return None
        idx = labels.index(selected_label)
        return ordered[idx]

    def resolve_member(self, text: str = "") -> None:
        query = str(text or self.query_input.text() or "").strip()
        if not query:
            self.info_label.setText("اكتب اسم العضو أو الموبايل وسيتم تحديد العملية تلقائيًا.")
            self.switch_mode(0)
            return

        candidates = self._find_member_candidates(query)
        member = self._choose_member_from_candidates(candidates)

        if member is None:
            if candidates:
                self.info_label.setText("تم إلغاء اختيار المشترك. اختر الاسم المطلوب من القائمة.")
                return
            self.info_label.setText("هذا العضو غير موجود، سيتم فتح تسجيل عضو جديد.")
            self.attendance_label.setText("لا يوجد عضو مسجل حتى الآن.")
            self.switch_mode(0)
            self.new_page.name.setText(query)
            self.new_page.mobile.setText(query if self._looks_like_mobile(query) else "")
            return

        self.query_input.setText(f"{member.get('name', '')} - {member.get('mobile', '')}")

        allowed, reason = self.store.can_member_attend(member, date.today())
        remaining = float(member.get("current_remaining", 0) or 0)
        self.attendance_label.setText(f"الحالة اليوم: {reason}")
        if remaining > 0:
            self.info_label.setText(f"تم التعرف على {member.get('name', '')} وعليه متبقي، سيتم فتح دفع المتبقي.")
            self.switch_mode(2)
            self.remaining_page.select_member(str(member.get("member_id", "")))
            return

        self.info_label.setText(f"تم التعرف على {member.get('name', '')} بدون متبقي، سيتم فتح صفحة التجديد.")
        self.switch_mode(1)
        self.renew_page.select_member(str(member.get("member_id", "")))
        self.renew_page.name.setText(str(member.get("name", "")))
        self.renew_page.mobile.setText(str(member.get("mobile", "")))
        self.renew_page.gender.setCurrentIndex(1 if str(member.get("gender", "male")) == "female" else 0)
        self.renew_page.load_selected_member()

    def _looks_like_mobile(self, value: str) -> bool:
        digits = re.sub(r"\D+", "", value or "")
        return len(digits) >= 7

    def switch_mode(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.current_mode = "new_subscription"
        elif index == 1:
            self.current_mode = "renewal"
        else:
            self.current_mode = "remaining"

    def reset_after_save(self) -> None:
        self.query_input.clear()
        self.info_label.setText("اكتب اسم العضو أو الموبايل وسيتم تحديد العملية تلقائيًا.")
        self.attendance_label.clear()
        self.new_page.clear_form()
        self.renew_page.clear_form()
        self.remaining_page.clear_form()
        self.switch_mode(0)

    def handle_save_complete(self) -> None:
        self.reset_after_save()
        self.save_callback()

    def refresh(self) -> None:
        self.query_completer_model.setStringList(self.build_suggestions())
        for page in (self.new_page, self.renew_page, self.remaining_page):
            if hasattr(page, "refresh"):
                page.refresh()  # type: ignore[attr-defined]
        self.resolve_member()


class DashboardPage(BasePage):
    def __init__(
        self,
        store: Store,
        open_new_callback,
        open_renew_callback,
        open_smart_callback,
        open_remaining_callback,
        open_expense_callback,
        quick_search_callback,
        open_remaining_members_callback,
        open_expired_members_callback,
        open_unified_callback: Optional[Callable[[], None]] = None,
        max_width: Optional[int] = None,
    ) -> None:
        super().__init__(store,title="", max_width=max_width)
        self.open_new_callback = open_new_callback
        self.open_renew_callback = open_renew_callback
        self.open_smart_callback = open_smart_callback
        self.open_remaining_callback = open_remaining_callback
        self.open_expense_callback = open_expense_callback
        self.quick_search_callback = quick_search_callback
        self.open_remaining_members_callback = open_remaining_members_callback
        self.open_expired_members_callback = open_expired_members_callback
        self.open_unified_callback = open_unified_callback

        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setObjectName("dashboardLogo")
        lp = logo_path()
        if lp:
            pix = QPixmap(str(lp))
            if not pix.isNull():
                logo.setPixmap(pix.scaled(QSize(280, 120), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if logo.pixmap() is None:
            logo.setText("HULK GYM")
            logo.setObjectName("logoText")
        self.root.addWidget(logo)

        search_row = QHBoxLayout()
        search_row.setDirection(QBoxLayout.Direction.RightToLeft)
        search_row.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText("ابحث بالاسم أو الموبايل أو نوع الاشتراك...")
        self.search.setFont(QFont("Segoe UI", 11))
        self.search.setFixedHeight(38)
        self.search.returnPressed.connect(self._run_quick_search)
        self.search_suggestions_model = QStringListModel(self._build_suggestions())
        self.search_completer = QCompleter(self.search_suggestions_model, self)
        self.search_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.search_completer.setFilterMode(Qt.MatchContains)
        self.search_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.search.setCompleter(self.search_completer)
        search_btn = QPushButton("بحث")
        search_btn.setObjectName("secondaryButton")
        search_btn.clicked.connect(self._run_quick_search)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(search_btn)
        self.root.addLayout(search_row)

        actions = QGridLayout()
        actions.setHorizontalSpacing(18)
        actions.setVerticalSpacing(18)
        actions.setColumnStretch(0, 1)
        actions.setColumnStretch(1, 1)
        actions.setRowStretch(0, 1)
        actions.setRowStretch(1, 1)
        smart_btn = QPushButton("سجل / جدد / دفع المتبقي")
        smart_btn.setObjectName("dashboardActionButton")
        smart_btn.clicked.connect(self._open_unified_entry)
        expense_btn = QPushButton("إضافة مصروف")
        expense_btn.setObjectName("dashboardActionButton")
        expense_btn.clicked.connect(self.open_expense_callback)
        actions.addWidget(smart_btn, 0, 0, 1, 2)
        actions.addWidget(expense_btn, 1, 0, 1, 2)
        self.root.addLayout(actions)

        quick_actions = QHBoxLayout()
        quick_actions.setDirection(QBoxLayout.Direction.RightToLeft)
        quick_actions.setSpacing(14)
        remaining_list_btn = QPushButton("عليهم متبقي")
        remaining_list_btn.setObjectName("dashboardActionButton")
        remaining_list_btn.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF9F00, stop:1 #FF5E00); color: #071006;")
        remaining_list_btn.clicked.connect(self.open_remaining_members_callback)
        expired_list_btn = QPushButton("انتهت اشتراكات")
        expired_list_btn.setObjectName("dashboardActionButton")
        expired_list_btn.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #D64550, stop:1 #A11D1F); color: #FFFFFF;")
        expired_list_btn.clicked.connect(self.open_expired_members_callback)
        quick_actions.addWidget(expired_list_btn)
        quick_actions.addWidget(remaining_list_btn)
        self.root.addLayout(quick_actions)

        self.root.addStretch(1)
        self.refresh()

    def _open_unified_entry(self) -> None:
        if self.open_unified_callback is not None:
            self.open_unified_callback()
            return
        self.open_smart_callback()

    def _build_suggestions(self) -> List[str]:
        suggestions: List[str] = []
        for member in self.store.members:
            name = str(member.get("name", "")).strip()
            mobile = str(member.get("mobile", "")).strip()
            if name and mobile:
                suggestions.append(f"{name} - {mobile}")
            elif name:
                suggestions.append(name)
            elif mobile:
                suggestions.append(mobile)
        return list(dict.fromkeys(suggestions))

    def _run_quick_search(self) -> None:
        query = self.search.text().strip() if hasattr(self, "search") else ""
        if self.quick_search_callback is not None:
            self.quick_search_callback(query)
        if hasattr(self, "search"):
            self.search.clear()

    def refresh(self) -> None:
        self.search_suggestions_model.setStringList(self._build_suggestions())


class SettingsPage(BasePage):
    def __init__(self, store: Store) -> None:
        super().__init__(store, "الإعدادات", "كل تعديل في الإعدادات يحتاج إدخال كلمة السر الحالية أولًا")

        self.unlock_duration_seconds = 60
        self.unlock_warning_seconds = 10
        self.unlock_session_id = 0
        self.unlock_expires_at: Optional[datetime] = None
        self.google_sync_thread: Optional[GoogleContactsSyncThread] = None
        self.google_sync_progress_dialog: Optional[QProgressDialog] = None

        self.scroll = QScrollArea()
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setLayoutDirection(Qt.LeftToRight)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        try:
            QScroller.grabGesture(self.scroll.viewport(), QScroller.LeftMouseButtonGesture)
        except Exception:
            pass

        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 14, 24)
        self.scroll_layout.setSpacing(16)
        self.scroll.setWidget(self.scroll_content)
        self.root.addWidget(self.scroll, 1)

        self.scroll_layout.addWidget(make_label(f"مسار ملفات JSON: {DATA_DIR}", "smallMuted"))
        self.scroll_layout.addWidget(make_label("كلمة سر الإيرادات في الرئيسية", "sectionTitle"))
        self.password_unlocked = False
        self.password_visible = False

        password_box = QFrame()
        password_box.setObjectName("settingsBox")
        password_layout = QGridLayout(password_box)
        password_layout.setContentsMargins(14, 14, 14, 14)
        password_layout.setHorizontalSpacing(10)
        password_layout.setVerticalSpacing(10)

        self.old_password = QLineEdit()
        self.old_password.setEchoMode(QLineEdit.Password)
        self.old_password.setPlaceholderText("كلمة السر الحالية")
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.new_password.setPlaceholderText("كلمة السر الجديدة")
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.Password)
        self.confirm_password.setPlaceholderText("تأكيد كلمة السر الجديدة")

        self.unlock_password_btn = QPushButton("فتح تعديل الإعدادات")
        self.unlock_password_btn.setObjectName("secondaryButton")
        self.unlock_password_btn.clicked.connect(self.unlock_password_change)
        self.toggle_password_btn = QPushButton("إظهار")
        self.toggle_password_btn.setObjectName("secondaryButton")
        self.toggle_password_btn.clicked.connect(self.toggle_password_visibility)
        self.password_status = make_label("الإعدادات مقفولة. اكتب كلمة السر الحالية أولًا حتى تقدر تعدّل أي حاجة.", "smallMuted")

        password_layout.addWidget(make_label("الحالية", "fieldLabel"), 0, 1)
        password_layout.addWidget(self.old_password, 0, 0)
        password_layout.addWidget(make_label("الجديدة", "fieldLabel"), 1, 1)
        password_layout.addWidget(self.new_password, 1, 0)
        password_layout.addWidget(make_label("تأكيد الجديدة", "fieldLabel"), 2, 1)
        password_layout.addWidget(self.confirm_password, 2, 0)
        password_actions = QHBoxLayout()
        password_actions.setDirection(QBoxLayout.Direction.RightToLeft)
        password_actions.addWidget(self.unlock_password_btn)
        password_actions.addWidget(self.toggle_password_btn)
        password_actions.addStretch(1)
        password_layout.addLayout(password_actions, 3, 0, 1, 2)
        password_layout.addWidget(self.password_status, 4, 0, 1, 2)
        self.scroll_layout.addWidget(password_box)
        self.set_password_fields_enabled(False)

        self.scroll_layout.addWidget(make_label("إعدادات واتساب", "sectionTitle"))
        whatsapp_box = QFrame()
        whatsapp_box.setObjectName("settingsBox")
        whatsapp_layout = QGridLayout(whatsapp_box)
        whatsapp_layout.setContentsMargins(14, 14, 14, 14)
        whatsapp_layout.setHorizontalSpacing(10)
        whatsapp_layout.setVerticalSpacing(10)
        self.manager_mobile = QLineEdit()
        self.manager_mobile.setPlaceholderText("رقم موبايل المدير للتقرير اليومي")
        whatsapp_layout.addWidget(make_label("رقم المدير", "fieldLabel"), 0, 1)
        whatsapp_layout.addWidget(self.manager_mobile, 0, 0)

        self.daily_report_time = QLineEdit()
        self.daily_report_time.setPlaceholderText("01:00")
        self.daily_report_time.setMaxLength(5)
        whatsapp_layout.addWidget(make_label("وقت التقرير اليومي (24 ساعة)", "fieldLabel"), 1, 1)
        whatsapp_layout.addWidget(self.daily_report_time, 1, 0)

        self.whatsapp_enabled_toggle = QCheckBox("تشغيل واتساب")
        self.whatsapp_enabled_toggle.setCursor(Qt.PointingHandCursor)
        self.whatsapp_enabled_toggle.setStyleSheet(
            "QCheckBox::indicator { width: 40px; height: 20px; border-radius: 10px; }"
            "QCheckBox::indicator:unchecked { background: #d9534f; border: 1px solid #c9302c; }"
            "QCheckBox::indicator:checked { background: #5cb85c; border: 1px solid #4cae4c; }"
        )
        whatsapp_layout.addWidget(make_label("تشغيل/إيقاف واتساب", "fieldLabel"), 2, 1)
        whatsapp_layout.addWidget(self.whatsapp_enabled_toggle, 2, 0)

        self.whatsapp_send_mode = QComboBox()
        self.whatsapp_send_mode.addItem("كتابة حرف حرف", "typing")
        self.whatsapp_send_mode.addItem("نسخ ولصق", "paste")
        self.whatsapp_send_mode.setFixedHeight(28)
        whatsapp_layout.addWidget(make_label("طريقة إرسال الرسالة", "fieldLabel"), 3, 1)
        whatsapp_layout.addWidget(self.whatsapp_send_mode, 3, 0)

        self.whatsapp_letter_delay = QDoubleSpinBox()
        self.whatsapp_letter_delay.setRange(0.0, 0.5)
        self.whatsapp_letter_delay.setSingleStep(0.0005)
        self.whatsapp_letter_delay.setDecimals(4)
        self.whatsapp_letter_delay.setSuffix(" s")
        whatsapp_layout.addWidget(make_label("الفاصل بين الحروف", "fieldLabel"), 4, 1)
        whatsapp_layout.addWidget(self.whatsapp_letter_delay, 4, 0)

        self.expired_message_template = QTextEdit()
        self.expired_message_template.setObjectName("searchInput")
        self.expired_message_template.setPlaceholderText("اكتب هنا نص رسالة غير المشتركين. استخدم {name} و {end_date} في النص.")
        self.expired_message_template.setMinimumHeight(120)
        whatsapp_layout.addWidget(make_label("نص رسالة غير المشتركين", "fieldLabel"), 5, 1)
        whatsapp_layout.addWidget(self.expired_message_template, 5, 0)

        whatsapp_layout.addWidget(make_label("التقرير اليومي يتجهز تلقائيًا في الوقت المحدد ويروح لرقم المدير.", "smallMuted"), 6, 0, 1, 2)
        self.scroll_layout.addWidget(whatsapp_box)

        self.scroll_layout.addWidget(make_label("معايرة شريط البحث في واتساب", "sectionTitle"))
        calibration_box = QFrame()
        calibration_box.setObjectName("settingsBox")
        calibration_layout = QGridLayout(calibration_box)
        calibration_layout.setContentsMargins(14, 14, 14, 14)
        calibration_layout.setHorizontalSpacing(10)
        calibration_layout.setVerticalSpacing(10)

        self.search_bar_x = QSpinBox()
        self.search_bar_x.setMinimum(0)
        self.search_bar_x.setMaximum(9999)
        self.search_bar_x.setSuffix(" px")
        calibration_layout.addWidget(make_label("إحداثي X لشريط البحث", "fieldLabel"), 0, 1)
        calibration_layout.addWidget(self.search_bar_x, 0, 0)

        self.search_bar_y = QSpinBox()
        self.search_bar_y.setMinimum(0)
        self.search_bar_y.setMaximum(9999)
        self.search_bar_y.setSuffix(" px")
        calibration_layout.addWidget(make_label("إحداثي Y لشريط البحث", "fieldLabel"), 1, 1)
        calibration_layout.addWidget(self.search_bar_y, 1, 0)

        self.test_calibration_btn = QPushButton("اختبر المعايرة (انقر على شريط البحث خلال 3 ثواني)")
        self.test_calibration_btn.setObjectName("secondaryButton")
        self.test_calibration_btn.clicked.connect(self.test_calibration)
        calibration_layout.addWidget(self.test_calibration_btn, 2, 0, 1, 2)

        self.calibration_status = make_label("اضغط الزر للبدء بالمعايرة", "smallMuted")
        calibration_layout.addWidget(self.calibration_status, 3, 0, 1, 2)

        self.scroll_layout.addWidget(calibration_box)

        self.scroll_layout.addWidget(make_label("إعدادات جهاز البصمة (ESP)", "sectionTitle"))
        esp_box = QFrame()
        esp_box.setObjectName("settingsBox")
        esp_layout = QGridLayout(esp_box)
        esp_layout.setContentsMargins(14, 14, 14, 14)
        esp_layout.setHorizontalSpacing(10)
        esp_layout.setVerticalSpacing(10)

        self.esp_ip = QLineEdit()
        self.esp_ip.setPlaceholderText("192.168.1.254")
        esp_layout.addWidget(make_label("IP عنوان جهاز ESP", "fieldLabel"), 0, 1)
        esp_layout.addWidget(self.esp_ip, 0, 0)

        self.esp_port = QSpinBox()
        self.esp_port.setMinimum(1)
        self.esp_port.setMaximum(65535)
        self.esp_port.setValue(80)
        esp_layout.addWidget(make_label("Port رقم الاتصال", "fieldLabel"), 1, 1)
        esp_layout.addWidget(self.esp_port, 1, 0)

        self.esp_enabled_toggle = QCheckBox("تشغيل الاتصال ب ESP")
        self.esp_enabled_toggle.setCursor(Qt.PointingHandCursor)
        self.esp_enabled_toggle.setStyleSheet(
            "QCheckBox::indicator { width: 40px; height: 20px; border-radius: 10px; }"
            "QCheckBox::indicator:unchecked { background: #d9534f; border: 1px solid #c9302c; }"
            "QCheckBox::indicator:checked { background: #5cb85c; border: 1px solid #4cae4c; }"
        )
        esp_layout.addWidget(make_label("تشغيل/إيقاف ESP", "fieldLabel"), 2, 1)
        esp_layout.addWidget(self.esp_enabled_toggle, 2, 0)

        esp_layout.addWidget(make_label("جهاز ESP متصل على نفس الشبكة (WiFi)، ويتحكم بنظام البصمة والدخول.", "smallMuted"), 3, 0, 1, 2)
        self.scroll_layout.addWidget(esp_box)

        self.scroll_layout.addWidget(make_label("بنك رسائل الواتساب (50 رسالة لكل مجموعة)", "sectionTitle"))
        message_bank_box = QFrame()
        message_bank_box.setObjectName("settingsBox")
        message_bank_layout = QVBoxLayout(message_bank_box)
        message_bank_layout.setContentsMargins(14, 14, 14, 14)
        message_bank_layout.setSpacing(10)

        self.message_bank_tabs = QTabWidget()
        self.message_bank_topics = {"general": QTextEdit(), "reminder_1": QTextEdit(), "reminder_3": QTextEdit(), "receipt": QTextEdit(), "expired": QTextEdit()}
        
        topic_placeholders = {
            "general": "المتاحة: {name}",
            "reminder_1": "المتاحة: {name}, {end_date}",
            "reminder_3": "المتاحة: {name}, {end_date}",
            "receipt": "المتاحة: {name}, {date}, {amount_paid}, {remaining_amount}",
            "expired": "المتاحة: {name}, {end_date}"
        }
        
        for topic, text_edit in self.message_bank_topics.items():
            text_edit.setObjectName("searchInput")
            placeholder_hint = topic_placeholders.get(topic, "")
            text_edit.setPlaceholderText(f"رسائل {topic} - افصل كل رسالة بـ ==\n{placeholder_hint}")
            text_edit.setMinimumHeight(200)
            self.message_bank_tabs.addTab(text_edit, topic)

        message_bank_layout.addWidget(self.message_bank_tabs)
        
        self.update_message_bank_btn = QPushButton("تحديث رسائل الواتساب")
        self.update_message_bank_btn.setObjectName("primaryButton")
        self.update_message_bank_btn.clicked.connect(self.update_message_bank)
        message_bank_layout.addWidget(self.update_message_bank_btn)

        message_bank_help = "اقسم كل رسالة باستخدام == بين الرسائل. يمكنك استخدام المتغيرات المتاحة لتخصيص الرسائل (مثال: أهلاً {name}، رصيدك {remaining_amount} ريال)"
        message_bank_layout.addWidget(make_label(message_bank_help, "smallMuted"))
        self.scroll_layout.addWidget(message_bank_box)

        self.scroll_layout.addWidget(make_label("خطط الاشتراك", "sectionTitle"))
        self.plans_table = QTableWidget()
        self.plans_table.setColumnCount(5)
        self.plans_table.setHorizontalHeaderLabels(["اسم الاشتراك", "السعر", "المدة بالأيام", "النظام", "حذف"])
        configure_table(self.plans_table)
        self.plans_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed)
        self.plans_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.plans_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.plans_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.plans_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.plans_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.plans_table.setMinimumHeight(320)
        self.plans_table.setMaximumHeight(430)
        self.scroll_layout.addWidget(self.plans_table)

        actions = QHBoxLayout()
        actions.setDirection(QBoxLayout.Direction.RightToLeft)
        self.save_settings_btn = QPushButton("حفظ الإعدادات")
        self.save_settings_btn.setObjectName("primaryButton")
        self.save_settings_btn.clicked.connect(self.save)
        self.sync_contacts_btn = QPushButton("مزامنة الأرقام مع Google")
        self.sync_contacts_btn.setObjectName("secondaryButton")
        self.sync_contacts_btn.clicked.connect(self.sync_all_google_contacts)
        self.force_sync_contacts_btn = QPushButton("مزامنة إجبارية لكل الأرقام")
        self.force_sync_contacts_btn.setObjectName("secondaryButton")
        self.force_sync_contacts_btn.clicked.connect(self.force_sync_all_google_contacts)
        self.add_plan_btn = QPushButton("+ إضافة خطة")
        self.add_plan_btn.setObjectName("secondaryButton")
        self.add_plan_btn.clicked.connect(self.add_plan_row)
        self.delete_selected_btn = QPushButton("حذف الخطة المحددة")
        self.delete_selected_btn.setObjectName("dangerButton")
        self.delete_selected_btn.clicked.connect(self.delete_selected_plan)
        actions.addWidget(self.save_settings_btn)
        actions.addWidget(self.sync_contacts_btn)
        actions.addWidget(self.force_sync_contacts_btn)
        actions.addWidget(self.add_plan_btn)
        actions.addWidget(self.delete_selected_btn)
        actions.addStretch(1)
        self.scroll_layout.addLayout(actions)

        self.scroll_layout.addWidget(make_label("طرق الدفع", "sectionTitle"))
        self.methods = QLineEdit()
        self.methods.setObjectName("searchInput")
        self.methods.setPlaceholderText("مثال: نقدي، انستاباي، فودافون كاش، تحويل بنكي")
        self.scroll_layout.addWidget(self.methods)

        self.scroll_layout.addWidget(make_label("فئات المصروفات", "sectionTitle"))
        self.expense_categories = QLineEdit()
        self.expense_categories.setObjectName("searchInput")
        self.expense_categories.setPlaceholderText("مثال: إيجار، معدات، فاتورة كهرباء")
        self.scroll_layout.addWidget(self.expense_categories)

        self.scroll_layout.addStretch(1)
        self.refresh()

    def set_password_fields_enabled(self, enabled: bool) -> None:
        self.new_password.setEnabled(enabled)
        self.confirm_password.setEnabled(enabled)
        if not enabled:
            self.new_password.clear()
            self.confirm_password.clear()

    def set_settings_controls_enabled(self, enabled: bool) -> None:
        for attr in ("manager_mobile", "daily_report_time", "whatsapp_enabled_toggle", "whatsapp_send_mode", "whatsapp_letter_delay", "message_bank_tabs", "update_message_bank_btn", "plans_table", "methods", "expense_categories", "save_settings_btn", "sync_contacts_btn", "force_sync_contacts_btn", "add_plan_btn", "delete_selected_btn", "search_bar_x", "search_bar_y", "test_calibration_btn", "esp_ip", "esp_port", "esp_enabled_toggle"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(enabled)
        if hasattr(self, "message_bank_topics"):
            for text_edit in self.message_bank_topics.values():
                text_edit.setEnabled(enabled)
        if hasattr(self, "plans_table"):
            for r in range(self.plans_table.rowCount()):
                btn = self.plans_table.cellWidget(r, 4)
                if btn is not None:
                    btn.setEnabled(enabled)

    def unlock_password_change(self) -> None:
        current = str(self.store.settings.get("dashboard_password", "1234"))
        if self.old_password.text() != current:
            QMessageBox.warning(self, "خطأ", "كلمة السر الحالية غير صحيحة.")
            return
        self.password_unlocked = True
        self.unlock_expires_at = datetime.now() + timedelta(seconds=self.unlock_duration_seconds)
        self.unlock_session_id += 1
        current_session = self.unlock_session_id

        self.set_password_fields_enabled(True)
        self.set_settings_controls_enabled(True)
        self.unlock_password_btn.setText("الإعدادات مفتوحة")
        self.password_status.setText(
            f"تم فتح الإعدادات لمدة {self.unlock_duration_seconds} ثانية. سيتم القفل تلقائيًا بعد انتهاء المدة."
        )

        warn_after = max(0, self.unlock_duration_seconds - self.unlock_warning_seconds)
        if warn_after > 0:
            QTimer.singleShot(
                warn_after * 1000,
                lambda sid=current_session: self._warn_before_auto_lock(sid),
            )
        QTimer.singleShot(
            self.unlock_duration_seconds * 1000,
            lambda sid=current_session: self._auto_lock_if_due(sid),
        )

        if hasattr(self, "manager_mobile"):
            self.manager_mobile.setFocus()

    def _warn_before_auto_lock(self, session_id: int) -> None:
        if session_id != self.unlock_session_id or not self.password_unlocked:
            return
        remaining = self._remaining_unlock_seconds()
        if remaining <= 0:
            return
        QMessageBox.information(
            self,
            "تنبيه",
            f"سيتم قفل التعديلات تلقائيًا خلال {remaining} ثانية.",
        )

    def _auto_lock_if_due(self, session_id: int) -> None:
        if session_id != self.unlock_session_id:
            return
        if not self.password_unlocked:
            return
        self._lock_settings(show_popup=True)

    def _remaining_unlock_seconds(self) -> int:
        if self.unlock_expires_at is None:
            return 0
        delta = int((self.unlock_expires_at - datetime.now()).total_seconds())
        return max(delta, 0)

    def _lock_settings(self, show_popup: bool = False) -> None:
        self.password_unlocked = False
        self.unlock_expires_at = None
        self.set_password_fields_enabled(False)
        self.set_settings_controls_enabled(False)
        self.unlock_password_btn.setText("فتح تعديل الإعدادات")
        self.password_status.setText("الإعدادات مقفولة. اكتب كلمة السر الحالية أولًا حتى تقدر تعدّل أي حاجة.")
        if show_popup:
            QMessageBox.information(self, "تم", "انتهت مدة فتح التعديلات وتم قفل الإعدادات تلقائيًا.")

    def toggle_password_visibility(self) -> None:
        self.password_visible = not self.password_visible
        mode = QLineEdit.Normal if self.password_visible else QLineEdit.Password
        self.old_password.setEchoMode(mode)
        self.new_password.setEchoMode(mode)
        self.confirm_password.setEchoMode(mode)
        self.toggle_password_btn.setText("إخفاء" if self.password_visible else "إظهار")

    def make_delete_button(self) -> QPushButton:
        btn = QPushButton("حذف")
        btn.setObjectName("dangerButtonSmall")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumWidth(86)
        btn.setMinimumHeight(28)
        btn.setEnabled(bool(getattr(self, "password_unlocked", False)))
        btn.clicked.connect(self.delete_plan_from_button)
        return btn

    def add_plan_row(self) -> None:
        r = self.plans_table.rowCount()
        self.plans_table.insertRow(r)
        self.plans_table.setItem(r, 0, item("اشتراك جديد"))
        self.plans_table.setItem(r, 1, item("0"))
        self.plans_table.setItem(r, 2, item("30"))
        self.plans_table.setItem(r, 3, item("كل يوم"))
        self.plans_table.setCellWidget(r, 4, self.make_delete_button())
        self.plans_table.setRowHeight(r, 50)
        self.plans_table.scrollToBottom()

    def delete_selected_plan(self) -> None:
        row = self.plans_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "تنبيه", "اختار الخطة الأول من الجدول.")
            return
        self.delete_plan_row(row)

    def delete_plan_from_button(self) -> None:
        button = self.sender()
        for r in range(self.plans_table.rowCount()):
            if self.plans_table.cellWidget(r, 4) is button:
                self.delete_plan_row(r)
                return

    def delete_plan_row(self, row: int) -> None:
        if self.plans_table.rowCount() <= 1:
            QMessageBox.warning(self, "تنبيه", "لازم تسيب خطة اشتراك واحدة على الأقل.")
            return
        name_item = self.plans_table.item(row, 0)
        name = name_item.text() if name_item else "الخطة"
        ok = QMessageBox.question(self, "تأكيد الحذف", f"تحذف خطة: {name} ؟", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ok == QMessageBox.Yes:
            self.plans_table.removeRow(row)

    def refresh(self) -> None:
        keep_unlocked = self.password_unlocked and self._remaining_unlock_seconds() > 0
        self.password_visible = False
        self.old_password.clear()
        self.new_password.clear()
        self.confirm_password.clear()
        self.old_password.setEchoMode(QLineEdit.Password)
        self.new_password.setEchoMode(QLineEdit.Password)
        self.confirm_password.setEchoMode(QLineEdit.Password)
        self.toggle_password_btn.setText("إظهار")
        if keep_unlocked:
            self.set_password_fields_enabled(True)
            self.set_settings_controls_enabled(True)
            self.unlock_password_btn.setText("الإعدادات مفتوحة")
            self.password_status.setText(
                f"الإعدادات مفتوحة الآن. الوقت المتبقي قبل القفل التلقائي: {self._remaining_unlock_seconds()} ثانية."
            )
        else:
            self._lock_settings(show_popup=False)
        if hasattr(self, "manager_mobile"):
            self.manager_mobile.setText(str(self.store.settings.get("manager_mobile", "")))
        if hasattr(self, "daily_report_time"):
            self.daily_report_time.setText(str(self.store.settings.get("daily_report_time", "01:00")))
        if hasattr(self, "whatsapp_enabled_toggle"):
            self.whatsapp_enabled_toggle.setChecked(bool(self.store.settings.get("whatsapp_enabled", True)))
        if hasattr(self, "whatsapp_send_mode"):
            mode_value = str(self.store.settings.get("whatsapp_send_mode", "typing")).strip().lower()
            for idx in range(self.whatsapp_send_mode.count()):
                if self.whatsapp_send_mode.itemData(idx) == mode_value:
                    self.whatsapp_send_mode.setCurrentIndex(idx)
                    break
        if hasattr(self, "whatsapp_letter_delay"):
            self.whatsapp_letter_delay.setValue(float(self.store.settings.get("whatsapp_letter_delay", 0.02) or 0.02))
        if hasattr(self, "expired_message_template"):
            self.expired_message_template.setPlainText(str(self.store.settings.get("expired_message_template", "")))
        if hasattr(self, "message_bank_topics"):
            message_bank = load_whatsapp_message_bank()
            for topic, text_edit in self.message_bank_topics.items():
                messages = message_bank.get(topic, [])
                text_edit.setPlainText(join_message_bank_entries(messages))
        plans = self.store.settings.get("plans", [])
        self.plans_table.setRowCount(len(plans))
        for r, p in enumerate(plans):
            self.plans_table.setItem(r, 0, item(p.get("name", "")))
            self.plans_table.setItem(r, 1, item(p.get("price", 0)))
            self.plans_table.setItem(r, 2, item(p.get("duration_days", 0)))
            self.plans_table.setItem(r, 3, item(p.get("frequency", "كل يوم")))
            self.plans_table.setCellWidget(r, 4, self.make_delete_button())
            self.plans_table.setRowHeight(r, 50)
        self.methods.setText("، ".join(self.store.settings.get("payment_methods", [])))
        self.expense_categories.setText("، ".join(self.store.settings.get("expense_categories", [])))
        if hasattr(self, "search_bar_x"):
            self.search_bar_x.setValue(int(self.store.settings.get("search_bar_x", 0)))
        if hasattr(self, "search_bar_y"):
            self.search_bar_y.setValue(int(self.store.settings.get("search_bar_y", 0)))
        if hasattr(self, "calibration_status") and (self.search_bar_x.value() or self.search_bar_y.value()):
            self.calibration_status.setText(f"✓ المعايرة محفوظة: X={self.search_bar_x.value()}, Y={self.search_bar_y.value()}")
        if hasattr(self, "esp_ip"):
            self.esp_ip.setText(str(self.store.settings.get("esp_ip", "192.168.1.254")))
        if hasattr(self, "esp_port"):
            self.esp_port.setValue(int(self.store.settings.get("esp_port", 80)))
        if hasattr(self, "esp_enabled_toggle"):
            self.esp_enabled_toggle.setChecked(bool(self.store.settings.get("esp_enabled", False)))
        if keep_unlocked:
            self.set_settings_controls_enabled(True)
        else:
            self.set_settings_controls_enabled(False)

    def save(self) -> None:
        if not self.password_unlocked:
            QMessageBox.warning(self, "تنبيه", "لا يمكن تعديل الإعدادات إلا بعد إدخال كلمة السر الحالية والضغط على فتح تعديل الإعدادات.")
            return
        plans: List[Dict[str, Any]] = []
        for r in range(self.plans_table.rowCount()):
            name_it = self.plans_table.item(r, 0)
            price_it = self.plans_table.item(r, 1)
            days_it = self.plans_table.item(r, 2)
            freq_it = self.plans_table.item(r, 3)
            name = name_it.text().strip() if name_it else ""
            if not name:
                continue
            try:
                price = float(price_it.text().replace(",", "")) if price_it else 0
                days = int(float(days_it.text())) if days_it else 30
            except Exception:
                QMessageBox.warning(self, "تنبيه", "تأكد من أن السعر والمدة أرقام صحيحة.")
                return
            frequency = freq_it.text().strip() if freq_it else ("يوم ويوم" if "يوم ويوم" in name else "كل يوم")
            months = 12 if "سنوي" in name or days >= 360 else 3 if "3" in name or days >= 80 else 1
            plans.append({"name": name, "price": price, "duration_days": days, "months": months, "frequency": frequency})
        methods = [m.strip() for m in re.split(r"[,،]", self.methods.text()) if m.strip()]
        expense_categories = [c.strip() for c in re.split(r"[,،]", self.expense_categories.text()) if c.strip()]
        if not plans:
            QMessageBox.warning(self, "تنبيه", "لازم تضيف خطة اشتراك واحدة على الأقل.")
            return
        if self.password_unlocked:
            new_password = self.new_password.text().strip()
            confirm_password = self.confirm_password.text().strip()
            if new_password or confirm_password:
                if len(new_password) < 3:
                    QMessageBox.warning(self, "تنبيه", "كلمة السر الجديدة لازم تكون 3 حروف/أرقام على الأقل.")
                    return
                if new_password != confirm_password:
                    QMessageBox.warning(self, "تنبيه", "تأكيد كلمة السر الجديدة غير مطابق.")
                    return
                self.store.settings["dashboard_password"] = new_password
        self.store.settings["plans"] = plans
        self.store.settings["payment_methods"] = methods or ["نقدي"]
        if hasattr(self, "manager_mobile"):
            self.store.settings["manager_mobile"] = normalize_mobile(self.manager_mobile.text())
        if hasattr(self, "daily_report_time"):
            report_time = normalize_clock_time(self.daily_report_time.text())
            if not report_time:
                QMessageBox.warning(self, "تنبيه", "وقت التقرير غير صحيح. اكتب الوقت بصيغة HH:MM مثل 01:00 أو 13:30 (ويمكن كتابة 9:30).")
                return
            self.store.settings["daily_report_time"] = report_time
        if hasattr(self, "whatsapp_enabled_toggle"):
            self.store.settings["whatsapp_enabled"] = bool(self.whatsapp_enabled_toggle.isChecked())
        if hasattr(self, "whatsapp_send_mode"):
            self.store.settings["whatsapp_send_mode"] = str(self.whatsapp_send_mode.currentData() or "typing")
        if hasattr(self, "whatsapp_letter_delay"):
            self.store.settings["whatsapp_letter_delay"] = max(0.0, float(self.whatsapp_letter_delay.value()))
        if hasattr(self, "expired_message_template"):
            self.store.settings["expired_message_template"] = self.expired_message_template.toPlainText().strip()
        if hasattr(self, "search_bar_x"):
            self.store.settings["search_bar_x"] = int(self.search_bar_x.value())
        if hasattr(self, "search_bar_y"):
            self.store.settings["search_bar_y"] = int(self.search_bar_y.value())
        if hasattr(self, "esp_ip"):
            esp_ip = self.esp_ip.text().strip() or "192.168.1.254"
            self.store.settings["esp_ip"] = esp_ip
        if hasattr(self, "esp_port"):
            self.store.settings["esp_port"] = int(self.esp_port.value())
        if hasattr(self, "esp_enabled_toggle"):
            self.store.settings["esp_enabled"] = bool(self.esp_enabled_toggle.isChecked())
        self.store.save_settings()
        QMessageBox.information(self, "تم", "تم حفظ الإعدادات بنجاح.")
        self.refresh()

    def update_message_bank(self) -> None:
        """Save the updated message bank from the tabs to JSON file."""
        if not self.password_unlocked:
            QMessageBox.warning(self, "تنبيه", "افتح الإعدادات أولًا قبل تحديث رسائل الواتساب.")
            return

        message_bank: Dict[str, List[str]] = {}
        for topic, text_edit in self.message_bank_topics.items():
            messages = split_message_bank_entries(text_edit.toPlainText())
            message_bank[topic] = messages

        if not message_bank or not any(message_bank.values()):
            QMessageBox.warning(self, "تنبيه", "لا توجد رسائل لحفظها. أضف رسائل في الأقل في مجموعة واحدة.")
            return

        success = self.store.save_whatsapp_message_bank(message_bank)
        if success:
            QMessageBox.information(
                self,
                "تم",
                f"تم حفظ {sum(len(msgs) for msgs in message_bank.values())} رسالة في {len(message_bank)} مجموعة.",
            )
            self.refresh()
        else:
            QMessageBox.critical(self, "خطأ", "حدث خطأ أثناء حفظ رسائل الواتساب. تأكد من صلاحيات الملفات.")

    def test_calibration(self) -> None:
        """Test WhatsApp search bar calibration by recording mouse click position."""
        if not self.password_unlocked:
            QMessageBox.warning(self, "تنبيه", "افتح الإعدادات أولًا قبل معايرة شريط البحث.")
            return
        
        reply = QMessageBox.information(
            self,
            "معايرة شريط البحث",
            "سيتم تسجيل موقع الماوس عند النقر عليه.\n\nانقر على شريط البحث في واتساب خلال 3 ثوانٍ...",
            QMessageBox.Ok,
            QMessageBox.Ok
        )
        
        # Disable the button during calibration
        self.test_calibration_btn.setEnabled(False)
        self.calibration_status.setText("⏱ جاري انتظار النقرة... (3 ثواني)")
        
        # Import mouse position tracking
        try:
            import pyautogui
            import time
            
            # Set a timeout for waiting
            start_time = time.time()
            timeout = 3
            last_pos = pyautogui.position()
            
            while time.time() - start_time < timeout:
                current_pos = pyautogui.position()
                # Check if mouse moved significantly (click detected by position change or listener)
                time.sleep(0.1)
            
            # For simplicity, just prompt user to enter coordinates manually or use current mouse position
            current_pos = pyautogui.position()
            self.search_bar_x.setValue(current_pos[0])
            self.search_bar_y.setValue(current_pos[1])
            self.calibration_status.setText(f"✓ تم التقاط: X={current_pos[0]}, Y={current_pos[1]}")
            
            QMessageBox.information(
                self,
                "تم",
                f"تم تسجيل إحداثيات شريط البحث:\nX: {current_pos[0]}\nY: {current_pos[1]}\n\nأنقر حفظ الإعدادات لحفظ هذه المعايرة."
            )
        except ImportError:
            QMessageBox.critical(self, "خطأ", "لم يتم العثور على مكتبة pyautogui. تأكد من تثبيتها.")
        except Exception as e:
            QMessageBox.critical(self, "خطأ", f"حدث خطأ أثناء المعايرة: {str(e)}")
        finally:
            self.test_calibration_btn.setEnabled(True)


    def sync_all_google_contacts(self) -> None:
        if not self.password_unlocked:
            QMessageBox.warning(self, "تنبيه", "افتح الإعدادات أولًا قبل مزامنة الأرقام.")
            return
        if self.google_sync_thread is not None and self.google_sync_thread.isRunning():
            QMessageBox.information(self, "تنبيه", "مزامنة Google شغالة بالفعل، انتظر حتى تنتهي.")
            return
        if not self.store.members:
            QMessageBox.information(self, "تم", "لا توجد أعضاء لمزامنتهم.")
            return
        total_members = len(self.store.members)
        reply = QMessageBox.question(
            self,
            "تأكيد المزامنة",
            f"هل تريد مزامنة {total_members} رقمًا مع Google Contacts؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        self._start_google_contacts_sync(force=False, total_members=total_members)

    def force_sync_all_google_contacts(self) -> None:
        if not self.password_unlocked:
            QMessageBox.warning(self, "تنبيه", "افتح الإعدادات أولًا قبل المزامنة الإجبارية.")
            return
        if self.google_sync_thread is not None and self.google_sync_thread.isRunning():
            QMessageBox.information(self, "تنبيه", "مزامنة Google شغالة بالفعل، انتظر حتى تنتهي.")
            return
        if not self.store.members:
            QMessageBox.information(self, "تم", "لا توجد أعضاء لمزامنتهم.")
            return
        total_members = len(self.store.members)
        reply = QMessageBox.question(
            self,
            "تأكيد المزامنة الإجبارية",
            f"سيتم محاولة رفع كل الأرقام ({total_members}) إلى Google Contacts حتى لو كانت متزامنة سابقًا.\nهل تريد المتابعة؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._start_google_contacts_sync(force=True, total_members=total_members)

    def _start_google_contacts_sync(self, force: bool, total_members: int) -> None:
        title = "جاري المزامنة الإجبارية" if force else "جاري مزامنة Google"
        initial_text = f"جاري رفع جهات الاتصال... 0/{total_members}"
        dialog = QProgressDialog(initial_text, "", 0, max(0, int(total_members)), self)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        dialog.show()
        self.google_sync_progress_dialog = dialog

        thread = GoogleContactsSyncThread(self.store, force=force, total_members=total_members)
        self.google_sync_thread = thread
        thread.progress.connect(self._on_google_sync_progress)
        thread.done.connect(self._on_google_sync_done)
        thread.finished.connect(self._on_google_sync_finished)
        thread.start()

    def _on_google_sync_progress(self, processed: int, synced: int, total: int) -> None:
        if self.google_sync_progress_dialog is None:
            return
        total = max(0, int(total))
        processed = max(0, min(int(processed), total))
        self.google_sync_progress_dialog.setMaximum(total)
        self.google_sync_progress_dialog.setValue(processed)
        self.google_sync_progress_dialog.setLabelText(f"جاري رفع جهات الاتصال... {synced}/{total}")

    def _on_google_sync_done(self, result: Dict[str, Any]) -> None:
        if self.google_sync_progress_dialog is not None:
            total = max(0, int(result.get("total_count", 0) or 0))
            self.google_sync_progress_dialog.setMaximum(total)
            self.google_sync_progress_dialog.setValue(total)
            self.google_sync_progress_dialog.close()
            self.google_sync_progress_dialog = None

        if not result.get("ok"):
            QMessageBox.warning(self, "خطأ", f"فشل مزامنة Google Contacts:\n{result.get('error', 'خطأ غير معروف')}")
            return

        total = int(result.get("total_count", 0) or 0)
        synced = int(result.get("synced_count", 0) or 0)
        queued_added = int(result.get("queued_added", 0) or 0)
        stats = result.get("stats") or {}
        no_phone = int(stats.get("no_phone_count", 0) or 0)
        duplicates = int(stats.get("duplicate_count", 0) or 0)
        already_synced = int(stats.get("already_synced_count", 0) or 0)
        quota_hit = bool(stats.get("quota_hit", False))
        remaining = int(stats.get("remaining_in_queue", 0) or 0)

        lines = []
        if result.get("force"):
            lines.append("نتائج المزامنة الإجبارية:")
        else:
            lines.append("نتائج مزامنة Google Contacts:")
        lines.append(f"• إجمالي الأعضاء في البرنامج: {total}")
        lines.append(f"• تمت المزامنة بنجاح: {synced}")
        if no_phone > 0:
            lines.append(f"• تم تخطي أعضاء بدون أرقام هواتف: {no_phone}")
        if duplicates > 0:
            lines.append(f"• تم تخطي أرقام مكررة: {duplicates}")
        if not result.get("force") and already_synced > 0:
            lines.append(f"• أرقام كانت متزامنة مسبقاً: {already_synced}")
        if quota_hit:
            lines.append("\n⚠️ تنبيه: تم الوصول للحد الأقصى المسموح به من Google (Rate Limit).")
            lines.append(f"تم حفظ باقي الأرقام ({remaining}) في قائمة الانتظار للمزامنة تلقائياً لاحقاً.")

        summary_text = "\n".join(lines)
        if synced > 0:
            QMessageBox.information(self, "تمت المزامنة", summary_text)
        else:
            QMessageBox.warning(self, "تنبيه المزامنة", summary_text)

    def _on_google_sync_finished(self) -> None:
        self.google_sync_thread = None


class AddSubscriptionDialog(QDialog):
    def __init__(self, store: Store, parent: Optional[QWidget] = None, mode: str = "new_subscription") -> None:
        super().__init__(parent)
        self.store = store
        self.mode = mode
        self.is_renewal = mode == "renewal"
        title_text = "تجديد اشتراك" if self.is_renewal else "تسجيل اشتراك جديد"
        self.setWindowTitle(title_text)
        self.setMinimumWidth(720)
        fit_dialog_to_screen(self, 900, 610)
        self.setLayoutDirection(Qt.RightToLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        layout, _scroll = create_dialog_shell(outer, max_width=860)

        layout.addWidget(make_label(title_text, "dialogTitle"))
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setColumnStretch(0, 1)
        form.setColumnMinimumWidth(1, 150)
        layout.addLayout(form)

        self.member_picker: Optional[QComboBox] = None
        if self.is_renewal:
            self.member_picker = QComboBox()
            self.member_picker.setEditable(True)
            self.member_picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            if self.member_picker.lineEdit():
                self.member_picker.lineEdit().setPlaceholderText("ابحث باسم المشترك أو الموبايل")
            for member in sorted(self.store.members, key=lambda m: str(m.get("name", ""))):
                text = f"{member.get('name', '')} - {member.get('mobile', '')} - {status_ar(str(member.get('current_status', '')))}"
                self.member_picker.addItem(text, member.get("member_id"))

        self.name = QLineEdit()
        self.name.setPlaceholderText("اسم المشترك")
        self.mobile = QLineEdit()
        self.mobile.setPlaceholderText("الموبايل")
        self.mobile.setMaxLength(13)
        self.mobile.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,13}"), self.mobile))
        self.gender = QComboBox()
        self.gender.addItem("ذكر", "male")
        self.gender.addItem("أنثى", "female")
        self.plan = QComboBox()
        for p in self.store.settings.get("plans", []):
            self.plan.addItem(str(p.get("name")), p)
        self.start = QDateEdit()
        self.start.setCalendarPopup(True)
        self.start.setDate(QDate.currentDate())
        self.start.setDisplayFormat(DISPLAY_DATE_FMT)
        self.paid = QDoubleSpinBox()
        self.paid.setRange(0, 1_000_000)
        self.paid.setDecimals(2)
        self.paid.setSingleStep(50)
        if self.store.settings.get("plans"):
            self.paid.setValue(float(self.store.settings["plans"][0].get("price", 0) or 0))
        self.allowance_days = QSpinBox()
        self.allowance_days.setRange(0, 365)
        self.allowance_days.setSingleStep(1)
        self.allowance_days.setValue(0)
        self.start_programmatic_change = False

        widgets = []
        if self.member_picker is not None:
            widgets.append(("اختار المشترك", self.member_picker))
        widgets.extend([
            ("الاسم", self.name),
            ("الموبايل", self.mobile),
            ("النوع", self.gender),
            ("نوع الاشتراك", self.plan),
            ("بداية الاشتراك" if not self.is_renewal else "بداية التجديد", self.start),
            ("المدفوع بالجنيه", self.paid),
            ("أيام السماح", self.allowance_days),
        ])
        for idx, (lbl, w) in enumerate(widgets):
            label = make_label(lbl, "fieldLabel")
            label.setMinimumWidth(140)
            form.addWidget(label, idx, 1)
            form.addWidget(w, idx, 0)

        if self.is_renewal:
            self.name.setReadOnly(True)
            self.mobile.setReadOnly(True)
            self.gender.setEnabled(False)
            if self.member_picker is not None:
                self.member_picker.currentIndexChanged.connect(self.load_selected_member)

        self.calc = make_label("", "calcBox")
        layout.addWidget(self.calc)
        layout.addStretch(1)

        self.save_button = add_fixed_dialog_actions(
            outer,
            "حفظ التجديد" if self.is_renewal else "حفظ الاشتراك",
            self.save,
            self.reject,
        )

        self.plan.currentIndexChanged.connect(self.update_plan_price)
        self.plan.currentIndexChanged.connect(self.update_calc)
        self.paid.valueChanged.connect(self.update_calc)
        self.allowance_days.valueChanged.connect(self.update_calc)
        self.start.dateChanged.connect(self.on_start_date_changed)
        if self.is_renewal:
            self.load_selected_member()
        self.update_calc()

    def on_start_date_changed(self, date: QDate) -> None:
        if self.start_programmatic_change:
            self.start_programmatic_change = False
            self.update_calc()
            return
        # Only prompt about adjusting allowance days when the new start date
        # is in the future (suspicious) and allowance days is zero. If the
        # user sets a past date (e.g., back-dating a subscription), do not
        # interrupt with confirmation dialogs.
        try:
            new_date = qdate_to_py(self.start.date())
            if int(self.allowance_days.value()) == 0 and new_date > date.today():
                answer = QMessageBox.question(
                    self,
                    "تأكيد تعديل التاريخ",
                    "لقد عدّلت تاريخ بداية الاشتراك يدويًا. هل تريد تعديل أيام السماح يدويًا؟\nاختر نعم لتعيين أيام السماح، أو لا للاستمرار بدون فترة سماح.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer == QMessageBox.Yes:
                    self.allowance_days.setFocus()
        except Exception:
            pass
        self.update_calc()

    def selected_member(self) -> Optional[Dict[str, Any]]:
        if not self.is_renewal or self.member_picker is None or self.member_picker.count() == 0:
            return None
        member_id = self.member_picker.currentData()
        return next((m for m in self.store.members if m.get("member_id") == member_id), None)

    def update_plan_price(self) -> None:
        data = self.plan.currentData()
        if isinstance(data, dict):
            self.paid.setValue(float(data.get("price", 0) or 0))

    def load_selected_member(self) -> None:
        member = self.selected_member()
        if not member:
            self.name.clear()
            self.mobile.clear()
            self.start_programmatic_change = True
            self.start.setDate(QDate.currentDate())
            self.update_calc()
            return
        self.name.setText(str(member.get("name", "")))
        self.mobile.setText(str(member.get("mobile", "")))
        self.gender.setCurrentIndex(1 if str(member.get("gender", "male")) == "female" else 0)
        suggested = self.store.suggested_renewal_start(member)
        self.start_programmatic_change = True
        self.start.setDate(qdate_from_date(suggested))
        self.update_calc()

    def update_calc(self) -> None:
        if self.is_renewal:
            member = self.selected_member()
            if member and float(member.get("current_remaining", 0) or 0) > 0:
                self.calc.setText(
                    f"لا يمكن تجديد الاشتراك لأن على المشترك متبقي {money(member.get('current_remaining', 0))}. استخدم زر دفع المتبقي الأول."
                )
                if hasattr(self, "save_button"):
                    self.save_button.setEnabled(False)
                return
        if hasattr(self, "save_button"):
            self.save_button.setEnabled(True)
        plan_name = self.plan.currentText()
        start = qdate_to_py(self.start.date())
        paid = float(self.paid.value())
        days_override = int(self.allowance_days.value())
        end, price, remaining, days = self.store.calculate_end(start, plan_name, paid, days_override)
        prefix = "تجديد" if self.is_renewal else "اشتراك جديد"
        note = "" if days_override == 0 else f" | أيام السماح: {days_override}"
        self.calc.setText(
            f"{prefix}  |  سعر الخطة: {money(price)}  |  الأيام المستحقة: {days} يوم  |  المتبقي: {money(remaining)}  |  نهاية الاشتراك: {display_date(end)}{note}"
        )

    def save(self) -> None:
        member = self.selected_member() if self.is_renewal else None
        if self.is_renewal and member is None:
            QMessageBox.warning(self, "تنبيه", "لا يوجد مشترك محدد للتجديد.")
            return
        name = str(member.get("name", "")).strip() if member else self.name.text().strip()
        mobile = str(member.get("mobile", "")).strip() if member else self.mobile.text().strip()
        gender = str(member.get("gender", "male")) if member else str(self.gender.currentData())
        if not name:
            QMessageBox.warning(self, "تنبيه", "اكتب اسم المشترك.")
            return
        if not normalize_mobile(mobile):
            QMessageBox.warning(self, "تنبيه", "اكتب رقم الموبايل.")
            return
        if qdate_to_py(self.start.date()) > date.today() and int(self.allowance_days.value()) <= 0:
            QMessageBox.warning(self, "تنبيه", "لأنت اخترت تاريخ بداية في المستقبل، اكتب أيام السماح أو عدّل التاريخ.")
            return
        if qdate_to_py(self.start.date()) > date.today() and int(self.allowance_days.value()) <= 0:
            QMessageBox.warning(self, "تنبيه", "لأنت اخترت تاريخ بداية في المستقبل، اكتب أيام السماح أو عدّل التاريخ.")
            return
        if self.plan.count() == 0:
            QMessageBox.warning(self, "تنبيه", "لا توجد خطط اشتراك في الإعدادات.")
            return
        if self.is_renewal and member and float(member.get("current_remaining", 0) or 0) > 0:
            QMessageBox.warning(self, "تنبيه", "لا يمكن تجديد الاشتراك قبل دفع المتبقي. استخدم زر دفع المتبقي الأول.")
            return
        try:
            payload = {
                "operation_type": "renewal" if self.is_renewal else "new_subscription",
                "name": name,
                "mobile": mobile,
                "gender": gender,
                "subscription_type": self.plan.currentText(),
                "subscription_start": date_to_str(qdate_to_py(self.start.date())),
                "paid_amount": self.paid.value(),
                "payment_method": str(self.store.settings.get("payment_methods", ["نقدي"])[0]),
            }
            if int(self.allowance_days.value()) > 0:
                payload["allowance_days"] = int(self.allowance_days.value())
            payment = self.store.add_payment(payload)
        except ValueError as exc:
            QMessageBox.warning(self, "تنبيه", str(exc))
            return
        saved_member = self.store.find_member_by_mobile(normalize_mobile(mobile))
        if saved_member and not str(saved_member.get("fingerprint_id", "")).strip():
            QTimer.singleShot(0, lambda m=saved_member: start_fingerprint_enrollment(self, self.store, m))
        QMessageBox.information(self, "تم", f"تم الحفظ بنجاح رقم {payment['invoice_no']}")
        self.accept()


class EditMemberDialog(QDialog):
    """Clean dialog for adding/editing members."""
    
    def __init__(self, store: Store, parent: Optional[QWidget] = None, member: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(parent)
        self.store = store
        self.member = member
        self.is_new = member is None
        debug_log(f"EditMemberDialog.__init__: is_new={self.is_new} member_id={member.get('member_id', '') if member else ''}")
        
        self.setWindowTitle("إضافة عضو جديد" if self.is_new else "تعديل بيانات العضو")
        self.setMinimumWidth(680)
        fit_dialog_to_screen(self, 800, 600)
        self.setLayoutDirection(Qt.RightToLeft)

        # Layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        layout, _scroll = create_dialog_shell(outer, max_width=760)
        layout.addWidget(make_label("إضافة عضو جديد" if self.is_new else "تعديل بيانات العضو", "dialogTitle"))

        form = QVBoxLayout()
        form.setSpacing(6)
        layout.addLayout(form)

        # Fields
        self.name = QLineEdit()
        self.name.setPlaceholderText("اسم العضو")
        self.mobile = QLineEdit()
        self.mobile.setPlaceholderText("الموبايل (أرقام فقط)")
        self.gender = QComboBox()
        self.gender.addItem("ذكر", "male")
        self.gender.addItem("أنثى", "female")

        # Last subscription fields (only for editing)
        self.subscription_type = QComboBox()
        self.subscription_type.addItem("بدون اشتراك", "")
        for plan in self.store.settings.get("plans", []):
            plan_name = str(plan.get("name", ""))
            if plan_name:
                self.subscription_type.addItem(plan_name, plan_name)
        
        self.subscription_start = QDateEdit()
        self.subscription_start.setCalendarPopup(True)
        self.subscription_start.setDisplayFormat(DISPLAY_DATE_FMT)
        self.subscription_start.setDate(qdate_from_date(date.today()))
        
        self.subscription_end = QDateEdit()
        self.subscription_end.setCalendarPopup(True)
        self.subscription_end.setDisplayFormat(DISPLAY_DATE_FMT)
        self.subscription_end.setDate(qdate_from_date(date.today()))

        self.current_paid = QDoubleSpinBox()
        self.current_paid.setRange(0, 1_000_000)
        self.current_paid.setDecimals(2)
        self.current_paid.setSingleStep(10)
        self.current_remaining = QDoubleSpinBox()
        self.current_remaining.setRange(0, 1_000_000)
        self.current_remaining.setDecimals(2)
        self.current_remaining.setSingleStep(10)

        self.end_manual_override = False
        self.suppress_end_change = False

        # Populate if editing
        if member:
            self.name.setText(str(member.get("name", "")))
            self.mobile.setText(str(member.get("mobile", "")))
            self.gender.setCurrentIndex(1 if str(member.get("gender", "male")) == "female" else 0)
            # Allow editing mobile numbers so admins can correct typos.
            # Previously this was locked; keep it editable now but rely on
            # uniqueness checks in save() to prevent duplicates.
            # self.mobile.setReadOnly(True)
            
            # Set subscription fields
            sub_type = str(member.get("last_subscription_type", ""))
            for i in range(self.subscription_type.count()):
                if self.subscription_type.itemData(i) == sub_type:
                    self.subscription_type.setCurrentIndex(i)
                    break
            
            sub_start = member.get("last_subscription_start", "")
            if sub_start:
                try:
                    self.subscription_start.setDate(qdate_from_str(sub_start))
                except:
                    pass
            
            sub_end = member.get("last_subscription_end", "")
            if sub_end:
                try:
                    self.subscription_end.setDate(qdate_from_str(sub_end))
                except:
                    pass

            self.current_paid.setValue(float(member.get("current_paid", 0) or 0))
            self.current_remaining.setValue(float(member.get("current_remaining", 0) or 0))

        # Row 1: Name & Mobile
        row1 = QHBoxLayout()
        row1.setDirection(QBoxLayout.Direction.RightToLeft)
        row1.setSpacing(10)
        for lbl, w in [("الاسم", self.name), ("الموبايل", self.mobile)]:
            field_container = QVBoxLayout()
            field_container.setSpacing(4)
            label = make_label(lbl, "fieldLabel")
            field_container.addWidget(label)
            field_container.addWidget(w)
            row1.addLayout(field_container, 1)
        form.addLayout(row1)

        # Row 2: Gender
        row2 = QHBoxLayout()
        row2.setDirection(QBoxLayout.Direction.RightToLeft)
        row2.setSpacing(10)
        field_container = QVBoxLayout()
        field_container.setSpacing(4)
        label = make_label("النوع", "fieldLabel")
        field_container.addWidget(label)
        field_container.addWidget(self.gender)
        row2.addLayout(field_container, 1)
        row2.addStretch(1)
        form.addLayout(row2)

        self.payment_unlock_btn: Optional[QPushButton] = None
        self.payment_unlock_status: Optional[QLabel] = None
        if not self.is_new:
            self.payment_unlock_btn = QPushButton("فتح تعديل آخر دفع")
            self.payment_unlock_btn.setObjectName("secondaryButton")
            self.payment_unlock_btn.clicked.connect(self.unlock_last_payment_editing)
            self.payment_unlock_status = make_label("لتعديل آخر عملية دفع اضغط فتح وأدخل كلمة سر.", "smallMuted")

            unlock_layout = QHBoxLayout()
            unlock_layout.setDirection(QBoxLayout.Direction.RightToLeft)
            unlock_layout.setSpacing(10)
            unlock_layout.addWidget(self.payment_unlock_btn)
            unlock_layout.addStretch(1)
            form.addLayout(unlock_layout)
            form.addWidget(self.payment_unlock_status)

            form.addWidget(make_label("آخر اشتراك", "sectionLabel"))
            
            # Row 3: Subscription Type
            row3 = QHBoxLayout()
            row3.setDirection(QBoxLayout.Direction.RightToLeft)
            row3.setSpacing(10)
            field_container = QVBoxLayout()
            field_container.setSpacing(4)
            label = make_label("نوع الاشتراك", "fieldLabel")
            field_container.addWidget(label)
            field_container.addWidget(self.subscription_type)
            row3.addLayout(field_container, 1)
            row3.addStretch(1)
            form.addLayout(row3)
            
            # Row 4: Start & End Dates
            row4 = QHBoxLayout()
            row4.setDirection(QBoxLayout.Direction.RightToLeft)
            row4.setSpacing(10)
            for lbl, w in [("البداية", self.subscription_start), ("النهاية", self.subscription_end)]:
                field_container = QVBoxLayout()
                field_container.setSpacing(4)
                label = make_label(lbl, "fieldLabel")
                field_container.addWidget(label)
                field_container.addWidget(w)
                row4.addLayout(field_container, 1)
            form.addLayout(row4)

            row5 = QHBoxLayout()
            row5.setDirection(QBoxLayout.Direction.RightToLeft)
            row5.setSpacing(10)
            for lbl, w in [("المبلغ المدفوع", self.current_paid), ("المتبقي", self.current_remaining)]:
                field_container = QVBoxLayout()
                field_container.setSpacing(4)
                label = make_label(lbl, "fieldLabel")
                field_container.addWidget(label)
                field_container.addWidget(w)
                row5.addLayout(field_container, 1)
            form.addLayout(row5)
            self.subscription_start.dateChanged.connect(self.on_last_payment_field_changed)
            self.subscription_type.currentIndexChanged.connect(self.on_last_payment_field_changed)
            self.current_paid.valueChanged.connect(self.on_last_payment_field_changed)
            self.current_remaining.valueChanged.connect(self.on_last_payment_field_changed)
            self.subscription_end.dateChanged.connect(self.on_subscription_end_changed)
            self.set_last_payment_editing_enabled(False)
            debug_log("EditMemberDialog.__init__: last-payment signals connected")

        layout.addStretch(1)
        add_fixed_dialog_actions(outer, "حفظ" if self.is_new else "تحديث", self.save, self.reject)

    def save(self) -> None:
        try:
            self._save_impl()
        except Exception as exc:
            debug_log(f"EditMemberDialog.save:unhandled-error {exc}")
            debug_log(traceback.format_exc())
            QMessageBox.critical(self, "خطأ", f"حصل خطأ أثناء تعديل بيانات العضو:\n{exc}")

    def _save_impl(self) -> None:
        debug_log("EditMemberDialog._save_impl:start")
        name = self.name.text().strip()
        mobile = self.mobile.text().strip()
        gender = str(self.gender.currentData())

        if not name:
            QMessageBox.warning(self, "تنبيه", "اكتب اسم العضو.")
            return

        is_valid, error_msg = validate_mobile(mobile)
        if not is_valid:
            QMessageBox.warning(self, "تنبيه", error_msg)
            return

        if self.member:
            debug_log(f"EditMemberDialog._save_impl:editing member_id={self.member.get('member_id', '')}")
            # Multiple different member names may share the same phone number.
            normalized_mobile_value = normalize_mobile(mobile)

            # Update existing member
            original_paid = float(self.member.get("current_paid", 0) or 0)
            original_total = float(self.member.get("total_paid", 0) or 0)
            self.member["name"] = name
            self.member["gender"] = gender
            self.member["last_subscription_type"] = str(self.subscription_type.currentData() or "")
            if self.subscription_start.isEnabled() and self.subscription_end.isEnabled():
                debug_log(
                    "EditMemberDialog._save_impl:subscription-fields-enabled "
                    f"start={self.subscription_start.date().toString('yyyy-MM-dd')} "
                    f"end={self.subscription_end.date().toString('yyyy-MM-dd')} "
                    f"manual_override={self.end_manual_override}"
                )
                if not self.end_manual_override:
                    self.auto_update_end_date()
                new_start = date_to_str(qdate_to_py(self.subscription_start.date()))
                new_end = date_to_str(qdate_to_py(self.subscription_end.date()))
                self.member["last_subscription_start"] = new_start
                self.member["last_subscription_end"] = new_end
            new_paid = float(self.current_paid.value())
            new_remaining = float(self.current_remaining.value())
            self.member["current_paid"] = new_paid
            self.member["current_remaining"] = new_remaining
            self.member["total_paid"] = max(0.0, original_total - original_paid + new_paid)
            self.member["current_status"] = status_en_from_dates(date_to_str(qdate_to_py(self.subscription_end.date())))
            self.member["mobile"] = normalized_mobile_value
            # If subscription/payment fields were edited, try to update the
            # existing payment record instead of creating a new one so we
            # don't generate a duplicate receipt WhatsApp message.
            try:
                if self.subscription_start.isEnabled() and self.subscription_end.isEnabled():
                    debug_log("EditMemberDialog._save_impl:attempt-sync-last-payment-record")
                    # Find last subscription history entry for this member
                    history = self.member.get("subscriptions_history", [])
                    if history:
                        last_hist = history[-1]
                        pid = last_hist.get("payment_id") or last_hist.get("payment_id")
                        inv = last_hist.get("invoice_no") or last_hist.get("invoice_no")
                        payment = None
                        if pid:
                            payment = next((p for p in self.store.payments if p.get("payment_id") == pid), None)
                        if payment is None and inv:
                            payment = next((p for p in self.store.payments if str(p.get("invoice_no", "")) == str(inv)), None)
                        if payment:
                            payment["subscription_start"] = new_start
                            payment["subscription_end"] = new_end
                            plan_name = str(self.subscription_type.currentData() or "")
                            payment["subscription_type"] = plan_name
                            payment["plan_price"] = float(self.store.plan_by_name(plan_name).get("price", 0) or 0)
                            payment["paid_amount"] = new_paid
                            payment["remaining_amount"] = new_remaining
                            payment["status"] = "paid" if new_remaining <= 0 else "partial"
                            payment["name"] = name
                            payment["mobile"] = normalize_mobile(self.mobile.text().strip())
                            payment["gender"] = gender
                            self.store.save_payments()
                            last_hist["subscription_start"] = new_start
                            last_hist["subscription_end"] = new_end
                            last_hist["subscription_type"] = plan_name
                            last_hist["plan_price"] = payment["plan_price"]
                            last_hist["paid_amount"] = new_paid
                            last_hist["remaining_amount"] = new_remaining
                            last_hist["status"] = payment["status"]
            except Exception:
                # Ignore failures here; still continue to save member data
                debug_log("EditMemberDialog._save_impl:sync-last-payment-record-failed")
                pass

            if self.subscription_start.isEnabled() and self.subscription_end.isEnabled():
                self.auto_update_end_date()
            self.store.save_members()
            debug_log("EditMemberDialog._save_impl:save_members-done")
            try:
                debug_log("EditMemberDialog._save_impl:queue-google-contact:start")
                self.store.queue_google_contact(self.member)
                # Do not flush here; flush runs in background from MainWindow startup timer.
                # Keeping this synchronous caused crashes on some systems.
                debug_log("EditMemberDialog._save_impl:queue-google-contact:queued")
            except Exception as exc:
                debug_log(f"EditMemberDialog._save_impl:queue-google-contact:error {exc}")
            debug_log("EditMemberDialog._save_impl:show-success-message")
            QMessageBox.information(self, "تم", "تم تحديث بيانات العضو.")
            debug_log("EditMemberDialog._save_impl:member-updated-success")
        else:
            # Add new member. The same phone may belong to different member names.
            member_id = f"member_{int(time.time() * 1000)}"
            new_member = {
                "member_id": member_id,
                "name": name,
                "mobile": normalize_mobile(mobile),
                "gender": gender,
                "member_type": "regular",
                "subscriptions_history": [],
                "current_status": "expired",
                "current_paid": 0,
                "current_remaining": 0,
                "last_subscription_type": "",
                "last_subscription_start": "",
                "last_subscription_end": "",
                "follow_up_date": "",
                "notes": "",
            }
            self.store.members.append(new_member)
            self.store.save_members()
            try:
                debug_log("EditMemberDialog._save_impl:new-member-queue-google-contact:start")
                self.store.queue_google_contact(new_member)
                debug_log("EditMemberDialog._save_impl:new-member-queue-google-contact:queued")
            except Exception as exc:
                debug_log(f"EditMemberDialog._save_impl:new-member-queue-google-contact:error {exc}")
            QMessageBox.information(self, "تم", f"تم إضافة {name} بنجاح.")
        
        self.accept()
        debug_log("EditMemberDialog._save_impl:dialog-accepted")

    def set_last_payment_editing_enabled(self, enabled: bool) -> None:
        debug_log(f"EditMemberDialog.set_last_payment_editing_enabled: enabled={enabled}")
        self.subscription_type.setEnabled(enabled)
        self.subscription_start.setEnabled(enabled)
        self.subscription_end.setEnabled(enabled)
        self.current_paid.setEnabled(enabled)
        self.current_remaining.setEnabled(enabled)
        if self.payment_unlock_btn is not None:
            self.payment_unlock_btn.setEnabled(not enabled)
        if self.payment_unlock_status is not None:
            self.payment_unlock_status.setText(
                "يمكنك الآن تعديل بيانات آخر عملية دفع." if enabled else "لتعديل آخر عملية دفع اضغط فتح وأدخل كلمة سر."
            )

    def unlock_last_payment_editing(self) -> None:
        debug_log("EditMemberDialog.unlock_last_payment_editing:prompt")
        password = str(self.store.settings.get("dashboard_password", "1234"))
        dlg = PasswordDialog(self, password)
        if dlg.exec() == QDialog.Accepted and getattr(dlg, "ok", False):
            debug_log("EditMemberDialog.unlock_last_payment_editing:accepted")
            self.set_last_payment_editing_enabled(True)
            # On unlock, restore the default calculated end-date cycle
            # (e.g., 17/7 -> 16/8) until the user edits end date manually.
            self.end_manual_override = False
            self.auto_update_end_date()
            QMessageBox.information(self, "تم", "يمكنك الآن تعديل بيانات آخر عملية دفع.")

    def on_last_payment_field_changed(self, *_args) -> None:
        debug_log(
            "EditMemberDialog.on_last_payment_field_changed: "
            f"manual_override={self.end_manual_override} "
            f"start={self.subscription_start.date().toString('yyyy-MM-dd')} "
            f"end={self.subscription_end.date().toString('yyyy-MM-dd')}"
        )
        if self.end_manual_override:
            return
        self.auto_update_end_date()

    def on_subscription_end_changed(self, _qdate) -> None:
        debug_log(
            "EditMemberDialog.on_subscription_end_changed: "
            f"suppress={self.suppress_end_change} "
            f"new_end={self.subscription_end.date().toString('yyyy-MM-dd')}"
        )
        if self.suppress_end_change:
            return
        self.end_manual_override = True
        debug_log("EditMemberDialog.on_subscription_end_changed:manual-override-enabled")

    def auto_update_end_date(self) -> None:
        plan_name = str(self.subscription_type.currentData() or "")
        debug_log(f"EditMemberDialog.auto_update_end_date:start plan={plan_name!r}")
        if not plan_name:
            debug_log("EditMemberDialog.auto_update_end_date:skip-empty-plan")
            return

        start_date = qdate_to_py(self.subscription_start.date())
        paid_amount = float(self.current_paid.value())
        self.suppress_end_change = True
        try:
            new_end, _, _, _ = self.store.calculate_end(start_date, plan_name, paid_amount)
            self.subscription_end.setDate(qdate_from_str(new_end))
            debug_log(f"EditMemberDialog.auto_update_end_date:applied new_end={new_end}")
        except Exception:
            debug_log("EditMemberDialog.auto_update_end_date:failed")
            pass
        finally:
            self.suppress_end_change = False
            debug_log("EditMemberDialog.auto_update_end_date:done")


class AddFollowUpDialog(QDialog):
    """Dialog for adding follow-ups."""
    
    def __init__(self, store: Store, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("إضافة متابعة")
        self.setMinimumWidth(680)
        fit_dialog_to_screen(self, 800, 500)
        self.setLayoutDirection(Qt.RightToLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        layout, _scroll = create_dialog_shell(outer, max_width=760)
        layout.addWidget(make_label("إضافة شخص غير مشترك للمتابعة", "dialogTitle"))
        layout.addWidget(make_label("سيتحفظ في صفحة غير المشتركين بدون مدفوعات، وبعد كده تقدر تسجله كاشتراك جديد بنفس رقم الموبايل.", "pageSubtitle"))

        form = QVBoxLayout()
        form.setSpacing(6)
        layout.addLayout(form)

        self.name = QLineEdit()
        self.name.setPlaceholderText("اسم الشخص")
        self.mobile = QLineEdit()
        self.mobile.setPlaceholderText("الموبايل (أرقام فقط)")
        self.gender = QComboBox()
        self.gender.addItem("ذكر", "male")
        self.gender.addItem("أنثى", "female")
        self.follow_up = QDateEdit()
        self.follow_up.setCalendarPopup(True)
        self.follow_up.setDisplayFormat(DISPLAY_DATE_FMT)
        self.follow_up.setDate(qdate_from_date(date.today() + timedelta(days=7)))
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("ملاحظات المتابعة: مهتم، كلمه آخر الأسبوع، جاي يجرب...")

        # Row 1: Name & Mobile
        row1 = QHBoxLayout()
        row1.setDirection(QBoxLayout.Direction.RightToLeft)
        row1.setSpacing(10)
        for lbl, w in [("الاسم", self.name), ("الموبايل", self.mobile)]:
            field_container = QVBoxLayout()
            field_container.setSpacing(4)
            label = make_label(lbl, "fieldLabel")
            field_container.addWidget(label)
            field_container.addWidget(w)
            row1.addLayout(field_container, 1)
        form.addLayout(row1)

        # Row 2: Gender & Follow-up Date
        row2 = QHBoxLayout()
        row2.setDirection(QBoxLayout.Direction.RightToLeft)
        row2.setSpacing(10)
        for lbl, w in [("النوع", self.gender), ("تاريخ المتابعة", self.follow_up)]:
            field_container = QVBoxLayout()
            field_container.setSpacing(4)
            label = make_label(lbl, "fieldLabel")
            field_container.addWidget(label)
            field_container.addWidget(w)
            row2.addLayout(field_container, 1)
        form.addLayout(row2)

        # Row 3: Notes
        field_container = QVBoxLayout()
        field_container.setSpacing(4)
        label = make_label("ملاحظات", "fieldLabel")
        field_container.addWidget(label)
        field_container.addWidget(self.notes)
        form.addLayout(field_container)

        add_fixed_dialog_actions(outer, "حفظ للمتابعة", self.save, self.reject)

    def save(self) -> None:
        name = self.name.text().strip()
        mobile = self.mobile.text().strip()
        gender = str(self.gender.currentData())

        if not name:
            QMessageBox.warning(self, "تنبيه", "اكتب اسم الشخص.")
            return

        is_valid, error_msg = validate_mobile(mobile)
        if not is_valid:
            QMessageBox.warning(self, "تنبيه", error_msg)
            return

        member_id = f"member_{int(time.time() * 1000)}"
        new_member = {
            "member_id": member_id,
            "name": name,
            "mobile": normalize_mobile(mobile),
            "gender": gender,
            "member_type": "regular",
            "subscriptions_history": [],
            "current_status": "expired",
            "current_paid": 0,
            "current_remaining": 0,
            "last_subscription_type": "",
            "last_subscription_start": "",
            "last_subscription_end": "",
            "follow_up_date": str(self.follow_up.date()),
            "notes": self.notes.text().strip(),
        }
        self.store.members.append(new_member)
        self.store.save_members()
        QMessageBox.information(self, "تم", f"تم إضافة {name} بنجاح.")
        self.accept()


class RemainingPaymentDialog(QDialog):
    def __init__(self, store: Store, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("دفع المتبقي")
        self.setMinimumWidth(720)
        fit_dialog_to_screen(self, 900, 610)
        self.setLayoutDirection(Qt.RightToLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        layout, _scroll = create_dialog_shell(outer, max_width=860)

        layout.addWidget(make_label("دفع المتبقي", "dialogTitle"))
        layout.addWidget(make_label("اختار مشترك عليه متبقي. دفع المتبقي يمد فترة الاشتراك بدل تجديد اشتراك جديد.", "pageSubtitle"))

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setColumnStretch(0, 1)
        form.setColumnMinimumWidth(1, 150)
        layout.addLayout(form)

        self.member_picker = QComboBox()
        self.member_picker.setEditable(True)
        self.member_picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if self.member_picker.lineEdit():
            self.member_picker.lineEdit().setPlaceholderText("ابحث باسم المشترك أو الموبايل")

        self.remaining_members = sorted(self.store.members_with_remaining(), key=lambda m: str(m.get("name", "")))
        for member in self.remaining_members:
            text = f"{member.get('name', '')} - {member.get('mobile', '')} - متبقي {money(member.get('current_remaining', 0))}"
            self.member_picker.addItem(text, member.get("member_id"))

        self.name = QLineEdit(); self.name.setReadOnly(True)
        self.mobile = QLineEdit(); self.mobile.setReadOnly(True)
        self.plan = QLineEdit(); self.plan.setReadOnly(True)
        self.current_end = QLineEdit(); self.current_end.setReadOnly(True)
        self.remaining_before = QLineEdit(); self.remaining_before.setReadOnly(True)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000)
        self.amount.setDecimals(2)
        self.amount.setSingleStep(50)

        widgets = [
            ("اختار المشترك", self.member_picker),
            ("الاسم", self.name),
            ("الموبايل", self.mobile),
            ("الخطة الحالية", self.plan),
            ("النهاية الحالية", self.current_end),
            ("المتبقي الحالي", self.remaining_before),
            ("المبلغ المدفوع الآن", self.amount),
        ]
        for idx, (lbl, w) in enumerate(widgets):
            label = make_label(lbl, "fieldLabel")
            label.setMinimumWidth(140)
            form.addWidget(label, idx, 1)
            form.addWidget(w, idx, 0)

        self.calc = make_label("", "calcBox")
        layout.addWidget(self.calc)
        layout.addStretch(1)

        self.save_button = add_fixed_dialog_actions(outer, "حفظ دفع المتبقي", self.save, self.reject)

        self.member_picker.currentIndexChanged.connect(self.load_selected_member)
        self.amount.valueChanged.connect(self.update_calc)
        if self.member_picker.count() == 0:
            self.calc.setText("لا يوجد أي مشترك عليه متبقي حاليًا.")
            self.save_button.setEnabled(False)
        self.load_selected_member()

    def selected_member(self) -> Optional[Dict[str, Any]]:
        if self.member_picker.count() == 0:
            return None
        member_id = self.member_picker.currentData()
        return next((m for m in self.store.members if m.get("member_id") == member_id), None)

    def load_selected_member(self) -> None:
        member = self.selected_member()
        if not member:
            self.name.clear()
            self.mobile.clear()
            self.plan.clear()
            self.current_end.clear()
            self.remaining_before.clear()
            self.amount.setValue(0)
            self.update_calc()
            return
        remaining = float(member.get("current_remaining", 0) or 0)
        self.name.setText(str(member.get("name", "")))
        self.mobile.setText(str(member.get("mobile", "")))
        self.plan.setText(str(member.get("last_subscription_type", "")))
        self.current_end.setText(display_date(member.get("last_subscription_end", "")))
        self.remaining_before.setText(money(remaining))
        self.amount.blockSignals(True)
        self.amount.setRange(0, remaining)
        self.amount.setValue(remaining)
        self.amount.blockSignals(False)
        self.update_calc()

    def update_calc(self) -> None:
        member = self.selected_member()
        if not member:
            return
        try:
            new_end, remaining_before, remaining_after, days_added = self.store.calculate_remaining_extension(member, float(self.amount.value()))
            self.calc.setText(
                f"المتبقي قبل الدفع: {money(remaining_before)}  |  المدفوع الآن: {money(self.amount.value())}  |  المتبقي بعد الدفع: {money(remaining_after)}  |  تمديد: {days_added} يوم  |  النهاية الجديدة: {display_date(new_end)}"
            )
            if hasattr(self, "save_button"):
                self.save_button.setEnabled(True)
        except ValueError as exc:
            self.calc.setText(str(exc))
            if hasattr(self, "save_button"):
                self.save_button.setEnabled(False)

    def save(self) -> None:
        member = self.selected_member()
        if member is None:
            QMessageBox.warning(self, "تنبيه", "اختار مشترك صحيح.")
            return
        try:
            payment = self.store.pay_remaining(member.get("member_id", ""), float(self.amount.value()), str(self.store.settings.get("payment_methods", ["نقدي"])[0]))
        except ValueError as exc:
            QMessageBox.warning(self, "تنبيه", str(exc))
            return
        QMessageBox.information(self, "تم", f"تم حفظ دفع المتبقي رقم {payment['invoice_no']}")
        self.accept()


class AddExpenseDialog(QDialog):
    def __init__(self, store: Store, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("إضافة مصروف")
        self.setMinimumWidth(680)
        fit_dialog_to_screen(self, 820, 460)
        self.setLayoutDirection(Qt.RightToLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        layout, _scroll = create_dialog_shell(outer, max_width=760)

        layout.addWidget(make_label("إضافة مصروف جديد", "dialogTitle"))
        layout.addWidget(make_label("سجل المصروف واحتفظ به في ملف expenses.json.", "pageSubtitle"))

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setColumnStretch(0, 1)
        form.setColumnMinimumWidth(1, 150)
        layout.addLayout(form)

        self.name = QLineEdit()
        self.name.setPlaceholderText("وصف المصروف")
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000)
        self.amount.setDecimals(2)
        self.amount.setSingleStep(50)
        self.amount.setValue(0)
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat(DISPLAY_DATE_FMT)
        self.date.setDate(QDate.currentDate())
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("ملاحظات إضافية (اختياري)")

        widgets = [
            ("الوصف", self.name),
            ("المبلغ", self.amount),
            ("التاريخ", self.date),
            ("ملاحظات", self.notes),
        ]
        for idx, (lbl, w) in enumerate(widgets):
            label = make_label(lbl, "fieldLabel")
            label.setMinimumWidth(140)
            form.addWidget(label, idx, 1)
            form.addWidget(w, idx, 0)

        layout.addStretch(1)
        add_fixed_dialog_actions(outer, "حفظ المصروف", self.save, self.reject)

    def clear_form(self) -> None:
        self.name.setCurrentIndex(0)
        self.amount.setValue(0)
        self.date.setDate(QDate.currentDate())
        self.notes.clear()

    def save(self) -> None:
        try:
            expense = self.store.add_expense(
                {
                    "name": self.name.text(),
                    "amount": self.amount.value(),
                    "date": date_to_str(qdate_to_py(self.date.date())),
                    "notes": self.notes.text(),
                }
            )
        except ValueError as exc:
            QMessageBox.warning(self, "تنبيه", str(exc))
            return
        QMessageBox.information(self, "تم", f"تم حفظ المصروف: {expense.get('name', '')}.")
        self.clear_form()
        self.accept()


class MemberDetailsDialog(QDialog):
    def __init__(self, store: Store, member: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.store = store
        self.member = member
        self.setWindowTitle(f"بيانات المشترك - {member.get('name', '')}")
        self.setMinimumSize(850, 560)
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(make_label(f"{member.get('name', '')} - {member.get('mobile', '')}", "dialogTitle"))
        follow_text = ""
        if member.get("member_type") == "lead" or member.get("follow_up_date") or member.get("notes"):
            follow_text = f"  |  متابعة: {display_date(member.get('follow_up_date', ''))}  |  ملاحظات: {member.get('notes', '-')}"
        fingerprint_text = str(member.get("fingerprint_id", "")).strip() or "غير مسجلة"
        layout.addWidget(
            make_label(
                f"النوع: {gender_ar(str(member.get('gender')))}  |  الحالة: {status_ar(str(member.get('current_status')))}  |  آخر اشتراك: {member.get('last_subscription_type', '-')}  |  رقم البصمة: {fingerprint_text}{follow_text}",
                "calcBox",
            )
        )
        table = QTableWidget()
        configure_table(table)
        headers = ["الفاتورة", "نوع العملية", "الاشتراك", "المدفوع", "المتبقي", "طريقة الدفع", "البداية", "النهاية", "وقت التسجيل"]
        hist = list(member.get("subscriptions_history", []))
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(hist))
        for r, h in enumerate(hist):
            values = [
                h.get("invoice_no", ""),
                operation_ar(str(h.get("operation_type", "new_subscription"))),
                h.get("subscription_type", ""),
                money(h.get("paid_amount", 0)),
                money(h.get("remaining_amount", 0)),
                h.get("payment_method", ""),
                display_date(h.get("subscription_start", "")),
                display_date(h.get("subscription_end", "")),
                h.get("created_at", ""),
            ]
            for c, v in enumerate(values):
                table.setItem(r, c, item(v))
            table.setRowHeight(r, 46)
        layout.addWidget(table, 1)
        close = QPushButton("إغلاق")
        close.setObjectName("secondaryButton")
        close.clicked.connect(self.accept)
        layout.addWidget(close)


def block_user_input(enabled: bool) -> None:
    """Temporarily block mouse/keyboard on Windows during WhatsApp automation.
    If Windows refuses it, the app continues normally.
    """
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.BlockInput(bool(enabled))
    except Exception:
        pass


class GoogleContactsSyncThread(QThread):
    progress = Signal(int, int, int)
    done = Signal(dict)

    def __init__(self, store: Store, force: bool, total_members: int) -> None:
        super().__init__()
        self.store = store
        self.force = force
        self.total_members = max(0, int(total_members))

    def run(self) -> None:  # type: ignore[override]
        try:
            sync_res = self.store.sync_all_google_contacts(
                force=self.force,
                progress_callback=lambda processed, synced, total: self.progress.emit(processed, synced, total),
                total_for_progress=self.total_members,
            )
            queued_added = sync_res[0]
            synced_count = sync_res[1]
            total_count = sync_res[2] if len(sync_res) > 2 else self.total_members
            stats = getattr(self.store, "last_google_sync_stats", {})
            self.done.emit(
                {
                    "ok": True,
                    "force": self.force,
                    "queued_added": queued_added,
                    "synced_count": synced_count,
                    "total_count": total_count,
                    "stats": stats,
                    "error": "",
                }
            )
        except Exception as exc:
            self.done.emit(
                {
                    "ok": False,
                    "force": self.force,
                    "queued_added": 0,
                    "synced_count": 0,
                    "total_count": self.total_members,
                    "error": str(exc),
                }
            )


class GoogleContactsQueueFlushThread(QThread):
    done = Signal(dict)

    def __init__(self, store: Store) -> None:
        super().__init__()
        self.store = store

    def run(self) -> None:  # type: ignore[override]
        try:
            synced_count = self.store.flush_google_contacts_queue()
            self.done.emit({"ok": True, "synced_count": int(synced_count), "error": ""})
        except Exception as exc:
            self.done.emit({"ok": False, "synced_count": 0, "error": str(exc)})


class ESPOperationThread(QThread):
    done = Signal(dict)

    def __init__(self, operation: str, settings: Dict[str, Any], **kwargs: Any) -> None:
        super().__init__()
        self.operation = operation
        self.settings = settings
        self.kwargs = kwargs

    def run(self) -> None:  # type: ignore[override]
        if self.operation == "enroll":
            result = esp_client.enroll_member(self.settings, str(self.kwargs["member_id"]))
        elif self.operation == "cancel_enroll":
            result = esp_client.cancel_enrollment(self.settings, str(self.kwargs["member_id"]))
        elif self.operation == "enroll_status":
            result = esp_client.get_enroll_status(self.settings)
        elif self.operation == "status":
            result = esp_client.get_esp_status(self.settings)
        elif self.operation == "last_scan":
            result = esp_client.get_last_scan(self.settings)
        elif self.operation == "display_member":
            result = esp_client.display_member(self.settings, self.kwargs["member_data"])
        elif self.operation == "sync":
            if not ESP_SYNC_LOCK.acquire(blocking=False):
                result = {"success": False, "error": "sync_in_progress"}
            else:
                try:
                    status = esp_client.get_esp_status(self.settings)
                    if not status.get("success"):
                        result = {
                            "success": False,
                            "error": "esp_offline",
                            "error_detail": status.get("error", status.get("error_detail", "ESP status check failed")),
                        }
                    else:
                        result = esp_client.push_members(self.settings, self.kwargs["members"])
                finally:
                    ESP_SYNC_LOCK.release()
        elif self.operation == "delete":
            result = esp_client.delete_fingerprint(self.settings, self.kwargs["fingerprint_id"])
        else:
            result = {"success": False, "error": "unknown_operation"}
        self.done.emit(result)


def start_fingerprint_enrollment(parent: QWidget, store: Store, member: Dict[str, Any]) -> None:
    if not store.esp_command_allowed() or str(member.get("fingerprint_id", "")).strip():
        if not store.esp_command_allowed():
            QMessageBox.warning(parent, "جهاز ESP غير متصل", "لا يمكن بدء تسجيل البصمة قبل تحديث حالة ESP والتأكد من اتصاله.")
        return

    store.esp_enrollment_active = True
    progress = QProgressDialog("تسجيل بصمة العضو:\nالخطوة 1 من 2: ضع إصبعك بثبات على القارئ", "إلغاء", 0, 0, parent)
    progress.setWindowTitle("تسجيل بصمة عضو")
    progress.setMinimumWidth(420)
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)
    cancelled = {"value": False, "finished": False}
    thread = ESPOperationThread("enroll", store.settings, member_id=str(member.get("member_id", "")))
    progress._esp_thread = thread
    status_thread_holder: Dict[str, Optional[ESPOperationThread]] = {"thread": None}
    status_timer = QTimer(progress)
    status_timer.setInterval(700)
    status_timer_active = {"value": True}

    ENROLL_STEPS_AR = {
        "waiting_first_finger": "الخطوة 1 من 2: ضع إصبعك بثبات على القارئ",
        "waiting_finger_removal": "ممتاز! ارفع إصبعك الآن عن القارئ...",
        "waiting_second_finger": "الخطوة 2 من 2: ضع نفس الإصبع مرة أخرى للتأكيد",
        "waiting_retry_removal": "أعد رفع الإصبع ثم وضعه بزاوية مستقيمة...",
        "creating_template": "جاري معالجة ومطابقة بصمة الإصبع...",
        "saving": "جاري حفظ البصمة في الذاكرة...",
        "completed": "تم تسجيل البصمة بنجاح!",
        "failed": "فشل تسجيل البصمة",
        "cancelled": "تم إلغاء التسجيل",
    }

    ENROLL_ERRORS_AR = {
        "first_scan_timeout": "انتهت المهلة قبل وضع الإصبع الأول",
        "remove_finger_timeout": "انتهت المهلة قبل رفع الإصبع",
        "second_scan_timeout": "انتهت المهلة قبل وضع الإصبع للمرة الثانية",
        "first_scan_failed": "فشل التقاط صورة البصمة الأولى - يرجى الضغط بثبات",
        "second_scan_failed": "فشل التقاط صورة البصمة الثانية - يرجى الضغط بثبات",
        "template_mismatch": "البصمتان غير متطابقتين - تأكد من وضع نفس الإصبع في المرتين",
        "save_failed": "فشل حفظ البصمة في ذاكرة الحساس",
        "cancelled": "تم إلغاء التسجيل",
    }

    def finished(result: Dict[str, Any]) -> None:
        if result.get("started") is True:
            progress.setLabelText("تسجيل بصمة العضو:\nالخطوة 1 من 2: ضع إصبعك بثبات على القارئ")
            status_timer.start()
            return
        if cancelled["finished"]:
            return
        cancelled["finished"] = True
        status_timer.stop()
        status_timer_active["value"] = False
        store.esp_enrollment_active = False
        progress.close()
        if cancelled["value"]:
            return
        fingerprint_id = result.get("fingerprint_id")
        valid_fingerprint_id = (
            isinstance(fingerprint_id, int)
            and not isinstance(fingerprint_id, bool)
            and 1 <= fingerprint_id <= 1000
        )
        if result.get("success") is True and valid_fingerprint_id:
            store.esp_connected = True
            store.esp_status_checked_at = time.monotonic()
            member["fingerprint_id"] = fingerprint_id
            store.save_members(push_to_esp=False)
            start_members_sync(parent, store, f"تم تسجيل البصمة بنجاح. الرقم: {member['fingerprint_id']}")
            return
        error = result.get("error", result.get("error_detail", "enrollment_failed"))
        if error == "enrollment_response_lost":
            QMessageBox.information(
                parent,
                "التسجيل ما زال غير مؤكد",
                "ESP أغلق اتصال HTTP قبل إرسال النتيجة النهائية.\n"
                "هذا لا يؤكد أن التسجيل توقف؛ قد يكون ESP ما زال ينتظر أو أنه سجل البصمة.\n"
                "لا تضغط Retry ولا تبدأ تسجيلًا جديدًا قبل مراجعة Serial Monitor الخاص بـ ESP.",
            )
            return
        error_ar = ENROLL_ERRORS_AR.get(error, error)
        reply = QMessageBox.question(
            parent,
            "فشل تسجيل البصمة",
            f"سبب الخطأ: {error_ar}\n\nهل تريد المحاولة مرة أخرى؟",
            QMessageBox.Retry | QMessageBox.Cancel,
            QMessageBox.Retry,
        )
        if reply == QMessageBox.Retry:
            start_fingerprint_enrollment(parent, store, member)

    def cancel_requested() -> None:
        if cancelled["finished"] or cancelled["value"]:
            return
        cancelled["value"] = True
        store.esp_enrollment_active = False
        progress.setLabelText("جاري طلب إيقاف التسجيل من ESP...")
        cancel_thread = ESPOperationThread(
            "cancel_enroll",
            store.settings,
            member_id=str(member.get("member_id", "")),
        )
        progress._cancel_thread = cancel_thread

        def cancel_finished(result: Dict[str, Any]) -> None:
            if result.get("success") is True:
                progress.close()
                QMessageBox.information(parent, "تم", "تم إيقاف تسجيل البصمة من جهاز ESP.")
            else:
                error = result.get("error", result.get("error_detail", "cancel_unsupported"))
                progress.close()
                QMessageBox.warning(
                    parent,
                    "لم يتم إيقاف جهاز ESP",
                    "تم إلغاء الانتظار في الكمبيوتر، لكن جهاز ESP ما زال قد يكون في وضع التسجيل.\n"
                    f"السبب: {error}\n"
                    "يحتاج firmware الخاص بـ ESP إلى دعم POST /cancel_enroll.",
                )

        cancel_thread.done.connect(cancel_finished)
        cancel_thread.finished.connect(cancel_thread.deleteLater)
        cancel_thread.start()

    def poll_enrollment_status() -> None:
        if not status_timer_active["value"] or cancelled["value"]:
            return
        active_status_thread = status_thread_holder["thread"]
        if active_status_thread is not None and active_status_thread.isRunning():
            return
        status_thread = ESPOperationThread("enroll_status", store.settings)
        status_thread_holder["thread"] = status_thread
        progress._status_thread = status_thread

        def status_finished(result: Dict[str, Any]) -> None:
            if result.get("success") is not True:
                return
            if result.get("completed") is True:
                finished({
                    "success": True,
                    "fingerprint_id": result.get("fingerprint_id"),
                })
            elif result.get("cancelled") is True or result.get("error"):
                finished({"success": False, "error": result.get("error", "cancelled")})
            else:
                step = result.get("step", "")
                step_text = ENROLL_STEPS_AR.get(step, f"جاري التسجيل... ({step})")
                progress.setLabelText(f"تسجيل بصمة العضو:\n{step_text}")

        status_thread.done.connect(status_finished)
        status_thread.finished.connect(status_thread.deleteLater)
        status_thread.finished.connect(
            lambda t=status_thread: status_thread_holder.__setitem__(
                "thread", None if status_thread_holder["thread"] is t else status_thread_holder["thread"]
            )
        )
        status_thread.start()

    progress.canceled.connect(cancel_requested)
    thread.done.connect(finished)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    progress.show()
    status_timer.timeout.connect(poll_enrollment_status)


def start_members_sync(parent: QWidget, store: Store, success_prefix: str = "") -> None:
    if not store.esp_command_allowed():
        QMessageBox.warning(parent, "جهاز ESP غير متصل", "لا يمكن تنفيذ المزامنة قبل تحديث حالة ESP والتأكد من اتصاله.")
        return
    progress = QProgressDialog("جاري مزامنة صلاحيات الأعضاء مع ESP...", "", 0, 0, parent)
    progress.setWindowTitle("مزامنة ESP")
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)
    thread = ESPOperationThread("sync", store.settings, members=store.esp_members_payload())
    progress._esp_thread = thread

    def finished(result: Dict[str, Any]) -> None:
        progress.close()
        if result.get("success"):
            prefix = f"{success_prefix}\n" if success_prefix else ""
            QMessageBox.information(parent, "تم", f"{prefix}تمت مزامنة {result.get('members', 0)} عضو مع ESP.")
        else:
            error = result.get("error", result.get("error_detail", "فشل مزامنة الصلاحيات"))
            QMessageBox.warning(parent, "فشل المزامنة", f"SYNC FAILED: {error}")

    thread.done.connect(finished)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    progress.show()


class WhatsAppSendThread(QThread):
    progress = Signal(int, int, int, int)
    done = Signal(dict)

    def __init__(self, messages: List[Dict[str, Any]], settings: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self.messages = messages
        self.settings = dict(settings or {})

    def run(self) -> None:  # type: ignore[override]
        ids = [str(m.get("message_id", "")) for m in self.messages]
        phones = [normalize_mobile(str(m.get("mobile", ""))) for m in self.messages]
        topics = [whatsapp_message_topic(m) for m in self.messages]
        message_bank = load_whatsapp_message_bank()
        
        # Extract context data for each message (name, dates, amounts, etc.)
        contexts = []
        for msg in self.messages:
            context = {
                "name": str(msg.get("recipient_name", "")),
                "date": str(msg.get("created_at", "")).split()[0],  # Extract just the date part
                "end_date": str(msg.get("subscription_end", "")),
                "amount_paid": str(msg.get("paid_amount", "")),
                "remaining_amount": str(msg.get("remaining_amount", "")),
            }
            contexts.append(context)
        
        print(f"[WhatsAppSendThread] Starting send with {len(self.messages)} messages")
        for i, (msg_id, phone, topic) in enumerate(zip(ids, phones, topics)):
            print(f"[WhatsAppSendThread] Message {i}: id={msg_id}, phone={phone}, topic={topic!r}, context={contexts[i]}")

        # Messages whose topic has no bank entry (e.g. daily_report) carry their own
        # fully-built text and must be sent as-is instead of a random bank pick.
        bank_indexes = [i for i, t in enumerate(topics) if t in message_bank]
        literal_indexes = [i for i, t in enumerate(topics) if t not in message_bank]

        try:
            import whatsapp_sender
            whatsapp_sender.apply_send_settings(self.settings)
            total = len(self.messages)
            self.progress.emit(0, total, 0, 0)
            offset = {"done": 0}

            def progress_callback(processed: int, total_count: int) -> None:
                done_count = offset["done"] + max(0, min(int(processed), int(total_count)))
                self.progress.emit(done_count, total, done_count, 0)

            whatsapp_sender.sent = []
            whatsapp_sender.unsent = []

            if bank_indexes:
                bank_phones = [phones[i] for i in bank_indexes]
                bank_topics = [topics[i] for i in bank_indexes]
                bank_contexts = [contexts[i] for i in bank_indexes]
                print(f"[WhatsAppSendThread] Calling whatsapp_sender.sending() with {len(bank_phones)} phones and {len(bank_topics)} topics (bank)")
                whatsapp_sender.sending(bank_phones, message_bank, groups=bank_topics, contexts=bank_contexts, progress_callback=progress_callback)
                offset["done"] += len(bank_indexes)

            if literal_indexes:
                literal_phones = [phones[i] for i in literal_indexes]
                literal_texts = [str(self.messages[i].get("message", "")) for i in literal_indexes]
                print(f"[WhatsAppSendThread] Calling whatsapp_sender.sending() with {len(literal_phones)} phones and literal text (e.g. daily_report)")
                whatsapp_sender.sending(literal_phones, literal_texts, progress_callback=progress_callback)
                offset["done"] += len(literal_indexes)

            print(f"[WhatsAppSendThread] Send complete. sent={len(whatsapp_sender.sent)}, unsent={len(whatsapp_sender.unsent)}")

            unsent = {normalize_mobile(str(x)) for x in getattr(whatsapp_sender, "unsent", [])}
            failed_ids = []
            if unsent:
                for msg in self.messages:
                    if normalize_mobile(str(msg.get("mobile", ""))) in unsent:
                        failed_ids.append(str(msg.get("message_id", "")))

            success_count = max(0, total - len(failed_ids))
            self.progress.emit(total, total, success_count, len(failed_ids))
            self.done.emit({"ok": True, "ids": ids, "failed_ids": failed_ids, "error": ""})
        except Exception as exc:
            print(f"[WhatsAppSendThread] ERROR: {exc}")
            self.done.emit({"ok": False, "ids": ids, "failed_ids": ids, "error": str(exc)})


def show_unsendable_whatsapp_dialog(
    parent: Optional[QWidget],
    title: str,
    intro_lines: List[str],
    items: List[tuple[Dict[str, Any], str]],
    can_proceed: bool = False,
    proceed_button_text: str = "متابعة الإرسال",
) -> bool:
    """Display an explicit modal dialog stating the exact messages that cannot be sent, why, and how many."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLayoutDirection(Qt.RightToLeft)
    fit_dialog_to_screen(dialog, 920, 520)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    # Header Box
    header_box = QFrame()
    header_box.setObjectName("settingsBox")
    header_layout = QVBoxLayout(header_box)
    header_layout.setContentsMargins(14, 12, 14, 12)
    header_layout.setSpacing(6)

    title_lbl = make_label(title, "dialogTitleSmall")
    title_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
    header_layout.addWidget(title_lbl)

    for line in intro_lines:
        line_lbl = make_label(line, "fieldLabel")
        line_lbl.setWordWrap(True)
        if "⚠️" in line or "لن يتم" in line or "فشل" in line:
            line_lbl.setStyleSheet("color: #FFB020; font-weight: bold;")
        elif "سيتم إرسال" in line or "تم الإرسال" in line:
            line_lbl.setStyleSheet("color: #2ECC71; font-weight: bold;")
        header_layout.addWidget(line_lbl)

    layout.addWidget(header_box)

    # Count badge
    count_text = f"عدد الرسائل المستبعدة / التي لن تُرسل: {len(items)} رسالة"
    count_lbl = make_label(count_text, "smallMuted")
    count_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
    layout.addWidget(count_lbl)

    # Table of unsendable messages
    table = QTableWidget()
    configure_table(table)
    table.setAlternatingRowColors(True)
    table.setFont(QFont("Segoe UI", 9))
    headers = ["الاسم", "الموبايل", "النوع", "الحالة الحالية", "سبب عدم الإرسال بالتفصيل"]
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(items))
    table.setColumnWidth(0, 140)
    table.setColumnWidth(1, 115)
    table.setColumnWidth(2, 95)
    table.setColumnWidth(3, 90)
    table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

    for row_idx, (msg, reason) in enumerate(items):
        name = str(msg.get("recipient_name", "") or msg.get("name", "عضو")).strip() or "غير محدد"
        mobile = str(msg.get("mobile", "")).strip() or "بدون هاتف"
        msg_type = whatsapp_type_ar(str(msg.get("type", "")))
        status_val = whatsapp_status_ar(str(msg.get("status", "pending")))

        name_cell = item(name)
        mobile_cell = item(mobile)
        type_cell = item(msg_type)
        status_cell = item(status_val)
        reason_cell = item(reason)
        reason_cell.setForeground(Qt.GlobalColor.yellow if "مجدولة" in reason else Qt.GlobalColor.red)

        table.setItem(row_idx, 0, name_cell)
        table.setItem(row_idx, 1, mobile_cell)
        table.setItem(row_idx, 2, type_cell)
        table.setItem(row_idx, 3, status_cell)
        table.setItem(row_idx, 4, reason_cell)
        table.setRowHeight(row_idx, 32)

    layout.addWidget(table, 1)

    # Footer Buttons
    btn_layout = QHBoxLayout()
    btn_layout.setDirection(QBoxLayout.Direction.RightToLeft)
    btn_layout.setSpacing(10)

    if can_proceed:
        cancel_btn = QPushButton("إلغاء")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setFixedHeight(32)
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        proceed_btn = QPushButton(proceed_button_text)
        proceed_btn.setObjectName("primaryButton")
        proceed_btn.setFixedHeight(32)
        proceed_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(proceed_btn)
    else:
        close_btn = QPushButton("إغلاق")
        close_btn.setObjectName("secondaryButton")
        close_btn.setFixedHeight(32)
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)

    layout.addLayout(btn_layout)

    return dialog.exec() == QDialog.Accepted


class WhatsAppPage(BasePage):
    def __init__(self, store: Store, send_pending_callback) -> None:
        super().__init__(store, "واتساب", "إيصالات الدفع وتذكيرات الاشتراك وتقرير المدير بنفس منطق الإرسال القديم")
        self.send_pending_callback = send_pending_callback

        # Search and filters row
        controls = QHBoxLayout()
        controls.setDirection(QBoxLayout.Direction.RightToLeft)
        controls.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText("ابحث بالاسم أو الموبايل أو النوع أو الحالة...")
        self.search.setFont(QFont("Segoe UI", 9))
        self.search.setFixedHeight(26)
        self.search.textChanged.connect(self.refresh)
        controls.addWidget(self.search, 1)

        # Message type filter
        self.type_filter = QComboBox()
        self.type_filter.setFont(QFont("Segoe UI", 10))
        self.type_filter.setFixedHeight(28)
        self.type_filter.addItem("جميع الأنواع", "all")
        self.type_filter.addItem("إيصالات الدفع", "receipt")
        self.type_filter.addItem("تذكيرات الاشتراك", "reminder")
        self.type_filter.addItem("غير المشتركين", "expired")
        self.type_filter.addItem("تقرير المدير", "daily_report")
        self.type_filter.currentIndexChanged.connect(self.refresh)
        self.type_filter.setFixedWidth(150)
        controls.addWidget(self.type_filter)

        # Status filter
        self.status_filter = QComboBox()
        self.status_filter.setFont(QFont("Segoe UI", 10))
        self.status_filter.setFixedHeight(28)
        self.status_filter.addItem("الكل", "all")
        self.status_filter.addItem("معلق", "pending")
        self.status_filter.addItem("تم الإرسال", "sent")
        self.status_filter.addItem("فشل", "failed")
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.status_filter.setFixedWidth(130)
        controls.addWidget(self.status_filter)

        self.root.addLayout(controls)

        # Prepare & Setup Group
        setup_row = QHBoxLayout()
        setup_row.setDirection(QBoxLayout.Direction.RightToLeft)
        setup_row.setSpacing(8)
        setup_row.setContentsMargins(0, 0, 0, 0)

        setup_label = make_label("تجهيز الرسائل:", "fieldLabel")
        setup_label.setFont(QFont("Segoe UI", 8))
        setup_row.addWidget(setup_label)

        prepare_btn = QPushButton("تجهيز التذكيرات")
        prepare_btn.setObjectName("secondaryButton")
        prepare_btn.setFixedHeight(26)
        prepare_btn.setFont(QFont("Segoe UI", 8))
        prepare_btn.clicked.connect(self.prepare_reminders)
        setup_row.addWidget(prepare_btn, 1)

        expired_bulk_btn = QPushButton("إرسال غير المشتركين")
        expired_bulk_btn.setObjectName("secondaryButton")
        expired_bulk_btn.setFixedHeight(26)
        expired_bulk_btn.setFont(QFont("Segoe UI", 8))
        expired_bulk_btn.clicked.connect(self.send_expired_non_subscribers)
        setup_row.addWidget(expired_bulk_btn, 1)

        send_report_btn = QPushButton("تقرير المدير")
        send_report_btn.setObjectName("primaryButton")
        send_report_btn.setFixedHeight(26)
        send_report_btn.setFont(QFont("Segoe UI", 8))
        send_report_btn.clicked.connect(self.send_manager_report_now)
        setup_row.addWidget(send_report_btn, 1)

        self.root.addLayout(setup_row)

        # Send Group
        send_row = QHBoxLayout()
        send_row.setDirection(QBoxLayout.Direction.RightToLeft)
        send_row.setSpacing(8)
        send_row.setContentsMargins(0, 0, 0, 0)

        send_label = make_label("إرسال:", "fieldLabel")
        send_label.setFont(QFont("Segoe UI", 8))
        send_row.addWidget(send_label)

        send_unsent_btn = QPushButton("إرسال غير المرسل")
        send_unsent_btn.setObjectName("primaryButton")
        send_unsent_btn.setFixedHeight(26)
        send_unsent_btn.setFont(QFont("Segoe UI", 8))
        send_unsent_btn.setToolTip("إرسال كافة الرسائل غير المرسلة (المعلقة + الفاشلة)")
        send_unsent_btn.clicked.connect(self.send_unsent_messages)
        send_row.addWidget(send_unsent_btn, 1)

        send_pending_btn = QPushButton("إرسال المعلق")
        send_pending_btn.setObjectName("secondaryButton")
        send_pending_btn.setFixedHeight(26)
        send_pending_btn.setFont(QFont("Segoe UI", 8))
        send_pending_btn.clicked.connect(self.select_and_send)
        send_row.addWidget(send_pending_btn, 1)

        unsendable_report_btn = QPushButton("فحص أسباب عدم الإرسال")
        unsendable_report_btn.setObjectName("secondaryButton")
        unsendable_report_btn.setFixedHeight(26)
        unsendable_report_btn.setFont(QFont("Segoe UI", 8))
        unsendable_report_btn.setToolTip("بيان الرسائل التي لن يتم إرسالها وعددها وأسباب استبعادها بالتفصيل")
        unsendable_report_btn.clicked.connect(self.show_unsendable_report)
        send_row.addWidget(unsendable_report_btn, 1)

        retry_failed_btn = QPushButton("إعادة الفاشل للمعلق")
        retry_failed_btn.setObjectName("secondaryButton")
        retry_failed_btn.setFixedHeight(26)
        retry_failed_btn.setFont(QFont("Segoe UI", 8))
        retry_failed_btn.clicked.connect(self.retry_failed)
        send_row.addWidget(retry_failed_btn, 1)

        resend_selected_btn = QPushButton("إعادة إرسال المحدد")
        resend_selected_btn.setObjectName("secondaryButton")
        resend_selected_btn.setFixedHeight(26)
        resend_selected_btn.setFont(QFont("Segoe UI", 8))
        resend_selected_btn.clicked.connect(self.resend_selected)
        send_row.addWidget(resend_selected_btn, 1)

        force_resend_btn = QPushButton("إرسال قسري (حتى لو أُرسلت)")
        force_resend_btn.setObjectName("warningButton")
        force_resend_btn.setFixedHeight(26)
        force_resend_btn.setFont(QFont("Segoe UI", 8))
        force_resend_btn.clicked.connect(self.force_resend_selected)
        send_row.addWidget(force_resend_btn, 1)

        self.root.addLayout(send_row)

        # Delete Group
        delete_row = QHBoxLayout()
        delete_row.setDirection(QBoxLayout.Direction.RightToLeft)
        delete_row.setSpacing(8)
        delete_row.setContentsMargins(0, 0, 0, 0)

        delete_label = make_label("حذف:", "fieldLabel")
        delete_label.setFont(QFont("Segoe UI", 8))
        delete_row.addWidget(delete_label)

        delete_selected_btn = QPushButton("حذف المحدد")
        delete_selected_btn.setObjectName("dangerButton")
        delete_selected_btn.setFixedHeight(26)
        delete_selected_btn.setFont(QFont("Segoe UI", 8))
        delete_selected_btn.clicked.connect(self.delete_selected)
        delete_row.addWidget(delete_selected_btn, 1)

        # Delete dropdown menu
        delete_menu_btn = QPushButton("حذف متقدم ▼")
        delete_menu_btn.setObjectName("dangerButton")
        delete_menu_btn.setFixedHeight(26)
        delete_menu_btn.setFont(QFont("Segoe UI", 8))
        delete_row.addWidget(delete_menu_btn, 1)

        delete_menu = QMenu(self)
        delete_menu.setLayoutDirection(Qt.RightToLeft)
        delete_menu.setFont(QFont("Segoe UI", 8))
        
        delete_sent_action = delete_menu.addAction("حذف المرسلة (تم)")
        delete_sent_action.triggered.connect(self.delete_sent_messages)
        
        delete_failed_action = delete_menu.addAction("حذف الفاشلة")
        delete_failed_action.triggered.connect(self.delete_failed_messages)
        
        delete_menu.addSeparator()
        
        delete_all_action = delete_menu.addAction("حذف الكل")
        delete_all_action.triggered.connect(self.delete_all_messages)

        delete_menu_btn.setMenu(delete_menu)

        self.root.addLayout(delete_row)

        self.count_lbl = make_label("0 رسالة", "muted")
        self.count_lbl.setFont(QFont("Segoe UI", 10))
        self.root.addWidget(self.count_lbl)

        self.table = QTableWidget()
        configure_table(self.table)
        self.table.setAlternatingRowColors(True)
        self.table.setFont(QFont("Segoe UI", 9))
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.itemDoubleClicked.connect(lambda item: self.open_message_from_row(item.row()))
        self.table.cellDoubleClicked.connect(lambda row, col: self.open_message_from_row(row))
        self.root.addWidget(self.table, 1)
        self._rows_by_index = {}
        self._refresh_pending = False
        self.refresh()

    def prepare_reminders(self) -> None:
        removed, added = self.store.force_rebuild_due_reminders(save=True)
        QMessageBox.information(
            self,
            "تم",
            f"تمت مراجعة الرسائل المعلقة.\nتم حذف {removed} رسالة قديمة.\nتم تجهيز {added} رسالة تذكير محدثة.",
        )
        self.refresh()

    def show_unsendable_report(self) -> None:
        """Scan all non-sent messages and display a detailed report stating which messages cannot be sent, why, and how many."""
        candidates = [
            m for m in self.store.whatsapp_messages
            if str(m.get("status", "")) in ("pending", "scheduled", "failed")
        ]
        if not candidates:
            QMessageBox.information(self, "واتساب", "لا توجد رسائل غير مرسلة (معلقة أو مجدولة أو فاشلة) حاليًا في النظام.")
            return

        unsendable = []
        ready_count = 0
        self.store.refresh_statuses(save=False)
        for m in candidates:
            reason = self.store.get_whatsapp_unsendable_reason(m, manual=False)
            if reason is not None:
                unsendable.append((m, reason))
            else:
                ready_count += 1

        if not unsendable:
            QMessageBox.information(
                self,
                "فحص الرسائل",
                f"كل الرسائل المعلقة ({ready_count} رسالة) جاهزة وصالحة للإرسال فورًا، ولا توجد أي رسائل معطلة أو مستبعدة.",
            )
            return

        show_unsendable_whatsapp_dialog(
            self,
            title="تقرير الرسائل التي لن يتم إرسالها وأسبابها",
            intro_lines=[
                f"• إجمالي الرسائل غير المرسلة (معلق + مجدول + فاشل): {len(candidates)} رسالة.",
                f"• الرسائل الجاهزة والصالحة للإرسال الآن: {ready_count} رسالة.",
                f"• ⚠️ الرسائل التي لن يتم إرسالها حاليًا: {len(unsendable)} رسالة (الأسباب موضحة بالجدول أدناه):",
            ],
            items=unsendable,
            can_proceed=False,
        )

    def send_manager_report_now(self) -> None:
        password = str(self.store.settings.get("dashboard_password", "1234"))
        dlg = PasswordDialog(self, password)
        if dlg.exec() != QDialog.Accepted or not getattr(dlg, "ok", False):
            return

        added = self.store.queue_daily_report(force=True, save=True, allow_duplicate=True)
        if not added:
            QMessageBox.warning(self, "تنبيه", "لم يتم تجهيز تقرير المدير. تأكد من كتابة رقم المدير في الإعدادات.")
            return
        self.refresh()
        pending_reports = [
            m for m in self.store.pending_whatsapp_messages() if str(m.get("type", "")) == "daily_report"
        ]
        if not pending_reports:
            QMessageBox.information(self, "واتساب", "لا يوجد تقرير مدير جاهز للإرسال.")
            return
        self.send_pending_callback(messages=pending_reports)

    def send_expired_non_subscribers(self) -> None:
        password = str(self.store.settings.get("dashboard_password", "1234"))
        dlg = PasswordDialog(self, password)
        if dlg.exec() != QDialog.Accepted or not getattr(dlg, "ok", False):
            return

        expired_members = self._expired_members_with_end_date()
        if not expired_members:
            QMessageBox.information(self, "واتساب", "لا يوجد غير مشتركين حاليًا.")
            return

        picked_result = self.pick_expired_members_for_send(expired_members)
        if picked_result is None:
            return
        selected_members, custom_template = picked_result
        if not selected_members:
            QMessageBox.warning(self, "تنبيه", "لا يوجد أعضاء محددين للإرسال.")
            return

        queued = self.store.queue_expired_messages_for_members(
            selected_members,
            save=True,
            template=custom_template,
        )
        if not queued:
            QMessageBox.information(self, "واتساب", "لا توجد رسائل جديدة لغير المشتركين (قد تكون مجهزة بالفعل).")
            self.refresh()
            return

        self.refresh()
        self.send_pending_callback(messages=queued)

    def _expired_members_with_end_date(self) -> List[Dict[str, Any]]:
        today = date.today()
        result: List[Dict[str, Any]] = []
        for member in self.store.members:
            if str(member.get("current_status", "")) != "expired":
                continue
            end_raw = str(member.get("last_subscription_end", "")).strip()
            if not end_raw:
                continue
            end_value = parse_date(end_raw)
            if end_value >= today:
                continue
            enriched = dict(member)
            enriched["_expired_end_date"] = end_value
            result.append(enriched)
        result.sort(key=lambda m: m.get("_expired_end_date", date.min), reverse=True)
        return result

    def pick_expired_members_for_send(self, members: List[Dict[str, Any]]) -> Optional[tuple[List[Dict[str, Any]], Optional[str]]]:
        dialog = QDialog(self)
        dialog.setWindowTitle("اختيار غير المشتركين للإرسال")
        dialog.setLayoutDirection(Qt.RightToLeft)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(8)

        title = make_label("إرسال رسائل غير المشتركين", "dialogTitleSmall")
        title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title.setFont(QFont("Segoe UI", 10))
        root.addWidget(title)

        subtitle = make_label("اختار المدة ثم شيل تحديد أي شخص مش عايز تبعتله.", "smallMuted")
        subtitle.setFont(QFont("Segoe UI", 8))
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        body = QHBoxLayout()
        body.setDirection(QBoxLayout.Direction.LeftToRight)
        body.setSpacing(10)
        root.addLayout(body, 1)

        # Left panel: filters, message text, and actions.
        left_panel = QFrame()
        left_panel.setObjectName("settingsBox")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)
        left_panel.setMinimumWidth(420)
        left_panel.setMaximumWidth(520)
        body.addWidget(left_panel, 0)

        # Right panel: members list from top to bottom.
        right_panel = QFrame()
        right_panel.setObjectName("settingsBox")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(6)
        body.addWidget(right_panel, 1)

        period_row = QHBoxLayout()
        period_row.setDirection(QBoxLayout.Direction.RightToLeft)
        period_row.setSpacing(8)
        period_label = make_label("فترة الانتهاء", "fieldLabel")
        period_label.setFont(QFont("Segoe UI", 8))
        period_row.addWidget(period_label)

        period_combo = QComboBox()
        period_combo.addItem("آخر أسبوع", "week")
        period_combo.addItem("آخر شهر", "month")
        period_combo.addItem("آخر 3 شهور", "3months")
        period_combo.addItem("مدى مخصص", "custom")
        period_combo.setFixedHeight(28)
        period_combo.setFont(QFont("Segoe UI", 7))
        period_row.addWidget(period_combo)
        left_layout.addLayout(period_row)

        custom_row = QHBoxLayout()
        custom_row.setDirection(QBoxLayout.Direction.RightToLeft)
        custom_row.setSpacing(6)

        to_date = QDateEdit()
        to_date.setCalendarPopup(True)
        to_date.setDisplayFormat(DISPLAY_DATE_FMT)
        to_date.setDate(QDate.currentDate())
        to_date.setFont(QFont("Segoe UI", 7))
        to_date.setFixedHeight(26)

        from_date = QDateEdit()
        from_date.setCalendarPopup(True)
        from_date.setDisplayFormat(DISPLAY_DATE_FMT)
        from_date.setDate(QDate.currentDate().addDays(-30))
        from_date.setFont(QFont("Segoe UI", 7))
        from_date.setFixedHeight(26)

        to_label = make_label("إلى", "fieldLabel")
        to_label.setFont(QFont("Segoe UI", 8))
        custom_row.addWidget(to_label)
        custom_row.addWidget(to_date)
        from_label = make_label("من", "fieldLabel")
        from_label.setFont(QFont("Segoe UI", 8))
        custom_row.addWidget(from_label)
        custom_row.addWidget(from_date)
        left_layout.addLayout(custom_row)

        search_input = QLineEdit()
        search_input.setPlaceholderText("ابحث بالاسم أو الموبايل...")
        search_input.setObjectName("searchInput")
        search_input.setFixedHeight(26)
        search_input.setFont(QFont("Segoe UI", 7))
        left_layout.addWidget(search_input)

        count_label = make_label("", "muted")
        count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        count_label.setFont(QFont("Segoe UI", 8))
        left_layout.addWidget(count_label)

        message_label = make_label("نص الرسالة / العرض المرسل", "fieldLabel")
        message_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        message_label.setFont(QFont("Segoe UI", 8))
        left_layout.addWidget(message_label)

        message_input = QTextEdit()
        message_input.setObjectName("searchInput")
        message_input.setFont(QFont("Segoe UI", 7))
        message_input.setPlaceholderText(
            "اكتب نص الرسالة أو العرض هنا... يمكنك استخدام {name} و {end_date}."
        )
        message_input.setMinimumHeight(210)
        message_input.setPlainText(str(self.store.settings.get("expired_message_template", "")).strip())
        left_layout.addWidget(message_input, 1)

        tools_row = QHBoxLayout()
        tools_row.setDirection(QBoxLayout.Direction.RightToLeft)
        tools_row.setSpacing(6)

        select_visible_btn = QPushButton("تحديد الظاهر")
        select_visible_btn.setObjectName("secondaryButton")
        select_visible_btn.setFixedHeight(28)
        select_visible_btn.setFont(QFont("Segoe UI", 7))
        tools_row.addWidget(select_visible_btn)

        unselect_visible_btn = QPushButton("إلغاء تحديد الظاهر")
        unselect_visible_btn.setObjectName("secondaryButton")
        unselect_visible_btn.setFixedHeight(28)
        unselect_visible_btn.setFont(QFont("Segoe UI", 7))
        tools_row.addWidget(unselect_visible_btn)

        tools_row.addStretch(1)
        left_layout.addLayout(tools_row)

        buttons = QHBoxLayout()
        buttons.setDirection(QBoxLayout.Direction.RightToLeft)
        buttons.setSpacing(8)

        cancel_btn = QPushButton("إلغاء")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setMinimumHeight(34)
        cancel_btn.setFont(QFont("Segoe UI", 7))
        cancel_btn.clicked.connect(dialog.reject)
        buttons.addWidget(cancel_btn)

        ok_btn = QPushButton("تجهيز المحدد")
        ok_btn.setObjectName("primaryButton")
        ok_btn.setMinimumHeight(34)
        ok_btn.setFont(QFont("Segoe UI", 7))
        buttons.addWidget(ok_btn)
        buttons.addStretch(1)
        left_layout.addLayout(buttons)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(4)

        row_entries: List[Dict[str, Any]] = []
        for member in members:
            end_value = member.get("_expired_end_date", date.today())
            member_row = QFrame()
            member_row.setObjectName("settingsBox")
            member_layout = QHBoxLayout(member_row)
            member_layout.setContentsMargins(6, 4, 6, 4)
            member_layout.setSpacing(6)

            checkbox = QCheckBox()
            checkbox.setChecked(True)
            member_layout.addWidget(checkbox)

            line = make_label(
                f"{member.get('name', '-') or '-'} | {member.get('mobile', '-') or '-'} | انتهاء: {display_date(date_to_str(end_value))}",
                "muted",
            )
            line.setFont(QFont("Segoe UI", 7))
            line.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            member_layout.addWidget(line, 1)

            scroll_layout.addWidget(member_row)
            row_entries.append(
                {
                    "row": member_row,
                    "checkbox": checkbox,
                    "member": member,
                    "end_date": end_value,
                    "blob": f"{member.get('name', '')} {member.get('mobile', '')}".lower(),
                }
            )

        scroll_layout.addStretch(1)
        scroll.setWidget(scroll_content)
        right_layout.addWidget(scroll, 1)

        def accept_with_validation() -> None:
            if not message_input.toPlainText().strip():
                QMessageBox.warning(dialog, "تنبيه", "اكتب نص الرسالة أو العرض قبل التجهيز.")
                message_input.setFocus()
                return
            dialog.accept()

        ok_btn.clicked.connect(accept_with_validation)

        def active_date_range() -> tuple[date, date]:
            today = date.today()
            mode = str(period_combo.currentData() or "week")
            if mode == "week":
                return today - timedelta(days=7), today
            if mode == "month":
                return today - timedelta(days=30), today
            if mode == "3months":
                return today - timedelta(days=90), today
            start_value = qdate_to_py(from_date.date())
            end_value = qdate_to_py(to_date.date())
            if start_value <= end_value:
                return start_value, end_value
            return end_value, start_value

        def apply_filters() -> None:
            q = search_input.text().strip().lower()
            start_value, end_value = active_date_range()
            visible_rows = 0
            selected_visible = 0
            for entry in row_entries:
                end_date_value = entry["end_date"]
                in_period = start_value <= end_date_value <= end_value
                in_search = q in str(entry["blob"])
                visible = in_period and in_search
                row_widget = entry["row"]
                row_widget.setVisible(visible)
                if visible:
                    visible_rows += 1
                    if entry["checkbox"].isChecked():
                        selected_visible += 1
            count_label.setText(f"المعروض: {visible_rows} | المحدد من المعروض: {selected_visible}")

        def set_visible_checked(checked: bool) -> None:
            for entry in row_entries:
                row_widget = entry["row"]
                if row_widget.isVisible():
                    entry["checkbox"].setChecked(checked)
            apply_filters()

        period_combo.currentIndexChanged.connect(lambda _=0: apply_filters())
        from_date.dateChanged.connect(lambda _=QDate(): apply_filters())
        to_date.dateChanged.connect(lambda _=QDate(): apply_filters())
        search_input.textChanged.connect(lambda _="": apply_filters())
        select_visible_btn.clicked.connect(lambda: set_visible_checked(True))
        unselect_visible_btn.clicked.connect(lambda: set_visible_checked(False))

        apply_filters()
        fit_dialog_to_screen(dialog, 1460, 940)
        if dialog.exec() != QDialog.Accepted:
            return None

        selected_members: List[Dict[str, Any]] = []
        for entry in row_entries:
            if entry["checkbox"].isChecked():
                member_data = entry["member"]
                selected_members.append(member_data)
        custom_template = message_input.toPlainText().strip()
        if not custom_template:
            custom_template = str(self.store.settings.get("expired_message_template", "")).strip()
        return selected_members, (custom_template or None)

    def retry_failed(self) -> None:
        count = self.store.reset_failed_whatsapp()
        QMessageBox.information(self, "تم", f"تم إرجاع {count} رسالة فاشلة إلى المعلق.")
        self.refresh()

    def delete_sent_messages(self) -> None:
        reply = QMessageBox.question(
            self,
            "تأكيد حذف الرسائل المرسلة",
            "هل تريد حذف رسائل التذكير التي تم إرسالها؟\nلن يتم حذف أي إيصالات أو تجديدات أو رسائل انتهاء اشتراك.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        count = self.store.delete_sent_whatsapp_messages(older_than_hours=0, save=True)
        QMessageBox.information(self, "تم", f"تم حذف {count} رسالة تذكير مرسلة، والاحتفاظ بكافة الإيصالات والتجديدات وانتهاء الاشتراك.")
        self.refresh()

    def delete_failed_messages(self) -> None:
        """Delete only failed reminders; protect receipts, renewals, invoices, and expired notices."""
        reply = QMessageBox.question(
            self,
            "تأكيد حذف الرسائل الفاشلة",
            "هل تريد حذف رسائل التذكير الفاشلة؟\nلن يتم حذف أي إيصالات أو تجديدات أو رسائل انتهاء اشتراك فاشلة.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        before_count = len(self.store.whatsapp_messages)
        self.store.whatsapp_messages = [
            m for m in self.store.whatsapp_messages
            if not (str(m.get("status", "")) == "failed" and not is_receipt_protected_whatsapp_message(m))
        ]
        self.store.save_whatsapp()
        deleted_count = before_count - len(self.store.whatsapp_messages)
        QMessageBox.information(self, "تم", f"تم حذف {deleted_count} رسالة تذكير فاشلة، والاحتفاظ بالرسائل المحمية.")
        self.refresh()

    def send_unsent_messages(self) -> None:
        """Collect all unsent messages (pending + failed + scheduled), reset send delays, and show selection dialog."""
        self.store.promote_scheduled_whatsapp_messages(save=True)
        unsent = [
            m for m in self.store.whatsapp_messages
            if str(m.get("status", "")) in ("pending", "failed", "scheduled")
        ]
        if not unsent:
            QMessageBox.information(self, "واتساب", "لا توجد رسائل غير مرسلة (معلقة أو فاشلة أو مجدولة) للإرسال.")
            return

        # Any failed or scheduled items are reset to pending with send_after cleared so they can be processed immediately
        reset_count = 0
        for m in unsent:
            if str(m.get("status", "")) in ("failed", "scheduled") or str(m.get("send_after", "")).strip():
                m["status"] = "pending"
                m["send_after"] = ""
                m["error"] = ""
                reset_count += 1
        if reset_count:
            self.store.save_whatsapp()
            self.refresh()

        self.select_and_send(
            custom_messages=unsent,
            title="اختيار الرسائل غير المرسلة للإرسال (المعلقة + المجدولة + الفاشلة)",
        )

    def select_and_send(self, custom_messages: Optional[List[Dict[str, Any]]] = None, title: Optional[str] = None) -> None:
        if custom_messages is not None:
            pending = custom_messages
        else:
            pending = self.store.pending_whatsapp_messages(ready_only=True)
        if not pending:
            QMessageBox.information(self, "واتساب", "لا توجد رسائل معلقة للإرسال.")
            return

        def parse_created_at(value: Any) -> Any:
            created_str = str(value or "").strip()
            try:
                return datetime.fromisoformat(created_str)
            except Exception:
                return created_str

        sorted_pending = sorted(
            pending,
            key=lambda m: (
                parse_created_at(m.get("created_at", "")),
                str(m.get("message_id", "")),
            ),
            reverse=True,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(title or "اختيار رسائل واتساب للإرسال")
        dialog.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        container = QFrame()
        container.setObjectName("settingsBox")
        container.setLayoutDirection(Qt.RightToLeft)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(18, 18, 18, 18)
        container_layout.setSpacing(14)

        title_label = make_label(title or "اختر رسائل واتساب للإرسال", "dialogTitleSmall")
        title_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        container_layout.addWidget(title_label)

        subtitle = make_label(
            "الرسائل الأحدث تظهر أولاً. اختر من القائمة ثم اضغط إرسال.",
            "smallMuted",
        )
        subtitle.setWordWrap(True)
        container_layout.addWidget(subtitle)

        header = QHBoxLayout()
        header.setDirection(QBoxLayout.Direction.RightToLeft)
        header.setSpacing(10)

        header_label = make_label(f"{len(sorted_pending)} رسالة معلقة", "muted")
        header_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.addWidget(header_label, 1)

        select_all_btn = QPushButton("تحديد الكل")
        select_all_btn.setObjectName("secondaryButton")
        select_all_btn.setFixedHeight(28)
        select_all_btn.setFont(QFont("Segoe UI", 8))
        header.addWidget(select_all_btn)

        unselect_all_btn = QPushButton("إلغاء التحديد")
        unselect_all_btn.setObjectName("secondaryButton")
        unselect_all_btn.setFixedHeight(28)
        unselect_all_btn.setFont(QFont("Segoe UI", 8))
        header.addWidget(unselect_all_btn)

        container_layout.addLayout(header)

        type_filter_row = QHBoxLayout()
        type_filter_row.setDirection(QBoxLayout.Direction.RightToLeft)
        type_filter_row.setSpacing(8)

        type_filter_label = make_label("نوع الرسالة", "fieldLabel")
        type_filter_label.setFont(QFont("Segoe UI", 8))
        type_filter_row.addWidget(type_filter_label)

        pending_type_filter = QComboBox()
        pending_type_filter.setFixedHeight(26)
        pending_type_filter.setFont(QFont("Segoe UI", 8))
        pending_type_filter.addItem("الكل", "all")
        pending_type_filter.addItem("الإيصالات", "receipt")
        pending_type_filter.addItem("التذكيرات", "reminder")
        pending_type_filter.addItem("غير المشتركين", "expired")
        pending_type_filter.addItem("تقرير المدير", "daily_report")
        type_filter_row.addWidget(pending_type_filter)
        container_layout.addLayout(type_filter_row)

        search_input = QLineEdit()
        search_input.setPlaceholderText("ابحث داخل الرسائل المعلقة...")
        search_input.setFont(QFont("Segoe UI", 7))
        search_input.setFixedHeight(22)
        search_input.setObjectName("searchInput")
        container_layout.addWidget(search_input)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        scroll_content = QWidget()
        scroll_content.setLayoutDirection(Qt.RightToLeft)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(4)

        row_entries: List[tuple[QFrame, QCheckBox, str, Dict[str, Any]]] = []
        checkboxes: List[tuple[QCheckBox, Dict[str, Any]]] = []
        for msg in sorted_pending:
            message_text = str(msg.get('message', '')).replace('\n', ' ')
            message_short = message_text[:90] + ("..." if len(message_text) > 90 else "")
            created_at = str(msg.get('created_at', '') or '')
            msg_type = str(msg.get('type', ''))
            search_blob = (
                f"{created_at} {msg.get('recipient_name', '')} {msg.get('mobile', '')} "
                f"{whatsapp_type_ar(msg_type)} {message_short}"
            ).lower()

            row = QFrame()
            row.setObjectName("settingsBox")
            row.setLayoutDirection(Qt.RightToLeft)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 4, 6, 4)
            row_layout.setSpacing(4)

            checkbox = QCheckBox()
            checkbox.setChecked(True)
            checkbox.setProperty("message_id", str(msg.get("message_id", "")))
            row_layout.addWidget(checkbox)

            reason = self.store.get_whatsapp_unsendable_reason(msg, manual=True)
            if reason:
                compact_line = make_label(
                    f"⚠️ [{reason}] | {created_at} | {msg.get('recipient_name', '-') or '-'} | {msg.get('mobile', '-') or '-'} | {whatsapp_type_ar(msg_type)} | {message_short}",
                    "warning",
                )
                compact_line.setStyleSheet("color: #FFB020; font-weight: bold;")
            else:
                compact_line = make_label(
                    f"{created_at} | {msg.get('recipient_name', '-') or '-'} | {msg.get('mobile', '-') or '-'} | {whatsapp_type_ar(msg_type)} | {message_short}",
                    "muted",
                )
            compact_line.setFont(QFont("Segoe UI", 7))
            compact_line.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            compact_line.setWordWrap(False)
            row_layout.addWidget(compact_line, 1)

            scroll_layout.addWidget(row)
            row_entries.append((row, checkbox, search_blob, msg))
            checkboxes.append((checkbox, msg))

        scroll_layout.addStretch(1)
        scroll.setWidget(scroll_content)
        container_layout.addWidget(scroll, 1)

        def apply_type_filter() -> None:
            query = search_input.text().lower().strip()
            selected_type = str(pending_type_filter.currentData() or "all")
            for row, _, blob, msg in row_entries:
                msg_type = str(msg.get("type", ""))
                matches_type = selected_type == "all" or msg_type == selected_type
                matches_query = not query or query in blob
                row.setVisible(matches_type and matches_query)

        search_input.textChanged.connect(apply_type_filter)
        pending_type_filter.currentIndexChanged.connect(apply_type_filter)
        apply_type_filter()

        buttons = QHBoxLayout()
        buttons.setDirection(QBoxLayout.Direction.RightToLeft)
        buttons.setSpacing(10)

        cancel_btn = QPushButton("إلغاء")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.setFixedHeight(26)
        cancel_btn.setFont(QFont("Segoe UI", 7))
        cancel_btn.clicked.connect(dialog.reject)
        buttons.addWidget(cancel_btn)

        ok_btn = QPushButton("إرسال المحدد")
        ok_btn.setObjectName("primaryButton")
        ok_btn.setFixedHeight(26)
        ok_btn.setFont(QFont("Segoe UI", 7))
        ok_btn.clicked.connect(dialog.accept)
        buttons.addWidget(ok_btn)

        container_layout.addLayout(buttons)
        layout.addWidget(container)

        select_all_btn.clicked.connect(lambda: [cb.setChecked(True) for cb, _ in checkboxes])
        unselect_all_btn.clicked.connect(lambda: [cb.setChecked(False) for cb, _ in checkboxes])

        select_all_btn.clicked.connect(lambda: [cb.setChecked(True) for cb, _ in checkboxes])
        unselect_all_btn.clicked.connect(lambda: [cb.setChecked(False) for cb, _ in checkboxes])

        fit_dialog_to_screen(dialog, 1500, 940)
        if dialog.exec() != QDialog.Accepted:
            return

        chosen = [msg for cb, msg in checkboxes if cb.isChecked()]
        if not chosen:
            QMessageBox.warning(self, "تنبيه", "اختر على الأقل رسالة واحدة للإرسال.")
            return

        for m in chosen:
            m["status"] = "pending"
            m["send_after"] = ""
            m["error"] = ""
        self.store.save_whatsapp()

        self.send_pending_callback(messages=chosen)

    def open_message_from_row(self, row: int) -> None:
        if row < 0:
            return
        msg = self._rows_by_index.get(row)
        if not msg:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("تفاصيل الرسالة")
        dialog.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        details = (
            f"النوع: {whatsapp_type_ar(str(msg.get('type', '')))}\n"
            f"الاسم: {msg.get('recipient_name', '-')}\n"
            f"الموبايل: {msg.get('mobile', '-')}\n"
            f"الحالة: {whatsapp_status_ar(str(msg.get('status', 'pending')))}\n"
            f"تاريخ الإنشاء: {msg.get('created_at', '-')}\n"
            f"وقت الإرسال: {msg.get('sent_at', '-')}\n"
            f"\nالرسالة:\n{msg.get('message', '')}"
        )
        if msg.get("error"):
            details += f"\n\nالخطأ:\n{msg.get('error', '')}"

        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(details)
        text.setMinimumWidth(640)
        text.setMinimumHeight(320)
        layout.addWidget(text)

        buttons = QHBoxLayout()
        buttons.setDirection(QBoxLayout.Direction.RightToLeft)
        close_btn = QPushButton("إغلاق")
        close_btn.setObjectName("secondaryButton")
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        fit_dialog_to_screen(dialog, 720, 420)
        dialog.exec()

    def open_selected_message(self) -> None:
        row = self.table.currentRow()
        self.open_message_from_row(row)

    def selected_message_ids(self) -> List[str]:
        ids: List[str] = []
        for item_obj in self.table.selectedItems():
            if item_obj.column() == 0:
                message_id = item_obj.data(Qt.UserRole) or item_obj.text()
                if message_id and str(message_id) not in ids:
                    ids.append(str(message_id))
        if not ids and self.table.currentRow() >= 0:
            first = self.table.item(self.table.currentRow(), 0)
            if first is not None:
                message_id = first.data(Qt.UserRole) or first.text()
                if message_id:
                    ids.append(str(message_id))
        return ids

    def delete_selected(self) -> None:
        ids = self.selected_message_ids()
        if not ids:
            QMessageBox.warning(self, "تنبيه", "اختار رسالة واحدة أو أكثر من الجدول الأول.")
            return

        protected = [
            str(msg.get("message_id", ""))
            for msg in self.store.whatsapp_messages
            if str(msg.get("message_id", "")) in set(ids) and is_receipt_protected_whatsapp_message(msg)
        ]
        if protected:
            QMessageBox.warning(
                self,
                "تنبيه",
                "لا يمكن حذف رسائل الإيصال؛ هذه الرسائل محمية تلقائيًا.",
            )
            ids = [msg_id for msg_id in ids if msg_id not in protected]
            if not ids:
                return

        reply = QMessageBox.question(
            self,
            "تأكيد الحذف",
            f"هل تريد حذف {len(ids)} رسالة محددة؟\nهذا الإجراء لا يمكن التراجع عنه.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        count = self.store.delete_whatsapp_messages(ids)
        QMessageBox.information(self, "تم", f"تم حذف {count} رسالة.")
        self.refresh()

    def delete_all_messages(self) -> None:
        reply = QMessageBox.question(
            self,
            "تأكيد حذف رسائل التذكير",
            "هل تريد حذف رسائل التذكير؟\nلن يتم حذف أي إيصالات أو رسائل تجديد أو انتهاء اشتراك (محمية دائمًا).",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        before_count = len(self.store.whatsapp_messages)
        self.store.whatsapp_messages = [
            m
            for m in self.store.whatsapp_messages
            if is_receipt_protected_whatsapp_message(m)
        ]
        self.store.save_whatsapp()
        deleted_count = before_count - len(self.store.whatsapp_messages)
        kept_count = len(self.store.whatsapp_messages)
        QMessageBox.information(
            self,
            "تم",
            f"تم حذف {deleted_count} رسالة تذكير، والاحتفاظ بـ {kept_count} رسالة محمية (إيصالات، تجديدات، انتهاء اشتراك).",
        )
        self.refresh()

    def resend_selected(self) -> None:
        ids = self.selected_message_ids()
        if not ids:
            QMessageBox.warning(self, "تنبيه", "اختار رسالة واحدة أو أكثر من الجدول الأول.")
            return
        count = self.store.requeue_whatsapp_messages(ids)
        QMessageBox.information(self, "تم", f"تم تجهيز {count} رسالة جديدة في المعلق لإعادة الإرسال.")
        self.refresh()

    def force_resend_selected(self) -> None:
        """Force resend selected messages even if they were already sent."""
        ids = self.selected_message_ids()
        if not ids:
            QMessageBox.warning(self, "تنبيه", "اختار رسالة واحدة أو أكثر من الجدول الأول.")
            return
        reply = QMessageBox.question(
            self,
            "تأكيد الإرسال القسري",
            f"هل تريد إعادة إرسال {len(ids)} رسالة حتى لو كانت مُرسلة بالفعل؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        # Reset status to pending for force resend
        count = 0
        for msg_id in ids:
            for msg in self.store.whatsapp_messages:
                if str(msg.get("message_id", "")) == msg_id:
                    msg["status"] = "pending"
                    msg["sent_at"] = ""
                    msg["error"] = ""
                    count += 1
                    break
        self.store.save_whatsapp()
        QMessageBox.information(self, "تم", f"تم تحضير {count} رسالة لإعادة الإرسال القسري.")
        self.refresh()

    def refresh(self) -> None:
        status_filter = self.status_filter.currentData() if hasattr(self, "status_filter") else "all"
        type_filter = self.type_filter.currentData() if hasattr(self, "type_filter") else "all"
        search_text = self.search.text() if hasattr(self, "search") else ""
        
        rows = self.store.filtered_whatsapp_messages(status_filter, search_text)
        
        # Apply type filter
        if type_filter != "all":
            rows = [m for m in rows if str(m.get("type", "")) == type_filter]
        
        rows = sorted(
            rows,
            key=lambda m: (
                str(m.get("created_at", "")),
                str(m.get("message_id", "")),
            ),
            reverse=True,
        )
        pending = len(self.store.pending_whatsapp_messages())
        self._rows_by_index = {}
        self.count_lbl.setText(f"{len(rows)} رسالة معروضة | المعلق: {pending}")
        headers = ["ID", "النوع", "الاسم", "الموبايل", "حالة العضو", "الحالة", "تاريخ الإنشاء", "وقت الإرسال", "الرسالة"]
        self.table.setUpdatesEnabled(False)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 120)
        self.table.setColumnWidth(7, 120)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        for r, msg in enumerate(rows):
            self._rows_by_index[r] = msg
            member_status = "غير معروف"
            mobile = str(msg.get("mobile", ""))
            member = next((m for m in self.store.members if normalize_mobile(str(m.get("mobile", ""))) == normalize_mobile(mobile)), None)
            if member is not None:
                member_status = status_ar(str(member.get("current_status", "expired")))

            values = [
                msg.get("message_id", ""),
                whatsapp_type_ar(str(msg.get("type", ""))),
                msg.get("recipient_name", ""),
                msg.get("mobile", ""),
                member_status,
                whatsapp_status_ar(str(msg.get("status", "pending"))),
                msg.get("created_at", ""),
                msg.get("sent_at", ""),
                str(msg.get("message", "")).replace("\n", "  |  ")[:140],
            ]
            for c, v in enumerate(values):
                cell = item(v)
                if c == 0:
                    cell.setData(Qt.UserRole, msg.get("message_id"))
                if c == 4:
                    if msg.get("status") == "sent":
                        cell.setForeground(Qt.GlobalColor.green)
                    elif msg.get("status") == "failed":
                        cell.setForeground(Qt.GlobalColor.red)
                self.table.setItem(r, c, cell)
            self.table.setRowHeight(r, 32)
        self.table.setUpdatesEnabled(True)


class FingerprintDevicePage(BasePage):
    def __init__(self, store: Store) -> None:
        super().__init__(store, "جهاز البصمة", "أجهزة البصمة والتحكم بالدخول")

        container = QFrame()
        container.setObjectName("settingsBox")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.status_label = make_label("لم يتم اختبار الاتصال بعد", "sectionTitle")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addSpacing(24)
        layout.addWidget(self.status_label)
        layout.addSpacing(12)

        self.test_btn = QPushButton("اختبار الاتصال بجهاز البصمة")
        self.test_btn.setObjectName("primaryButton")
        self.test_btn.setCursor(Qt.PointingHandCursor)
        self.test_btn.clicked.connect(self.test_connection)
        layout.addWidget(self.test_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(24)

        self.sync_btn = QPushButton("مزامنة ESP32 الآن")
        self.sync_btn.setObjectName("primaryButton")
        self.sync_btn.setCursor(Qt.PointingHandCursor)
        self.sync_btn.clicked.connect(self.sync_members)
        layout.addWidget(self.sync_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.sync_status_label = make_label("لم تتم مزامنة قاعدة الأعضاء بعد", "muted")
        self.sync_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sync_status_label.setWordWrap(True)
        layout.addWidget(self.sync_status_label)
        layout.addSpacing(12)

        self.member_counts_label = make_label("", "muted")
        self.member_counts_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.member_counts_label)
        layout.addSpacing(12)

        self.push_test_btn = QPushButton("دفع قاعدة اختبار من عضوين")
        self.push_test_btn.setObjectName("primaryButton")
        self.push_test_btn.setCursor(Qt.PointingHandCursor)
        self.push_test_btn.clicked.connect(self.push_test_members)
        layout.addWidget(self.push_test_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        test_permissions = QHBoxLayout()
        test_permissions.setSpacing(10)
        self.deny_test_btn = QPushButton("منع MEM-00001")
        self.deny_test_btn.setObjectName("secondaryButton")
        self.deny_test_btn.clicked.connect(lambda: self.push_test_permission(False))
        self.allow_test_btn = QPushButton("السماح MEM-00001")
        self.allow_test_btn.setObjectName("secondaryButton")
        self.allow_test_btn.clicked.connect(lambda: self.push_test_permission(True))
        test_permissions.addWidget(self.deny_test_btn, 1)
        test_permissions.addWidget(self.allow_test_btn, 1)
        layout.addLayout(test_permissions)

        layout.addStretch()

        self.root.addWidget(container, 1)

    def test_connection(self) -> None:
        if not esp_client.is_enabled(self.store.settings):
            self.status_label.setText("ESP غير مفعل. من فضلك فعّل الاتصال بـ ESP من الإعدادات أولاً.")
            return
        self.test_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = esp_client.get_esp_status(self.store.settings)
        finally:
            QApplication.restoreOverrideCursor()
            self.test_btn.setEnabled(True)

        if not result.get("success"):
            kind = result.get("error_kind", "unknown")
            detail = result.get("error_detail", "")
            self.status_label.setText(f"فشل الاتصال ({kind}): {detail}")
            return

        self.status_label.setText(
            "متصل ✓\n"
            f"الجهاز: {result.get('device', '-')}\n"
            f"الواي فاي: {result.get('wifi', '-')}\n"
            f"قارئ البصمة: {'موجود' if result.get('fingerprint') else 'غير موجود'}\n"
            f"عدد الأعضاء المحملين: {result.get('members', '-')}"
        )

    def _test_members_payload(self, first_allowed: bool = True) -> Dict[str, Dict[str, Any]]:
        return {
            "MEM-00001": {"fingerprint_id": 1, "allowed": first_allowed},
            "MEM-00002": {"fingerprint_id": 2, "allowed": False},
        }

    def sync_members(self) -> None:
        if not esp_client.is_enabled(self.store.settings):
            self.sync_status_label.setText("SYNC FAILED: ESP غير مفعل في الإعدادات")
            return
        self.sync_btn.setEnabled(False)
        self.sync_status_label.setText("جاري مزامنة قاعدة الأعضاء...")
        progress = QProgressDialog("جاري مزامنة قاعدة الأعضاء مع ESP32...", "إلغاء", 0, 0, self)
        progress.setWindowTitle("مزامنة ESP32")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        thread = ESPOperationThread("sync", self.store.settings, members=self.store.esp_members_payload())
        progress._esp_thread = thread

        def finished(result: Dict[str, Any]) -> None:
            progress.close()
            self.sync_btn.setEnabled(True)
            if result.get("success") is True:
                self.sync_status_label.setText(f"SYNC SUCCESS: تم إرسال {result.get('members', 0)} عضو")
            else:
                error = result.get("error", result.get("error_detail", "فشل مزامنة ESP32"))
                self.sync_status_label.setText(f"SYNC FAILED: {error}")

        thread.done.connect(finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        progress.show()

    def _push_test_payload(self, members: Dict[str, Dict[str, Any]]) -> None:
        if not self.store.esp_command_allowed():
            self.status_label.setText("ESP غير متصل أو لم يتم تحديث حالته خلال آخر 60 ثانية.")
            return
        self.push_test_btn.setEnabled(False)
        self.deny_test_btn.setEnabled(False)
        self.allow_test_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = esp_client.push_members(self.store.settings, members)
        finally:
            QApplication.restoreOverrideCursor()
            self.push_test_btn.setEnabled(True)
            self.deny_test_btn.setEnabled(True)
            self.allow_test_btn.setEnabled(True)

        if not result.get("success"):
            error = result.get("error", result.get("error_detail", "فشل مزامنة قاعدة الأعضاء"))
            self.status_label.setText(f"فشل إرسال قاعدة الاختبار: {error}")
            return

        self.status_label.setText(
            "تم إرسال قاعدة الاختبار ✓\n"
            f"الأعضاء المؤكدون من ESP: {result.get('members', '-')}"
        )

    def push_test_members(self) -> None:
        self._push_test_payload(self._test_members_payload(True))

    def push_test_permission(self, allowed: bool) -> None:
        self._push_test_payload(self._test_members_payload(allowed))

    def refresh(self) -> None:
        enrolled = sum(1 for member in self.store.members if str(member.get("fingerprint_id", "")).strip())
        without_fingerprint = len(self.store.members) - enrolled
        self.member_counts_label.setText(
            f"إجمالي الأعضاء: {len(self.store.members)}\n"
            f"لديهم بصمة: {enrolled}  |  بدون بصمة: {without_fingerprint}"
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.store = Store()
        self.setWindowTitle("HULK GYM - نظام إدارة النادي")
        self.resize(1440, 850)
        self.setLayoutDirection(Qt.LeftToRight)

        self.central = QWidget()
        self.central.setObjectName("central")
        self.central.setLayoutDirection(Qt.LeftToRight)
        self.setCentralWidget(self.central)
        main = QGridLayout(self.central)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.setColumnStretch(0, 1)
        main.setColumnStretch(1, 0)

        content_widget = QWidget()
        content_widget.setLayoutDirection(Qt.RightToLeft)
        content = QVBoxLayout(content_widget)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        main.addWidget(content_widget, 0, 0)

        self.sidebar = self.build_sidebar()
        main.addWidget(self.sidebar, 0, 1)

        self.stack = QStackedWidget()
        content.addWidget(self.stack, 1)

        self.pages: Dict[str, QWidget] = {}
        self.whatsapp_thread: Optional[WhatsAppSendThread] = None
        self.google_queue_flush_thread: Optional[GoogleContactsQueueFlushThread] = None
        self.whatsapp_progress_dialog: Optional[QProgressDialog] = None
        self.whatsapp_silent = False
        self.whatsapp_startup_prompted = False
        self.last_whatsapp_hourly_prompt_key = ""
        self.esp_startup_sync_thread: Optional[ESPOperationThread] = None
        self.esp_status_thread: Optional[ESPOperationThread] = None
        self.esp_scan_thread: Optional[ESPOperationThread] = None
        self.esp_display_thread: Optional[ESPOperationThread] = None
        self.esp_scan_poll_timer = QTimer(self)
        self.esp_scan_poll_timer.setInterval(800)
        self.esp_scan_poll_timer.timeout.connect(self.poll_esp_last_scan)
        self.last_scan_sequence: Optional[int] = None
        self.scan_popup: Optional[QMessageBox] = None
        self.esp_status_label = QLabel("ESP: غير متصل")
        self.esp_status_label.setObjectName("espStatusLabel")
        self.esp_status_label.setMinimumWidth(150)
        self.statusBar().addWidget(self.esp_status_label)
        self.add_pages()
        self.apply_styles()
        self.install_shortcuts()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.auto_timer = QTimer(self)
        self.auto_timer.setInterval(60_000)
        self.auto_timer.timeout.connect(self.run_auto_whatsapp_checks)
        self.auto_timer.start()
        QTimer.singleShot(5_000, self.run_auto_whatsapp_checks)
        QTimer.singleShot(1_500, self.start_background_google_contacts_flush)
        QTimer.singleShot(2_000, self.start_background_esp_sync)
        QTimer.singleShot(3_000, self.start_esp_scan_polling)
        self.esp_retry_timer = QTimer(self)
        self.esp_retry_timer.setInterval(60_000)
        self.esp_retry_timer.timeout.connect(self.refresh_esp_status)
        self.esp_retry_timer.start()

    def start_background_esp_sync(self) -> None:
        if self.store.esp_enrollment_active:
            return
        if not esp_client.is_enabled(self.store.settings):
            self.set_esp_status(False, "غير مفعل")
            return
        if self.esp_startup_sync_thread is not None and self.esp_startup_sync_thread.isRunning():
            return
        self.set_esp_status(None, "جاري الاتصال...")
        thread = ESPOperationThread("sync", self.store.settings, members=self.store.esp_members_payload())
        self.esp_startup_sync_thread = thread
        thread.done.connect(self.on_background_esp_sync_done)
        thread.finished.connect(self.on_background_esp_sync_finished)
        thread.start()

    def on_background_esp_sync_done(self, result: Dict[str, Any]) -> None:
        if result.get("success") is True:
            self.store.esp_connected = True
            self.store.esp_status_checked_at = time.monotonic()
            self.set_esp_status(True)
            self.statusBar().showMessage(f"تمت مزامنة {result.get('members', 0)} عضو مع ESP32.", 5000)
        else:
            self.store.esp_connected = False
            self.store.esp_status_checked_at = time.monotonic()
            self.set_esp_status(False)
            error = result.get("error", result.get("error_detail", "ESP غير متصل"))
            self.statusBar().showMessage(f"ESP غير متزامن: {error}", 7000)

    def on_background_esp_sync_finished(self) -> None:
        self.esp_startup_sync_thread = None

    def set_esp_status(self, connected: Optional[bool], detail: str = "") -> None:
        if connected is True:
            self.esp_status_label.setText("ESP: متصل ✓")
            self.esp_status_label.setStyleSheet("color: #2e7d32; font-weight: 700;")
        elif connected is False:
            suffix = f" ({detail})" if detail else ""
            self.esp_status_label.setText(f"ESP: غير متصل{suffix}")
            self.esp_status_label.setStyleSheet("color: #c62828; font-weight: 700;")
        else:
            self.esp_status_label.setText(f"ESP: {detail or 'جاري الاتصال...'}")
            self.esp_status_label.setStyleSheet("color: #b26a00; font-weight: 700;")

    def retry_esp_if_disconnected(self) -> None:
        self.refresh_esp_status()

    def refresh_esp_status(self) -> None:
        if self.store.esp_enrollment_active:
            return
        if not esp_client.is_enabled(self.store.settings):
            self.store.esp_connected = False
            self.store.esp_status_checked_at = time.monotonic()
            self.set_esp_status(False, "غير مفعل")
            return
        if self.esp_status_thread is not None and self.esp_status_thread.isRunning():
            return
        thread = ESPOperationThread("status", self.store.settings)
        self.esp_status_thread = thread

        def status_done(result: Dict[str, Any]) -> None:
            self.store.esp_connected = result.get("success") is True
            self.store.esp_status_checked_at = time.monotonic()
            self.set_esp_status(self.store.esp_connected)

        thread.done.connect(status_done)
        thread.finished.connect(lambda: setattr(self, "esp_status_thread", None))
        thread.start()

    def start_esp_scan_polling(self) -> None:
        self.esp_scan_poll_timer.start()

    def poll_esp_last_scan(self) -> None:
        if self.store.esp_enrollment_active:
            return
        if not self.store.esp_command_allowed():
            return
        if self.esp_scan_thread is not None and self.esp_scan_thread.isRunning():
            return
        thread = ESPOperationThread("last_scan", self.store.settings)
        self.esp_scan_thread = thread

        def scan_done(result: Dict[str, Any]) -> None:
            if result.get("success") is not True:
                return
            sequence = result.get("sequence")
            if not isinstance(sequence, int) or sequence <= 0 or sequence == self.last_scan_sequence:
                return
            if not str(result.get("member_id", "")).strip() or result.get("fingerprint_id", 0) in (0, None):
                return
            self.last_scan_sequence = sequence
            self.handle_esp_scan(result)

        thread.done.connect(scan_done)
        thread.finished.connect(lambda: setattr(self, "esp_scan_thread", None))
        thread.start()

    def handle_esp_scan(self, scan: Dict[str, Any]) -> None:
        member_id = str(scan.get("member_id", "")).strip()
        member = next((m for m in self.store.members if str(m.get("member_id", "")) == member_id), None)
        if member is None:
            return
        member_data = {
            "sequence": scan.get("sequence"),
            "name": str(member.get("name", "")),
            "member_id": member_id,
            "plan_type": str(member.get("last_subscription_type", "")),
            "end_date": display_date(member.get("last_subscription_end", "")),
            "last_payment": str(member.get("last_payment_date", "")),
            "days_left": calculate_days_left(member.get("last_subscription_end", "")),
            "fingerprint_id": scan.get("fingerprint_id", member.get("fingerprint_id", "")),
            "allowed": bool(scan.get("allowed", False)),
        }
        self.show_scan_popup(member_data)
        if self.store.esp_command_allowed():
            thread = ESPOperationThread("display_member", self.store.settings, member_data=member_data)
            self.esp_display_thread = thread
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda: setattr(self, "esp_display_thread", None))
            thread.start()

    def show_scan_popup(self, member_data: Dict[str, Any]) -> None:
        if self.scan_popup is not None:
            self.scan_popup.close()
        access = "مسموح بالدخول" if member_data["allowed"] else "الدخول مرفوض"
        popup = QDialog(self)
        popup.setWindowTitle("ملف العضو")
        popup.setLayoutDirection(Qt.RightToLeft)
        popup.setStyleSheet(
            "QDialog { background: #101820; color: white; }"
            "QLabel { color: white; }"
            "QPushButton { background: #a8f05a; color: #101820; font-size: 22px; "
            "font-weight: 700; padding: 14px 44px; border-radius: 8px; }"
        )
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(60, 50, 60, 45)
        layout.setSpacing(18)

        icon = QLabel("👤")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 96px; color: #a8f05a;")
        layout.addWidget(icon)

        name_label = QLabel(member_data["name"] or "عضو")
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("font-size: 42px; font-weight: 800; color: #a8f05a;")
        layout.addWidget(name_label)

        access_label = QLabel(access)
        access_label.setAlignment(Qt.AlignCenter)
        access_label.setStyleSheet(
            f"font-size: 30px; font-weight: 800; color: {'#61e294' if member_data['allowed'] else '#ff6b6b'};"
        )
        layout.addWidget(access_label)

        details = QLabel(
            f"رقم العضو: {member_data['member_id']}\n"
            f"رقم البصمة: {member_data['fingerprint_id']}\n"
            f"الخطة: {member_data['plan_type'] or '-'}\n"
            f"نهاية الاشتراك: {member_data['end_date']}\n"
            f"آخر دفع: {member_data['last_payment']}"
        )
        details.setAlignment(Qt.AlignCenter)
        details.setStyleSheet("font-size: 25px; line-height: 1.5; color: #f1f5f9;")
        layout.addWidget(details)
        layout.addStretch(1)

        close_button = QPushButton("إغلاق")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(popup.close)
        layout.addWidget(close_button, alignment=Qt.AlignCenter)

        self.scan_popup = popup
        popup.finished.connect(lambda: setattr(self, "scan_popup", None) if self.scan_popup is popup else None)
        popup.showFullScreen()
        QTimer.singleShot(10_000, lambda p=popup: p.close() if self.scan_popup is p else None)

    def start_background_google_contacts_flush(self) -> None:
        if self.google_queue_flush_thread is not None and self.google_queue_flush_thread.isRunning():
            return
        thread = GoogleContactsQueueFlushThread(self.store)
        self.google_queue_flush_thread = thread
        thread.done.connect(self.on_background_google_contacts_flush_done)
        thread.finished.connect(self.on_background_google_contacts_flush_finished)
        thread.start()

    def on_background_google_contacts_flush_done(self, result: Dict[str, Any]) -> None:
        if not result.get("ok"):
            self.statusBar().showMessage("فشل مزامنة Google التلقائية عند بدء التشغيل.", 7000)
            return
        synced_count = int(result.get("synced_count", 0) or 0)
        if synced_count > 0:
            self.statusBar().showMessage(f"تمت مزامنة {synced_count} رقمًا تلقائيًا مع Google Contacts.", 7000)

    def on_background_google_contacts_flush_finished(self) -> None:
        self.google_queue_flush_thread = None

    def build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        side.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(6, 18, 6, 20)
        layout.setSpacing(8)

        layout.addSpacing(8)

        self.nav_buttons: Dict[str, QPushButton] = {}
        nav = [
            ("dashboard", "🏠  الرئيسية"),
            ("manager", "👔  المدير"),
            ("members", "👥  الأعضاء"),
            ("payments", "💵  المدفوعات"),
            ("whatsapp", "🟢  واتساب"),
            ("fingerprint", "👆  جهاز البصمة"),
            ("settings", "⚙  الإعدادات"),
        ]
        for key, text in nav:
            btn = QPushButton(text)
            btn.setObjectName("navButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self.navigate(k))
            btn.setMinimumHeight(48)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.nav_buttons[key] = btn
            layout.addWidget(btn)
        layout.addStretch(1)
        user = QFrame()
        user.setObjectName("userBox")
        u_layout = QVBoxLayout(user)
        u_layout.setContentsMargins(12, 12, 12, 12)
        u_layout.addWidget(make_label("المدير", "userName"))
        u_layout.addWidget(make_label("مدير النظام", "smallMuted"))
        layout.addWidget(user)
        return side

    def add_pages(self) -> None:
        self.pages["dashboard"] = DashboardPage(
            self.store,
            self.open_new_dialog,
            self.open_renewal_dialog,
            self.open_smart_dialog,
            self.open_remaining_dialog,
            self.open_expense_dialog,
            self.open_member_search,
            self.open_remaining_members_page,
            self.open_expired_members_page,
            self.open_unified_entry_page,
            max_width=1900,
        )
        self.pages["smart_subscription"] = AddSubscriptionPage(
            self.store,
            "smart",
            lambda: self.navigate("dashboard"),
            lambda: self.handle_post_save(types=["receipt"]),
            self.open_remaining_dialog,
        )
        self.pages["new_subscription"] = AddSubscriptionPage(
            self.store,
            "new_subscription",
            lambda: self.navigate("dashboard"),
            lambda: self.handle_post_save(types=["receipt"]),
            self.open_remaining_dialog,
        )
        self.pages["renewal"] = AddSubscriptionPage(
            self.store,
            "renewal",
            lambda: self.navigate("dashboard"),
            lambda: self.handle_post_save(types=["receipt"]),
            self.open_remaining_dialog,
        )
        self.pages["remaining"] = RemainingPaymentPage(
            self.store,
            lambda: self.navigate("dashboard"),
            lambda: self.handle_post_save(types=["receipt"]),
        )
        self.pages["unified_entry"] = UnifiedEntryPage(
            self.store,
            lambda: self.navigate("dashboard"),
            lambda: self.handle_post_save(types=["receipt"]),
        )
        self.pages["expense"] = AddExpensePage(
            self.store,
            lambda: self.navigate("dashboard"),
            self.refresh_all,
        )
        self.pages["members"] = MembersTablePage(
            self.store,
            "all",
            "الأعضاء",
            "كل أعضاء النادي مع البحث وفلتر النوع والحالة",
            self.open_member_page,
        )
        self.pages["payments"] = PaymentsPage(self.store)
        self.pages["whatsapp"] = WhatsAppPage(self.store, self.send_pending_whatsapp)
        self.pages["member_details"] = MemberDetailsPage(
            self.store,
            self.navigate_back_to_members,
            self.open_member_renewal,
        )
        self.pages["settings"] = SettingsPage(self.store)
        self.pages["fingerprint"] = FingerprintDevicePage(self.store)
        # Manager page (password protected)
        self.pages["manager"] = ManagerPage(self.store)
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.navigate("dashboard")

    def install_shortcuts(self) -> None:
        refresh_action = QAction(self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self.refresh_current)
        self.addAction(refresh_action)
        add_action = QAction(self)
        add_action.setShortcut(QKeySequence("Ctrl+N"))
        add_action.triggered.connect(self.open_new_dialog)
        self.addAction(add_action)
        renew_action = QAction(self)
        renew_action.setShortcut(QKeySequence("Ctrl+R"))
        renew_action.triggered.connect(self.open_renewal_dialog)
        self.addAction(renew_action)
        remaining_action = QAction(self)
        remaining_action.setShortcut(QKeySequence("Ctrl+P"))
        remaining_action.triggered.connect(self.open_remaining_dialog)
        self.addAction(remaining_action)

    def navigate(self, key: str) -> None:
        if key == "whatsapp" and not self.store.settings.get("whatsapp_enabled", True):
            QMessageBox.warning(self, "واتساب معطل", "رجاءً فعّل واتساب من صفحة الإعدادات قبل فتح صفحة واتساب.")
            btn = self.nav_buttons.get("whatsapp")
            if btn is not None:
                btn.setChecked(False)
            return
        # Password-protect manager page
        if key == "manager":
            password = str(self.store.settings.get("dashboard_password", "1234"))
            dlg = PasswordDialog(self, password)
            if dlg.exec() != QDialog.Accepted or not getattr(dlg, "ok", False):
                return
        for k, b in self.nav_buttons.items():
            b.setChecked(k == key)
        self.stack.setCurrentWidget(self.pages[key])
        self.refresh_current()

    def refresh_current(self) -> None:
        widget = self.stack.currentWidget()
        if hasattr(widget, "refresh"):
            widget.refresh()  # type: ignore[attr-defined]

    def refresh_all(self) -> None:
        for p in self.pages.values():
            if hasattr(p, "refresh"):
                p.refresh()  # type: ignore[attr-defined]

    def refresh_background_views(self) -> None:
        """Refresh non-editing pages only to avoid losing in-progress form input."""
        for key in ("dashboard", "members", "payments", "whatsapp", "manager"):
            page = self.pages.get(key)
            if page is not None and hasattr(page, "refresh"):
                page.refresh()  # type: ignore[attr-defined]

    def handle_post_save(self, types: Optional[List[str]] = None) -> None:
        debug_log(f"MainWindow.handle_post_save:start types={types}")
        try:
            # Defer refresh to avoid re-entrant updates while save handler is still on stack.
            QTimer.singleShot(0, self.refresh_background_views)
        except Exception as exc:
            debug_log(f"MainWindow.handle_post_save:refresh-error {exc}")
            self.statusBar().showMessage(f"تم الحفظ لكن حدث خطأ أثناء تحديث الواجهة: {exc}", 7000)
        if not types:
            debug_log("MainWindow.handle_post_save:no-types")
            return
        if not self.store.settings.get("whatsapp_enabled", True):
            debug_log("MainWindow.handle_post_save:whatsapp-disabled")
            self.statusBar().showMessage("واتساب معطل في الإعدادات. لن يتم إرسال أي رسائل الآن.", 5000)
            return

        if "receipt" in set(types):
            receipt_id = str(getattr(self.store, "last_queued_receipt_message_id", "") or "")
            if receipt_id:
                newest_receipt = next(
                    (m for m in self.store.whatsapp_messages if str(m.get("message_id", "")) == receipt_id),
                    None,
                )
                self.store.last_queued_receipt_message_id = ""
                if newest_receipt is not None and self.store.whatsapp_message_ready(newest_receipt):
                    # Keep receipts queued to avoid any crash-prone immediate send path.
                    debug_log("MainWindow.handle_post_save:receipt-queued")
                    self.statusBar().showMessage("تم الحفظ وإضافة الإيصال إلى رسائل واتساب المعلقة.", 6000)
                    return

        debug_log("MainWindow.handle_post_save:default-status")
        self.statusBar().showMessage(
            "تم الحفظ. الرقم جديد وسيتم إدخاله إلى رسائل واتساب المعلقة بعد ساعة.",
            6000,
        )

    def _prompt_whatsapp_send_after_delay(self, types: List[str]) -> None:
        if not self.store.settings.get("whatsapp_enabled", True):
            return
        # This call shows the confirmation popup before sending.
        self.send_pending_whatsapp(silent=False, types=types)

    def open_new_dialog(self) -> None:
        self.navigate("new_subscription")

    def open_renewal_dialog(self, member_id: Optional[str] = None) -> None:
        self.navigate("renewal")
        if member_id:
            renewal_page = self.pages.get("renewal")
            if renewal_page is not None and hasattr(renewal_page, "select_member"):
                getattr(renewal_page, "select_member")(member_id)

    def open_member_renewal(self, member_id: str) -> None:
        self.open_renewal_dialog(member_id)

    def open_smart_dialog(self) -> None:
        self.navigate("smart_subscription")

    def open_unified_entry_page(self) -> None:
        self.navigate("unified_entry")

    def open_remaining_dialog(self, member_id: Optional[str] = None) -> None:
        self.navigate("remaining")
        remaining_page = self.pages.get("remaining")
        if remaining_page is not None and hasattr(remaining_page, "refresh"):
            getattr(remaining_page, "refresh")()
        if member_id is not None and remaining_page is not None and hasattr(remaining_page, "select_member"):
            getattr(remaining_page, "select_member")(member_id)

    def open_expense_dialog(self) -> None:
        self.navigate("expense")

    def open_remaining_members_page(self) -> None:
        self.navigate("members")
        members_page = self.pages.get("members")
        if hasattr(members_page, "search"):
            members_page.search.setText("")
        if hasattr(members_page, "status_filter") and members_page.status_filter is not None:
            for idx in range(members_page.status_filter.count()):
                if members_page.status_filter.itemData(idx) == "remaining":
                    members_page.status_filter.setCurrentIndex(idx)
                    break
        if hasattr(members_page, "refresh"):
            members_page.refresh()  # type: ignore[attr-defined]

    def open_expired_members_page(self) -> None:
        self.navigate("members")
        members_page = self.pages.get("members")
        if hasattr(members_page, "search"):
            members_page.search.setText("")
        if hasattr(members_page, "status_filter") and members_page.status_filter is not None:
            for idx in range(members_page.status_filter.count()):
                if members_page.status_filter.itemData(idx) == "expired":
                    members_page.status_filter.setCurrentIndex(idx)
                    break
        if hasattr(members_page, "refresh"):
            members_page.refresh()  # type: ignore[attr-defined]

    def open_member_page(self, member: Dict[str, Any]) -> None:
        page = self.pages.get("member_details")
        if page and hasattr(page, "set_member"):
            page.set_member(member)  # type: ignore[attr-defined]
            self.navigate("member_details")

    def navigate_back_to_members(self) -> None:
        self.navigate("members")
        members_page = self.pages.get("members")
        if hasattr(members_page, "refresh"):
            members_page.refresh()  # type: ignore[attr-defined]

    def open_member_search(self, query_or_member: Union[str, Dict[str, Any]]) -> None:
        if isinstance(query_or_member, dict):
            self.open_member_page(query_or_member)
            return
        query = str(query_or_member or "").strip()
        if not query:
            self.navigate("members")
            return
        rows = self.store.filtered_members("all", "all", query)
        if len(rows) == 1:
            self.open_member_page(rows[0])
            return
        self.navigate("members")
        members_page = self.pages.get("members")
        if hasattr(members_page, "search"):
            members_page.search.setText(query)
            members_page.refresh()  # type: ignore[attr-defined]

    def run_auto_whatsapp_checks(self) -> None:
        self.store.delete_sent_whatsapp_messages(older_than_hours=24, save=True)
        removed_old = self.store.purge_old_whatsapp_messages(retention_days=7, save=True)
        added = self.store.queue_due_reminders(save=True)
        added_daily_report = self.store.queue_daily_report_if_due(force=False, save=True)
        added += added_daily_report
        promoted = self.store.promote_scheduled_whatsapp_messages(save=True)
        self.refresh_background_views()
        pending = self.store.pending_whatsapp_messages(ready_only=True)
        if promoted > 0:
            self.statusBar().showMessage(f"تم نقل {promoted} رسالة واتساب إلى المعلق بعد اكتمال ساعة الانتظار.", 6000)
        if removed_old > 0:
            self.statusBar().showMessage(f"تم تنظيف {removed_old} رسالة واتساب قديمة تلقائيًا.", 6000)
        if added_daily_report > 0 and self.store.settings.get("whatsapp_enabled", True):
            pending_reports = [m for m in pending if str(m.get("type", "")) == "daily_report"]
            if pending_reports:
                self.send_pending_whatsapp(silent=True, messages=pending_reports)
                return
        if not self.store.settings.get("whatsapp_enabled", True):
            return
        now = datetime.now()
        hour_key = now.strftime("%Y-%m-%d %H")
        if hour_key == self.last_whatsapp_hourly_prompt_key:
            return

        def created_at_datetime(message: Dict[str, Any]) -> Optional[datetime]:
            raw = str(message.get("created_at", "")).strip()
            if not raw:
                return None
            try:
                return datetime.strptime(raw, DATETIME_FMT)
            except ValueError:
                return None

        today = now.date()
        yesterday = today - timedelta(days=1)
        today_pending = [
            msg
            for msg in pending
            if (created_at_datetime(msg) is not None and created_at_datetime(msg).date() == today)
        ]
        yesterday_pending = [
            msg
            for msg in pending
            if (created_at_datetime(msg) is not None and created_at_datetime(msg).date() == yesterday)
        ]

        target_messages = today_pending + yesterday_pending
        if not target_messages:
            return

        self.last_whatsapp_hourly_prompt_key = hour_key
        sorted_target = sorted(
            target_messages,
            key=lambda m: (
                str(m.get("created_at", "")),
                str(m.get("message_id", "")),
            ),
            reverse=True,
        )
        send_count = min(10, len(sorted_target))
        total_pending = len(pending)
        total_scheduled = len([m for m in self.store.whatsapp_messages if str(m.get("status", "")) == "scheduled"])

        should_send = self.show_pending_whatsapp_summary_dialog(
            today_count=len(today_pending),
            yesterday_count=len(yesterday_pending),
            total_ready=total_pending,
            total_scheduled=total_scheduled,
            send_count=send_count,
        )
        if should_send:
            self.send_pending_whatsapp(silent=False, messages=sorted_target[:send_count])

    def show_pending_whatsapp_summary_dialog(
        self,
        today_count: int,
        yesterday_count: int,
        total_ready: int,
        total_scheduled: int,
        send_count: int,
    ) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("رسائل واتساب المعلقة")
        dialog.setLayoutDirection(Qt.RightToLeft)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(22, 22, 22, 20)
        root.setSpacing(16)

        title_label = make_label("ملخص الرسائل المعلقة", "dialogTitleSmall")
        title_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        root.addWidget(title_label)

        subtitle = make_label(
            "يعرض هذا التنبيه رسائل اليوم وأمس فقط لقرار إرسال أسرع.",
            "smallMuted",
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        summary_box = QFrame()
        summary_box.setObjectName("settingsBox")
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(16, 16, 16, 16)
        summary_layout.setSpacing(12)
        summary_layout.addWidget(make_label(f"رسائل اليوم: {today_count}", "muted"))
        summary_layout.addWidget(make_label(f"رسائل أمس: {yesterday_count}", "muted"))
        summary_layout.addWidget(make_label(f"إجمالي الرسائل الجاهزة الآن: {total_ready}", "muted"))
        summary_layout.addWidget(make_label(f"رسائل قيد الانتظار (scheduled): {total_scheduled}", "muted"))
        summary_layout.addWidget(make_label(f"سيتم إرسال: {send_count} رسالة", "muted"))
        root.addWidget(summary_box)

        buttons = QHBoxLayout()
        buttons.setDirection(QBoxLayout.Direction.RightToLeft)
        buttons.setSpacing(12)

        send_btn = QPushButton(f"إرسال {send_count} الآن")
        send_btn.setObjectName("primaryButton")
        send_btn.setMinimumHeight(40)
        postpone_btn = QPushButton("تأجيل")
        postpone_btn.setObjectName("secondaryButton")
        postpone_btn.setMinimumHeight(40)

        buttons.addWidget(send_btn)
        buttons.addWidget(postpone_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        choice: Dict[str, bool] = {"send": False}

        def choose_send() -> None:
            choice["send"] = True
            dialog.accept()

        send_btn.clicked.connect(choose_send)
        postpone_btn.clicked.connect(dialog.reject)

        fit_dialog_to_screen(dialog, 860, 360)
        dialog.exec()
        return bool(choice["send"])

    def prompt_whatsapp_send_options(self, pending: List[Dict[str, Any]]) -> None:
        def created_at_datetime(message: Dict[str, Any]) -> Optional[datetime]:
            raw = str(message.get("created_at", "")).strip()
            if not raw:
                return None
            try:
                return datetime.strptime(raw, DATETIME_FMT)
            except ValueError:
                return None

        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        today_count = 0
        yesterday_count = 0
        for msg in pending:
            created = created_at_datetime(msg)
            if created is None:
                continue
            if created.date() == today:
                today_count += 1
            elif created.date() == yesterday:
                yesterday_count += 1

        dialog = QDialog(self)
        dialog.setWindowTitle("رسائل واتساب المعلقة")
        dialog.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 22, 22, 20)
        layout.setSpacing(16)

        title = make_label("رسائل واتساب المعلقة", "dialogTitleSmall")
        title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(title)

        layout.addWidget(make_label(
            f"الإجمالي: {len(pending)} رسالة | اليوم: {today_count} | أمس: {yesterday_count}",
            "muted",
        ))
        layout.addWidget(make_label(
            "سيتم طلب تأكيد نهائي قبل بدء الإرسال.",
            "smallMuted",
        ))

        button_row = QHBoxLayout()
        button_row.setDirection(QBoxLayout.Direction.RightToLeft)
        button_row.setSpacing(10)

        send_all_btn = QPushButton("إرسال الكل")
        send_all_btn.setObjectName("primaryButton")
        send_all_btn.setMinimumHeight(40)
        button_row.addWidget(send_all_btn)

        send_ten_btn = QPushButton("إرسال 10 فقط")
        send_ten_btn.setObjectName("secondaryButton")
        send_ten_btn.setMinimumHeight(40)
        button_row.addWidget(send_ten_btn)

        select_some_btn = QPushButton("اختيار بعض")
        select_some_btn.setObjectName("secondaryButton")
        select_some_btn.setMinimumHeight(40)
        button_row.addWidget(select_some_btn)

        snooze_btn = QPushButton("تأجيل")
        snooze_btn.setObjectName("dangerButton")
        snooze_btn.setMinimumHeight(40)
        button_row.addWidget(snooze_btn)

        layout.addLayout(button_row)

        choice: Dict[str, str] = {"action": ""}

        def choose_send_all() -> None:
            choice["action"] = "all"
            dialog.accept()

        def choose_send_ten() -> None:
            choice["action"] = "ten"
            dialog.accept()

        def choose_select_some() -> None:
            choice["action"] = "select"
            dialog.accept()

        def choose_snooze() -> None:
            choice["action"] = "snooze"
            dialog.reject()

        send_all_btn.clicked.connect(choose_send_all)
        send_ten_btn.clicked.connect(choose_send_ten)
        select_some_btn.clicked.connect(choose_select_some)
        snooze_btn.clicked.connect(choose_snooze)

        fit_dialog_to_screen(dialog, 920, 340)
        if dialog.exec() != QDialog.Accepted:
            return

        if choice["action"] == "all":
            self.send_pending_whatsapp(silent=False)
        elif choice["action"] == "ten":
            self.send_pending_whatsapp(silent=False, messages=pending[:10])
        elif choice["action"] == "select":
            whatsapp_page = self.pages.get("whatsapp")
            if whatsapp_page is not None and hasattr(whatsapp_page, "select_and_send"):
                getattr(whatsapp_page, "select_and_send")()
            else:
                QMessageBox.warning(self, "واتساب", "لا يمكن فتح اختيار الرسائل الآن.")

    def send_pending_whatsapp(
        self,
        silent: bool = False,
        types: Optional[List[str]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        if not self.store.settings.get("whatsapp_enabled", True):
            if not silent:
                QMessageBox.warning(self, "واتساب متوقف", "واتساب معطل في الإعدادات. فعّل واتساب في صفحة الإعدادات قبل إرسال الرسائل.")
            return
        if self.whatsapp_thread is not None and self.whatsapp_thread.isRunning():
            if not silent:
                QMessageBox.information(self, "واتساب", "الإرسال شغال بالفعل، استنى لما يخلص.")
            return
        if messages is None:
            all_candidates = [
                m for m in self.store.whatsapp_messages
                if str(m.get("status", "")) in ("pending", "scheduled", "failed")
            ]
            if types is not None:
                all_candidates = [m for m in all_candidates if str(m.get("type", "")) in types]

            self.store.refresh_statuses(save=False)
            pending = []
            unsendable = []
            for m in all_candidates:
                reason = self.store.get_whatsapp_unsendable_reason(m, manual=False)
                if reason is None:
                    pending.append(m)
                else:
                    unsendable.append((m, reason))
        else:
            pending = []
            unsendable = []
            self.store.refresh_statuses(save=False)
            for m in messages:
                if types is not None and str(m.get("type", "")) not in types:
                    continue
                reason = self.store.get_whatsapp_unsendable_reason(m, manual=True)
                if reason is None:
                    m["status"] = "pending"
                    m["send_after"] = ""
                    m["error"] = ""
                    pending.append(m)
                else:
                    unsendable.append((m, reason))
            if pending:
                self.store.save_whatsapp()

        if not pending and not unsendable:
            if not silent:
                QMessageBox.information(self, "واتساب", "لا توجد رسائل معلقة للإرسال الآن.")
            return

        if not pending and unsendable:
            if not silent:
                show_unsendable_whatsapp_dialog(
                    self,
                    title="تنبيه: لا يمكن إرسال الرسائل",
                    intro_lines=[
                        f"تم فحص {len(unsendable)} رسالة، ولكن لا يمكن إرسال أي منها حاليًا للأسباب الموضحة أدناه:"
                    ],
                    items=unsendable,
                    can_proceed=False,
                )
            return

        if not silent:
            label = "رسائل الإيصال" if types == ["receipt"] else "الرسائل المعلقة"
            if unsendable:
                proceed = show_unsendable_whatsapp_dialog(
                    self,
                    title="تأكيد إرسال واتساب وبيان المستبعد",
                    intro_lines=[
                        f"• سيتم إرسال {len(pending)} {label}.",
                        f"• ⚠️ تنبيه: هناك {len(unsendable)} رسالة لن يتم إرسالها للأسباب الموضحة بالجدول أدناه:",
                        "لا تلمس الماوس أو الكيبورد أثناء الإرسال. هل تريد المتابعة؟",
                    ],
                    items=unsendable,
                    can_proceed=True,
                    proceed_button_text=f"متابعة إرسال الـ ({len(pending)}) رسالة الجاهزة",
                )
                if not proceed:
                    return
            else:
                reply = QMessageBox.question(
                    self,
                    "تأكيد إرسال واتساب",
                    f"سيتم إرسال {len(pending)} {label}.\nجميع الرسائل المحددة جاهزة وصالحة للإرسال (0 رسائل مستبعدة).\nلا تلمس الماوس أو الكيبورد حتى انتهاء الإرسال.\nهل تريد المتابعة؟",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return
        self.whatsapp_silent = silent
        self.whatsapp_thread = WhatsAppSendThread(pending, self.store.settings)
        self.whatsapp_thread.progress.connect(self.on_whatsapp_progress)
        self.whatsapp_thread.done.connect(self.on_whatsapp_done)
        try:
            self.show_whatsapp_progress_popup(total=len(pending))
        except Exception as exc:
            self.statusBar().showMessage(f"تعذر إظهار نافذة تقدم واتساب: {exc}", 5000)
        self.whatsapp_thread.start()
        if not silent:
            self.statusBar().showMessage(f"جاري إرسال {len(pending)} رسالة واتساب... لا تلمس الماوس أو الكيبورد حتى انتهاء الإرسال.", 8000)

    def show_whatsapp_progress_popup(self, total: int) -> None:
        if self.whatsapp_progress_dialog is not None:
            try:
                self.whatsapp_progress_dialog.close()
            except Exception:
                pass
            self.whatsapp_progress_dialog = None

        dlg = QProgressDialog(f"واتساب: 0/{total}", "", 0, max(0, int(total)), self)
        dlg.setWindowTitle("إرسال واتساب")
        dlg.setWindowModality(Qt.NonModal)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)

        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = avail.right() - 250
            y = avail.top() + 20
            dlg.setGeometry(x, y, 230, 68)

        dlg.show()
        self.whatsapp_progress_dialog = dlg

    def on_whatsapp_progress(self, processed: int, total: int, success_count: int, failed_count: int) -> None:
        if self.whatsapp_progress_dialog is None:
            return
        safe_total = max(0, int(total))
        safe_processed = max(0, min(int(processed), safe_total))
        self.whatsapp_progress_dialog.setMaximum(safe_total)
        self.whatsapp_progress_dialog.setValue(safe_processed)
        self.whatsapp_progress_dialog.setLabelText(f"واتساب: {safe_processed}/{safe_total} | تم {success_count} | فشل {failed_count}")

    def on_whatsapp_done(self, result: Dict[str, Any]) -> None:
        if self.whatsapp_progress_dialog is not None:
            try:
                max_value = int(self.whatsapp_progress_dialog.maximum())
                self.whatsapp_progress_dialog.setValue(max_value)
                self.whatsapp_progress_dialog.close()
            except Exception:
                pass
            self.whatsapp_progress_dialog = None
        ids = [str(x) for x in result.get("ids", [])]
        failed_ids = [str(x) for x in result.get("failed_ids", [])]
        error = str(result.get("error", ""))
        self.store.mark_whatsapp_sent(ids, failed_ids=failed_ids, error=error)
        self.refresh_all()
        self.statusBar().showMessage("انتهى إرسال واتساب.", 5000)
        if not self.whatsapp_silent:
            if result.get("ok") and not failed_ids:
                QMessageBox.information(self, "واتساب", f"تم إرسال جميع الرسائل بنجاح ({len(ids)} رسالة).")
            elif result.get("ok"):
                failed_items = []
                for msg_id in failed_ids:
                    msg = next((m for m in self.store.whatsapp_messages if str(m.get("message_id", "")) == msg_id), None)
                    if msg:
                        err_msg = str(msg.get("error", "")).strip() or "لم يتم التسليم عبر واتساب (الرقم غير مسجل على واتساب أو لم يستجب)"
                        failed_items.append((msg, err_msg))
                    else:
                        failed_items.append(({"message_id": msg_id, "recipient_name": "عضو", "mobile": "-"}, "تعذر التسليم عبر واتساب"))
                success_count = max(0, len(ids) - len(failed_ids))
                show_unsendable_whatsapp_dialog(
                    self,
                    title="تقرير نتائج إرسال واتساب",
                    intro_lines=[
                        f"• تم الإرسال بنجاح إلى: {success_count} رسالة.",
                        f"• ⚠️ فشل الإرسال إلى: {len(failed_ids)} رسالة للأسباب الموضحة بالجدول أدناه:",
                    ],
                    items=failed_items,
                    can_proceed=False,
                )
            else:
                QMessageBox.warning(self, "واتساب", f"فشل إرسال رسائل واتساب: {error}")

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key_F11:
            self.showNormal() if self.isMaximized() else self.showMaximized()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            widget = QApplication.focusWidget()
            if isinstance(widget, QLineEdit) and not isinstance(widget.window(), QDialog):
                if widget.objectName() == "searchInput":
                    return False
                if widget.isReadOnly():
                    return False
                widget.focusNextChild()
                return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.whatsapp_thread is not None and self.whatsapp_thread.isRunning():
            QMessageBox.information(
                self,
                "واتساب",
                "الإرسال شغال الآن. استنى لحد ما يخلص ثم اقفل البرنامج.",
            )
            event.ignore()
            return
        if self.google_queue_flush_thread is not None and self.google_queue_flush_thread.isRunning():
            self.google_queue_flush_thread.wait(2000)
        super().closeEvent(event)

    def apply_styles(self) -> None:
        self.setStyleSheet(
            """
            * {
                font-family: "Segoe UI", "Cairo", "Tahoma";
                font-size: 15px;
                color: #E9EEF2;
            }
            QWidget#central {
                background: #050B10;
            }
            QWidget#pageShell {
                background: transparent;
            }
            QFrame#settingsBox {
                background: #0A1118;
                border: 1px solid #16232D;
                border-radius: 12px;
            }
            QFrame#sidebar {
                background: #070D12;
                border-left: 1px solid #14202A;
            }
            QLabel#logoText, QLabel#topTitle, .topTitle {
                color: #7ED321;
                font-size: 34px;
                font-weight: 900;
                letter-spacing: 1px;
            }
            QFrame#topbar {
                background: #050B10;
                border-bottom: 1px solid #101B24;
                min-height: 90px;
            }
            QLabel#topDate, .topDate {
                color: #DDE6EC;
                font-size: 18px;
            }
            QPushButton#navButton {
                text-align: right;
                padding: 14px 16px;
                border-radius: 10px;
                border: 1px solid transparent;
                background: transparent;
                color: #DDE4EA;
                font-size: 18px;
            }
            QPushButton#navButton:hover {
                background: #0B171E;
                border: 1px solid #1A2B36;
            }
            QPushButton#navButton:checked {
                background: #11220E;
                border: 1px solid #244015;
                color: #A8F14B;
            }
            QFrame#userBox {
                background: #07141B;
                border: 1px solid #14242D;
                border-radius: 16px;
            }
            QLabel#userName, .userName {
                color: #FFFFFF;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#pageTitle, .pageTitle {
                font-size: 28px;
                font-weight: 800;
                color: #F3F8FB;
            }
            QLabel#pageSubtitle, QLabel#muted, .pageSubtitle, .muted {
                color: #A8B3BC;
                font-size: 16px;
            }
            QLabel#smallMuted, .smallMuted {
                color: #8D99A3;
                font-size: 15px;
            }
            QLabel#sectionTitle, .sectionTitle {
                color: #F0F6F2;
                font-size: 18px;
                font-weight: 700;
                margin-top: 6px;
            }
            QFrame#dashboardHero {
                background: #0A1118;
                border: 1px solid #17392B;
                border-radius: 16px;
            }
            QLabel#heroTitle, .heroTitle {
                color: #F3F8FB;
                font-size: 34px;
                font-weight: 900;
            }
            QLabel#heroSubtitle, .heroSubtitle {
                color: #C3D7DE;
                font-size: 18px;
            }
            QPushButton#dashboardActionButton {
                background: #7ED321;
                color: #071006;
                border: none;
                border-radius: 14px;
                padding: 18px 20px;
                font-size: 20px;
                font-weight: 900;
                min-height: 72px;
            }
            QPushButton#dashboardActionButton:hover {
                background: #93EE2E;
            }
            QLineEdit#searchInput {
                font-size: 18px;
                padding: 14px;
                min-height: 58px;
            }
            QFrame#dashboardHero {
                background: #0F1C23;
                border: 1px solid #164028;
                border-radius: 18px;
            }
            QLabel#statusChip, .statusChip {
                background: rgba(126, 211, 33, 0.14);
                color: #BFF48B;
                font-size: 16px;
                font-weight: 800;
                padding: 10px 18px;
                border: 1px solid #7ED321;
                border-radius: 20px;
            }
            QFrame#metricCard {
                background: #07131B;
                border: 1px solid #1D2F3A;
                border-radius: 16px;
            }
            QLabel#metricValue, .metricValue {
                color: #F3F8FB;
                font-size: 20px;
                font-weight: 800;
                padding: 10px 0;
            }
            QFrame#detailCard {
                background: #0F1B24;
                border: 1px solid #1B2C38;
                border-radius: 16px;
                padding: 18px;
            }
            QTableWidget#memberDetailTable {
                background: #0A1118;
                alternate-background-color: #091319;
                gridline-color: #12202D;
                border: 1px solid #16232D;
                border-radius: 12px;
                selection-background-color: #214521;
                selection-color: #FFFFFF;
                font-size: 15px;
            }
            QTableWidget#memberDetailTable QHeaderView::section {
                background: #0D171F;
                color: #EAF0F4;
                padding: 14px 10px;
                font-size: 15px;
            }
            QTableWidget#memberDetailTable QTableCornerButton::section {
                background: #0D171F;
                border: none;
            }
            QFrame#statCard {
                background: #0A1118;
                border: 1px solid #16232D;
                border-radius: 12px;
            }
            QFrame#statCard:hover {
                border: 1px solid #27421B;
                background: #0D151C;
            }
            #cardIcon {
                color: #7ED321;
                font-size: 38px;
                font-weight: 800;
            }
            QLabel#statValue, .statValue {
                color: #FFFFFF;
                font-size: 28px;
                font-weight: 800;
            }
            QPushButton#primaryButton {
                background: #7ED321;
                color: #071006;
                border: none;
                border-radius: 9px;
                padding: 6px 14px;
                font-size: 14px;
                font-weight: 800;
                min-height: 28px;
                min-width: 120px;
            }
            QPushButton#primaryButton:hover {
                background: #93EE2E;
            }
            QPushButton#secondaryButton {
                background: #0B141B;
                color: #E2E8EC;
                border: 1px solid #1B2A35;
                border-radius: 9px;
                padding: 6px 12px;
                font-weight: 700;
                min-height: 28px;
                min-width: 100px;
            }
            QPushButton#secondaryButton:hover {
                border-color: #7ED321;
                color: #A8F14B;
            }
            QPushButton#secondaryButton[reportActive="true"], QPushButton#primaryButton[reportActive="true"] {
                background: #7ED321;
                color: #071006;
                border: none;
            }
            QPushButton#secondaryButton[reportActive="true"]:hover, QPushButton#primaryButton[reportActive="true"]:hover {
                background: #93EE2E;
            }
            QPushButton#secondaryButton[reportActive="false"], QPushButton#primaryButton[reportActive="false"] {
                background: #0B141B;
                color: #E2E8EC;
                border: 1px solid #1B2A35;
            }
            QPushButton#dangerButton {
                background: #1A0C0C;
                color: #FFB8B8;
                border: 1px solid #4A1E1E;
                border-radius: 9px;
                padding: 6px 12px;
                font-weight: 800;
                min-height: 28px;
                min-width: 120px;
            }
            QPushButton#dangerButtonSmall {
                background: #1A0C0C;
                color: #FFB8B8;
                border: 1px solid #4A1E1E;
                border-radius: 8px;
                padding: 4px 12px;
                font-weight: 800;
                min-width: 82px;
                min-height: 26px;
            }
            QPushButton#dangerButton:hover, QPushButton#dangerButtonSmall:hover {
                background: #351111;
                border-color: #B33939;
                color: #FFFFFF;
            }
            QPushButton#warningButton {
                background: #2A2C0C;
                color: #FFE874;
                border: 1px solid #5C5D1E;
                border-radius: 9px;
                padding: 6px 12px;
                font-weight: 800;
                min-height: 28px;
                min-width: 120px;
            }
            QPushButton#warningButton:hover {
                background: #4A4D12;
                border-color: #FFE874;
                color: #FFFFFF;
            }
            QLineEdit#searchInput, QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox {
                background: #080F15;
                border: 1px solid #1A2833;
                border-radius: 8px;
                padding: 6px 8px;
                color: #EAF0F4;
                min-height: 26px;
                font-size: 13px;
            }
            QLineEdit#searchInput:focus, QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus {
                border: 1px solid #5FAF1B;
            }
            QComboBox::drop-down, QDateEdit::drop-down, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                border: none;
                width: 30px;
            }
            QTableWidget#darkTable {
                background: #080F15;
                alternate-background-color: #091219;
                gridline-color: #121D26;
                border: 1px solid #14212B;
                border-radius: 10px;
                selection-background-color: #18350F;
                selection-color: #FFFFFF;
                font-size: 12px;
            }
            QHeaderView::section {
                background: #0D171F;
                color: #D9E3E8;
                border: none;
                border-bottom: 1px solid #172632;
                padding: 6px 6px;
                font-weight: 700;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 4px 6px;
                border-bottom: 1px solid #111B23;
                font-size: 12px;
            }
            QScrollArea#pageScroll {
                background: transparent;
                border: none;
            }
            QScrollArea#pageScroll > QWidget > QWidget {
                background: transparent;
            }
            QScrollBar:vertical {
                background: #071016;
                width: 16px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #1B2C37;
                min-height: 36px;
                border-radius: 7px;
            }
            QScrollBar::handle:vertical:hover {
                background: #355315;
            }
            QScrollBar:horizontal {
                background: #071016;
                height: 16px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #1B2C37;
                min-width: 36px;
                border-radius: 7px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #355315;
            }
            QLabel#dialogTitle, .dialogTitle {
                font-size: 28px;
                font-weight: 800;
                color: #FFFFFF;
                margin-bottom: 4px;
            }
            QLabel#dialogTitleSmall, .dialogTitleSmall {
                font-size: 19px;
                font-weight: 800;
                color: #FFFFFF;
            }
            QLabel#fieldLabel, .fieldLabel {
                color: #AEB8C1;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#calcBox, .calcBox {
                background: #0B171E;
                border: 1px solid #1E3214;
                border-radius: 9px;
                padding: 10px;
                color: #B7F56D;
                font-weight: 700;
            }
            QDialog {
                background: #050B10;
            }
            QScrollArea#dialogScroll {
                background: transparent;
                border: none;
            }
            QFrame#dialogActionBar {
                background: #050B10;
                border-top: 1px solid #15222D;
            }
            QMessageBox {
                background-color: #071018;
                color: #F3F7FA;
            }
            QMessageBox QLabel {
                color: #F3F7FA;
                font-size: 16px;
                font-weight: 700;
                background: transparent;
            }
            QMessageBox QPushButton {
                background-color: #B7F56D;
                color: #071018;
                border: none;
                border-radius: 9px;
                padding: 8px 18px;
                min-width: 95px;
                font-weight: 800;
            }
            QMessageBox QPushButton:hover {
                background-color: #C9FF80;
            }
            """
        )


def main() -> None:
    def qt_message_handler(mode, context, message) -> None:
        try:
            mode_name = {
                QtMsgType.QtDebugMsg: "DEBUG",
                QtMsgType.QtInfoMsg: "INFO",
                QtMsgType.QtWarningMsg: "WARNING",
                QtMsgType.QtCriticalMsg: "CRITICAL",
                QtMsgType.QtFatalMsg: "FATAL",
            }.get(mode, str(mode))
        except Exception:
            mode_name = str(mode)
        debug_log(f"QT_{mode_name}: {message}")

    def handle_unhandled_exception(exc_type, exc_value, exc_tb) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        debug_log(f"UNHANDLED_EXCEPTION: {exc_value}")
        debug_log(details)
        try:
            print(details, file=sys.stderr)
        except Exception:
            pass
        try:
            QMessageBox.critical(None, "خطأ غير متوقع", f"حدث خطأ غير متوقع:\n{exc_value}\n\nراجع التيرمنال للتفاصيل.")
        except Exception:
            pass

    sys.excepthook = handle_unhandled_exception
    try:
        faulthandler.enable(all_threads=True)
        debug_log("faulthandler: enabled")
    except Exception as exc:
        debug_log(f"faulthandler: enable-failed {exc}")
    try:
        qInstallMessageHandler(qt_message_handler)
        debug_log("qt_message_handler: installed")
    except Exception as exc:
        debug_log(f"qt_message_handler: install-failed {exc}")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setLayoutDirection(Qt.RightToLeft)
    app.setFont(QFont("Segoe UI", 11))
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
