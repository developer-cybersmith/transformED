# ─── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# System-level dependencies (OCR + MuPDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmupdf-dev \
    libffi-dev \
    libssl-dev \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /build

# Copy dependency manifest first for layer caching
COPY pyproject.toml ./

# Create a virtual environment and install deps into it
RUN uv venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv"
ENV PATH="/opt/venv/bin:$PATH"

RUN uv pip install --no-cache ".[dev]" 2>/dev/null || uv pip install --no-cache .

# Copy application source
COPY app/ ./app/

# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Only the runtime system deps (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for least-privilege execution
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv"
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
WORKDIR /app
COPY --from=builder /build/app ./app/

# Ownership
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
