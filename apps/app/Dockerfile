FROM debian:bookworm-slim

ARG ASTERISK_VERSION=22.9.0
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    docker.io \
    git \
    libcurl4 \
    libcurl4-openssl-dev \
    libedit-dev \
    libedit2 \
    libjansson-dev \
    libjansson4 \
    libncurses-dev \
    libncurses6 \
    libsqlite3-0 \
    libsqlite3-dev \
    libssl-dev \
    libssl3 \
    libxml2 \
    libxml2-dev \
    pkg-config \
    python3 \
    python3-dev \
    python3-pip \
    tar \
    tini \
    uuid-dev \
    wget \
    build-essential \
    && if apt-cache show docker-compose-plugin >/dev/null 2>&1; then apt-get install -y --no-install-recommends docker-compose-plugin; elif apt-cache show docker-compose-v2 >/dev/null 2>&1; then apt-get install -y --no-install-recommends docker-compose-v2; fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src

RUN wget -O asterisk.tar.gz "https://downloads.asterisk.org/pub/telephony/asterisk/releases/asterisk-${ASTERISK_VERSION}.tar.gz" \
    && tar -xzf asterisk.tar.gz \
    && mv "asterisk-${ASTERISK_VERSION}" asterisk

WORKDIR /usr/src/asterisk

RUN ./configure --with-pjproject-bundled --without-dahdi --without-pri \
    && make -j"$(nproc)" \
    && make install \
    && cd / \
    && rm -rf /usr/src/asterisk /usr/src/asterisk.tar.gz \
    && apt-get purge -y --auto-remove \
        build-essential \
        libcurl4-openssl-dev \
        libedit-dev \
        libjansson-dev \
        libncurses-dev \
        libsqlite3-dev \
        libssl-dev \
        libxml2-dev \
        pkg-config \
        python3-dev \
        uuid-dev \
        wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/omnipbx

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app ./app
COPY asterisk-config /etc/asterisk
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

EXPOSE 8000 5060/udp 10000-10100/udp

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
