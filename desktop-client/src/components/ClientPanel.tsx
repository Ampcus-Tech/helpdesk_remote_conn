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
  chatOpen: boolean;
  onToggleChat: () => void;
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
  chatOpen,
  onToggleChat
}) => {
  return (
    <div className="client-panel">
      <div className="toolbar">
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
        <button 
          type="button" 
          className={`secondary ${chatOpen ? 'active' : ''}`} 
          onClick={onToggleChat}
          title="Toggle Chat & Files"
        >
          {chatOpen ? "Hide Chat" : "Show Chat"}
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
