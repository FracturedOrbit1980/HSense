FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-osd \
        poppler-utils \
        libglib2.0-0 \
        libgomp1 \
        libheif1 \
        libde265-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=7860 \
    PYTHONUNBUFFERED=1 \
    HS_OCR_BACKEND=tesseract

EXPOSE 7860

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 300 web:app"]
