import sys
import os
import json
import time
import threading
import ctypes
import platform
import signal
from pynput.keyboard import Listener as KeyboardListener, Key, KeyCode
 
# Add parent dir to path to import common
# For bundled app, add the executable directory to path
if getattr(sys, 'frozen', False):
    # Running in a bundle
    bundle_dir = os.path.dirname(sys.executable)
    sys.path.insert(0, bundle_dir)
else:
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
        self._window_name_lower = self._window_name.lower()
        self._stop_event = threading.Event()
        self._active = True
        self._state_lock = threading.Lock()
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        print(f"Received signal {signum}, shutting down...", flush=True)
        self.stop()
        sys.exit(0)

    def stop(self):
        self._stop_event.set()
        self._stop_listener()

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
                return title_lower == self._window_name_lower or title_lower.startswith(f"{self._window_name_lower} -")
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
 
    def _stop_listener(self):
        if self._listener:
            try:
                self._listener.stop()
            except:
                pass
            self._listener = None
 
    def _start_listener(self):
        self._listener = KeyboardListener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=True
        )
        self._listener.start()
 
    def _set_active(self, active: bool):
        with self._state_lock:
            self._active = active
            if not active:
                # Ensure no local typing is blocked while paused.
                self._stop_listener()
 
    def _read_commands(self):
        while not self._stop_event.is_set():
            line = sys.stdin.readline()
            if not line:
                # Stdin closed, we should exit
                self.stop()
                break
            try:
                payload = json.loads(line.strip())
            except Exception:
                continue
 
            command = payload.get("command")
            if command == "pause":
                self._set_active(False)
            elif command == "resume":
                self._set_active(True)
 
    def run(self):
        listener_running = False
       
        def focus_checker():
            nonlocal listener_running
            while not self._stop_event.is_set():
                with self._state_lock:
                    active = self._active
 
                if not active:
                    if listener_running:
                        self._stop_listener()
                        listener_running = False
                    time.sleep(0.1)
                    continue
 
                is_focused = self._is_target_window_foreground()
                if is_focused and not listener_running:
                    # Start listener
                    self._start_listener()
                    listener_running = True
                elif not is_focused and listener_running:
                    # Stop listener
                    self._stop_listener()
                    listener_running = False
                time.sleep(0.1)  # Check every 100ms
       
        focus_thread = threading.Thread(target=focus_checker, daemon=True)
        focus_thread.start()
        command_thread = threading.Thread(target=self._read_commands, daemon=True)
        command_thread.start()
       
        try:
            while not self._stop_event.is_set():
                time.sleep(0.1)
        finally:
            self._stop_listener()
 
if __name__ == "__main__":
    helper = InputHelper()
    helper.run()