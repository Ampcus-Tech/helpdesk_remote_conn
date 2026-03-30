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
