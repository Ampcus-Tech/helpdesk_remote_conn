import asyncio
import json
import random
import string
import sys
import os
import signal
from multiprocessing import Queue

# For bundled app, add the executable directory to path
if getattr(sys, 'frozen', False):
    # Running in a bundle
    bundle_dir = os.path.dirname(sys.executable)
    sys.path.insert(0, bundle_dir)

from common.config import setup_logging
from host.webrtc_host import WebRTCHost

def generate_host_id(length=6):
    return ''.join(random.choices(string.digits, k=length))

async def read_commands(host: WebRTCHost):
    """Read commands from stdin and put them into the host's command_queue."""
    if not host.command_queue:
        host.command_queue = Queue()
        
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            cmd = json.loads(line)
            host.command_queue.put(cmd)
        except Exception as e:
            # If stdin is closed, we should probably exit
            if not line: break
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

    # Handle termination signals
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(host.stop()))
        except NotImplementedError:
            # add_signal_handler is not implemented on Windows
            pass

    # Run the command listener and the host concurrently
    try:
        await asyncio.gather(
            host.run(),
            read_commands(host)
        )
    except asyncio.CancelledError:
        print("Host tasks cancelled", flush=True)
    finally:
        await host.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Host terminated by user", flush=True)
    except SystemExit:
        pass
