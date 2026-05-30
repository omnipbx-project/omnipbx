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

ARG DOCKER_COMPOSE_VERSION=2.40.3
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    docker.io \
    git \
    libcurl4 \
    libedit2 \
    libjansson4 \
    libncurses6 \
    libpq5 \
    libsqlite3-0 \
    libssl3 \
    libxml2 \
    odbc-postgresql \
    python3 \
    python3-pip \
    tini \
    unixodbc \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && arch="$(dpkg --print-architecture)" \
    && case "${arch}" in amd64) compose_arch="x86_64" ;; arm64) compose_arch="aarch64" ;; *) compose_arch="${arch}" ;; esac \
    && curl -fsSL "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${compose_arch}" -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
    && rm -rf /var/lib/apt/lists/*

COPY --from=asterisk-builder /asterisk-root/usr/ /usr/
COPY --from=asterisk-builder /asterisk-root/etc/ /etc/
COPY --from=asterisk-builder /asterisk-root/var/lib/asterisk/ /var/lib/asterisk/
COPY --from=asterisk-builder /asterisk-root/var/spool/asterisk/ /var/spool/asterisk/

WORKDIR /opt/omnipbx

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app ./app
COPY asterisk-config /etc/asterisk
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 8000 5060/udp 10000-10100/udp

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
