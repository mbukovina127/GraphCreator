# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into an isolated venv (works with arbitrary runtime UID)
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

# Create a non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
RUN chown appuser:appuser /app

# Bring the venv from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Copy application code (excluding __pycache__)
COPY --chown=appuser:appuser src/*.py ./src/
COPY --chown=appuser:appuser src/code_analyzer/*.py ./src/code_analyzer/
COPY --chown=appuser:appuser src/code_analyzer/ast_metrics/*.py ./src/code_analyzer/ast_metrics/
COPY --chown=appuser:appuser src/file_system_analyzer/*.py ./src/file_system_analyzer/
COPY --chown=appuser:appuser src/graph_builder/*.py ./src/graph_builder/
COPY --chown=appuser:appuser src/ray_implementation/*.py ./src/ray_implementation/
COPY --chown=appuser:appuser src/ray_implementation/builders/*.py ./src/ray_implementation/builders/
COPY --chown=appuser:appuser src/ray_implementation/builders/cpg/*.py ./src/ray_implementation/builders/cpg/
COPY --chown=appuser:appuser src/ray_implementation/dto/*.py ./src/ray_implementation/dto/
COPY --chown=appuser:appuser src/ray_implementation/managers/*.py ./src/ray_implementation/managers/
COPY --chown=appuser:appuser src/ray_implementation/structures/*.py ./src/ray_implementation/structures/
COPY --chown=appuser:appuser src/ray_implementation/graph_metrics/*.py ./src/ray_implementation/graph_metrics/
COPY --chown=appuser:appuser src/ray_implementation/utils/*.py ./src/ray_implementation/utils/

# Copy CPG schemas for validation
COPY --chown=appuser:appuser schema/v1 /app/schema/v1

# Set Python path
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV RAY_TMPDIR=/tmp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health')" || exit 1

# Expose port
EXPOSE 8080

USER appuser

# Run the application
CMD ["python", "-m", "uvicorn", "dapr_handler:app", "--host", "0.0.0.0", "--port", "8080"]
