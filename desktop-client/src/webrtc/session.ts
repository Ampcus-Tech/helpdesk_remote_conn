import { MessageType } from "../protocol";
import { invoke } from "@tauri-apps/api/core";
 
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
let incomingSavePaths: Record<string, string> = {};

export function setIncomingFileSavePath(fileId: string, path: string) {
  incomingSavePaths[fileId] = path;
}
 
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
  if (fileChannel.readyState !== "open") {
    console.error("File channel not ready", fileChannel.readyState);
    return false;
  }

  const fileId = Math.random().toString(36).substring(2, 15);
  const fileName = file.name;
  const fileSize = file.size;
  
  console.log(`Sending file: ${fileName} (${fileSize} bytes)`);

  try {
    // Send offer
    if (fileChannel.readyState !== "open") {
      console.error("File channel closed before sending offer");
      return false;
    }
    fileChannel.send(JSON.stringify({
      type: MessageType.FILE_OFFER,
      file_id: fileId,
      file_name: fileName,
      file_size: fileSize
    }));
    console.log(`File offer sent for ${fileId}`);
  } catch (e: unknown) {
    console.error("Failed to send file offer:", e);
    return false;
  }

  // Wait for acceptance (with shorter timeout for better responsiveness)
  const accepted = await new Promise<boolean>((resolve) => {
    pendingOutgoingAccept[fileId] = resolve;
    const timer = setTimeout(() => {
      if (pendingOutgoingAccept[fileId]) {
        delete pendingOutgoingAccept[fileId];
        console.error("File offer timed out");
        resolve(false);
      }
    }, 30000);
    
    // Also resolve if channel closes
    const onClose = () => {
      if (pendingOutgoingAccept[fileId]) {
        delete pendingOutgoingAccept[fileId];
        clearTimeout(timer);
        console.error("File channel closed while waiting for acceptance");
        resolve(false);
      }
    };
    fileChannel.addEventListener("close", onClose, { once: true });
  });

  if (!accepted) {
    console.error("File offer not accepted");
    return false;
  }
  
  console.log(`File offer accepted for ${fileId}`);

  // Send start
  const chunkSize = 16 * 1024; // Reduced from 64KB to 16KB for better compatibility
  try {
    if (fileChannel.readyState !== "open") {
      console.error("File channel closed before sending start");
      return false;
    }
    fileChannel.send(JSON.stringify({
      type: MessageType.FILE_START,
      file_id: fileId,
      file_name: fileName,
      file_size: fileSize,
      chunk_size: chunkSize
    }));
    console.log(`File start sent, chunk size: ${chunkSize}`);
  } catch (e: unknown) {
    console.error("Failed to send file start:", e);
    return false;
  }
  
  // Send chunks
  let sent = 0;
  const reader = file.stream().getReader();
  let chunkCount = 0;
  
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
   
      let offset = 0;
      while (offset < value.length) {
        // Check channel is still open
        if (fileChannel.readyState !== "open") {
          console.error("File channel closed before sending chunk", chunkCount);
          return false;
        }
        
        const end = Math.min(offset + chunkSize, value.length);
        const chunk = value.slice(offset, end);
        
        // Backpressure: wait if buffer is getting full
        if (fileChannel.bufferedAmount > 2 * 1024 * 1024) { // 2MB threshold
          let drainWaits = 0;
          while (fileChannel.bufferedAmount > 2 * 1024 * 1024 && fileChannel.readyState === "open") {
            await new Promise(r => setTimeout(r, 10));
            drainWaits++;
            if (drainWaits > 300) { // ~3s timeout
              console.error("Buffer drain timeout");
              return false;
            }
          }
        }
   
        // Fast base64 encoding using native btoa (much faster than FileReader)
        let base64 = "";
        try {
          // Convert Uint8Array to binary string, then encode
          base64 = btoa(String.fromCharCode.apply(null, Array.from(chunk)));
        } catch (e: unknown) {
          console.error("Failed to encode chunk to base64:", e);
          return false;
        }
   
        try {
          fileChannel.send(JSON.stringify({
            type: MessageType.FILE_CHUNK,
            file_id: fileId,
            chunk_b64: base64
          }));
          chunkCount++;
        } catch (e: unknown) {
          console.error(`Failed to send file chunk ${chunkCount}:`, e);
          return false;
        }
   
        sent += chunk.length;
        onProgress(sent);
        offset = end;
        
        // Yield to browser every 20 chunks to prevent UI blocking
        if (chunkCount % 20 === 0) {
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
 
  // Send end message
  try {
    if (fileChannel.readyState !== "open") {
      console.error("File channel closed before sending end");
      return false;
    }
    fileChannel.send(JSON.stringify({
      type: MessageType.FILE_END,
      file_id: fileId
    }));
    console.log(`File transfer complete: ${fileId}, ${chunkCount} chunks, ${sent} bytes`);
  } catch (e: unknown) {
    console.error("Failed to send file end:", e);
    return false;
  }
 
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
      if (o.type === MessageType.DISCONNECT) {
        handlers.onSessionEnd("Host has disconnected the connection.");
        return;
      }
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
          path: incomingSavePaths[payload.file_id] || "",
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
          // Decode all base64 chunks into a single byte array and save to the path
          // chosen by the client when accepting the file offer.
          const decodedChunks = f.chunks.map((b64) => {
            const bin = atob(b64);
            const arr = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
            return arr;
          });
          const totalSize = decodedChunks.reduce((sum, chunk) => sum + chunk.length, 0);
          const bytes = new Uint8Array(totalSize);
          let offset = 0;
          for (const chunk of decodedChunks) {
            bytes.set(chunk, offset);
            offset += chunk.length;
          }

          if (f.path) {
            await invoke("save_received_file", {
              path: f.path,
              bytes: Array.from(bytes)
            });
            handlers.onFileDone(f.name, f.path, "recv");
          } else {
            // Fallback if no explicit path was stored (should be rare).
            const blob = new Blob([bytes]);
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = f.name;
            a.click();
            URL.revokeObjectURL(url);
            handlers.onFileDone(f.name, "Downloads", "recv");
          }

          delete incomingSavePaths[payload.file_id];
          delete incomingFiles[payload.file_id];
        }
      }
    } catch (e: unknown) {
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
    if (st === "failed" || st === "disconnected" || st === "closed") {
      // Send disconnect message to host if control channel is still open
      if (ctrl.readyState === "open") {
        try {
          ctrl.send(JSON.stringify({ type: MessageType.DISCONNECT }));
        } catch (e) {
          console.error("Failed to send disconnect message:", e);
        }
      }
      if (st === "failed") {
        handlers.onSessionEnd("ICE failed");
      } else {
        handlers.onSessionEnd("Client has disconnected the connection.");
      }
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