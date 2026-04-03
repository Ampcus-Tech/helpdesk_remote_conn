import { MessageType } from "../protocol";

export type DataChannels = {
  ctrl: RTCDataChannel;
  chat: RTCDataChannel;
  file: RTCDataChannel;
};

export type SessionHandlers = {
  onStatus: (msg: string) => void;
  onVideoStream: (stream: MediaStream) => void;
  onControlOpen: (send: (json: string) => void) => void;
  onControlMessage: (text: string) => void;
  onCursorName: (name: string) => void;
  onChatText: (sender: "Host" | "You", text: string) => void;
  onDataChannelsReady: (ch: DataChannels) => void;
  onSessionEnd: (reason: string) => void;
};

export type ActiveSession = {
  pc: RTCPeerConnection;
  ws: WebSocket;
  channels: DataChannels;
  close: () => void;
};

const CTRL = "control";
const CHAT = "chat";
const FILE = "file";

function defaultIceServers(): RTCIceServer[] {
  return [{ urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] }];
}

function loadIceServers(): RTCIceServer[] {
  const raw = import.meta.env.VITE_ICE_SERVERS_JSON;
  if (!raw) return defaultIceServers();
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return defaultIceServers();
    return parsed as RTCIceServer[];
  } catch {
    return defaultIceServers();
  }
}

export function sendChatLine(chat: RTCDataChannel, text: string) {
  if (chat.readyState !== "open") return;
  const payload = {
    type: MessageType.CHAT_TEXT,
    text: text.trim(),
    ts: Math.floor(Date.now() / 1000),
  };
  chat.send(JSON.stringify(payload));
}

/**
 * Start viewer session: WebSocket signaling + WebRTC (matches Python `client/webrtc_client.py` flow).
 */
export async function startSession(hostId: string, handlers: SessionHandlers): Promise<ActiveSession> {
  const signalingUrl = import.meta.env.VITE_SIGNALING_URL || "ws://127.0.0.1:8080";
  handlers.onStatus(`Signaling: ${signalingUrl}`);

  const ws = await new Promise<WebSocket>((resolve, reject) => {
    const s = new WebSocket(signalingUrl);
    s.onopen = () => resolve(s);
    s.onerror = () => reject(new Error("WebSocket failed to connect"));
  });

  const iceServers = loadIceServers();
  const pc = new RTCPeerConnection({ iceServers });

  const ctrl = pc.createDataChannel(CTRL, { ordered: true });
  const chat = pc.createDataChannel(CHAT, { ordered: true });
  const file = pc.createDataChannel(FILE, { ordered: true });

  const channels: DataChannels = { ctrl, chat, file };

  let chatReady = false;
  let fileReady = false;

  const maybeEmitChannelsReady = () => {
    if (chatReady && fileReady) handlers.onDataChannelsReady(channels);
  };

  chat.onopen = () => {
    chatReady = true;
    maybeEmitChannelsReady();
  };
  chat.onclose = () => {
    chatReady = false;
    handlers.onSessionEnd("chat channel closed");
  };

  file.onopen = () => {
    fileReady = true;
    maybeEmitChannelsReady();
  };
  file.onclose = () => {
    fileReady = false;
    handlers.onSessionEnd("file channel closed");
  };

  ctrl.onopen = () => {
    handlers.onControlOpen((json) => {
      if (ctrl.readyState === "open") ctrl.send(json);
    });
  };

  ctrl.onmessage = (ev) => {
    const text = typeof ev.data === "string" ? ev.data : "";
    if (!text) return;
    try {
      const o = JSON.parse(text) as { type?: string; cursor_name?: string };
      if (o.type === MessageType.CURSOR_UPDATE && o.cursor_name) {
        handlers.onCursorName(o.cursor_name);
        return;
      }
    } catch {
      /* ignore */
    }
    handlers.onControlMessage(text);
  };

  chat.onmessage = (ev) => {
    const text = typeof ev.data === "string" ? ev.data : "";
    try {
      const o = JSON.parse(text) as { type?: string; text?: string };
      if (o.type === MessageType.CHAT_TEXT && o.text) {
        handlers.onChatText("Host", o.text);
      }
    } catch {
      /* ignore */
    }
  };

  pc.addTransceiver("video", { direction: "recvonly" });

  pc.ontrack = (ev) => {
    if (ev.track.kind === "video") {
      const [stream] = ev.streams;
      if (stream) handlers.onVideoStream(stream);
    }
  };

  pc.oniceconnectionstatechange = () => {
    const st = pc.iceConnectionState;
    handlers.onStatus(`ICE: ${st}`);
    if (st === "failed") {
      handlers.onSessionEnd("ICE failed");
    }
  };

  ws.send(JSON.stringify({ type: MessageType.FIND_HOST, host_id: hostId }));

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const local = pc.localDescription;
  if (!local?.sdp) throw new Error("Missing local SDP");

  ws.send(JSON.stringify({ type: MessageType.SDP, sdp: { sdp: local.sdp, type: local.type } }));

  const answer = await new Promise<RTCSessionDescriptionInit>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      reject(new Error("Timed out waiting for SDP answer"));
    }, 120_000);

    ws.onmessage = (ev) => {
      let data: { type?: string; sdp?: { sdp?: string; type?: RTCSdpType } };
      try {
        data = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      if (data.type === MessageType.HOST_NOT_FOUND) {
        window.clearTimeout(timer);
        reject(new Error(`Host ${hostId} not found on signaling server`));
        return;
      }
      if (data.type === MessageType.SDP && data.sdp?.sdp && data.sdp.type) {
        window.clearTimeout(timer);
        resolve({ type: data.sdp.type, sdp: data.sdp.sdp });
      }
    };
  });

  await pc.setRemoteDescription(answer);
  handlers.onStatus("WebRTC negotiated; waiting for media…");

  const close = () => {
    try {
      ws.close();
    } catch {
      /* ignore */
    }
    try {
      pc.close();
    } catch {
      /* ignore */
    }
  };

  return { pc, ws, channels, close };
}
