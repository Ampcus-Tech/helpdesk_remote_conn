import cv2
from common.messages import ControlMessage, MessageType

class InputSender:
    def __init__(self, window_name, data_channel):
        self.window_name = window_name
        self.channel = data_channel
        self.screen_width = 1920
        self.screen_height = 1080
        
        cv2.setMouseCallback(self.window_name, self._mouse_callback)
        
    def update_screen_size(self, width, height):
        self.screen_width = width
        self.screen_height = height

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

    def handle_keyboard(self, key_code):
        if not self.channel or self.channel.readyState != "open":
            return
        if key_code == -1:
            return
            
        special_keys = {
            2424832: "left",
            2490368: "up",
            2555904: "right",
            2621440: "down",
        }

        try:
            key = special_keys.get(key_code)
            if key is None:
                key = chr(key_code & 0xFF)

            msg = ControlMessage(type=MessageType.KEYBOARD, key=key, pressed=True)
            self.channel.send(msg.to_json())
            
            # Simulated key up
            msg.pressed = False
            self.channel.send(msg.to_json())
        except ValueError:
            pass
