# OmniPBX Developer Guide

OmniPBX is a portable business PBX admin application built with FastAPI,
Asterisk, PostgreSQL, Docker Compose, Caddy, and coturn. It gives admins a web
GUI for managing PBX users, SIP trunks, call routing, queues, IVRs, voicemail,
call logs, recordings, reports, webphone/softphone provisioning, system status,
security rules, backups, and manual updates.

This README is written for developers who need to understand where each feature
lives and which file to edit when a screen, button, route, database query, or
Asterisk output needs to change.

## Quick Start

Production install:

```bash
curl -fsSL https://omnipbx.techseba.com | sudo bash
```

Local development from this repository:

```bash
cd deploy
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

Run the regression tests from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

Useful management commands:

```bash
omnipbx check-update
sudo omnipbx update
omnipbx restart
omnipbx unlock
```

## Project Layout

| Path | Purpose |
| --- | --- |
| `apps/app` | Main FastAPI application and Asterisk container source. |
| `apps/app/app/main.py` | FastAPI app creation, startup/shutdown lifecycle, middleware, router registration, root redirect, health endpoint. |
| `apps/app/app/web.py` | Shared Jinja rendering helper, sidebar navigation, topbar search placeholders, update banner context. |
| `apps/app/app/core/settings.py` | Environment-backed settings with the `OMNIPBX_` prefix. |
| `apps/app/app/core/db.py` | Runtime schema initialization and migrations beyond the bootstrap SQL. |
| `apps/app/app/features` | Feature route modules. Most UI pages have `ui.py`; JSON/API endpoints use `api.py`; live/status features may also have `service.py`. |
| `apps/app/app/services` | Business logic, database operations, Asterisk config generation, security, auth, permissions, reports, updates, backup, softphone, etc. |
| `apps/app/app/templates` | Jinja HTML templates. Shared shell lives in `base.html`; reusable pieces live in `components/` and `_ui_macros.html`. |
| `apps/app/app/static` | Global CSS/JS plus feature-specific JavaScript and CSS. |
| `apps/app/asterisk-config` | Static Asterisk config copied into the app image. Generated config is written under `/etc/asterisk/generated`. |
| `deploy/compose.yaml` | Production-like Compose stack: app, PostgreSQL, Caddy, TURN. |
| `deploy/compose.dev.yaml` | Development Compose override that builds the app image from local source. |
| `deploy/postgres/init/001-bootstrap.sql` | First database bootstrap tables and seed rows. |
| `deploy/runtime` | Runtime files mounted into containers, including generated Caddy/runtime state. |
| `scripts` | Install, update, control, and QA helper scripts. |
| `tests` | Python unittest regression suite. |
| `docs` | Extra architecture, release, and legacy notes. |
| `third_party/web-softphone-demo` | Browser extension/demo assets used as a reference for softphone behavior. |

## Runtime Architecture

The Compose stack is defined in `deploy/compose.yaml`:

- `app`: runs FastAPI, Asterisk, workers, and config generation.
- `postgres`: stores application data, call records, CEL events, users, routing
  rules, settings, and security state.
- `caddy`: public HTTP/HTTPS reverse proxy and certificate management.
- `turn`: coturn server for browser/webphone ICE relay.

On app startup, `apps/app/app/main.py` runs this lifecycle:

1. `initialize_schema()` from `apps/app/app/core/db.py`.
2. `sync_asterisk_config()` from `apps/app/app/services/asterisk.py`.
3. `write_caddyfile(render_caddyfile(...))` from `apps/app/app/services/setup.py`.
4. Starts API push, live event, and auto dialer workers.

The app keeps Asterisk lean. Product data stays in PostgreSQL and Asterisk files
are generated only for the active feature set. CDR/CEL history is written to
PostgreSQL by Asterisk ODBC into `cdr_raw` and `cel_raw`.

## Request Flow

Main request flow lives in `apps/app/app/main.py`:

- Static files are mounted at `/static`.
- User photos are mounted at `/user-photos`.
- Routers from every feature are included in one place.
- The `setup_guard` middleware handles setup redirects, login/session checks,
  CRM API key auth, read-only restrictions, user feature permissions, and
  security blocking.
- `/` redirects to `/setup`, `/login`, `/dashboard`, or the first allowed user
  page.
- `/health` returns a simple JSON health payload.

Shared page rendering lives in `apps/app/app/web.py`:

- `NAV_SECTIONS` controls sidebar items and labels.
- `render_template()` injects app version, current user, permissions, update
  banner, sidebar navigation, topbar search, page CSS, and page JS.
- Edit navigation labels/icons here when the left sidebar should change.

## Permissions

Permissions are centralized in `apps/app/app/services/permissions.py`.

Important objects:

- `ALL_FEATURES`: complete list of feature permission keys.
- `BUILTIN_PERMISSION_FEATURES`: default User, Supervisor, and Admin feature sets.
- `NAV_FEATURES`: maps sidebar pages to permission keys.
- `required_feature(method, path)`: maps routes/buttons/actions to required
  permissions.
- `filter_navigation()`: hides sidebar links a user cannot access.

When adding a new page or action:

1. Add or reuse a feature key in `ALL_FEATURES`.
2. Add navigation mapping in `NAV_FEATURES` if it appears in the sidebar.
3. Add route matching in `required_feature()`.
4. Add UI visibility checks in the template if needed.

## Feature Map

### Setup Wizard

| Item | Path |
| --- | --- |
| Page route | `apps/app/app/features/setup/ui.py` |
| Template | `apps/app/app/templates/setup/index.html` |
| Browser JS | `apps/app/app/static/js/setup.js` |
| CSS | `apps/app/app/static/css/setup.css` |
| Service | `apps/app/app/services/setup.py` |
| Main routes | `GET /setup`, `POST /setup`, `GET /setup/internal-ca.crt` |

Buttons/actions:

- Initial setup submit: `POST /setup`.
- Download internal CA certificate: `GET /setup/internal-ca.crt`.
- Access mode and certificate field behavior: `apps/app/app/static/js/setup.js`.

Change here for first-run setup, public URL, LAN/WAN mode, TLS/Caddy settings,
timezone/company settings, and certificate download behavior.

### Authentication and Password Reset

| Item | Path |
| --- | --- |
| Routes | `apps/app/app/features/auth/ui.py` |
| Templates | `apps/app/app/templates/auth/login.html`, `forgot_password.html`, `reset_password.html` |
| Email template | `apps/app/app/templates/email/password_reset.html` |
| Service | `apps/app/app/services/auth.py` |
| Security helpers | `apps/app/app/services/security.py` |
| Main routes | `GET/POST /login`, `GET /logout`, `GET/POST /forgot-password`, `GET/POST /reset-password` |

Buttons/actions:

- Login form: `POST /login`.
- Logout links: `GET /logout`.
- Forgot password form: `POST /forgot-password`.
- Reset password form: `POST /reset-password`.

Change here for session cookie behavior, password hashing, reset tokens, login
lockouts, and password reset email flow.

### Dashboard

| Item | Path |
| --- | --- |
| Page route | `apps/app/app/features/dashboard/ui.py` |
| Template | `apps/app/app/templates/dashboard/index.html` |
| Browser JS | `apps/app/app/static/js/dashboard.js` |
| CSS | `apps/app/app/static/css/dashboard.css` |
| Related services | `apps/app/app/services/reports.py`, `apps/app/app/services/live_events.py`, `apps/app/app/features/live_overview/service.py` |
| Main route | `GET /dashboard` |

Buttons/actions:

- Update panel buttons are rendered by `apps/app/app/templates/components/_updates_panel.html`.
- `Check Update` calls `POST /api/system/update/check` from `apps/app/app/static/js/updates.js`.
- `Manual Update` calls `POST /api/system/update/run` from `apps/app/app/static/js/updates.js`.
- Live/system cards refresh through `/status/usage` and `/live-overview/data`.

Change here for dashboard totals, recent activity, live status cards, and update
banner placement.

### Live Overview

| Item | Path |
| --- | --- |
| Routes | `apps/app/app/features/live_overview/ui.py` |
| Service | `apps/app/app/features/live_overview/service.py` |
| Template | `apps/app/app/templates/live_overview/index.html` |
| Browser JS | `apps/app/app/static/js/live_overview.js` |
| CSS | `apps/app/app/static/css/live_overview.css` |
| Event hub | `apps/app/app/services/live_events.py` |
| Main routes | `GET /live-overview`, `GET /live-overview/data`, `GET /live-overview/events`, `POST /live-overview/supervisor-action` |

Buttons/actions:

- Supervisor monitor/whisper/barge/hangup-style actions post to
  `/live-overview/supervisor-action`.
- Live refresh uses `/live-overview/data` and server-sent events from
  `/live-overview/events`.

Change here for active call parsing, trunk/user presence, call quality, and
supervisor controls.

### Users, Extensions, Groups, Permissions, My Profile

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/extensions/ui.py` |
| API routes | `apps/app/app/features/extensions/api.py` |
| Templates | `apps/app/app/templates/extensions/index.html`, `apps/app/app/templates/extensions/my_profile.html` |
| Browser JS | `apps/app/app/static/js/users.js` |
| CSS | `apps/app/app/static/css/users.css` |
| Services | `apps/app/app/services/extensions.py`, `apps/app/app/services/user_management.py`, `apps/app/app/services/permissions.py` |
| Main routes | `/extensions`, `/my-profile`, `/api/extensions` |

