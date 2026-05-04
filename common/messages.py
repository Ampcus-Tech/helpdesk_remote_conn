from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
import json

class MessageType:
    REGISTER_HOST = "register_host"
    FIND_HOST = "find_host"
    HOST_REGISTERED = "host_registered"
    HOST_NOT_FOUND = "host_not_found"
    AUTH_FAILED = "auth_failed"
    AUTH_RATE_LIMITED = "auth_rate_limited"
    SDP = "sdp"
    ICE = "ice"

    # Data channel messages
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_DOUBLE_CLICK = "mouse_double_click"
    MOUSE_SCROLL = "mouse_scroll"
    KEYBOARD = "keyboard"
    QUALITY_CHANGE = "quality_change"
    CURSOR_UPDATE = "cursor_update"
    CHAT_TEXT = "chat_text"
    FILE_OFFER = "file_offer"
    FILE_ACCEPT = "file_accept"
    FILE_START = "file_start"
    FILE_CHUNK = "file_chunk"
    FILE_END = "file_end"
    HOST_INFO = "host_info"

@dataclass
class SignalingMessage:
    type: str
    host_id: Optional[str] = None
    connection_id: Optional[str] = None
    password: Optional[str] = None
    password_hash: Optional[str] = None
    password_salt: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    sdp: Optional[Dict[str, Any]] = None
    candidate: Optional[Dict[str, Any]] = None
    
    def to_json(self) -> str:
        return json.dumps({k: v for k, v in asdict(self).items() if v is not None})
    
    @classmethod
    def from_json(cls, data: str) -> "SignalingMessage":
        obj = json.loads(data)
        return cls(**obj)

@dataclass
class ControlMessage:
    type: str
    # Mouse move
    x: Optional[float] = None
    y: Optional[float] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    # Mouse click
    button: Optional[str] = None
    pressed: Optional[bool] = None
    # Keyboard
    key: Optional[str] = None
    modifiers: Optional[List[str]] = None
    # Mouse scroll
    scroll_dx: Optional[int] = None
    scroll_dy: Optional[int] = None
    # Quality
    quality: Optional[str] = None
    cursor_name: Optional[str] = None
    os: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps({k: v for k, v in asdict(self).items() if v is not None})
    
    @classmethod
    def from_json(cls, data: str) -> "ControlMessage":
        obj = json.loads(data)
        return cls(**obj)
