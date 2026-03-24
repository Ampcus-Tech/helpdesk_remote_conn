import asyncio
import random
import string
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import setup_logging
from host.webrtc_host import WebRTCHost

def generate_host_id(length=6):
    return ''.join(random.choices(string.digits, k=length))

async def main():
    setup_logging()
    host_id = generate_host_id()
    print("=========================================")
    print(f"Host ID to connect: {host_id}")
    print("=========================================")
    
    host = WebRTCHost(host_id)
    await host.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Host terminated by user")