Buttons/actions:

- Tabs `Users`, `Groups`, `Permissions`: handled in `static/js/users.js`.
- `+ Add User`: opens the users action panel in `static/js/users.js`.
- `Create User`: `POST /extensions/create`.
- `Edit` / `Save User`: dynamic form action to `POST /extensions/{extension}/update`.
- `Enable User` / `Disable User`: `POST /extensions/{extension}/set-enabled`.
- `Delete User`: `POST /extensions/{extension}/delete`.
- `Save Group`: `POST /extensions/groups/create`.
- `Delete Group`: `POST /extensions/groups/{group_name}/delete`.
- `Save Permission`: `POST /extensions/permissions/create`.
- `Delete Permission`: `POST /extensions/permissions/{permission_name}/delete`.
- `Save My Profile`: `POST /my-profile`.

Change here for extension provisioning fields, profile photos, group assignment,
permission templates, user enable/disable behavior, and profile editing.

### Trunks

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/trunks/ui.py` |
| API routes | `apps/app/app/features/trunks/api.py` |
| Template | `apps/app/app/templates/trunks/index.html` |
| Browser JS | `apps/app/app/static/js/trunks.js` |
| CSS | `apps/app/app/static/css/trunks.css` |
| Service/model | `apps/app/app/services/trunks.py`, `apps/app/app/models/trunk.py` |
| Main routes | `/trunks`, `/api/trunks` |

Buttons/actions:

- `+ Add Trunk`: opens trunk modal in `static/js/trunks.js`.
- `Create Trunk`: `POST /trunks/create`.
- `Edit Trunk`: opens prefilled modal; save posts to `/trunks/{name}/update`.
- `Test Connection`: `POST /trunks/{name}/test` or `POST /trunks/test`.
- `Disable Trunk`: `POST /trunks/{name}/disable`.
- `Delete Trunk`: `POST /trunks/{name}/delete`.

Change here for SIP provider fields, registration vs IP-auth trunks, outbound
prefix/strip behavior, trunk testing, and generated PJSIP trunk config.

### Call Routing Hub

| Item | Path |
| --- | --- |
| Routes | `apps/app/app/features/call_routing/ui.py` |
| Templates | `apps/app/app/templates/call_routing/index.html`, `section.html`, `detail.html` |
| Browser JS | `apps/app/app/static/js/call_routing.js` |
| CSS | `apps/app/app/static/css/call_routing.css` |
| Service | `apps/app/app/services/call_routing.py` |
| Main routes | `/call-routing`, `/call-routing/{section_slug}`, `/call-routing/{section_slug}/{item_slug}` |

Buttons/actions:

- Routing cards link to sections/items.
- Target picker `OK` and `Clear`: handled in `static/js/call_routing.js`.
- `Save Rule` / `Update Rule`: `POST /call-routing/{section_slug}/{item_slug}/save`.
- `Cancel Edit`: link back to the rule page.
- `Edit`: adds `?edit_id={rule.id}` to the rule page.
- `Delete`: `POST /call-routing/{section_slug}/{item_slug}/{rule_id}/delete`.
- Conference `Start Now`: `POST /call-routing/internal-calls/conferences/{rule_id}/start`.

Change here for internal call rules, outbound rules, conferences, blocking,
advanced routing fields, and the routing hub card layout.

### Auto Dialer and Leads

| Item | Path |
| --- | --- |
| Routes | `apps/app/app/features/auto_dialer/ui.py` |
| Templates | `apps/app/app/templates/auto_dialer/index.html`, `detail.html`, `leads.html` |
| Browser JS | `apps/app/app/static/js/auto_dialer.js` |
| CSS | `apps/app/app/static/css/auto_dialer.css` |
| Service | `apps/app/app/services/auto_dialer.py` |
| Main routes | `/call-routing/auto-dialer/campaigns`, `/call-routing/auto-dialer/leads` |

Buttons/actions:

- `Save Campaign`: `POST /call-routing/auto-dialer/campaigns/save`.
- `Delete Campaign`: `POST /call-routing/auto-dialer/campaigns/{campaign_id}/delete`.
- `Start Campaign` / `Pause Campaign`: `POST /call-routing/auto-dialer/campaigns/{campaign_id}/status`.
- `Upload Numbers`: opens import dialog in `static/js/auto_dialer.js`.
- Campaign detail `Import Numbers`: `POST /call-routing/auto-dialer/campaigns/{campaign_id}/leads/import`.
- Leads page `Upload Leads` / `Import Leads`: `POST /call-routing/auto-dialer/leads/import`.
- Lead `Call`: `POST /call-routing/auto-dialer/campaigns/{campaign_id}/leads/{lead_id}/call`.
- Lead `Delete`: `POST /call-routing/auto-dialer/campaigns/{campaign_id}/leads/{lead_id}/delete`.

Change here for campaign assignment, lead import parsing, preview/progressive
dialing behavior, and worker logic.

### Call Logs

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/call_logs/ui.py` |
| API routes | `apps/app/app/features/call_logs/api.py` |
| Template | `apps/app/app/templates/call_logs/index.html` |
| Service | `apps/app/app/services/call_logs.py` |
| Classification | `apps/app/app/services/call_classification.py` |
| Main routes | `/call-logs`, `/api/call-logs`, `/api/call-recordings/{recordingfile}` |

