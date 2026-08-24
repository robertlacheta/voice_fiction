import logging
import os
from pydantic import BaseModel

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from google.cloud import speech
from google.oauth2 import service_account
from firestore_client import init_session, add_turn, get_latest_state, reset_session
from ai_engine import process_turn
from pubsub_client import publish_game_started

logger = logging.getLogger(__name__)

router = APIRouter()

_CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "gcp-credentials.json"),
)

_MAX_AUDIO_BYTES: int = int(os.environ.get("MAX_AUDIO_BYTES", 350 * 1024))


def _get_speech_client() -> speech.SpeechClient:
    if os.path.isfile(_CREDENTIALS_PATH):
        credentials = service_account.Credentials.from_service_account_file(
            _CREDENTIALS_PATH,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return speech.SpeechClient(credentials=credentials)

    logger.info("Brak pliku credentials – używam Application Default Credentials (ADC).")
    return speech.SpeechClient()


class InitRequest(BaseModel):
    player_id: str
    language: str = "pl"


@router.post("/api/init")
def initialize_session(req: InitRequest):
    try:
        session_data = init_session(req.player_id, language=req.language)

        # Wysyłamy asynchroniczne powiadomienie do Pub/Sub
        publish_game_started(req.player_id)

        return session_data
    except Exception as e:
        logger.error(f"Błąd inicjalizacji sesji dla {req.player_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/reset")
def reset_game_session(req: InitRequest):
    try:
        session_data = reset_session(req.player_id, language=req.language)
        publish_game_started(req.player_id)
        return session_data
    except Exception as e:
        logger.error(f"Błąd resetowania sesji dla {req.player_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/recognize")
async def recognize_speech(
    audio: UploadFile = File(..., description="Plik audio do transkrypcji"),
    player_id: str = Form(..., description="Identyfikator gracza"),
    language: str = Form("pl", description="Preferowany język (pl lub en)"),
):
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

    content_type = (audio.content_type or "").lower()
    is_english = (language or "pl").lower().startswith("en")
    primary_lang = "en-US" if is_english else "pl-PL"
    alt_langs = ["pl-PL"] if is_english else ["en-US"]

    if content_type.startswith(("audio/wav", "audio/wave", "audio/x-wav", "audio/vnd.wave")):
        recognition_config = speech.RecognitionConfig(
            language_code=primary_lang,
            alternative_language_codes=alt_langs,
            model="latest_long",  # lepszy model dla naturalnej mowy konwersacyjnej
            enable_automatic_punctuation=True,
        )
    elif content_type.startswith(("audio/webm", "audio/ogg")):
        recognition_config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            language_code=primary_lang,
            alternative_language_codes=alt_langs,
            model="latest_long",  # lepszy model dla naturalnej mowy konwersacyjnej
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
    ).strip()

    logger.info("player_id=%s | transcript=%r", player_id, transcript)

    if not transcript:
        err_msg = (
            "Could not recognize speech. Please speak louder and clearer."
            if is_english
            else "Nie udało się rozpoznać mowy. Spróbuj mówić głośniej i wyraźniej."
        )
        raise HTTPException(status_code=400, detail=err_msg)

    try:
        current_state = get_latest_state(player_id)
        
        # 1. Zapisujemy akcję gracza jako osobną turę (zabezpiecza to historię, nawet jeśli AI padnie)
        player_turn = {
            "status": current_state.get("status", "active") if current_state else "active",
            "hp": current_state.get("hp", 100) if current_state else 100,
            "location": current_state.get("location", "tavern") if current_state else "tavern",
            "scene_description": current_state.get("scene_description", "") if current_state else "",
            "turn_source": "player",
            "segments": [{"type": "action", "text": transcript}]
        }
        add_turn(player_id, player_turn)
        
        # 2. Przekazujemy akcję do silnika AI i zapisujemy wynik jako odpowiedź AI
        ai_turn = process_turn(player_id, transcript)
        add_turn(player_id, ai_turn)
        
    except Exception as e:
        logger.error("Błąd podczas procesowania tury dla player_id=%s: %s", player_id, e)
        raise HTTPException(status_code=500, detail=f"Błąd silnika AI: {str(e)}")

    return {
        "player_id": player_id,
        "transcript": transcript,
    }