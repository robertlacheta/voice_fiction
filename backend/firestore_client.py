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
    """Tworzy klienta Firestore, używając pliku JSON lub ADC."""
    if os.path.isfile(_CREDENTIALS_PATH):
        credentials = service_account.Credentials.from_service_account_file(
            _CREDENTIALS_PATH,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return firestore.Client(credentials=credentials)
    
    logger.info("Brak pliku credentials – używam Application Default Credentials (ADC) dla Firestore.")
    return firestore.Client()

# Inicjalizacja klienta przy starcie modułu
try:
    db = _get_firestore_client()
except Exception as e:
    logger.error(f"Nie udało się zainicjalizować klienta Firestore: {e}")
    db = None

def init_session(player_id: str) -> dict:
    """
    Sprawdza, czy sesja istnieje. Jeśli nie, tworzy nową z domyślnymi wartościami.
    Zwraca dane sesji.
    """
    if not db:
        raise RuntimeError("Klient Firestore nie jest zainicjalizowany.")

    doc_ref = db.collection("sessions").document(player_id)
    doc = doc_ref.get()

    if doc.exists:
        logger.info(f"Sesja dla {player_id} już istnieje.")
        data = doc.to_dict()
        if 'created_at' in data and data['created_at']:
            data['created_at'] = str(data['created_at'])
        if 'updated_at' in data and data['updated_at']:
            data['updated_at'] = str(data['updated_at'])
        return data

    now = datetime.now(timezone.utc)
    new_session = {
        "player_id": player_id,
        "status": "active",
        "stage": 1,
        "hp": 100,
        "location": "tavern",
        "scene_description": "Znajdujesz się w zadymionej karczmie. Za barem stoi potężny barman.",
        "logs": [
            {
                "id": str(int(now.timestamp() * 1000)),
                "text": "Wchodzisz do Karczmy pod Zdechłym Dzikiem.",
                "type": "system",
                "timestamp": now.isoformat()
            }
        ],
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    doc_ref.set(new_session)
    logger.info(f"Utworzono nową sesję dla {player_id}.")
    
    # Bezpieczna kopia dla FastAPI bez obiektów Sentinel
    safe_session = dict(new_session)
    safe_session["created_at"] = now.isoformat()
    safe_session["updated_at"] = now.isoformat()
    return safe_session

def add_log(player_id: str, text: str, log_type: str):
    """
    Atomowo dodaje nowy wpis logu do tablicy 'logs' w dokumencie sesji.
    """
    if not db:
        raise RuntimeError("Klient Firestore nie jest zainicjalizowany.")

    doc_ref = db.collection("sessions").document(player_id)
    
    now = datetime.now(timezone.utc)
    new_log = {
        "id": str(int(now.timestamp() * 1000)),
        "text": text,
        "type": log_type,
        "timestamp": now.isoformat()
    }

    doc_ref.update({
        "logs": firestore.ArrayUnion([new_log]),
        "updated_at": firestore.SERVER_TIMESTAMP
    })
    logger.info(f"Dodano log [{log_type}] do sesji {player_id}.")
