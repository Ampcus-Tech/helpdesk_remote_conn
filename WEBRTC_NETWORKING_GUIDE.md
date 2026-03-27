# Understanding WebRTC Networking: A Step-by-Step Guide

This guide explains how your remote desktop application establishes a secure connection across different network types (Wi-Fi, Mobile Data, VPNs).

## 1. The Three Key Players
Before the connection starts, three distinct services work together:

| Service | Role | Location in Config |
| :--- | :--- | :--- |
| **Signaling Server** | The "Switchboard" — it lets the Host and Client find each other. | `SIGNALING_URL` (Ngrok) |
| **STUN Server** | The "Mirror" — it tells your computer its **Public IP** address. | `stun.l.google.com` |
| **TURN Server** | The "Relay" — it passes data through a third-party server if a direct connection is blocked. | `global.relay.metered.ca` |

---

## 2. The Connection Process: Step-by-Step

### Step 1: Registration
*   The **Host** connects to the **Signaling Server** (Ngrok) and says: *"I am Host ID 'XYZ'."*
*   The **Client** connects to the same server and asks: *"Where is Host ID 'XYZ'?"*

### Step 2: Gathering Candidates
Each computer starts looking at every available "door" to reach the other side:
1.  **Host Candidates:** Your private internal IP (e.g., `172.22.41.15`).
2.  **Srflx Candidates (STUN):** Your router's public IP (found by asking the Google STUN server).
3.  **Relay Candidates (TURN):** A special backup IP provided by the Metered.ca server.

### Step 3: The SDP Handshake (Sharing the Menu)
The Host and Client exchange a text file called an **SDP (Session Description Protocol)**. This file contains a "menu" of all the IPs found in Step 2.
*   *Signaling Server encryp ts this exchange so only the two computers see the IPs.*

### Step 4: ICE Negotiation (The Ping Test)
Both computers simultaneously start "pining" every pair of IPs they received. In your logs, you see this as `Check CandidatePair`.
*   They try: Local -> Local
*   They try: Public -> Public
*   They try: Relay -> Relay

### Step 5: Final Connection (Winning Pair)
The first pair that successfully completes a "handshake" wins. WebRTC automatically picks the most direct and fastest path.

---

## 3. Analysis of Your Tests

### Scenario A: Same Network or VPN (Your 1st Log)
*   **Result:** `172.22.41.15` -> `172.22.41.13` **SUCCEEDED**.
*   **Explanation:** Because both computers were either on the same Wi-Fi or a virtual network (like Tailscale), they reached each other's **Private (Host) IPs**.
*   **Performance:** Ultra-low latency, crystal clear video.

### Scenario B: Different Hotspots (Your 2nd Log)
*   **Result:** `172.237.33.131` (TURN) -> `106.216.x.x` **SUCCEEDED**.
*   **Explanation:** Mobile hotspots use "Symmetric NAT," which blocks direct pings. The app realized STUN (Direct P2P) was impossible and switched to the **TURN Relay**.
*   **Performance:** Higher latency (slight delay), but it’s the only way the connection could work at all.

---

## 4. Security & Privacy FAQ

#### Q: Is it safe to share my Private (Host) IP in logs?
**Yes.** A private IP like `172.22.x.x` is useless to someone on the internet. It only works inside your personal Wi-Fi or VPN. It’s like knowing someone’s room number in a hotel but not having the room key.

#### Q: Can someone see my screen if they see these IPs?
**No.** All WebRTC traffic is **End-to-End Encrypted (E2EE)** using DTLS-SRTP. Even the TURN server owner cannot see your video because it is encrypted with a key that only the Host and Client possess.

#### Q: Why did STUN give a "401 Error"?
The `401 - Unauthorized` error is a normal part of the handshake. Your app sends a request without a password first; the TURN server says "401 - Go get a password"; your app sends the password automatically, and the connection succeeds.

---