Buttons/actions:

- Category folders: links back to `/call-logs` with query parameters.
- Date/search/direction filter `Apply`: `GET /call-logs`.
- `Export CSV`: `GET /call-logs/export`.
- `Play`: opens recording URL from `/api/call-recordings/{recordingfile}`.
- Sync endpoint: `POST /call-logs/sync`.

Change here for CDR queries, call visibility, recording access, CSV export, and
missed/answered/customer missed classification.

### Follow Up / Callbacks

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/callbacks/ui.py` |
| API routes | `apps/app/app/features/callbacks/api.py` |
| Template | `apps/app/app/templates/callbacks/index.html` |
| Browser JS | `apps/app/app/static/js/callbacks.js` |
| Service | `apps/app/app/services/call_logs.py` |
| Main routes | `/callbacks`, `/api/callbacks` |

Buttons/actions:

- Take callback: `POST /callbacks/{linkedid}/take` or API
  `POST /api/callbacks/{linkedid}/take`.
- Mark done: `POST /callbacks/{linkedid}/done` or API
  `POST /api/callbacks/{linkedid}/done`.
- Update note/assignment: `POST /callbacks/{linkedid}/update` or API
  `POST /api/callbacks/{linkedid}`.

Change here for missed-call follow up workflow, assignment, notes, and completion
logic.

### Call Records

| Item | Path |
| --- | --- |
| Route | `apps/app/app/features/call_records/ui.py` |
| Template | `apps/app/app/templates/call_records/index.html` |
| Service | `apps/app/app/services/call_records.py` |
| Main route | `GET /call-records` |

Buttons/actions:

- This page lists/searches recording records. Recording playback/download should
  be traced through call log recording URLs and `apps/app/app/services/call_records.py`.

Change here for recording list filters, metadata, and record visibility.

### Voicemail and Welcome Messages

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/welcome_messages/ui.py` |
| API routes | `apps/app/app/features/welcome_messages/api.py` |
| Template | `apps/app/app/templates/welcome_messages/index.html` |
| Service | `apps/app/app/services/welcome_messages.py` |
| Audio helpers | `apps/app/app/services/audio.py` |
| Main routes | `/welcome-messages`, `/api/welcome-messages`, `/voicemail/messages/...` |

