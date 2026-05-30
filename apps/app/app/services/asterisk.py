from pathlib import Path
import re
import subprocess
from datetime import date

import psycopg
from psycopg.rows import dict_row

from app.core.settings import get_settings
from app.services.audio import normalize_sound_name


DEFAULT_EXTENSION_TRANSPORT = "transport-udp"
DEFAULT_EXTENSION_CODECS = "ulaw,alaw,g722"
DEFAULT_EXTENSION_VIDEO_CODECS = ""
WEBPHONE_TRANSPORT = "transport-wss"
SOFTPHONE_TRANSPORT = "transport-udp-softphone"


FETCH_ENABLED_EXTENSIONS_SQL = """
SELECT extension, display_name, secret, context, transport, codecs, video_codecs, call_recording_enabled
FROM extensions
WHERE enabled = TRUE
ORDER BY extension;
"""

FETCH_ENABLED_TRUNKS_SQL = """
SELECT name, provider_name, host, username, password, transport, register_enabled,
       match_ip, codecs, outbound_prefix, strip_digits
FROM trunks
WHERE enabled = TRUE
ORDER BY name;
"""

FETCH_ENABLED_INBOUND_ROUTES_SQL = """
SELECT name, trunk_name, did_pattern, destination_type, destination_value
FROM inbound_routes
WHERE enabled = TRUE
ORDER BY trunk_name, name;
"""

FETCH_ENABLED_RING_GROUPS_SQL = """
SELECT id, name, extension, ring_strategy, ring_timeout
FROM ring_groups
WHERE enabled = TRUE
ORDER BY extension;
"""

FETCH_RING_GROUP_MEMBERS_SQL = """
SELECT ring_group_id, extension, position
FROM ring_group_members
ORDER BY ring_group_id, position, extension;
"""

FETCH_ENABLED_QUEUES_SQL = """
SELECT id, name, extension, strategy, timeout, retry, wrapuptime, max_wait_time,
       announce_position, musicclass, moh_file_name
FROM queues_custom
WHERE enabled = TRUE
ORDER BY extension;
"""

FETCH_QUEUE_MEMBERS_SQL = """
SELECT queue_id, extension, member_order
FROM queue_members_custom
ORDER BY queue_id, member_order, extension;
"""

FETCH_ENABLED_IVRS_SQL = """
SELECT id, name, extension, prompt, timeout, invalid_retries
FROM ivr_menus
WHERE enabled = TRUE
ORDER BY extension;
"""

FETCH_IVR_OPTIONS_SQL = """
SELECT ivr_id, digit, destination_type, destination_value
FROM ivr_options
ORDER BY ivr_id, digit;
"""

FETCH_ENABLED_WORKING_HOURS_SQL = """
SELECT name, start_day, end_day, start_time, end_time, inbound_route_name, after_hours_sound
FROM working_hours
WHERE enabled = TRUE
ORDER BY name;
"""

FETCH_ENABLED_WELCOME_MESSAGES_SQL = """
SELECT name, sound_name, inbound_route_name
FROM welcome_messages
WHERE enabled = TRUE
ORDER BY name;
"""

FETCH_ENABLED_CALL_ROUTING_RULES_SQL = """
SELECT section_slug, item_slug, name, config_json
FROM call_routing_rules
WHERE enabled = TRUE
ORDER BY section_slug, item_slug, name;
"""

FETCH_ADVANCED_SECURITY_RULES_SQL = """
SELECT rule_type, value, note, enabled
FROM advanced_security_rules
WHERE enabled = TRUE
ORDER BY rule_type, value;
"""

FETCH_ADVANCED_CUSTOM_CONFIG_SQL = """
SELECT config_key, content, enabled
FROM advanced_custom_config
WHERE enabled = TRUE;
"""

DAY_CODE_MAP = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}

MONTH_CODE_MAP = {
    1: "jan",
    2: "feb",
    3: "mar",
    4: "apr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "aug",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dec",
}


