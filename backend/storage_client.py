import os
import logging
from datetime import timedelta
from google.cloud import storage
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "voice_fiction_bucket")
_CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "gcp-credentials.json"),
)

def _get_storage_client() -> storage.Client:
    if os.path.isfile(_CREDENTIALS_PATH):
        credentials = service_account.Credentials.from_service_account_file(_CREDENTIALS_PATH)
        return storage.Client(credentials=credentials)
    
    logger.info("Brak pliku credentials dla Cloud Storage – używam Application Default Credentials (ADC).")
    return storage.Client()

try:
    storage_client = _get_storage_client()
except Exception as e:
    logger.error(f"Nie udało się zainicjalizować klienta Cloud Storage: {e}")
    storage_client = None

def generate_signed_url(blob_name: str, expiration_minutes: int = 5) -> str:
    """Generuje tymczasowy link (Signed URL) do pliku w Cloud Storage."""
    if not storage_client:
        logger.error("Klient Cloud Storage nie jest zainicjalizowany.")
        return ""
        
    try:
        bucket = storage_client.bucket(_BUCKET_NAME)
        blob = bucket.blob(blob_name)
        
        # Generowanie Signed URL ważnego przez określoną liczbę minut
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
        )
        return url
    except Exception as e:
        logger.error(f"Błąd podczas generowania Signed URL dla {blob_name}: {e}")
        return ""
