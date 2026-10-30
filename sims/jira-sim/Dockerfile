# jira-sim — Jira Cloud REST v3 + Xray Cloud alt kümesi simülatörü
FROM ghcr.io/astral-sh/uv:0.8@sha256:1d31be550ff927957472b2a491dc3de1ea9b5c2d319a9cea5b6a48021e2990a6 AS uv

FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    JIRA_SIM_DATA=/data/jira.json

WORKDIR /app

# Önce yalnızca bağımlılıklar (katman önbelleği)
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --system --uid 10001 --no-create-home app \
    && mkdir -p /data && chown 10001:10001 /data

USER 10001
VOLUME ["/data"]
EXPOSE 8090
CMD ["uvicorn", "jira_sim.app:app", "--host", "0.0.0.0", "--port", "8090"]