Buttons/actions:

- Create welcome/voicemail rule: `POST /welcome-messages/create`.
- Delete rule: `POST /welcome-messages/{rule_id}/delete`.
- Play/download voicemail file: `GET /voicemail/messages/{mailbox}/{folder}/{filename}`.
- Delete voicemail file: `POST /voicemail/messages/{mailbox}/{folder}/{filename}/delete`.

Change here for uploaded prompts, voicemail mailbox handling, inbound welcome
messages, and voicemail deletion.

### Reports and Audit Log

| Item | Path |
| --- | --- |
| Routes | `apps/app/app/features/audit_log/ui.py` |
| Template | `apps/app/app/templates/audit_log/index.html` |
| Service | `apps/app/app/services/reports.py`, `apps/app/app/services/audit.py` |
| Main routes | `GET /reports`, `GET /reports/export`, `GET /audit-log` |

Buttons/actions:

- Report rail links: `GET /reports?section=...`.
- Date/user filters `Apply` or `View`: `GET /reports`.
- `Export CSV`: `GET /reports/export`.
- `Open Call Log`: link to `/call-logs`.
- `Open Follow Up`: link to `/callbacks`.

Change here for report sections, KPI cards, detail tables, CSV export, and audit
history views.

### Settings

| Item | Path |
| --- | --- |
| Routes | `apps/app/app/features/settings/ui.py` |
| Template | `apps/app/app/templates/settings/index.html` |
| Browser JS | `apps/app/app/static/js/settings.js` |
| Service | `apps/app/app/services/setup.py` |
| Main routes | `GET /settings`, `POST /settings/timezone`, `POST /settings/company-network` |

Buttons/actions:

- Save timezone: `POST /settings/timezone`.
- Save company/network settings: `POST /settings/company-network`.
- Modal open/close behavior: `static/js/settings.js`.

Change here for company profile, timezone, public base URL, network defaults, and
settings page UI.

### Advanced Status, Logs, SSL, Network, Updates, Security, Custom Config

| Item | Path |
| --- | --- |
| Routes | `apps/app/app/features/status/ui.py` |
| Service | `apps/app/app/features/status/service.py` |
| Template | `apps/app/app/templates/status/index.html` |
| Browser JS | `apps/app/app/static/js/status.js` |
| CSS | `apps/app/app/static/css/status.css` |
| System API | `apps/app/app/api/system.py` |
| Main route | `GET /status` |

Buttons/actions:

- Advanced tabs `System Monitor`, `Logs`, `Asterisk CLI`, `SSL`, `Network`,
  `Updates`, `Security`, `Custom Config`: handled in `static/js/status.js`.
- Usage refresh: `GET /status/usage`.
- Logs `Load`: `GET /status/logs`.
- Asterisk CLI `Run`: `POST /status/asterisk-cli`.
- Network `Check`: `POST /status/network-check`.
- SSL `Save SSL`: `POST /status/ssl-settings` with `action=save`.
- SSL `Redo SSL`: `POST /status/ssl-settings` with `action=refresh`.
- `Download LAN certificate`: `GET /setup/internal-ca.crt`.
- Port/network settings: `POST /status/network-settings`.
- Update panel `Check Update`: `POST /api/system/update/check`.
- Update panel `Manual Update`: `POST /api/system/update/run`.
- Security rule `Save`: `POST /status/security-rules`.
- Security rule `Delete`: `POST /status/security-rules/{rule_id}/delete`.
- Security ban `Unblock`: `POST /status/security-bans/{ban_id}/unblock`.
- Custom config `Save and Reload`: `POST /status/custom-config`.

