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
            
        if msg:
            self.channel.send(msg.to_json())

    def handle_keyboard(self, key_code):
        if not self.channel or self.channel.readyState != "open":
            return
        if key_code == -1:
            return
            
        try:
            char = chr(key_code & 0xFF)
            msg = ControlMessage(type=MessageType.KEYBOARD, key=char, pressed=True)
            self.channel.send(msg.to_json())
            
            # Simulated key up
            msg.pressed = False
            self.channel.send(msg.to_json())
        except ValueError:
            pass
