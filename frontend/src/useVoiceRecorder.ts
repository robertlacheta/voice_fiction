import { useRef, useState, useCallback } from 'react';

export type RecorderStatus = 'idle' | 'recording' | 'processing' | 'error';

export interface VoiceRecorderResult {
  status: RecorderStatus;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
}

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? '';
const MAX_RECORDING_MS = 8_000; // twardy limit: 8 sekund

export function useVoiceRecorder(
  playerId: string,
  onTranscript: (transcript: string) => void,
  onError: (message: string) => void,
): VoiceRecorderResult {
  const [status, setStatus] = useState<RecorderStatus>('idle');

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const hardLimitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  /** Zatrzymuje nagrywanie i zwalnia mikrofon */
  const stopRecording = useCallback(() => {
    if (hardLimitTimerRef.current) {
      clearTimeout(hardLimitTimerRef.current);
      hardLimitTimerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  const sendAudio = useCallback(
    async (blob: Blob) => {
      setStatus('processing');
      try {
        const form = new FormData();
        form.append('player_id', playerId);
        form.append('audio', blob, 'recording.wav');

        const res = await fetch(`${BACKEND_URL}/api/recognize`, {
          method: 'POST',
          body: form,
        });

        if (res.status === 413) {
          throw new Error('Nagranie jest zbyt długie – maksymalnie ~6 sekund.');
        }
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
        }

        const data = (await res.json()) as { transcript: string };
        onTranscript(data.transcript);
        setStatus('idle');
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Nieznany błąd.';
        onError(message);
        setStatus('error');
      } finally {
        // Zawsze zwalniamy ślady mikrofonu
        streamRef.current?.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        chunksRef.current = [];
      }
    },
    [playerId, onTranscript, onError],
  );

  const startRecording = useCallback(async () => {
    if (status === 'recording' || status === 'processing') return;

    chunksRef.current = [];

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,   // mono – Firefox domyślnie stereo, co powoduje błąd Google STT
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;
    } catch {
      onError('Brak dostępu do mikrofonu. Sprawdź uprawnienia w przeglądarce.');
      setStatus('error');
      return;
    }

    // Preferowany format zgodny z backendem; fallback do domyślnego
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')
        ? 'audio/ogg;codecs=opus'
        : '';

    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunksRef.current, {
        type: recorder.mimeType || 'audio/webm',
      });
      void sendAudio(blob);
    };

    recorder.start();
    setStatus('recording');

    // Twardy limit – bezwzględne zatrzymanie po MAX_RECORDING_MS
    hardLimitTimerRef.current = setTimeout(() => {
      if (mediaRecorderRef.current?.state === 'recording') {
        mediaRecorderRef.current.stop();
      }
    }, MAX_RECORDING_MS);
  }, [status, sendAudio, onError]);

  return { status, startRecording, stopRecording };
}