def sync_asterisk_config(connection: psycopg.Connection, reload_config: bool = True) -> dict[str, str | int]:
    settings = get_settings()
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(FETCH_ENABLED_EXTENSIONS_SQL)
        extensions = list(cursor.fetchall())
        cursor.execute(FETCH_ENABLED_TRUNKS_SQL)
        trunks = list(cursor.fetchall())
        cursor.execute(FETCH_ENABLED_INBOUND_ROUTES_SQL)
        inbound_routes = list(cursor.fetchall())
        cursor.execute(FETCH_ENABLED_RING_GROUPS_SQL)
        ring_groups = list(cursor.fetchall())
        cursor.execute(FETCH_RING_GROUP_MEMBERS_SQL)
        ring_group_members = list(cursor.fetchall())
        cursor.execute(FETCH_ENABLED_QUEUES_SQL)
        queues = list(cursor.fetchall())
        cursor.execute(FETCH_QUEUE_MEMBERS_SQL)
        queue_members = list(cursor.fetchall())
        cursor.execute(FETCH_ENABLED_IVRS_SQL)
        ivrs = list(cursor.fetchall())
        cursor.execute(FETCH_IVR_OPTIONS_SQL)
        ivr_options = list(cursor.fetchall())
        cursor.execute(FETCH_ENABLED_WORKING_HOURS_SQL)
        working_hours = list(cursor.fetchall())
        cursor.execute(FETCH_ENABLED_WELCOME_MESSAGES_SQL)
        welcome_messages = list(cursor.fetchall())
        cursor.execute(FETCH_ENABLED_CALL_ROUTING_RULES_SQL)
        call_routing_rules = list(cursor.fetchall())
        cursor.execute(FETCH_ADVANCED_SECURITY_RULES_SQL)
        advanced_security_rules = list(cursor.fetchall())
        cursor.execute(FETCH_ADVANCED_CUSTOM_CONFIG_SQL)
        advanced_custom_config = list(cursor.fetchall())

    ring_groups = _attach_group_members(ring_groups, ring_group_members, "id", "ring_group_id")
    queues = _attach_group_members(queues, queue_members, "id", "queue_id", member_key="member_order")
    ivrs = _attach_ivr_options(ivrs, ivr_options)

    pjsip_text = render_pjsip_config(extensions) + _custom_config_text(advanced_custom_config, "pjsip")
    dialplan_text = render_extensions_config(extensions, call_routing_rules) + _custom_config_text(advanced_custom_config, "dialplan")
    pjsip_trunks_text = render_trunk_pjsip_config(trunks)
    trunks_dialplan_text = render_trunk_dialplan(trunks, call_routing_rules, extensions)
    ring_groups_text = render_ring_groups_config(ring_groups)
    queues_text = render_queues_config(queues)
    queues_dialplan_text = render_queues_dialplan(queues)
    ivrs_text = render_ivrs_config(ivrs, queues)
    musiconhold_text = render_musiconhold_config(queues)
    voicemail_text = render_voicemail_config(extensions, call_routing_rules)
    inbound_routes_text = render_inbound_routes_config(
        inbound_routes,
        queues=queues,
        ivrs=ivrs,
        ring_groups=ring_groups,
        working_hours=working_hours,
        welcome_messages=welcome_messages,
        call_routing_rules=call_routing_rules,
        extensions=extensions,
        advanced_security_rules=advanced_security_rules,
    )

    Path(settings.generated_config_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.pjsip_generated_file).write_text(pjsip_text, encoding="utf-8")
    Path(settings.extensions_generated_file).write_text(dialplan_text, encoding="utf-8")
    Path(settings.pjsip_trunks_generated_file).write_text(pjsip_trunks_text, encoding="utf-8")
    Path(settings.trunks_generated_file).write_text(trunks_dialplan_text, encoding="utf-8")
    Path(settings.ring_groups_generated_file).write_text(ring_groups_text, encoding="utf-8")
    Path(settings.queues_generated_file).write_text(queues_text, encoding="utf-8")
    Path(settings.queues_dialplan_generated_file).write_text(queues_dialplan_text, encoding="utf-8")
    Path(settings.ivrs_generated_file).write_text(ivrs_text, encoding="utf-8")
    Path(settings.musiconhold_generated_file).write_text(musiconhold_text, encoding="utf-8")
    Path(settings.voicemail_generated_file).write_text(voicemail_text, encoding="utf-8")
    Path(settings.inbound_routes_generated_file).write_text(inbound_routes_text, encoding="utf-8")

    if not reload_config:
        return {
            "status": "written",
            "extension_count": len(extensions),
            "trunk_count": len(trunks),
            "inbound_route_count": len(inbound_routes),
            "ring_group_count": len(ring_groups),
            "queue_count": len(queues),
            "ivr_count": len(ivrs),
        }

    completed = subprocess.run(
        ["asterisk", "-rx", settings.asterisk_reload_command],
        capture_output=True,
        text=True,
        check=False,
    )
    status = "reloaded" if completed.returncode == 0 else "reload_failed"
    return {
        "status": status,
        "extension_count": len(extensions),
        "trunk_count": len(trunks),
        "inbound_route_count": len(inbound_routes),
        "ring_group_count": len(ring_groups),
        "queue_count": len(queues),
        "ivr_count": len(ivrs),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _attach_group_members(
    rows: list[dict],
    members: list[dict],
    row_id_key: str,
    member_parent_key: str,
    member_key: str = "position",
) -> list[dict]:
    members_by_parent: dict[int, list[str]] = {}
    for member in members:
        members_by_parent.setdefault(member[member_parent_key], []).append(member["extension"])
    for row in rows:
        row["members"] = members_by_parent.get(row[row_id_key], [])
    return rows


def _attach_ivr_options(ivrs: list[dict], options: list[dict]) -> list[dict]:
    options_by_ivr: dict[int, list[dict]] = {}
    for option in options:
        options_by_ivr.setdefault(option["ivr_id"], []).append(
            {
                "digit": option["digit"],
                "destination_type": option["destination_type"],
                "destination_value": option["destination_value"],
            }
        )
    for ivr in ivrs:
        ivr["options"] = options_by_ivr.get(ivr["id"], [])
    return ivrs


def render_pjsip_config(extensions: list[dict]) -> str:
    blocks = ["; This file is generated by OmniPBX.\n"]
    for item in extensions:
        extension = item["extension"]
        display_name = item["display_name"]
        secret = item["secret"]
        context = item["context"]
        transport = item.get("transport") or DEFAULT_EXTENSION_TRANSPORT
        pjsip_transport = WEBPHONE_TRANSPORT if transport == WEBPHONE_TRANSPORT else DEFAULT_EXTENSION_TRANSPORT
        codecs = item.get("codecs") or DEFAULT_EXTENSION_CODECS
        video_codecs = item.get("video_codecs") or DEFAULT_EXTENSION_VIDEO_CODECS
        allowed_codecs = ",".join(
            codec_group for codec_group in [codecs, video_codecs] if codec_group
        )
        webphone_options = ""
        if transport == WEBPHONE_TRANSPORT:
            webphone_options = (
                "webrtc = yes\n"
                "use_avpf = yes\n"
                "media_encryption = dtls\n"
                "dtls_auto_generate_cert = yes\n"
                "ice_support = yes\n"
                "rtcp_mux = yes\n"
                "media_use_received_transport = yes\n"
            )
        blocks.append(
            (
                f"[{extension}]\n"
                "type = endpoint\n"
                f"transport = {pjsip_transport}\n"
                f"context = {context}\n"
                "disallow = all\n"
                f"allow = {allowed_codecs}\n"
                "identify_by = username,auth_username\n"
                f"auth = auth-{extension}\n"
                f"aors = {extension}\n"
                f"callerid = {display_name} <{extension}>\n"
                "direct_media = no\n"
                "force_rport = yes\n"
                "rewrite_contact = yes\n"
                "rtp_symmetric = yes\n"
                f"{webphone_options}"
                "\n"
                f"[auth-{extension}]\n"
                "type = auth\n"
                "auth_type = userpass\n"
                f"username = {extension}\n"
                f"password = {secret}\n"
                "\n"
                f"[{extension}]\n"
                "type = aor\n"
                "max_contacts = 1\n"
                "remove_existing = yes\n"
                "qualify_frequency = 60\n\n"
            )
        )
    return "".join(blocks)


def render_extensions_config(extensions: list[dict], call_routing_rules: list[dict] | None = None) -> str:
    blocks = ["; This file is generated by OmniPBX.\n"]
    recording_extensions = _recording_extensions(extensions)
    blocks.append("exten => *97,1,VoiceMailMain(${CALLERID(num)}@default)\n")
    blocks.append(" same => n,Hangup()\n")
    blocks.append("exten => *98,1,VoiceMailMain(@default)\n")
    blocks.append(" same => n,Hangup()\n\n")
    for item in extensions:
        extension = item["extension"]
        blocks.append(
            (
                f"exten => {extension},1,NoOp(OmniPBX call to {extension})\n"
                " same => n,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n"
                " same => n,Set(CDR(direction)=internal)\n"
                " same => n,Set(CDR(caller_extension)=${CALLERID(num)})\n"
                f" same => n,Set(CDR(callee_extension)={extension})\n"
                f"{_render_recording_lines(recording_extensions, target=extension, target_variable='EXTEN')}"
                f" same => n,Dial(PJSIP/{extension},20)\n"
                " same => n,Hangup()\n"
                f"exten => {extension},hint,PJSIP/{extension}\n\n"
            )
        )
    rules = call_routing_rules or []
    for rule in _rules_for(rules, "internal-calls", "voicemail"):
        config = _rule_config(rule)
        extension = config.get("extension")
        mailbox = config.get("mailbox") or extension
        if not extension or not mailbox:
            continue
        blocks.append(
            (
                f"exten => {extension},1,NoOp(Internal voicemail {rule['name']})\n"
                f" same => n,VoiceMail({mailbox}@default,u)\n"
                " same => n,Hangup()\n\n"
            )
        )
    for rule in _rules_for(rules, "internal-calls", "conference-rooms"):
        config = _rule_config(rule)
        room = config.get("room")
        pin = config.get("pin")
        if not room:
            continue
        blocks.append(
            (
                f"exten => {room},1,NoOp(Conference room {rule['name']})\n"
            )
        )
        if pin:
            blocks.append(f" same => n,Authenticate({pin})\n")
        blocks.append(f" same => n,ConfBridge({room})\n")
        blocks.append(" same => n,Hangup()\n\n")
    return "".join(blocks)


def _is_ip_like(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Fa-f:.]+(?:/\d{1,3})?", value))


def _default_match_ip(trunk: dict) -> str | None:
    match_ip = trunk.get("match_ip")
    if match_ip:
        return str(match_ip).strip()
    host = str(trunk["host"]).strip()
    if _is_ip_like(host):
        return host
    return None


def _default_server_uri(trunk: dict) -> str:
    host = str(trunk["host"]).strip()
    if host.startswith("sip:"):
        return host
    return f"sip:{host}"


def _default_client_uri(trunk: dict) -> str:
    username = trunk.get("username")
    server_uri = _default_server_uri(trunk)
    if username:
        host = server_uri.replace("sip:", "", 1)
        return f"sip:{username}@{host}"
    return server_uri


def _trunk_context(name: str) -> str:
    return f"from-trunk-{name}"


def _route_context(name: str) -> str:
    return f"inbound-route-{name}"


def _ring_group_context(extension: str) -> str:
    return f"ring-group-{extension}"


def _ivr_context(extension: str) -> str:
    return f"ivr-{extension}"


def _queue_application(queue: dict) -> str:
    queue_name = queue["name"]
    max_wait_time = queue.get("max_wait_time")
    if max_wait_time:
        return f"Queue({queue_name},t,,,{int(max_wait_time)})"
    return f"Queue({queue_name},t)"


def _recording_extensions(extensions: list[dict]) -> set[str]:
    return {str(item["extension"]) for item in extensions if item.get("call_recording_enabled")}


def _custom_config_text(rows: list[dict], config_key: str) -> str:
    for row in rows:
        if row.get("config_key") == config_key and row.get("enabled") and row.get("content"):
            return f"\n; Advanced custom {config_key} starts\n{row['content'].rstrip()}\n; Advanced custom {config_key} ends\n"
    return ""


def _render_recording_lines(
    recording_extensions: set[str],
    *,
    target: str | None = None,
    target_variable: str = "EXTEN",
) -> str:
    should_record_target = bool(target and target in recording_extensions)
    caller_checks = [f'"${{CALLERID(num)}}" = "{extension}"' for extension in sorted(recording_extensions)]
    lines: list[str] = []
    if should_record_target:
        lines.extend(_recording_start_lines(target_variable))
        return "".join(f"{line}\n" for line in lines)
    if not caller_checks:
        return ""
    expression = " | ".join(caller_checks)
    lines.append(f" same => n,GotoIf($[{expression}]?record-call)")
    lines.append(" same => n,Goto(after-record-check)")
    lines.extend(_recording_start_lines(target_variable, label="record-call"))
    lines.append(" same => n(after-record-check),NoOp(Recording check done)")
    return "".join(f"{line}\n" for line in lines)


def _recording_start_lines(target_variable: str, *, label: str | None = None) -> list[str]:
    prefix = f" same => n({label})" if label else " same => n"
    return [
        f"{prefix},Set(OMNI_RECORDING_FILE=${{STRFTIME(${{EPOCH}},,%Y%m%d-%H%M%S)}}-${{CHANNEL(linkedid)}}-${{CALLERID(num)}}-${{{target_variable}}}.wav)",
        " same => n,Set(CDR(recordingfile)=${OMNI_RECORDING_FILE})",
        " same => n,MixMonitor(${OMNI_RECORDING_FILE},b)",
    ]


def _render_destination_same_lines(
    destination_type: str,
    destination_value: str,
    queues_by_extension: dict[str, dict],
    *,
    hangup: bool = True,
) -> list[str]:
    if destination_type == "extension":
        return [
            f" same => n,Set(CDR(callee_extension)={destination_value})",
            f" same => n,Goto(omnipbx-internal,{destination_value},1)",
        ]
    if destination_type == "trunk":
        return [
            " same => n,Set(CDR(direction)=outbound)",
            f" same => n,Dial(PJSIP/${{EXTEN}}@{destination_value},60)",
            " same => n,Hangup()",
        ]
    if destination_type == "ring_group":
        return [
            f" same => n,Set(CDR(callee_extension)={destination_value})",
            f" same => n,Goto({_ring_group_context(destination_value)},s,1)",
        ]
    if destination_type == "ivr":
        return [f" same => n,Goto({_ivr_context(destination_value)},s,1)"]
    if destination_type == "queue":
        queue = queues_by_extension.get(destination_value)
        queue_name = queue["name"] if queue else destination_value
        max_wait_time = queue.get("max_wait_time") if queue else None
        queue_app = _queue_application({"name": queue_name, "max_wait_time": max_wait_time})
        lines = [
            f" same => n,Set(CDR(queue_name)={queue_name})",
            f" same => n,Set(CDR(callee_extension)={destination_value})",
            f" same => n,{queue_app}",
        ]
        if hangup:
            lines.append(" same => n,Hangup()")
        return lines
    return [" same => n,Playback(ss-noservice)", " same => n,Hangup()"]


def render_trunk_pjsip_config(trunks: list[dict]) -> str:
    blocks = ["; This file is generated by OmniPBX.\n"]
    for trunk in trunks:
        name = trunk["name"]
        username = trunk.get("username")
        password = trunk.get("password")
        transport = trunk["transport"]
        codecs = trunk["codecs"] or "ulaw,alaw"
        context = _trunk_context(name)
        identify_match = _default_match_ip(trunk)

        blocks.append(
            (
                f"[{name}]\n"
                "type = endpoint\n"
                f"transport = {transport}\n"
                f"context = {context}\n"
                "disallow = all\n"
                f"allow = {codecs}\n"
                f"aors = {name}\n"
                "direct_media = no\n"
                "force_rport = yes\n"
                "rewrite_contact = yes\n"
                "rtp_symmetric = yes\n"
                "trust_id_inbound = yes\n"
                "send_pai = yes\n"
            )
        )
        if username and password:
            blocks.append(f"outbound_auth = auth-{name}\n")
        blocks.append("\n")

        if username and password:
            blocks.append(
                (
                    f"[auth-{name}]\n"
                    "type = auth\n"
                    "auth_type = userpass\n"
                    f"username = {username}\n"
                    f"password = {password}\n\n"
                )
            )

        blocks.append(f"[{name}]\n")
        blocks.append("type = aor\n")
        if trunk.get("register_enabled"):
            blocks.append("max_contacts = 1\n")
            blocks.append("remove_existing = yes\n")
            blocks.append("qualify_frequency = 60\n")
        else:
            blocks.append(f"contact = {_default_server_uri(trunk)}\n")
            blocks.append("qualify_frequency = 60\n")
        blocks.append("\n")

        if identify_match:
            blocks.append(
                (
                    f"[identify-{name}]\n"
                    "type = identify\n"
                    f"endpoint = {name}\n"
                    f"match = {identify_match}\n\n"
                )
            )

        if trunk.get("register_enabled") and username and password:
            blocks.append(
                (
                    f"[reg-{name}]\n"
                    "type = registration\n"
                    f"transport = {transport}\n"
                    f"outbound_auth = auth-{name}\n"
                    f"server_uri = {_default_server_uri(trunk)}\n"
                    f"client_uri = {_default_client_uri(trunk)}\n"
                    f"contact_user = {username}\n"
                    f"endpoint = {name}\n"
                    "retry_interval = 60\n"
                    "forbidden_retry_interval = 600\n"
                    "expiration = 3600\n\n"
                )
            )

    return "".join(blocks)


def render_trunk_dialplan(
    trunks: list[dict],
    call_routing_rules: list[dict] | None = None,
    extensions: list[dict] | None = None,
) -> str:
    blocks = [
        "; This file is generated by OmniPBX.\n",
        "[from-internal-trunks]\n",
    ]
    rules = call_routing_rules or []
    recording_extensions = _recording_extensions(extensions or [])
    for rule in _rules_for(rules, "outgoing-calls", "routes"):
        config = _rule_config(rule)
        pattern = _asterisk_prefix_pattern(config.get("dial_pattern", ""))
        trunk_name = config.get("trunk")
        if not pattern or not trunk_name:
            continue
        remove_digits = int(config.get("remove_digits") or 0)
        blocks.append(
            (
                f"exten => {pattern},1,NoOp(Outgoing route {rule['name']})\n"
                " same => n,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n"
                " same => n,Set(CDR(direction)=outbound)\n"
                " same => n,Set(CDR(caller_extension)=${CALLERID(num)})\n"
                f" same => n,Set(CDR(trunk_name)={trunk_name})\n"
                f" same => n,Set(OUTNUM=${{EXTEN:{remove_digits}}})\n"
                f"{_render_recording_lines(recording_extensions, target_variable='OUTNUM')}"
                f" same => n,Dial(PJSIP/${{OUTNUM}}@{trunk_name},60)\n"
                " same => n,Hangup()\n\n"
            )
        )
    for rule in _rules_for(rules, "outgoing-calls", "dial-rules"):
        config = _rule_config(rule)
        pattern = _asterisk_prefix_pattern(config.get("dial_pattern", ""))
        replace_with = config.get("replace_with", "")
        trunk_name = trunks[0]["name"] if trunks else ""
        if not pattern or not trunk_name:
            continue
        blocks.append(
            (
                f"exten => {pattern},1,NoOp(Dial rule {rule['name']})\n"
                " same => n,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n"
                " same => n,Set(CDR(direction)=outbound)\n"
                " same => n,Set(CDR(caller_extension)=${CALLERID(num)})\n"
                f" same => n,Set(CDR(trunk_name)={trunk_name})\n"
                f" same => n,Set(OUTNUM={replace_with}${{EXTEN:1}})\n"
                f"{_render_recording_lines(recording_extensions, target_variable='OUTNUM')}"
                f" same => n,Dial(PJSIP/${{OUTNUM}}@{trunk_name},60)\n"
                " same => n,Hangup()\n\n"
            )
        )
    for trunk in trunks:
        prefix = trunk.get("outbound_prefix")
        if not prefix:
            continue
        strip_digits = int(trunk.get("strip_digits") or 0)
        name = trunk["name"]
        prefix_len = len(prefix) + strip_digits
        blocks.append(
            (
                f"exten => _{prefix}X.,1,NoOp(Outbound via trunk {name})\n"
                " same => n,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n"
                " same => n,Set(CDR(direction)=outbound)\n"
                " same => n,Set(CDR(caller_extension)=${CALLERID(num)})\n"
                f" same => n,Set(CDR(trunk_name)={name})\n"
                f" same => n,Set(OUTNUM=${{EXTEN:{prefix_len}}})\n"
                f"{_render_recording_lines(recording_extensions, target_variable='OUTNUM')}"
                f" same => n,Dial(PJSIP/${{OUTNUM}}@{name},60)\n"
                " same => n,Hangup()\n\n"
            )
        )
    if len(blocks) == 2:
        blocks.append("exten => _X.,1,Hangup()\n")
    return "".join(blocks)


def render_ring_groups_config(ring_groups: list[dict]) -> str:
    blocks = ["; This file is generated by OmniPBX.\n", "[from-internal-ring-groups]\n"]
    if not ring_groups:
        blocks.append("exten => _X.,1,Hangup()\n")
        return "".join(blocks)

    for group in ring_groups:
        blocks.append(f"exten => {group['extension']},1,Goto({_ring_group_context(group['extension'])},s,1)\n")
    blocks.append("\n")

    for group in ring_groups:
        blocks.append(f"[{_ring_group_context(group['extension'])}]\n")
        blocks.append(f"exten => s,1,NoOp(Ring group {group['name']})\n")
        blocks.append(" same => n,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n")
        blocks.append(f" same => n,Set(CDR(callee_extension)={group['extension']})\n")
        members = group.get("members", [])
        if not members:
            blocks.append(" same => n,Playback(ss-noservice)\n")
            blocks.append(" same => n,Hangup()\n\n")
            continue
        timeout = int(group["ring_timeout"])
        if group["ring_strategy"] == "linear":
            for index, member in enumerate(members):
                label = "start" if index == 0 else f"try{index + 1}"
                blocks.append(f" same => n({label}),Dial(PJSIP/{member},{timeout})\n")
                blocks.append(" same => n,GotoIf($[\"${DIALSTATUS}\" = \"ANSWER\"]?done)\n")
            blocks.append(" same => n,Hangup()\n")
            blocks.append(" same => n(done),Hangup()\n\n")
        else:
            joined = "&".join(f"PJSIP/{member}" for member in members)
            blocks.append(f" same => n,Dial({joined},{timeout})\n")
            blocks.append(" same => n,Hangup()\n\n")
    return "".join(blocks)


def render_queues_config(queues: list[dict]) -> str:
    blocks = ["; This file is generated by OmniPBX.\n"]
    if not queues:
        return "".join(blocks)
    for queue in queues:
        blocks.append(f"[{queue['name']}]\n")
        blocks.append(f"strategy={queue['strategy']}\n")
        blocks.append(f"timeout={int(queue['timeout'])}\n")
        blocks.append(f"retry={int(queue['retry'])}\n")
        blocks.append(f"wrapuptime={int(queue['wrapuptime'])}\n")
        blocks.append(f"announce-position={'yes' if queue['announce_position'] else 'no'}\n")
        blocks.append("autofill=yes\n")
        blocks.append("ringinuse=no\n")
        blocks.append("setinterfacevar=yes\n")
        blocks.append(f"musicclass={queue['musicclass'] or 'default'}\n")
        for member in queue.get("members", []):
            blocks.append(f"member => PJSIP/{member}\n")
        blocks.append("\n")
    return "".join(blocks)


def render_queues_dialplan(queues: list[dict]) -> str:
    blocks = ["; This file is generated by OmniPBX.\n", "[from-internal-queues]\n"]
    if not queues:
        blocks.append("exten => _X.,1,Hangup()\n")
        return "".join(blocks)
    for queue in queues:
        queue_app = _queue_application(queue)
        blocks.append(f"exten => {queue['extension']},1,NoOp(Queue {queue['name']})\n")
        blocks.append(" same => n,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n")
        blocks.append(f" same => n,Set(CDR(queue_name)={queue['name']})\n")
        blocks.append(f" same => n,Set(CDR(callee_extension)={queue['extension']})\n")
        blocks.append(f" same => n,{queue_app}\n")
        blocks.append(" same => n,Hangup()\n\n")
    return "".join(blocks)


def render_ivrs_config(ivrs: list[dict], queues: list[dict]) -> str:
    queues_by_extension = {queue["extension"]: queue for queue in queues}
    blocks = ["; This file is generated by OmniPBX.\n", "[from-internal-ivrs]\n"]
    if not ivrs:
        blocks.append("exten => _X.,1,Hangup()\n")
        return "".join(blocks)
    for ivr in ivrs:
        blocks.append(f"exten => {ivr['extension']},1,Goto({_ivr_context(ivr['extension'])},s,1)\n")
    blocks.append("\n")

    for ivr in ivrs:
        prompt = normalize_sound_name(ivr["prompt"]) or "demo-congrats"
        blocks.append(f"[{_ivr_context(ivr['extension'])}]\n")
        blocks.append(f"exten => s,1,NoOp(IVR {ivr['name']})\n")
        blocks.append(" same => n,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n")
        blocks.append(f" same => n,Set(CDR(ivr_name)={ivr['name']})\n")
        blocks.append(f" same => n,Set(IVR_RETRIES={int(ivr['invalid_retries'])})\n")
        blocks.append(f" same => n(replay),Background({prompt})\n")
        blocks.append(f" same => n,WaitExten({int(ivr['timeout'])})\n")
        blocks.append(" same => n,Hangup()\n")
        blocks.append("exten => t,1,Set(IVR_RETRIES=$[${IVR_RETRIES}-1])\n")
        blocks.append(" same => n,GotoIf($[${IVR_RETRIES} >= 0]?s,replay)\n")
        blocks.append(" same => n,Playback(vm-goodbye)\n")
        blocks.append(" same => n,Hangup()\n")
        blocks.append("exten => i,1,Playback(pbx-invalid)\n")
        blocks.append(" same => n,Goto(t,1)\n")
        for option in ivr.get("options", []):
            blocks.append(f"exten => {option['digit']},1,NoOp(IVR selection {option['digit']})\n")
            blocks.extend(f"{line}\n" for line in _render_destination_same_lines(option["destination_type"], option["destination_value"], queues_by_extension))
        blocks.append("\n")
    return "".join(blocks)


def render_musiconhold_config(queues: list[dict]) -> str:
    settings = get_settings()
    blocks = ["; This file is generated by OmniPBX.\n"]
    for queue in queues:
        musicclass = (queue.get("musicclass") or "").strip()
        moh_file_name = (queue.get("moh_file_name") or "").strip()
        if not musicclass or musicclass == "default" or not moh_file_name:
            continue
        target_dir = Path(settings.moh_root_dir) / musicclass
        blocks.append(f"[{musicclass}]\n")
        blocks.append("mode=files\n")
        blocks.append(f"directory={target_dir}\n\n")
    return "".join(blocks)


def render_voicemail_config(extensions: list[dict], call_routing_rules: list[dict] | None = None) -> str:
    mailboxes: dict[str, str] = {}
    for extension in extensions:
        mailbox = str(extension["extension"]).strip()
        display_name = str(extension.get("display_name") or mailbox).strip()
        if mailbox:
            mailboxes[mailbox] = display_name
    for rule in _rules_for(call_routing_rules or [], "incoming-calls", "voicemail"):
        mailbox = _rule_config(rule).get("mailbox", "").strip()
        if mailbox:
            mailboxes.setdefault(mailbox, mailbox)

    blocks = [
        "; This file is generated by OmniPBX.\n",
        "[general]\n",
        "format=wav\n",
        "attach=no\n",
        "maxmsg=100\n",
        "maxsecs=180\n",
        "minsecs=2\n",
        "saycid=yes\n",
        "\n[default]\n",
    ]
    for mailbox, display_name in sorted(mailboxes.items()):
        pin = mailbox[-4:] if len(mailbox) >= 4 else mailbox
        blocks.append(f"{mailbox} => {pin},{display_name}\n")
    return "".join(blocks)


def render_inbound_routes_config(
    routes: list[dict],
    *,
    queues: list[dict],
    ivrs: list[dict],
    ring_groups: list[dict],
    working_hours: list[dict],
    welcome_messages: list[dict],
    call_routing_rules: list[dict] | None = None,
    extensions: list[dict] | None = None,
    advanced_security_rules: list[dict] | None = None,
) -> str:
    blocks = ["; This file is generated by OmniPBX.\n"]
    routes_by_trunk: dict[str, list[dict]] = {}
    queues_by_extension = {queue["extension"]: queue for queue in queues}
    working_hours_by_route = {row["inbound_route_name"]: row for row in working_hours}
    welcome_by_route = {row["inbound_route_name"]: row for row in welcome_messages}
    routing_rules = call_routing_rules or []
    blocked_rules = _rules_for(routing_rules, "incoming-calls", "blocked-numbers")
    blocked_rules = [*blocked_rules, *_advanced_number_block_rules(advanced_security_rules or [])]
    holiday_rules = _rules_for(routing_rules, "incoming-calls", "holiday-rules")
    voicemail_rules = _rules_for(routing_rules, "incoming-calls", "voicemail")
    failover_rules = _rules_for(routing_rules, "incoming-calls", "failover")
    recording_extensions = _recording_extensions(extensions or [])

    for route in routes:
        routes_by_trunk.setdefault(route["trunk_name"], []).append(route)

    for trunk_name, trunk_routes in sorted(routes_by_trunk.items()):
        blocks.append(f"[{_trunk_context(trunk_name)}]\n")
        did_routes = [route for route in trunk_routes if route.get("did_pattern")]
        default_routes = [route for route in trunk_routes if not route.get("did_pattern")]

        for route in did_routes:
            blocks.append(f"exten => {route['did_pattern']},1,NoOp(Inbound trunk {trunk_name})\n")
            blocks.append(" same => n,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n")
            blocks.append(" same => n,Set(CDR(direction)=inbound)\n")
            blocks.append(f" same => n,Set(CDR(trunk_name)={trunk_name})\n")
            blocks.append(f" same => n,Goto({_route_context(route['name'])},s,1)\n")
        if default_routes:
            default_route = sorted(default_routes, key=lambda item: item["name"])[0]
            blocks.append("exten => s,1,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n")
            blocks.append(" same => n,Set(CDR(direction)=inbound)\n")
            blocks.append(f" same => n,Set(CDR(trunk_name)={trunk_name})\n")
            blocks.append(f" same => n,Goto({_route_context(default_route['name'])},s,1)\n")
            blocks.append("exten => _X.,1,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n")
            blocks.append(" same => n,Set(CDR(direction)=inbound)\n")
            blocks.append(f" same => n,Set(CDR(trunk_name)={trunk_name})\n")
            blocks.append(f" same => n,Goto({_route_context(default_route['name'])},s,1)\n")
        elif did_routes:
            fallback_route = sorted(did_routes, key=lambda item: item["name"])[0]
            blocks.append("exten => s,1,Set(CDR(omni_linkedid)=${CHANNEL(linkedid)})\n")
            blocks.append(" same => n,Set(CDR(direction)=inbound)\n")
            blocks.append(f" same => n,Set(CDR(trunk_name)={trunk_name})\n")
            blocks.append(f" same => n,Goto({_route_context(fallback_route['name'])},s,1)\n")
        else:
            blocks.append("exten => s,1,Playback(ss-noservice)\n")
            blocks.append(" same => n,Hangup()\n")
        blocks.append("exten => i,1,Hangup()\n\n")

    for route in routes:
        route_ctx = _route_context(route["name"])
        schedule = working_hours_by_route.get(route["name"])
        welcome = welcome_by_route.get(route["name"])
        blocks.append(f"[{route_ctx}]\n")
        blocks.append(f"exten => s,1,NoOp(Inbound route {route['name']})\n")
        blocks.append(f" same => n,Set(CDR(route_name)={route['name']})\n")
        blocks.extend(_render_blocked_number_checks(blocked_rules))
        for holiday in holiday_rules:
            config = _rule_config(holiday)
            if config.get("route") and config["route"] != route["name"]:
                continue
            time_rule = _holiday_time_rule(config.get("date_range", ""))
            if time_rule:
                blocks.append(f" same => n,GotoIfTime({time_rule}?{_holiday_label(holiday)},1)\n")
        if schedule:
            days = f"{DAY_CODE_MAP[schedule['start_day']]}-{DAY_CODE_MAP[schedule['end_day']]}"
            blocks.append(
                f" same => n,GotoIfTime({schedule['start_time']}-{schedule['end_time']},{days},*,*?open-hours,1)\n"
            )
            blocks.append(" same => n,Goto(after-hours,1)\n")
            blocks.append("exten => open-hours,1,NoOp(Inside configured office hours)\n")
            if welcome:
                welcome_prompt = normalize_sound_name(welcome["sound_name"])
                if welcome_prompt:
                    blocks.append(f" same => n,Playback({welcome_prompt})\n")
            blocks.extend(
                f"{line}\n"
                for line in _render_destination_same_lines(
                    route["destination_type"],
                    route["destination_value"],
                    queues_by_extension,
                )
            )
            blocks.append("exten => after-hours,1,NoOp(Outside configured office hours)\n")
            after_hours_prompt = normalize_sound_name(schedule["after_hours_sound"])
            if after_hours_prompt:
                blocks.append(f" same => n,Playback({after_hours_prompt})\n")
            else:
                blocks.append(" same => n,Playback(ss-noservice)\n")
            blocks.append(" same => n,Hangup()\n\n")
            blocks.extend(_render_route_special_extensions(route["name"], holiday_rules, blocked_rules))
            continue

        if welcome:
            welcome_prompt = normalize_sound_name(welcome["sound_name"])
            if welcome_prompt:
                blocks.append(f" same => n,Playback({welcome_prompt})\n")
        route_voicemail = _route_voicemail_rule(voicemail_rules, route["name"])
        if route_voicemail:
            mailbox = _rule_config(route_voicemail).get("mailbox")
            if route["destination_type"] == "extension":
                blocks.append(f" same => n,Set(CDR(callee_extension)={route['destination_value']})\n")
                blocks.append(_render_recording_lines(recording_extensions, target=route["destination_value"], target_variable="CALLERID(num)"))
                blocks.append(f" same => n,Dial(PJSIP/{route['destination_value']},20)\n")
                blocks.append(" same => n,GotoIf($[\"${DIALSTATUS}\" = \"ANSWER\"]?done)\n")
                blocks.append(f" same => n,VoiceMail({mailbox}@default,u)\n")
                blocks.append(" same => n(done),Hangup()\n\n")
                blocks.extend(_render_route_special_extensions(route["name"], holiday_rules, blocked_rules))
                continue
            if route["destination_type"] == "queue":
                blocks.extend(
                    f"{line}\n"
                    for line in _render_destination_same_lines(
                        route["destination_type"],
                        route["destination_value"],
                        queues_by_extension,
                        hangup=False,
                    )
                )
                blocks.append(f" same => n,VoiceMail({mailbox}@default,u)\n")
                blocks.append(" same => n,Hangup()\n\n")
                blocks.extend(_render_route_special_extensions(route["name"], holiday_rules, blocked_rules))
                continue
            blocks.append(f" same => n,VoiceMail({mailbox}@default,u)\n")
            blocks.append(" same => n,Hangup()\n\n")
            continue
        route_failover = _route_failover_rule(failover_rules, route["name"])
        if route_failover and route["destination_type"] == "extension":
            failover_config = _rule_config(route_failover)
            blocks.append(_render_recording_lines(recording_extensions, target=route["destination_value"], target_variable="CALLERID(num)"))
            blocks.append(f" same => n,Dial(PJSIP/{route['destination_value']},20)\n")
            blocks.append(" same => n,GotoIf($[\"${DIALSTATUS}\" = \"ANSWER\"]?done)\n")
            blocks.extend(
                f"{line}\n"
                for line in _render_destination_same_lines(
                    _destination_type_from_label(failover_config.get("backup_type", "")),
                    failover_config.get("backup", ""),
                    queues_by_extension,
                )
            )
            blocks.append(" same => n(done),Hangup()\n")
            blocks.extend(_render_route_special_extensions(route["name"], holiday_rules, blocked_rules))
            blocks.append("\n")
            continue
        blocks.extend(
            f"{line}\n"
            for line in _render_destination_same_lines(
                route["destination_type"],
                route["destination_value"],
                queues_by_extension,
            )
        )
        blocks.extend(_render_route_special_extensions(route["name"], holiday_rules, blocked_rules))
        blocks.append("\n")
    return "".join(blocks)


def _rules_for(rules: list[dict], section_slug: str, item_slug: str) -> list[dict]:
    return [
        rule
        for rule in rules
        if rule.get("section_slug") == section_slug and rule.get("item_slug") == item_slug
    ]


def _rule_config(rule: dict) -> dict[str, str]:
    config = rule.get("config") or rule.get("config_json") or {}
    if isinstance(config, dict):
        return {str(key): str(value) for key, value in config.items()}
    return {}


def _asterisk_prefix_pattern(prefix: str) -> str:
    clean = re.sub(r"[^0-9+*#]", "", prefix)
    if not clean:
        return ""
    return f"_{clean}X."


def _render_blocked_number_checks(rules: list[dict]) -> list[str]:
    lines: list[str] = []
    for rule in rules:
        caller = _rule_config(rule).get("caller")
        if not caller:
            continue
        lines.append(f" same => n,GotoIf($[\"${{CALLERID(num)}}\" = \"{caller}\"]?blocked,1)\n")
    return lines


def _advanced_number_block_rules(rules: list[dict]) -> list[dict]:
    return [
        {"name": row["value"], "config_json": {"caller": row["value"]}}
        for row in rules
        if row.get("rule_type") == "number_block" and row.get("value")
    ]


def _holiday_time_rule(date_range: str) -> str:
    parts = [part.strip() for part in date_range.split(" to ", 1)]
    if len(parts) != 2:
        return ""
    try:
        start = date.fromisoformat(parts[0])
        end = date.fromisoformat(parts[1])
    except ValueError:
        return ""
    if start.month != end.month:
        return ""
    return f"*,*,{start.day}-{end.day},{MONTH_CODE_MAP[start.month]}"


def _route_voicemail_rule(rules: list[dict], route_name: str) -> dict | None:
    for rule in rules:
        config = _rule_config(rule)
        if config.get("route") == route_name and config.get("mailbox"):
            return rule
    return None


def _route_failover_rule(rules: list[dict], route_name: str) -> dict | None:
    for rule in rules:
        config = _rule_config(rule)
        if config.get("route") == route_name and config.get("backup"):
            return rule
    return None


def _destination_type_from_label(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    return {
        "extension": "extension",
        "user": "extension",
        "ring_group": "ring_group",
        "queue": "queue",
        "call_queue": "queue",
        "ivr": "ivr",
        "trunk": "trunk",
    }.get(normalized, normalized)


def _holiday_label(rule: dict) -> str:
    return f"holiday-{re.sub(r'[^A-Za-z0-9_-]+', '-', str(rule['name'])).strip('-') or 'closed'}"


def _render_route_special_extensions(route_name: str, holiday_rules: list[dict], blocked_rules: list[dict]) -> list[str]:
    blocks: list[str] = []
    for holiday in holiday_rules:
        config = _rule_config(holiday)
        if config.get("route") and config["route"] != route_name:
            continue
        prompt = normalize_sound_name(config.get("message"))
        blocks.append(f"exten => {_holiday_label(holiday)},1,NoOp(Holiday rule {holiday['name']})\n")
        if prompt:
            blocks.append(f" same => n,Playback({prompt})\n")
        else:
            blocks.append(" same => n,Playback(ss-noservice)\n")
        blocks.append(" same => n,Hangup()\n")
    if blocked_rules:
        blocks.append("exten => blocked,1,NoOp(Blocked caller)\n")
        blocks.append(" same => n,Playback(ss-noservice)\n")
        blocks.append(" same => n,Hangup()\n")
    return blocks
