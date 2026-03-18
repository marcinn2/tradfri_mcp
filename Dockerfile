FROM python:3.12-slim-bookworm

WORKDIR /app

# dtlssocket 編譯所需的 build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake libtool build-essential \
    && rm -rf /var/lib/apt/lists/*

# uv 安裝依賴
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
COPY vendor/ ./vendor/
# 讓 autogen.sh 變成 no-op，直接用 vendor 裡預先產生的 configure script
RUN TINYDTLS=/app/vendor/dtlssocket/DTLSSocket/tinydtls && \
    printf '#!/bin/sh\nexit 0\n' > ${TINYDTLS}/autogen.sh && \
    chmod +x ${TINYDTLS}/autogen.sh && \
    rm -rf ${TINYDTLS}/config.log ${TINYDTLS}/config.status ${TINYDTLS}/dtls_config.h \
           /app/vendor/dtlssocket/build /app/vendor/dtlssocket/DTLSSocket.egg-info
RUN uv sync --frozen --no-dev

# 複製程式碼
COPY config.py coap_client.py devices.py server.py ./

# 資料檔（外部 mount）
VOLUME ["/app/devices.json", "/app/aliases.json", "/app/.tradfri_psk.json"]

EXPOSE 8765

CMD ["uv", "run", "python", "server.py"]
