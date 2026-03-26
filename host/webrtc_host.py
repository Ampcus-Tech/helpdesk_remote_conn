import asyncio
import json
import logging
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc import RTCRtpSender
import websockets
try:
    import ctypes
    from ctypes import wintypes
except ImportError:
    ctypes = None

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.messages import SignalingMessage, MessageType, ControlMessage
from common.config import (
    SIGNALING_URL,
    ICE_SERVERS,
    CTRL_CHANNEL_NAME,
    VIDEO_CODEC,
    VIDEO_BITRATE,
    VIDEO_BITRATE_MIN,
    VIDEO_BITRATE_MAX,
)
from host.screen_capture import ScreenCaptureTrack
from host.input_receiver import InputReceiver

# Standardized cursor names used across all platforms
# To support Mac/Linux, add their specific detection logic and map to these names.
WIN_CURSOR_NAME_MAP = {
    32512: "arrow",
    32513: "ibeam",
    32514: "wait",
    32515: "crosshair",
    32516: "uparrow",
    32642: "size_nwse",
    32643: "size_nesw",
    32644: "size_we",
    32645: "size_ns",
    32646: "size_all",
    32648: "no",
    32649: "hand",
    32650: "appstarting",
    32651: "help",
}

if ctypes:
    class CURSORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hCursor", wintypes.HANDLE),
            ("ptScreenPos", wintypes.POINT),
        ]

logger = logging.getLogger("webrtc_host")

