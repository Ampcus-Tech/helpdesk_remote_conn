import cv2
import logging
import ctypes
from pynput.keyboard import Listener as KeyboardListener, Key, KeyCode
from common.messages import ControlMessage, MessageType

logger = logging.getLogger("input_sender")

class InputSender:
    def __init__(self, window_name, data_channel, loop):
        self.window_name = window_name
        self.channel = data_channel
        self.loop = loop
        self.screen_width = 1920
        self.screen_height = 1080
        self._pressed_keys = set()
        self._enable_focus_gating = True
        self._keyboard_listener = KeyboardListener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self._keyboard_listener.start()
        
        cv2.setMouseCallback(self.window_name, self._mouse_callback)
        
    def update_screen_size(self, width, height):
        self.screen_width = width
        self.screen_height = height

    def _is_target_window_foreground(self) -> bool:
        """
        On Wi only forward keyboard input when the Ondows,penCV "Remote Desktop"
        window is the foreground window. This prevents keystrokes typed into the
        client's own applications (e.g., browser search) from reaching the host.
        """
        try:
            if self.window_name is None:
                return False

            # Best-effort: if anything fails, block input to avoid leaking keystrokes.
            if not hasattr(ctypes, "windll"):
                return False

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False

            length = user32.GetWindowTextLengthW(hwnd)
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)

            title = (title_buf.value or "").strip()
            expected = str(self.window_name).strip()

            if not expected:
                return False

            # OpenCV uses the provided window name as the title.
            return expected in title
        except Exception:
            return False

    @staticmethod
    def _extract_wheel_delta(flags):
        # Prefer OpenCV helper when available; fallback to signed high-word parsing.
        if hasattr(cv2, "getMouseWheelDelta"):
            return cv2.getMouseWheelDelta(flags)
        delta = (flags >> 16) & 0xFFFF
        if delta >= 0x8000:
            delta -= 0x10000
        return delta

    def _mouse_callback(self, event, x, y, flags, param):
        if not self.channel or self.channel.readyState != "open":
            return
            
        msg = None
        if event == cv2.EVENT_MOUSEMOVE:
            msg = ControlMessage(type=MessageType.MOUSE_MOVE, x=x, y=y, screen_width=self.screen_width, screen_height=self.screen_height)
        elif event == cv2.EVENT_LBUTTONDOWN:
            msg = ControlMessage(type=MessageType.MOUSE_CLICK, button="left", pressed=True)
        elif event == cv2.EVENT_LBUTTONUP:
            msg = ControlMessage(type=MessageType.MOUSE_CLICK, button="left", pressed=False)
        elif event == cv2.EVENT_RBUTTONDOWN:
            msg = ControlMessage(type=MessageType.MOUSE_CLICK, button="right", pressed=True)
        elif event == cv2.EVENT_RBUTTONUP:
            msg = ControlMessage(type=MessageType.MOUSE_CLICK, button="right", pressed=False)
        elif event == cv2.EVENT_LBUTTONDBLCLK:
            msg = ControlMessage(type=MessageType.MOUSE_DOUBLE_CLICK, button="left")
        elif event == cv2.EVENT_RBUTTONDBLCLK:
            msg = ControlMessage(type=MessageType.MOUSE_DOUBLE_CLICK, button="right")
        elif event == cv2.EVENT_MOUSEWHEEL:
            delta = self._extract_wheel_delta(flags)
            steps = int(delta / 120) if delta else 0
            if steps == 0 and delta:
                steps = 1 if delta > 0 else -1
            msg = ControlMessage(
                type=MessageType.MOUSE_SCROLL,
                x=x,
                y=y,
                screen_width=self.screen_width,
                screen_height=self.screen_height,
                scroll_dx=0,
                scroll_dy=steps
            )
        elif event == cv2.EVENT_MOUSEHWHEEL:
            delta = self._extract_wheel_delta(flags)
            steps = int(delta / 120) if delta else 0
            if steps == 0 and delta:
                steps = 1 if delta > 0 else -1
            msg = ControlMessage(
                type=MessageType.MOUSE_SCROLL,
                x=x,
                y=y,
                screen_width=self.screen_width,
                screen_height=self.screen_height,
                scroll_dx=steps,
                scroll_dy=0
            )
            
        if msg:
            self.channel.send(msg.to_json())

    @staticmethod
    def _normalize_key(key):
        if isinstance(key, KeyCode):
            if key.char:
                char = key.char
                # When Ctrl is held, platforms may emit control chars (\x01..\x1a)
                # instead of literal letters. Convert back to a-z for shortcuts.
                if len(char) == 1 and 1 <= ord(char) <= 26:
                    return chr(ord(char) + 96)
                return char.lower()
            return None

        if isinstance(key, Key):
            name = str(key).replace("Key.", "")
            # Normalize common aliases for better cross-platform compatibility.
            aliases = {
                "ctrl": "ctrl",
                "ctrl_l": "ctrl_l",
                "ctrl_r": "ctrl_r",
                "alt": "alt",
                "alt_l": "alt_l",
                "alt_r": "alt_r",
                "alt_gr": "alt_gr",
                "shift": "shift",
                "shift_l": "shift_l",
                "shift_r": "shift_r",
                "cmd": "cmd",
                "cmd_l": "cmd_l",
                "cmd_r": "cmd_r",
                "super": "cmd",
                "super_l": "cmd_l",
                "super_r": "cmd_r",
                "esc": "esc",
                "space": "space",
                "tab": "tab",
                "enter": "enter",
                "backspace": "backspace",
                "delete": "delete",
                "insert": "insert",
                "home": "home",
                "end": "end",
                "page_up": "page_up",
                "page_down": "page_down",
                "up": "up",
                "down": "down",
                "left": "left",
                "right": "right",
            }
            if name in aliases:
                return aliases[name]

            # Function keys: f1..f24
            if name.startswith("f") and name[1:].isdigit():
                return name

        return None

    def _send_key(self, key_name, pressed):
        if not self.channel or self.channel.readyState != "open":
            return
        msg = ControlMessage(type=MessageType.KEYBOARD, key=key_name, pressed=pressed)
        self.channel.send(msg.to_json())

    def _send_key_threadsafe(self, key_name, pressed):
        # Keyboard callbacks come from pynput thread; marshal sends to asyncio loop thread.
        if not self.loop or self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(self._send_key, key_name, pressed)

    def _on_key_press(self, key):
        try:
            if self._enable_focus_gating and not self._is_target_window_foreground():
                return
            key_name = self._normalize_key(key)
            if not key_name:
                return
            if key_name in self._pressed_keys:
                return
            self._pressed_keys.add(key_name)
            self._send_key_threadsafe(key_name, True)
        except Exception as e:
            logger.error(f"Keyboard press handling error: {e}")

    def _on_key_release(self, key):
        try:
            key_name = self._normalize_key(key)
            if not key_name:
                return
            # If we didn't forward this key-press to the host, ignore the release too.
            # This keeps the host's modifier/keypress state from getting corrupted.
            if key_name not in self._pressed_keys:
                return
            self._pressed_keys.discard(key_name)
            self._send_key_threadsafe(key_name, False)
        except Exception as e:
            logger.error(f"Keyboard release handling error: {e}")

    def close(self):
        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None
