import logging
import os
from datetime import datetime, timezone
from google.cloud import firestore
from google.oauth2 import service_account
from storage_client import generate_signed_url

logger = logging.getLogger(__name__)

# Ścieżka do klucza JSON – domyślnie obok tego pliku, nadpisywalna przez env
_CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "gcp-credentials.json"),
)

def _get_firestore_client() -> firestore.Client:
    if os.path.isfile(_CREDENTIALS_PATH):
        credentials = service_account.Credentials.from_service_account_file(
            _CREDENTIALS_PATH,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return firestore.Client(credentials=credentials)
    
    logger.info("Brak pliku credentials – używam Application Default Credentials (ADC) dla Firestore.")
    return firestore.Client()

try:
    db = _get_firestore_client()
except Exception as e:
    logger.error(f"Nie udało się zainicjalizować klienta Firestore: {e}")
    db = None

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

def get_latest_state(player_id: str) -> dict:
    """Zwraca ostatnią turę, która reprezentuje aktualny stan gry."""
    history = get_history(player_id, limit=1)
    if history:
        return history[0]
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
        
    turn_data["background_url"] = generate_signed_url(background_path, expiration_minutes=60)
    turn_data["audio_url"] = generate_signed_url(audio_path, expiration_minutes=60)
    turn_data["background_key"] = background_path
    turn_data["audio_key"] = audio_path
    
    doc_ref = db.collection("sessions").document(player_id).collection("turns").document(str(turn_id))
    doc_ref.set(turn_data)
    
    logger.info(f"Dodano turę {turn_id} dla {player_id}.")
    
    safe_data = dict(turn_data)
    safe_data["created_at"] = now.isoformat()
    return safe_data

def init_session(player_id: str) -> dict:
    """Inicjalizuje nową grę, tworząc pierwszą turę, chyba że już istnieje historia."""
    latest = get_latest_state(player_id)
    if latest:
        logger.info(f"Sesja dla {player_id} już istnieje.")
        if 'created_at' in latest and latest['created_at']:
            latest['created_at'] = str(latest['created_at'])
        return latest

    # Nowa gra
    first_turn = {
        "status": "active",
        "hp": 100,
        "location": "tavern",
        "scene_description": "Znajdujesz się w zadymionej karczmie. Za barem stoi potężny barman.",
        "turn_source": "system",
        "segments": [
            {
                "type": "system",
                "text": "Wchodzisz do Karczmy pod Zdechłym Dzikiem."
            }
        ]
    }
    
    return add_turn(player_id, first_turn)

def reset_session(player_id: str) -> dict:
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
    return init_session(player_id)
