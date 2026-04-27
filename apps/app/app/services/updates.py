from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile

from app.core.settings import Settings


def get_update_overview(settings: Settings, *, force_refresh: bool = False) -> dict[str, object]:
    status = load_update_status(settings)
    check = _refresh_update_check(settings) if force_refresh or _check_cache_stale(settings) else load_update_check(settings)
    status_state = str(status.get("state") or "idle")
    commits_behind = int(check.get("commits_behind") or 0)
    commits_ahead = int(check.get("commits_ahead") or 0)
    repo_dirty = bool(check.get("repo_dirty"))
    tracked_upstream = bool(check.get("tracked_upstream"))

    return {
        "current_version": str(check.get("current_version") or settings.app_version),
        "latest_version": str(check.get("latest_version") or settings.app_version),
        "update_available": bool(check.get("update_available")),
        "git_ready": bool(check.get("git_ready")),
        "tracked_upstream": tracked_upstream,
        "local_branch": check.get("local_branch") or "",
        "upstream_ref": check.get("upstream_ref") or "",
        "remote_name": check.get("remote_name") or "",
        "remote_url": check.get("remote_url") or "",
        "local_commit": check.get("local_commit") or "",
        "remote_commit": check.get("remote_commit") or "",
        "commits_behind": commits_behind,
        "commits_ahead": commits_ahead,
        "repo_dirty": repo_dirty,
        "check_error": check.get("check_error") or "",
        "check_message": check.get("message") or "",
        "last_checked_at": check.get("last_checked_at") or "",
        "update_status": status,
        "can_start_update": bool(
            bool(check.get("git_ready"))
            and tracked_upstream
            and commits_behind > 0
            and commits_ahead == 0
            and not repo_dirty
            and status_state not in {"queued", "updating"}
        ),
    }


def get_update_banner(settings: Settings) -> dict[str, str] | None:
    status = load_update_status(settings)
    state = str(status.get("state") or "idle")
    if state in {"queued", "updating"}:
        return {
            "tone": "info",
            "title": "Update in progress",
            "detail": str(status.get("message") or "OmniPBX is applying the requested update."),
            "href": "/dashboard#updates",
        }
    if state == "error":
        return {
            "tone": "error",
            "title": "Update failed",
            "detail": str(status.get("message") or "The last manual update did not finish successfully."),
            "href": "/dashboard#updates",
        }

    check = _refresh_update_check(settings) if _check_cache_stale(settings) else load_update_check(settings)
    if bool(check.get("update_available")):
        commits_behind = int(check.get("commits_behind") or 0)
        latest_version = str(check.get("latest_version") or "")
        branch = str(check.get("upstream_ref") or "upstream")
        detail = f"{branch} is {commits_behind} commit{'s' if commits_behind != 1 else ''} ahead."
        if latest_version and latest_version != str(check.get("current_version") or ""):
            detail = f"Version {latest_version} is available from {branch}."
        return {
            "tone": "warn",
            "title": "Update available",
            "detail": detail,
            "href": "/dashboard#updates",
        }
    return None


def load_update_status(settings: Settings) -> dict[str, object]:
    payload = _read_json_file(Path(settings.update_status_path))
    if payload:
        return payload
    return {
        "state": "idle",
        "message": "No update has been started yet.",
        "current_version": settings.app_version,
        "target_version": "",
        "job_container_id": "",
        "started_at": "",
        "finished_at": "",
        "updated_at": "",
    }


def load_update_check(settings: Settings) -> dict[str, object]:
    payload = _read_json_file(Path(settings.update_check_cache_path))
    if payload:
        return payload
    return {
        "current_version": settings.app_version,
        "latest_version": settings.app_version,
        "git_ready": False,
        "tracked_upstream": False,
        "local_branch": "",
        "upstream_ref": "",
        "remote_name": "",
        "remote_url": "",
        "local_commit": "",
        "remote_commit": "",
        "commits_behind": 0,
        "commits_ahead": 0,
        "repo_dirty": False,
        "update_available": False,
        "check_error": "",
        "message": "Update checks have not run yet.",
        "last_checked_at": "",
    }


