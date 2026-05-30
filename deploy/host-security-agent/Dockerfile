FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    fail2ban \
    iproute2 \
    iptables \
    ufw \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/omnipbx-host-security-agent
COPY agent.py ./agent.py

EXPOSE 8765

CMD ["python3", "/opt/omnipbx-host-security-agent/agent.py"]
