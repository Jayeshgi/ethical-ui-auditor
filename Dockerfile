FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONPATH=/app/backend

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt alembic.ini ./
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch>=2.6,<3.0" \
        "torchvision>=0.21,<1.0" \
    && pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /app/runtime_data /app/model_artifacts \
    && chown -R pwuser:pwuser /app

USER pwuser
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
