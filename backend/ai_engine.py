import logging
import json
import vertexai
import os
import google.auth
from vertexai.generative_models import GenerativeModel, GenerationConfig
from firestore_client import get_history

from google.oauth2 import service_account

logger = logging.getLogger(__name__)

# Próbujemy wykryć ID projektu automatycznie
try:
    _, default_project_id = google.auth.default()
except Exception:
    default_project_id = None

project_id = os.environ.get("VITE_FIREBASE_PROJECT_ID", default_project_id or "project-156a0c69-6d30-45a1-bd9")
location = os.environ.get("GOOGLE_CLOUD_REGION", "us-central1")
credentials_path = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "gcp-credentials.json"),
)

try:
    if os.path.isfile(credentials_path):
        creds = service_account.Credentials.from_service_account_file(credentials_path)
        vertexai.init(project=project_id, location=location, credentials=creds)
        logger.info(f"Vertex AI initialized with JSON credentials for project {project_id} in {location}.")
    else:
        vertexai.init(project=project_id, location=location)
        logger.info(f"Vertex AI initialized with ADC for project {project_id} in {location}.")
except Exception as e:
    logger.error(f"Failed to initialize Vertex AI: {e}")


_SYSTEM_PROMPT = """Jesteś Mistrzem Gry w krótkiej, zamkniętej grze RPG „Voice Fiction” (You are the Game Master in a short, closed RPG game "Voice Fiction"). Prowadzisz gracza przez liniową przygodę składającą się z 3 scen:
1. tawerna (tavern)
2. las z rozwidleniem (forest with a crossroads)
3. pojedynek (duel)

Najważniejsze zasady świata gry:
- Gra ma tylko te 3 sceny.
- Nie wolno dodawać nowych lokacji, nowych zadań pobocznych ani nowych ważnych postaci.
- Główny cel gracza to odzyskanie srebrnego amuletu skradzionego karczmarzowi przez bandytę Rudana.
- Gracz zaczyna grę z mieczem i tarczą.
- Gracz nie może opuścić głównej ścieżki fabularnej.
- W lesie istnieją tylko dwie ścieżki: lewa i prawa. Obie ścieżki ostatecznie prowadzą do tego samego przeciwnika, ale muszą być opisywane jako różne doświadczenia.
- Nie wolno zmieniać sceny bez wyraźnej decyzji gracza.

JĘZYK ODPOWIEDZI (LANGUAGE SUPPORT):
- Odpowiadaj w języku, w którym mówi/zwraca się gracz:
  * Jeśli gracz mówi po angielsku, całą narrację ("segments", "scene_description") generuj w języku angielskim.
  * Jeśli gracz mówi po polsku, generuj w języku polskim.
- Klucze JSON oraz wartości enumów ("status", "hp", "location", "turn_source", "segments", "type") ZAWSZE muszą pozostać w języku angielskim ("active", "game_over", "victory", "tavern", "forest", "duel", "narration", "dialogue", "ai").

Bardzo ważne reguły prowadzenia gry:
- Jeśli gracz rozmawia z karczmarzem, pozostań w scenie tawerny.
- Nie wypychaj gracza z tawerny, dopóki sam nie powie, że wychodzi lub idzie do lasu.
- Jeśli gracz wybiera lewą ścieżkę, opisz lewą ścieżkę.
- Jeśli gracz wybiera prawą ścieżkę, opisz prawą ścieżkę.
- Nie ignoruj wyboru gracza.
- Nie przeskakuj od razu do kolejnej sceny, jeśli gracz dopiero rozpoczął działanie.
- Każda odpowiedź ma reagować na konkretną intencję gracza, a nie wymuszać tempo fabuły.

Styl:
- mroczny, średniowieczny, klimatyczny / dark fantasy, medieval, atmospheric
- krótki i czytelny / concise and clear
- bez rozwlekłych opisów i bez długich monologów
- bez zbędnych pytań i bez zmuszania gracza do natychmiastowego ruchu naprzód
- narracja ma być sugestywna, obrazowa i lekko surowa
- tekst ma brzmieć jak właściwa opowieść fabularna, a nie suchy log systemowy

Bardzo ważna zasada struktury odpowiedzi:
- Odpowiadasz wyłącznie poprawnym JSON-em.
- Nie dodawaj żadnego tekstu poza JSON-em.
- Pole "segments" jest głównym nośnikiem treści fabularnej.
- Nie twórz jednego długiego bloku tekstu, jeśli odpowiedź naturalnie składa się z kilku części.
- Rozdzielaj narrację ("narration") i dosłowne kwestie dialogowe postaci ("dialogue") na osobne elementy tablicy "segments".

Scena 1: Tawerna (Tavern)
- Gracz stoi przed karczmarzem.
- Karczmarz informuje, że bandyta Rudan ukradł mu srebrny amulet, rodzinną pamiątkę, i uciekł do lasu.
- W tej scenie gracz może swobodnie rozmawiać z karczmarzem w granicach tematu.
- Przejście do sceny lasu następuje tylko wtedy, gdy gracz wyraźnie powie, że wychodzi lub rusza do lasu.

Scena 2: Las (Forest)
- Gracz dociera do rozwidlenia dróg: lewej i prawej.
- Obie drogi prowadzą ostatecznie do tego samego miejsca, ale mają różne opisy.
- Jeśli gracz wybierze lewo, prowadź go lewą ścieżką.
- Jeśli gracz wybierze prawo, prowadź go prawą ścieżką.

Scena 3: Pojedynek (Duel)
- Gracz spotyka Rudana i dochodzi do walki.
- Gracz może używać miecza i tarczy.
- Jeśli HP gracza spadnie do 0, status = "game_over".
- Jeśli gracz pokona Rudana i odzyska amulet, status = "victory".
"""

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "status": {
            "type": "STRING",
            "enum": ["active", "game_over", "victory"]
        },
        "hp": {
            "type": "INTEGER"
        },
        "location": {
            "type": "STRING",
            "enum": ["tavern", "forest", "duel"]
        },
        "scene_description": {
            "type": "STRING"
        },
        "turn_source": {
            "type": "STRING",
            "enum": ["ai"]
        },
        "segments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "type": {
                        "type": "STRING",
                        "enum": ["narration", "dialogue"]
                    },
                    "text": {
                        "type": "STRING"
                    }
                },
                "required": ["type", "text"]
            }
        }
    },
    "required": ["status", "hp", "location", "scene_description", "turn_source", "segments"]
}

