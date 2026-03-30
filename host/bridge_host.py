import asyncio
import json
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import setup_logging
from host.webrtc_host import WebRTCHost

def emit(message):
    print(f"EVENT:{message}", flush=True)

async def main():
    if len(sys.argv) < 2:
        print("ERROR: Host ID required", flush=True)
        return

    host_id = sys.argv[1]
    setup_logging()
    
    emit(f"Starting host with ID: {host_id}")
    
    host = WebRTCHost(host_id, on_event=emit)
    try:
        await host.run()
    except Exception as e:
        emit(f"ERROR: {str(e)}")
    finally:
        emit("__DONE__")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
