import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import setup_logging
from client.webrtc_client import WebRTCClient

async def main():
    setup_logging()
    
    if len(sys.argv) > 1:
        target_host = sys.argv[1]
    else:
        target_host = input("Enter target host ID to connect: ").strip()
        
    print(f"Connecting to host {target_host}...")
    
    client = WebRTCClient(target_host)
    await client.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Client terminated by user")
