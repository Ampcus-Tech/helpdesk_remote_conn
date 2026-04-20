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

async def read_commands(host: WebRTCHost):
    """Read commands from stdin and put them into the host's command_queue."""
    if not host.command_queue:
        from multiprocessing import Queue
        host.command_queue = Queue()
        
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        try:
            cmd = json.loads(line)
            host.command_queue.put(cmd)
        except Exception as e:
            print(f"Error parsing command: {e}", file=sys.stderr)

async def main():
    setup_logging()
    host_id = generate_host_id()
    print("=========================================")
    print(f"Host ID to connect: {host_id}")
    # UI SIGNAL for Tauri/React to capture
    print(f"UI_SIGNAL:HOST_ID:{host_id}", flush=True)
    print("=========================================")
    
    def on_event(msg):
        print(f"UI_SIGNAL:STATUS:{msg}", flush=True)

    def on_chat(sender, text):
        json_data = json.dumps({"sender": sender, "text": text})
        print(f"UI_SIGNAL:CHAT_RECEIVED:{json_data}", flush=True)

    def on_file_offer(file_id, name, size):
        json_data = json.dumps({"file_id": file_id, "name": name, "size": size})
        print(f"UI_SIGNAL:FILE_OFFER:{json_data}", flush=True)

    def on_file_progress(name, progress, total, direction):
        json_data = json.dumps({"name": name, "progress": progress, "total": total, "direction": direction})
        print(f"UI_SIGNAL:FILE_PROGRESS:{json_data}", flush=True)

    def on_file_done(name, path, direction):
        json_data = json.dumps({"name": name, "path": path, "direction": direction})
        print(f"UI_SIGNAL:FILE_DONE:{json_data}", flush=True)

    host = WebRTCHost(
        host_id, 
        on_event=on_event,
        on_chat=on_chat,
        on_file_offer=on_file_offer,
        on_file_progress=on_file_progress,
        on_file_done=on_file_done
    )
    
    # Run the command listener and the host concurrently
    await asyncio.gather(
        host.run(),
        read_commands(host)
    )

if __name__ == "__main__":
    import json
    from multiprocessing import Queue
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Host terminated by user")
