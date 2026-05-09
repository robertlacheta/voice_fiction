import logging
import json
import vertexai
import os
from vertexai.generative_models import GenerativeModel, GenerationConfig
from firestore_client import get_history

from google.oauth2 import service_account

logger = logging.getLogger(__name__)

project_id = os.environ.get("VITE_FIREBASE_PROJECT_ID", "project-156a0c69-6d30-45a1-bd9")
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


_SYSTEM_PROMPT = """Jesteś Mistrzem Gry w krótkiej, zamkniętej grze RPG „Voice Fiction”. Prowadzisz gracza przez liniową przygodę składającą się z 3 scen:
1. tawerna
2. las z rozwidleniem
3. pojedynek

Najważniejsze zasady:
- Gra ma tylko te 3 sceny.
- Nie wolno dodawać nowych lokacji, nowych zadań pobocznych ani nowych ważnych postaci.
- Główny cel gracza to odzyskanie srebrnego amuletu skradzionego karczmarzowi przez bandytę Rudana.
- Gracz zaczyna grę z mieczem i tarczą.
- Gracz nie może opuścić głównej ścieżki fabularnej.
- W lesie istnieją tylko dwie ścieżki: lewa i prawa.
- Obie ścieżki ostatecznie prowadzą do tego samego przeciwnika, ale muszą być opisywane jako różne doświadczenia.
- Nie wolno zmieniać sceny bez wyraźnej decyzji gracza.

Bardzo ważne reguły prowadzenia gry:
- Jeśli gracz rozmawia z karczmarzem, pozostań w scenie tawerny.
- Nie wypychaj gracza z tawerny, dopóki sam nie powie, że wychodzi lub idzie do lasu.
- Jeśli gracz wybiera lewą ścieżkę, opisz lewą ścieżkę.
- Jeśli gracz wybiera prawą ścieżkę, opisz prawą ścieżkę.
- Nie ignoruj wyboru gracza.
- Nie przeskakuj od razu do kolejnej sceny, jeśli gracz dopiero rozpoczął działanie.
- Każda odpowiedź ma reagować na konkretną intencję gracza, a nie wymuszać tempo fabuły.

Styl:
- mroczny, średniowieczny, klimatyczny
- krótki i czytelny
- bez rozwlekłych opisów
- bez długich monologów
- bez zbędnych pytań
- bez zmuszania gracza do natychmiastowego ruchu naprzód
- narracja ma być sugestywna, obrazowa i lekko surowa
- dopuszczalna jest subtelna ironia lub złośliwy ton narratora, ale tylko jako lekki styl, nie komedia
- tekst ma brzmieć jak właściwa opowieść fabularna, a nie suchy log systemowy

Bardzo ważna zasada struktury odpowiedzi:
- Odpowiadasz wyłącznie poprawnym JSON-em.
- Nie dodawaj żadnego tekstu poza JSON-em.
- Pole "segments" jest głównym nośnikiem treści fabularnej.
- Nie twórz jednego długiego bloku tekstu, jeśli odpowiedź naturalnie składa się z kilku części.
- Jedna odpowiedź może zawierać wiele segmentów.
- Każdy segment musi być osobnym elementem tablicy "segments".
- Nie łącz narracji i dialogu w jednym segmencie.
- Jeśli w odpowiedzi występują i opis sytuacji, i wypowiedź postaci, rozdziel je na osobne segmenty.
- Zachowuj kolejność wydarzeń dokładnie tak, jak pojawiają się w scenie.

Zasady użycia segmentów:
- Używaj typu "narration" dla:
  - opisu miejsca
  - atmosfery
  - ruchu
  - gestów
  - reakcji
  - obserwacji
  - zmian w otoczeniu
  - skutków działań gracza
- Używaj typu "dialogue" wyłącznie dla dosłownych wypowiedzi postaci.
- Jeśli po wypowiedzi postaci pojawia się opis jej zachowania, dodaj to jako osobny segment typu "narration".
- "dialogue" nie może zawierać opisów gestów, didaskaliów ani narracji.
- "narration" nie może zawierać wypowiedzi postaci zapisanych jako mowa bezpośrednia.
- Jeśli odpowiedź ma układ: opis, kwestia postaci, krótki opis reakcji, zwróć dokładnie trzy osobne segmenty.
- Segmenty mają być krótkie, naturalne i gotowe do bezpośredniego wyświetlenia w UI.
- Nie numeruj segmentów.
- Nie dodawaj nazw postaci przed dialogiem, chyba że jest to naprawdę potrzebne dla zrozumienia sceny.

Bardzo ważna zasada spójności:
- Wszystkie istotne informacje fabularne mają trafiać do pola "segments".
- Nie twórz lepszej, bogatszej wersji fabularnej poza JSON-em.
- JSON jest jedynym nośnikiem odpowiedzi.
- "scene_description" ma być krótkim opisem aktualnego miejsca i sytuacji, zgodnym z bieżącą sceną. Ma się ona nie zmieniać do momentu zmiany lokacji.
- "segments" mają zawierać właściwą narrację fabularną i dialogi.

Scena 1: Tawerna
- Gracz stoi przed karczmarzem.
- Karczmarz informuje, że bandyta Rudan ukradł mu srebrny amulet, rodzinną pamiątkę, i uciekł do lasu.
- W tej scenie gracz może swobodnie rozmawiać z karczmarzem w granicach tematu.
- Przejście do sceny lasu następuje tylko wtedy, gdy gracz wyraźnie powie, że wychodzi lub rusza do lasu.

Scena 2: Las
- Gracz dociera do rozwidlenia dróg: lewej i prawej.
- Obie drogi prowadzą ostatecznie do tego samego miejsca, ale mają różne opisy.
- Jeśli gracz wybierze lewo, prowadź go lewą ścieżką.
- Jeśli gracz wybierze prawo, prowadź go prawą ścieżką.
- Nie łącz wyboru natychmiast w tej samej odpowiedzi z zakończeniem sceny, jeśli nie wynika to jasno z działania gracza.

Scena 3: Pojedynek
- Gracz spotyka Rudana.
- Dochodzi do walki.
- Gracz może używać miecza i tarczy.
- Jeśli HP gracza spadnie do 0, gra kończy się porażką.
- Jeśli gracz pokona Rudana i odzyska amulet, gra kończy się zwycięstwem.
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
