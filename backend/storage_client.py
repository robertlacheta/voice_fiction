import os
from typing import Optional
import logging
from datetime import timedelta
import urllib.request
from google.cloud import storage
from google.oauth2 import service_account
import google.auth
import google.auth.transport.requests

logger = logging.getLogger(__name__)

_BUCKET_NAME = os.environ.get(
    "GCS_BUCKET_NAME",
    "voice_fiction_bucket",
)

# Lokalny klucz JSON ma zawsze priorytet nad zmienną środowiskową
# (chroni przed przypadkowym użyciem systemowych credentials np. gemini-cli)
_LOCAL_CREDS = os.path.join(os.path.dirname(__file__), "gcp-credentials.json")
_CREDENTIALS_PATH = _LOCAL_CREDS if os.path.isfile(_LOCAL_CREDS) else os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

logger.info(f"Używam bucketa GCS: {_BUCKET_NAME}")


def _get_storage_client() -> storage.Client:
    if os.path.isfile(_CREDENTIALS_PATH):
        credentials = service_account.Credentials.from_service_account_file(_CREDENTIALS_PATH)
        return storage.Client(credentials=credentials)

    logger.info("Brak pliku credentials – używam ADC dla Cloud Storage.")
    return storage.Client()


try:
    storage_client = _get_storage_client()
except Exception as e:
    logger.error(f"Nie udało się zainicjalizować klienta Cloud Storage: {e}")
    storage_client = None


def _get_metadata_email() -> Optional[str]:
    """Pobiera email SA z Metadata Server (działa na Cloud Run / GCE)."""
    try:
        url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"
        req = urllib.request.Request(url)
        req.add_header("Metadata-Flavor", "Google")
        with urllib.request.urlopen(req, timeout=2) as response:
            email = response.read().decode("utf-8")
            if email and email != "default":
                return email
    except Exception:
        pass
    return None


def _get_access_token() -> Optional[str]:
    """Pobiera aktualny access token z credentials (niezbędny do IAM signBlob API)."""
    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        request = google.auth.transport.requests.Request()
        creds.refresh(request)
        return creds.token
    except Exception as e:
        logger.error(f"Błąd pobierania access token: {e}")
        return None


def generate_signed_url(blob_name: str, expiration_minutes: int = 60) -> str:
    """
    Generuje Signed URL V4 dla pliku w Cloud Storage.

    - Lokalnie (z kluczem JSON): podpisuje kluczem prywatnym bezpośrednio.
    - Na Cloud Run (ADC): używa IAM Credentials API (signBlob) przez przekazanie
      `service_account_email` + `access_token`. Wymaga roli
      'Service Account Token Creator' na koncie usługowym.
    """
    if not storage_client:
        logger.error("Klient Cloud Storage nie jest zainicjalizowany.")
        return f"https://storage.googleapis.com/{_BUCKET_NAME}/{blob_name}"

    try:
        bucket = storage_client.bucket(_BUCKET_NAME)
        blob = bucket.blob(blob_name)

        if os.path.isfile(_CREDENTIALS_PATH):
            # Lokalnie: klucz JSON pozwala podpisywać bezpośrednio
            url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=expiration_minutes),
                method="GET",
            )
        else:
            # Cloud Run: musimy przekazać access_token + service_account_email,
            # żeby biblioteka użyła IAM Credentials API zamiast klucza prywatnego.
            sa_email = _get_metadata_email()
            access_token = _get_access_token()

            if not sa_email or not access_token:
                raise ValueError(
                    f"Nie można uzyskać danych do podpisywania "
                    f"(sa_email={sa_email}, token={'ok' if access_token else 'brak'})"
                )

            url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=expiration_minutes),
                method="GET",
                service_account_email=sa_email,
                access_token=access_token,
            )

        logger.debug(f"Signed URL wygenerowany dla: {blob_name}")
        return url

    except Exception as e:
        logger.error(f"Błąd podczas generowania Signed URL dla {blob_name}: {e}")
        # Fallback – zadziała tylko jeśli bucket/obiekt jest publiczny
        fallback = f"https://storage.googleapis.com/{_BUCKET_NAME}/{blob_name}"
        logger.warning(f"Fallback do publicznego URL: {fallback}")
        return fallback
