import { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';
import { useVoiceRecorder } from './useVoiceRecorder';

interface LogEntry {
  id: number;
  text: string;
  type: 'system' | 'action' | 'dialogue';
}

function App() {
  const PLAYER_ID = 'player_001';

  const [hp] = useState(100);
  const [avatarError, setAvatarError] = useState(false);

  const [logs, setLogs] = useState<LogEntry[]>([
    { id: 1, text: "Thalia enters the tavern.", type: 'system' },
    { id: 2, text: "Thalia: Heard any good rumors lately, barkeep?", type: 'action' },
    { id: 3, text: "Bartender: Aye, heard there's trouble in the woods to the east. Bandits, maybe worse...", type: 'dialogue' },
  ]);

  const [sceneDescription] = useState(
    "You're in a dimly lit tavern. A burly bartender looks up at you. The air is thick with the smell of roasted meat and old ale."
  );

  const onTranscript = useCallback((transcript: string) => {
    setLogs((prev) => [
      ...prev,
      { id: Date.now(), text: `Thalia: ${transcript}`, type: 'action' },
    ]);
  }, []);

  const { status, errorMessage, startRecording, stopRecording } =
    useVoiceRecorder(PLAYER_ID, onTranscript);

  const isRecording = status === 'recording';
  const isProcessing = status === 'processing';

  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollTop = logEndRef.current.scrollHeight;
    }
  }, [logs]);

  // Naciśnij i przytrzymaj = nagrywanie; puść = wyślij
  const handlePointerDown = () => {
    if (!isProcessing) void startRecording();
  };
  const handlePointerUp = () => {
    if (isRecording) stopRecording();
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
            id="mic-button"
            className={`mic-button ${isRecording ? 'recording' : ''} ${isProcessing ? 'processing' : ''} ${status === 'error' ? 'error' : ''}`}
            onPointerDown={handlePointerDown}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
            disabled={isProcessing}
            aria-label={isRecording ? 'Nagrywanie – puść aby wysłać' : isProcessing ? 'Przetwarzanie…' : 'Przytrzymaj aby nagrać'}
          >
            <div className="mic-icon" />
          </button>
          {isProcessing && <p className="mic-hint">Przetwarzanie…</p>}
          {!isProcessing && !isRecording && !errorMessage && (
            <p className="mic-hint">Przytrzymaj i mów</p>
          )}
          {isRecording && <p className="mic-hint recording-hint">Nagrywanie… (maks. 5 s)</p>}
          {errorMessage && <p className="mic-error">{errorMessage}</p>}
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
          {isProcessing && <div className="log-entry system">⏳ Przetwarzanie…</div>}
        </div>
      </aside>
    </div>
  );
}

export default App;
