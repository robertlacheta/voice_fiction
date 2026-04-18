import { useState, useEffect, useRef } from 'react';
import './App.css';

interface LogEntry {
  id: number;
  text: string;
  type: 'system' | 'action' | 'dialogue';
}

function App() {
  const [hp, setHp] = useState(100);
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [avatarError, setAvatarError] = useState(false);

  const [sceneDescription, setSceneDescription] = useState(
    "You're in a dimly lit tavern. A burly bartender looks up at you. The air is thick with the smell of roasted meat and old ale."
  );

  const [logs, setLogs] = useState<LogEntry[]>([
    { id: 1, text: "Thalia enters the tavern.", type: 'system' },
    { id: 2, text: "Thalia: Heard any good rumors lately, barkeep?", type: 'action' },
    { id: 3, text: "Bartender: Aye, heard there's trouble in the woods to the east. Bandits, maybe worse...", type: 'dialogue' },
  ]);

  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollTop = logEndRef.current.scrollHeight;
    }
  }, [logs]);

  const handleMicClick = () => {
    if (isProcessing) return;

    if (!isRecording) {
      setIsRecording(true);
    } else {
      setIsRecording(false);
      setIsProcessing(true);

      setTimeout(() => {
        const newAction: LogEntry = {
          id: Date.now(),
          text: "Thalia: Tell me more about these bandits.",
          type: 'action'
        };
        setLogs(prev => [...prev, newAction]);
        setIsProcessing(false);

        setTimeout(() => {
          setLogs(prev => [...prev, {
            id: Date.now() + 1,
            text: "Bartender: They've been raiding caravans near the old bridge. The local guard is spread thin.",
            type: 'dialogue'
          }]);
          setSceneDescription("The bartender leans in closer, his voice dropping to a whisper. He points a calloused finger toward a map tacked to the wall.");
          setHp(prev => Math.max(0, prev - 5));
        }, 1200);
      }, 1500);
    }
  };

  return (
    <div className="game-window">
      {/* Left Column: HUD */}
      <aside className="panel hud-left">
        <div className="avatar-container">
          {!avatarError ? (
            <img
              src="/avatar.png"
              alt="Avatar"
              className="avatar-img"
              onError={() => setAvatarError(true)}
            />
          ) : (
            <span className="avatar-placeholder">[ PORTRAIT ]</span>
          )}
        </div>

        <div className="player-info">
          <div className="player-name-row">
            <span className="player-name">Thalia</span>
          </div>

          <div className="stat-bars">
            <div className="bar-row">
              <div className="bar-container">
                <div className="bar-fill-hp" style={{ width: `${hp}%` }}></div>
              </div>
            </div>
          </div>
        </div>
        <div className="game-logo-container">
          <img
            src="/logo.png"
            alt="Voice Fiction Logo"
            className="game-logo"
            onError={(e) => (e.currentTarget.style.display = 'none')}
          />
        </div>
      </aside>

      {/* Center Column: Illustration + Scene Description + Mic */}
      <main className="center-column">
        <section className="illustration-area">
          <img
            src="/tavern_interior.png"
            alt="Tavern Interior"
            className="illustration-img"
            onError={(e) => (e.currentTarget.style.display = 'none')}
          />
        </section>

        <section className="chat-area">
          <p>{sceneDescription}</p>
        </section>

        <section className="mic-area">
          <button
            className={`mic-button ${isRecording ? 'recording' : ''} ${isProcessing ? 'processing' : ''}`}
            onClick={handleMicClick}
            disabled={isProcessing}
          >
            <div className="mic-icon"></div>
          </button>
        </section>
      </main>

      {/* Right Column: Game Log */}
      <aside className="panel log-column">
        <div className="log-header">■ GAME LOG ■</div>
        <div className="log-content" ref={logEndRef}>
          {logs.map((log) => (
            <div key={log.id} className={`log-entry ${log.type}`}>
              {log.text}
            </div>
          ))}
          {isProcessing && <div className="log-entry system">...listening...</div>}
        </div>
      </aside>
    </div>
  );
}

export default App;