def write_update_status(settings: Settings, payload: dict[str, object]) -> None:
    enriched = {
        "current_version": settings.app_version,
        "updated_at": _utc_now(),
        **payload,
    }
    _write_json_file(Path(settings.update_status_path), enriched)


def start_detached_update(settings: Settings) -> dict[str, object]:
    overview = get_update_overview(settings, force_refresh=True)
    if not overview["git_ready"]:
        raise ValueError("This OmniPBX install is not a git checkout, so git-based updates are unavailable.")
    if not overview["tracked_upstream"]:
        raise ValueError("This OmniPBX install does not have an upstream tracking branch configured.")
    if overview["repo_dirty"]:
        raise ValueError("This OmniPBX install has local tracked changes. Commit or revert them before updating.")
    if int(overview["commits_ahead"]) > 0 and int(overview["commits_behind"]) > 0:
        raise ValueError("This OmniPBX branch has diverged from upstream. Resolve the git history before updating.")
    if not overview["update_available"]:
        raise ValueError("OmniPBX is already up to date with its tracked git branch.")

    current_status = load_update_status(settings)
    current_state = str(current_status.get("state") or "idle")
    if current_state in {"queued", "updating"}:
        raise ValueError("Another update is already running.")

    target_version = _target_label(overview)
    write_update_status(
        settings,
        {
            "state": "queued",
            "message": f"Queued manual git update to {target_version}.",
            "target_version": target_version,
            "started_at": _utc_now(),
            "finished_at": "",
        },
    )

    compose_file = Path(settings.host_project_path) / "deploy" / "compose.yaml"
    command = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "run",
        "-d",
        "--rm",
        "--no-deps",
        "app",
        "python3",
        f"{settings.host_project_path}/scripts/omnipbxctl",
        "update",
        "--non-interactive",
        "--project-root",
        settings.host_project_path,
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Failed to start detached update helper."
        write_update_status(
            settings,
            {
                "state": "error",
                "message": message,
                "target_version": target_version,
                "finished_at": _utc_now(),
            },
        )
        raise RuntimeError(message)

    job_container_id = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    write_update_status(
        settings,
        {
            "state": "queued",
            "message": f"Detached git updater started for {target_version}.",
            "target_version": target_version,
            "job_container_id": job_container_id,
            "started_at": current_status.get("started_at") or _utc_now(),
            "finished_at": "",
        },
    )
    return {
        "status": "started",
        "job_container_id": job_container_id,
        "target_version": target_version,
    }


