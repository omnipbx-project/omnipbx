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
    libopus-dev \
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
    libpq5 \
    libsqlite3-0 \
    libssl3 \
    libsrtp2-1 \
    libxml2 \
    odbc-postgresql \
    openssh-client \
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

RUN arch="$(dpkg --print-architecture)" \
    && case "${arch}" in \
      amd64) \
        curl -fsSL "https://downloads.digium.com/pub/telephony/codec_opus/asterisk-22.0/x86-64/codec_opus-22.0-current-x86_64.tar.gz" -o /tmp/codec_opus.tgz \
        && tar -xzf /tmp/codec_opus.tgz -C /tmp \
        && codec_dir="$(find /tmp -maxdepth 1 -type d -name 'codec_opus-*' -print -quit)" \
        && install -m 0644 "${codec_dir}/codec_opus.so" /usr/lib/asterisk/modules/codec_opus.so \
        && install -m 0644 "${codec_dir}/format_ogg_opus.so" /usr/lib/asterisk/modules/format_ogg_opus.so \
        && mkdir -p /var/lib/asterisk/documentation/thirdparty \
        && install -m 0644 "${codec_dir}/codec_opus_config-en_US.xml" /var/lib/asterisk/documentation/thirdparty/codec_opus_config-en_US.xml \
        && rm -rf /tmp/codec_opus.tgz "${codec_dir}" ;; \
      *) \
        echo "codec_opus binary package is unavailable for ${arch}; use an amd64 image for Opus transcoding." >&2 \
        && exit 1 ;; \
    esac

WORKDIR /opt/omnipbx

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app ./app
COPY asterisk-config /etc/asterisk
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 8000 5060/udp 10000-20000/udp

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
