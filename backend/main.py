from fastapi import FastAPI
import os
import uvicorn

from api import router

app = FastAPI()
app.include_router(router)

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    # Cloud Run domyślnie używa portu 8080 lub wstrzykuje go przez zmienną środowiskową PORT
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
