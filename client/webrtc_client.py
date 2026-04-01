import asyncio
import json
import logging
import traceback
import cv2
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc import RTCRtpSender
import websockets

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.messages import SignalingMessage, MessageType
from common.config import SIGNALING_URL, ICE_SERVERS, CTRL_CHANNEL_NAME, VIDEO_CODEC
from client.display import Display
from client.input_sender import InputSender

logger = logging.getLogger("webrtc_client")


def _client_print(msg: str) -> None:
    """Always visible in terminal (setup_logging may only configure file handlers)."""
    print(f"[webrtc_client] {msg}", file=sys.stderr, flush=True)

class WebRTCClient:
    def __init__(self, target_host_id, on_event=None):
        self.target_host_id = target_host_id
        self.pc = None
        self.ws = None
        self.channel = None
        
        self.display = Display()
        self.input_sender = None
        self.connected_event = asyncio.Event()
        self.on_event = on_event
        self._video_started = False
        self._handshake_ok = False

    def _emit(self, message: str) -> None:
        """Send lightweight status updates to the UI (if provided)."""
        try:
            if self.on_event:
                self.on_event(message)
        except Exception:
            # UI callbacks must never break the media pipeline.
            pass

    async def create_pc(self):
        # Convert dict configs to RTCIceServer objects
        ice_servers = [RTCIceServer(**server) for server in ICE_SERVERS]
        config = RTCConfiguration(iceServers=ice_servers)
        self.pc = RTCPeerConnection(configuration=config)
        
        self.channel = self.pc.createDataChannel(CTRL_CHANNEL_NAME)
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

        @self.pc.on("track")
        def on_track(track):
            logger.info(f"Received {track.kind} track")
            if track.kind == "video":
                self._emit("Video track received...")
                asyncio.ensure_future(self.consume_video(track))

        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            state = self.pc.iceConnectionState
            logger.info("ICE connection state is %s", state)
            _client_print(f"ICE state: {state}")
            if state == "failed":
                _client_print(
                    "ICE failed — NAT/firewall or TURN/STUN mismatch. "
                    "Check ICE_SERVERS / TURN credentials and that host is reachable."
                )
                await self.pc.close()

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
                logger.error("Video track error: %s", e)
                _client_print(f"Video track ended: {type(e).__name__}: {e}")
                self._emit(f"Video stopped: {e}")
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
        self._handshake_ok = False
        try:
            self._emit("Connecting to signaling server...")
            _client_print(f"Signaling URL: {SIGNALING_URL!r}")
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
                    reason = (
                        f"Host ID {self.target_host_id!r} not registered on signaling server. "
                        "Start the host app with the same ID and ensure signaling/server.py is running."
                    )
                    logger.error(reason)
                    _client_print(reason)
                    self._emit(reason)
                    self.connected_event.set()
                    break

                elif msg_type == MessageType.SDP:
                    logger.info("Received SDP answer from host")
                    self._emit("SDP answer received. Setting up WebRTC…")
                    sdp = data.get("sdp")
                    if not sdp:
                        raise RuntimeError("SDP answer missing sdp payload")
                    answer = RTCSessionDescription(sdp=sdp["sdp"], type=sdp["type"])
                    await self.pc.setRemoteDescription(answer)
                    self._handshake_ok = True
                    _client_print("SDP exchange complete; waiting for ICE + media.")
                    self.connected_event.set()

            if not self._handshake_ok and not self.connected_event.is_set():
                reason = (
                    "Signaling websocket closed before an answer was received "
                    "(server restarted, ngrok session ended, or host disconnected)."
                )
                logger.error(reason)
                _client_print(reason)
                self._emit(reason)

        except asyncio.TimeoutError:
            logger.error("Signaling error: Timed out during opening handshake.")
            self._emit("Signaling timeout. Start signaling server first.")
            print("\n" + "!" * 60)
            print("DIAGNOSTIC: Handshake Timeout Detected!")
            print(f"Target URL: {SIGNALING_URL}")
            if "172." in SIGNALING_URL or "192.168." in SIGNALING_URL or "10." in SIGNALING_URL:
                print("REASON: You are trying to use a PRIVATE IP address across different networks.")
                print("FIX: Both PCs must be on the same Wi-Fi, OR you must use Tailscale/Ngrok.")
            else:
                print("REASON: The Signaling Server is not running or port 8080 is blocked by a firewall.")
            print("!" * 60 + "\n")
        except websockets.exceptions.ConnectionClosed as e:
            msg = (
                f"Signaling WebSocket closed: {e.reason or e} (code {e.code}). "
                "Often: wrong wss URL, ngrok limit, or host dropped off signaling."
            )
            logger.error(msg)
            _client_print(msg)
            self._emit(msg)
        except Exception as e:
            logger.error("Signaling error: %s", e)
            traceback.print_exc()
            _client_print(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            self._emit(f"Signaling error: {type(e).__name__}: {e}")
        finally:
            if not self.connected_event.is_set():
                self.connected_event.set()

    async def run(self):
        try:
            await self.start()
            if not self._handshake_ok:
                _client_print("Stopping: WebRTC handshake did not succeed.")
                return

            _client_print("Handshake OK — holding session until ICE closes or fails.")
            while self.pc and self.pc.iceConnectionState not in ("failed", "closed"):
                await asyncio.sleep(0.25)

            final = self.pc.iceConnectionState if self.pc else "gone"
            summary = f"Session ended (ICE: {final})."
            logger.info(summary)
            _client_print(summary)
            self._emit(summary)

        except Exception as e:
            logger.exception("Client run failed")
            traceback.print_exc()
            _client_print(f"Fatal: {type(e).__name__}: {e}")
            self._emit(f"ERROR: {type(e).__name__}: {e}")
        finally:
            if self.input_sender:
                self.input_sender.close()
            if self.pc:
                try:
                    await self.pc.close()
                except Exception as e:
                    logger.debug("pc.close: %s", e)
            if self.ws:
                try:
                    await self.ws.close()
                except Exception as e:
                    logger.debug("ws.close: %s", e)
            self.display.close()
