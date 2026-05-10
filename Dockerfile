# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into an isolated venv so the runtime stage needs no build tools
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
RUN chown appuser:appuser /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Copy entire src/ package tree
COPY --chown=appuser:appuser src/ ./src/

# CPG JSON schemas used for validation:
#   graph_collector.py  →  schema_lua/cpg.node.schema.json
#   dapr_handler.py     →  schema/v1/cpg.export.schema.json
COPY --chown=appuser:appuser schema/ ./schema/v1/
COPY --chown=appuser:appuser schema/ ./schema_lua/

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV RAY_TMPDIR=/tmp

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health')" || exit 1

EXPOSE 8080

USER appuser

CMD ["python", "-m", "uvicorn", "dapr_handler:app", "--host", "0.0.0.0", "--port", "8080"]
