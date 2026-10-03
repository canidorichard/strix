FROM golang:1.24 AS go

FROM python:3.12-slim AS builder
COPY --from=go /usr/local/go /usr/local/go
ENV PATH="/usr/local/go/bin:${PATH}"
RUN pip install --no-cache-dir uv
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY strix/ ./strix/
COPY scripts/tui_sidecar_hook.py ./scripts/tui_sidecar_hook.py
RUN uv build --wheel

FROM python:3.12-slim
COPY --from=builder /src/dist/*.whl /tmp/wheels/
RUN apt-get update && \
    apt-get install -y --no-install-recommends docker-cli && \
    rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels

WORKDIR /workspace
ENTRYPOINT ["strix"]
