import logging
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import requests
import google.auth
import google.auth.transport.requests
from google.oauth2 import service_account
from storage_client import generate_signed_url

logger = logging.getLogger(__name__)

# Lokalny klucz JSON ma zawsze priorytet nad zmienną środowiskową
_LOCAL_CREDS = os.path.join(os.path.dirname(__file__), "gcp-credentials.json")
_CREDENTIALS_PATH = _LOCAL_CREDS if os.path.isfile(_LOCAL_CREDS) else os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

_PROJECT_ID = os.environ.get(
    "VITE_FIREBASE_PROJECT_ID",
    os.environ.get("GOOGLE_CLOUD_PROJECT", "project-156a0c69-6d30-45a1-bd9"),
)
os.environ["GOOGLE_CLOUD_PROJECT"] = _PROJECT_ID
os.environ["GCLOUD_PROJECT"] = _PROJECT_ID

# Bezpośredni, surowy adres REST API Firestore (bez auto-encodowania nawiasów (default))
_BASE_FIRESTORE_URL = f"https://firestore.googleapis.com/v1/projects/{_PROJECT_ID}/databases/(default)/documents"


def _get_auth_headers() -> Dict[str, str]:
    """Pobiera świeży token OAuth2 (z klucza JSON lub z ADC na Cloud Run)."""
    scopes = [
        "https://www.googleapis.com/auth/datastore",
        "https://www.googleapis.com/auth/cloud-platform",
    ]
    if os.path.isfile(_CREDENTIALS_PATH):
        creds = service_account.Credentials.from_service_account_file(
            _CREDENTIALS_PATH,
            scopes=scopes,
        )
    else:
        creds, _ = google.auth.default(scopes=scopes)

    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }


def _to_firestore_value(val: Any) -> Dict[str, Any]:
    """Konwertuje typy Pythona na format pól Firestore REST API."""
    if isinstance(val, bool):
        return {"booleanValue": val}
    elif isinstance(val, int):
        return {"integerValue": str(val)}
    elif isinstance(val, float):
        return {"doubleValue": val}
    elif isinstance(val, str):
        return {"stringValue": val}
    elif isinstance(val, list):
        return {"arrayValue": {"values": [_to_firestore_value(item) for item in val]}}
    elif isinstance(val, dict):
        return {"mapValue": {"fields": {k: _to_firestore_value(v) for k, v in val.items()}}}
    elif val is None:
        return {"nullValue": None}
    return {"stringValue": str(val)}


def _from_firestore_value(val_dict: Any) -> Any:
    """Konwertuje pola Firestore REST API na natywne typy Pythona."""
    if not isinstance(val_dict, dict):
        return val_dict
    if "stringValue" in val_dict:
        return val_dict["stringValue"]
    elif "integerValue" in val_dict:
        try:
            return int(val_dict["integerValue"])
        except (ValueError, TypeError):
            return val_dict["integerValue"]
    elif "doubleValue" in val_dict:
        return val_dict["doubleValue"]
    elif "booleanValue" in val_dict:
        return val_dict["booleanValue"]
    elif "timestampValue" in val_dict:
        return val_dict["timestampValue"]
    elif "arrayValue" in val_dict:
        values = val_dict["arrayValue"].get("values", [])
        return [_from_firestore_value(v) for v in values]
    elif "mapValue" in val_dict:
        fields = val_dict["mapValue"].get("fields", {})
        return {k: _from_firestore_value(v) for k, v in fields.items()}
    elif "nullValue" in val_dict:
        return None
    return str(val_dict)


def _doc_to_dict(doc_json: Dict[str, Any]) -> Dict[str, Any]:
    """Parsuje dokument Firestore REST API do słownika Pythona."""
    fields = doc_json.get("fields", {})
    res = {k: _from_firestore_value(v) for k, v in fields.items()}
    if "createTime" in doc_json:
        res["created_at"] = doc_json["createTime"]
    return res


def _enrich_with_urls(turn: dict) -> dict:
    """Generuje świeże Signed URLe na podstawie kluczy GCS zapisanych w turze."""
    bg_key = turn.get("background_key")
    audio_key = turn.get("audio_key")
    if bg_key:
        turn["background_url"] = generate_signed_url(bg_key, expiration_minutes=60)
    if audio_key:
        turn["audio_url"] = generate_signed_url(audio_key, expiration_minutes=60)
    return turn


