# Remote Desktop App

A Python-based remote desktop application using WebRTC (`aiortc`), WebSockets for signaling, `mss` for screen capture, OpenCV for display and frame processing, and `pynput` for remote input control.

## Project Structure

- `signaling/`: WebSocket server for SDP and ICE relay.
- `host/`: Host application capturing the screen and receiving input.
- `client/`: Client application displaying the screen and generating input.
- `common/`: Shared config, message structs, and utils.

## Installation

1. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   *Note: `aiortc`, `websockets`, `mss`, `pynput`, `opencv-python` are required. PyAV is automatically installed with `aiortc`.*

## Running the Application

./ngrok.exe http 8080

### 1. Start the Signaling Server
```bash
python signaling/server.py
```
*Runs on `127.0.0.1:8080` by default. Change in `common/config.py`.*

### 2. Start the Host Application
On the computer you want to control:
```bash
python host/main.py
```
This will output a 6-digit Host ID (e.g., `123456`). Keep this window open.

### 3. Start the Client Application
On the computer you are using as a viewer:vgdf
```bash
python client/main.py
```
When prompted, enter the 6-digit Host ID. Or pass it as an argument:
```bash
python client/main.py 123456
```

## Running across the Internet (Office Firewall Fix)

If you are on an office network or different networks, use **Ngrok** to bypass the firewall without needing Administrator rights:

### 1. Install Ngrok
1. Go to [ngrok.com](https://ngrok.com/) and create a free account.
2. Download the **Ngrok Agent** for Windows and unzip the `ngrok.exe` file.
3. Open a terminal where you unzipped it and run: 
   `./ngrok config add-authtoken YOUR_AUTH_TOKEN_FROM_DASHBOARD`

### 2. Start the Tunnel
1. Run the signaling server: `python signaling/server.py`
2. Start the tunnel in a new terminal: `./ngrok http 8080`
3. Copy the **Forwarding URL** (e.g., `https://xxxx.ngrok-free.app`).

### 3. Update the Config
1. Open `common/config.py` on **both** PCs.
2. Change the `SIGNALING_URL` to your Ngrok URL (change `https` to `wss`):
   ```python
   SIGNALING_URL = "wss://xxxx.ngrok-free.app"
   ```
   *Note: Do NOT add :8080 to the Ngrok URL.*

### 4. Run the Apps
- **Host PC**: `python host/main.py`
- **Viewer PC**: `python client/main.py`