Change here for system monitoring, log loading, CLI commands, SSL/Caddy settings,
security rules, blocked IPs, update execution, and custom generated Asterisk
snippets.

### API Push

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/api_push/ui.py` |
| API routes | `apps/app/app/features/api_push/api.py` |
| Template | `apps/app/app/templates/api_push/index.html` |
| Service | `apps/app/app/services/api_push.py` |
| Main routes | `/api-push`, `/api-push/settings`, `/api-push/run`, `/api-push/dead-letters`, `/api-push/test-receiver/{entity_type}` |

Buttons/actions:

- Save settings form: `POST /api-push/settings/form`.
- Run now: `POST /api-push/run`.
- Resolve dead letter: `POST /api-push/dead-letters/resolve`.
- JSON settings API: `GET/POST /api-push/settings`.
- Test receiver: `POST /api-push/test-receiver/{entity_type}`.

Change here for outbound webhook/API delivery, payload shape, retries, dead
letters, and test receiver payloads.

### Admin Accounts and SMTP

| Item | Path |
| --- | --- |
| Routes | `apps/app/app/features/admin_accounts/ui.py` |
| Template | `apps/app/app/templates/admin_accounts/index.html` |
| Service | `apps/app/app/services/admin_accounts.py`, `apps/app/app/services/mailer.py` |
| Email template | `apps/app/app/templates/email/smtp_test.html` |
| Main route | `GET /admin-accounts` |

Buttons/actions:

- Delete admin: `POST /admin-accounts/{admin_id}/delete`.
- Update my password: `POST /admin-accounts/change-password`.
- Create admin: `POST /admin-accounts/create`.
- Save profile: `POST /admin-accounts/update`.
- Set admin password: `POST /admin-accounts/set-password`.
- Save SMTP settings: `POST /admin-accounts/smtp`.
- Send test email: `POST /admin-accounts/smtp/test`.

Change here for admin roles, read-only admins, password management, SMTP config,
and test email behavior.

### Softphone, Webphone, Desktop Provisioning

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/softphone/ui.py` |
| API routes | `apps/app/app/features/softphone/api.py` |
| Templates | `apps/app/app/templates/softphone/index.html`, `detached.html`, `components/_webphone.html` |
| Browser JS | `apps/app/app/static/js/webphone.js` |
| CSS | `apps/app/app/static/css/webphone.css` |
| Service | `apps/app/app/services/softphone.py` |
| Vendor JS | `apps/app/app/static/vendor/jssip.min.js`, `sip-simple-user.min.js` |
| Main routes | `/softphone`, `/webphone/detached`, `/api/softphone/...` |

Buttons/actions:

- Download browser extension: `GET /softphone/extension/download`.
- Save softphone settings: `POST /softphone/settings`.
- Load bootstrap: `GET /api/softphone/bootstrap/current` or
  `/api/softphone/bootstrap`.
- Save DND: `POST /softphone/dnd/{extension}` or API
  `POST /api/softphone/dnd/{extension}`.
- Webphone keypad number buttons: handled in `static/js/webphone.js`.
- Backspace `⌫`, clear `C`, transfer `R`, call, video call, hang up, mic,
  sound, hold, DND, auto-answer, copy, attach, detach, close: handled in
  `static/js/webphone.js`.
- Detached webphone window: `GET /webphone/detached`.
- Desktop provisioning data: `GET /api/softphone/desktop/current`.

Change here for SIP/WebRTC bootstrap, ICE/TURN settings, webphone controls,
downloaded browser extension config, detached phone window, and DND.

### Backup and Restore

| Item | Path |
| --- | --- |
| Routes | `apps/app/app/features/backup_restore/ui.py` |
| Template | `apps/app/app/templates/backup_restore/index.html` |
| Service | `apps/app/app/services/backup.py` |
| Main routes | `/backup-restore`, `/backup-restore/create`, `/backup-restore/download/{file_name}`, `/backup-restore/restore` |

Buttons/actions:

- Create backup: `POST /backup-restore/create`.
- Restore backup: `POST /backup-restore/restore`.
- Download backup: `GET /backup-restore/download/{file_name}`.

Change here for what data is included in backup archives, restore validation,
and backup file listing.

### Inbound Routes

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/inbound/ui.py` |
| API routes | `apps/app/app/features/inbound/api.py` |
| Template | `apps/app/app/templates/inbound/index.html` |
| Browser JS | `apps/app/app/static/js/inbound.js` |
| Service | `apps/app/app/services/inbound_routes.py` |
| Main routes | `/inbound-routes`, `/api/inbound-routes` |

Buttons/actions:

- Create inbound route: `POST /inbound-routes/create`.
- Update inbound route: `POST /inbound-routes/{name}/update`.
- Delete inbound route: `POST /inbound-routes/{name}/delete`.
- Destination picker `OK` / `Clear`: handled in `static/js/inbound.js`.

Change here for DID matching, destination selection, inbound route forms, and
generated inbound dialplan.

### Ring Groups

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/ring_groups/ui.py` |
| API routes | `apps/app/app/features/ring_groups/api.py` |
| Template | `apps/app/app/templates/ring_groups/index.html` |
| Service | `apps/app/app/services/ring_groups.py` |
| Main routes | `/ring-groups`, `/api/ring-groups` |

