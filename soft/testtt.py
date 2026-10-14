from collections import deque
from subprocess import Popen
from time import sleep
import ctypes
import io
import random
import time

import pyautogui
import win32clipboard
from PIL import Image
from pyautogui import hotkey, press, write
from pygetwindow import getAllWindows, getActiveWindow
from pyperclip import copy, paste
def random_delay(min_seconds: float = 0.25, max_seconds: float = 1.2) -> float:
    """Sleep for a random duration while preserving the original flow."""
    delay = random.uniform(min_seconds, max_seconds)
    sleep(delay)
    return delay


def set_keyboard_layout_to_english():
    """Detect current Windows keyboard language and switch to English (US) once if needed."""
    hkl = ctypes.windll.user32.GetKeyboardLayout(0)
    lang_id = hkl & 0xFFFF
    language_map = {
        0x0409: "en-US",
        0x0809: "en-GB",
        0x0407: "de-DE",
        0x040C: "fr-FR",
        0x0410: "it-IT",
        0x0412: "ko-KR",
        0x0411: "ja-JP",
        0x0804: "zh-CN",
        0x0404: "zh-TW",
        0x0413: "nl-NL",
        0x0416: "pt-BR",
    }
    current_lang = language_map.get(lang_id, f"0x{lang_id:04X}")
    print(f"[set_keyboard_layout_to_english_once] Current keyboard language: {current_lang}")

    if current_lang == "en-US":
        print("[set_keyboard_layout_to_english_once] Already English (US). No switch needed.")
        return

    print("[set_keyboard_layout_to_english_once] Sending Alt+Shift once to switch layout.")
    pyautogui.hotkey("alt", "shift")
    sleep(0.25)

    hkl_after = ctypes.windll.user32.GetKeyboardLayout(0)
    current_lang_after = language_map.get(hkl_after & 0xFFFF, f"0x{(hkl_after & 0xFFFF):04X}")
    print(f"[set_keyboard_layout_to_english_once] After switch, current keyboard language: {current_lang_after}")
    


def write_message(message: str, char_delay: float = None, use_paste_mode: bool = False):
    if not message:
        return

    if use_paste_mode:
        try:
            copy(message)
            random_delay(3, 5)
            pyautogui.hotkey("ctrl", "v")
            random_delay(2,3)
            return
        except Exception:
            pass

    hotkey("win", "space")
    random_delay(5, 5.1)


    arabic_keys = {
    "ذ": "`",
    "ض": "q",
    "ص": "w",
    "ث": "e",
    "ق": "r",
    "ف": "t",
    "غ": "y",
    "ع": "u",
    "ه": "i",
    "خ": "o",
    "ح": "p",
    "ج": "[",
    "د": "]",

    "ش": "a",
    "س": "s",
    "ي": "d",
    "ب": "f",
    "ل": "g",
    "ا": "h",
    "ت": "j",
    "ن": "k",
    "م": "l",
    "ك": ";",
    "ط": "'",
    "/": "/l",
    ":": "/;",
    ".": "/.",

    "ئ": "z",
    "ء": "x",
    "ؤ": "c",
    "ر": "v",
    "ى": "n",
    "ة": "m",
    "و": ",",
    "ز": ".",
    "ظ": "/",
"أ": "h",
"إ": "h",
"آ": "h",
",": "/,"
}


    for char in message :
        if char == ' ':
            pyautogui.write(' ')
        elif char in arabic_keys.keys():
            key = arabic_keys[char]
            if len(key) == 1 :
                pyautogui.press(key)
            else :
                random_delay(0.1,0.25)
                pyautogui.hotkey('shift',key[1])
                random_delay(0.1,0.25)       
        elif char == "\n":
            hotkey('shift','enter')
        else :
            pyautogui.write(char)
        #sleep(0.00001)

message =  """
            تقرير هالك جيم اليومي
            التاريخ: 30/09/2026 - الساعة: 13:22
            --------------------
            إجمالي الأعضاء: 231
            --------------------
            مدفوعات اليوم: 0 عملية
            إيراد اليوم: 0 .ج
            إجمالي الإيرادات: 22,870 .ج
            إجمالي المتبقي: 1,400 .ج
            --------------------
            تفاصيل مدفوعات اليوم:
            - لا توجد مدفوعات اليوم
            --------------------
            """

write_message   ( message )






