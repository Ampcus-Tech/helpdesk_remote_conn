import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { ask, message } from "@tauri-apps/plugin-dialog";
import { invoke } from "@tauri-apps/api/core";
import { MessageType } from "./protocol";
import { pointerToVideoFrame } from "./webrtc/coords";
import { mapKeyboardEvent } from "./webrtc/keyboard";
import { sessionManager, SessionMode } from "./services/sessionManager";

import HostPanel from "./components/HostPanel";
import ClientPanel from "./components/ClientPanel";
import ChatPanel from "./components/ChatPanel";
import LandingScreen from "./components/LandingScreen";

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

function normalizeDialogPath(path: string): string {
  if (!path.startsWith("file://")) return path;
  try {
    const url = new URL(path);
    // URL pathname is percent-encoded and may include leading slash on Windows drive paths.
    let normalized = decodeURIComponent(url.pathname);
    if (/^\/[A-Za-z]:\//.test(normalized)) {
      normalized = normalized.slice(1);
    }
    return normalized;
  } catch {
    return path;
  }
}

export default function App() {
  const [mode, setMode] = useState<SessionMode>("idle");
  const [hostId, setHostId] = useState("");
  const [status, setStatus] = useState("Idle");
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [chatLines, setChatLines] = useState<{ who: string; text: string; fileOffer?: { id: string; name: string; size: number } }[]>([]);
  const [fileProgress, setFileProgress] = useState<{ name: string; progress: number; total: number; direction: "send" | "recv" } | null>(null);
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
  const lastProgressUpdate = useRef(0);
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

  const disconnect = useCallback(async () => {
    releaseAllKeys();
    setHostWarning(null);
    if (moveTimer.current != null) {
      window.clearTimeout(moveTimer.current);
      moveTimer.current = null;
    }
    moveArmed.current = false;
    lastPointer.current = null;
 
    if (mode === "client") {
      await sessionManager.stopClient();
    } else if (mode === "host") {
      await sessionManager.stopHost();
    }
 
    const v = videoRef.current;
    if (v) v.srcObject = null;
 
    setConnected(false);
    setConnecting(false);
    setStatus("Disconnected");
    setMode("idle");
    setFileProgress(null);
  }, [mode, releaseAllKeys]);

  useEffect(() => {
    sessionManager.setEvents({
      onStatusChange: setStatus,
      onHostIdGenerated: setHostId,
      onConnected: () => {
        setConnected(true);
        setConnecting(false);
      },
      onDisconnected: async (reason) => {
        setStatus(reason || "Disconnected");
        const currentMode = mode;
        disconnect();
        if (currentMode === "host") {
          await message("Client has disconnected the connection.", { title: "Disconnection", kind: "info" });
        } else if (currentMode === "client") {
          await message("Host has disconnected the connection.", { title: "Disconnection", kind: "info" });
        }
      },
      onChatReceived: (who, text) => {
        setChatLines((prev) => [...prev, { who, text }]);
      },
      onVideoStream: (stream) => {
        const v = videoRef.current;
        if (v) {
          v.srcObject = stream;
          void v.play().catch(() => { });
        }
      },
      onCursorChange: setCursorName,
      onHostWarning: setHostWarning,
      onHostInfo: setRemoteOS,
      onFileOffer: (id, name, size) => {
        // Ensure the receiver can see the Accept/Reject UI (it lives in ChatPanel).
        setChatOpen(true);
        const sender = mode === "host" ? "Client" : "Host";
        setChatLines((prev) => [
          ...prev,
          { who: sender, text: `Incoming file offer.`, fileOffer: { id, name, size } },
        ]);
      },
      onFileProgress: (name, progress, total, direction) => {
        const now = Date.now();
        if (now - lastProgressUpdate.current > 100 || progress === total) {
          lastProgressUpdate.current = now;
          setFileProgress({ name, progress, total, direction });
        }
      },
      onFileDone: (name, _path, direction) => {
        setFileProgress(null);
        setChatLines((prev) => [...prev, { who: "SYSTEM", text: `${direction === "send" ? "Sent" : "Received"} ${name} successfully.` }]);
      }
    });
  }, [disconnect, mode]);

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
    if (connected) {
      sessionManager.sendChat(text);
      // Host receives its own chat back via host event stream, so avoid double-appending.
      if (mode !== "host") {
        setChatLines((prev) => [...prev, { who: "You", text }]);
      }
    }
  };

  const sendFileNow = async (file?: File) => {
    if (mode === "client" && connected) {
      if (!file) return;
      setChatLines((prev) => [...prev, { who: "You", text: `Offering file: ${file.name}` }]);
      await sessionManager.sendFile(file, (p) => {
        setFileProgress({ name: file.name, progress: p, total: file.size, direction: "send" });
      });
    } else if (mode === "host" && connected) {
      // In host mode, we use Tauri to pick a file path
      const { open } = await import("@tauri-apps/plugin-dialog");
      const path = await open({
        multiple: false,
        directory: false,
      });
      if (path && typeof path === "string") {
        setChatLines((prev) => [...prev, { who: "You", text: `Offering file: ${path.split(/[/\\]/).pop()}` }]);
        await sessionManager.sendFile(path, () => { });
      }
    }
  };

  const respondFileNow = async (id: string, accept: boolean) => {
    if (mode === "client" && connected) {
      let savePath: string | null = null;
      if (accept) {
        const { save } = await import("@tauri-apps/plugin-dialog");
        const offer = chatLines.find(l => l.fileOffer?.id === id)?.fileOffer;
        savePath = await save({
          defaultPath: offer?.name
        });
        if (!savePath) return; // Cancelled
        savePath = normalizeDialogPath(savePath);
      }
      sessionManager.respondToFileOffer(id, accept, savePath || undefined);
      setChatLines((prev) => prev.map(l => l.fileOffer?.id === id ? { ...l, fileOffer: undefined, text: l.text + (accept ? " (Accepted)" : " (Rejected)") } : l));
    } else if (mode === "host" && connected) {
      let savePath: string | null = null;
      if (accept) {
        const { save } = await import("@tauri-apps/plugin-dialog");
        const offer = chatLines.find(l => l.fileOffer?.id === id)?.fileOffer;
        savePath = await save({
          defaultPath: offer?.name
        });
        if (!savePath) return; // Cancelled
        savePath = normalizeDialogPath(savePath);
      }
      sessionManager.respondToFileOffer(id, accept, savePath || undefined);
      setChatLines((prev) => prev.map(l => l.fileOffer?.id === id ? { ...l, fileOffer: undefined, text: l.text + (accept ? " (Accepted)" : " (Rejected)") } : l));
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

  const modeRef = useRef(mode);
  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

  useEffect(() => {
    let unlistenFn: (() => void) | null = null;

    const setup = async () => {
      const win = getCurrentWindow();
      unlistenFn = await win.onCloseRequested(async (event) => {
        if (modeRef.current !== "idle") {
          event.preventDefault();
          const confirmed = await ask(
            "An active connection is running. Are you sure you want to disconnect and exit?",
            { title: "Confirm Exit", kind: "warning" }
          );
          if (confirmed) {
            // Send disconnect message before disconnecting
            if (modeRef.current === "client") {
              const sess = sessionManager.getActiveSession();
              if (sess?.channels.ctrl?.readyState === "open") {
                try {
                  sess.channels.ctrl.send(JSON.stringify({ type: MessageType.DISCONNECT }));
                } catch (e) {
                  console.error("Failed to send disconnect message:", e);
                }
              }
            } else if (modeRef.current === "host") {
              await invoke("send_host_command", {
                cmd: JSON.stringify({ type: "disconnect" })
              });
            }
            
            await disconnect();
            await win.destroy();
          }
        }
      });
    };

    setup();

    return () => {
      if (unlistenFn) unlistenFn();
    };
  }, [disconnect]);

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
        <LandingScreen onSetMode={setMode} onStartHost={startHost} />
      ) : (
        <div style={{ flex: 1, position: 'relative', display: 'flex' }}>
          <button
            style={{ 
              position: 'absolute', 
              top: 10, 
              left: 10, 
              zIndex: 100, 
              padding: '6px 12px', 
              fontSize: '12px' 
            }}
            onClick={disconnect}
          >
            Back to Menu
          </button>

          {mode === "host" ? (
            <HostPanel
              hostId={hostId}
              status={status}
              running={mode === "host"}
              onStart={startHost}
              onStop={disconnect}
              chatOpen={chatOpen}
              onToggleChat={() => setChatOpen(!chatOpen)}
              warning={hostWarning}
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
              chatOpen={chatOpen}
              onToggleChat={() => setChatOpen(!chatOpen)}
            />
          )}

          {chatOpen && (
            <ChatPanel
              lines={chatLines}
              onSendChat={sendChatNow}
              onSendFile={sendFileNow}
              onRespondFile={respondFileNow}
              fileProgress={fileProgress || undefined}
              disabled={!connected}
              mode={mode === "host" ? "host" : "client"}
            />
          )}
        </div>
      )}
    </div>
  );
}