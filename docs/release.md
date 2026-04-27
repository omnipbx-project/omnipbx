# OmniPBX Release Workflow

OmniPBX production releases are published as Docker images and installed from
the public GitHub repository.

## Docker Hub Setup

Create a Docker Hub repository for the app image. The default image name used
by the installer and Compose file is:

```text
saroarsabbir/omnipbx
```

If the Docker Hub repository uses a different name, set this GitHub Actions
repository variable:

```text
DOCKERHUB_REPOSITORY=your-dockerhub-name/omnipbx
```

Add these GitHub Actions repository secrets:

```text
DOCKERHUB_USERNAME
DOCKERHUB_TOKEN
```

Use a Docker Hub access token for `DOCKERHUB_TOKEN`, not your Docker Hub
password.

## Publishing A Release

Update the version file, commit it, then push a matching tag:

```bash
echo "0.1.1" > VERSION
git add VERSION
git commit -m "Release 0.1.1"
git push
git tag v0.1.1
git push origin v0.1.1
```

The `v0.1.1` tag triggers GitHub Actions to build and push:

```text
saroarsabbir/omnipbx:0.1.1
saroarsabbir/omnipbx:latest
```

## Production Install

Install from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/omnipbx-project/omnipbx/main/scripts/install.sh | sudo bash
```

The installer clones the deployment repository into `/opt/omnipbx`, writes a
host-specific `.env`, pulls Docker images, starts the stack, and links:

```text
/usr/local/bin/omnipbxctl
```

## Production Update

Check for updates:

```bash
sudo omnipbxctl update --check-only
```

Apply an update:

```bash
sudo omnipbxctl update
```

The update command fast-forwards `/opt/omnipbx`, updates
`OMNIPBX_APP_VERSION`, pulls Docker images, and restarts the stack.

## Local Development

Use the development override to build the app image locally:

```bash
cd deploy
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```
