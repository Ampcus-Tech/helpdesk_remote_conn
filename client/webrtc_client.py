import asyncio
import base64
import json
import logging
import os
import time
import uuid
import cv2
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc import RTCRtpSender
import websockets

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.messages import SignalingMessage, MessageType
from common.config import (
    SIGNALING_URL,
    ICE_SERVERS,
    CTRL_CHANNEL_NAME,
    CHAT_CHANNEL_NAME,
    FILE_CHANNEL_NAME,
    VIDEO_CODEC,
)
from client.display import Display
from client.input_sender import InputSender

logger = logging.getLogger("webrtc_client")

class WebRTCClient:
    def __init__(
        self,
        target_host_id,
        on_event=None,
        on_chat=None,
        on_file_offer=None,
        on_file_progress=None,
        on_file_done=None,
    ):
        self.target_host_id = target_host_id
        self.pc = None
        self.ws = None
        self.channel = None
        self.chat_channel = None
        self.file_channel = None
        self.loop = None
        
        self.display = Display()
        self.input_sender = None
        self.connected_event = asyncio.Event()
        self.on_event = on_event
        self.on_chat = on_chat
        self.on_file_offer = on_file_offer
        self.on_file_progress = on_file_progress
        self.on_file_done = on_file_done
        self._video_started = False
        self._pending_outgoing_accept: dict[str, asyncio.Event] = {}
        self._outgoing_accepted: dict[str, bool] = {}
        self._incoming_targets: dict[str, str] = {}
        self._incoming_files: dict[str, object] = {}
        self._incoming_offers: dict[str, dict] = {}
        self._chat_opened = False
        self._file_opened = False
        self._channels_ready = False

    def _emit(self, message: str) -> None:
        """Send lightweight status updates to the UI (if provided)."""
        try:
            if self.on_event:
                self.on_event(message)
        except Exception:
            # UI callbacks must never break the media pipeline.
            pass

    async def create_pc(self):
        self.loop = asyncio.get_running_loop()
        # Convert dict configs to RTCIceServer objects
        ice_servers = [RTCIceServer(**server) for server in ICE_SERVERS]
        config = RTCConfiguration(iceServers=ice_servers)
        self.pc = RTCPeerConnection(configuration=config)
        
        self.channel = self.pc.createDataChannel(CTRL_CHANNEL_NAME)
        self.chat_channel = self.pc.createDataChannel(CHAT_CHANNEL_NAME)
        self.file_channel = self.pc.createDataChannel(FILE_CHANNEL_NAME)
        video_transceiver = self.pc.addTransceiver("video", direction="recvonly")

        # Prefer a specific codec for negotiation/decoding (helps quality).
        caps = RTCRtpSender.getCapabilities("video").codecs
        if VIDEO_CODEC == "h264":
            main_mime = "video/H264"
        else:
            main_mime = "video/VP8"

        preferred = [c for c in caps if c.mimeType == main_mime]
        preferred.extend([c for c in caps if c.mimeType == "video/rtx"])
        video_transceiver.setCodecPreferences(preferred)
        loop = asyncio.get_running_loop()
        self.input_sender = InputSender(self.display.window_name, self.channel, loop)
        self._setup_chat_channel()
        self._setup_file_channel()

        # Enable chat/files UI only after both DataChannels are open.
        @self.chat_channel.on("open")
        def _on_chat_open():
            self._chat_opened = True
            self._check_data_channels_ready()

        @self.chat_channel.on("close")
        def _on_chat_close():
            self._chat_opened = False
            self._channels_ready = False
            self._emit("SESSION_CHANNELS_CLOSED")

        @self.file_channel.on("open")
        def _on_file_open():
            self._file_opened = True
            self._check_data_channels_ready()

        @self.file_channel.on("close")
        def _on_file_close():
            self._file_opened = False
            self._channels_ready = False
            self._emit("SESSION_CHANNELS_CLOSED")

        @self.pc.on("track")
        def on_track(track):
            logger.info(f"Received {track.kind} track")
            if track.kind == "video":
                self._emit("Video track received...")
                asyncio.ensure_future(self.consume_video(track))

        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info(f"ICE connection state is {self.pc.iceConnectionState}")
            if self.pc.iceConnectionState == "failed":
                await self.pc.close()

    def _check_data_channels_ready(self) -> None:
        if self._channels_ready:
            return
        if self._chat_opened and self._file_opened:
            self._channels_ready = True
            self._emit("SESSION_CONNECTED")

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

    def _setup_chat_channel(self) -> None:
        @self.chat_channel.on("message")
        def on_message(message):
            try:
                payload = json.loads(message)
                if payload.get("type") == MessageType.CHAT_TEXT:
                    text = payload.get("text", "")
                    self._emit_chat("Host", text)
            except Exception as e:
                logger.error(f"Chat channel message error: {e}")

        # Handle race: channel might already be open.
        if self.chat_channel.readyState == "open":
            self._chat_opened = True
            self._check_data_channels_ready()

    def _setup_file_channel(self) -> None:
        @self.file_channel.on("message")
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
                    accepted = bool(payload.get("accepted"))
                    self._outgoing_accepted[file_id] = accepted
                    event = self._pending_outgoing_accept.get(file_id)
                    if event and self.loop:
                        self.loop.call_soon_threadsafe(event.set)

                elif msg_type == MessageType.FILE_START:
                    file_id = payload["file_id"]
                    file_name = payload["file_name"]
                    file_size = int(payload["file_size"])
                    target_path = self._incoming_targets.get(file_id)
                    if not target_path:
                        return
                    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
                    fh = open(target_path, "wb")
                    self._incoming_files[file_id] = {
                        "fh": fh,
                        "name": file_name,
                        "size": file_size,
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

        # Handle race: channel might already be open.
        if self.file_channel.readyState == "open":
            self._file_opened = True
            self._check_data_channels_ready()

    def send_chat(self, text: str) -> None:
        if not text.strip() or not self.chat_channel:
            return
        payload = {"type": MessageType.CHAT_TEXT, "text": text.strip(), "ts": int(time.time())}
        if self.chat_channel.readyState == "open":
            self.chat_channel.send(json.dumps(payload))
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
            raise RuntimeError("Client loop is not running")
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

    async def consume_video(self, track):
        while True:
            try:
                frame = await track.recv()
                img = frame.to_ndarray(format="bgr24")
                
                height, width = img.shape[:2]
                self.input_sender.update_screen_size(width, height)
                
                self.display.show_frame(img)
                if not self._video_started:
                    self._video_started = True
                    self._emit("Connected. You are now viewing the remote screen.")
                # Pump OpenCV GUI events so the window repaints.
                cv2.waitKey(1)
                
            except Exception as e:
                logger.error(f"Video track error: {e}")
                break

    async def start(self):
        await self.create_pc()
        
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        # setLocalDescription runs ICE gather and embeds candidates; createOffer() SDP alone is incomplete.
        local = self.pc.localDescription
        if local is None:
            raise RuntimeError("Missing localDescription after setLocalDescription")
        
        asyncio.create_task(self._signaling_loop(local))
        
        await self.connected_event.wait()

    async def _signaling_loop(self, local_desc: RTCSessionDescription):
        try:
            self._emit("Connecting to signaling server...")
            self.ws = await websockets.connect(SIGNALING_URL)
            find_msg = SignalingMessage(type=MessageType.FIND_HOST, host_id=self.target_host_id)
            await self.ws.send(find_msg.to_json())
            
            offer_msg = SignalingMessage(
                type=MessageType.SDP,
                sdp={"sdp": local_desc.sdp, "type": local_desc.type}
            )
            await self.ws.send(offer_msg.to_json())
            
            async for message in self.ws:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == MessageType.HOST_NOT_FOUND:
                    logger.error(f"Host {self.target_host_id} not found!")
                    self._emit("Host ID not found. Check Host ID and try again.")
                    self.connected_event.set()
                    break
                    
                elif msg_type == MessageType.SDP:
                    logger.info("Received SDP answer")
                    self._emit("SDP answer received. Waiting for video...")
                    sdp = data.get("sdp")
                    answer = RTCSessionDescription(sdp=sdp["sdp"], type=sdp["type"])
                    await self.pc.setRemoteDescription(answer)
        except asyncio.TimeoutError:
            logger.error("Signaling error: Timed out during opening handshake.")
            self._emit("Signaling timeout. Start signaling server first.")
            print("\n" + "!"*60)
            print("DIAGNOSTIC: Handshake Timeout Detected!")
            print(f"Target URL: {SIGNALING_URL}")
            if "172." in SIGNALING_URL or "192.168." in SIGNALING_URL or "10." in SIGNALING_URL:
                print("REASON: You are trying to use a PRIVATE IP address across different networks.")
                print("FIX: Both PCs must be on the same Wi-Fi, OR you must use Tailscale/Ngrok.")
            else:
                print("REASON: The Signaling Server is not running or port 8080 is blocked by a firewall.")
            print("!"*60 + "\n")
            self.connected_event.set()
        except Exception as e:
            logger.error(f"Signaling error: {e}")
            self._emit(f"Signaling error: {e}")
            self.connected_event.set()
            
    async def run(self):
        try:
            await self.start()
        finally:
            if self.input_sender:
                self.input_sender.close()
            if self.pc:
                await self.pc.close()
            if self.ws:
                await self.ws.close()
            self.display.close()
