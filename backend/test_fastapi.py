import asyncio
from fastapi import FastAPI, UploadFile, File
from fastapi.testclient import TestClient

app = FastAPI()

@app.post("/test")
async def test_upload(audio: UploadFile = File(...)):
    return {"content_type": audio.content_type, "filename": audio.filename}

client = TestClient(app)
res = client.post("/test", files={"audio": ("recording.webm", b"dummy", "audio/webm;codecs=opus")})
print(res.json())
