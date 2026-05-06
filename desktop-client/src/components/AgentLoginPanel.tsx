import React from "react";

interface AgentLoginPanelProps {
  username: string;
  password: string;
  status: string;
  loggingIn: boolean;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onLogin: () => void;
}

const AgentLoginPanel: React.FC<AgentLoginPanelProps> = ({
  username,
  password,
  status,
  loggingIn,
  onUsernameChange,
  onPasswordChange,
  onLogin,
}) => {
  return (
    <div className="agent-login-panel">
      <h2>Agent Login (Client Mode)</h2>
      <p className="agent-login-subtitle">
        Login to authorize this client before connecting to a host.
      </p>

      <div className="agent-login-form">
        <input
          type="text"
          placeholder="Username or Email"
          value={username}
          disabled={loggingIn}
          onChange={(e) => onUsernameChange(e.target.value)}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          disabled={loggingIn}
          onChange={(e) => onPasswordChange(e.target.value)}
        />
        <button
          type="button"
          disabled={
            loggingIn ||
            !username.trim() ||
            !password.trim()
          }
          onClick={onLogin}
        >
          {loggingIn ? "Logging in..." : "Login as Agent"}
        </button>
      </div>

      <div className="agent-login-status">{status}</div>
    </div>
  );
};

export default AgentLoginPanel;
