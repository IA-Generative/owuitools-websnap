# ----- Build stage -----
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ----- Runtime stage -----
FROM python:3.11-slim AS runtime

# Labels for multi-arch awareness
LABEL org.opencontainers.image.title="browser-use"
LABEL org.opencontainers.image.description="Web extraction service"

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app/ ./app/
COPY entrypoint.py .

# Runtime deps for pymupdf (optional — skip if unavailable on this arch)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 libharfbuzz0b libjbig2dec0 libjpeg62-turbo libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/* || true

USER appuser

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000 8088

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/healthz').raise_for_status()"

CMD ["python", "entrypoint.py"]
