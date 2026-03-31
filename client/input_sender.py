import cv2
import logging
import ctypes
import json
import threading
import time
import platform
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
  
        # Cross-platform cursor handling. Initialize with default arrow.
        self._current_cursor_obj = None
        self._ns_cursor = None
        
        if platform.system() == "Windows" and hasattr(ctypes, "windll"):
            self._current_cursor_obj = ctypes.windll.user32.LoadCursorW(0, 32512)  # IDC_ARROW
        elif platform.system() == "Darwin":
            try:
                from AppKit import NSCursor
                self._ns_cursor = NSCursor
                self._current_cursor_obj = NSCursor.arrowCursor()
            except ImportError:
                pass
        elif platform.system() == "Linux":
            try:
                from Xlib import display, X
                self._x_display = display.Display()
                self._x_window_id = None
            except ImportError:
                pass

        if self.channel:
            @self.channel.on("message")
            def on_message(message):
                try:
                    data = json.loads(message)
                    if data.get("type") == MessageType.CURSOR_UPDATE:
                        cname = data.get("cursor_name")
                        if cname:
                            self.loop.call_soon_threadsafe(self._update_local_cursor, cname)
                except Exception:
                    pass

        self._mouse_listener = MouseListener(on_click=self._on_mouse_click)
        self._mouse_listener.start()
        self._keyboard_listener = None
        self._keyboard_listener_suppressed = False

        # Start/stop the keyboard hook based on focus.
        # On Windows we can suppress local key delivery (so Win+R doesn't open locally).
        # When the remote window is not active/minimized, we stop the hook so the client PC works normally.
        self._focus_thread_stop = threading.Event()
        self._focus_thread = threading.Thread(target=self._focus_monitor_loop, daemon=True)
        self._focus_thread.start()
        
        cv2.setMouseCallback(self.window_name, self._mouse_callback)
        
        # Windows-specific: Force the window class cursor to an arrow. 
        # OpenCV windows often default to an I-beam on Windows if not explicitly overridden.
        if hasattr(ctypes, "windll"):
            threading.Thread(target=self._force_arrow_cursor_delayed, daemon=True).start()

    def _force_arrow_cursor_delayed(self):
        """Find the window and override its class cursor to prevent it defaulting to I-beam."""
        # Wait a bit for the window to actually be created by OpenCV.
        for _ in range(10): 
            try:
                hwnd = ctypes.windll.user32.FindWindowW(None, self.window_name)
                if hwnd:
                    # GCLP_HCURSOR = -12
                    h_arrow = ctypes.windll.user32.LoadCursorW(0, 32512)
                    # Set the class cursor once. This usually stops the I-beam default.
                    if hasattr(ctypes.windll.user32, "SetClassLongPtrW"):
                        ctypes.windll.user32.SetClassLongPtrW(hwnd, -12, h_arrow)
                    else:
                        ctypes.windll.user32.SetClassLongW(hwnd, -12, h_arrow)
                    break
            except Exception:
                pass
            time.sleep(0.5)

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

            # Best-effort focus gating:
            # - Windows: check real foreground window + minimized state.
            # - macOS/Linux: fall back to OpenCV window visibility (best-effort).
            if not hasattr(ctypes, "windll"):
                try:
                    visible = cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE)
                    return visible > 0
                except Exception:
                    # If we cannot determine visibility, block forwarding to avoid leaking.
                    return False

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False
            # If the remote desktop window is minimized, stop forwarding keystrokes
            # so the local client app behaves normally.
            if hasattr(user32, "IsIconic") and user32.IsIconic(hwnd):
                return False
            if hasattr(user32, "IsWindowVisible") and not user32.IsWindowVisible(hwnd):
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

    def _apply_cursor(self):
        """Apply the currently selected cursor shape to the local window."""
        if not self._current_cursor_obj:
            return
            
        sys_platform = platform.system()
        if sys_platform == "Windows" and hasattr(ctypes, "windll"):
            ctypes.windll.user32.SetCursor(self._current_cursor_obj)
        elif sys_platform == "Darwin":
            try:
                self._current_cursor_obj.set()
            except Exception:
                pass

    def _mouse_callback(self, event, x, y, flags, param):
        if not self.channel or self.channel.readyState != "open":
            return

        # Synchronize local cursor with the remote host's current shape.
        self._apply_cursor()
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
                # Windows system keys / locks / screenshot
                "caps_lock": "caps_lock",
                "num_lock": "num_lock",
                "scroll_lock": "scroll_lock",
                "pause": "pause",
                "print_screen": "print_screen",
                "menu": "menu",
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

    def _release_all_pressed_keys_threadsafe(self) -> None:
        """Best-effort: prevent stuck modifiers on the host when focus changes."""
        try:
            if not self._pressed_keys:
                return
            # Copy before clearing to avoid mutation during iteration.
            keys = list(self._pressed_keys)
            self._pressed_keys.clear()
            for k in keys:
                self._send_key_threadsafe(k, False)
        except Exception:
            pass

    def _ensure_keyboard_listener(self, should_run: bool) -> None:
        """
        Start/stop the global keyboard listener depending on whether the remote window
        is active. On Windows, we run with suppress=True so client shortcuts don't fire locally.
        """
        try:
            if should_run:
                if self._keyboard_listener:
                    return
                suppress = bool(hasattr(ctypes, "windll"))
                self._keyboard_listener_suppressed = suppress
                self._keyboard_listener = KeyboardListener(
                    on_press=self._on_key_press,
                    on_release=self._on_key_release,
                    suppress=suppress,
                )
                self._keyboard_listener.start()
            else:
                if not self._keyboard_listener:
                    return
                # Release anything we may have sent to the host.
                self._release_all_pressed_keys_threadsafe()
                try:
                    self._keyboard_listener.stop()
                finally:
                    self._keyboard_listener = None
                    self._keyboard_listener_suppressed = False
        except TypeError:
            # Some platforms/builds may not support suppress=.
            if should_run and not self._keyboard_listener:
                self._keyboard_listener = KeyboardListener(
                    on_press=self._on_key_press,
                    on_release=self._on_key_release,
                )
                self._keyboard_listener.start()
            elif not should_run and self._keyboard_listener:
                self._release_all_pressed_keys_threadsafe()
                try:
                    self._keyboard_listener.stop()
                finally:
                    self._keyboard_listener = None
                    self._keyboard_listener_suppressed = False
        except Exception:
            # Never crash the client due to keyboard hook issues.
            pass

    def _focus_monitor_loop(self) -> None:
        """
        Poll focus/visibility and only keep the keyboard hook active when the
        remote window is actually active. This is what prevents Win+R/etc from
        triggering on the client PC while controlling the host.
        """
        last_should_run = None
        while not self._focus_thread_stop.is_set():
            try:
                should_run = True
                if self._enable_focus_gating:
                    should_run = self._is_target_window_foreground()

                if should_run != last_should_run:
                    self._ensure_keyboard_listener(should_run)
                    last_should_run = should_run
            except Exception:
                pass
            time.sleep(0.05)

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
            # Focus is handled by the focus monitor starting/stopping the listener.
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

    def _update_local_cursor(self, cursor_name: str):
        """Map standardized names to platform-specific cursor objects and apply them."""
        sys_platform = platform.system()
        
        if sys_platform == "Windows" and hasattr(ctypes, "windll"):
            mapping = {
                "arrow": 32512, "ibeam": 32513, "wait": 32514, "crosshair": 32515,
                "hand": 32649, "size_all": 32646, "size_we": 32644, "size_ns": 32645,
                "size_nwse": 32642, "size_nesw": 32643, "uparrow": 32516,
                "no": 32648, "appstarting": 32650, "help": 32651
            }
            idc = mapping.get(cursor_name, 32512)
            h = ctypes.windll.user32.LoadCursorW(0, idc)
            if h:
                self._current_cursor_obj = h
                self._apply_cursor()
                
        elif sys_platform == "Darwin" and self._ns_cursor:
            # Map standardized names to AppKit NSCursor methods
            mapping = {
                "arrow": "arrowCursor",
                "ibeam": "IBeamCursor",
                "hand": "pointingHandCursor",
                "crosshair": "crosshairCursor",
                "size_we": "resizeLeftRightCursor",
                "size_ns": "resizeUpDownCursor",
                "size_all": "openHandCursor",
            }
            method_name = mapping.get(cursor_name, "arrowCursor")
            if hasattr(self._ns_cursor, method_name):
                try:
                    self._current_cursor_obj = getattr(self._ns_cursor, method_name)()
                    self._apply_cursor()
                except Exception:
                    pass
                    
        elif sys_platform == "Linux" and hasattr(self, "_x_display") and self._x_display:
            try:
                from Xlib import X
                # Find current OpenCV window if not already found
                if not self._x_window_id:
                    # Generic search for window by title
                    root = self._x_display.screen().root
                    window_ids = root.get_full_property(self._x_display.intern_atom('_NET_CLIENT_LIST'), X.AnyPropertyType).value
                    for wid in window_ids:
                        win = self._x_display.create_resource_object('window', wid)
                        name = win.get_wm_name()
                        if name == self.window_name:
                            self._x_window_id = win
                            break
                
                if self._x_window_id:
                    # Map names to X11 Font Cursors
                    # http://tronche.com/gui/x/xlib/appendix/b/
                    mapping = {
                        "arrow": 68, "ibeam": 152, "wait": 150, "crosshair": 34,
                        "hand": 60, "size_all": 52, "size_we": 108, "size_ns": 116,
                        "size_nwse": 134, "size_nesw": 12, "uparrow": 144,
                        "no": 30, "help": 92
                    }
                    cursor_id = mapping.get(cursor_name, 68)
                    cursor = self._x_display.create_font_cursor(cursor_id)
                    self._x_window_id.define_cursor(cursor)
                    self._x_display.flush()
            except Exception:
                pass

    def close(self):
        if self._focus_thread_stop:
            self._focus_thread_stop.set()
            self._focus_thread_stop = None
        if self._focus_thread:
            try:
                self._focus_thread.join(timeout=0.5)
            except Exception:
                pass
            self._focus_thread = None
        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None