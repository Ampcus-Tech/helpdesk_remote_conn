import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageType } from "./protocol";
import { pointerToVideoFrame } from "./webrtc/coords";
import { mapKeyboardEvent } from "./webrtc/keyboard";
import { ActiveSession, sendChatLine, startHostSession, startSession } from "./webrtc/session";
 
const MOUSE_MOVE_INTERVAL_MS = 1000 / 60;
const DC_BUFFER_CAP = 24 * 1024;

const generateHostId = () => Math.floor(100000 + Math.random() * 900000).toString();
 
const CURSOR_CSS: Record<string, string> = {
  arrow: "default",
  ibeam: "text",
  wait: "wait",
  crosshair: "crosshair",
  hand: "pointer",
  size_we: "ew-resize",
  size_ns: "ns-resize",
  size_nwse: "nwse-resize",
  size_nesw: "nesw-resize",
  size_all: "move",
  uparrow: "default",
  no: "not-allowed",
  appstarting: "progress",
  help: "help",
};
 
function useStatus(initial: string) {
  const [status, setStatus] = useState(initial);
  return { status, setStatus };
}
 
export default function App() {
  const [role, setRole] = useState<"host" | "client">("client");
  const [hostId, setHostId] = useState("");
  const [signalingUrl, setSignalingUrl] = useState(import.meta.env.VITE_SIGNALING_URL || "ws://127.0.0.1:8080");
  const { status, setStatus } = useStatus("Idle");
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [sessionAlive, setSessionAlive] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [chatLines, setChatLines] = useState<{ who: string; text: string }[]>([]);
  const [chatDraft, setChatDraft] = useState("");
  const [cursorName, setCursorName] = useState("arrow");
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
 
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const sessionRef = useRef<ActiveSession | null>(null);
  const ctrlSendRef = useRef<((json: string) => void) | null>(null);
  const chatRef = useRef<RTCDataChannel | null>(null);
  const lastMoveAt = useRef(0);
  const buttonsDown = useRef<Set<"left" | "right">>(new Set());
  const pressedKeys = useRef<Set<string>>(new Set());
  const lastPointer = useRef<{ x: number; y: number } | null>(null);
  const moveTimer = useRef<number | null>(null);
  const moveArmed = useRef(false);
 
  const cursorStyle = useMemo(() => CURSOR_CSS[cursorName] || "default", [cursorName]);
 
  const releaseAllKeys = useCallback(() => {
    const fn = ctrlSendRef.current;
    if (!fn) return;
    if (pressedKeys.current.size === 0) return;
    for (const k of Array.from(pressedKeys.current)) {
      fn(JSON.stringify({ type: MessageType.KEYBOARD, key: k, pressed: false }));
    }
    pressedKeys.current.clear();
  }, []);
 
  const disconnect = useCallback(() => {
    releaseAllKeys();
    if (moveTimer.current != null) {
      window.clearTimeout(moveTimer.current);
      moveTimer.current = null;
    }
    moveArmed.current = false;
    lastPointer.current = null;
    releaseAllKeys();
    if (moveTimer.current != null) {
      window.clearTimeout(moveTimer.current);
      moveTimer.current = null;
    }
    moveArmed.current = false;
    lastPointer.current = null;
    sessionRef.current?.close();
    sessionRef.current = null;
    ctrlSendRef.current = null;
    chatRef.current = null;
    const v = videoRef.current;
    if (v) {
      v.srcObject = null;
    }
    if (localStream) {
      localStream.getTracks().forEach((track) => track.stop());
      setLocalStream(null);
    }
    setConnected(false);
    setSessionAlive(false);
    setConnecting(false);
    setStatus("Disconnected");
  }, [localStream, releaseAllKeys]);
 
  const appendChat = useCallback((who: string, text: string) => {
    setChatLines((prev) => [...prev, { who, text }]);
  }, []);
 
  const connect = useCallback(async () => {
    const id = hostId.trim();
    if (!id) {
      setStatus(role === "host" ? "Enter a Host ID" : "Enter a Host ID to connect");
      return;
    }
    if (connecting || sessionAlive) return;
 
    setConnecting(true);
    setStatus(role === "host" ? "Starting host..." : "Connecting…");
    setChatLines([]);
 
    try {
      const handlers = {
        onStatus: setStatus,
        onVideoStream: (stream: MediaStream) => {
          const v = videoRef.current;
          if (v) {
            v.srcObject = stream;
            void v.play().catch(() => {});
          }
          setStatus(role === "host" ? "Sharing screen" : "Receiving video");
          setConnected(true);
          setLocalStream(stream);
        },
        onControlOpen: (send: (json: string) => void) => {
          ctrlSendRef.current = send;
        },
        onControlMessage: () => {},
        onCursorName: (name: string) => setCursorName(name),
        onChatText: (sender: string, text: string) => appendChat(sender, text),
        onDataChannelsReady: (ch: { ctrl: RTCDataChannel; chat: RTCDataChannel; file: RTCDataChannel }) => {
          chatRef.current = ch.chat;
          setStatus("Session ready (chat/files)");
          setConnected(true);
        },
        onSessionEnd: (reason: string) => {
          setStatus(reason);
          disconnect();
        },
      };

      const session =
        role === "host"
          ? await startHostSession(id, handlers, signalingUrl)
          : await startSession(id, handlers, signalingUrl);

      sessionRef.current = session;
      setSessionAlive(true);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
      disconnect();
    } finally {
      setConnecting(false);
    }
  }, [appendChat, connecting, disconnect, hostId, role, signalingUrl, sessionAlive]);
 
  useEffect(() => {
    if (role === "host" && !hostId) {
      setHostId(generateHostId());
    }
  }, [hostId, role]);
 
  useEffect(() => {
    return () => disconnect();
  }, [disconnect]);
 
  const sendCtrl = (payload: object) => {
    const fn = ctrlSendRef.current;
    if (!fn) return;
    fn(JSON.stringify(payload));
  };
 
  useEffect(() => {
    const onBlur = () => releaseAllKeys();
    const onVis = () => {
      if (document.visibilityState !== "visible") releaseAllKeys();
    };
    window.addEventListener("blur", onBlur);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [releaseAllKeys]);
 
  useEffect(() => {
    return () => {
      if (moveTimer.current != null) window.clearTimeout(moveTimer.current);
    };
  }, []);
 
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const video = videoRef.current;
      const fn = ctrlSendRef.current;
      if (!video || !fn) return;
      e.preventDefault();
      const mapped = pointerToVideoFrame(e.clientX, e.clientY, video);
      if (!mapped) return;
      const dx = e.deltaX;
      const dy = e.deltaY;
      const scroll_dy =
        dy === 0 ? 0 : Math.abs(dy) < 1 ? (dy > 0 ? 1 : -1) : Math.trunc(dy / 100) || (dy > 0 ? 1 : -1);
      const scroll_dx =
        dx === 0 ? 0 : Math.abs(dx) < 1 ? (dx > 0 ? 1 : -1) : Math.trunc(dx / 100) || (dx > 0 ? 1 : -1);
      fn(
        JSON.stringify({
          type: MessageType.MOUSE_SCROLL,
          x: mapped.x,
          y: mapped.y,
          screen_width: mapped.screen_width,
          screen_height: mapped.screen_height,
          scroll_dx,
          scroll_dy,
        }),
      );
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [sessionAlive]);
 
  const onPointerMove = (e: React.PointerEvent) => {
    // Coalesce mouse-move to avoid queuing delays on the ordered control channel.
    lastPointer.current = { x: e.clientX, y: e.clientY };
    if (moveArmed.current) return;
    moveArmed.current = true;
 
    const tick = () => {
      moveArmed.current = false;
      moveTimer.current = null;
 
      const video = videoRef.current;
      const ch = sessionRef.current?.channels?.ctrl;
      const fn = ctrlSendRef.current;
      const pt = lastPointer.current;
      if (!video || !ch || !fn || !pt) return;
 
      const now = performance.now();
      if (now - lastMoveAt.current < MOUSE_MOVE_INTERVAL_MS) {
        moveTimer.current = window.setTimeout(tick, Math.max(0, MOUSE_MOVE_INTERVAL_MS - (now - lastMoveAt.current)));
        moveArmed.current = true;
        return;
      }
 
      // Backpressure: if SCTP buffer has grown, drop moves until it drains.
      if (ch.bufferedAmount > DC_BUFFER_CAP) {
        moveTimer.current = window.setTimeout(tick, 16);
        moveArmed.current = true;
        return;
      }
 
      const mapped = pointerToVideoFrame(pt.x, pt.y, video);
      if (!mapped) return;
      lastMoveAt.current = now;
      fn(
        JSON.stringify({
          type: MessageType.MOUSE_MOVE,
          x: mapped.x,
          y: mapped.y,
          screen_width: mapped.screen_width,
          screen_height: mapped.screen_height,
        }),
      );
    };
 
    moveTimer.current = window.setTimeout(tick, 0);
  };
 
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    el.focus();
    try {
      el.setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
 
    const video = videoRef.current;
    if (!video || !ctrlSendRef.current) return;
    const mapped = pointerToVideoFrame(e.clientX, e.clientY, video);
    if (!mapped) return;
 
    if (e.button === 0) {
      buttonsDown.current.add("left");
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "left", pressed: true });
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "left", pressed: true });
    } else if (e.button === 2) {
      e.preventDefault();
      buttonsDown.current.add("right");
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "right", pressed: true });
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "right", pressed: true });
    }
  };
 
  const onPointerUp = (e: React.PointerEvent) => {
    if (!ctrlSendRef.current) return;
    if (e.button === 0 && buttonsDown.current.has("left")) {
      buttonsDown.current.delete("left");
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "left", pressed: false });
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "left", pressed: false });
    } else if (e.button === 2 && buttonsDown.current.has("right")) {
      e.preventDefault();
      buttonsDown.current.delete("right");
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "right", pressed: false });
    }
  };
 
  const onPointerCancel = () => {
    if (!ctrlSendRef.current) return;
    if (buttonsDown.current.has("left")) {
      buttonsDown.current.delete("left");
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "left", pressed: false });
    }
    if (buttonsDown.current.has("right")) {
      buttonsDown.current.delete("right");
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "right", pressed: false });
    }
  };
 
  const onDoubleClick = (e: React.MouseEvent) => {
    const video = videoRef.current;
    if (!video || !ctrlSendRef.current) return;
    const mapped = pointerToVideoFrame(e.clientX, e.clientY, video);
    if (!mapped) return;
    if (e.button === 0) {
      sendCtrl({ type: MessageType.MOUSE_DOUBLE_CLICK, button: "left" });
    } else if (e.button === 2) {
      sendCtrl({ type: MessageType.MOUSE_DOUBLE_CLICK, button: "right" });
    }
  };
 
  const onKey = (e: React.KeyboardEvent) => {
    if (!ctrlSendRef.current) return;
    const mk = mapKeyboardEvent(e.nativeEvent);
    if (!mk) return;
    e.preventDefault();
    if (mk.pressed) pressedKeys.current.add(mk.key);
    else pressedKeys.current.delete(mk.key);
    sendCtrl({ type: MessageType.KEYBOARD, key: mk.key, pressed: mk.pressed });
    if (mk.pressed) pressedKeys.current.add(mk.key);
    else pressedKeys.current.delete(mk.key);
    sendCtrl({ type: MessageType.KEYBOARD, key: mk.key, pressed: mk.pressed });
  };
 
  const sendChatNow = () => {
    const ch = chatRef.current;
    if (!ch) return;
    const t = chatDraft.trim();
    if (!t) return;
    sendChatLine(ch, t);
    appendChat("You", t);
    setChatDraft("");
  };
 
  return (
    <div className="layout">
      <div className="toolbar">
        <div className="role-buttons">
          <button
            type="button"
            className={role === "host" ? "active" : "secondary"}
            disabled={connecting || sessionAlive}
            onClick={() => setRole("host")}
          >
            Host session
          </button>
          <button
            type="button"
            className={role === "client" ? "active" : "secondary"}
            disabled={connecting || sessionAlive}
            onClick={() => setRole("client")}
          >
            Join session
          </button>
        </div>

        <input
          type="text"
          placeholder="Signaling URL"
          value={signalingUrl}
          disabled={connecting || sessionAlive}
          onChange={(e) => setSignalingUrl(e.target.value)}
        />
        <input
          type="text"
          placeholder={role === "host" ? "Host ID to share" : "Host ID to connect"}
          value={hostId}
          disabled={connecting || sessionAlive}
          style={{ fontWeight: "bold", textAlign: "center", minWidth: "120px", color: role === "host" ? "#00ff88" : "inherit" }}
          onChange={(e) => setHostId(e.target.value.replace(/\D/g, "").slice(0, 8))}
        />
        {role === "host" && !sessionAlive && !connecting && (
          <button type="button" className="secondary" onClick={() => setHostId(generateHostId())}>
            New ID
          </button>
        )}
        <button 
          type="button" 
          className={!sessionAlive ? "primary" : "secondary"}
          disabled={connecting || (!sessionAlive && !hostId.trim())} 
          onClick={sessionAlive ? disconnect : connect}
        >
          {connecting ? "Starting..." : sessionAlive ? "Stop Session" : role === "host" ? "Start Host" : "Connect"}
        </button>
        <button type="button" className="secondary" onClick={() => setChatOpen((v) => !v)}>
          {chatOpen ? "Hide chat" : "Show chat"}
        </button>
        <div className="status" style={{ marginLeft: "auto" }}>{status}</div>
      </div>
 
      <div className="stage">
        <div
          ref={wrapRef}
          className="video-wrap"
          tabIndex={role === "client" ? 0 : -1}
          style={{ cursor: role === "client" ? cursorStyle : "default" }}
          onPointerMove={role === "client" ? onPointerMove : undefined}
          onPointerDown={role === "client" ? onPointerDown : undefined}
          onPointerUp={role === "client" ? onPointerUp : undefined}
          onPointerCancel={role === "client" ? onPointerCancel : undefined}
          onDoubleClick={role === "client" ? onDoubleClick : undefined}
          onKeyDown={role === "client" ? onKey : undefined}
          onKeyUp={role === "client" ? onKey : undefined}
          onBlur={() => releaseAllKeys()}
          onContextMenu={(e) => e.preventDefault()}
        >
          <video ref={videoRef} playsInline autoPlay muted />
          <div className="capture-layer" style={{ cursor: cursorStyle }} />
          {!connected && (
            <div className="hint">
              {role === "host" ? (
                <>
                  Start host mode and choose a screen/window to share.
                  <div style={{ marginTop: 12 }}>
                    Share the Host ID shown above with your client.
                  </div>
                </>
              ) : (
                <>
                  Enter a Host ID and connect to the host session.
                  <div style={{ marginTop: 12 }}>
                    Make sure the signaling URL is correct and the host is running.
                  </div>
                </>
              )}
            </div>
          )}
        </div>
 
        {chatOpen && (
          <aside className="drawer">
            <h3>Chat</h3>
            <div className="chat-log">
              {chatLines.map((l, i) => (
                <div key={i} className="chat-row">
                  <div className="chat-meta">{l.who}</div>
                  <div>{l.text}</div>
                </div>
              ))}
            </div>
            <div className="chat-input-row">
              <input
                value={chatDraft}
                onChange={(e) => setChatDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") sendChatNow();
                }}
                placeholder="Message…"
              />
              <button type="button" onClick={sendChatNow}>
                Send
              </button>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
 