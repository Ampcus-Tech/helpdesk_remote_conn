# Remote Desktop App

A Python-based remote desktop core (WebRTC via `aiortc`, WebSocket signaling, `mss` + OpenCV on the host for capture/processing, `pynput` for input injection) plus a **Tauri + React** viewer for low-latency playback (native `<video>` / hardware decoding instead of OpenCV `imshow` on the viewer).

## Project Structure

- `signaling/`: WebSocket server for SDP relay.
- `host/`: Host application capturing the screen and receiving input (Python).
- `desktop-client/`: Tauri shell + React UI + browser WebRTC.
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

### 3. Start the Client (Tauri + React viewer)

Prerequisites: [Node.js](https://nodejs.org/), [Rust](https://www.rust-lang.org/tools/install) (for Tauri), same signaling URL and STUN/TURN settings as `common/config.py`.

```bash
cd desktop-client
copy .env.example .env
# Edit .env: set VITE_SIGNALING_URL (and VITE_ICE_SERVERS_JSON if you use TURN — must match host/client ICE).
npm install
npm run tauri dev
```

Enter the host ID in the UI and connect. Production build: `npm run tauri build`.


## P2P Chat and File Transfer

- Chat and file transfer use WebRTC DataChannels (`chat` and `file`), so payload data is peer-to-peer after session setup.
- Incoming file transfers prompt the receiver to choose a save path before transfer starts.

### No Relay Mode (Direct P2P Only)

To disable TURN relay and allow only direct P2P candidates:

```bash
# Windows PowerShell
$env:NO_RELAY="1"
```

Then start Host/Client from the same terminal session.

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

## Make it Clearer (Ultraviewer-like Tuning)
Your current WebRTC pipeline is solid; the biggest quality jump is bitrate + codec choice.

### VP9 note (important)
With your installed `aiortc` version, `VP9` is not available. The fastest path to “Ultraviewer clarity” in this stack is:

- Prefer `H264` (`VIDEO_CODEC=h264`)
- Increase `VIDEO_BITRATE`
- Optionally increase `TARGET_FPS`

### Quick settings to try
Edit `common/config.py` or set environment variables before starting Host/Client.

- `VIDEO_CODEC`: `vp8` or `h264` (default: `h264`)
- `VIDEO_BITRATE`: bits/sec (default: `2000000`)
- `VIDEO_BITRATE_MIN`: encoder floor (default: `1000000`)
- `VIDEO_BITRATE_MAX`: encoder ceiling (default: `4000000`)
- `TARGET_FPS`: frame rate (default: `24`)
- `DEFAULT_QUALITY`: affects capture scaling (`low`=0.5, `medium`=0.75, `high`=1.0)
- `CAPTURE_MAX_WIDTH`: host capture width cap (default: `1920`, set `0` to disable)
- `CAPTURE_MAX_HEIGHT`: host capture height cap (default: `1080`, set `0` to disable)

### Recommended starting point
If your connection is decent, try:

- `VIDEO_CODEC=h264`
- `VIDEO_BITRATE=4500000`
- `TARGET_FPS=24`

For lag spikes while switching apps/windows, also prefer UDP relay:

- `ICE_UDP_TURN_FIRST=1` (default now)
- if your office network blocks UDP, fallback with `ICE_UDP_TURN_FIRST=0`

Then restart both apps and evaluate sharpness/latency.

