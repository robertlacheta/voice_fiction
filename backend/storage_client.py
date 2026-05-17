import os
import logging
from datetime import timedelta
from google.cloud import storage
from google.oauth2 import service_account
import google.auth

logger = logging.getLogger(__name__)

# Próbujemy pobrać ID projektu, aby zbudować domyślną nazwę bucketa
try:
    _, default_project_id = google.auth.default()
except Exception:
    default_project_id = None

_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
if not _BUCKET_NAME:
    # Jeśli nie podano nazwy bucketa, próbujemy użyć standardowej nazwy Firebase
    if default_project_id:
        _BUCKET_NAME = f"{default_project_id}.firebasestorage.app"
    else:
        # Ostatnia deska ratunku - nazwa z konfiguracji frontendu
        _BUCKET_NAME = "project-156a0c69-6d30-45a1-bd9.firebasestorage.app"

logger.info(f"Używam bucketa GCS: {_BUCKET_NAME}")

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
        
        # W środowiskach takich jak Cloud Run, przy użyciu ADC, v4 wymaga podania emaila konta usługowego.
        # Próbujemy go pobrać z credentials jeśli to możliwe.
        service_account_email = getattr(storage_client._credentials, 'service_account_email', None)

        # Generowanie Signed URL ważnego przez określoną liczbę minut
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
            service_account_email=service_account_email
        )
        return url
    except Exception as e:
        logger.error(f"Błąd podczas generowania Signed URL dla {blob_name}: {e}")
        # Jeśli podpisanie się nie uda (np. brak uprawnień IAM lub brak emaila SA), 
        # zwracamy standardowy publiczny URL jako fallback.
        public_url = f"https://storage.googleapis.com/{_BUCKET_NAME}/{blob_name}"
        logger.info(f"Zwracam publiczny URL jako fallback: {public_url}")
        return public_url
