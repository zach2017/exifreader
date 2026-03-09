# ─────────────────────────────────────────────────────────────
# TextExtract Worker – Memory-Optimised Docker Image
# ─────────────────────────────────────────────────────────────
# Build:  docker build -t textextract-worker .
# Run:    docker run --memory=512m --memory-swap=512m \
#           --tmpfs /tmp:rw,size=2g \
#           --env-file .env textextract-worker
# ─────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

# ── System hardening & minimal footprint ──────────────────────
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libmupdf-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ── Python tuning for low-memory containers ───────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONMALLOC=malloc \
    MALLOC_TRIM_THRESHOLD_=65536 \
    MALLOC_MMAP_THRESHOLD_=131072 \
    PYTHONGC=1

# ── App directory ─────────────────────────────────────────────
WORKDIR /app

# ── Install Python deps (cached layer) ───────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache/pip

# ── Copy application code ────────────────────────────────────
COPY app.py processors.py ./

# ── Scratch space for temp files (prefer --tmpfs at runtime) ──
RUN mkdir -p /tmp/docworker && chmod 1777 /tmp/docworker

# ── Non-root user ────────────────────────────────────────────
RUN groupadd -r worker && useradd -r -g worker -d /app worker && \
    chown -R worker:worker /app /tmp/docworker
USER worker

# ── Health / entry ───────────────────────────────────────────
STOPSIGNAL SIGTERM
CMD ["python", "app.py"]
