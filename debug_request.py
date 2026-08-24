import requests

res = requests.post(
    "http://localhost:8080/api/recognize",
    data={"player_id": "test"},
    files={"audio": ("recording.webm", b"dummy_data", "audio/webm")}
)
print(res.status_code)
print(res.text)
