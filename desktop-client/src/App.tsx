import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageType } from "./protocol";
import { pointerToVideoFrame } from "./webrtc/coords";
import { mapKeyboardEvent } from "./webrtc/keyboard";
import { ActiveSession, sendChatLine, startSession } from "./webrtc/session";

const MOUSE_MOVE_INTERVAL_MS = 1000 / 90;
const DC_BUFFER_CAP = 48 * 1024;

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
  const [hostId, setHostId] = useState("");
  const { status, setStatus } = useStatus("Idle");
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [sessionAlive, setSessionAlive] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [chatLines, setChatLines] = useState<{ who: string; text: string }[]>([]);
  const [chatDraft, setChatDraft] = useState("");
  const [cursorName, setCursorName] = useState("arrow");

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
    sessionRef.current?.close();
    sessionRef.current = null;
    ctrlSendRef.current = null;
    chatRef.current = null;
    const v = videoRef.current;
    if (v) {
      v.srcObject = null;
    }
    setConnected(false);
    setSessionAlive(false);
    setConnecting(false);
    setStatus("Disconnected");
  }, [releaseAllKeys]);

  const appendChat = useCallback((who: string, text: string) => {
    setChatLines((prev) => [...prev, { who, text }]);
  }, []);

  const connect = useCallback(async () => {
    const id = hostId.trim();
    if (!id) {
      setStatus("Enter a host ID");
      return;
    }
    if (connecting || sessionAlive) return;

    setConnecting(true);
    setStatus("Connecting…");
    setChatLines([]);

    try {
      const s = await startSession(id, {
        onStatus: setStatus,
        onVideoStream: (stream) => {
          const v = videoRef.current;
          if (v) {
            v.srcObject = stream;
            void v.play().catch(() => {});
          }
          setStatus("Receiving video");
          setConnected(true);
        },
        onControlOpen: (send) => {
          ctrlSendRef.current = send;
        },
        onControlMessage: () => {},
        onCursorName: (name) => setCursorName(name),
        onChatText: (sender, text) => appendChat(sender === "Host" ? "Host" : sender, text),
        onDataChannelsReady: (ch) => {
          chatRef.current = ch.chat;
          setStatus("Session ready (chat/files)");
        },
        onSessionEnd: (reason) => {
          setStatus(reason);
          disconnect();
        },
      });
      sessionRef.current = s;
      setSessionAlive(true);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
      disconnect();
    } finally {
      setConnecting(false);
    }
  }, [appendChat, connecting, disconnect, hostId, sessionAlive]);

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
      const ch = sessionRef.current?.channels.ctrl;
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
    } else if (e.button === 2) {
      e.preventDefault();
      buttonsDown.current.add("right");
      sendCtrl({ type: MessageType.MOUSE_CLICK, button: "right", pressed: true });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (!ctrlSendRef.current) return;
    if (e.button === 0 && buttonsDown.current.has("left")) {
      buttonsDown.current.delete("left");
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
        <input
          type="text"
          placeholder="Host ID (6 digits)"
          value={hostId}
          disabled={connecting || sessionAlive}
          onChange={(e) => setHostId(e.target.value.replace(/\D/g, "").slice(0, 8))}
        />
        <button type="button" disabled={connecting || sessionAlive || !hostId.trim()} onClick={connect}>
          Connect
        </button>
        <button type="button" className="secondary" disabled={!sessionAlive} onClick={disconnect}>
          Disconnect
        </button>
        <button type="button" className="secondary" onClick={() => setChatOpen((v) => !v)}>
          {chatOpen ? "Hide chat" : "Show chat"}
        </button>
        <div className="status">{status}</div>
      </div>

      <div className="stage">
        <div
          ref={wrapRef}
          className="video-wrap"
          tabIndex={0}
          style={{ cursor: cursorStyle }}
          onPointerMove={onPointerMove}
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerCancel}
          onDoubleClick={onDoubleClick}
          onKeyDown={onKey}
          onKeyUp={onKey}
          onBlur={() => releaseAllKeys()}
          onContextMenu={(e) => e.preventDefault()}
        >
          <video ref={videoRef} playsInline autoPlay muted />
          <div className="capture-layer" style={{ cursor: cursorStyle }} />
          {!connected && (
            <div className="hint">
              Tauri + React viewer: enter Host ID, start <code>python signaling/server.py</code> and{" "}
              <code>python host/main.py</code>, then connect.
              <div style={{ marginTop: 12 }}>
                Configure <code>.env</code>: <code>VITE_SIGNALING_URL</code>, <code>VITE_ICE_SERVERS_JSON</code> (match{" "}
                <code>common/config.py</code>).
              </div>
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
