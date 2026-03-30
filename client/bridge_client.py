import asyncio
import base64
import json
import logging
import sys
import os
import cv2

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import setup_logging
from client.webrtc_client import WebRTCClient

def emit(message):
    print(f"EVENT:{message}", flush=True)

class BridgeClient(WebRTCClient):
    def __init__(self, target_host_id, on_event=None):
        super().__init__(target_host_id, on_event=on_event)
        # Disable legacy OpenCV components
        self.display = None 

    async def create_pc(self):
        # Optimized version of create_pc for Electron (no InputSender/Display)
        # Convert dict configs to RTCIceServer objects
        from aiortc import RTCConfiguration, RTCIceServer
        from common.config import ICE_SERVERS, CTRL_CHANNEL_NAME, VIDEO_CODEC
        from aiortc import RTCRtpSender

        ice_servers = [RTCIceServer(**server) for server in ICE_SERVERS]
        config = RTCConfiguration(iceServers=ice_servers)
        self.pc = RTCPeerConnection(configuration=config)
        
        self.channel = self.pc.createDataChannel(CTRL_CHANNEL_NAME)
        video_transceiver = self.pc.addTransceiver("video", direction="recvonly")

        caps = RTCRtpSender.getCapabilities("video").codecs
        if VIDEO_CODEC == "h264":
            main_mime = "video/H264"
        else:
            main_mime = "video/VP8"

        preferred = [c for c in caps if c.mimeType == main_mime]
        preferred.extend([c for c in caps if c.mimeType == "video/rtx"])
        video_transceiver.setCodecPreferences(preferred)

        @self.pc.on("track")
        def on_track(track):
            if track.kind == "video":
                asyncio.ensure_future(self.consume_video(track))

        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            if self.pc.iceConnectionState == "failed":
                await self.pc.close()

    async def start(self):
        await self.create_pc()
        
        # Set up data channel listener for cursor updates
        @self.channel.on("message")
        def on_message(message):
            try:
                data = json.loads(message)
                if data.get("type") == "cursor_update":
                    cursor_name = data.get("cursor_name")
                    if cursor_name:
                        emit(f"CURSOR:{cursor_name}")
            except Exception:
                pass

        # Continue with base start logic
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        local = self.pc.localDescription
        asyncio.create_task(self._signaling_loop(local))
        await self.connected_event.wait()

    async def consume_video(self, track):
        while True:
            try:
                frame = await track.recv()
                img = frame.to_ndarray(format="bgr24")
                
                # Update screen size for input sender
                height, width = img.shape[:2]
                if self.input_sender:
                    self.input_sender.update_screen_size(width, height)
                
                # Encode frame to JPEG
                _, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                jpg_as_text = base64.b64encode(buffer).decode('utf-8')
                
                # Send frame to Electron
                print(f"FRAME:{jpg_as_text}", flush=True)
                
                if not self._video_started:
                    self._video_started = True
                    self._emit("Connected. Viewing remote screen.")
                    
            except Exception as e:
                emit(f"ERROR: Video track error: {e}")
                break

async def handle_stdin(client):
    """Read input events from Electron via stdin."""
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        try:
            if line.startswith("CONTROL:"):
                # Forward control message to data channel
                if client.channel and client.channel.readyState == "open":
                    client.channel.send(line[8:].strip())
        except Exception as e:
            emit(f"ERROR: Stdin handler error: {e}")

async def main():
    if len(sys.argv) < 2:
        print("ERROR: Target Host ID required", flush=True)
        return

    target_host_id = sys.argv[1]
    setup_logging(level=logging.WARNING) # Reduce noise
    
    client = BridgeClient(target_host_id, on_event=emit)
    
    # Run signaling and input handler together
    try:
        await asyncio.gather(
            client.run(),
            handle_stdin(client)
        )
    except Exception as e:
        emit(f"ERROR: {str(e)}")
    finally:
        emit("__DONE__")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
