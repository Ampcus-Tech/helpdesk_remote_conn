import React from "react";

interface HostPanelProps {
  hostId: string;
  status: string;
  running: boolean;
  onStart: () => void;
  onStop: () => void;
  warning?: string | null;
  onBack: () => void;
}

export const HostPanel: React.FC<HostPanelProps> = ({ hostId, status, running, onStart, onStop, warning, onBack }) => {
  return (
    <div className="host-panel" style={{ padding: '20px', textAlign: 'center', position: 'relative' }}>
      <button 
        className="secondary" 
        onClick={onBack} 
        style={{ 
          position: 'absolute', 
          top: '10px', 
          left: '10px', 
          padding: '4px 12px', 
          fontSize: '12px' 
        }}
      >
        Back
      </button>
      {warning && (
        <div style={{ 
          background: '#fff4ce', 
          border: '1px solid #ffb900', 
          padding: '10px', 
          marginBottom: '15px', 
          borderRadius: '4px',
          color: '#333',
          fontSize: '13px'
        }}>
          ⚠️ <strong>Note:</strong> {warning}
        </div>
      )}
      <h2>Host Desktop</h2>
      <p style={{ color: '#666', marginBottom: '20px' }}>
        Share your screen with a remote professional.
      </p>
      
      <div className="id-container" style={{ 
        background: '#f0f4f8', 
        padding: '30px', 
        borderRadius: '12px',
        border: '2px dashed #0078d4',
        margin: '0 auto 20px',
        maxWidth: '300px'
      }}>
        <div style={{ fontSize: '14px', color: '#555', marginBottom: '8px', textTransform: 'uppercase' }}>Your Host ID</div>
        <div style={{ fontSize: '32px', fontWeight: 'bold', letterSpacing: '4px', color: '#0078d4' }}>
          {hostId || "------"}
        </div>
      </div>

      <div style={{ marginBottom: '20px' }}>
        {!running ? (
          <button onClick={onStart} style={{ padding: '12px 30px', fontSize: '16px' }}>
            Start Hosting
          </button>
        ) : (
          <button className="secondary" onClick={onStop} style={{ padding: '12px 30px', fontSize: '16px' }}>
            Stop Hosting
          </button>
        )}
      </div>

      <div className="host-status" style={{ 
        padding: '10px', 
        background: running ? '#e6f4ea' : '#f8f9fa',
        borderRadius: '6px',
        fontSize: '14px',
        display: 'inline-block'
      }}>
        Status: <strong>{status}</strong>
      </div>

      {!running && (
        <div style={{ marginTop: '20px', fontSize: '13px', color: '#666', fontStyle: 'italic' }}>
          Note: This will execute the background host process on your PC.
        </div>
      )}
    </div>
  );
};

export default HostPanel;
