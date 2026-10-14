import pyautogui
import time
from tkinter import messagebox 
import tkinter as tk

def popup(title, message):
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    messagebox.showinfo(title, message)
    root.destroy()  # Destroy the main window after the popup is closed



while True:
    popup(pyautogui.position(), "Move your mouse to the desired position and click OK.")
    
    pyautogui.moveTo(300,195,duration=4)
