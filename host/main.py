import asyncio
import hashlib
import json
import platform
import secrets
import socket
import sys
import os
import signal
import uuid
from multiprocessing import Queue

# Ensure repo root is importable regardless of launcher working directory.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# For bundled app, add the executable directory to path
if getattr(sys, 'frozen', False):
    # Running in a bundle
    bundle_dir = os.path.dirname(sys.executable)
    sys.path.insert(0, bundle_dir)

from common.config import setup_logging
from host.webrtc_host import WebRTCHost

PBKDF2_ITERATIONS = 200_000

def _hardware_fingerprint() -> str:
    mac_addr = hex(uuid.getnode())
    cpu = platform.processor() or "unknown-cpu"
    hostname = socket.gethostname() or "unknown-host"
    return f"{mac_addr}|{cpu}|{hostname}"

def generate_hidden_host_id() -> str:
    return hashlib.sha256(_hardware_fingerprint().encode("utf-8")).hexdigest()

def derive_public_connection_id(hidden_host_id: str, length: int = 8) -> str:
    digest = hashlib.sha256(f"public::{hidden_host_id}".encode("utf-8")).hexdigest()
    digits_only = "".join(str(int(ch, 16) % 10) for ch in digest)
    return digits_only[:length]

def generate_session_password() -> str:
    # Cryptographically secure 6-digit one-time session password.
    return f"{secrets.randbelow(1_000_000):06d}"

def hash_password(password: str):
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return password_hash.hex(), salt.hex()

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
    hidden_host_id = generate_hidden_host_id()
    connection_id = derive_public_connection_id(hidden_host_id)
    session_password = generate_session_password()
    password_hash, password_salt = hash_password(session_password)
    print("=========================================")
    print(f"Connection ID to connect: {connection_id}")
    print(f"Password: {session_password}")
    print(f"UI_SIGNAL:HOST_ID:{connection_id}", flush=True)
    print(f"UI_SIGNAL:SESSION_PASSWORD:{session_password}", flush=True)
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
        hidden_host_id,
        connection_id=connection_id,
        password_hash=password_hash,
        password_salt=password_salt,
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
