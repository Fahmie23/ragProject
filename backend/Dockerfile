# syntax=docker/dockerfile:1.7
FROM python:3.12.14-slim-bookworm AS python-base

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/rag/.cache/huggingface

RUN groupadd --gid "${APP_GID}" rag \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin rag

WORKDIR /app

FROM python-base AS runtime-deps
COPY requirements.lock.txt ./requirements.lock.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.lock.txt

FROM runtime-deps AS app-base
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts
COPY evaluation ./evaluation
RUN mkdir -p /app/data /home/rag/.cache/huggingface \
    && chown -R rag:rag /app /home/rag

FROM app-base AS runtime
USER rag
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=12 \
  CMD python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)); raise SystemExit(0 if d.get('status') == 'ok' else 1)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python-base AS test
COPY requirements-dev.lock.txt ./requirements-dev.lock.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-dev.lock.txt
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts
COPY evaluation ./evaluation
COPY tests ./tests
RUN mkdir -p /app/data /home/rag/.cache/huggingface \
    && chown -R rag:rag /app /home/rag
USER rag
CMD ["python", "-m", "pytest", "-q"]
