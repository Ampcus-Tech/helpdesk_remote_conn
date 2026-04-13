import json
import logging
import os

_log = logging.getLogger(__name__)

# Networking
# When using Ngrok, keep SIGNALING_HOST as "0.0.0.0"
SIGNALING_HOST = os.getenv("SIGNALING_HOST", "0.0.0.0")
SIGNALING_PORT = 8080

# FOR NGROK: Change this to "wss://xxxx.ngrok-free.app"
# FOR LOCAL: It will automatically use ws://0.0.0.0:8080
SIGNALING_URL = os.getenv("SIGNALING_URL", "wss://kiera-unsensory-kathrine.ngrok-free.dev")
NO_RELAY = os.getenv("NO_RELAY", "").lower() in ("1", "true", "yes")


def _metered_turn_urls_udp_first() -> list[str]:
    """UDP TURN first (lower latency when UDP is allowed)."""
    return [
        "turn:global.relay.metered.ca:80",
        "turn:global.relay.metered.ca:443?transport=tcp",
        "turns:global.relay.metered.ca:443?transport=tcp",
    ]


def _metered_turn_urls_tcp_first() -> list[str]:
    """
    TURNS/TCP first — best default for internet / office firewalls.
    aiortc only applies the *first* TURN URL it sees (see rtcicetransport.connection_kwargs).
    """
    return [
        "turns:global.relay.metered.ca:443?transport=tcp",
        "turn:global.relay.metered.ca:443?transport=tcp",
        "turn:global.relay.metered.ca:80",
    ]


def _default_ice_servers() -> list[dict]:
    if NO_RELAY:
        # STUN-only mode (no TURN relay). Direct P2P only.
        return [
            {
                "urls": [
                    "stun:stun.l.google.com:19302",
                    "stun:stun1.l.google.com:19302",
                ]
            }
        ]

    # Metered Open Relay: create your own app at https://www.metered.ca/tools/openrelay/
    turn_user = os.getenv("TURN_USERNAME", "587951adfe11be5490c837ef")
    turn_cred = os.getenv("TURN_CREDENTIAL", "bpKpuMJZ0XIBT49m")
    # Latency-first default: prefer UDP relay when available.
    # If your network blocks UDP TURN, set ICE_UDP_TURN_FIRST=0.
    udp_first_env = os.getenv("ICE_UDP_TURN_FIRST", "1").lower()
    if udp_first_env in ("1", "true", "yes"):
        turn_urls = _metered_turn_urls_udp_first()
    else:
        turn_urls = _metered_turn_urls_tcp_first()
    return [
        {
            "urls": [
                "stun:stun.l.google.com:19302",
                "stun:stun1.l.google.com:19302",
            ]
        },
        {"urls": turn_urls, "username": turn_user, "credential": turn_cred},
    ]


def _load_ice_servers() -> list[dict]:
    raw = os.getenv("ICE_SERVERS_JSON")
    if not raw:
        return _default_ice_servers()
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("ICE_SERVERS_JSON must be a JSON array of objects")
        return parsed
    except (json.JSONDecodeError, ValueError) as e:
        _log.warning("ICE_SERVERS_JSON invalid (%s); using built-in defaults", e)
        return _default_ice_servers()
    
    
# STUN / TURN — required for NAT traversal across different networks.
# Override: ICE_SERVERS_JSON, or TURN_USERNAME + TURN_CREDENTIAL, or ICE_UDP_TURN_FIRST=1.
ICE_SERVERS = _load_ice_servers()

# Video settings
# 24 FPS is a better default for interactive remote control over internet links:
# it reduces bitrate spikes during full-window changes while staying visually smooth.
TARGET_FPS = int(os.getenv("TARGET_FPS", "24"))
DEFAULT_QUALITY = "high"
QUALITY_SETTINGS = {
    "low": {
        "scale": 0.5,
        "jpeg_quality": 30,
    },
    "medium": {
        "scale": 0.75,
        "jpeg_quality": 60,
    },
    "high": {
        "scale": 1.0,
        "jpeg_quality": 85,
    }
}

# WebRTC video codec/bitrate tuning.
# Note: Your current `aiortc` version supports `VP8` and `H264` (not `VP9`).
VIDEO_CODEC = os.getenv("VIDEO_CODEC", "h264").lower()  # "vp8" or "h264"
VIDEO_BITRATE = int(os.getenv("VIDEO_BITRATE", "4500000"))  # bits per second
VIDEO_BITRATE_MIN = int(os.getenv("VIDEO_BITRATE_MIN", "1800000"))
VIDEO_BITRATE_MAX = int(os.getenv("VIDEO_BITRATE_MAX", "8000000"))

# Capture-side resolution guardrail for smoother real-time streaming.
# Useful when host desktop is 2K/4K and bandwidth/CPU are limited.
# Set either value to 0 to disable that cap.
CAPTURE_MAX_WIDTH = int(os.getenv("CAPTURE_MAX_WIDTH", "1920"))
CAPTURE_MAX_HEIGHT = int(os.getenv("CAPTURE_MAX_HEIGHT", "1080"))

# Data Channel Names
CTRL_CHANNEL_NAME = "control"
CHAT_CHANNEL_NAME = "chat"
FILE_CHANNEL_NAME = "file"

# Logging Config
def setup_logging(level=logging.INFO):
    logging.basicConfig(level=level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
