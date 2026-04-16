import React from "react";

interface ClientPanelProps {
  hostId: string;
  setHostId: (id: string) => void;
  status: string;
  connecting: boolean;
  connected: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
  videoRef: React.RefObject<HTMLVideoElement>;
  wrapRef: React.RefObject<HTMLDivElement>;
  cursorStyle: string;
  onPointerMove: (e: React.PointerEvent) => void;
  onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void;
  onPointerUp: (e: React.PointerEvent) => void;
  onPointerCancel: () => void;
  onDoubleClick: (e: React.MouseEvent) => void;
  onKey: (e: React.KeyboardEvent) => void;
  releaseAllKeys: () => void;
  onBack: () => void;
}

export const ClientPanel: React.FC<ClientPanelProps> = ({
  hostId,
  setHostId,
  status,
  connecting,
  connected,
  onConnect,
  onDisconnect,
  videoRef,
  wrapRef,
  cursorStyle,
  onPointerMove,
  onPointerDown,
  onPointerUp,
  onPointerCancel,
  onDoubleClick,
  onKey,
  releaseAllKeys,
  onBack,
}) => {
  React.useEffect(() => {
    if (connected && typeof navigator !== "undefined" && "keyboard" in navigator) {
      const kb = (navigator as any).keyboard;
      if (kb && typeof kb.lock === "function") {
        kb.lock().catch((err: any) => {
          console.warn("Keyboard Lock failed:", err);
        });
      }
    }
    return () => {
      if (typeof navigator !== "undefined" && "keyboard" in navigator) {
        const kb = (navigator as any).keyboard;
        if (kb && typeof kb.unlock === "function") {
          kb.unlock();
        }
      }
    };
  }, [connected]);

  return (
    <div className="client-panel">
      <div className="toolbar">
        <button type="button" className="secondary" onClick={onBack} style={{ marginRight: '8px' }}>
          Back
        </button>
        <input
          type="text"
          placeholder="Enter Host ID"
          value={hostId}
          disabled={connecting || connected}
          onChange={(e) => setHostId(e.target.value.replace(/\D/g, "").slice(0, 8))}
        />
        <button type="button" disabled={connecting || connected || !hostId.trim()} onClick={onConnect}>
          Connect
        </button>
        <button type="button" className="secondary" disabled={!connected && !connecting} onClick={onDisconnect}>
          Disconnect
        </button>


        <div className="status" style={{ marginLeft: "auto" }}>{status}</div>
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
          onBlur={releaseAllKeys}
          onContextMenu={(e) => e.preventDefault()}
        >
          <video ref={videoRef} playsInline autoPlay muted />
          <div className="capture-layer" style={{ cursor: cursorStyle }} />
          {!connected && (
            <div className="hint">
              {connecting ? "Handshaking with remote host..." : "Enter a 6-digit Host ID to start a remote control session."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ClientPanel;
