# Phase 1 Scope

Phase 1 is the smallest end-to-end OmniPBX foundation.

## In Scope

- Docker Compose deployment
- One `app` container with FastAPI and Asterisk runtime hooks
- One `postgres` container
- Basic health endpoints
- Generated minimal Asterisk config for internal dialing
- Persistent storage layout

## Out of Scope

- Trunks
- Inbound routes
- Outbound routes
- Queues
- IVR
- Automated TLS
- Auto-update
- Full installer

## Next Milestone

Wire the web app to:

- store extensions in PostgreSQL
- generate minimal PJSIP and dialplan config
- trigger an Asterisk reload
- prove one internal extension-to-extension call
