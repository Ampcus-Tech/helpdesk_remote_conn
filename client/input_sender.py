import cv2
import json
import logging
import ctypes
import sys
from pynput.keyboard import Listener as KeyboardListener, Key, KeyCode
from pynput.mouse import Listener as MouseListener, Button as MouseButton
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
        self._pressed_mouse_buttons = set()
        self._enable_focus_gating = True
        
        # Cross-platform shortcut handling: Detect if we are on Mac to map Cmd to Ctrl for shortcuts.
        self._is_mac = sys.platform == "darwin"
        self._remap_shortcuts = True  # Enable for intuitive cross-platform experience.
        self._host_os = "win32" if self._is_mac else None  # Default assumption
  
        # Cross-platform cursor handling: current handle and mapping.
        self._h_cursor_current = None
        if hasattr(ctypes, "windll"):
            self._h_cursor_current = ctypes.windll.user32.LoadCursorW(0, 32512)  # Default arrow

        if self.channel:
            @self.channel.on("message")
            def on_message(message):
                try:
                    data = json.loads(message)
                    if data.get("type") == MessageType.CURSOR_UPDATE:
                        cname = data.get("cursor_name")
                        if cname:
                            self._update_local_cursor(cname)
                except Exception:
                    pass

        self._mouse_listener = MouseListener(on_click=self._on_mouse_click)
        self._mouse_listener.start()
        
        # On Windows, we use a win32_event_filter to selectively swallow system shortcuts
        # like Win+R locally when the remote window is focused.
        filter_params = {}
        if not self._is_mac and hasattr(ctypes, "windll"):
            filter_params["win32_event_filter"] = self._win32_event_filter

        self._keyboard_listener = KeyboardListener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
            **filter_params
        )
        self._keyboard_listener.start()
        
        cv2.setMouseCallback(self.window_name, self._mouse_callback)
        
    def set_host_os(self, host_os: str):
        """Configure remapping logic based on the host operating system."""
        self._host_os = host_os.lower()
        logger.info(f"InputSender host OS set to: {self._host_os}")

    def update_screen_size(self, width, height):
        self.screen_width = width
        self.screen_height = height

    def _is_target_window_foreground(self) -> bool:
        """
        On Windows, only forward keyboard input when the OpenCV "Remote Desktop"
        window is the foreground window. This prevents keystrokes typed into the
        client's own applications (e.g., browser search) from reaching the host.
        """
        try:
            if self.window_name is None:
                return False

            # For non-Windows platforms, we skip focus gating for now as standard OpenCV/ctypes
            # don't provide a trivial cross-platform way to check window focus.
            if not hasattr(ctypes, "windll"):
                return True

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

        # Synchronize local cursor with the remote host's current shape.
        if self._h_cursor_current:
            ctypes.windll.user32.SetCursor(self._h_cursor_current)
        is_foreground = True
        if self._enable_focus_gating:
            is_foreground = self._is_target_window_foreground()
            
        msg = None
        if event == cv2.EVENT_MOUSEMOVE:
            if self._enable_focus_gating and not is_foreground:
                return
            msg = ControlMessage(type=MessageType.MOUSE_MOVE, x=x, y=y, screen_width=self.screen_width, screen_height=self.screen_height)
        elif event == cv2.EVENT_LBUTTONDOWN:
            if self._enable_focus_gating and not is_foreground:
                return
            self._pressed_mouse_buttons.add("left")
            msg = ControlMessage(type=MessageType.MOUSE_CLICK, button="left", pressed=True)
        elif event == cv2.EVENT_LBUTTONUP:
            if self._enable_focus_gating and not is_foreground and "left" not in self._pressed_mouse_buttons:
                return
            if "left" not in self._pressed_mouse_buttons:
                return
            self._pressed_mouse_buttons.discard("left")
            msg = ControlMessage(type=MessageType.MOUSE_CLICK, button="left", pressed=False)
        elif event == cv2.EVENT_RBUTTONDOWN:
            if self._enable_focus_gating and not is_foreground:
                return
            self._pressed_mouse_buttons.add("right")
            msg = ControlMessage(type=MessageType.MOUSE_CLICK, button="right", pressed=True)
        elif event == cv2.EVENT_RBUTTONUP:
            if self._enable_focus_gating and not is_foreground and "right" not in self._pressed_mouse_buttons:
                return
            if "right" not in self._pressed_mouse_buttons:
                return
            self._pressed_mouse_buttons.discard("right")
            msg = ControlMessage(type=MessageType.MOUSE_CLICK, button="right", pressed=False)
        elif event == cv2.EVENT_LBUTTONDBLCLK:
            if self._enable_focus_gating and not is_foreground:
                return
            msg = ControlMessage(type=MessageType.MOUSE_DOUBLE_CLICK, button="left")
        elif event == cv2.EVENT_RBUTTONDBLCLK:
            if self._enable_focus_gating and not is_foreground:
                return
            msg = ControlMessage(type=MessageType.MOUSE_DOUBLE_CLICK, button="right")
        elif event == cv2.EVENT_MOUSEWHEEL:
            if self._enable_focus_gating and not is_foreground:
                return
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
            if self._enable_focus_gating and not is_foreground:
                return
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

    def _normalize_key(self, key):
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
            
            # Normalize common aliases and platform-specific names.
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
                "caps_lock": "caps_lock",
                "print_screen": "print_screen",
                "scroll_lock": "scroll_lock",
                "pause": "pause",
                "num_lock": "num_lock",
            }
            
            if name in aliases:
                normalized = aliases[name]
                
                # Cross-platform shortcut remapping
                if self._remap_shortcuts and self._host_os:
                    # Case 1: Mac Client controlling a Windows/Linux host
                    # Map Cmd (Mac) to Ctrl (Host) for standard shortcuts.
                    # Map Ctrl (Mac) to Win (Host Host) for system shortcuts.
                    if self._is_mac and ("win" in self._host_os or "linux" in self._host_os):
                        if normalized.startswith("cmd"):
                            return normalized.replace("cmd", "ctrl")
                        if normalized.startswith("ctrl"):
                            return normalized.replace("ctrl", "cmd")
                    
                    # Case 2: Windows Client controlling a Mac host
                    # Map Ctrl (Win) to Cmd (Mac) for standard shortcuts.
                    # Map Win (Win) to Ctrl (Mac) for system shortcuts.
                    elif not self._is_mac and "darwin" in self._host_os:
                        if normalized.startswith("ctrl"):
                            return normalized.replace("ctrl", "cmd")
                        if normalized.startswith("cmd"):
                            return normalized.replace("cmd", "ctrl")
                
                return normalized

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

    def _send_mouse_click(self, button_name: str, pressed: bool) -> None:
        if not self.channel or self.channel.readyState != "open":
            return
        msg = ControlMessage(type=MessageType.MOUSE_CLICK, button=button_name, pressed=pressed)
        self.channel.send(msg.to_json())

    def _send_mouse_click_threadsafe(self, button_name: str, pressed: bool) -> None:
        # Mouse callbacks come from pynput thread; marshal sends to asyncio loop thread.
        if not self.loop or self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(self._send_mouse_click, button_name, pressed)

    def _on_mouse_click(self, x, y, button, pressed):
        """
        Only used to prevent "stuck" mouse buttons if the release happens outside the
        OpenCV window (so cv2's mouse callback won't fire).

        We forward releases only for buttons we've already sent to the host.
        """
        try:
            if not self.channel or self.channel.readyState != "open":
                return

            button_name = None
            if button == MouseButton.left:
                button_name = "left"
            elif button == MouseButton.right:
                button_name = "right"

            if button_name is None:
                return

            if pressed:
                # Mouse presses are handled by OpenCV mouse callback (keeps coordinates consistent).
                return

            if button_name not in self._pressed_mouse_buttons:
                return

            # Ensure the pressed set is cleared immediately; the OpenCV callback may never fire.
            self._pressed_mouse_buttons.discard(button_name)
            self._send_mouse_click_threadsafe(button_name, False)
        except Exception as e:
            logger.error(f"Mouse click handling error: {e}")

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

    def _win32_event_filter(self, msg, data):
        """
        Windows-only callback to selectively swallow system shortcuts locally 
        while sending them to the remote machine.
        """
        try:
            # 1. Check if our window is focused.
            if not self._is_target_window_foreground():
                return True # Pass to local OS
                
            # 2. Check for system keys that cause local/remote conflicts.
            # vkCode for LWIN/RWIN (Windows Logo Key)
            vk = data.vkCode
            
            # Suppressing Win key (0x5B, 0x5C) prevents local Start menu/Run dialog
            # while allowing the pynput listener to still send them to the remote host.
            if vk in [0x5B, 0x5C]:
                return False # Swallows the event locally
                
            # Note: We keep Alt+Tab (0x09) as True locally by default so users 
            # don't get 'trapped' in the window, but Win+R is now exclusive to remote.
            return True 
        except Exception:
            return True

    def _update_local_cursor(self, cursor_name: str):
        """Map standardized names to platform-specific cursor IDs and apply them."""
        if not hasattr(ctypes, "windll"):
            return # Placeholder for Mac/Linux client cursor setting logic

        # Mapping names to Windows IDC constants.
        mapping = {
            "arrow": 32512, "ibeam": 32513, "wait": 32514, "crosshair": 32515,
            "hand": 32649, "size_all": 32646, "size_we": 32644, "size_ns": 32645,
            "size_nwse": 32642, "size_nesw": 32643, "uparrow": 32516,
            "no": 32648, "appstarting": 32650, "help": 32651
        }
        
        try:
            idc = mapping.get(cursor_name, 32512)
            h = ctypes.windll.user32.LoadCursorW(0, idc)
            if h:
                self._h_cursor_current = h
                ctypes.windll.user32.SetCursor(h)
        except Exception:
            pass

    def close(self):
        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None