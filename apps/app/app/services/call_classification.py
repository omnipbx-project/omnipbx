from __future__ import annotations


MISSED_DISPOSITIONS = {"NO ANSWER", "CANCEL", "BUSY", "FAILED", "CONGESTION"}


def sql_column(column: str, alias: str = "") -> str:
    return f"{alias}.{column}" if alias else column


def abandoned_call_condition(alias: str = "") -> str:
    direction = sql_column("direction", alias)
    queue_name = sql_column("queue_name", alias)
    ivr_name = sql_column("ivr_name", alias)
    callee_extension = sql_column("callee_extension", alias)
    disposition = sql_column("disposition", alias)
    return """
    COALESCE({direction}, 'unknown') = 'inbound'
    AND (
        COALESCE(NULLIF({queue_name}, ''), NULLIF({ivr_name}, ''), '') <> ''
        OR COALESCE(NULLIF({callee_extension}, ''), '') = ''
    )
    AND {disposition} <> 'ANSWERED'
    """.format(
        direction=direction,
        queue_name=queue_name,
        ivr_name=ivr_name,
        callee_extension=callee_extension,
        disposition=disposition,
    )


def customer_missed_call_condition(alias: str = "") -> str:
    direction = sql_column("direction", alias)
    disposition = sql_column("disposition", alias)
    return f"""
    COALESCE({direction}, 'unknown') = 'inbound'
    AND {disposition} = ANY(%(missed)s)
    AND NOT ({abandoned_call_condition(alias)})
    """


def callback_candidate_condition(alias: str = "") -> str:
    return f"(({customer_missed_call_condition(alias)}) OR ({abandoned_call_condition(alias)}))"


def is_abandoned_call(row: dict[str, object]) -> bool:
    if _clean(row.get("direction")) != "inbound":
        return False
    if _clean(row.get("disposition")) == "ANSWERED":
        return False
    has_queue_or_ivr = bool(_clean(row.get("queue_name")) or _clean(row.get("ivr_name")))
    has_callee_extension = bool(_clean(row.get("callee_extension")))
    return has_queue_or_ivr or not has_callee_extension


def is_customer_missed_call(row: dict[str, object]) -> bool:
    if _clean(row.get("direction")) != "inbound":
        return False
    if _clean(row.get("disposition")) not in MISSED_DISPOSITIONS:
        return False
    return not is_abandoned_call(row)


def is_callback_candidate(row: dict[str, object]) -> bool:
    return is_customer_missed_call(row) or is_abandoned_call(row)


def call_type_label(row: dict[str, object]) -> str:
    if is_abandoned_call(row):
        return "Abandoned"
    if is_customer_missed_call(row):
        return "Missed"
    direction = _clean(row.get("direction")) or "unknown"
    if direction == "inbound":
        return "Incoming"
    if direction == "outbound":
        return "Outgoing"
    return direction.replace("_", " ").title()


def _clean(value: object) -> str:
    return str(value or "").strip()