def _refresh_update_check(settings: Settings) -> dict[str, object]:
    payload = {
        "current_version": settings.app_version,
        "latest_version": settings.app_version,
        "git_ready": False,
        "tracked_upstream": False,
        "local_branch": "",
        "upstream_ref": "",
        "remote_name": "",
        "remote_url": "",
        "local_commit": "",
        "remote_commit": "",
        "commits_behind": 0,
        "commits_ahead": 0,
        "repo_dirty": False,
        "update_available": False,
        "check_error": "",
        "message": "",
        "last_checked_at": _utc_now(),
    }

    repo = Path(settings.host_project_path)
    if not repo.exists():
        payload["message"] = f"Host project path {repo} is not mounted into the app container."
        _write_json_file(Path(settings.update_check_cache_path), payload)
        return payload

    try:
        _git(repo, "rev-parse", "--is-inside-work-tree", timeout=settings.update_check_timeout_seconds)
    except RuntimeError as exc:
        payload["message"] = "This OmniPBX install is not a git checkout, so git update checks are unavailable."
        payload["check_error"] = str(exc)
        _write_json_file(Path(settings.update_check_cache_path), payload)
        return payload

    try:
        local_version = _read_version_file(repo / "VERSION", settings.app_version)
        local_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD", timeout=settings.update_check_timeout_seconds)
        payload["current_version"] = local_version
        payload["local_branch"] = local_branch
        payload["git_ready"] = True
        payload["local_commit"] = _git(repo, "rev-parse", "--short=12", "HEAD", timeout=settings.update_check_timeout_seconds)
        payload["repo_dirty"] = bool(
            _git(repo, "status", "--porcelain", "--untracked-files=no", timeout=settings.update_check_timeout_seconds)
        )

        if local_branch == "HEAD":
            payload["message"] = "This OmniPBX install is on a detached git HEAD. Check out a branch to enable updates."
            _write_json_file(Path(settings.update_check_cache_path), payload)
            return payload

        upstream_ref = _git(
            repo,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
            timeout=settings.update_check_timeout_seconds,
        )
        payload["tracked_upstream"] = True
        payload["upstream_ref"] = upstream_ref
        remote_name = upstream_ref.split("/", 1)[0]
        payload["remote_name"] = remote_name
        payload["remote_url"] = _git(repo, "remote", "get-url", remote_name, timeout=settings.update_check_timeout_seconds)

        _git(repo, "fetch", "--prune", remote_name, timeout=settings.update_check_timeout_seconds)

        payload["remote_commit"] = _git(repo, "rev-parse", "--short=12", upstream_ref, timeout=settings.update_check_timeout_seconds)
        payload["latest_version"] = _read_version_at_ref(repo, upstream_ref, payload["current_version"])

        counts = _git(repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream_ref}", timeout=settings.update_check_timeout_seconds)
        ahead_raw, behind_raw = counts.split()
        commits_ahead = int(ahead_raw)
        commits_behind = int(behind_raw)
        payload["commits_ahead"] = commits_ahead
        payload["commits_behind"] = commits_behind
        payload["update_available"] = commits_behind > 0

        if commits_behind > 0 and commits_ahead == 0:
            payload["message"] = (
                f"{upstream_ref} is {commits_behind} commit{'s' if commits_behind != 1 else ''} ahead of this install."
            )
        elif commits_behind > 0 and commits_ahead > 0:
            payload["message"] = (
                f"This OmniPBX branch has diverged from {upstream_ref}. Manual git cleanup is required before updating."
            )
        elif commits_ahead > 0:
            payload["message"] = (
                f"This OmniPBX install has {commits_ahead} local commit{'s' if commits_ahead != 1 else ''} ahead of {upstream_ref}."
            )
        else:
            payload["message"] = f"OmniPBX is up to date on {upstream_ref}."

        if payload["repo_dirty"]:
            payload["message"] += " Local tracked changes are present."
    except RuntimeError as exc:
        payload["check_error"] = str(exc)
        if payload["tracked_upstream"]:
            payload["message"] = "Unable to compare this OmniPBX install with its upstream git branch right now."
        else:
            payload["message"] = "This OmniPBX install does not have an upstream tracking branch configured."

    _write_json_file(Path(settings.update_check_cache_path), payload)
    return payload


def _check_cache_stale(settings: Settings) -> bool:
    cache = load_update_check(settings)
    last_checked_at = str(cache.get("last_checked_at") or "")
    if not last_checked_at:
        return True
    try:
        checked_at = _parse_timestamp(last_checked_at)
    except ValueError:
        return True
    age = datetime.now(UTC) - checked_at
    return age >= timedelta(seconds=settings.update_check_interval_seconds)


def _git(repo: Path, *args: str, timeout: int) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git {' '.join(args)} timed out after {timeout} seconds") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"git {' '.join(args)} failed"
        raise RuntimeError(detail)
    return completed.stdout.strip()


def _read_version_at_ref(repo: Path, ref: str, fallback: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{ref}:VERSION"],
        cwd=repo,
        text=True,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if completed.returncode != 0:
        return fallback
    version = completed.stdout.strip()
    return version or fallback


def _read_version_file(path: Path, fallback: str) -> str:
    try:
        version = path.read_text(encoding="utf-8").strip()
    except OSError:
        return fallback
    return version or fallback


def _target_label(overview: dict[str, object]) -> str:
    latest_version = str(overview.get("latest_version") or "").strip()
    current_version = str(overview.get("current_version") or "").strip()
    if latest_version and latest_version != current_version:
        return latest_version
    remote_commit = str(overview.get("remote_commit") or "").strip()
    if remote_commit:
        return remote_commit
    return "upstream"


def _read_json_file(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