Buttons/actions:

- Create ring group: `POST /ring-groups/create`.
- Delete ring group: `POST /ring-groups/{name}/delete`.

Change here for ring strategy, timeout, members, extension number, fallback
behavior, and generated ring group dialplan.

### Queues

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/queues/ui.py` |
| API routes | `apps/app/app/features/queues/api.py` |
| Template | `apps/app/app/templates/queues/index.html` |
| Service | `apps/app/app/services/queues.py` |
| Main routes | `/queues`, `/api/queues` |

Buttons/actions:

- Create queue: `POST /queues/create`.
- Delete queue: `POST /queues/{name}/delete`.
- Prompt/music uploads are handled by the queue form and audio helpers.

Change here for queue strategy, members, retry/wrap-up timing, MOH, prompts, and
generated queue config/dialplan.

### IVRs

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/ivrs/ui.py` |
| API routes | `apps/app/app/features/ivrs/api.py` |
| Template | `apps/app/app/templates/ivrs/index.html` |
| Service | `apps/app/app/services/ivrs.py` |
| Main routes | `/ivrs`, `/api/ivrs` |

Buttons/actions:

- Create IVR: `POST /ivrs/create`.
- Delete IVR: `POST /ivrs/{name}/delete`.
- Prompt uploads are handled by the IVR form and audio helpers.

Change here for IVR prompt, timeout, retry count, digit options, destinations,
and generated IVR dialplan.

### Working Hours

| Item | Path |
| --- | --- |
| UI routes | `apps/app/app/features/working_hours/ui.py` |
| API routes | `apps/app/app/features/working_hours/api.py` |
| Template | `apps/app/app/templates/working_hours/index.html` |
| Service | `apps/app/app/services/working_hours.py` |
| Main routes | `/working-hours`, `/api/working-hours` |

Buttons/actions:

- Create working-hours rule: `POST /working-hours/create`.
- Delete working-hours rule: `POST /working-hours/{name}/delete`.
- After-hours sound uploads are handled by the form and audio helpers.

Change here for office hour matching, after-hours prompt behavior, inbound route
attachment, and generated time-condition dialplan.

### CRM API

| Item | Path |
| --- | --- |
| API routes | `apps/app/app/features/crm_api/api.py` |
| Service | `apps/app/app/services/crm_api.py` |
| Docs | `docs/laravel-crm-integration.md` |
| Main routes | `/crm-api/health`, `/crm-api/call-data`, `/crm-api/call-logs`, `/crm-api/callbacks` |

Actions:

- CRM endpoints require `X-API-Key`; auth is checked in `main.py` and
  `services/crm_api.py`.
- `GET /crm-api/call-data`: call data feed.
- `GET /crm-api/call-logs`: call log feed.
- `GET /crm-api/callbacks`: callback list.
- `POST /crm-api/callbacks/{linkedid}`: update callback data.

Change here for external CRM payloads, API-key validation, filters, and callback
integration.

## Shared UI Components and Buttons

| UI piece | Path | What to change |
| --- | --- | --- |
| Page shell | `apps/app/app/templates/base.html` | Global HTML layout, CSS/JS includes, update banner placement, webphone include. |
| Sidebar | `apps/app/app/templates/components/_sidebar.html` and `apps/app/app/web.py` | Sidebar markup, nav labels, nav icons, active state. |
| Topbar | `apps/app/app/templates/components/_topbar.html` | Search input, notifications button, Provision menu, theme button, profile menu. |
| Update panel | `apps/app/app/templates/components/_updates_panel.html` and `apps/app/app/static/js/updates.js` | Check/manual update buttons and status rendering. |
| Webphone widget | `apps/app/app/templates/components/_webphone.html` and `apps/app/app/static/js/webphone.js` | Dialpad, call controls, DND, detach/attach, transfer, media controls. |
| Feature cards/date filter macros | `apps/app/app/templates/_ui_macros.html` | Reusable feature card and date range filter markup. |
| Global styles | `apps/app/app/static/app.css` | Shell, generic buttons, panels, forms, cards, theme variables. |
| Global JS | `apps/app/app/static/app.js` | Theme toggle, topbar/profile/provision menu behavior, shared interactions. |

Topbar buttons:

- Notifications: markup in `_topbar.html`; behavior in `static/app.js`.
- Provision: opens provisioning menu; desktop/webphone actions are in
  `_topbar.html` and `static/app.js`.
- Browser extension download: `GET /softphone/extension/download`.
- LAN certificate download: `GET /setup/internal-ca.crt`.
- Theme toggle: `static/app.js`.
- My Profile: `GET /my-profile`.
- Logout: `GET /logout`.

## Asterisk Config Generation

Most PBX changes eventually flow into generated Asterisk config through
`apps/app/app/services/asterisk.py`.

Important generated files are configured in `apps/app/app/core/settings.py`:

