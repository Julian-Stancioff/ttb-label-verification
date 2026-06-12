FROM python:3.12-slim

# Tesseract OCR engine (for word-level bounding boxes on labels).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY frontend frontend

# Persistent data (SQLite review queue + stored label images). Dokploy mounts a
# volume here; the app falls back to ./data locally when /data is absent.
RUN mkdir -p /data
VOLUME ["/data"]
ENV DATA_DIR=/data

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
