FROM python:3.12-slim-bookworm

WORKDIR /app

# build tools required to compile dtlssocket
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake libtool build-essential \
    && rm -rf /var/lib/apt/lists/*

# install dependencies via uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
COPY vendor/ ./vendor/
# stub out autogen.sh so the build uses the pre-generated configure script from vendor
RUN TINYDTLS=/app/vendor/dtlssocket/DTLSSocket/tinydtls && \
    printf '#!/bin/sh\nexit 0\n' > ${TINYDTLS}/autogen.sh && \
    chmod +x ${TINYDTLS}/autogen.sh && \
    rm -rf ${TINYDTLS}/config.log ${TINYDTLS}/config.status ${TINYDTLS}/dtls_config.h \
           /app/vendor/dtlssocket/build /app/vendor/dtlssocket/DTLSSocket.egg-info
RUN uv sync --frozen --no-dev

# copy application code
COPY config.py coap_client.py devices.py server.py ./
COPY scripts/ ./scripts/

# data files (mounted externally)
VOLUME ["/app/devices.json", "/app/aliases.json", "/app/.tradfri_psk.json"]

EXPOSE 8765

CMD ["uv", "run", "python", "server.py"]
