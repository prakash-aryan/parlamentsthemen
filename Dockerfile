FROM node:24.11.1-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12.7-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra db
RUN uv pip install --python /opt/venv/bin/python --index-url https://download.pytorch.org/whl/cpu "torch==2.14.1" \
 && uv pip install --python /opt/venv/bin/python "sentence-transformers==6.1.0" "transformers==5.20.1"
COPY src/ src/
COPY cards/ cards/
COPY models/ models/
RUN uv sync --frozen --inexact --extra db
COPY --from=web /web/out web/out
EXPOSE 8765
CMD ["uvicorn", "parltopics.api:app", "--host", "0.0.0.0", "--port", "8765"]
