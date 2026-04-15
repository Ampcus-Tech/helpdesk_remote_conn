import sys
import os
import json
import time
import threading
import ctypes
import platform
from pynput.keyboard import Listener as KeyboardListener, Key, KeyCode

# Add parent dir to path to import common
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _normalize_key(key):
    if isinstance(key, KeyCode):
        if key.char:
            char = key.char
            # When Ctrl is held, platforms may emit control chars (\x01..\x1a)
            if len(char) == 1 and 1 <= ord(char) <= 26:
                return chr(ord(char) + 96)
            return char.lower()
        return None

    if isinstance(key, Key):
        name = str(key).replace("Key.", "")
        aliases = {
            "ctrl": "ctrl", "ctrl_l": "ctrl_l", "ctrl_r": "ctrl_r",
            "alt": "alt", "alt_l": "alt_l", "alt_r": "alt_r", "alt_gr": "alt_gr",
            "shift": "shift", "shift_l": "shift_l", "shift_r": "shift_r",
            "cmd": "cmd", "cmd_l": "cmd_l", "cmd_r": "cmd_r", "meta": "cmd", "meta_l": "cmd_l", "meta_r": "cmd_r",
            "esc": "esc", "space": "space", "tab": "tab", "enter": "enter",
            "backspace": "backspace", "delete": "delete", "insert": "insert",
            "home": "home", "end": "end", "page_up": "page_up", "page_down": "page_down",
            "up": "up", "down": "down", "left": "left", "right": "right",
            "caps_lock": "caps_lock", "num_lock": "num_lock", "scroll_lock": "scroll_lock",
            "pause": "pause", "print_screen": "print_screen", "menu": "menu",
            "media_play_pause": "play_pause", "media_next_track": "next_track", "media_prev_track": "prev_track",
            "media_volume_up": "volume_up", "media_volume_down": "volume_down", "media_volume_mute": "volume_mute",
        }
        if name in aliases:
            return aliases[name]
        if name.startswith("f") and name[1:].isdigit():
            return name
    return None

class InputHelper:
    def __init__(self):
        self._pressed_keys = set()
        self._listener = None
        self._window_name = "Remote Desktop Client" # Default Tauri app name from index.html title
        self._stop_event = threading.Event()
        
    def _is_target_window_foreground(self) -> bool:
        system = platform.system()
        if system == "Windows":
            try:
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                if not hwnd: return False
                
                length = user32.GetWindowTextLengthW(hwnd)
                title_buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title_buf, length + 1)
                title = (title_buf.value or "").strip()
                
                # Match Tauri app title. Check for exact match or partial matches
                title_lower = title.lower()
                return (self._window_name.lower() in title_lower or 
                       "remote desktop" in title_lower or 
                       "helpdesk" in title_lower or
                       "remote" in title_lower)
            except Exception:
                return False
        elif system == "Darwin":  # macOS
            try:
                from AppKit import NSWorkspace
                active_app = NSWorkspace.sharedWorkspace().activeApplication()
                if active_app and 'remote-desktop' in active_app['NSApplicationName'].lower():
                    return True
                return False
            except ImportError:
                return True  # Fallback if PyObjC isn't available
        elif system == "Linux":
            try:
                from ewmh import EWMH
                ewmh = EWMH()
                active_window = ewmh.getActiveWindow()
                if active_window:
                    title = ewmh.getWmName(active_window).decode('utf-8', errors='ignore')
                    return 'remote desktop' in title.lower()
                return False
            except ImportError:
                return True  # Fallback
        return True  # Default for other systems

    def _on_press(self, key):
        name = _normalize_key(key)
        if name and name not in self._pressed_keys:
            self._pressed_keys.add(name)
            print(json.dumps({"key": name, "pressed": True}), flush=True)

    def _on_release(self, key):
        name = _normalize_key(key)
        if name in self._pressed_keys:
            self._pressed_keys.discard(name)
            print(json.dumps({"key": name, "pressed": False}), flush=True)

    def run(self):
        listener_running = False
        
        def focus_checker():
            nonlocal listener_running
            while not self._stop_event.is_set():
                is_focused = self._is_target_window_foreground()
                if is_focused and not listener_running:
                    # Start listener
                    self._listener = KeyboardListener(
                        on_press=self._on_press,
                        on_release=self._on_release,
                        suppress=True
                    )
                    self._listener.start()
                    listener_running = True
                elif not is_focused and listener_running:
                    # Stop listener
                    if self._listener:
                        self._listener.stop()
                        self._listener = None
                    listener_running = False
                time.sleep(0.1)  # Check every 100ms
        
        focus_thread = threading.Thread(target=focus_checker, daemon=True)
        focus_thread.start()
        
        try:
            while not self._stop_event.is_set():
                time.sleep(0.1)
        finally:
            if self._listener:
                self._listener.stop()

if __name__ == "__main__":
    helper = InputHelper()
    helper.run()
