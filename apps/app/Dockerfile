FROM debian:bookworm-slim AS asterisk-builder

ARG ASTERISK_VERSION=22.9.0
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libcurl4 \
    libcurl4-openssl-dev \
    libedit-dev \
    libjansson-dev \
    libncurses-dev \
    libpq-dev \
    libsqlite3-dev \
    libssl-dev \
    libsrtp2-dev \
    libxml2-dev \
    pkg-config \
    tar \
    unixodbc-dev \
    uuid-dev \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src

RUN wget -O asterisk.tar.gz "https://downloads.asterisk.org/pub/telephony/asterisk/releases/asterisk-${ASTERISK_VERSION}.tar.gz" \
    && tar -xzf asterisk.tar.gz \
    && mv "asterisk-${ASTERISK_VERSION}" asterisk

WORKDIR /usr/src/asterisk

RUN ./configure --with-pjproject-bundled --without-dahdi --without-pri \
    && make -j"$(nproc)" \
    && make install DESTDIR=/asterisk-root

FROM debian:bookworm-slim

ARG DOCKER_CLI_VERSION=29.1.3
ARG DOCKER_COMPOSE_VERSION=2.40.3
ARG ASTERISK_OPUS_CODEC_URL=https://downloads.digium.com/pub/telephony/codec_opus/asterisk-22.0/x86-64/codec_opus-22.0-current-x86_64.tar.gz
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    libcurl4 \
    libedit2 \
    libjansson4 \
    libncurses6 \
    libopus0 \
    libopusfile0 \
    libpq5 \
    libsqlite3-0 \
    libssl3 \
    libsrtp2-1 \
    libxml2 \
    odbc-postgresql \
    python3 \
    python3-pip \
    tar \
    tini \
    unixodbc \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && arch="$(dpkg --print-architecture)" \
    && case "${arch}" in amd64) docker_arch="x86_64" ;; arm64) docker_arch="aarch64" ;; *) docker_arch="${arch}" ;; esac \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${docker_arch}/docker-${DOCKER_CLI_VERSION}.tgz" -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp \
    && install -m 0755 /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz \
    && case "${arch}" in amd64) compose_arch="x86_64" ;; arm64) compose_arch="aarch64" ;; *) compose_arch="${arch}" ;; esac \
    && curl -fsSL "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${compose_arch}" -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
    && rm -rf /var/lib/apt/lists/*

COPY --from=asterisk-builder /asterisk-root/usr/ /usr/
COPY --from=asterisk-builder /asterisk-root/etc/ /etc/
COPY --from=asterisk-builder /asterisk-root/var/lib/asterisk/ /var/lib/asterisk/
COPY --from=asterisk-builder /asterisk-root/var/spool/asterisk/ /var/spool/asterisk/

RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        tmpdir="$(mktemp -d)" \
        && curl -fsSL "${ASTERISK_OPUS_CODEC_URL}" -o "${tmpdir}/codec_opus.tar.gz" \
        && tar -xzf "${tmpdir}/codec_opus.tar.gz" --strip-components=1 -C "${tmpdir}" \
        && install -m 0755 "${tmpdir}/codec_opus.so" /usr/lib/asterisk/modules/codec_opus.so \
        && install -m 0755 "${tmpdir}/format_ogg_opus.so" /usr/lib/asterisk/modules/format_ogg_opus.so \
        && install -d /var/lib/asterisk/documentation/thirdparty/codec_opus \
        && install -m 0644 "${tmpdir}/codec_opus_config-en_US.xml" /var/lib/asterisk/documentation/thirdparty/codec_opus_config-en_US.xml \
        && install -m 0644 "${tmpdir}/LICENSE" /var/lib/asterisk/documentation/thirdparty/codec_opus/LICENSE \
        && install -m 0644 "${tmpdir}/README" /var/lib/asterisk/documentation/thirdparty/codec_opus/README \
        && rm -rf "${tmpdir}"; \
    else \
        echo "Skipping codec_opus install: no official Asterisk 22 codec_opus package configured for this architecture"; \
    fi

WORKDIR /opt/omnipbx

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app ./app
COPY asterisk-config /etc/asterisk
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 8000 5060/udp 10000-10100/udp

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
