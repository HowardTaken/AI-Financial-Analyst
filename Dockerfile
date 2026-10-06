# Stage 1: build the React frontend
FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime serving the API and the built frontend from one process
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY analyst/ analyst/
COPY api/ api/
COPY --from=frontend /app/frontend/dist frontend/dist

# Job state is held in process memory, so run exactly one worker.
# Set GEMINI_API_KEY (and optionally SEC_USER_AGENT) at runtime; never bake secrets into the image.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
