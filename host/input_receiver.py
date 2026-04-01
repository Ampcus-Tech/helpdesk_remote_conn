from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, Key
import logging
import platform
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.messages import ControlMessage

logger = logging.getLogger("input_receiver")

class InputReceiver:
    def __init__(self):
        # Check macOS permissions for input control
        if platform.system() == "Darwin":
            try:
                self.mouse = MouseController()
                self.keyboard = KeyboardController()
                # Test basic mouse movement to check accessibility permissions
                original_pos = self.mouse.position
                self.mouse.position = (original_pos[0], original_pos[1])
            except Exception as e:
                raise PermissionError(
                    "macOS Accessibility permission required.\n"
                    "Go to System Settings → Privacy & Security → Accessibility\n"
                    "and enable for your terminal application."
                )
        else:
            self.mouse = MouseController()
            self.keyboard = KeyboardController()
        
        import mss
        with mss.mss() as sct:
            self.screen_width = sct.monitors[1]["width"]
            self.screen_height = sct.monitors[1]["height"]

    def handle_mouse_move(self, msg: ControlMessage):
        cw = msg.screen_width
        ch = msg.screen_height
        if not cw or not ch:
            return
            
        hx = int((msg.x / cw) * self.screen_width)
        hy = int((msg.y / ch) * self.screen_height)
        self.mouse.position = (hx, hy)
        
    def handle_mouse_click(self, msg: ControlMessage):
        btn = Button.left if msg.button == "left" else Button.right
        if msg.pressed:
            self.mouse.press(btn)
        else:
            self.mouse.release(btn)

    def handle_mouse_double_click(self, msg: ControlMessage):
        btn = Button.left if msg.button == "left" else Button.right
        self.mouse.click(btn, 2)

    def handle_mouse_scroll(self, msg: ControlMessage):
        # Ensure scroll happens at the same on-screen target as the client pointer.
        if (
            msg.x is not None
            and msg.y is not None
            and msg.screen_width
            and msg.screen_height
        ):
            hx = int((msg.x / msg.screen_width) * self.screen_width)
            hy = int((msg.y / msg.screen_height) * self.screen_height)
            self.mouse.position = (hx, hy)

        dx = msg.scroll_dx or 0
        dy = msg.scroll_dy or 0
        if dx == 0 and dy == 0:
            return
        # Pynput scroll units are coarse; boost a little for Windows explorer feel.
        if dx != 0:
            dx = 2 if dx > 0 else -2
        if dy != 0:
            dy = 2 if dy > 0 else -2
        self.mouse.scroll(dx, dy)
            
    def handle_keyboard(self, msg: ControlMessage):
        key = msg.key
        try:
            # simple mapping
            if hasattr(Key, key):
                k = getattr(Key, key)
            elif len(key) == 1:
                k = key
            else:
                return # unknown
                
            if msg.pressed:
                self.keyboard.press(k)
            else:
                self.keyboard.release(k)
        except Exception as e:
            logger.error(f"Error handling key {key}: {e}")
