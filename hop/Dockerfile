FROM apache/hop:2.19.0 AS hop
FROM eclipse-temurin:21.0.12_8-jre-jammy AS java

FROM python:3.12.7-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=hop /opt/hop /opt/hop
ENV JAVA_HOME=/opt/java/openjdk HOP_JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/venv/bin:/opt/java/openjdk/bin:$PATH \
    UV_PROJECT_ENVIRONMENT=/opt/venv PYTHONUNBUFFERED=1 PYTHON=python
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra db
COPY src/ src/
COPY cards/ cards/
COPY models/ models/
RUN uv sync --frozen --inexact --extra db
COPY hop/ hop/
RUN /opt/hop/hop-conf.sh --project=parltopics --project-create --project-home=/app/hop
ENTRYPOINT ["/opt/hop/hop-run.sh", "--project=parltopics", "--runconfig=local", "--file=/app/hop/nightly.hwf", "--level=Basic"]
