import React, { useState, useRef } from "react";
import { sessionManager } from "../services/sessionManager";

interface ChatPanelProps {
  lines: { who: string; text: string; fileOffer?: { id: string; name: string; size: number } }[];
  onSendChat: (text: string) => void;
  onSendFile: (file: File) => void;
  onRespondFile: (id: string, accept: boolean) => void;
  fileProgress?: { name: string; progress: number; total: number; direction: "send" | "recv" };
  disabled?: boolean;
  onFocus?: () => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ 
  lines, 
  onSendChat, 
  onSendFile, 
  onRespondFile,
  fileProgress,
  disabled,
  onFocus
}) => {
  const [draft, setDraft] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    if (!draft.trim() || disabled) return;
    onSendChat(draft);
    setDraft("");
  };

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onSendFile(file);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <aside className="drawer chat-panel">
      <div className="chat-header">
        <h3>Chat & Files</h3>
      </div>
      
      <div className="chat-log">
        {lines.map((l, i) => (
          <div key={i} className={`chat-row ${l.who === "You" ? "own" : l.who === "SYSTEM" ? "system" : ""}`}>
            <div className="chat-meta">{l.who}</div>
            <div className="chat-body">
              {l.text}
              {l.fileOffer && (
                <div className="file-offer">
                  <p>Incoming file: <strong>{l.fileOffer.name}</strong> ({(l.fileOffer.size / 1024).toFixed(1)} KB)</p>
                  <div className="offer-actions">
                    <button className="small accept" onClick={() => onRespondFile(l.fileOffer!.id, true)}>Accept</button>
                    <button className="small secondary" onClick={() => onRespondFile(l.fileOffer!.id, false)}>Reject</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {fileProgress && (
        <div className="file-progress-overlay">
          <div className="progress-info">
            <span>{fileProgress.direction === "send" ? "Sending" : "Receiving"} {fileProgress.name}...</span>
            <span>{Math.round((fileProgress.progress / fileProgress.total) * 100)}%</span>
          </div>
          <div className="progress-bar-bg">
            <div className="progress-bar-fg" style={{ width: `${(fileProgress.progress / fileProgress.total) * 100}%` }}></div>
          </div>
        </div>
      )}

      <div className="chat-input-row">
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          onChange={onFileChange}
          disabled={disabled}
        />
        <button 
          className="icon-button" 
          title="Send File" 
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
        >
          📎
        </button>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSend();
          }}
          onFocus={() => {
            onFocus?.();
            sessionManager.setInputHelperActive(false).catch(() => {});
          }}
          onBlur={() => {
            sessionManager.setInputHelperActive(true).catch(() => {});
          }}
          placeholder={disabled ? "Connecting..." : "Message…"}
          disabled={disabled}
        />
        <button className="primary" type="button" onClick={handleSend} disabled={disabled || !draft.trim()}>
          Send
        </button>
      </div>
    </aside>
  );
};

export default ChatPanel;
