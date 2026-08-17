# syntax=docker/dockerfile:1
# Production Containerfile for FortifiedReg Fleet (v0.3.0)
# Multi-stage minimal footprint, non-root user, fail-closed runtime.

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install pinned upstream dependencies from GitHub
RUN pip install --no-cache-dir \
    "git+https://github.com/prodocux/pdx-artifact-engine.git@93ec3514261bf89e9cb88b79f524e3fbc5ef4402#subdirectory=packages/pdx_artifact_core" \
    "git+https://github.com/prodocux/prodocux.git@7a1d820639910c1d92b31de6eaf0a371f7386182" \
    uvicorn \
    fastapi \
    pydantic \
    jsonschema \
    pyjwt \
    passlib \
    requests \
    httpx

# Final Runtime Image
FROM python:3.12-slim AS runner

WORKDIR /app

# Copy installed site-packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create unprivileged runtime user and data directories
RUN useradd -m -u 10001 fleetuser && \
    mkdir -p /app/data /app/artifacts /app/schemas && \
    chown -R fleetuser:fleetuser /app

# Copy Fleet source codebase
COPY --chown=fleetuser:fleetuser apps /app/apps
COPY --chown=fleetuser:fleetuser packages /app/packages
COPY --chown=fleetuser:fleetuser schemas /app/schemas
COPY --chown=fleetuser:fleetuser fixtures /app/fixtures
COPY --chown=fleetuser:fleetuser pyproject.toml /app/pyproject.toml
COPY --chown=fleetuser:fleetuser README.md /app/README.md

# Set Python path to resolve Fleet packages directly
ENV PYTHONPATH="/app/packages/fleet-governance-core/src:/app/packages/fleet-domain-cosmetics/src:/app/packages/fleet-adapter-pdx/src:/app/packages/fleet-adapter-prodocux/src:/app/packages/fleet-adapter-google-adk/src:/app/packages/fleet-adapter-gcp/src:/app/packages/fleet-adapter-local/src:/app/apps/fleet-api/src"
ENV FLEET_ENV="production"
ENV FLEET_DB_PATH="/app/data/fleet.db"
ENV FLEET_ARTIFACTS_DIR="/app/artifacts"
ENV PORT=8000

USER fleetuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health')" || exit 1

ENTRYPOINT ["uvicorn", "fleet_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
