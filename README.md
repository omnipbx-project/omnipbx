# OmniPBX

OmniPBX is a portable business PBX product built around Asterisk, FastAPI,
and PostgreSQL. Phase 1 focuses on a small but real foundation:

- one app container for Asterisk plus FastAPI
- one PostgreSQL container
- persistent volumes for PBX data
- a minimal web API and health endpoints
- generated minimal Asterisk configuration for internal calling

## Phase 1 Goal

The first milestone is to make the stack boot cleanly and support the flow
below:

1. Start the stack with Docker Compose.
2. Open the web app.
3. Create extensions `1001` and `1002`.
4. Reload Asterisk.
5. Register two phones.
6. Place an internal call between them.

## Project Layout

- `apps/app`: OmniPBX app container source
- `deploy`: Compose stack and environment templates
- `deploy/postgres/init`: database bootstrap files
- `scripts`: install/update helper scripts
- `docs`: architecture and milestone notes

## Manual Updates

OmniPBX updates are manual only. Production installs keep `/opt/omnipbx`
as a lightweight git checkout for deployment scripts, but the app container is
pulled from a published Docker image instead of being built on user servers.

- Install OmniPBX with:
  `curl -fsSL https://omnipbx.techseba.com | sudo bash`
- Run `omnipbx check-update` to compare the installed branch with its tracked upstream branch.
- Run `sudo omnipbx update` to do a fast-forward `git pull`, pull the configured Docker images, and restart the stack manually.
- Run `omnipbx unlock` if an admin locks themselves out after too many failed login attempts.
- In the web GUI, the dashboard now shows when the tracked upstream branch has newer commits and exposes a manual `Check now` and `Update OmniPBX` action for writable admin roles.

For local development, use `deploy/compose.dev.yaml` together with
`deploy/compose.yaml` to build the app image from `apps/app`.

Restart the active stack with:
`omnipbx restart`

See `docs/release.md` for Docker Hub and GitHub Actions release setup.

## Light Runtime Direction

OmniPBX keeps Asterisk lean by storing product data in PostgreSQL and
generating only the Asterisk files needed for the current feature set.
Call history is written by Asterisk directly into PostgreSQL through ODBC:
`cdr_adaptive_odbc` stores final call records in `cdr_raw`, while `cel_odbc`
stores event-level call flow history in `cel_raw`. The older CSV CDR importer
remains in the app as a fallback for legacy data, but ODBC is the primary
runtime path.

Phase 1 keeps the runtime focused on these core files:

- `asterisk.conf`
- `modules.conf`
- `res_odbc.conf`
- `cdr_adaptive_odbc.conf`
- `cel_odbc.conf`
- `pjsip.conf`
- `extensions.conf`
- `rtp.conf`
- generated files under `/etc/asterisk/generated`
