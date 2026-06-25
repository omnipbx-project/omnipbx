#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "apps" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import psycopg

from app.core.settings import get_settings
from app.services.call_logs import list_call_logs
from app.services.reports import build_reports


PREFIX = "qa-auto-report"
TEST_DAY = "2099-01-15"
EXPECTED = {
    "total": 8,
    "inbound": 5,
    "outbound": 2,
    "internal": 1,
    "answered": 4,
    "missed": 1,
    "abandoned": 2,
    "recorded": 2,
    "duration": 221,
    "billsec": 129,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed known QA CDR/CEL rows, compare Call Log and Reports totals, then clean them up."
    )
    parser.add_argument("--keep", action="store_true", help="Leave QA rows in cdr_raw/cel_raw for UI inspection.")
    parser.add_argument("--no-seed", action="store_true", help="Do not insert rows; validate existing QA rows only.")
    parser.add_argument("--cleanup-only", action="store_true", help="Delete QA rows and exit.")
    args = parser.parse_args()

    settings = get_settings()
    with psycopg.connect(settings.db_dsn, autocommit=True) as connection:
        if args.cleanup_only:
            deleted = cleanup(connection)
            print(f"Removed {deleted} QA rows.")
            return 0

        if not args.no_seed:
            cleanup(connection)
            seed(connection)

        failures = validate(connection)
        if not args.keep:
            cleanup(connection)

    if failures:
        print("\nFAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nPASS: Call Log and Reports matched the expected QA dataset.")
    if args.keep:
        print(f"QA rows were kept. Open Reports with custom range {TEST_DAY} to {TEST_DAY}.")
    return 0


