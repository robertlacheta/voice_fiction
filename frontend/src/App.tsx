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
    console.log("Inicjalizacja sesji dla gracza:", PLAYER_ID, "pod adresem:", BACKEND_URL || "względnym");

    // Inicjalizacja na backendzie
    fetch(`${BACKEND_URL}/api/init`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_id: PLAYER_ID }),
    })
      .then(res => {
        if (!res.ok) {
          throw new Error(`HTTP Error: ${res.status} ${res.statusText}`);
        }
        return res.json();
      })
      .then(data => console.log("Sesja zainicjowana poprawnie:", data))
      .catch(err => console.error("Failed to initialize session. Błąd sieci lub backendu:", err));

    // Nasłuch zmian z Firestore
    const unsub = onSnapshot(doc(db, 'sessions', PLAYER_ID), (docSnap) => {
      console.log("Zdarzenie onSnapshot, doc exists?", docSnap.exists());
      if (docSnap.exists()) {
        const data = docSnap.data();
        console.log("Pobrane dane z bazy:", data);
        if (data.hp !== undefined) setHp(data.hp);
        if (data.scene_description) setSceneDescription(data.scene_description);
        if (data.logs) setLogs(data.logs);
      }
    }, (error) => {
      console.error("Błąd onSnapshot Firestore:", error);
    });

    return () => unsub();
  }, [PLAYER_ID]);

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
      {/* Upper Zone: SCENE */}
      <section className="scene-area">
        <img
          src="/tavern_interior.png"
          alt="Tavern Interior"
          className="illustration-img"
          onError={(e) => (e.currentTarget.style.display = 'none')}
        />

        <div className="character-badge pixel-border-thin">
          <div className="avatar-wrapper">
            {!avatarError ? (
              <img
                src="/avatar.png"
                alt="Avatar"
                className="avatar-img"
                onError={() => setAvatarError(true)}
              />
            ) : (
              <span className="avatar-placeholder">PORTRAIT</span>
            )}
          </div>
          <div className="character-stats">
            <span className="character-name">Thalia</span>
            <div className="hp-bar-container">
              <div className="hp-bar-fill" style={{ width: `${hp}%` }}></div>
            </div>
            <span className="hp-label">HP {hp}/100</span>
          </div>
        </div>

        <div className="scene-description-overlay">
          <div className="scene-description-text">{sceneDescription}</div>
        </div>
      </section>

      {/* Lower Zone: DIALOG PANEL */}
      <section className="dialog-panel">
        <div className="game-log" ref={logEndRef}>
          {logs.map((log) => (
            <div key={log.id} className={`log-entry ${log.type}`}>
              {log.text}
            </div>
          ))}
          {isProcessing && <div className="log-entry system">⏳ Przetwarzanie…</div>}
        </div>

        <div className="log-separator"></div>

        <div className="mic-area">
          <button
            className={`mic-button ${isRecording ? 'recording' : ''}`}
            onPointerDown={handlePointerDown}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
            disabled={isProcessing}
            aria-label="Mikrofon"
          >
            {isRecording && <div className="mic-pulse"></div>}
            <div className="mic-icon"></div>
          </button>

          <span className="mic-status-text">
            {isProcessing ? "Przetwarzanie..." : isRecording ? "Nagrywanie (max 5s)..." : "Kliknij i przytrzymaj by mówić"}
          </span>
        </div>
      </section>
    </div>
  );
}

export default App;