- `/etc/asterisk/pjsip.conf`
- `/etc/asterisk/rtp.conf`
- `/etc/asterisk/generated/pjsip.generated.conf`
- `/etc/asterisk/generated/pjsip.trunks.generated.conf`
- `/etc/asterisk/generated/extensions.generated.conf`
- `/etc/asterisk/generated/extensions.trunks.generated.conf`
- `/etc/asterisk/generated/inbound_routes.generated.conf`
- `/etc/asterisk/generated/ring_groups.generated.conf`
- `/etc/asterisk/generated/queues.generated.conf`
- `/etc/asterisk/generated/queues_dialplan.generated.conf`
- `/etc/asterisk/generated/ivrs.generated.conf`
- `/etc/asterisk/generated/musiconhold.generated.conf`
- `/etc/asterisk/generated/voicemail.generated.conf`

Static baseline config lives in `apps/app/asterisk-config`.

When changing calling behavior:

1. Update the service that stores the feature data.
2. Update `services/asterisk.py` render functions.
3. Add/adjust tests in `tests/test_asterisk_rendering.py`.
4. Make sure `sync_asterisk_config(connection, reload_config=True)` is called
   after write actions that need immediate Asterisk reload.

## Database Guide

Initial schema is in `deploy/postgres/init/001-bootstrap.sql`. Runtime schema
creation/migrations continue in `apps/app/app/core/db.py`.

High-value tables:

- `extensions`, `user_profiles`, `user_groups`, `user_permissions`: users,
  extension accounts, groups, and feature permissions.
- `cdr_raw`, `cel_raw`: call history and event history from Asterisk ODBC.
- `autodialer_campaigns`, `autodialer_leads`: auto dialer campaigns and leads.
- `callback_followups`: follow-up state for missed/customer callbacks.
- `advanced_security_rules`, `app_security_failures`, `app_security_bans`:
  security allow/block/ban state.
- `advanced_custom_config`, `advanced_network_settings`: advanced settings.
- Additional feature tables are initialized in `apps/app/app/core/db.py`.

When adding schema:

