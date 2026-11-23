# syntax=docker/dockerfile:1
# The API image for Render Free (512 MB, 0.1 CPU). Build from the repository root, because the
# API reads config/ and taxonomy/ beside backend/:
#
#     docker build -f backend/Dockerfile -t shortlist-api .

FROM python:3.12-slim

# Copy the uv binary from its official image instead of installing it with pip.
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/backend/.venv \
    FASTEMBED_CACHE_PATH=/srv/models \
    EMBED_CACHE_DIR=/srv/models

# /srv mirrors the repository, so app/core/config.py finds the data files the same way it
# does on a laptop: REPO_ROOT is three levels above app/core/.
WORKDIR /srv/backend

# Dependencies first, code second: editing app code does not reinstall every package.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

ENV PATH="/srv/backend/.venv/bin:$PATH"

# Bake the embedding model into the image, so a cold start never downloads it.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY config /srv/config
COPY taxonomy /srv/taxonomy
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app

# Never run the server as root inside the container.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /srv/models
USER appuser

EXPOSE 8000
# Migrate (over DIRECT_DATABASE_URL when set), then serve. One worker fits 512 MB.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
