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
  onHostInfo: (os: string) => void;
  onChatText: (sender: "Host" | "You" | "SYSTEM", text: string) => void;
  onFileOffer: (fileId: string, fileName: string, fileSize: number) => void;
  onFileProgress: (fileName: string, transferred: number, total: number, direction: "send" | "recv") => void;
  onFileDone: (fileName: string, path: string, direction: "send" | "recv") => void;
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
 
// Internal state for file transfers
let incomingFiles: Record<string, {
  name: string;
  size: number;
  received: number;
  path: string;
  // In a real app we'd write to disk, for now we collect in memory 
  // or use a Tauri command. Let's use a command for better performance.
  chunks: string[]; 
}> = {};
 
let pendingOutgoingAccept: Record<string, (accepted: boolean) => void> = {};
 
async function waitForIceGatheringComplete(pc: RTCPeerConnection, timeoutMs = 15000): Promise<void> {
  if (pc.iceGatheringState === "complete") return;
  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      pc.removeEventListener("icegatheringstatechange", onStateChange);
      window.clearTimeout(timer);
      resolve();
    };
    const onStateChange = () => {
      if (pc.iceGatheringState === "complete") finish();
    };
    const timer = window.setTimeout(finish, timeoutMs);
    pc.addEventListener("icegatheringstatechange", onStateChange);
  });
}
 
function defaultIceServers(): RTCIceServer[] {
  return [{ urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] }];
}
 
function loadIceServers(): RTCIceServer[] {
  const raw = import.meta.env.VITE_ICE_SERVERS_JSON;
  if (!raw) return defaultIceServers();
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return defaultIceServers();
    console.log('Loaded ICE servers:', parsed);
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
 
export function respondFileOffer(fileChannel: RTCDataChannel, fileId: string, accepted: boolean) {
  if (fileChannel.readyState !== "open") return;
  fileChannel.send(JSON.stringify({
    type: MessageType.FILE_ACCEPT,
    file_id: fileId,
    accepted: accepted
  }));
}
 
export async function sendFile(fileChannel: RTCDataChannel, file: File, onProgress: (p: number) => void) {
  if (fileChannel.readyState !== "open") return;
 
  const fileId = Math.random().toString(36).substring(2, 15);
  const fileName = file.name;
  const fileSize = file.size;
 
  // Send offer
  fileChannel.send(JSON.stringify({
    type: MessageType.FILE_OFFER,
    file_id: fileId,
    file_name: fileName,
    file_size: fileSize
  }));
 
  // Wait for acceptance
  const accepted = await new Promise<boolean>((resolve) => {
    pendingOutgoingAccept[fileId] = resolve;
    // Timeout after 60s
    setTimeout(() => {
      if (pendingOutgoingAccept[fileId]) {
        delete pendingOutgoingAccept[fileId];
        resolve(false);
      }
    }, 60000);
  });
 
  if (!accepted) return false;
 
  // Send start
  const chunkSize = 64 * 1024;
  fileChannel.send(JSON.stringify({
    type: MessageType.FILE_START,
    file_id: fileId,
    file_name: fileName,
    file_size: fileSize,
    chunk_size: chunkSize
  }));
 
  // Send chunks
  let sent = 0;
  const reader = file.stream().getReader();
  
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
 
    let offset = 0;
    while (offset < value.length) {
      const end = Math.min(offset + chunkSize, value.length);
      const chunk = value.slice(offset, end);
      
      // Wait if buffer is full
      while (fileChannel.bufferedAmount > 4 * 1024 * 1024) {
        await new Promise(r => setTimeout(r, 10));
      }
 
      // Convert chunk to base64 (matching Python implementation)
      const base64 = await new Promise<string>((resolve) => {
        const r = new FileReader();
        r.onload = () => resolve((r.result as string).split(',')[1]);
        r.readAsDataURL(new Blob([chunk]));
      });
 
      fileChannel.send(JSON.stringify({
        type: MessageType.FILE_CHUNK,
        file_id: fileId,
        chunk_b64: base64
      }));
 
      sent += chunk.length;
      onProgress(sent);
      offset = end;
    }
  }
 
  // Send end
  fileChannel.send(JSON.stringify({
    type: MessageType.FILE_END,
    file_id: fileId
  }));
 
  return true;
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
  const pc = new RTCPeerConnection({ iceServers, iceTransportPolicy: 'all' });
 
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
      if (o.type === MessageType.HOST_INFO && (o as any).os) {
        handlers.onHostInfo((o as any).os);
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
 
  file.onmessage = async (ev) => {
    const text = typeof ev.data === "string" ? ev.data : "";
    try {
      const payload = JSON.parse(text);
      const msgType = payload.type;
 
      if (msgType === MessageType.FILE_OFFER) {
        handlers.onFileOffer(payload.file_id, payload.file_name, payload.file_size);
      } else if (msgType === MessageType.FILE_ACCEPT) {
        const resolve = pendingOutgoingAccept[payload.file_id];
        if (resolve) {
          delete pendingOutgoingAccept[payload.file_id];
          resolve(payload.accepted);
        }
      } else if (msgType === MessageType.FILE_START) {
        incomingFiles[payload.file_id] = {
          name: payload.file_name,
          size: payload.file_size,
          received: 0,
          path: "", // We'll set this when user accepts
          chunks: []
        };
      } else if (msgType === MessageType.FILE_CHUNK) {
        const f = incomingFiles[payload.file_id];
        if (f) {
          f.chunks.push(payload.chunk_b64);
          f.received += Math.floor((payload.chunk_b64.length * 3) / 4); // basic estimate
          handlers.onFileProgress(f.name, f.received, f.size, "recv");
        }
      } else if (msgType === MessageType.FILE_END) {
        const f = incomingFiles[payload.file_id];
        if (f) {
          // Combine chunks and save
          const blobs = f.chunks.map(b64 => {
            const bin = atob(b64);
            const arr = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
            return arr;
          });
          const blob = new Blob(blobs);
          
          // In Tauri, we can use a command to save this truly to disk if we want.
          // For now, we'll just trigger a browser download.
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = f.name;
          a.click();
          URL.revokeObjectURL(url);
 
          handlers.onFileDone(f.name, "Downloads", "recv");
          delete incomingFiles[payload.file_id];
        }
      }
    } catch (e) {
      console.error("File channel error:", e);
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
    console.log('ICE connection state:', st);
    handlers.onStatus(`ICE: ${st}`);
    if (st === "failed") {
      handlers.onSessionEnd("ICE failed");
    }
  };
 
  pc.onicecandidate = (ev) => {
    if (ev.candidate) {
      console.log('ICE candidate gathered:', ev.candidate.candidate);
    } else {
      console.log('ICE gathering complete');
    }
  };
 
  ws.send(JSON.stringify({ type: MessageType.FIND_HOST, host_id: hostId }));
 
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  handlers.onStatus("Gathering ICE candidates...");
  await waitForIceGatheringComplete(pc);
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