class WebRTCHost:
    def __init__(self, host_id, on_event=None):
        self.host_id = host_id
        self.pc = None
        self.ws = None
        self.input_receiver = InputReceiver()
        self.on_event = on_event
        
        # Cursor tracking state (Cross-platform ready)
        self._cursor_handles = {}
        if ctypes and hasattr(ctypes, "windll"):
            for cid in WIN_CURSOR_NAME_MAP.keys():
                h = ctypes.windll.user32.LoadCursorW(0, cid)
                if h:
                    self._cursor_handles[h] = WIN_CURSOR_NAME_MAP[cid]
        self._last_cursor_name = None
        self._cursor_task = None

    def _emit(self, message: str) -> None:
        """Send lightweight status updates to the UI (if provided)."""
        try:
            if self.on_event:
                self.on_event(message)
        except Exception:
            # Never break the session due to UI callbacks.
            pass

    async def create_pc(self):
        # aiortc's VP8/H264 encoders take bitrate from module-level defaults.
        # Set them before the first encoded frame is produced.
        if VIDEO_CODEC == "h264":
            import aiortc.codecs.h264 as h264

            h264.DEFAULT_BITRATE = VIDEO_BITRATE
            h264.MIN_BITRATE = VIDEO_BITRATE_MIN
            h264.MAX_BITRATE = VIDEO_BITRATE_MAX
        elif VIDEO_CODEC == "vp8":
            import aiortc.codecs.vpx as vpx

            vpx.DEFAULT_BITRATE = VIDEO_BITRATE
            vpx.MIN_BITRATE = VIDEO_BITRATE_MIN
            vpx.MAX_BITRATE = VIDEO_BITRATE_MAX
        else:
            logger.warning("Unknown VIDEO_CODEC=%r; falling back to aiortc defaults", VIDEO_CODEC)

        # Convert dict configs to RTCIceServer objects
        ice_servers = [RTCIceServer(**server) for server in ICE_SERVERS]
        config = RTCConfiguration(iceServers=ice_servers)
        self.pc = RTCPeerConnection(configuration=config)

        # Add video track
        video_track = ScreenCaptureTrack()
        video_sender = self.pc.addTrack(video_track)

        # Prefer a specific codec for negotiation (helps quality/latency).
        # aiortc (your version) supports VP8 and H264; VP9 is not available.
        caps = RTCRtpSender.getCapabilities("video").codecs
        if VIDEO_CODEC == "h264":
            main_mime = "video/H264"
        else:
            main_mime = "video/VP8"

        preferred = [c for c in caps if c.mimeType == main_mime]
        preferred.extend([c for c in caps if c.mimeType == "video/rtx"])

        # Apply preferences to the transceiver created by addTrack().
        for transceiver in self.pc.getTransceivers():
            if transceiver.sender == video_sender:
                transceiver.setCodecPreferences(preferred)
                break

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            logger.info(f"Data channel {channel.label} received")
            if channel.label == CTRL_CHANNEL_NAME:
                # Start tracking host cursor shape to sync with client
                if self._cursor_task and not self._cursor_task.done():
                    self._cursor_task.cancel()
                self._cursor_task = asyncio.create_task(self._cursor_tracking_loop(channel))

                @channel.on("message")
                def on_message(message):
                    try:
                        msg = ControlMessage.from_json(message)
                        if msg.type == MessageType.MOUSE_MOVE:
                            self.input_receiver.handle_mouse_move(msg)
                        elif msg.type == MessageType.MOUSE_CLICK:
                            self.input_receiver.handle_mouse_click(msg)
                        elif msg.type == MessageType.MOUSE_DOUBLE_CLICK:
                            self.input_receiver.handle_mouse_double_click(msg)
                        elif msg.type == MessageType.MOUSE_SCROLL:
                            self.input_receiver.handle_mouse_scroll(msg)
                        elif msg.type == MessageType.KEYBOARD:
                            self.input_receiver.handle_keyboard(msg)
                    except Exception as e:
                        logger.error(f"Error processing control message: {e}")

        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info(f"ICE connection state is {self.pc.iceConnectionState}")
            if self.pc.iceConnectionState == "failed":
                await self.pc.close()

    async def _cursor_tracking_loop(self, channel):
        """Periodically check the host's move cursor shape and sync it to the client."""
        if not ctypes or not hasattr(ctypes, "windll"):
            # Placeholder for macOS/Linux detection logic
            return

        info = CURSORINFO()
        info.cbSize = ctypes.sizeof(CURSORINFO)
        user32 = ctypes.windll.user32

        try:
            while channel.readyState == "open":
                info.cbSize = ctypes.sizeof(CURSORINFO) # Reset every time for safety
                if user32.GetCursorInfo(ctypes.byref(info)):
                    # Map the current handle to our standardized cursor names
                    cname = self._cursor_handles.get(info.hCursor, "arrow")
                    if cname != self._last_cursor_name:
                        self._last_cursor_name = cname
                        msg = ControlMessage(type=MessageType.CURSOR_UPDATE, cursor_name=cname)
                        channel.send(msg.to_json())
                await asyncio.sleep(0.1) # 10Hz sync rate
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Cursor tracking error: {e}")

    async def connect_signaling(self):
        logger.info(f"Connecting to signaling server at {SIGNALING_URL}")
        self._emit(f"Connecting to signaling server...")
        try:
            self.ws = await websockets.connect(SIGNALING_URL)
        except asyncio.TimeoutError:
            logger.error("Signaling error: Timed out during opening handshake.")
            print("\n" + "!"*60)
            print("DIAGNOSTIC: Host Signaling Timeout!")
            print(f"Target URL: {SIGNALING_URL}")
            print("REASON: The Signaling Server is not reachable.")
            print("FIX: Check if signaling/server.py is running on this PC.")
            print("FIX: Check firewall settings for port 8080.")
            print("!"*60 + "\n")
            raise
        
        reg_msg = SignalingMessage(type=MessageType.REGISTER_HOST, host_id=self.host_id)
        await self.ws.send(reg_msg.to_json())

        async for message in self.ws:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == MessageType.HOST_REGISTERED:
                logger.info("Host registered successfully.")
                self._emit(f"Host registered. Waiting for client...")
                
            elif msg_type == MessageType.SDP:
                logger.info("Received SDP offer")
                self._emit("Client requested connection. Exchanging SDP...")
                sdp = data.get("sdp")
                offer = RTCSessionDescription(sdp=sdp["sdp"], type=sdp["type"])
                
                await self.create_pc()
                await self.pc.setRemoteDescription(offer)
                
                answer = await self.pc.createAnswer()
                await self.pc.setLocalDescription(answer)
                
                ans_msg = SignalingMessage(
                    type=MessageType.SDP,
                    sdp={"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type}
                )
                await self.ws.send(ans_msg.to_json())

    async def run(self):
        try:
            await self.connect_signaling()
        except asyncio.CancelledError:
            pass
        finally:
            if self.pc:
                await self.pc.close()
            if self.ws:
                await self.ws.close()
