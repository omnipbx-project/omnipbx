import json

import psycopg
from psycopg.rows import dict_row


LIST_RULES_SQL = """
SELECT id, section_slug, item_slug, name, enabled, config_json
FROM call_routing_rules
ORDER BY section_slug, item_slug, name;
"""

LIST_RULES_FOR_ITEM_SQL = """
SELECT id, section_slug, item_slug, name, enabled, config_json
FROM call_routing_rules
WHERE section_slug = %(section_slug)s
  AND item_slug = %(item_slug)s
ORDER BY name;
"""

UPSERT_RULE_SQL = """
INSERT INTO call_routing_rules (section_slug, item_slug, name, enabled, config_json)
VALUES (%(section_slug)s, %(item_slug)s, %(name)s, %(enabled)s, %(config_json)s::jsonb)
ON CONFLICT (section_slug, item_slug, name) DO UPDATE
SET enabled = EXCLUDED.enabled,
    config_json = EXCLUDED.config_json,
    updated_at = NOW()
RETURNING id, section_slug, item_slug, name, enabled, config_json;
"""

DELETE_RULE_SQL = """
DELETE FROM call_routing_rules
WHERE id = %(rule_id)s
RETURNING id;
"""


def list_call_routing_rules(connection: psycopg.Connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(LIST_RULES_SQL)
        return [_normalize_rule(row) for row in cursor.fetchall()]


def list_call_routing_item_rules(
    connection: psycopg.Connection,
    section_slug: str,
    item_slug: str,
) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            LIST_RULES_FOR_ITEM_SQL,
            {"section_slug": section_slug, "item_slug": item_slug},
        )
        return [_normalize_rule(row) for row in cursor.fetchall()]


def save_call_routing_rule(
    connection: psycopg.Connection,
    *,
    section_slug: str,
    item_slug: str,
    name: str,
    enabled: bool,
    config: dict[str, str],
) -> dict:
    values = {
        "section_slug": section_slug,
        "item_slug": item_slug,
        "name": name.strip(),
        "enabled": enabled,
        "config_json": json.dumps({key: value.strip() for key, value in config.items()}),
    }
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(UPSERT_RULE_SQL, values)
        return _normalize_rule(cursor.fetchone())


def delete_call_routing_rule(connection: psycopg.Connection, rule_id: int) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(DELETE_RULE_SQL, {"rule_id": rule_id})
        return bool(cursor.fetchone())


def rules_by_item(rules: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for rule in rules:
        grouped.setdefault((rule["section_slug"], rule["item_slug"]), []).append(rule)
    return grouped


def _normalize_rule(row: dict) -> dict:
    rule = dict(row)
    config = rule.get("config_json") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            config = {}
    rule["config"] = config
    return rule
