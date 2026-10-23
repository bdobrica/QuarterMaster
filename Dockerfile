FROM python:3.13-slim-trixie@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    QM_DATA_DIR=/data \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN python -m pip install --no-cache-dir uv==0.12.19
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY quartermaster ./quartermaster
RUN uv sync --locked --no-dev --no-editable --no-cache \
    && groupadd --gid 10001 quartermaster \
    && useradd --uid 10001 --gid 10001 --no-create-home quartermaster \
    && mkdir /data \
    && chown 10001:10001 /data

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "quartermaster.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]
