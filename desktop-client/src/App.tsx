import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageType } from "./protocol";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { pointerToVideoFrame } from "./webrtc/coords";
import { mapKeyboardEvent } from "./webrtc/keyboard";
import { sessionManager, SessionMode } from "./services/sessionManager";
import { confirm, open, save } from "@tauri-apps/plugin-dialog";
import { invoke } from "@tauri-apps/api/core";

import HostPanel from "./components/HostPanel";
import ClientPanel from "./components/ClientPanel";
import ChatPanel from "./components/ChatPanel";
import LandingScreen from "./components/LandingScreen";
import AgentLoginPanel from "./components/AgentLoginPanel";

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

function formatFileSize(size: number): string {
  if (!isFinite(size)) return `${size} bytes`;
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} bytes`;
}

export default function App() {
  const BACKEND_URL = (import.meta.env.VITE_BACKEND_URL || "http://localhost:8080").replace(/\/+$/, "");
  const [mode, setMode] = useState<SessionMode>("idle");
  const [hostId, setHostId] = useState("");
  const [sessionPassword, setSessionPassword] = useState("");
  const [status, setStatus] = useState("Idle");
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [chatLines, setChatLines] = useState<{ who: string; text: string; fileOffer?: { id: string; name: string; size: number } }[]>([]);
  const [fileProgress, setFileProgress] = useState<{ name: string; progress: number; total: number; direction: "send" | "recv" } | null>(null);
  const [cursorName, setCursorName] = useState("arrow");
  const [remoteOS, setRemoteOS] = useState<string | null>(null);
  const [isAgentAuthenticated, setIsAgentAuthenticated] = useState(false);
  const [agentUsername, setAgentUsername] = useState("");
  const [agentPassword, setAgentPassword] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
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

  const loginAgent = useCallback(async () => {
    if (!agentUsername.trim() || !agentPassword.trim()) {
      setStatus("Please enter username and password");
      return;
    }
    setLoggingIn(true);
    setStatus("Authenticating agent...");
    try {
      const resp = await fetch(`${BACKEND_URL}/api/auth/agent/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: agentUsername.trim(),
          password: agentPassword
        }),
      });

      if (!resp.ok) {
        const errorData = await resp.json().catch(() => null);
        console.error("Login failed response:", errorData);
        const errorMessage = errorData?.message || errorData?.error || `Login failed (${resp.status})`;
        throw new Error(errorMessage);
      }

      const data = await resp.json();
      console.log("Login successful:", data);
      localStorage.setItem("agent_auth_token", data.token || "");
      localStorage.setItem("agent_refresh_token", data.refreshToken || "");
      localStorage.setItem("agent_username", data.username || agentUsername.trim());
      setIsAgentAuthenticated(true);
      setStatus("Agent authorized. Enter host connection details.");
    } catch (error) {
      setIsAgentAuthenticated(false);
      setStatus(error instanceof Error ? error.message : "Agent login failed");
    } finally {
      setLoggingIn(false);
    }
  }, [BACKEND_URL, agentUsername, agentPassword]);

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
    setIsAgentAuthenticated(false);
    setAgentPassword("");
    setFileProgress(null);
  }, [mode, releaseAllKeys]);

  useEffect(() => {
    sessionManager.setEvents({
      onStatusChange: setStatus,
      onHostIdGenerated: setHostId,
      onSessionPasswordGenerated: setSessionPassword,
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
          {
            who: sender,
            text: `Incoming file offer: ${name} (${formatFileSize(size)})`,
            fileOffer: { id, name, size }
          },
        ]);
      },
      onFileProgress: (name, progress, total, direction) => {
        const now = Date.now();
        if (now - lastProgressUpdate.current > 100 || progress === total) {
          lastProgressUpdate.current = now;
          setFileProgress({ name, progress, total, direction });
        }
      },
      onFileDone: (name, _path, direction, size) => {
        setFileProgress(null);
        setChatLines((prev) => [
          ...prev,
          {
            who: "SYSTEM",
            text: `${direction === "send" ? "Sent" : "Received"} ${name} successfully${typeof size === "number" ? ` (${formatFileSize(size)})` : ""}.`
          }
        ]);
      }
    });
  }, [disconnect, mode]);

  const startHost = async () => {
    setMode("host");
    setChatLines([]);
    await sessionManager.startHost();
  };

  const startClient = async () => {
    if (!isAgentAuthenticated) {
      setStatus("Please login as agent first.");
      return;
    }
    const id = hostId.trim();
    const pwd = sessionPassword.trim();
    if (!id) {
      setStatus("Enter a connection ID");
      return;
    }
    if (!pwd) {
      setStatus("Enter the password");
      return;
    }
    if (pwd.length !== 6) {
      setStatus("Password must be 6 digits");
      return;
    }
    setMode("client");
    setConnecting(true);
    setChatLines([]);
    await sessionManager.startClient(id, pwd);
    const sess = sessionManager.getActiveSession();
    if (sess) {
      ctrlSendRef.current = (json) => {
        if (sess.channels.ctrl.readyState === "open") {
          sess.channels.ctrl.send(json);
        }
      };
    }
  };

  const chooseClientMode = useCallback(async () => {
    setMode("client");
    setConnected(false);
    setConnecting(false);
    setHostId("");
    setSessionPassword("");
    setIsAgentAuthenticated(false);
    setStatus("Please login as agent");
  }, []);

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
      const success = await sessionManager.sendFile(file, (p) => {
        setFileProgress({ name: file.name, progress: p, total: file.size, direction: "send" });
      });
      if (!success) {
        setStatus("File transfer failed or was not accepted.");
        setChatLines((prev) => [...prev, { who: "SYSTEM", text: `File transfer failed: ${file.name}` }]);
        setFileProgress(null);
      }
    } else if (mode === "host" && connected) {
      // In host mode, we use Tauri to pick a file path
      // const { open } = await import("@tauri-apps/plugin-dialog");
      const path = await open({
        multiple: false,
        directory: false,
      });
      if (path && typeof path === "string") {
        const fileName = path.split(/[/\\]/).pop() || path;
        setChatLines((prev) => [...prev, { who: "You", text: `Offering file: ${fileName}` }]);
        const success = await sessionManager.sendFile(path, () => { });
        if (!success) {
          setStatus(`File transfer failed: ${fileName}`);
          setChatLines((prev) => [...prev, { who: "SYSTEM", text: `File transfer failed: ${fileName}` }]);
        }
      }
    }
  };

  const respondFileNow = async (id: string, accept: boolean) => {
    if (mode === "client" && connected) {
      let savePath: string | null = null;
      if (accept) {
        // const { save } = await import("@tauri-apps/plugin-dialog");
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
        // const { save } = await import("@tauri-apps/plugin-dialog");
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

  // Use a ref to keep the close handler stable without re-registering
  const stateRef = useRef({ mode, disconnect });
  useEffect(() => {
    stateRef.current = { mode, disconnect };
  }, [mode, disconnect]);

  useEffect(() => {
    let unlisten: (() => void) | null = null;

    const setup = async () => {
      unlisten = await getCurrentWindow().onCloseRequested(async (event) => {
        // Always prevent default so we have control
        event.preventDefault();

        const { mode: currentMode, disconnect: currentDisconnect } = stateRef.current;
        console.log("Close requested. Current mode:", currentMode);

        // Show warning for ANY active session (Host or Client)
        if (currentMode === "host" || currentMode === "client") {
          const confirmed = await confirm(
            "A session is currently active. Do you want to disconnect and exit?",
            { title: "Remote Desktop", kind: "warning" }
          );

          if (!confirmed) {
            console.log("Close cancelled by user");
            return;
          }
        }

        console.log("Proceeding with cleanup and exit...");

        try {
          // Add a 1.5s timeout so the window closes even if cleanup hangs
          await Promise.race([
            currentDisconnect(),
            new Promise((resolve) => setTimeout(resolve, 1500))
          ]);
        } catch (e) {
          console.error("Cleanup failed:", e);
        } finally {
          await invoke("close_app");
        }
      });
    };

    setup();

    return () => {
      if (unlisten) unlisten();
    };
  }, []); // Run exactly once on mount

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
        <LandingScreen onStartHost={startHost} onStartClientMode={chooseClientMode} />
      ) : (
        <div style={{ flex: 1, position: 'relative', display: 'flex' }}>
          <button
            style={{ position: 'absolute', top: 10, left: 10, zIndex: 100, padding: '6px 12px', fontSize: '12px' }}
            onClick={disconnect}
          >
            Back to Menu
          </button>

          {mode === "host" ? (
            <HostPanel
              hostId={hostId}
              sessionPassword={sessionPassword}
              status={status}
              running={mode === "host"}
              onStart={startHost}
              onStop={disconnect}
              chatOpen={chatOpen}
              onToggleChat={() => setChatOpen(!chatOpen)}
              warning={hostWarning}
            />
          ) : !isAgentAuthenticated ? (
            <AgentLoginPanel
              username={agentUsername}
              password={agentPassword}
              status={status}
              loggingIn={loggingIn}
              onUsernameChange={setAgentUsername}
              onPasswordChange={setAgentPassword}
              onLogin={loginAgent}
            />
          ) : (
            <ClientPanel
              hostId={hostId}
              setHostId={setHostId}
              sessionPassword={sessionPassword}
              setSessionPassword={setSessionPassword}
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