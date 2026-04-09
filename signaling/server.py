import asyncio
import json
import logging
import websockets
from websockets.server import WebSocketServerProtocol
import sys
import os

# Add parent directory to path to import common
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.config import SIGNALING_HOST, SIGNALING_PORT, setup_logging
from common.messages import SignalingMessage, MessageType

logger = logging.getLogger("signaling")

# Maintain a dictionary of registered hosts: { host_id: websocket }
hosts = {}
# Maintain a dictionary mapping clients to their connected host_id
# so we can route client messages back to the correct host.
clients_to_hosts = {}

async def register_host(websocket: WebSocketServerProtocol, host_id: Any):
    host_id_str = str(host_id)
    logger.info(f"Registering host {host_id_str}")
    hosts[host_id_str] = websocket
    response = SignalingMessage(type=MessageType.HOST_REGISTERED, host_id=host_id_str)
    await websocket.send(response.to_json())

async def find_host(websocket: WebSocketServerProtocol, host_id: Any):
    host_id_str = str(host_id)
    logger.info(f"Client searching for host {host_id_str}")
    if host_id_str in hosts:
        clients_to_hosts[websocket] = host_id_str
        # Let client know host was found
        response = SignalingMessage(type=MessageType.HOST_FOUND, host_id=host_id_str)
        await websocket.send(response.to_json())
        # Let host know a client wants to connect via an offer they will send
        # Typically the client follows up with an SDP offer.
    else:
        logger.warning(f"Host {host_id_str} not found")
        response = SignalingMessage(type=MessageType.HOST_NOT_FOUND, host_id=host_id_str)
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
                await register_host(websocket, host_id)
                is_host = True
                connected_host_id = str(host_id)
                
            elif msg_type == MessageType.FIND_HOST:
                host_id = data.get("host_id")
                await find_host(websocket, host_id)
                is_host = False
                connected_host_id = str(host_id)
                
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

    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Connection closed {websocket.remote_address}")
    finally:
        if is_host and connected_host_id and connected_host_id in hosts:
            if hosts[connected_host_id] == websocket:
                del hosts[connected_host_id]
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
