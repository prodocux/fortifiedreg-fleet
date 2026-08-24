# =============================================================================
# Stage 1: Builder — compile wheel from public GitHub pin
# =============================================================================
FROM python:3.12-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends git gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Build wheels directly from the pinned public release of ProDocuX
RUN pip wheel --no-cache-dir \
    "git+https://github.com/prodocux/prodocux.git@bcbe39cd095b06238a836268fab7092466d20ab0" \
    -w /wheels

# =============================================================================
# Stage 2: Minimal Runtime — zero git, compiler, or build cache
# =============================================================================
FROM python:3.12-slim AS runner

LABEL org.opencontainers.image.title="prodocux-intake"
LABEL org.opencontainers.image.description="ProDocuX Kernel — Deterministic Document Intake & Profiling Service"
LABEL org.opencontainers.image.source="https://github.com/prodocux/prodocux"
LABEL org.opencontainers.image.revision="bcbe39cd095b06238a836268fab7092466d20ab0"
LABEL org.opencontainers.image.version="0.3.0rc1"
LABEL org.opencontainers.image.vendor="ProDocuX"

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Run as non-root user
RUN useradd -m -u 10001 prodocuxuser
USER prodocuxuser

EXPOSE 8080

ENTRYPOINT ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
