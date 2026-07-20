FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.lock pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install --require-hashes -r requirements.lock \
    && pip check

RUN addgroup --system safemeal \
    && adduser --system --ingroup safemeal --home /app safemeal

COPY --chown=safemeal:safemeal . .

USER safemeal

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=4)"]

CMD ["python", "-m", "uvicorn", "back.main:application", "--host", "0.0.0.0", "--port", "8000"]