def cleanup(connection: psycopg.Connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM cel_raw WHERE uniqueid LIKE %s OR linkedid LIKE %s", (f"{PREFIX}%", f"{PREFIX}%"))
        cel_deleted = cursor.rowcount
        cursor.execute("DELETE FROM cdr_raw WHERE uniqueid LIKE %s OR linkedid LIKE %s", (f"{PREFIX}%", f"{PREFIX}%"))
        cdr_deleted = cursor.rowcount
    return int(cdr_deleted + cel_deleted)


def seed(connection: psycopg.Connection) -> None:
    base = datetime(2099, 1, 15, 10, 0, tzinfo=UTC)
    rows = [
        cdr(1, base, "inbound", "ANSWERED", 70, 45, src="+15550000001", dst="09639145345", trunk="icc", route="qa-inbound", queue="qa-support", ivr="qa-main-menu", callee="10000"),
        cdr(2, base, "inbound", "NO ANSWER", 20, 0, src="+15550000002", dst="1099", trunk="icc", route="qa-inbound", callee="1099"),
        cdr(3, base, "inbound", "NO ANSWER", 15, 0, src="+15550000003", dst="6399", trunk="icc", route="qa-inbound", queue="qa-support"),
        cdr(4, base, "inbound", "CANCEL", 6, 0, src="+15550000004", dst="6499", trunk="icc", route="qa-inbound", ivr="qa-main-menu"),
        cdr(5, base, "inbound", "ANSWERED", 30, 24, src="+15550000005", dst="1099", trunk="icc", route="qa-inbound", callee="1099", recording="qa-auto-inbound.wav"),
        cdr(6, base, "outbound", "ANSWERED", 50, 40, src="1099", dst="8801712345678", trunk="icc", caller="1099", recording="qa-auto-outbound.wav"),
        cdr(7, base, "outbound", "FAILED", 5, 0, src="1099", dst="8801799999999", trunk="icc", caller="1099"),
        cdr(8, base, "internal", "ANSWERED", 25, 20, src="1099", dst="1002", caller="1099", callee="1002"),
    ]
    with connection.cursor() as cursor:
        for row in rows:
            cursor.execute(
                """
                INSERT INTO cdr_raw (
                    calldate, uniqueid, linkedid, src, dst, clid, channel, dstchannel, dcontext,
                    lastapp, lastdata, duration, billsec, disposition, amaflags, recordingfile,
                    direction, trunk_name, route_name, queue_name, ivr_name, caller_extension, callee_extension
                )
                VALUES (
                    %(calldate)s, %(uniqueid)s, %(linkedid)s, %(src)s, %(dst)s, %(clid)s, %(channel)s, %(dstchannel)s, %(dcontext)s,
                    %(lastapp)s, %(lastdata)s, %(duration)s, %(billsec)s, %(disposition)s, 'DOCUMENTATION', %(recordingfile)s,
                    %(direction)s, %(trunk_name)s, %(route_name)s, %(queue_name)s, %(ivr_name)s, %(caller_extension)s, %(callee_extension)s
                )
                """,
                row,
            )
            cursor.execute(
                """
                INSERT INTO cel_raw (
                    eventtype, eventtime, cid_num, exten, context, appname, appdata, uniqueid, linkedid
                )
                VALUES ('CHAN_END', %(calldate)s, %(src)s, %(dst)s, %(dcontext)s, %(lastapp)s, %(lastdata)s, %(uniqueid)s, %(linkedid)s)
                """,
                row,
            )


def cdr(
    index: int,
    base: datetime,
    direction: str,
    disposition: str,
    duration: int,
    billsec: int,
    *,
    src: str,
    dst: str,
    trunk: str = "",
    route: str = "",
    queue: str = "",
    ivr: str = "",
    caller: str = "",
    callee: str = "",
    recording: str = "",
) -> dict[str, object]:
    uniqueid = f"{PREFIX}-{index:02d}"
    lastapp = "Queue" if queue else ("Background" if ivr and disposition != "ANSWERED" else "Dial")
    return {
        "calldate": base + timedelta(minutes=index),
        "uniqueid": uniqueid,
        "linkedid": uniqueid,
        "src": src,
        "dst": dst,
        "clid": src,
        "channel": f"PJSIP/{src}-{index}",
        "dstchannel": f"PJSIP/{dst}-{index}" if callee else "",
        "dcontext": "qa-auto",
        "lastapp": lastapp,
        "lastdata": queue or dst,
        "duration": duration,
        "billsec": billsec,
        "disposition": disposition,
        "recordingfile": recording,
        "direction": direction,
        "trunk_name": trunk,
        "route_name": route,
        "queue_name": queue,
        "ivr_name": ivr,
        "caller_extension": caller,
        "callee_extension": callee,
    }


def validate(connection: psycopg.Connection) -> list[str]:
    failures: list[str] = []
    db_counts = fetch_db_counts(connection)
    expect_equal(failures, "DB total", db_counts["total"], EXPECTED["total"])
    expect_equal(failures, "DB inbound", db_counts["inbound"], EXPECTED["inbound"])
    expect_equal(failures, "DB outbound", db_counts["outbound"], EXPECTED["outbound"])
    expect_equal(failures, "DB internal", db_counts["internal"], EXPECTED["internal"])
    expect_equal(failures, "DB answered", db_counts["answered"], EXPECTED["answered"])
    expect_equal(failures, "DB recorded", db_counts["recorded"], EXPECTED["recorded"])
    expect_equal(failures, "DB duration", db_counts["duration"], EXPECTED["duration"])
    expect_equal(failures, "DB billsec", db_counts["billsec"], EXPECTED["billsec"])
    expect_equal(failures, "CEL event rows", db_counts["cel"], EXPECTED["total"])

    call_logs = list_call_logs(
        connection,
        date_from=TEST_DAY,
        date_to=TEST_DAY,
        timezone_name="UTC",
        limit=50,
    )
    log_summary = call_logs["summary"]
    log_counts = call_logs["category_counts"]
    expect_equal(failures, "Call Log total", log_summary["total_calls"], EXPECTED["total"])
    expect_equal(failures, "Call Log inbound", log_summary["total_inbound"], EXPECTED["inbound"])
    expect_equal(failures, "Call Log outbound", log_summary["total_outbound"], EXPECTED["outbound"])
    expect_equal(failures, "Call Log internal", log_summary["total_internal"], EXPECTED["internal"])
    expect_equal(failures, "Call Log answered", log_summary["total_answered"], EXPECTED["answered"])
    expect_equal(failures, "Call Log missed", log_summary["total_missed"], EXPECTED["missed"])
    expect_equal(failures, "Call Log duration", log_summary["total_duration"], EXPECTED["duration"])
    expect_equal(failures, "Call Log billsec", log_summary["total_billsec"], EXPECTED["billsec"])
    expect_equal(failures, "Call Log category all", log_counts["all"], EXPECTED["total"])
    expect_equal(failures, "Call Log category incoming", log_counts["incoming"], EXPECTED["inbound"])
    expect_equal(failures, "Call Log category outgoing", log_counts["outgoing"], EXPECTED["outbound"])
    expect_equal(failures, "Call Log category missed", log_counts["missed"], EXPECTED["missed"])
    expect_equal(failures, "Call Log category abandoned", log_counts["abandoned"], EXPECTED["abandoned"])

    reports = build_reports(
        connection,
        section="overview",
        range_key="custom",
        date_from=TEST_DAY,
        date_to=TEST_DAY,
    )
    calls = reports["calls"]
    expect_equal(failures, "Reports total", calls["total"], EXPECTED["total"])
    expect_equal(failures, "Reports inbound", calls["inbound"], EXPECTED["inbound"])
    expect_equal(failures, "Reports outbound", calls["outbound"], EXPECTED["outbound"])
    expect_equal(failures, "Reports internal", calls["internal"], EXPECTED["internal"])
    expect_equal(failures, "Reports answered", calls["answered"], EXPECTED["answered"])
    expect_equal(failures, "Reports missed", calls["missed"], EXPECTED["missed"])
    expect_equal(failures, "Reports abandoned", calls["abandoned"], EXPECTED["abandoned"])
    expect_equal(failures, "Reports recorded", calls["recorded"], EXPECTED["recorded"])
    expect_equal(failures, "Reports duration", calls["total_duration"], EXPECTED["duration"])
    expect_equal(failures, "Reports talk time", calls["total_talk_time"], EXPECTED["billsec"])
    return failures


def fetch_db_counts(connection: psycopg.Connection) -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE direction = 'inbound') AS inbound,
                COUNT(*) FILTER (WHERE direction = 'outbound') AS outbound,
                COUNT(*) FILTER (WHERE direction = 'internal') AS internal,
                COUNT(*) FILTER (WHERE disposition = 'ANSWERED') AS answered,
                COUNT(*) FILTER (WHERE COALESCE(NULLIF(recordingfile, ''), '') <> '') AS recorded,
                COALESCE(SUM(duration), 0) AS duration,
                COALESCE(SUM(billsec), 0) AS billsec
            FROM cdr_raw
            WHERE uniqueid LIKE %s
            """,
            (f"{PREFIX}%",),
        )
        row = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM cel_raw WHERE uniqueid LIKE %s", (f"{PREFIX}%",))
        cel_count = cursor.fetchone()[0]
    keys = ("total", "inbound", "outbound", "internal", "answered", "recorded", "duration", "billsec")
    return {**{key: int(value or 0) for key, value in zip(keys, row, strict=True)}, "cel": int(cel_count or 0)}


def expect_equal(failures: list[str], label: str, actual: object, expected: object) -> None:
    if int(actual or 0) != int(expected or 0):
        failures.append(f"{label}: expected {expected}, got {actual}")


if __name__ == "__main__":
    raise SystemExit(main())
