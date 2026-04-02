import asyncio
import base64
import json
import logging
import os
import time
import uuid
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc import RTCRtpSender
import websockets
import platform
try:
    if platform.system() == "Windows":
        import ctypes
        from ctypes import wintypes
    else:
        ctypes = None
except ImportError:
    ctypes = None

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.messages import SignalingMessage, MessageType, ControlMessage
from common.config import (
    SIGNALING_URL,
    ICE_SERVERS,
    CTRL_CHANNEL_NAME,
    CHAT_CHANNEL_NAME,
    FILE_CHANNEL_NAME,
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

# Mac system cursor to standardized names
MAC_CURSOR_MAP = {
    "arrowCursor": "arrow",
    "IBeamCursor": "ibeam",
    "pointingHandCursor": "hand",
    "closedHandCursor": "size_all",
    "openHandCursor": "size_all",
    "resizeLeftRightCursor": "size_we",
    "resizeUpDownCursor": "size_ns",
    "crosshairCursor": "crosshair",
    "disappearingItemCursor": "no",
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
    def __init__(
        self,
        host_id,
        on_event=None,
        on_chat=None,
        on_file_offer=None,
        on_file_progress=None,
        on_file_done=None,
        command_queue=None,
    ):
        self.host_id = host_id
        self.pc = None
        self.ws = None
        self.command_queue = command_queue
        self.input_receiver = InputReceiver()
        self.on_event = on_event
        self.on_chat = on_chat
        self.on_file_offer = on_file_offer
        self.on_file_progress = on_file_progress
        self.on_file_done = on_file_done
        self.chat_channel = None
        self.file_channel = None
        self.loop = None
        self._pending_outgoing_accept = {}
        self._outgoing_accepted = {}
        self._incoming_targets = {}
        self._incoming_files = {}
        self._incoming_offers = {}
        self._chat_opened = False
        self._file_opened = False
        self._channels_ready = False
        
        # Cursor tracking state (Cross-platform ready)
        self._cursor_handles = {}
        if platform.system() == "Windows" and ctypes:
            for cid in WIN_CURSOR_NAME_MAP.keys():
                h = ctypes.windll.user32.LoadCursorW(0, cid)
                if h:
                    self._cursor_handles[h] = WIN_CURSOR_NAME_MAP[cid]
        elif platform.system() == "Darwin":
            try:
                from Cocoa import NSCursor
                self._ns_cursor = NSCursor
            except ImportError:
                self._ns_cursor = None
        
        self._last_cursor_name = None
        self._cursor_task = None
        self._command_task = None

    def _emit(self, message: str) -> None:
        """Send lightweight status updates to the UI (if provided)."""
        try:
            if self.on_event:
                self.on_event(message)
        except Exception:
            # Never break the session due to UI callbacks.
            pass

    async def create_pc(self):
        self.loop = asyncio.get_running_loop()
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
            elif channel.label == CHAT_CHANNEL_NAME:
                self.chat_channel = channel
                self._setup_chat_channel(channel)
            elif channel.label == FILE_CHANNEL_NAME:
                self.file_channel = channel
                self._setup_file_channel(channel)

        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info(f"ICE connection state is {self.pc.iceConnectionState}")
            if self.pc.iceConnectionState == "failed":
                await self.pc.close()

    def _emit_chat(self, sender: str, text: str) -> None:
        try:
            if self.on_chat:
                self.on_chat(sender, text)
        except Exception:
            pass

    def _emit_file_progress(self, file_name: str, transferred: int, total: int, direction: str) -> None:
        try:
            if self.on_file_progress:
                self.on_file_progress(file_name, transferred, total, direction)
        except Exception:
            pass

    def _emit_file_done(self, file_name: str, path: str, direction: str) -> None:
        try:
            if self.on_file_done:
                self.on_file_done(file_name, path, direction)
        except Exception:
            pass

    def _check_data_channels_ready(self) -> None:
        if self._channels_ready:
            return
        if self._chat_opened and self._file_opened:
            self._channels_ready = True
            self._emit("SESSION_CONNECTED")

    def _setup_chat_channel(self, channel):
        @channel.on("open")
        def _on_chat_open():
            self._chat_opened = True
            self._check_data_channels_ready()

        @channel.on("close")
        def _on_chat_close():
            self._chat_opened = False
            self._channels_ready = False
            self._emit("SESSION_CHANNELS_CLOSED")

        @channel.on("message")
        def on_message(message):
            try:
                payload = json.loads(message)
                if payload.get("type") == MessageType.CHAT_TEXT:
                    self._emit_chat("Client", payload.get("text", ""))
            except Exception as e:
                logger.error(f"Chat channel message error: {e}")

        # If channel is already open before handlers are attached, mark ready immediately.
        if channel.readyState == "open":
            self._chat_opened = True
            self._check_data_channels_ready()

    def _setup_file_channel(self, channel):
        @channel.on("open")
        def _on_file_open():
            self._file_opened = True
            self._check_data_channels_ready()

        @channel.on("close")
        def _on_file_close():
            self._file_opened = False
            self._channels_ready = False
            self._emit("SESSION_CHANNELS_CLOSED")

        @channel.on("message")
        def on_message(message):
            try:
                payload = json.loads(message)
                msg_type = payload.get("type")

                if msg_type == MessageType.FILE_OFFER:
                    file_id = payload["file_id"]
                    file_name = payload["file_name"]
                    file_size = int(payload["file_size"])
                    self._incoming_offers[file_id] = {"file_name": file_name, "file_size": file_size}
                    if self.on_file_offer:
                        # Non-blocking UI prompt flow; UI must call respond_file_offer().
                        self.on_file_offer(file_id, file_name, file_size)

                elif msg_type == MessageType.FILE_ACCEPT:
                    file_id = payload["file_id"]
                    self._outgoing_accepted[file_id] = bool(payload.get("accepted"))
                    event = self._pending_outgoing_accept.get(file_id)
                    if event and self.loop:
                        self.loop.call_soon_threadsafe(event.set)

                elif msg_type == MessageType.FILE_START:
                    file_id = payload["file_id"]
                    target_path = self._incoming_targets.get(file_id)
                    if not target_path:
                        return
                    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
                    fh = open(target_path, "wb")
                    self._incoming_files[file_id] = {
                        "fh": fh,
                        "name": payload["file_name"],
                        "size": int(payload["file_size"]),
                        "written": 0,
                        "path": target_path,
                    }

                elif msg_type == MessageType.FILE_CHUNK:
                    file_id = payload["file_id"]
                    file_state = self._incoming_files.get(file_id)
                    if not file_state:
                        return
                    chunk = base64.b64decode(payload["chunk_b64"])
                    file_state["fh"].write(chunk)
                    file_state["written"] += len(chunk)
                    self._emit_file_progress(file_state["name"], file_state["written"], file_state["size"], "recv")

                elif msg_type == MessageType.FILE_END:
                    file_id = payload["file_id"]
                    file_state = self._incoming_files.pop(file_id, None)
                    self._incoming_targets.pop(file_id, None)
                    self._incoming_offers.pop(file_id, None)
                    if not file_state:
                        return
                    file_state["fh"].close()
                    self._emit_file_done(file_state["name"], file_state["path"], "recv")
            except Exception as e:
                logger.error(f"File channel message error: {e}")

        # If channel is already open before handlers are attached, mark ready immediately.
        if channel.readyState == "open":
            self._file_opened = True
            self._check_data_channels_ready()

    def send_chat(self, text: str) -> None:
        if not text.strip() or not self.chat_channel or self.chat_channel.readyState != "open":
            return
        self.chat_channel.send(json.dumps({"type": MessageType.CHAT_TEXT, "text": text.strip(), "ts": int(time.time())}))
        self._emit_chat("You", text.strip())

    async def _send_file_task(self, file_path: str) -> None:
        if not self.file_channel or self.file_channel.readyState != "open":
            raise RuntimeError("File channel is not open")
        if not os.path.isfile(file_path):
            raise FileNotFoundError(file_path)

        file_id = uuid.uuid4().hex
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        chunk_size = 64 * 1024

        accept_event = asyncio.Event()
        self._pending_outgoing_accept[file_id] = accept_event
        self.file_channel.send(json.dumps({
            "type": MessageType.FILE_OFFER,
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
        }))
        await asyncio.wait_for(accept_event.wait(), timeout=120)
        self._pending_outgoing_accept.pop(file_id, None)
        if not self._outgoing_accepted.pop(file_id, False):
            self._emit("Remote rejected file transfer.")
            return

        self.file_channel.send(json.dumps({
            "type": MessageType.FILE_START,
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "chunk_size": chunk_size,
        }))

        sent = 0
        with open(file_path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                while self.file_channel.bufferedAmount > (4 * 1024 * 1024):
                    await asyncio.sleep(0.01)
                self.file_channel.send(json.dumps({
                    "type": MessageType.FILE_CHUNK,
                    "file_id": file_id,
                    "chunk_b64": base64.b64encode(chunk).decode("ascii"),
                }))
                sent += len(chunk)
                self._emit_file_progress(file_name, sent, file_size, "send")
                await asyncio.sleep(0)

        self.file_channel.send(json.dumps({"type": MessageType.FILE_END, "file_id": file_id}))
        self._emit_file_done(file_name, file_path, "send")

    def send_file(self, file_path: str) -> None:
        if not self.loop or self.loop.is_closed():
            raise RuntimeError("Host loop is not running")
        fut = asyncio.run_coroutine_threadsafe(self._send_file_task(file_path), self.loop)
        fut.result()

    def respond_file_offer(self, file_id: str, save_path: str | None) -> None:
        if not self.file_channel or self.file_channel.readyState != "open":
            return
        offer = self._incoming_offers.get(file_id)
        accepted = bool(save_path)
        if accepted and offer:
            self._incoming_targets[file_id] = save_path
        self.file_channel.send(json.dumps({
            "type": MessageType.FILE_ACCEPT,
            "file_id": file_id,
            "accepted": accepted,
        }))
        if not accepted:
            self._incoming_offers.pop(file_id, None)

    async def _cursor_tracking_loop(self, channel):
        """Periodically check the host's move cursor shape and sync it to the client."""
        sys_platform = platform.system()
        
        try:
            while channel.readyState == "open":
                cname = None
                
                if sys_platform == "Windows" and ctypes:
                    info = CURSORINFO()
                    info.cbSize = ctypes.sizeof(CURSORINFO)
                    if ctypes.windll.user32.GetCursorInfo(ctypes.byref(info)):
                        cname = self._cursor_handles.get(info.hCursor, "arrow")
                
                elif sys_platform == "Darwin" and self._ns_cursor:
                    try:
                        curr = self._ns_cursor.currentSystemCursor()
                        # Map native Mac cursor objects to names
                        for method_name, standardized_name in MAC_CURSOR_MAP.items():
                            if hasattr(self._ns_cursor, method_name):
                                if curr == getattr(self._ns_cursor, method_name)():
                                    cname = standardized_name
                                    break
                    except Exception:
                        pass
                
                if cname and cname != self._last_cursor_name:
                    self._last_cursor_name = cname
                    msg = ControlMessage(type=MessageType.CURSOR_UPDATE, cursor_name=cname)
                    channel.send(msg.to_json())
                    
                await asyncio.sleep(0.1)
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

    async def _process_commands(self):
        """Poll the incoming command queue from the UI process."""
        if not self.command_queue:
            return
        
        while True:
            try:
                # Use a thread-safe way to check the queue in an async loop
                if hasattr(self.command_queue, "empty") and self.command_queue.empty():
                    await asyncio.sleep(0.1)
                    continue
                
                # Get command without blocking the whole loop
                cmd = await asyncio.get_event_loop().run_in_executor(None, self.command_queue.get)
                if not cmd:
                    continue
                
                kind = cmd.get("type")
                if kind == "send_chat":
                    self.send_chat(cmd["text"])
                elif kind == "send_file":
                    # Run file task concurrently
                    asyncio.create_task(self._send_file_task(cmd["path"]))
                elif kind == "respond_file_offer":
                    self.respond_file_offer(cmd["file_id"], cmd["save_path"])
                elif kind == "shutdown":
                    break
                    
            except Exception as e:
                logger.error(f"Error in command processing: {e}")
                await asyncio.sleep(0.1)

    async def run(self):
        self._command_task = asyncio.create_task(self._process_commands())
        try:
            await self.connect_signaling()
            # Keep running until the command task (or signaling) ends
            if self._command_task:
                await self._command_task
        except asyncio.CancelledError:
            pass
        finally:
            if self._command_task:
                self._command_task.cancel()
            if self.pc:
                await self.pc.close()
            if self.ws:
                await self.ws.close()
