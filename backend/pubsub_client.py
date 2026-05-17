import os
import json
import logging
import google.auth
from google.cloud import pubsub_v1
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

# Próbujemy wykryć ID projektu automatycznie
try:
    _, default_project_id = google.auth.default()
except Exception:
    default_project_id = None

_PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", default_project_id or "project-156a0c69-6d30-45a1-bd9")
_TOPIC_ID = "game-events"

_CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "gcp-credentials.json"),
)

def _get_publisher_client() -> pubsub_v1.PublisherClient:
    if os.path.isfile(_CREDENTIALS_PATH):
        credentials = service_account.Credentials.from_service_account_file(_CREDENTIALS_PATH)
        return pubsub_v1.PublisherClient(credentials=credentials)
    
    logger.info("Brak pliku credentials dla Pub/Sub – używam Application Default Credentials (ADC).")
    return pubsub_v1.PublisherClient()

publisher = _get_publisher_client()
topic_path = publisher.topic_path(_PROJECT_ID, _TOPIC_ID)

def publish_game_started(player_id: str):
    try:
        message_json = json.dumps({
            "event": "game_started",
            "player_id": player_id
        })
        message_bytes = message_json.encode("utf-8")
        
        # Opublikowanie wiadomości
        future = publisher.publish(topic_path, message_bytes)
        message_id = future.result(timeout=5)
        logger.info(f"Opublikowano zdarzenie 'game_started' dla gracza {player_id}. Message ID: {message_id}")
    except Exception as e:
        logger.error(f"Nie udało się opublikować zdarzenia Pub/Sub dla gracza {player_id}: {e}")
