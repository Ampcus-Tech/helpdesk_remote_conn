import logo from "../assets/logo.png";
import { SessionMode } from "../services/sessionManager";

interface LandingScreenProps {
  onSetMode: (mode: SessionMode) => void;
  onStartHost: () => void;
}

export default function LandingScreen({ onSetMode, onStartHost }: LandingScreenProps) {
  return (
    <div className="landing-screen" style={{ height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center' }}>
      <img src={logo} alt="Logo" style={{ width: '150px', height: '150px', marginBottom: '30px', filter: 'drop-shadow(0 10px 15px rgba(0,0,0,0.1))', borderRadius: '24px' }} />
      <h1 style={{ marginBottom: '40px' }}>Remote Helpdesk</h1>
      <div style={{ display: 'flex', gap: '20px' }}>
        <button style={{ padding: '20px 40px', fontSize: '18px' }} onClick={() => onSetMode("client")}>
          Client Mode
        </button>
        <button className="secondary" style={{ padding: '20px 40px', fontSize: '18px' }} onClick={onStartHost}>
          Host Mode
        </button>
      </div>
      <p style={{ marginTop: '20px', color: '#666' }}>Choose your role to get started.</p>
    </div>
  );
}
