# Legacy PBX Inventory

Source workspace:
- `/home/sabbir/project.code-workspace`
- `/etc/asterisk`
- `/var/www/html`

Legacy FastAPI entrypoint:
- `/var/www/html/main.py`

Legacy feature modules discovered:

## Core
- `auth.py`
- `extensions.py`
- `status.py`
- `dialplan.py`

## Call Flow
- `trunk.py`
- `inbound.py`

## Operator Tools
- `call_logs.py`
- `soft_phone.py`
- `api.py`

Legacy route map:

## Extensions
- `GET /extensions`
- `POST /add-extension`
- `POST /edit-extension/{extension}`
- `POST /delete-extension/{extension}`

## Status
- `GET /status-ui`
- `GET /status-data`
- `WEBSOCKET /ws/status`

## Trunks
- `GET /trunks-ui`
- `GET /trunks`
- `POST /add-trunk`
- `POST /edit-trunk/{name}`
- `POST /delete-trunk/{name}`

## Inbound / Queue / IVR / Schedule
- `GET /inbound-ui`
- `GET /queue-ui`
- `GET /working-hours-ui`
- `GET /welcome-msg-ui`
- `GET /ivr-ui`
- `GET /ring-groups-ui`
- `GET /inbound-routes`
- `POST /inbound-routes`
- `GET /ring-groups`
- `POST /ring-groups`
- `GET /queues-custom`
- `POST /queues-custom`
- `GET /ivrs`
- `POST /ivrs`
- `GET /working-hours`
- `POST /working-hours`
- `GET /welcome-messages`
- `POST /welcome-messages/upload`

## Call Logs / Callback
- `GET /call-logs-ui`
- `GET /callback-ui`
- `GET /call-logs`
- `GET /callback-worklist`
- `POST /callback-followups/{linkedid}`

## Softphone
- `GET /softphone-ui`
- `POST /softphone/dnd`
- softphone asset and manifest routes

## API Push
- `GET /api-push-ui`
- `GET /api-push-test-ui`
- `GET /api-push/settings`
- `POST /api-push/settings`
- `POST /api-push/run`
- `GET /api-push/dead-letters`

Migration rules for OmniPBX:
- Each feature gets its own package under `app/features/<feature>/`
- Each feature gets its own HTML template under `app/templates/<feature>/`
- Shared layout and navigation live in `app/web.py` and `app/templates/base.html`
- Feature logic moves into small services instead of embedding large HTML strings inside Python modules
- Generated Asterisk config remains small and intentional
