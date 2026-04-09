import React, { useState } from "react";

interface ChatPanelProps {
  lines: { who: string; text: string }[];
  onSend: (text: string) => void;
  disabled?: boolean;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ lines, onSend, disabled }) => {
  const [draft, setDraft] = useState("");

  const handleSend = () => {
    if (!draft.trim() || disabled) return;
    onSend(draft);
    setDraft("");
  };

  return (
    <aside className="drawer">
      <h3>Chat</h3>
      <div className="chat-log">
        {lines.map((l, i) => (
          <div key={i} className="chat-row">
            <div className="chat-meta">{l.who}</div>
            <div>{l.text}</div>
          </div>
        ))}
      </div>
      <div className="chat-input-row">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSend();
          }}
          placeholder={disabled ? "Connecting..." : "Message…"}
          disabled={disabled}
        />
        <button type="button" onClick={handleSend} disabled={disabled || !draft.trim()}>
          Send
        </button>
      </div>
    </aside>
  );
};

export default ChatPanel;