def get_history(player_id: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Pobiera chronologiczną historię tur gracza przez Firestore REST API."""
    headers = _get_auth_headers()
    query_url = f"{_BASE_FIRESTORE_URL}/sessions/{player_id}:runQuery"
    
    query_body = {
        "structuredQuery": {
            "from": [{"collectionId": "turns"}],
            "orderBy": [{"field": {"fieldPath": "turn_id"}, "direction": "DESCENDING"}],
            "limit": limit,
        }
    }
    
    resp = requests.post(query_url, headers=headers, json=query_body, timeout=10)
    if not resp.ok:
        logger.error(f"Błąd get_history ({resp.status_code}): {resp.text}")
        raise RuntimeError(f"Firestore query error: {resp.text}")
    
    results = []
    items = resp.json()
    if isinstance(items, list):
        for item in items:
            if "document" in item:
                results.append(_doc_to_dict(item["document"]))
                
    results.reverse()  # Zwracamy od najstarszej do najnowszej
    return results


def get_latest_state(player_id: str) -> Optional[dict]:
    """Zwraca ostatnią turę z odświeżonymi Signed URLami."""
    history = get_history(player_id, limit=1)
    if history:
        return _enrich_with_urls(history[0])
    return None


def add_turn(player_id: str, turn_data: dict) -> dict:
    """Dodaje nową turę do historii gracza przez Firestore REST API."""
    now = datetime.now(timezone.utc)
    turn_id = int(now.timestamp() * 1000)
    
    turn_data["turn_id"] = turn_id
    turn_data["player_id"] = player_id
    turn_data["created_at"] = now.isoformat()
    
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
        background_path = "assets/scenes/duel_scene.png"
        audio_path = "audio/Background music/Walka.webm"
    elif location == "victory":
        background_path = "assets/scenes/victory.png"
        audio_path = "audio/Background music/Victory.webm"
    elif location == "failure":
        background_path = "assets/scenes/failure.png"
        audio_path = "audio/Background music/Failure.webm"
        
    turn_data["background_key"] = background_path
    turn_data["audio_key"] = audio_path
    turn_data["background_url"] = generate_signed_url(background_path, expiration_minutes=60)
    turn_data["audio_url"] = generate_signed_url(audio_path, expiration_minutes=60)
    
    # Zapis do Firestore przez REST PATCH
    headers = _get_auth_headers()
    write_url = f"{_BASE_FIRESTORE_URL}/sessions/{player_id}/turns/{turn_id}"
    fields_payload = {"fields": {k: _to_firestore_value(v) for k, v in turn_data.items()}}
    
    resp = requests.patch(write_url, headers=headers, json=fields_payload, timeout=10)
    if not resp.ok:
        logger.error(f"Błąd zapisu tury do Firestore ({resp.status_code}): {resp.text}")
        raise RuntimeError(f"Firestore write error: {resp.text}")
        
    logger.info(f"Dodano turę {turn_id} dla gracza {player_id}.")
    return turn_data


def init_session(player_id: str, language: str = "pl") -> dict:
    """Inicjalizuje nową grę, tworząc pierwszą turę, chyba że już istnieje historia."""
    latest = get_latest_state(player_id)
    if latest:
        logger.info(f"Sesja dla {player_id} już istnieje.")
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
    """Czyści historię gracza i rozpoczyna nową grę przez Firestore REST."""
    logger.info(f"Resetowanie sesji dla gracza {player_id}...")
    headers = _get_auth_headers()
    
    # 1. Pobieramy listę dokumentów tur
    query_url = f"{_BASE_FIRESTORE_URL}/sessions/{player_id}:runQuery"
    query_body = {"structuredQuery": {"from": [{"collectionId": "turns"}]}}
    resp = requests.post(query_url, headers=headers, json=query_body, timeout=10)
    
    if resp.ok:
        items = resp.json()
        if isinstance(items, list):
            for item in items:
                doc_name = item.get("document", {}).get("name")
                if doc_name:
                    del_url = f"https://firestore.googleapis.com/v1/{doc_name}"
                    requests.delete(del_url, headers=headers, timeout=5)
                    
    logger.info(f"Usunięto stare tury dla gracza {player_id}.")
    return init_session(player_id, language=language)
