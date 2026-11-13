# Multi-stage Dockerfile for rc-typing-registry
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.15 /uv /bin/uv

# Copy common and registry packages
COPY packages/rctyping_common /build/packages/rctyping_common
COPY registry /build/registry

# Install dependencies into virtualenv
ENV VIRTUAL_ENV="/app/.venv"
RUN uv venv /app/.venv && \
    uv pip install --no-cache /build/packages/rctyping_common /build/registry

# --- Final Runtime Stage ---
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN groupadd -r rctyping && useradd -r -g rctyping -u 1000 rctyping

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

ENV RCTYPING_REGISTRY_DATA_DIR="/data"

RUN mkdir -p /data/keys && chown -R rctyping:rctyping /data /app

USER rctyping
VOLUME ["/data"]
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/.well-known/rctyping-registry.json')" || exit 1

ENTRYPOINT ["rctyping-registry"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8001"]
