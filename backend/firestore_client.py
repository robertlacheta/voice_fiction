import logging
import os
from datetime import datetime, timezone
from google.cloud import firestore
from google.oauth2 import service_account

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
