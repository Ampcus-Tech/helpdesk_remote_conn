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
