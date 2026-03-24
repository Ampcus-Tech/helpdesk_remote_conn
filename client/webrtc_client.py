import asyncio
import json
import logging
import cv2
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
import websockets

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.messages import SignalingMessage, MessageType
from common.config import SIGNALING_URL, ICE_SERVERS, CTRL_CHANNEL_NAME
from client.display import Display
from client.input_sender import InputSender

logger = logging.getLogger("webrtc_client")

class WebRTCClient:
    def __init__(self, target_host_id):
        self.target_host_id = target_host_id
        self.pc = None
        self.ws = None
        self.channel = None
        
        self.display = Display()
        self.input_sender = None
        self.connected_event = asyncio.Event()

    async def create_pc(self):
        # Convert dict configs to RTCIceServer objects
        ice_servers = [RTCIceServer(**server) for server in ICE_SERVERS]
        config = RTCConfiguration(iceServers=ice_servers)
        self.pc = RTCPeerConnection(configuration=config)
        
        self.channel = self.pc.createDataChannel(CTRL_CHANNEL_NAME)
        self.pc.addTransceiver("video", direction="recvonly")
        self.input_sender = InputSender(self.display.window_name, self.channel)

        @self.pc.on("track")
        def on_track(track):
            logger.info(f"Received {track.kind} track")
            if track.kind == "video":
                asyncio.ensure_future(self.consume_video(track))

        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info(f"ICE connection state is {self.pc.iceConnectionState}")
            if self.pc.iceConnectionState == "failed":
                await self.pc.close()

    async def consume_video(self, track):
        while True:
            try:
                frame = await track.recv()
                img = frame.to_ndarray(format="bgr24")
                
                height, width = img.shape[:2]
                self.input_sender.update_screen_size(width, height)
                
                self.display.show_frame(img)
                key = cv2.waitKey(1)
                self.input_sender.handle_keyboard(key)
                
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
                    self.connected_event.set()
                    break
                    
                elif msg_type == MessageType.SDP:
                    logger.info("Received SDP answer")
                    sdp = data.get("sdp")
                    answer = RTCSessionDescription(sdp=sdp["sdp"], type=sdp["type"])
                    await self.pc.setRemoteDescription(answer)
        except asyncio.TimeoutError:
            logger.error("Signaling error: Timed out during opening handshake.")
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
            self.connected_event.set()
            
    async def run(self):
        try:
            await self.start()
        finally:
            if self.pc:
                await self.pc.close()
            if self.ws:
                await self.ws.close()
            self.display.close()