def process_turn(player_id: str, new_player_action: str) -> dict:
    """
    Wywołuje model Gemini 1.5 Flash z historią gracza.
    """
    history = get_history(player_id, limit=20)
    
    if not history:
        raise ValueError("Cannot process turn: session history is empty.")

    # Inicjalizacja modelu
    model = GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=[_SYSTEM_PROMPT]
    )

    # Budujemy prompt z kontekstem
    context_str = "HISTORIA GRY:\n"
    for turn in history:
        source = turn.get("turn_source", "unknown")
        
        # Jeśli to gracz, pobieramy jego tekst z segmentów
        if source == "player":
            action_text = ""
            for seg in turn.get("segments", []):
                action_text += seg.get("text", "") + " "
            context_str += f"[Gracz]: {action_text.strip()}\n"
            
        # Jeśli to AI, dodajemy jej ostatnie akcje żeby pamiętała o czym mówiła
        elif source == "ai":
            context_str += "[Mistrz Gry]:\n"
            for seg in turn.get("segments", []):
                context_str += f"  - ({seg.get('type')}): {seg.get('text')}\n"

    # Wymuszamy na modelu format JSON zgodny z naszym schematem
    config = GenerationConfig(
        response_mime_type="application/json",
        response_schema=_RESPONSE_SCHEMA,
        temperature=0.7 # Odrobina kreatywności w dialogach i opisach
    )

    prompt = f"{context_str}\n\n[OSTATNIA AKCJA GRACZA]: {new_player_action}\nWygeneruj następną turę (jako JSON) kontynuując tę historię."
    
    logger.info(f"Wysyłam prompt do Gemini (długość: {len(prompt)} znaków)...")
    
    response = model.generate_content(
        prompt,
        generation_config=config
    )
    
    if not response.text:
        raise RuntimeError("Gemini zwróciło pustą odpowiedź.")
        
    try:
        new_turn_state = json.loads(response.text)
    except json.JSONDecodeError as e:
        logger.error(f"Nie udało się sparsować odpowiedzi JSON od Gemini: {response.text}")
        raise RuntimeError(f"Błąd parsowania JSON z Gemini: {e}")

    # Dla pewności upewniamy się, że to AI
    new_turn_state["turn_source"] = "ai"
    
    return new_turn_state
