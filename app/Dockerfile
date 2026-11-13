# Multi-stage Dockerfile for rc-typing-app
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.15 /uv /bin/uv

# Copy common package and app package
COPY packages/rctyping_common /build/packages/rctyping_common
COPY app /build/app
COPY pyproject.toml /build/pyproject.toml

# Install dependencies into virtualenv
ENV UV_PROJECT_ENVIRONMENT="/app/.venv"
RUN uv venv /app/.venv && \
    uv pip install --no-cache /build/packages/rctyping_common /build/app

# --- Final Runtime Stage ---
FROM python:3.12-slim AS runtime

WORKDIR /app

# Create non-root user
RUN groupadd -r rctyping && useradd -r -g rctyping -u 1000 rctyping

# Copy virtualenv from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy corpus data into runtime
COPY corpus/data /app/corpus/data
ENV RCTYPING_CORPUS_DIR="/app/corpus/data"
ENV RCTYPING_DATA_DIR="/data"

# Create /data directory for keys & sqlite
RUN mkdir -p /data/keys && chown -R rctyping:rctyping /data /app

USER rctyping
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/categories')" || exit 1

ENTRYPOINT ["rctyping-app"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
