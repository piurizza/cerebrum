FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

WORKDIR /app
# `copy`, not uv's default hardlink: the cache mount below is a separate
# filesystem from /app, so hardlinking would fail over to a copy anyway
# (with a warning).
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
# The cache mount keeps downloaded wheels between builds, so a rebuild
# after a lockfile change only fetches what changed.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# uv itself (~50 MB) is only needed to resolve and install the venv, so the
# runtime image is plain Python with the finished venv copied in. Same
# Python base as the uv image above -- the venv's interpreter symlink
# points at /usr/local/bin/python3, which this image provides too.
FROM python:3.12-slim-bookworm

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY src/ src/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

EXPOSE 8000
CMD ["uvicorn", "cerebrum.main:app", "--host", "0.0.0.0", "--port", "8000"]
