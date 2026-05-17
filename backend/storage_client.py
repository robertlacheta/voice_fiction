import os
import logging
from datetime import timedelta
import urllib.request
from google.cloud import storage
from google.oauth2 import service_account
import google.auth

logger = logging.getLogger(__name__)

# Próbujemy pobrać ID projektu i email konta usługowego
try:
    _credentials, default_project_id = google.auth.default()
except Exception:
    _credentials, default_project_id = None, None

def _get_service_account_email():
    """Pobiera email konta usługowego z credentials lub metadata server."""
    if _credentials and hasattr(_credentials, 'service_account_email'):
        return _credentials.service_account_email
    
    # Próba pobrania z Metadata Server (Cloud Run / GCE)
    try:
        url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"
        req = urllib.request.Request(url)
        req.add_header("Metadata-Flavor", "Google")
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.read().decode("utf-8")
    except Exception:
        return None

_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
if not _BUCKET_NAME:
    if default_project_id:
        _BUCKET_NAME = f"{default_project_id}.firebasestorage.app"
    else:
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
        
        # Pobieramy email konta usługowego - kluczowe dla V4 i ADC na Cloud Run
        service_account_email = _get_service_account_email()

        # Generowanie Signed URL ważnego przez określoną liczbę minut
        # Wymaga roli 'Service Account Token Creator' dla konta usługowego w Cloud Run
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
            service_account_email=service_account_email
        )
        return url
    except Exception as e:
        logger.error(f"Błąd podczas generowania Signed URL dla {blob_name}: {e}")
        # Fallback do publicznego URL (zadziała tylko jeśli bucket/obiekt jest publiczny)
        public_url = f"https://storage.googleapis.com/{_BUCKET_NAME}/{blob_name}"
        logger.info(f"Zwracam publiczny URL jako fallback: {public_url}")
        return public_url
