import json
from pathlib import Path
import shutil
from typing import BinaryIO

import psycopg
from psycopg.rows import dict_row


PHOTO_DIR = Path("/var/lib/omnipbx/user-photos")
PHOTO_URL_PREFIX = "/user-photos"


def list_permissions(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, name, description, features
            FROM user_permissions
            ORDER BY CASE name WHEN 'User' THEN 0 WHEN 'Supervisor' THEN 1 WHEN 'Admin' THEN 2 ELSE 3 END, name
            """
        )
        rows = list(cursor.fetchall())
    for row in rows:
        row["features"] = _normalize_features(row.get("features"))
    return rows


def list_groups(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT group_row.id, group_row.name, group_row.description,
                   COALESCE(permission.name, 'User') AS permission,
                   COUNT(profile.extension) AS user_count
            FROM user_groups group_row
            LEFT JOIN user_permissions permission ON permission.id = group_row.permission_id
            LEFT JOIN user_profiles profile ON profile.group_id = group_row.id
            GROUP BY group_row.id, group_row.name, group_row.description, permission.name
            ORDER BY group_row.name
            """
        )
        return list(cursor.fetchall())


def profiles_by_extension(connection: psycopg.Connection) -> dict[str, dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT profile.extension, profile.email, profile.photo_path,
                   COALESCE(group_row.name, 'Sales') AS group_name,
                   COALESCE(permission.name, group_permission.name, 'User') AS permission_name
            FROM user_profiles profile
            LEFT JOIN user_groups group_row ON group_row.id = profile.group_id
            LEFT JOIN user_permissions permission ON permission.id = profile.permission_id
            LEFT JOIN user_permissions group_permission ON group_permission.id = group_row.permission_id
            """
        )
        rows = list(cursor.fetchall())
    for row in rows:
        row["photo_url"] = photo_url_from_path(row.get("photo_path"))
    return {row["extension"]: row for row in rows}


def ensure_profile(
    connection: psycopg.Connection,
    *,
    extension: str,
    email: str = "",
    group_name: str = "",
    photo_path: str = "",
) -> None:
    with connection.cursor(row_factory=dict_row) as cursor:
        group_id = _lookup_id(cursor, "user_groups", group_name)
        cursor.execute(
            """
            INSERT INTO user_profiles (extension, email, photo_path, group_id)
            VALUES (%(extension)s, %(email)s, %(photo_path)s, %(group_id)s)
            ON CONFLICT (extension) DO UPDATE
            SET email = EXCLUDED.email,
                photo_path = COALESCE(NULLIF(EXCLUDED.photo_path, ''), user_profiles.photo_path),
                group_id = EXCLUDED.group_id,
                updated_at = NOW()
            """,
            {
                "extension": extension,
                "email": email.strip() or None,
                "photo_path": photo_path.strip(),
                "group_id": group_id,
            },
        )


def update_own_profile(
    connection: psycopg.Connection,
    *,
    extension: str,
    email: str,
    photo_path: str = "",
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_profiles (extension, email, photo_path)
            VALUES (%(extension)s, %(email)s, %(photo_path)s)
            ON CONFLICT (extension) DO UPDATE
            SET email = EXCLUDED.email,
                photo_path = COALESCE(NULLIF(EXCLUDED.photo_path, ''), user_profiles.photo_path),
                updated_at = NOW()
            """,
            {
                "extension": extension,
                "email": email.strip() or None,
                "photo_path": photo_path.strip(),
            },
        )


def create_group(connection: psycopg.Connection, *, name: str, description: str, permission_name: str) -> None:
    with connection.cursor(row_factory=dict_row) as cursor:
        permission_id = _lookup_id(cursor, "user_permissions", permission_name)
        cursor.execute(
            """
            INSERT INTO user_groups (name, description, permission_id)
            VALUES (%(name)s, %(description)s, %(permission_id)s)
            ON CONFLICT (name) DO UPDATE
            SET description = EXCLUDED.description,
                permission_id = EXCLUDED.permission_id,
                updated_at = NOW()
            """,
            {"name": name.strip(), "description": description.strip(), "permission_id": permission_id},
        )


def create_permission(connection: psycopg.Connection, *, name: str, description: str, features: str) -> None:
    feature_list = [item.strip() for item in features.split(",") if item.strip()]
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_permissions (name, description, features)
            VALUES (%(name)s, %(description)s, %(features)s::jsonb)
            ON CONFLICT (name) DO UPDATE
            SET description = EXCLUDED.description,
                features = EXCLUDED.features,
                updated_at = NOW()
            """,
            {
                "name": name.strip(),
                "description": description.strip(),
                "features": json.dumps(feature_list),
            },
        )


def delete_group(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("DELETE FROM user_groups WHERE name = %(name)s RETURNING id", {"name": name})
        return bool(cursor.fetchone())


def delete_permission(connection: psycopg.Connection, name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("DELETE FROM user_permissions WHERE name = %(name)s RETURNING id", {"name": name})
        return bool(cursor.fetchone())


def save_user_photo(extension: str, upload_file) -> str:
    if not upload_file or not getattr(upload_file, "filename", ""):
        return ""
    suffix = Path(upload_file.filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    destination = PHOTO_DIR / f"{extension}{suffix}"
    file_obj: BinaryIO = upload_file.file
    file_obj.seek(0)
    with destination.open("wb") as output:
        shutil.copyfileobj(file_obj, output)
    return photo_url_from_path(destination.name)


def photo_url_from_path(photo_path: str | None) -> str:
    value = (photo_path or "").strip()
    if not value:
        return ""
    if value.startswith(f"{PHOTO_URL_PREFIX}/"):
        return value
    filename = Path(value).name
    return f"{PHOTO_URL_PREFIX}/{filename}" if filename else ""


def _lookup_id(cursor: psycopg.Cursor, table: str, name: str) -> int | None:
    if not name:
        return None
    cursor.execute(f"SELECT id FROM {table} WHERE name = %(name)s", {"name": name})
    row = cursor.fetchone()
    return row["id"] if row else None


def _normalize_features(value) -> list[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []
