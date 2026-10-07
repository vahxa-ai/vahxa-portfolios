# Vahxa Portfolios: React app + FastAPI in one image.
#   docker build -t vahxa-portfolios .
#   docker run -p 8080:8080 vahxa-portfolios

# ---------------------------------------------------------------- frontend build
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- app
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt \
 && python -c "import fastapi, jwt, google.cloud.firestore"

COPY portal/ portal/
COPY --from=web /web/dist frontend/dist

RUN useradd --create-home --uid 1000 portal
USER portal

EXPOSE 8080
# Cloud Run sets PORT.
CMD ["sh", "-c", "exec uvicorn portal.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips '*'"]
