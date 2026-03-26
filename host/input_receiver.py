from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, Key
import logging
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.messages import ControlMessage

logger = logging.getLogger("input_receiver")

class InputReceiver:
    def __init__(self):
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
        if not key:
            return
            
        try:
            # Map normalized names back to pynput Key objects or characters.
            k = None
            if hasattr(Key, key):
                k = getattr(Key, key)
            elif len(key) == 1:
                k = key
            else:
                # Fallback for common variations
                mapping = {
                    "win": Key.cmd,
                    "command": Key.cmd,
                    "control": Key.ctrl,
                    "option": Key.alt,
                    "escape": Key.esc,
                    "return": Key.enter,
                    "back": Key.backspace,
                }
                k = mapping.get(key.lower())
                
            if k is None:
                logger.warning(f"Unknown key received: {key}")
                return
                
            if msg.pressed:
                self.keyboard.press(k)
            else:
                self.keyboard.release(k)
        except Exception as e:
            logger.error(f"Error handling key {key}: {e}")
