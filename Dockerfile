# syntax=docker/dockerfile:1
# Production Containerfile for FortifiedReg Fleet (v0.3.0)
# Multi-stage minimal footprint, non-root user, fail-closed runtime.

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install pinned upstream dependencies from GitHub RC sealing pins with exact pinned dependencies
RUN pip install --no-cache-dir \
    "git+https://github.com/prodocux/pdx-artifact-engine.git@61cff57ec7938165234dd895177dccade7ac1a5f#subdirectory=packages/pdx_artifact_core" \
    "git+https://github.com/prodocux/prodocux.git@c8acd2ba69c23458cb2589d8450246fe9b16424f" \
    uvicorn==0.34.0 \
    fastapi==0.115.6 \
    pydantic==2.10.4 \
    jsonschema==4.26.0 \
    pyjwt==2.13.0 \
    passlib==1.7.4 \
    requests==2.34.2 \
    httpx==0.28.1 \
    pypdf==5.1.0 \
    python-docx==1.1.2 \
    openpyxl==3.1.5 \
    python-pptx==1.0.2

# Final Runtime Image
FROM python:3.12-slim AS runner

ARG GIT_COMMIT=unknown
LABEL org.opencontainers.image.title="fortifiedreg-fleet"
LABEL org.opencontainers.image.version="0.3.0"
LABEL org.opencontainers.image.revision="${GIT_COMMIT}"
LABEL org.opencontainers.image.vendor="ProDocuX FortifiedReg"
LABEL org.opencontainers.image.description="FortifiedReg Fleet - Governed dossier production for regulated products"

WORKDIR /app

# Copy installed site-packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create unprivileged runtime user and data directories
RUN useradd -m -u 10001 fleetuser && \
    mkdir -p /app/data /app/artifacts /app/schemas /app/compatibility && \
    chown -R fleetuser:fleetuser /app

# Copy Fleet source codebase
COPY --chown=fleetuser:fleetuser apps /app/apps
COPY --chown=fleetuser:fleetuser packages /app/packages
COPY --chown=fleetuser:fleetuser schemas /app/schemas
COPY --chown=fleetuser:fleetuser fixtures /app/fixtures
COPY --chown=fleetuser:fleetuser compatibility /app/compatibility
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
