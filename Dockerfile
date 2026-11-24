# --- frontend
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- backend + worker
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
COPY start.sh /app/start.sh
ENV FRONTEND_DIST=/app/frontend/dist STORAGE_DIR=/data/storage DATABASE_URL=sqlite:////data/clipes.db PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
CMD ["/app/start.sh"]
