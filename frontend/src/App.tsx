import { useState, useEffect, useRef, useCallback } from 'react';
import { collection, query, orderBy, onSnapshot } from 'firebase/firestore';
import { db } from './firebase';
import './App.css';
import { useVoiceRecorder } from './useVoiceRecorder';

interface LogEntry {
  id: number | string;
  text: string;
  type: 'system' | 'action' | 'dialogue' | 'error' | 'narration';
}

function getOrCreatePlayerId() {
  const stored = localStorage.getItem('vf_player_id');
  if (stored) return stored;
  const newId = 'player_' + Math.random().toString(36).substring(2, 10);
  localStorage.setItem('vf_player_id', newId);
  return newId;
}

// Ekstraktuje ścieżkę pliku z signed URL (bez parametrów query)
// np. https://storage.googleapis.com/bucket/audio/Tawerna.webm?X-Goog-... → /bucket/audio/Tawerna.webm
function getUrlPath(url: string): string {
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
}

function App() {
  const [PLAYER_ID] = useState(() => getOrCreatePlayerId());

  const [hp, setHp] = useState(100);
  const [avatarError, setAvatarError] = useState(false);

  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [sceneDescription, setSceneDescription] = useState("Ładowanie...");
  const [backgroundUrl, setBackgroundUrl] = useState<string>("/tavern_interior.png");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [location, setLocation] = useState<string>("tavern");

  const audioRef = useRef<HTMLAudioElement>(null);
  const initStartedRef = useRef(false);
  const logEndRef = useRef<HTMLDivElement>(null);
  const fadeIntervalRef = useRef<number | null>(null);

  // Śledzi ścieżkę pliku (bez signed params) aktualnie załadowanego w audio/img
  const currentAudioPathRef = useRef<string | null>(null);
  const currentBgPathRef = useRef<string | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  const fadeAudio = useCallback((targetVolume: number, duration: number) => {
    if (!audioRef.current) return;
    const audio = audioRef.current;
    
    if (fadeIntervalRef.current !== null) {
      clearInterval(fadeIntervalRef.current);
    }

    const clamp = (v: number) => Math.min(1, Math.max(0, v));
    const target = clamp(targetVolume);
    const startVolume = audio.volume;
    const startTime = performance.now();

    fadeIntervalRef.current = window.setInterval(() => {
      const now = performance.now();
      const progress = Math.min((now - startTime) / duration, 1);
      
      // smoothstep easing (eliminuje ostre przeskoki "zipper noise" na początku i końcu fadu)
      const ease = progress * progress * (3 - 2 * progress);
      
      audio.volume = clamp(startVolume + (target - startVolume) * ease);

      if (progress >= 1) {
        if (fadeIntervalRef.current !== null) {
          clearInterval(fadeIntervalRef.current);
          fadeIntervalRef.current = null;
        }
      }
    }, 10);
  }, []);

  const [pendingTranscript, setPendingTranscript] = useState<string | null>(null);

  const onTranscript = useCallback((transcript: string) => {
    console.log("Transkrypcja wygenerowana:", transcript);
    // Pokaż transkrypt optymistycznie w logu natychmiast po rozpoznaniu
    setPendingTranscript(transcript);
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

  // Efekt do dynamicznej regulacji głośności z płynnym fade
  // Wyciszamy tylko podczas nagrywania — podczas przetwarzania muzyka wraca
  useEffect(() => {
    const audio = audioRef.current;
    
    if (isRecording) {
      fadeAudio(0, 300);
    } else {
      if (audio && audio.src && audio.paused) {
        void audio.play().catch(e => console.warn("Nie można wznowić audio:", e));
      }

      const targetVolume = location === 'duel' ? 0.6 : 0.3;
      fadeAudio(targetVolume, 600);
    }
  }, [isRecording, location, fadeAudio]);

  // Efekt do obsługi zmiany ścieżki audio bez restartu
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !audioUrl) return;

    audio.loop = true;
    audio.src = audioUrl;
    audio.load();
    void audio.play().catch((e) => console.warn('Autoplay blocked:', e));
    console.log('Ładowanie nowej ścieżki audio:', getUrlPath(audioUrl));
  }, [audioUrl]);


  // Efekt do inicjalizacji sesji (tylko raz)
  useEffect(() => {
    if (initStartedRef.current) return;
    initStartedRef.current = true;

    const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? '';
    console.log("Inicjalizacja sesji dla gracza:", PLAYER_ID, "pod adresem:", BACKEND_URL || "względnym");

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
      .catch(err => console.error("Failed to initialize session:", err));
  }, [PLAYER_ID]);

  // Efekt do nasłuchu bazy danych
  useEffect(() => {
    const turnsRef = collection(db, 'sessions', PLAYER_ID, 'turns');
    const q = query(turnsRef, orderBy('turn_id', 'asc'));

    const unsub = onSnapshot(q, (querySnapshot) => {
      console.log("Zdarzenie onSnapshot dla tur. Ilość dokumentów:", querySnapshot.size);
      if (!querySnapshot.empty) {
        const latestDoc = querySnapshot.docs[querySnapshot.docs.length - 1];
        const latestData = latestDoc.data();

        if (latestData.hp !== undefined) setHp(latestData.hp);
        if (latestData.scene_description) setSceneDescription(latestData.scene_description);
        if (latestData.location) setLocation(latestData.location);

        // Aktualizuj URL obrazka tylko gdy zmienił się plik (nie tylko signed URL)
        if (latestData.background_url) {
          const newBgPath = getUrlPath(latestData.background_url);
          if (newBgPath !== currentBgPathRef.current) {
            currentBgPathRef.current = newBgPath;
            setBackgroundUrl(latestData.background_url);
            console.log('Nowe tło:', newBgPath);
          }
        }

        // Aktualizuj URL audio tylko gdy zmienił się plik (nie tylko signed URL)
        if (latestData.audio_url) {
          const newAudioPath = getUrlPath(latestData.audio_url);
          if (newAudioPath !== currentAudioPathRef.current) {
            currentAudioPathRef.current = newAudioPath;
            setAudioUrl(latestData.audio_url);
            console.log('Nowa muzyka:', newAudioPath);
          }
        }

        const allLogs: LogEntry[] = [];
        querySnapshot.docs.forEach(doc => {
          const data = doc.data();
          if (data.segments && Array.isArray(data.segments)) {
            data.segments.forEach((seg: { type?: LogEntry['type'], text: string }, idx: number) => {
              allLogs.push({
                id: `${doc.id}_${idx}`,
                text: seg.text,
                type: seg.type || 'system'
              });
            });
          }
        });
        setLogs(allLogs);
      }
    }, (error) => {
      console.error("Błąd onSnapshot Firestore:", error);
    });

    return () => unsub();
  }, [PLAYER_ID]);

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollTo({
        top: logEndRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [logs, pendingTranscript]);

  // Tymczasowy transkrypt widoczny dopóki Firestore nie dostarczy prawdziwego wpisu
  const showPendingTranscript = pendingTranscript && !logs.some(l => l.text === pendingTranscript);


  const handleMicClick = () => {
    if (isProcessing) return;
    if (isRecording) {
      stopRecording();
    } else {
      void startRecording();
    }
  };

  const handleResetGame = async () => {
    if (!window.confirm("Czy na pewno chcesz zresetować grę? Cały postęp zostanie utracony.")) {
      return;
    }

    setIsSettingsOpen(false);
    setSceneDescription("Resetowanie...");
    setLogs([]);
    setPendingTranscript(null);

    const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? '';
    try {
      const res = await fetch(`${BACKEND_URL}/api/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: PLAYER_ID }),
      });
      if (!res.ok) {
        throw new Error(`HTTP Error: ${res.status}`);
      }
      console.log("Gra została zresetowana.");
    } catch (err) {
      console.error("Błąd resetowania gry:", err);
      onError("Nie udało się zresetować gry.");
    }
  };

  return (
    <div className="game-window">
      <div style={{ display: 'none' }}>
        <audio
          ref={audioRef}
          loop
          playsInline
          onPlay={() => console.log("Muzyka gra:", audioRef.current?.src)}
          onError={(e) => console.error("Błąd odtwarzania audio:", e)}
        />
      </div>
      {/* Upper Zone: SCENE */}
      <section className="scene-area">
        <img
          key={backgroundUrl}
          src={backgroundUrl}
          alt="Scene Background"
          onLoad={() => console.log("Obrazek tła załadowany:", backgroundUrl)}
          onError={(e) => {
            console.error("Błąd ładowania tła:", backgroundUrl);
            e.currentTarget.style.display = 'none';
          }}
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

        <button
          className="settings-button pixel-border-thin"
          onClick={() => setIsSettingsOpen(true)}
          aria-label="Ustawienia"
        >
          ⚙️
        </button>

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
          {/* Tymczasowy transkrypt — pokazywany od razu po rozpoznaniu głosu */}
          {showPendingTranscript && (
            <div className="log-entry action">{pendingTranscript}</div>
          )}
          {isProcessing && <div className="log-entry system">⏳ Przetwarzanie…</div>}
        </div>

        <div className="log-separator"></div>

        <div className="mic-area">
          <button
            className={`mic-button ${isRecording ? 'recording' : ''}`}
            onClick={handleMicClick}
            disabled={isProcessing}
            aria-label="Mikrofon"
          >
            {isRecording && <div className="mic-pulse"></div>}
            <div className="mic-icon"></div>
          </button>

          <span className="mic-status-text">
            {isProcessing ? "Przetwarzanie..." : isRecording ? "Nagrywanie (max 8s)..." : "Kliknij raz by mówić"}
          </span>
        </div>
      </section>

      {isSettingsOpen && (
        <div className="settings-modal-overlay">
          <div className="settings-modal pixel-border">
            <h2>USTAWIENIA</h2>
            <p>Twój ID: {PLAYER_ID}</p>
            <button className="reset-button pixel-border-thin" onClick={handleResetGame}>
              Zacznij od nowa
            </button>
            <button className="close-modal-button" onClick={() => setIsSettingsOpen(false)}>
              Zamknij
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
