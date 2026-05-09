import { useState, useEffect, useRef, useCallback } from 'react';
import { doc, onSnapshot } from 'firebase/firestore';
import { db } from './firebase';
import './App.css';
import { useVoiceRecorder } from './useVoiceRecorder';

interface LogEntry {
  id: number | string;
  text: string;
  type: 'system' | 'action' | 'dialogue' | 'error';
}

function getOrCreatePlayerId() {
  const stored = localStorage.getItem('vf_player_id');
  if (stored) return stored;
  const newId = 'player_' + Math.random().toString(36).substring(2, 10);
  localStorage.setItem('vf_player_id', newId);
  return newId;
}

function App() {
  const [PLAYER_ID] = useState(() => getOrCreatePlayerId());

  const [hp, setHp] = useState(100);
  const [avatarError, setAvatarError] = useState(false);

  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [sceneDescription, setSceneDescription] = useState("Ładowanie...");

  useEffect(() => {
    const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? '';
    
    // Inicjalizacja na backendzie
    fetch(`${BACKEND_URL}/api/init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_id: PLAYER_ID }),
    }).catch(err => console.error("Failed to initialize session", err));

    // Nasłuch zmian z Firestore
    const unsub = onSnapshot(doc(db, 'sessions', PLAYER_ID), (docSnap) => {
      if (docSnap.exists()) {
        const data = docSnap.data();
        if (data.hp !== undefined) setHp(data.hp);
        if (data.scene_description) setSceneDescription(data.scene_description);
        if (data.logs) setLogs(data.logs);
      }
    });

    return () => unsub();
  }, []);

  const onTranscript = useCallback((transcript: string) => {
    // Nie dodajemy logu ręcznie – polegamy na tym, że po pomyślnym wysłaniu
    // backend zapisze go w bazie, co wywoła onSnapshot i zaktualizuje UI.
    console.log("Transkrypcja wygenerowana:", transcript);
  }, []);

  const onError = useCallback((message: string) => {
    setLogs((prev) => [
      ...prev,
      { id: Date.now().toString(), text: `⚠ ${message}`, type: 'error' },
    ]);
  }, []);

  const { status, startRecording, stopRecording } =
    useVoiceRecorder(PLAYER_ID, onTranscript, onError);

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
          <div className="mic-container">
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
            {!isProcessing && !isRecording && (
              <p className="mic-hint">Przytrzymaj i mów</p>
            )}
            {isRecording && <p className="mic-hint recording-hint">Nagrywanie… (maks. 5 s)</p>}
          </div>
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
