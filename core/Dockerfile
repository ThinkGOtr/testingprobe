# core-api, core-worker ve migrate aynı imajdan farklı komutlarla çalışır.
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

COPY --from=ghcr.io/astral-sh/uv:0.8@sha256:1d31be550ff927957472b2a491dc3de1ea9b5c2d319a9cea5b6a48021e2990a6 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin tp

USER 10001
EXPOSE 8000
CMD ["uvicorn", "tp_core.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
