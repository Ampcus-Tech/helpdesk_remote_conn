import asyncio
import hashlib
import hmac
import json
import logging
import time
import websockets
from websockets import exceptions as ws_exceptions
from websockets.server import WebSocketServerProtocol
import sys
import os

# Add parent directory to path to import common
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import SIGNALING_HOST, SIGNALING_PORT, setup_logging
from common.messages import SignalingMessage, MessageType

logger = logging.getLogger("signaling")

# Maintain registered hosts by internal host id: { host_id: websocket }
hosts = {}
# Public lookup: { connection_id: internal_host_id }
connection_to_host = {}
# Per-host auth material keyed by internal host id.
host_auth = {}
# Maintain a dictionary mapping clients to their connected internal host_id
# so we can route client messages back to the correct host.
clients_to_hosts = {}
# Failed auth tracking per public connection ID.
auth_failures = {}

AUTH_WINDOW_SECONDS = 300
AUTH_LOCK_SECONDS = 300
AUTH_MAX_ATTEMPTS = 5
PBKDF2_ITERATIONS = 200_000

def _pbkdf2_hash(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex()

def _verify_password(password: str, expected_hash_hex: str, salt_hex: str) -> bool:
    computed = _pbkdf2_hash(password, salt_hex)
    return hmac.compare_digest(computed, expected_hash_hex)

def _check_rate_limit(connection_id: str):
    now = time.time()
    bucket = auth_failures.get(connection_id)
    if not bucket:
        return False, 0
    if bucket.get("locked_until", 0) > now:
        wait_for = int(bucket["locked_until"] - now)
        return True, wait_for
    return False, 0

def _record_failed_auth(connection_id: str):
    now = time.time()
    bucket = auth_failures.get(connection_id)
    if not bucket or now - bucket.get("window_start", 0) > AUTH_WINDOW_SECONDS:
        bucket = {"window_start": now, "count": 0, "locked_until": 0}
    bucket["count"] += 1
    if bucket["count"] >= AUTH_MAX_ATTEMPTS:
        bucket["locked_until"] = now + AUTH_LOCK_SECONDS
        bucket["count"] = 0
        bucket["window_start"] = now
    auth_failures[connection_id] = bucket

def _reset_failed_auth(connection_id: str):
    auth_failures.pop(connection_id, None)

async def register_host(
    websocket: WebSocketServerProtocol,
    host_id: str,
    connection_id: str,
    password_hash: str,
    password_salt: str,
):
    logger.info(f"Registering host {host_id} with public connection ID {connection_id}")
    hosts[host_id] = websocket
    connection_to_host[connection_id] = host_id
    host_auth[host_id] = {
        "connection_id": connection_id,
        "password_hash": password_hash,
        "password_salt": password_salt,
    }
    response = SignalingMessage(type=MessageType.HOST_REGISTERED, connection_id=connection_id)
    await websocket.send(response.to_json())

async def find_host(websocket: WebSocketServerProtocol, connection_id: str, password: str):
    logger.info(f"Client searching for public connection ID {connection_id}")
    if not connection_id or not password:
        response = SignalingMessage(type=MessageType.AUTH_FAILED)
        await websocket.send(response.to_json())
        return

    is_limited, wait_for = _check_rate_limit(connection_id)
    if is_limited:
        logger.warning(f"Auth blocked for {connection_id}: rate limited")
        response = SignalingMessage(type=MessageType.AUTH_RATE_LIMITED, retry_after_seconds=wait_for)
        await websocket.send(response.to_json())
        return

    internal_host_id = connection_to_host.get(connection_id)
    if internal_host_id and internal_host_id in hosts:
        auth = host_auth.get(internal_host_id)
        if not auth:
            response = SignalingMessage(type=MessageType.HOST_NOT_FOUND, connection_id=connection_id)
            await websocket.send(response.to_json())
            return

        if _verify_password(password, auth["password_hash"], auth["password_salt"]):
            clients_to_hosts[websocket] = internal_host_id
            _reset_failed_auth(connection_id)
            return

        logger.warning(f"Invalid password for connection ID {connection_id}")
        _record_failed_auth(connection_id)
        response = SignalingMessage(type=MessageType.AUTH_FAILED)
        await websocket.send(response.to_json())
        # Let host know a client wants to connect via an offer they will send
        # In WebRTC, typically the caller (Client in this case) sends the first SDP offer
        # We don't necessarily send a message yet, just route future messages.
    else:
        logger.warning(f"Host with connection ID {connection_id} not found")
        response = SignalingMessage(type=MessageType.HOST_NOT_FOUND, connection_id=connection_id)
        await websocket.send(response.to_json())

async def relay_message_to_host(websocket: WebSocketServerProtocol, msg: json):
    # This message is coming from a client, meant for a host
    if websocket in clients_to_hosts:
        host_id = clients_to_hosts[websocket]
        if host_id in hosts:
            host_ws = hosts[host_id]
            # Add relay context
            await host_ws.send(json.dumps(msg))
        else:
            logger.warning(f"Associated host {host_id} is no longer connected.")
    else:
        logger.warning("Message from unregistered client. Drop.")

async def relay_message_to_client(websocket: WebSocketServerProtocol, msg: json, target_client: str = None):
    # This message is from a host, meant for a client
    # In a full app, we need to track WHICH client this goes to.
    # For now, we broadcast to all clients connected to this host, 
    # or improve client tracking. A minimal approach:
    # the signaling server needs a concept of client_id or sender.
    pass # To be handled efficiently in handle_connection

async def handle_connection(websocket: WebSocketServerProtocol):
    logger.info(f"New connection from {websocket.remote_address}")
    client_id = id(websocket)
    connected_host_id = None
    is_host = False
    
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == MessageType.REGISTER_HOST:
                host_id = data.get("host_id")
                connection_id = data.get("connection_id")
                password_hash = data.get("password_hash")
                password_salt = data.get("password_salt")
                await register_host(websocket, host_id, connection_id, password_hash, password_salt)
                is_host = True
                connected_host_id = host_id
                
            elif msg_type == MessageType.FIND_HOST:
                connection_id = data.get("connection_id")
                password = data.get("password")
                await find_host(websocket, connection_id, password)
                is_host = False
                connected_host_id = clients_to_hosts.get(websocket)
                
            elif msg_type in [MessageType.SDP, MessageType.ICE]:
                # If we are the host, broadcasting to all connected clients is one way.
                # Better way: relay to specific peer.
                # Since WebSockets don't easily track SDP session pairs without IDs,
                # let's just do a simple 1-to-1 relay: 
                # If host sends, relay to the first client looking for this host.
                # If client sends, relay to host.
                if is_host:
                    # relay to clients
                    for client_ws, h_id in dict(clients_to_hosts).items():
                        if h_id == connected_host_id:
                            try:
                                await client_ws.send(message)
                            except:
                                pass
                else:
                    # relay to host
                    if connected_host_id in hosts:
                        try:
                            await hosts[connected_host_id].send(message)
                        except:
                            pass
            else:
                logger.warning(f"Unknown message type: {msg_type}")

    except ws_exceptions.ConnectionClosed:
        logger.info(f"Connection closed {websocket.remote_address}")
    finally:
        if is_host and connected_host_id in hosts:
            del hosts[connected_host_id]
            host_auth_entry = host_auth.pop(connected_host_id, None)
            if host_auth_entry:
                connection_to_host.pop(host_auth_entry.get("connection_id"), None)
            logger.info(f"Unregistered host {connected_host_id}")
        if websocket in clients_to_hosts:
            del clients_to_hosts[websocket]

async def start_server():
    setup_logging()
    logger.info(f"Starting signaling server on 0.0.0.0:{SIGNALING_PORT}...")
    async with websockets.serve(handle_connection, "0.0.0.0", SIGNALING_PORT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(start_server())
