import logging
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from google.cloud import speech
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

router = APIRouter()

# Ścieżka do klucza JSON – domyślnie obok tego pliku, nadpisywalna przez env
_CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "gcp-credentials.json"),
)

# Limit rozmiaru payloadu audio.
# WEBM_OPUS ~6 s @ 256 kbps ≈ 192 KB – przyjmujemy 200 KB z marginesem.
# Nadpisywalny przez zmienną środowiskową MAX_AUDIO_BYTES.
_MAX_AUDIO_BYTES: int = int(os.environ.get("MAX_AUDIO_BYTES", 200 * 1024))


def _get_speech_client() -> speech.SpeechClient:
    """Tworzy SpeechClient.

    Lokalnie: używa pliku JSON wskazanego przez GOOGLE_APPLICATION_CREDENTIALS.
    Na Cloud Run: używa Application Default Credentials (ADC) – service account
                  przypisany do serwisu Cloud Run, bez żadnego pliku.
    """
    if os.path.isfile(_CREDENTIALS_PATH):
        credentials = service_account.Credentials.from_service_account_file(
            _CREDENTIALS_PATH,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return speech.SpeechClient(credentials=credentials)

    # Cloud Run / ADC – brak pliku, używamy tożsamości serwisu
    logger.info("Brak pliku credentials – używam Application Default Credentials (ADC).")
    return speech.SpeechClient()


@router.post("/api/recognize")
async def recognize_speech(
    audio: UploadFile = File(..., description="Plik audio do transkrypcji"),
    player_id: str = Form(..., description="Identyfikator gracza"),
):
    """
    Przyjmuje nagranie audio i player_id (multipart/form-data),
    następnie uruchamia Google Cloud Speech-to-Text i zwraca transkrypcję.
    """
    try:
        audio_bytes = await audio.read()
    except Exception as e:
        logger.error("Błąd podczas odczytu pliku audio: %s", e)
        raise HTTPException(status_code=400, detail="Nie udało się odczytać pliku audio.")

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Plik audio jest pusty.")

    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        limit_kb = _MAX_AUDIO_BYTES // 1024
        actual_kb = len(audio_bytes) // 1024
        logger.warning(
            "Odrzucono plik audio: rozmiar %d KB przekracza limit %d KB (player_id=%s)",
            actual_kb, limit_kb, player_id,
        )
        raise HTTPException(
            status_code=413,
            detail=(
                f"Plik audio ({actual_kb} KB) przekracza maksymalny dozwolony rozmiar "
                f"({limit_kb} KB, ~6 s nagrania). Skróć nagranie i spróbuj ponownie."
            ),
        )

    # Dobierz konfigurację STT na podstawie typu MIME pliku
    content_type = (audio.content_type or "").lower()

    if content_type in ("audio/wav", "audio/wave", "audio/x-wav", "audio/vnd.wave"):
        # Dla WAV pomijamy encoding i sample_rate – Google czyta je z nagłówka WAV
        recognition_config = speech.RecognitionConfig(
            language_code="pl-PL",
            enable_automatic_punctuation=True,
        )
    elif content_type in ("audio/webm", "audio/ogg"):
        recognition_config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            sample_rate_hertz=48000,
            language_code="pl-PL",
            enable_automatic_punctuation=True,
        )
    else:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Nieobsługiwany format audio: '{audio.content_type}'. "
                "Obsługiwane formaty: audio/wav, audio/webm, audio/ogg."
            ),
        )

    try:
        client = _get_speech_client()

        audio_content = speech.RecognitionAudio(content=audio_bytes)
        config = recognition_config

        response = client.recognize(config=config, audio=audio_content)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Błąd Google Speech-to-Text dla player_id=%s: %s", player_id, e)
        raise HTTPException(status_code=502, detail=f"Google Speech-to-Text error: {e}")

    transcript = " ".join(
        result.alternatives[0].transcript
        for result in response.results
        if result.alternatives
    )

    logger.info("player_id=%s | transcript=%r", player_id, transcript)

    return {
        "player_id": player_id,
        "transcript": transcript,
    }