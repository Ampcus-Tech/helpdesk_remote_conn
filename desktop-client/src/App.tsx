import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageType } from "./protocol";
import { pointerToVideoFrame } from "./webrtc/coords";
import { mapKeyboardEvent } from "./webrtc/keyboard";
import { sessionManager, SessionMode } from "./services/sessionManager";
 
import HostPanel from "./components/HostPanel";
import ClientPanel from "./components/ClientPanel";
import ChatPanel from "./components/ChatPanel";
 
const MOUSE_MOVE_INTERVAL_MS = 1000 / 60;
const DC_BUFFER_CAP = 24 * 1024;
 
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
 
export default function App() {
  const [mode, setMode] = useState<SessionMode>("idle");
  const [hostId, setHostId] = useState("");
  const [status, setStatus] = useState("Idle");
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [chatLines, setChatLines] = useState<{ who: string; text: string }[]>([]);
  const [cursorName, setCursorName] = useState("arrow");
  const [remoteOS, setRemoteOS] = useState<string | null>(null);
  const swapModifiers = useMemo(() => {
    const localIsMac = typeof navigator !== 'undefined' && /Mac/.test(navigator.platform);
    const remoteIsMac = remoteOS === "Darwin";
    // Swap if one is Mac and the other is not (Windows/Linux)
    return localIsMac !== remoteIsMac;
  }, [remoteOS]);
  const [hostWarning, setHostWarning] = useState<string | null>(null);
 
  const videoRef = useRef<HTMLVideoElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const ctrlSendRef = useRef<((json: string) => void) | null>(null);
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
    setHostWarning(null);
    if (moveTimer.current != null) {
      window.clearTimeout(moveTimer.current);
      moveTimer.current = null;
    }
    moveArmed.current = false;
    lastPointer.current = null;
 
    if (mode === "client") {
        sessionManager.stopClient();
    } else if (mode === "host") {
        sessionManager.stopHost();
    }
 
    const v = videoRef.current;
    if (v) v.srcObject = null;
   
    setConnected(false);
    setConnecting(false);
    setStatus("Disconnected");
    setMode("idle");
  }, [mode, releaseAllKeys]);
 
  useEffect(() => {
    sessionManager.setEvents({
      onStatusChange: setStatus,
      onHostIdGenerated: setHostId,
      onConnected: () => {
        setConnected(true);
        setConnecting(false);
      },
      onDisconnected: (reason) => {
        setStatus(reason || "Disconnected");
        disconnect();
      },
      onChatReceived: (who, text) => {
        setChatLines((prev) => [...prev, { who, text }]);
      },
      onVideoStream: (stream) => {
        const v = videoRef.current;
        if (v) {
          v.srcObject = stream;
          void v.play().catch(() => {});
        }
      },
      onCursorChange: setCursorName,
      onHostWarning: setHostWarning,
      onHostInfo: setRemoteOS,
    });
  }, [disconnect]);
 
  const startHost = async () => {
    setMode("host");
    setChatLines([]);
    await sessionManager.startHost();
  };
 
  const startClient = async () => {
    const id = hostId.trim();
    if (!id) {
      setStatus("Enter a host ID");
      return;
    }
    setMode("client");
    setConnecting(true);
    setChatLines([]);
    await sessionManager.startClient(id);
    const sess = sessionManager.getActiveSession();
    if (sess) {
        ctrlSendRef.current = (json) => {
            if (sess.channels.ctrl.readyState === "open") {
                sess.channels.ctrl.send(json);
            }
        };
    }
  };
 
  const sendChatNow = (text: string) => {
    if (mode === "client") {
        sessionManager.sendChat(text);
        setChatLines((prev) => [...prev, { who: "You", text }]);
    }
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
      const scroll_dy = -(dy === 0 ? 0 : Math.abs(dy) < 1 ? (dy > 0 ? 1 : -1) : Math.trunc(dy / 100) || (dy > 0 ? 1 : -1));
      const scroll_dx = dx === 0 ? 0 : Math.abs(dx) < 1 ? (dx > 0 ? 1 : -1) : Math.trunc(dx / 100) || (dx > 0 ? 1 : -1);
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
  }, [connected]);
 
  const onPointerMove = (e: React.PointerEvent) => {
    lastPointer.current = { x: e.clientX, y: e.clientY };
    if (moveArmed.current) return;
    moveArmed.current = true;
 
    const tick = () => {
      moveArmed.current = false;
      moveTimer.current = null;
 
      const video = videoRef.current;
      const sess = sessionManager.getActiveSession();
      const fn = ctrlSendRef.current;
      const pt = lastPointer.current;
      if (!video || !sess || !fn || !pt) return;
 
      const now = performance.now();
      if (now - lastMoveAt.current < MOUSE_MOVE_INTERVAL_MS) {
        moveTimer.current = window.setTimeout(tick, Math.max(0, MOUSE_MOVE_INTERVAL_MS - (now - lastMoveAt.current)));
        moveArmed.current = true;
        return;
      }
 
      const ch = sess.channels.ctrl;
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
    try { el.setPointerCapture(e.pointerId); } catch { /* ignore */ }
 
    const video = videoRef.current;
    if (!video || !ctrlSendRef.current) return;
    const mapped = pointerToVideoFrame(e.clientX, e.clientY, video);
    if (!mapped) return;
 
    if (e.button === 0) {
      buttonsDown.current.add("left");
      ctrlSendRef.current(JSON.stringify({ type: MessageType.MOUSE_CLICK, button: "left", pressed: true }));
    } else if (e.button === 2) {
      e.preventDefault();
      buttonsDown.current.add("right");
      ctrlSendRef.current(JSON.stringify({ type: MessageType.MOUSE_CLICK, button: "right", pressed: true }));
    }
  };
 
  const onPointerUp = (e: React.PointerEvent) => {
    if (!ctrlSendRef.current) return;
    if (e.button === 0 && buttonsDown.current.has("left")) {
      buttonsDown.current.delete("left");
      ctrlSendRef.current(JSON.stringify({ type: MessageType.MOUSE_CLICK, button: "left", pressed: false }));
    } else if (e.button === 2 && buttonsDown.current.has("right")) {
      e.preventDefault();
      buttonsDown.current.delete("right");
      ctrlSendRef.current(JSON.stringify({ type: MessageType.MOUSE_CLICK, button: "right", pressed: false }));
    }
  };
 
  const onPointerCancel = () => {
    if (!ctrlSendRef.current) return;
    if (buttonsDown.current.has("left")) {
      buttonsDown.current.delete("left");
      ctrlSendRef.current(JSON.stringify({ type: MessageType.MOUSE_CLICK, button: "left", pressed: false }));
    }
    if (buttonsDown.current.has("right")) {
      buttonsDown.current.delete("right");
      ctrlSendRef.current(JSON.stringify({ type: MessageType.MOUSE_CLICK, button: "right", pressed: false }));
    }
  };
 
  const onDoubleClick = (e: React.MouseEvent) => {
    const video = videoRef.current;
    if (!video || !ctrlSendRef.current) return;
    const mapped = pointerToVideoFrame(e.clientX, e.clientY, video);
    if (!mapped) return;
    if (e.button === 0) {
      ctrlSendRef.current(JSON.stringify({ type: MessageType.MOUSE_DOUBLE_CLICK, button: "left" }));
    } else if (e.button === 2) {
      ctrlSendRef.current(JSON.stringify({ type: MessageType.MOUSE_DOUBLE_CLICK, button: "right" }));
    }
  };
 
  const onKey = (e: React.KeyboardEvent) => {
    if (!ctrlSendRef.current) return;
    const mk = mapKeyboardEvent(e.nativeEvent, { swapModifiers });
    if (!mk) return;
    e.preventDefault();
    if (mk.pressed) pressedKeys.current.add(mk.key);
    else pressedKeys.current.delete(mk.key);
    ctrlSendRef.current(JSON.stringify({ type: MessageType.KEYBOARD, key: mk.key, pressed: mk.pressed }));
  };
 
  return (
    <div className="layout">
      {mode === "idle" ? (
        <div className="landing-screen" style={{ height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
          <h1 style={{ marginBottom: '40px' }}>Remote Helpdesk</h1>
          <div style={{ display: 'flex', gap: '20px' }}>
            <button style={{ padding: '20px 40px', fontSize: '18px' }} onClick={() => setMode("client")}>
              Client Mode
            </button>
            <button className="secondary" style={{ padding: '20px 40px', fontSize: '18px' }} onClick={startHost}>
              Host Mode
            </button>
          </div>
          <p style={{ marginTop: '20px', color: '#666' }}>Choose your role to get started.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', width: '100%', height: '100%' }}>
                {mode === "host" ? (
                    <HostPanel
                        hostId={hostId}
                        status={status}
                        running={mode === "host"}
                        onStart={startHost}
                        onStop={disconnect}
                        warning={hostWarning}
                        onBack={disconnect}
                    />
                ) : (
                    <ClientPanel
                        hostId={hostId}
                        setHostId={setHostId}
                        status={status}
                        connecting={connecting}
                        connected={connected}
                        onConnect={startClient}
                        onDisconnect={disconnect}
                        videoRef={videoRef}
                        wrapRef={wrapRef}
                        cursorStyle={cursorStyle}
                        onPointerMove={onPointerMove}
                        onPointerDown={onPointerDown}
                        onPointerUp={onPointerUp}
                        onPointerCancel={onPointerCancel}
                        onDoubleClick={onDoubleClick}
                        onKey={onKey}
                        releaseAllKeys={releaseAllKeys}
                        onBack={disconnect}
                    />
                )}
 
            {chatOpen && (
                <ChatPanel
                    lines={chatLines}
                    onSend={sendChatNow}
                    disabled={!connected && mode === "client"}
                />
            )}
        </div>
      )}
    </div>
  );
}