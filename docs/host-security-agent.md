# OmniPBX Host Security Agent

The host security agent is the safe way for OmniPBX to manage PBX firewall and fail2ban actions.

It accepts only fixed actions:

- `status`
- `firewall_status`
- `fail2ban_status`
- `allow_ip`
- `block_ip`
- `unblock_ip`
- `fail2ban_unban`

It does not accept raw shell commands.

## Docker Compose

1. Add a strong token to `deploy/.env`:

```env
OMNIPBX_HOST_SECURITY_AGENT_TOKEN=change-this-long-random-token
OMNIPBX_HOST_SECURITY_AGENT_URL=http://127.0.0.1:8765
OMNIPBX_SECURITY_AGENT_EMERGENCY_ALLOWLIST=127.0.0.1,::1,YOUR_ADMIN_IP
```

2. Start the agent:

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.security-agent.yaml --profile host-security up -d host-security-agent
```

3. Restart OmniPBX app so it reads the agent URL/token:

```bash
docker compose -f deploy/compose.yaml restart app
```

## Safety

- The agent defaults to dry-run behavior for UI tests.
- The agent refuses to block emergency allowlist networks.
- Keep your admin IP in `OMNIPBX_SECURITY_AGENT_EMERGENCY_ALLOWLIST`.
- Do not expose port `8765` publicly.
