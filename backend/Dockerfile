# Używamy lekkiego obrazu bazowego Pythona
FROM python:3.11-slim

# Katalog roboczy w kontenerze
WORKDIR /app

# Kopiujemy najpierw requirements.txt i instalujemy zależności
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiujemy resztę kodu
COPY . .

# Cloud Run domyślnie nasłuchuje na porcie 8080.
# Zmienna środowiskowa PORT zostanie wstrzyknięta, jeśli będzie inna.
ENV PORT=8080

# Uruchamiamy aplikację
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
