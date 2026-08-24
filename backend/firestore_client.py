import logging
import os
from typing import Optional
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials as fa_credentials
from firebase_admin import firestore as fa_firestore
from google.cloud import firestore
from storage_client import generate_signed_url

logger = logging.getLogger(__name__)

# Lokalny klucz JSON ma zawsze priorytet nad zmienną środowiskową
# (chroni przed przypadkowym użyciem systemowych credentials np. gemini-cli)
_LOCAL_CREDS = os.path.join(os.path.dirname(__file__), "gcp-credentials.json")
_CREDENTIALS_PATH = _LOCAL_CREDS if os.path.isfile(_LOCAL_CREDS) else os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

_PROJECT_ID = os.environ.get(
    "VITE_FIREBASE_PROJECT_ID",
    os.environ.get("GOOGLE_CLOUD_PROJECT", "project-156a0c69-6d30-45a1-bd9"),
)
os.environ["GOOGLE_CLOUD_PROJECT"] = _PROJECT_ID
os.environ["GCLOUD_PROJECT"] = _PROJECT_ID


def _get_firestore_client():
    try:
        if not firebase_admin._apps:
            if os.path.isfile(_CREDENTIALS_PATH):
                cred = fa_credentials.Certificate(_CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred, {"projectId": _PROJECT_ID})
            else:
                firebase_admin.initialize_app(options={"projectId": _PROJECT_ID})
        return fa_firestore.client()
    except Exception as e:
        logger.warning(f"Błąd inicjalizacji firebase_admin: {e}, fallback do google-cloud-firestore...")
        if os.path.isfile(_CREDENTIALS_PATH):
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                _CREDENTIALS_PATH,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            return firestore.Client(project=_PROJECT_ID, credentials=creds)
        return firestore.Client(project=_PROJECT_ID)


try:
    db = _get_firestore_client()
except Exception as e:
    logger.error(f"Nie udało się zainicjalizować klienta Firestore: {e}")
    db = None


def _enrich_with_urls(turn: dict) -> dict:
    """Generuje świeże Signed URLe na podstawie kluczy GCS zapisanych w turze."""
    bg_key = turn.get("background_key")
    audio_key = turn.get("audio_key")
    if bg_key:
        turn["background_url"] = generate_signed_url(bg_key, expiration_minutes=60)
    if audio_key:
        turn["audio_url"] = generate_signed_url(audio_key, expiration_minutes=60)
    return turn


def get_history(player_id: str, limit: int = 15) -> list:
    """Pobiera chronologiczną historię tur gracza."""
    if not db:
        raise RuntimeError("Klient Firestore nie jest zainicjalizowany.")
    
    turns_ref = db.collection("sessions").document(player_id).collection("turns")
    query = turns_ref.order_by("turn_id", direction=firestore.Query.DESCENDING).limit(limit)
    
    results = []
    for doc in query.stream():
        data = doc.to_dict()
        results.append(data)
        
    results.reverse() # Zwracamy od najstarszej do najnowszej
    return results


def get_latest_state(player_id: str) -> Optional[dict]:
    """Zwraca ostatnią turę z odświeżonymi Signed URLami."""
    history = get_history(player_id, limit=1)
    if history:
        return _enrich_with_urls(history[0])
    return None


def add_turn(player_id: str, turn_data: dict) -> dict:
    """Dodaje nową turę do historii gracza."""
    if not db:
        raise RuntimeError("Klient Firestore nie jest zainicjalizowany.")
        
    now = datetime.now(timezone.utc)
    turn_id = int(now.timestamp() * 1000)
    
    turn_data["turn_id"] = turn_id
    turn_data["player_id"] = player_id
    turn_data["created_at"] = firestore.SERVER_TIMESTAMP
    
    # Automatyczna zmiana lokacji na podstawie stanu gry (HP/Status)
    hp = turn_data.get("hp", 100)
    status = turn_data.get("status", "active")
    
    if hp <= 0 or status == "game_over":
        turn_data["location"] = "failure"
    elif status == "victory":
        turn_data["location"] = "victory"

    # Obsługa assetów z Cloud Storage w zależności od lokalizacji
    location = turn_data.get("location", "tavern")
    background_path = "assets/scenes/tavern_interior.png"
    audio_path = "audio/Background music/Tawerna.webm"
    
    if location == "forest":
        background_path = "assets/scenes/forest_road.png"
        audio_path = "audio/Background music/Las.webm"
    elif location == "duel":
        background_path = "assets/scenes/duel_scene.png" # Walka toczy się w lesie
        audio_path = "audio/Background music/Walka.webm"
    elif location == "victory":
        background_path = "assets/scenes/victory.png"
        audio_path = "audio/Background music/Victory.webm"
    elif location == "failure":
        background_path = "assets/scenes/failure.png"
        audio_path = "audio/Background music/Failure.webm"
        
    # Zapisujemy klucze GCS (trwałe) i świeże Signed URLe (ważne 60 min)
    # Frontend czyta background_url/audio_url bezpośrednio przez onSnapshot z Firestore
    turn_data["background_key"] = background_path
    turn_data["audio_key"] = audio_path
    turn_data["background_url"] = generate_signed_url(background_path, expiration_minutes=60)
    turn_data["audio_url"] = generate_signed_url(audio_path, expiration_minutes=60)
    
    doc_ref = db.collection("sessions").document(player_id).collection("turns").document(str(turn_id))
    doc_ref.set(turn_data)
    
    logger.info(f"Dodano turę {turn_id} dla {player_id}.")
    
    safe_data = dict(turn_data)
    safe_data["created_at"] = now.isoformat()
    return safe_data


def init_session(player_id: str, language: str = "pl") -> dict:
    """Inicjalizuje nową grę, tworząc pierwszą turę, chyba że już istnieje historia."""
    latest = get_latest_state(player_id)
    if latest:
        logger.info(f"Sesja dla {player_id} już istnieje.")
        if 'created_at' in latest and latest['created_at']:
            latest['created_at'] = str(latest['created_at'])
        return latest

    # Nowa gra
    is_en = (language or "pl").lower().startswith("en")
    first_turn = {
        "status": "active",
        "hp": 100,
        "location": "tavern",
        "scene_description": (
            "You are inside a smoky tavern. A sturdy innkeeper stands behind the counter."
            if is_en
            else "Znajdujesz się w zadymionej karczmie. Za barem stoi potężny barman."
        ),
        "turn_source": "system",
        "segments": [
            {
                "type": "system",
                "text": (
                    "You enter the Dead Boar Tavern."
                    if is_en
                    else "Wchodzisz do Karczmy pod Zdechłym Dzikiem."
                )
            }
        ]
    }
    
    return add_turn(player_id, first_turn)


def reset_session(player_id: str, language: str = "pl") -> dict:
    """Czyści historię gracza i rozpoczyna nową grę."""
    if not db:
        raise RuntimeError("Klient Firestore nie jest zainicjalizowany.")
        
    logger.info(f"Resetowanie sesji dla gracza {player_id}...")
    turns_ref = db.collection("sessions").document(player_id).collection("turns")
    
    # Usuwanie wszystkich dokumentów z użyciem transakcji wsadowej (batch)
    docs = list(turns_ref.stream())
    batch = db.batch()
    count = 0
    
    for doc in docs:
        batch.delete(doc.reference)
        count += 1
        if count >= 400:
            batch.commit()
            batch = db.batch()
            count = 0
            
    if count > 0:
        batch.commit()
        
    logger.info(f"Usunięto stare tury dla gracza {player_id}.")
    return init_session(player_id, language=language)
