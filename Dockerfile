# One image, one web service: Node builds the React app, then Django (gunicorn + WhiteNoise)
# serves the API at /api/ and the app everywhere else.

# ---- 1. Build the frontend ----
FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. Python runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FRONTEND_DIST=/app/frontend/dist \
    CACHE_DB=/app/data/cache.sqlite3

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
# Pre-compressed .gz copies, so WhiteNoise serves the 1.3 MB bundle as ~360 KB without
# compressing on every request.
RUN python -m whitenoise.compress /app/frontend/dist

# Run as an unprivileged user; it only needs to write the SQLite provider cache.
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown app /app/data
USER app

# Render sets PORT (10000 by default). Threads, because a plan mostly waits on HERE and
# Open-Meteo; the timeout covers a cold plan plus one rate-limit retry.
EXPOSE 10000
CMD ["sh", "-c", "exec gunicorn config.wsgi --bind 0.0.0.0:${PORT:-10000} --workers 2 --threads 4 --timeout 60 --access-logfile -"]