1. Add idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` logic in
   `apps/app/app/core/db.py` unless it belongs only to first bootstrap.
2. Add indexes for list/search pages.
3. Update the corresponding service query file.
4. Add tests for validation and rendering if the data affects Asterisk.

## API and Route Index

| Area | Routes |
| --- | --- |
| Root/health | `GET /`, `GET /health` |
| Setup | `GET /setup`, `POST /setup`, `GET /setup/internal-ca.crt` |
| Auth | `GET/POST /login`, `GET /logout`, `GET/POST /forgot-password`, `GET/POST /reset-password` |
| Dashboard | `GET /dashboard` |
| Live overview | `GET /live-overview`, `GET /live-overview/data`, `GET /live-overview/events`, `POST /live-overview/supervisor-action` |
| Users | `GET /extensions`, `POST /extensions/create`, `POST /extensions/{extension}/update`, `POST /extensions/{extension}/set-enabled`, `POST /extensions/{extension}/delete`, `GET/POST /my-profile` |
| User API | `GET /api/extensions`, `POST /api/extensions`, `DELETE /api/extensions/{extension}` |
| Groups/permissions | `POST /extensions/groups/create`, `POST /extensions/groups/{group_name}/delete`, `POST /extensions/permissions/create`, `POST /extensions/permissions/{permission_name}/delete` |
| Trunks | `GET /trunks`, `POST /trunks/create`, `POST /trunks/{name}/update`, `POST /trunks/test`, `POST /trunks/{name}/test`, `POST /trunks/{name}/disable`, `POST /trunks/{name}/delete` |
| Trunk API | `GET /api/trunks`, `POST /api/trunks`, `DELETE /api/trunks/{name}` |
| Call routing | `GET /call-routing`, `GET /call-routing/{section_slug}`, `GET /call-routing/{section_slug}/{item_slug}`, `POST /call-routing/{section_slug}/{item_slug}/save`, `POST /call-routing/{section_slug}/{item_slug}/{rule_id}/delete` |
| Auto dialer | `GET /call-routing/auto-dialer/campaigns`, `GET /call-routing/auto-dialer/leads`, `GET /call-routing/auto-dialer/campaigns/{campaign_id}`, campaign/lead POST actions under the same prefix |
| Call logs | `GET /call-logs`, `POST /call-logs/sync`, `GET /call-logs/export`, `GET /api/call-logs`, `POST /api/call-logs/sync`, `GET /api/call-recordings/{recordingfile}` |
| Callbacks | `GET /callbacks`, `POST /callbacks/{linkedid}/take`, `POST /callbacks/{linkedid}/done`, `POST /callbacks/{linkedid}/update`, plus `/api/callbacks` equivalents |
| Call records | `GET /call-records` |
| Voicemail/welcome | `GET /welcome-messages`, `POST /welcome-messages/create`, `POST /welcome-messages/{rule_id}/delete`, `GET/POST /voicemail/messages/{mailbox}/{folder}/{filename}` |
| Reports | `GET /reports`, `GET /reports/export`, `GET /audit-log` |
| Settings | `GET /settings`, `POST /settings/timezone`, `POST /settings/company-network` |
| Status | `GET /status`, `GET /status/data`, `GET /status/usage`, `GET /status/logs`, and status POST actions |
| System API | `POST /api/system/reload`, `GET /api/system/update`, `POST /api/system/update/check`, `POST /api/system/update/run` |
| API push | `GET /api-push`, `GET/POST /api-push/settings`, `POST /api-push/settings/form`, `POST /api-push/run`, `GET /api-push/dead-letters`, `POST /api-push/dead-letters/resolve`, `POST /api-push/test-receiver/{entity_type}` |
| Admin accounts | `GET /admin-accounts`, create/update/delete/password/SMTP POST actions |
| Softphone | `GET /softphone`, `POST /softphone/settings`, `POST /softphone/dnd/{extension}`, `GET /softphone/extension/download`, `GET /webphone/detached`, `/api/softphone/...` |
| Backup/restore | `GET /backup-restore`, `POST /backup-restore/create`, `GET /backup-restore/download/{file_name}`, `POST /backup-restore/restore` |
| Inbound routes | `/inbound-routes` UI actions and `/api/inbound-routes` JSON API |
| Ring groups | `/ring-groups` UI actions and `/api/ring-groups` JSON API |
| Queues | `/queues` UI actions and `/api/queues` JSON API |
| IVRs | `/ivrs` UI actions and `/api/ivrs` JSON API |
| Working hours | `/working-hours` UI actions and `/api/working-hours` JSON API |
| CRM API | `GET /crm-api/health`, `GET /crm-api/call-data`, `GET /crm-api/call-logs`, `GET /crm-api/callbacks`, `POST /crm-api/callbacks/{linkedid}` |

## Where To Change Common Things

| Need | Edit |
| --- | --- |
| Add a sidebar item | `apps/app/app/web.py`, then permission mapping in `apps/app/app/services/permissions.py`. |
| Change global theme/styles | `apps/app/app/static/app.css`. |
| Change topbar/profile/provision behavior | `apps/app/app/templates/components/_topbar.html`, `apps/app/app/static/app.js`. |
| Change a page layout | The matching file in `apps/app/app/templates/<feature>/`. |
| Change a button target | The template form/link action, then matching `features/<feature>/ui.py` route. |
| Change client-side modal/tab/picker behavior | The matching `apps/app/app/static/js/<feature>.js`. |
| Change database reads/writes | The matching `apps/app/app/services/<feature>.py`. |
| Change JSON API behavior | The matching `apps/app/app/features/<feature>/api.py`. |
| Change Asterisk output | `apps/app/app/services/asterisk.py` and tests in `tests/test_asterisk_rendering.py`. |
| Change permissions | `apps/app/app/services/permissions.py`. |
| Change startup behavior | `apps/app/app/main.py`. |
| Change environment defaults | `apps/app/app/core/settings.py`, `deploy/.env.example`, `deploy/compose.yaml`. |
| Change Docker services/ports/volumes | `deploy/compose.yaml` and `deploy/compose.dev.yaml`. |
| Change install/update commands | `scripts/install.sh`, `scripts/update.sh`, `scripts/omnipbxctl`, root `omnipbx`. |
| Change release docs | `docs/release.md`. |

## Testing Map

| Test file | Covers |
| --- | --- |
| `tests/test_asterisk_rendering.py` | PJSIP, RTP, trunks, inbound routes, working hours, ring groups, queues, IVRs, voicemail, dialplan rendering. |
| `tests/test_auth.py` | Password hashing, sessions, extension sessions, reset token behavior. |
| `tests/test_auto_dialer.py` | Lead import parsing and phone normalization. |
| `tests/test_call_classification.py` | Customer missed/abandoned/outbound/internal classification. |
| `tests/test_call_logs.py` | Call log visibility, spy call filtering, own/all permissions. |
| `tests/test_crm_api.py` | CRM API key validation. |
| `tests/test_date_ranges.py` | Date range parsing and timezone behavior. |
| `tests/test_extensions_service.py` | Extension transport defaults, device limits, protected admin extension. |
| `tests/test_live_call_webhooks.py` | Live webhook payload and event filtering. |
| `tests/test_live_overview.py` | Active call parsing, supervisor permissions/actions, quality stats, status sorting. |
| `tests/test_models_validation.py` | Pydantic/model validation for trunks, inbound routes, queues, ring groups, working hours. |
| `tests/test_permissions.py` | Feature permission routing, navigation filtering, first allowed path. |
| `tests/test_security.py` | IP cleaning, CIDR/exact matching. |
| `tests/test_softphone.py` | ICE/TURN server generation. |

Add tests whenever a change affects generated Asterisk config, permissions,
authentication/security, call visibility, or data validation.

## Manual Updates and Release Notes

OmniPBX updates are manual. Production installs keep `/opt/omnipbx` as a
lightweight git checkout for deployment scripts, while the app container is
pulled from the configured Docker image.

Update behavior:

- CLI update commands live in `scripts/update.sh`, `scripts/omnipbxctl`, and the
  root `omnipbx` wrapper.
- Web update APIs live in `apps/app/app/api/system.py`.
- Update status/check logic lives in `apps/app/app/services/updates.py`.
- The dashboard/status update UI uses
  `apps/app/app/templates/components/_updates_panel.html` and
  `apps/app/app/static/js/updates.js`.

Release setup is documented in `docs/release.md`.
