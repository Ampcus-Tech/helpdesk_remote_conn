import asyncio
import json
import logging
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
import websockets

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.messages import SignalingMessage, MessageType, ControlMessage
from common.config import SIGNALING_URL, ICE_SERVERS, CTRL_CHANNEL_NAME
from host.screen_capture import ScreenCaptureTrack
from host.input_receiver import InputReceiver

logger = logging.getLogger("webrtc_host")

class WebRTCHost:
    def __init__(self, host_id):
        self.host_id = host_id
        self.pc = None
        self.ws = None
        self.input_receiver = InputReceiver()

    async def create_pc(self):
        # Convert dict configs to RTCIceServer objects
        ice_servers = [RTCIceServer(**server) for server in ICE_SERVERS]
        config = RTCConfiguration(iceServers=ice_servers)
        self.pc = RTCPeerConnection(configuration=config)

        # Add video track
        video_track = ScreenCaptureTrack()
        self.pc.addTrack(video_track)

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            logger.info(f"Data channel {channel.label} received")
            if channel.label == CTRL_CHANNEL_NAME:
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
                        elif msg.type == MessageType.KEYBOARD:
                            self.input_receiver.handle_keyboard(msg)
                    except Exception as e:
                        logger.error(f"Error processing control message: {e}")

        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info(f"ICE connection state is {self.pc.iceConnectionState}")
            if self.pc.iceConnectionState == "failed":
                await self.pc.close()

    async def connect_signaling(self):
        logger.info(f"Connecting to signaling server at {SIGNALING_URL}")
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
                
            elif msg_type == MessageType.SDP:
                logger.info("Received SDP offer")
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
