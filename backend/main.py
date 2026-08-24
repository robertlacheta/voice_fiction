import os

# Wymuszenie identyfikatora projektu jako string zamiast numeru projektu z Cloud Run Metadata
_PROJECT_ID = os.environ.get("VITE_FIREBASE_PROJECT_ID", "project-156a0c69-6d30-45a1-bd9")
os.environ["GOOGLE_CLOUD_PROJECT"] = _PROJECT_ID
os.environ["GCLOUD_PROJECT"] = _PROJECT_ID

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api import router

app = FastAPI()

# Dozwolone originy frontendu
_allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,"
        "https://voice-fiction-app-293322474475.europe-central2.run.app",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    # Cloud Run domyślnie używa portu 8080 lub wstrzykuje go przez zmienną środowiskową PORT
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
