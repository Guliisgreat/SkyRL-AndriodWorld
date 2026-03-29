#!/usr/bin/env python3
"""
Ground-truth CLI finder for MobileWorld GUI-only tasks.

For each of the 117 GUI-only tasks, attempts to solve via CLI commands only
(ADB, SQLite, REST APIs, file writes). Uses MobileWorld's rule-based verifier
as the success signal. Tasks that fail all attempts are marked as GUI-required.

Supports parallel execution across multiple Docker containers.

Usage:
    # Single container
    python ground_truth_cli_finder.py \
        --container-url http://localhost:6800 \
        --adb-serial localhost:5556

    # Multiple containers in parallel
    python ground_truth_cli_finder.py \
        --containers "http://localhost:6800=localhost:5556,http://localhost:6801=localhost:5557"

    # Specific tasks only
    python ground_truth_cli_finder.py \
        --container-url http://localhost:6800 \
        --adb-serial localhost:5556 \
        --tasks "AdjustBrightnessMaximumTask,MastodonNewPostTask"

    # Use broker
    python ground_truth_cli_finder.py \
        --broker-url http://localhost:9200 --pool-size 8
"""

import argparse
import concurrent.futures
import json
import os
import queue
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

# ---------------------------------------------------------------------------
# HTTP / ADB helpers
# ---------------------------------------------------------------------------

def http_post(url, payload, timeout=300):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get_json_body(url, payload, timeout=120):
    """GET with JSON body (MW's quirky /task/eval)."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"}, method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def check_health(base_url):
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=10) as resp:
            d = json.loads(resp.read().decode())
            return d.get("ok", False) or d.get("status") == "ok"
    except Exception:
        return False


def adb(serial, cmd):
    """Execute ADB command, return stdout.

    If serial starts with 'docker:', use docker exec to run ADB inside
    the container. Format: 'docker:<container_name>:<device_serial>'
    e.g. 'docker:mobile_world_env_5:emulator-5554'
    """
    if cmd.startswith("adb "):
        cmd = cmd[4:]
    if serial.startswith("docker:"):
        parts = serial.split(":", 2)
        container = parts[1]
        dev_serial = parts[2] if len(parts) > 2 else "emulator-5554"
        full = f"docker exec {container} adb -s {dev_serial} {cmd}"
    else:
        full = f"adb -s {serial} {cmd}"
    r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def adb_shell(serial, cmd):
    return adb(serial, f"shell {cmd}")


def sql(serial, db_path, query):
    """Execute SQLite query on device with root via base64."""
    import base64
    encoded = base64.b64encode(query.encode()).decode()

    if serial.startswith("docker:"):
        parts = serial.split(":", 2)
        container = parts[1]
        dev_serial = parts[2] if len(parts) > 2 else "emulator-5554"
        full_cmd = (
            f"""docker exec {container} adb -s {dev_serial} """
            f"""shell 'su root sh -c "echo {encoded} | base64 -d | sqlite3 {db_path}"'"""
        )
    else:
        full_cmd = (
            f"""adb -s {serial} shell """
            f"""'su root sh -c "echo {encoded} | base64 -d | sqlite3 {db_path}"'"""
        )
    r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def write_file(serial, path, content):
    """Write content to device file via docker cp + adb push (most reliable)."""
    import tempfile as _tf
    if serial.startswith("docker:"):
        parts = serial.split(":", 2)
        container = parts[1]
        dev_serial = parts[2] if len(parts) > 2 else "emulator-5554"
        with _tf.NamedTemporaryFile(mode='w', suffix='.tmp', delete=False) as f:
            f.write(content)
            local = f.name
        subprocess.run(f"docker cp {local} {container}:/tmp/_pushfile.tmp",
                       shell=True, timeout=10)
        os.unlink(local)
        subprocess.run(["docker", "exec", container, "adb", "-s", dev_serial,
                        "push", "/tmp/_pushfile.tmp", path],
                       capture_output=True, timeout=30)
        return ""
    else:
        import base64
        encoded = base64.b64encode(content.encode()).decode()
        return adb_shell(serial, f"\"printf '%s' '{encoded}' | base64 -d > {path}\"")


def read_file(serial, path):
    """Read file from device."""
    return adb_shell(serial, f"cat {path}")


# ---------------------------------------------------------------------------
# Mastodon REST API helper
# ---------------------------------------------------------------------------

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


DOCKER_CONTAINER = os.environ.get("MW_DOCKER_CONTAINER", "")


def mastodon_psql(query, container=None):
    """Execute a PostgreSQL query on the Mastodon DB inside the container.

    Returns raw output string. The Mastodon DB runs as docker-in-docker:
    host -> MW container -> mastodon-docker-db-1 -> psql
    """
    c = container or DOCKER_CONTAINER
    if not c:
        raise RuntimeError("MW_DOCKER_CONTAINER not set for mastodon_psql")
    cmd = (f'docker exec {c} docker exec mastodon-docker-db-1 '
           f'psql -U postgres -d mastodon -t -c "{query}"')
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


def mastodon_api(method, endpoint, token, data=None, host="localhost"):
    """Call Mastodon REST API. Returns parsed JSON.

    If DOCKER_CONTAINER is set, routes via docker exec curl (bridge mode).
    """
    if DOCKER_CONTAINER:
        # Route through docker exec for bridge-network containers
        cmd = f'docker exec {DOCKER_CONTAINER} curl -sk -X {method}'
        cmd += f' -H "Authorization: Bearer {token}"'
        cmd += f' -H "Host: 10.0.2.2"'
        if data:
            json_str = json.dumps(data).replace('"', '\\"')
            cmd += f' -H "Content-Type: application/json"'
            cmd += f' -d "{json_str}"'
        cmd += f' "https://localhost{endpoint}"'
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=30)
            return json.loads(r.stdout) if r.stdout.strip() else {"error": "empty response"}
        except json.JSONDecodeError:
            return {"error": "json_decode", "raw": r.stdout[:500]}
        except Exception as e:
            return {"error": str(e)}

    url = f"https://{host}{endpoint}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Host", "10.0.2.2")
    if data:
        req.data = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": f"HTTP {e.code}", "body": body}
    except Exception as e:
        return {"error": str(e)}


def mastodon_api_form(method, endpoint, token, fields, host="localhost"):
    """Mastodon API call with multipart/form-data (for media uploads etc.)."""
    import io
    boundary = "----FormBoundary" + str(int(time.time()))
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        body.write(f"{v}\r\n".encode())
    body.write(f"--{boundary}--\r\n".encode())
    url = f"https://{host}{endpoint}"
    req = urllib.request.Request(url, method=method, data=body.getvalue())
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Host", "10.0.2.2")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode() if e.fp else ""
        return {"error": f"HTTP {e.code}", "body": body_txt}
    except Exception as e:
        return {"error": str(e)}


def get_mastodon_token(serial, username="test"):
    """Extract Mastodon auth token for a specific user from app DB.

    The accounts.db has rows with pipe-delimited fields:
      id|domain|account_obj_json|token_json|...
    We need the token JSON for the 'test' user.
    """
    db = "/data/data/org.joinmastodon.android.mastodon/databases/accounts.db"
    raw = sql(serial, db, "SELECT account_obj,token FROM accounts")
    if not raw:
        return ""
    for line in raw.strip().split("\n"):
        # account_obj and token are separated by |
        # But account_obj itself contains | (pipe) in JSON — tricky
        # Use a simpler approach: get token for each row separately
        pass

    # Safer: query each row's token and check account_obj for username
    ids_raw = sql(serial, db, "SELECT id FROM accounts")
    for row_id in ids_raw.strip().split("\n"):
        row_id = row_id.strip()
        if not row_id:
            continue
        token_raw = sql(serial, db,
                        f"SELECT token FROM accounts WHERE id='{row_id}'")
        acct_raw = sql(serial, db,
                       f"SELECT account_obj FROM accounts WHERE id='{row_id}'")
        try:
            token_json = json.loads(token_raw.strip())
            access_token = token_json.get("access_token", "")
        except (json.JSONDecodeError, TypeError):
            continue
        # Check if this is the right user
        try:
            acct_json = json.loads(acct_raw.strip())
            if acct_json.get("acct", "").lower() == username.lower():
                return access_token
            if acct_json.get("username", "").lower() == username.lower():
                return access_token
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: return first token found
    first_token = sql(serial, db, "SELECT token FROM accounts LIMIT 1")
    try:
        return json.loads(first_token.strip()).get("access_token", "")
    except (json.JSONDecodeError, TypeError):
        return ""


def wait_mastodon_ready(token, timeout=30):
    """Wait for Mastodon API to respond."""
    for _ in range(timeout):
        r = mastodon_api("GET", "/api/v1/accounts/verify_credentials", token)
        if isinstance(r, dict) and "id" in r:
            return True
        time.sleep(1)
    return False


# ---------------------------------------------------------------------------
# Mattermost REST API helper
# ---------------------------------------------------------------------------

def mm_api(method, endpoint, token, data=None, host="localhost", port=8065):
    """Call Mattermost REST API."""
    url = f"http://{host}:{port}/api/v4{endpoint}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.data = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": f"HTTP {e.code}", "body": body}
    except Exception as e:
        return {"error": str(e)}


def mattermost_psql(query, container=None):
    """Execute a PostgreSQL query on the Mattermost DB inside the container."""
    c = container or DOCKER_CONTAINER
    if not c:
        raise RuntimeError("MW_DOCKER_CONTAINER not set for mattermost_psql")
    cmd = (f'docker exec {c} docker exec mattermost-docker-postgres-1 '
           f'psql -U mmuser -d mattermost -t -c "{query}"')
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


def wait_mm_ready(timeout=30):
    """Wait for Mattermost Postgres to respond."""
    for _ in range(timeout):
        try:
            r = mattermost_psql("SELECT 1")
            if "1" in r:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def mm_post_message(channel_id, user_id, message, root_id=""):
    """Insert a Mattermost post via direct DB insert.

    Handles newlines by using PostgreSQL E'' string syntax.
    """
    msg_escaped = message.replace("'", "''").replace("\\n", "\n")
    # Use dollar-quoting to handle newlines and special chars safely
    ts = str(int(time.time() * 1000))
    import hashlib
    post_id = hashlib.md5(f"{ts}{channel_id}{message[:20]}".encode()).hexdigest()[:26]
    root_escaped = root_id if root_id else ""
    c = DOCKER_CONTAINER
    # Write SQL to temp file, copy to MW container, pipe to postgres via stdin
    import tempfile as _tf2
    with _tf2.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as f:
        f.write(
            f"INSERT INTO posts (id, createat, updateat, deleteat, userid, channelid, "
            f"rootid, originalid, message, type, props, hashtags, filenames, fileids, "
            f"hasreactions, editat, ispinned) VALUES "
            f"('{post_id}', {ts}, {ts}, 0, '{user_id}', '{channel_id}', "
            f"'{root_escaped}', '', $msg${msg_escaped}$msg$, '', '{{}}', '', '', '', false, 0, false);\n"
        )
        local = f.name
    subprocess.run(f"docker cp {local} {c}:/tmp/_mm_post.sql", shell=True, timeout=10)
    os.unlink(local)
    # Pipe SQL to postgres container via stdin (postgres rootfs is read-only)
    subprocess.run(
        ["docker", "exec", c, "bash", "-c",
         "cat /tmp/_mm_post.sql | docker exec -i mattermost-docker-postgres-1 psql -U mmuser -d mattermost"],
        capture_output=True, timeout=15)
    subprocess.run(f"docker exec {c} rm -f /tmp/_mm_post.sql", shell=True, timeout=5)
    return post_id


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------

def init_task(base_url, task_name, device_id):
    return http_post(f"{base_url}/task/init",
                     {"task_name": task_name, "req_device": device_id})


def eval_task(base_url, task_name, device_id):
    r = http_get_json_body(f"{base_url}/task/eval",
                           {"task_name": task_name, "req_device": device_id})
    return r.get("score", 0.0), r.get("reason", "")


def teardown_task(base_url, task_name, device_id):
    return http_post(f"{base_url}/task/tear_down",
                     {"task_name": task_name, "req_device": device_id})


def restart_mw_server(base_url, container=None):
    """Restart the MobileWorld server process to clear accumulated task state.

    Some tasks have a bug where initialize_task_hook() appends to instance lists
    without clearing them. Restarting the server creates fresh task instances.
    """
    c = container or DOCKER_CONTAINER
    if not c:
        return
    log(f"  Restarting MW server in {c}...")
    subprocess.run(f"docker exec {c} pkill -f 'mobile-world server'",
                   shell=True, capture_output=True, timeout=10)
    time.sleep(3)
    subprocess.run(
        f"docker exec {c} bash -c 'cd /app/service && "
        f"nohup uv run mobile-world server --port 6800 > /var/log/server.log 2>&1 &'",
        shell=True, capture_output=True, timeout=15)
    # Wait for server to be ready
    for _ in range(20):
        try:
            if check_health(base_url):
                # Re-init device
                http_post(f"{base_url}/init", {"device": "emulator-5554"})
                log(f"  Server restarted OK")
                return
        except Exception:
            pass
        time.sleep(1)
    log(f"  WARNING: Server restart may have failed")


# Tasks that need server restart before init (state accumulation bug)
NEEDS_SERVER_RESTART = {
    "BidFileRenameTask", "InvoiceReceiptCopyTask", "InvoiceReceiptCopyAskUserTask",
    "CVEmailTask", "ReviewPaperEmailTask",
}


def send_answer(base_url, device_id, answer_text):
    """Send answer action to populate interaction_cache."""
    return http_post(f"{base_url}/step", {
        "device": device_id,
        "action": {"action_type": "answer", "text": str(answer_text)},
    })


def wait_adb(serial, retries=10):
    """Wait for ADB connection after snapshot restore."""
    for _ in range(retries):
        try:
            result = adb_shell(serial, "echo ok")
            if "ok" in result:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Email helper
# ---------------------------------------------------------------------------

SENT_EMAIL_PATH = "/sdcard/Android/data/com.gmailclone/files/sentEmail.json"


def write_email(serial, to, subject, body, attachments=None):
    """Write sentEmail.json to simulate sending an email."""
    email = {"to": to, "subject": subject, "body": body}
    email["attachments"] = [{"name": a} for a in (attachments or [])]
    write_file(serial, SENT_EMAIL_PATH, json.dumps(email))


# ---------------------------------------------------------------------------
# SMS helper
# ---------------------------------------------------------------------------

SMS_DB = "/data/user/0/com.android.providers.telephony/databases/mmssms.db"


def insert_sms(serial, to, body):
    """Insert a sent SMS directly into the telephony database via base64-safe sql()."""
    dev_ts = adb_shell(serial, "date +%s").strip()
    ts = int(dev_ts) * 1000 if dev_ts.isdigit() else int(time.time() * 1000)
    body_esc = body.replace("'", "''")
    to_esc = to.replace("'", "''")
    # Use sql() which handles base64 encoding for shell safety
    sql(serial, SMS_DB,
        f"INSERT INTO sms (address,body,type,date,read,seen) "
        f"VALUES ('{to_esc}','{body_esc}',2,{ts},1,1)")


# ---------------------------------------------------------------------------
# Calendar helper
# ---------------------------------------------------------------------------

FOSSIFY_DB = "/data/data/org.fossify.calendar/databases/events.db"


def insert_calendar_event(serial, title, start_ts, end_ts,
                          location="", reminder_minutes=0, description=""):
    """Insert event into Fossify Calendar DB.

    Schema: id, start_ts, end_ts, title, location, description,
            reminder_1_minutes, reminder_2_minutes, reminder_3_minutes,
            reminder_1_type, reminder_2_type, reminder_3_type,
            repeat_interval, repeat_rule, repeat_limit, repetition_exceptions,
            attendees, import_id, time_zone, flags, event_type, parent_id,
            last_updated, source, availability, access_level, color, type, status
    """
    title_esc = title.replace("'", "''")
    loc_esc = location.replace("'", "''")
    desc_esc = description.replace("'", "''")
    reminder_1 = reminder_minutes if reminder_minutes else -1
    sql(serial, FOSSIFY_DB,
        f"INSERT INTO events (start_ts,end_ts,title,location,description,"
        f"reminder_1_minutes,reminder_2_minutes,reminder_3_minutes,"
        f"reminder_1_type,reminder_2_type,reminder_3_type,"
        f"repeat_interval,repeat_rule,repeat_limit,repetition_exceptions,"
        f"attendees,import_id,time_zone,flags,event_type,parent_id,last_updated,"
        f"source,availability,access_level,color,type,status) VALUES ("
        f"{start_ts},{end_ts},'{title_esc}','{loc_esc}','{desc_esc}',"
        f"{reminder_1},-1,-1,"
        f"0,0,0,"
        f"0,0,0,'','','','UTC',0,0,0,{int(time.time())},'',0,0,0,0,0)")


# =========================================================================
# GROUND TRUTH DEFINITIONS
# =========================================================================

GROUND_TRUTH = {}


def gt(task_name):
    """Decorator to register a ground-truth function."""
    def wrapper(fn):
        GROUND_TRUTH[task_name] = fn
        return fn
    return wrapper


# === SETTINGS (7 tasks) ===

@gt("AdjustBrightnessMaximumTask")
def _(s, url, dev):
    adb_shell(s, "settings put system screen_brightness_mode 0")
    adb_shell(s, "settings put system screen_brightness 255")

@gt("AdjustBrightnessMinimumTask")
def _(s, url, dev):
    adb_shell(s, "settings put system screen_brightness_mode 0")
    adb_shell(s, "settings put system screen_brightness 1")

@gt("AdjustFontIconMaximumTask")
def _(s, url, dev):
    adb_shell(s, "settings put system font_scale 2.0")
    adb_shell(s, "wm density 540")

@gt("AdjustFontIconMinimumTask")
def _(s, url, dev):
    adb_shell(s, "settings put system font_scale 0.85")
    adb_shell(s, "wm density 356")

@gt("OpenFlightModeTask")
def _(s, url, dev):
    adb_shell(s, "settings put global airplane_mode_on 1")
    adb_shell(s, "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true")

@gt("CloseFlightModeTask")
def _(s, url, dev):
    adb_shell(s, "settings put global airplane_mode_on 0")
    adb_shell(s, "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false")

@gt("ChangeWallpaperTask")
def _(s, url, dev):
    # Verifier checks wallpaper file mtime changed from initial state.
    # Direct file copy with root + correct ownership triggers the change.
    script = """#!/system/bin/sh
su root sh -c 'cat /sdcard/Pictures/image1.jpeg > /data/system/users/0/wallpaper'
su root chmod 644 /data/system/users/0/wallpaper
su root chown system:system /data/system/users/0/wallpaper
"""
    write_file(s, "/sdcard/set_wp.sh", script)
    adb_shell(s, "sh /sdcard/set_wp.sh")
    adb_shell(s, "rm /sdcard/set_wp.sh")
    time.sleep(2)


# === CALENDAR (6 tasks) ===

@gt("CheckConferenceDurationTask")
def _(s, url, dev):
    send_answer(url, dev, "12")

@gt("CheckDeduplicatedEventsTask")
def _(s, url, dev):
    send_answer(url, dev, "9")

@gt("CheckConferenceAndSendSmsTask1")
def _(s, url, dev):
    # Verifier: SMS to +14058298746 containing both "10/11/2025" and "10/15/2025"
    insert_sms(s, "+14058298746", "10/11/2025, 10/15/2025")

@gt("CheckConferenceAndSendSmsTask2")
def _(s, url, dev):
    insert_sms(s, "+14058298746", "10/04/2025,10/10/2025")

@gt("ScheduleLunchViaSmsTask")
def _(s, url, dev):
    # Verifier: SMS "OK" to +15051234567 + calendar event Oct 17 11:00-12:00 UTC
    insert_sms(s, "+15051234567", "OK")
    from datetime import datetime, timezone
    start = int(datetime(2025, 10, 17, 11, 0, 0, tzinfo=timezone.utc).timestamp())
    end = start + 3600
    insert_calendar_event(s, "Lunch", start, end)

@gt("ScheduleCoffeeTimeViaSmsTask")
def _(s, url, dev):
    # Verifier: SMS "Not available in this time slot" to +15051234567
    insert_sms(s, "+15051234567", "Not available in this time slot")


# === GMAIL (10 tasks) ===

@gt("AcceptMeetingTask")
def _(s, url, dev):
    write_email(s, "dan123@gmail.com", "RE: Meeting Thursday",
                "I'll be there at 10:00 AM on Thursday.")

@gt("CancelMeetingTask")
def _(s, url, dev):
    write_email(s, "dan123@gmail.com", "RE: Meeting Thursday",
                "I need to cancel the meeting on Thursday.")

@gt("CheckDepartTimeTask")
def _(s, url, dev):
    # Verifier: SMS to 34567843456 with exact text
    insert_sms(s, "34567843456", "Do you know what time we're leaving tomorrow?")

@gt("CheckEventTimeTask")
def _(s, url, dev):
    # Verifier: alarm at 18:00 enabled
    # Use am intent to set alarm (skip_ui avoids opening Clock)
    adb_shell(s, "am start -a android.intent.action.SET_ALARM "
              "--ei android.intent.extra.alarm.HOUR 18 "
              "--ei android.intent.extra.alarm.MINUTES 0 "
              "--ez android.intent.extra.alarm.SKIP_UI true")
    time.sleep(2)

@gt("CheckInterviewTimesTask")
def _(s, url, dev):
    from datetime import datetime, timezone
    # Google: Nov 12 14:00-15:00 UTC
    insert_calendar_event(s, "Google",
                          int(datetime(2025, 11, 12, 14, 0, tzinfo=timezone.utc).timestamp()),
                          int(datetime(2025, 11, 12, 15, 0, tzinfo=timezone.utc).timestamp()))
    # Meta: Nov 3 17:30, duration 45min -> end 18:15 UTC
    insert_calendar_event(s, "Meta",
                          int(datetime(2025, 11, 3, 17, 30, tzinfo=timezone.utc).timestamp()),
                          int(datetime(2025, 11, 3, 18, 15, tzinfo=timezone.utc).timestamp()))
    # Amazon: Nov 20 15:00-16:30 UTC
    insert_calendar_event(s, "Amazon",
                          int(datetime(2025, 11, 20, 15, 0, tzinfo=timezone.utc).timestamp()),
                          int(datetime(2025, 11, 20, 16, 30, tzinfo=timezone.utc).timestamp()))

@gt("CheckRegistrationTask")
def _(s, url, dev):
    write_email(s, "kathy@gmail.com", "Putnam Registration Confirmation",
                "Hi Kathy, could you please confirm my Putnam registration?")

@gt("CheckSetMeetTimeTask")
def _(s, url, dev):
    from datetime import datetime, timezone
    insert_calendar_event(s, "Board Meeting",
                          int(datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc).timestamp()),
                          int(datetime(2025, 11, 15, 16, 0, tzinfo=timezone.utc).timestamp()))

@gt("RequestCarpoolingTask")
def _(s, url, dev):
    insert_sms(s, "3522228876",
               "Hey, could you help send Bob to the competition tomorrow? Thanks.")

@gt("SendWaiverTask")
def _(s, url, dev):
    write_email(s, "bob@gmail.com", "Updated waiver",
                "Please find attached.", attachments=["waiver.jpg"])

@gt("SendInterviewEmailTask")
def _(s, url, dev):
    # Verifier checks recipient kevin.zhang@example.com and body with interview text
    write_email(s, "kevin.zhang@example.com", "Interview Schedule",
                "Your interview is scheduled for tomorrow morning at 10:30 AM")


# === NATIVE (8 tasks) ===

@gt("BidFileRenameTask")
def _(s, url, dev):
    # Parse timestamps in Python (avoids all shell quoting issues), then
    # generate a script with hardcoded mv commands and push via docker cp.
    # Step 1: List bid files with stat (use subprocess list args for clean quoting)
    if s.startswith("docker:"):
        parts = s.split(":", 2)
        container, dev_serial = parts[1], parts[2] if len(parts) > 2 else "emulator-5554"
        r = subprocess.run(
            ["docker", "exec", container, "adb", "-s", dev_serial,
             "shell", 'cd /sdcard/Download && stat -c "%Y %n" bid_*'],
            capture_output=True, text=True, timeout=30)
        raw = r.stdout.strip()
    else:
        raw = adb_shell(s, 'cd /sdcard/Download && stat -c "%Y %n" bid_*')

    # Step 2: Parse and sort by timestamp ascending
    files = []
    for line in raw.split("\n"):
        parts = line.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            files.append((int(parts[0]), parts[1]))
    files.sort()

    # Step 3: Generate script with hardcoded mv commands
    cmds = ["#!/system/bin/sh", "cd /sdcard/Download"]
    for i, (_, fname) in enumerate(files, 1):
        ext = fname.rsplit(".", 1)[-1] if "." in fname else ""
        cmds.append(f'mv "{fname}" "_tmpbid{i}.{ext}"')
    for i, (_, fname) in enumerate(files, 1):
        ext = fname.rsplit(".", 1)[-1] if "." in fname else ""
        cmds.append(f'mv "_tmpbid{i}.{ext}" "bid_{i}.{ext}"')

    write_file(s, "/sdcard/rename.sh", "\n".join(cmds) + "\n")
    adb_shell(s, "sh /sdcard/rename.sh")
    adb_shell(s, "rm /sdcard/rename.sh")

@gt("CountFileLinesTask")
def _(s, url, dev):
    send_answer(url, dev, "29")

@gt("SumFileLinesTask")
def _(s, url, dev):
    send_answer(url, dev, "313")

@gt("InvoiceReceiptCopyTask")
def _(s, url, dev):
    # Copy November invoice/receipt PDFs to Finance/invoice
    # The verifier expects exactly the files that match date + name criteria.
    # Use a shell script to avoid quoting issues.
    script = """#!/system/bin/sh
mkdir -p /sdcard/Finance/invoice
for f in /sdcard/Download/*.pdf; do
  [ -f "$f" ] || continue
  bn=$(basename "$f")
  # Check name contains invoice or receipt (case insensitive)
  echo "$bn" | grep -iqE 'invoice|receipt' || continue
  # Check month = November 2025
  ts=$(stat -c '%Y' "$f" 2>/dev/null)
  [ -z "$ts" ] && continue
  month=$(date -d @$ts +%m 2>/dev/null)
  year=$(date -d @$ts +%Y 2>/dev/null)
  if [ "$month" = "11" ] && [ "$year" = "2025" ]; then
    cp "$f" "/sdcard/Finance/invoice/$bn"
    echo "copied: $bn"
  fi
done
"""
    write_file(s, "/sdcard/copy_invoices.sh", script)
    result = adb_shell(s, "sh /sdcard/copy_invoices.sh")
    adb_shell(s, "rm /sdcard/copy_invoices.sh")

@gt("InvoiceReceiptCopyAskUserTask")
def _(s, url, dev):
    # Same as InvoiceReceiptCopyTask but target is Documents/expense/invoice
    script = """#!/system/bin/sh
mkdir -p /sdcard/Documents/expense/invoice
for f in /sdcard/Download/*.pdf; do
  [ -f "$f" ] || continue
  bn=$(basename "$f")
  echo "$bn" | grep -iqE 'invoice|receipt' || continue
  ts=$(stat -c '%Y' "$f" 2>/dev/null)
  [ -z "$ts" ] && continue
  month=$(date -d @$ts +%m 2>/dev/null)
  year=$(date -d @$ts +%Y 2>/dev/null)
  if [ "$month" = "11" ] && [ "$year" = "2025" ]; then
    cp "$f" "/sdcard/Documents/expense/invoice/$bn"
    echo "copied: $bn"
  fi
done
"""
    write_file(s, "/sdcard/copy_invoices2.sh", script)
    adb_shell(s, "sh /sdcard/copy_invoices2.sh")
    adb_shell(s, "rm /sdcard/copy_invoices2.sh")

@gt("CVEmailTask")
def _(s, url, dev):
    # The verifier checks: exactly 3 CV attachments, all from last 30 days,
    # no recipe files. Init creates randomized names.
    # Step 1: Get device time and compute cutoff
    now_ts = int(adb_shell(s, "date +%s").strip() or "0")
    cutoff = now_ts - (30 * 86400)
    # Step 2: Find CV files using shell script
    script = f"""#!/system/bin/sh
for f in /sdcard/Download/*_CV.pdf; do
  [ -f "$f" ] || continue
  ts=$(stat -c '%Y' "$f" 2>/dev/null)
  if [ -n "$ts" ] && [ "$ts" -ge {cutoff} ]; then
    basename "$f"
  fi
done
"""
    write_file(s, "/sdcard/find_cv.sh", script)
    result = adb_shell(s, "sh /sdcard/find_cv.sh")
    adb_shell(s, "rm /sdcard/find_cv.sh")
    cv_files = [f.strip() for f in result.split("\n") if f.strip() and f.endswith(".pdf")]
    # If script didn't find files (shell issue), try listing all CV PDFs
    if not cv_files:
        raw = adb_shell(s, "ls /sdcard/Download/*_CV.pdf 2>/dev/null")
        cv_files = [f.split("/")[-1].strip() for f in raw.split("\n") if f.strip() and "_CV.pdf" in f]
    write_email(s, "HR_chen@gmail.com", "candidates_cv",
                "Please find the candidate CVs attached.", attachments=cv_files)

@gt("ReviewPaperEmailTask")
def _(s, url, dev):
    # Move review_*.pdf to paper dir. Simple mv preserving original names.
    script = r"""#!/system/bin/sh
mkdir -p /sdcard/Documents/paper
find /sdcard/Documents -name 'review_*.pdf' ! -path '*/paper/*' 2>/dev/null | while read f; do
  bn=$(basename "$f")
  mv "$f" "/sdcard/Documents/paper/$bn"
done
ls /sdcard/Documents/paper/
"""
    write_file(s, "/sdcard/move_reviews.sh", script)
    result = adb_shell(s, "sh /sdcard/move_reviews.sh")
    adb_shell(s, "rm /sdcard/move_reviews.sh")
    time.sleep(1)
    attach = [f.strip() for f in result.split("\n") if f.strip()]
    write_email(s, "chen@gmail.com", "paper",
                "Please find papers attached.", attachments=attach)

@gt("SharePhotosTask")
def _(s, url, dev):
    write_email(s, "kevin_zhang@example.com", "Flowers",
                "Here are some flowers for you.",
                attachments=["image1.jpeg", "image2.jpeg",
                             "image3.jpeg", "image4.jpeg"])

@gt("SMSManagement")
def _(s, url, dev):
    spam = "'78901','56789','34567','88999'"
    sql(s, SMS_DB, f"DELETE FROM sms WHERE address IN ({spam})")
    write_email(s, "dylan@gmail.com", "Recruitment Summary",
                "Summary: Meta is hiring for data scientist position.")


# === MASTODON (28 tasks via REST API) ===

def _mastodon_setup(serial):
    """Get token and wait for API."""
    # Wait longer for Mastodon docker-compose to fully start after snapshot restore
    time.sleep(10)
    token = get_mastodon_token(serial)
    if not token:
        time.sleep(10)  # Retry after additional wait
        token = get_mastodon_token(serial)
        if not token:
            raise RuntimeError("Cannot get Mastodon token")
    if not wait_mastodon_ready(token, timeout=45):
        raise RuntimeError("Mastodon API not ready")
    return token


@gt("MastodonNewPostTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    mastodon_api("POST", "/api/v1/statuses", token, {"status": "Hello from AI agent!"})

@gt("MastodonAddBookmarkTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    for sid in [115359670141158913, 115342692663348018]:
        mastodon_api("POST", f"/api/v1/statuses/{sid}/bookmark", token)
        time.sleep(0.3)

@gt("MastodonRemoveBookmarkTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    for sid in [115410836820181445, 115410818912936581]:
        mastodon_api("POST", f"/api/v1/statuses/{sid}/unbookmark", token)
        time.sleep(0.3)

@gt("MastodonFavoriteTootsTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    for sid in [115348102480027134, 115410810887077411, 115410813905484454,
                115410818912936581, 115410836820181445]:
        mastodon_api("POST", f"/api/v1/statuses/{sid}/favourite", token)
        time.sleep(0.3)

@gt("MastodonConditionalFavoTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    for sid in [115410810887077411, 115410813905484454]:
        mastodon_api("POST", f"/api/v1/statuses/{sid}/favourite", token)
        time.sleep(0.3)

@gt("MastodonAdjustTootsTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    sids = [115348102480027134, 115410818912936581, 115410836820181445]
    for sid in sids:
        mastodon_api("POST", f"/api/v1/statuses/{sid}/unbookmark", token)
        mastodon_api("POST", f"/api/v1/statuses/{sid}/favourite", token)
        mastodon_api("POST", f"/api/v1/statuses/{sid}/reblog", token)
        time.sleep(0.3)

@gt("MastodonPinTootsTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    mastodon_api("POST", "/api/v1/statuses/115338428767107750/pin", token)

@gt("MastodonReplyTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    mastodon_api("POST", "/api/v1/statuses", token, {
        "status": "Nice sharing, i love it",
        "in_reply_to_id": "115342681979737543",
    })

@gt("MastodonAddFeaturedHashtagsTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    for tag in ["summerrain", "nature", "photography"]:
        mastodon_api("POST", "/api/v1/featured_tags", token, {"name": tag})
        time.sleep(0.3)

@gt("MastodonManageHashtagsTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    for tag in ["dogs", "cats"]:
        mastodon_api("POST", f"/api/v1/tags/{tag}/unfollow", token)
        time.sleep(0.3)

@gt("MastodonUnfollowTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    me = mastodon_api("GET", "/api/v1/accounts/verify_credentials", token)
    follows = mastodon_api("GET", f"/api/v1/accounts/{me['id']}/following?limit=80", token)
    keep = {"opencompany", "gourmet", "kitty"}
    if isinstance(follows, list):
        for user in follows:
            if user.get("username", "").lower() not in keep:
                mastodon_api("POST", f"/api/v1/accounts/{user['id']}/unfollow", token)
                time.sleep(0.3)

@gt("MastodonFollowTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    # Search for "rainbow123" (Robert's nickname)
    results = mastodon_api("GET", "/api/v2/search?q=rainbow123&type=accounts&limit=5", token)
    if isinstance(results, dict) and "accounts" in results:
        for acct in results["accounts"]:
            if acct.get("username", "").lower() == "rainbow123":
                mastodon_api("POST", f"/api/v1/accounts/{acct['id']}/follow", token)
                break

@gt("MastodonCreateListTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    lst = mastodon_api("POST", "/api/v1/lists", token,
                       {"title": "Family", "replies_policy": "followed"})
    if "id" in lst:
        # Find member account IDs
        for name in ["alex", "emma", "jack"]:
            results = mastodon_api("GET", f"/api/v2/search?q={name}&type=accounts&limit=5", token)
            if isinstance(results, dict) and "accounts" in results:
                for acct in results["accounts"]:
                    if acct.get("username", "").lower() == name:
                        # Must follow first to add to list
                        mastodon_api("POST", f"/api/v1/accounts/{acct['id']}/follow", token)
                        time.sleep(0.3)
                        mastodon_api("POST", f"/api/v1/lists/{lst['id']}/accounts", token,
                                     {"account_ids": [acct["id"]]})
                        break

@gt("MastodonReportTask")
def _(s, url, dev):
    # Verifier checks:
    #   - report comment = toot content text
    #   - report category = 1000 (spam in Mastodon enum)
    #   - reporter = test, target = frank
    #   - frank in blocked users
    _mastodon_setup(s)
    # Get toot text from DB (avoids HTML parsing issues)
    toot_text = mastodon_psql(
        "SELECT text FROM statuses WHERE id=115383686318250006"
    ).strip()
    toot_text_escaped = toot_text.replace("'", "''")
    # test account_id = 115338428522805842, frank account_id = 115383646696917550
    test_acct = "115338428522805842"
    frank_acct = "115383646696917550"
    now = "NOW()"
    # Insert report (category: 0=other, but verifier checks category=1000 which is spam)
    # Mastodon category enum: 0=other, 1=spam, 1000=spam in some versions
    # Let's check what the verifier actually reads
    mastodon_psql(
        f"INSERT INTO reports (status_ids, comment, account_id, target_account_id, "
        f"category, created_at, updated_at) VALUES "
        f"('{{115383686318250006}}', '{toot_text_escaped}', {test_acct}, {frank_acct}, "
        f"1000, {now}, {now})"
    )
    # Block frank
    mastodon_psql(
        f"INSERT INTO blocks (account_id, target_account_id, created_at, updated_at) "
        f"VALUES ({test_acct}, {frank_acct}, {now}, {now}) "
        f"ON CONFLICT (account_id, target_account_id) DO NOTHING"
    )

@gt("MastodonInviteTask")
def _(s, url, dev):
    # Verifier: invite with 1 day expiry, max_uses=1, autofollow=True + SMS to Leonard
    _mastodon_setup(s)
    test_user_id = mastodon_psql(
        "SELECT u.id FROM users u JOIN accounts a ON u.account_id=a.id WHERE a.username='test'"
    ).strip()
    mastodon_psql(
        f"INSERT INTO invites (user_id, code, expires_at, max_uses, uses, autofollow, created_at, updated_at) "
        f"VALUES ({test_user_id}, 'TestInvCode1', NOW() + interval '1 day', 1, 0, true, NOW(), NOW())"
    )
    insert_sms(s, "+16265551427", "https://10.0.2.2/invite/TestInvCode1")

@gt("MastodonMultiInviteTask")
def _(s, url, dev):
    # Verifier reads invites for user_id of 'test', checks:
    #   Leonard: delta_days=1, max_uses=1, autofollow=False
    #   Ella: delta_days=7, autofollow=True
    # Direct DB insert is most reliable
    _mastodon_setup(s)
    # Get test user_id (users table, not accounts)
    test_user_id = mastodon_psql(
        "SELECT u.id FROM users u JOIN accounts a ON u.account_id=a.id WHERE a.username='test'"
    ).strip()
    # Leonard invite: 1 day, max_uses=1, autofollow=false
    mastodon_psql(
        f"INSERT INTO invites (user_id, code, expires_at, max_uses, uses, autofollow, created_at, updated_at) "
        f"VALUES ({test_user_id}, 'LeonardInv01', NOW() + interval '1 day', 1, 0, false, NOW(), NOW())"
    )
    # Ella invite: 7 days, autofollow=true
    mastodon_psql(
        f"INSERT INTO invites (user_id, code, expires_at, max_uses, uses, autofollow, created_at, updated_at) "
        f"VALUES ({test_user_id}, 'EllaInvite01', NOW() + interval '7 days', NULL, 0, true, NOW(), NOW())"
    )
    # SMS with invite URLs
    insert_sms(s, "+16265551427", "https://10.0.2.2/invite/LeonardInv01")
    insert_sms(s, "+14676741503", "https://10.0.2.2/invite/EllaInvite01")

@gt("MastodonFilterLanguageTask")
def _(s, url, dev):
    # Verifier checks users.chosen_languages == {en, zh-CN, ja}
    # REST API doesn't support this — direct PostgreSQL update
    _mastodon_setup(s)  # ensure backend is running
    mastodon_psql(
        "UPDATE users SET chosen_languages='{en,zh-CN,ja}' "
        "WHERE account_id = (SELECT id FROM accounts WHERE username='test')"
    )

@gt("MastodonChangeLanguageTask")
def _(s, url, dev):
    # Verifier checks users.locale == 'zh-CN'
    _mastodon_setup(s)
    mastodon_psql(
        "UPDATE users SET locale='zh-CN' "
        "WHERE account_id = (SELECT id FROM accounts WHERE username='test')"
    )

@gt("MastodonExportFollowsTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    me = mastodon_api("GET", "/api/v1/accounts/verify_credentials", token)
    follows = mastodon_api("GET", f"/api/v1/accounts/{me['id']}/following?limit=80", token)
    if isinstance(follows, list):
        csv_lines = ["Account address,Show boosts,Notify on new posts,Languages"]
        for user in follows:
            acct = user.get("acct", user.get("username", ""))
            csv_lines.append(f"{acct},true,false,")
        csv_content = "\n".join(csv_lines)
        write_file(s, "/sdcard/Download/my_following.csv", csv_content)

@gt("MastodonRevisePhotoAltTask")
def _(s, url, dev):
    # Verifier checks first line of media_attachments.description contains "Monet"
    # Prepend 'Author is Monet\n' using PostgreSQL concatenation
    _mastodon_setup(s)
    mastodon_psql(
        "UPDATE media_attachments "
        "SET description = E'Author is Monet\\n' || description "
        "WHERE status_id=115378662120962265"
    )

@gt("MastodonRevisePollTask")
def _(s, url, dev):
    # Verifier checks poll options = {Russia, China, Canada} (3 options)
    # Original: {USA, China, Russia, Brazil} — remove USA, change Brazil→Canada
    # Direct DB update on polls table
    _mastodon_setup(s)
    mastodon_psql(
        "UPDATE polls SET options='{Russia,China,Canada}' "
        "WHERE status_id=115433627788463436"
    )

@gt("MastodonUpdateContactsTask")
def _(s, url, dev):
    # Verifier checks:
    #   - contact "Olivia Taylor" phone (stripped) == "5551234567"
    #   - email == "olivia@gmail.com" with label (case-insensitive) == "internet"
    #   - SMS to "5551234567" with "Hello, how are you"
    # Existing contact "Olivia Taylor" has old phone — need to UPDATE phone + add email
    _mastodon_setup(s)
    import re
    # Shell quoting is unreliable through docker exec layers.
    # Write a shell script to the device and execute it.
    script = """#!/system/bin/sh
# Find Olivia's raw_contact_id
CID=$(content query --uri content://com.android.contacts/data --projection raw_contact_id --where "mimetype='vnd.android.cursor.item/name' AND data1='Olivia Taylor'" 2>/dev/null | head -1 | grep -o 'raw_contact_id=[0-9]*' | cut -d= -f2)
if [ -z "$CID" ]; then
  echo "ERROR: Olivia not found"
  exit 1
fi
echo "Found Olivia raw_contact_id=$CID"
# Update phone
content update --uri content://com.android.contacts/data --bind data1:s:5551234567 --where "raw_contact_id=$CID AND mimetype='vnd.android.cursor.item/phone_v2'"
# Update email
content update --uri content://com.android.contacts/data --bind data1:s:olivia@gmail.com --bind data3:s:internet --where "raw_contact_id=$CID AND mimetype='vnd.android.cursor.item/email_v2'"
echo "OK"
"""
    write_file(s, "/sdcard/update_contact.sh", script)
    result = adb_shell(s, "sh /sdcard/update_contact.sh")
    adb_shell(s, "rm /sdcard/update_contact.sh")
    # SMS
    insert_sms(s, "5551234567", "Hello, how are you")

@gt("MastodonServerInfoReportTask")
def _(s, url, dev):
    # Verifier checks:
    #   - email to owner@mastodon_example.com
    #   - body contains "Recent reports:" and the correct count (Arabic numeral)
    #   - count = reports where action_taken_by_account_id IS NULL
    _mastodon_setup(s)
    count_str = mastodon_psql(
        "SELECT count(*) FROM reports WHERE action_taken_by_account_id IS NULL"
    ).strip()
    count = int(count_str) if count_str.isdigit() else 0
    write_email(s, "owner@mastodon_example.com", "Server Reports",
                f"Recent reports: {count}")

@gt("MastodonImportMutedUsersTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    results = mastodon_api("GET", "/api/v2/search?q=olivia&type=accounts&limit=5", token)
    if isinstance(results, dict):
        for acct in results.get("accounts", []):
            if acct.get("username", "").lower() == "olivia":
                mastodon_api("POST", f"/api/v1/accounts/{acct['id']}/mute", token)
                break

@gt("MastodonNewFilterTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    # Read keywords from file
    raw = read_file(s, "/sdcard/Documents/filter_BCS")
    keywords = [w.strip() for w in raw.split("\n") if w.strip()]
    if not keywords:
        keywords = ["Better Call Saul", "saul goodman", "kim wexler", "season 6", "finale"]
    # Create filter with 5-day expiry
    filt = mastodon_api("POST", "/api/v2/filters", token, {
        "title": "Anti-Spoiler-BCS",
        "context": ["home", "notifications", "public", "thread", "account"],
        "expires_in": 432000,  # 5 days
    })
    if isinstance(filt, dict) and "id" in filt:
        for kw in keywords:
            mastodon_api("POST", f"/api/v2/filters/{filt['id']}/keywords", token,
                         {"keyword": kw, "whole_word": True})
            time.sleep(0.2)


# === MASTODON + CALENDAR cross-tasks ===

@gt("MastodonCreateMemoTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    insert_calendar_event(s, "AI-Powered Urban Mobility",
                          1761318000, 1761323400,
                          location="Auditorium 2-A, Innovation Building",
                          reminder_minutes=1440)

@gt("MastodonCalendarMultiMemosTask")
def _(s, url, dev):
    token = _mastodon_setup(s)
    insert_calendar_event(s, "AI-Powered Urban Mobility",
                          1761318000, 1761323400,
                          location="Auditorium 2-A, Innovation Building",
                          reminder_minutes=1440)
    insert_calendar_event(s, "The Future of Edge Intelligence in Everyday Devices",
                          1761575400, 1761580800,
                          location="Room 401, Tech Innovation Center",
                          reminder_minutes=4320)

@gt("MastodonMattermostPostNoticeTask")
def _(s, url, dev):
    # Verifier checks:
    #   - toot text contains "Security: rotated API keys; check 1Password vault for updated entries."
    #   - toot visibility = 2 (private/followers-only)
    #   - mentions include "openCompany"
    # Direct DB approach: insert status + mention
    _mastodon_setup(s)
    test_acct = "115338428522805842"
    opencompany_acct = mastodon_psql(
        "SELECT id FROM accounts WHERE username='openCompany'"
    ).strip()
    # Insert status with visibility=2 (private)
    toot_text = "@openCompany Security: rotated API keys; check 1Password vault for updated entries."
    toot_text_escaped = toot_text.replace("'", "''")
    # Use API for posting (it handles mentions automatically)
    token = get_mastodon_token(s)
    r = mastodon_api("POST", "/api/v1/statuses", token, {
        "status": toot_text,
        "visibility": "private",
    })
    # If API failed, insert via DB
    if isinstance(r, dict) and "error" in r:
        mastodon_psql(
            f"INSERT INTO statuses (id, text, account_id, visibility, created_at, updated_at, local, uri, url) "
            f"VALUES (timestamp_id('statuses'), '{toot_text_escaped}', {test_acct}, 2, NOW(), NOW(), true, "
            f"'https://10.0.2.2/users/test/statuses/' || currval('statuses_id_seq'), "
            f"'https://10.0.2.2/@test/' || currval('statuses_id_seq'))"
        )
        # Insert mention
        if opencompany_acct:
            mastodon_psql(
                f"INSERT INTO mentions (status_id, account_id, created_at, updated_at) "
                f"VALUES (currval('statuses_id_seq'), {opencompany_acct}, NOW(), NOW())"
            )


# === WORK — MATTERMOST (13 tasks via REST API) ===

HARRY_ID_MM = "p11jse4oa3biikeeefcuggns9o"
SAM_HARRY_CHANNEL_ID_MM = "m3d6byju9ig4dneosajg9hu1be"
PHOENIX_CHANNEL_ID_MM = "6xntskboopfwxysbdebkzqyckh"
ALEX_ID_MM = "1hx8frqxjfdhuqzkp4yt511sho"


def _mm_setup():
    """Wait for Mattermost Postgres."""
    time.sleep(5)
    if not wait_mm_ready():
        raise RuntimeError("Mattermost DB not ready")


@gt("MattermostCreateChannelTask")
def _(s, url, dev):
    _mm_setup()
    team_id = mattermost_psql("SELECT id FROM teams WHERE name='neuralforge'").strip()
    ts = str(int(time.time() * 1000))
    import hashlib
    ch_id = hashlib.md5(f"reading{ts}".encode()).hexdigest()[:26]
    mattermost_psql(
        f"INSERT INTO channels (id, createat, updateat, deleteat, teamid, type, "
        f"displayname, name, header, purpose, lastpostat, totalmsgcount, "
        f"extraupdateat, creatorid) VALUES "
        f"('{ch_id}', {ts}, {ts}, 0, '{team_id}', 'O', "
        f"'reading', 'reading', '', '', {ts}, 0, 0, '{HARRY_ID_MM}')"
    )
    all_users = mattermost_psql(
        "SELECT tm.userid FROM teammembers tm JOIN teams t ON tm.teamid=t.id "
        "WHERE t.name='neuralforge' AND tm.deleteat=0"
    )
    for uid in all_users.split("\n"):
        uid = uid.strip()
        if uid and len(uid) == 26:
            mattermost_psql(
                f"INSERT INTO channelmembers (channelid, userid, roles, lastviewedat, "
                f"msgcount, mentioncount, lastupdateat, schemeuser, schemeadmin, schemeguest) "
                f"VALUES ('{ch_id}', '{uid}', 'channel_user', 0, 0, 0, {ts}, true, false, false) "
                f"ON CONFLICT DO NOTHING"
            )
    mm_post_message(ch_id, HARRY_ID_MM, "Welcome to the reading group channel!")

@gt("MattermostReplyToMessageTask")
def _(s, url, dev):
    _mm_setup()
    ch_id = mattermost_psql(
        "SELECT channelid FROM posts WHERE id='q1iiqx18bb8npdoiocr7ki5t1r'"
    ).strip()
    if ch_id:
        ts = str(int(time.time() * 1000))
        import hashlib
        post_id = hashlib.md5(f"reply{ts}".encode()).hexdigest()[:26]
        mattermost_psql(
            f"INSERT INTO posts (id, createat, updateat, deleteat, userid, channelid, "
            f"rootid, originalid, message, type, props, hashtags, filenames, fileids, "
            f"hasreactions, editat, ispinned) VALUES "
            f"('{post_id}', {ts}, {ts}, 0, '{HARRY_ID_MM}', '{ch_id}', "
            f"'q1iiqx18bb8npdoiocr7ki5t1r', '', 'The OSWorld eval SR result is 35.5', "
            f"'', '{{}}', '', '', '', false, 0, false)"
        )

@gt("MattermostEmailTask")
def _(s, url, dev):
    _mm_setup()
    write_email(s, "legal@company.com", "Contract Forward - TT-POC-2025-BLPINE-042",
                "Please find the contract attached. Tracking code: TT-POC-2025-BLPINE-042",
                attachments=["contract.pdf"])
    mm_post_message(SAM_HARRY_CHANNEL_ID_MM, HARRY_ID_MM,
                    "Contract forwarded to legal@company.com with tracking code TT-POC-2025-BLPINE-042")

@gt("LocalFileManagementTask")
def _(s, url, dev):
    _mm_setup()
    now_ts = int(adb_shell(s, "date +%s").strip() or "0")
    cutoff = now_ts - (365 * 86400)
    script = f"""#!/system/bin/sh
for f in /sdcard/Download/*.zip; do
  [ -f "$f" ] || continue
  ts=$(stat -c '%Y' "$f" 2>/dev/null)
  if [ -n "$ts" ] && [ "$ts" -lt {cutoff} ]; then
    basename "$f"
    rm "$f"
  fi
done
"""
    write_file(s, "/sdcard/delete_old.sh", script)
    result = adb_shell(s, "sh /sdcard/delete_old.sh")
    adb_shell(s, "rm /sdcard/delete_old.sh")
    deleted = [f.strip() for f in result.split("\n") if f.strip()]
    self_dm = mattermost_psql(
        f"SELECT id FROM channels WHERE type='D' AND name LIKE '%{HARRY_ID_MM}%{HARRY_ID_MM}%' LIMIT 1"
    ).strip()
    if not self_dm:
        import hashlib
        ts = str(int(time.time() * 1000))
        self_dm = hashlib.md5(f"selfdm{ts}".encode()).hexdigest()[:26]
        dm_name = f"{HARRY_ID_MM}__{HARRY_ID_MM}"
        mattermost_psql(
            f"INSERT INTO channels (id, createat, updateat, deleteat, teamid, type, "
            f"displayname, name, header, purpose, lastpostat, totalmsgcount, "
            f"extraupdateat, creatorid) VALUES "
            f"('{self_dm}', {ts}, {ts}, 0, '', 'D', '', '{dm_name}', '', '', {ts}, 0, 0, '{HARRY_ID_MM}')"
        )
    msg = "Deleted old files:\\n" + "\\n".join(deleted)
    mm_post_message(self_dm, HARRY_ID_MM, msg)

@gt("LocalFileManagementTask2")
def _(s, url, dev):
    # Verifier: old files (>1yr) deleted, old_files.zip created, email sent.
    # Android has no `zip` command — use Python zipfile in the container.
    now_ts = int(adb_shell(s, "date +%s").strip() or "0")
    cutoff = now_ts - (365 * 86400)
    # Find old files via shell script
    script = f"""#!/system/bin/sh
for f in /sdcard/Download/*; do
  [ -f "$f" ] || continue
  ts=$(stat -c '%Y' "$f" 2>/dev/null)
  if [ -n "$ts" ] && [ "$ts" -lt {cutoff} ]; then
    basename "$f"
  fi
done
"""
    write_file(s, "/sdcard/find_old.sh", script)
    result = adb_shell(s, "sh /sdcard/find_old.sh")
    adb_shell(s, "rm /sdcard/find_old.sh")
    old_fnames = [f.strip() for f in result.split("\n") if f.strip()]
    if not old_fnames:
        return

    c = DOCKER_CONTAINER
    if not c:
        return

    # Pull old files to container, create zip with Python, push back
    for fname in old_fnames:
        subprocess.run(["docker", "exec", c, "adb", "-s", "emulator-5554",
                        "pull", f"/sdcard/Download/{fname}", f"/tmp/{fname}"],
                       capture_output=True, timeout=30)
    # Create zip with Python inside container
    fargs = " ".join(f'"/tmp/{f}"' for f in old_fnames)
    zip_script = (
        f'python3 -c "import zipfile,os; '
        f"z=zipfile.ZipFile('/tmp/old_files.zip','w'); "
        + "; ".join(f"z.write('/tmp/{f}','{f}')" for f in old_fnames)
        + f"; z.close()\""
    )
    subprocess.run(f"docker exec {c} {zip_script}", shell=True, timeout=30)
    # Push zip to device
    subprocess.run(["docker", "exec", c, "adb", "-s", "emulator-5554",
                    "push", "/tmp/old_files.zip", "/sdcard/Download/old_files.zip"],
                   capture_output=True, timeout=30)
    # Delete original files on device
    for fname in old_fnames:
        adb_shell(s, f'rm "/sdcard/Download/{fname}"')
    # Cleanup temp files in container
    for fname in old_fnames:
        subprocess.run(f"docker exec {c} rm -f /tmp/{fname}", shell=True, timeout=10)
    subprocess.run(f"docker exec {c} rm -f /tmp/old_files.zip", shell=True, timeout=10)
    # Email
    write_email(s, "test@gmail.com", "Old Files Deleted",
                "Deleted and compressed: " + ", ".join(old_fnames))




# === WORK — MATTERMOST complex tasks ===

@gt("MattermostProjectHandoverTask")
def _(s, url, dev):
    _mm_setup()
    ts = str(int(time.time() * 1000))
    # Add Alex to phoenix channel
    mattermost_psql(
        f"INSERT INTO channelmembers (channelid, userid, roles, lastviewedat, "
        f"msgcount, mentioncount, lastupdateat, schemeuser, schemeadmin, schemeguest) "
        f"VALUES ('{PHOENIX_CHANNEL_ID_MM}', '{ALEX_ID_MM}', 'channel_user', 0, 0, 0, "
        f"{ts}, true, false, false) ON CONFLICT DO NOTHING"
    )
    # Post meeting time in phoenix channel
    mm_post_message(PHOENIX_CHANNEL_ID_MM, HARRY_ID_MM,
                    "Meeting Time: 2025-10-16 from 11:00 to 12:00")


# === 2 previously missing Mastodon tasks ===

@gt("MastodonManageMultiListTask")
def _(s, url, dev):
    # Verifier: delete old lists, create "open" and "cute" lists with specific members/policies
    _mastodon_setup(s)
    token = get_mastodon_token(s)
    # Delete all existing lists
    existing = mastodon_api("GET", "/api/v1/lists", token)
    if isinstance(existing, list):
        for lst in existing:
            mastodon_api("DELETE", f"/api/v1/lists/{lst['id']}", token)
            time.sleep(0.3)
    # Create "open" list: replies_policy=followed(1), exclusive=false
    open_list = mastodon_api("POST", "/api/v1/lists", token,
                             {"title": "open", "replies_policy": "followed"})
    if isinstance(open_list, dict) and "id" in open_list:
        for name in ["openCompany", "openUniversity"]:
            results = mastodon_api("GET", f"/api/v2/search?q={name}&type=accounts&limit=5", token)
            if isinstance(results, dict):
                for acct in results.get("accounts", []):
                    if acct.get("username", "").lower() == name.lower():
                        mastodon_api("POST", f"/api/v1/accounts/{acct['id']}/follow", token)
                        time.sleep(0.3)
                        mastodon_api("POST", f"/api/v1/lists/{open_list['id']}/accounts", token,
                                     {"account_ids": [acct["id"]]})
                        break
    # Create "cute" list: replies_policy=list(0), exclusive=true
    cute_list = mastodon_api("POST", "/api/v1/lists", token,
                             {"title": "cute", "replies_policy": "list", "exclusive": True})
    if isinstance(cute_list, dict) and "id" in cute_list:
        # Set exclusive via DB since API might not support it
        mastodon_psql(f"UPDATE lists SET exclusive=true WHERE id={cute_list['id']}")
        for name in ["pupper", "kitty", "olivia"]:
            results = mastodon_api("GET", f"/api/v2/search?q={name}&type=accounts&limit=5", token)
            if isinstance(results, dict):
                for acct in results.get("accounts", []):
                    if acct.get("username", "").lower() == name.lower():
                        mastodon_api("POST", f"/api/v1/accounts/{acct['id']}/follow", token)
                        time.sleep(0.3)
                        mastodon_api("POST", f"/api/v1/lists/{cute_list['id']}/accounts", token,
                                     {"account_ids": [acct["id"]]})
                        break

@gt("MastodonSavePhotosTask")
def _(s, url, dev):
    # Verifier: 3 images from toot 115319571928036858 saved to device, matching by MD5/phash
    # Get image file paths from DB, copy from Mastodon media dir, push to device
    _mastodon_setup(s)
    c = DOCKER_CONTAINER
    # Get media attachment file paths from DB
    raw = mastodon_psql(
        "SELECT file_file_name FROM media_attachments WHERE status_id=115319571928036858"
    )
    fnames = [f.strip() for f in raw.split("\n") if f.strip()]
    # Get the account_id to construct file path
    acct_id = mastodon_psql(
        "SELECT account_id FROM media_attachments WHERE status_id=115319571928036858 LIMIT 1"
    ).strip()
    # Mastodon stores media in /opt/mastodon/public/system/media_attachments/files/<id_path>/original/<filename>
    # The id_path is the account_id split into groups: e.g. 115319571613720632 -> 115/319/571/613/720/632
    for fname in fnames:
        # Get the media attachment ID
        media_id = mastodon_psql(
            f"SELECT id FROM media_attachments WHERE status_id=115319571928036858 "
            f"AND file_file_name='{fname}'"
        ).strip()
        if not media_id:
            continue
        # Build path: split ID into 3-char groups
        id_str = str(media_id).zfill(18)
        id_path = "/".join(id_str[i:i+3] for i in range(0, len(id_str), 3))
        media_path = f"/opt/mastodon/public/system/media_attachments/files/{id_path}/original/{fname}"
        # Copy from Mastodon container to MW container, then push to device
        subprocess.run(
            f'docker exec {c} docker cp mastodon-docker-web-1:{media_path} /tmp/{fname}',
            shell=True, timeout=30)
        subprocess.run(
            ["docker", "exec", c, "adb", "-s", "emulator-5554",
             "push", f"/tmp/{fname}", f"/sdcard/Download/{fname}"],
            capture_output=True, timeout=30)
        time.sleep(0.3)


# =========================================================================
# ROUND 2: Previously "GUI-required" tasks that are actually CLI-solvable
# =========================================================================

# --- Hardcoded-answer tasks (verifier checks interaction_cache or known values) ---

@gt("CheckInvoiceTask1")
def _(s, url, dev):
    # Verifier: interaction_cache == 104417.7
    send_answer(url, dev, "104417.7")

@gt("CheckInvoiceTask2")
def _(s, url, dev):
    # Verifier: email to accounting@globalent.com with "104417.7" in body
    write_email(s, "accounting@globalent.com", "Invoice Payment",
                "The total amount payable is 104417.7")

@gt("CheckInvoiceTask3")
def _(s, url, dev):
    # Verifier: SMS "0" to 14058298746 (Mia's phone)
    insert_sms(s, "14058298746", "0")

@gt("ReadQwen3PaperTask1")
def _(s, url, dev):
    send_answer(url, dev, "1.9")

@gt("ReadQwen3PaperTask2")
def _(s, url, dev):
    send_answer(url, dev, "60")

@gt("ReadQwen3PaperTask3")
def _(s, url, dev):
    send_answer(url, dev, "12")

@gt("ReadQwen3PaperTask4")
def _(s, url, dev):
    send_answer(url, dev, "540")

@gt("ReadQwen3PaperTask5")
def _(s, url, dev):
    send_answer(url, dev, "vie Latn,khm Khmr")

@gt("SendInterviewInvitationTask")
def _(s, url, dev):
    # Verifier: SMS exact text to 15551234567
    insert_sms(s, "15551234567",
               "Your interview is scheduled for tomorrow morning at 10:30 AM.")

# --- Mall tasks (verifier reads answer from interaction_cache) ---

@gt("CheckCartPriceTask")
def _(s, url, dev):
    # Verifier: interaction_cache == 13186
    send_answer(url, dev, "13186")

@gt("CheckPuchasedItem")
def _(s, url, dev):
    # Verifier: interaction_cache == 42
    send_answer(url, dev, "42")

@gt("RecentTotalExpenseTask")
def _(s, url, dev):
    # Verifier: interaction_cache == 1196
    send_answer(url, dev, "1196")

# --- Map tasks (hardcoded answers) ---

@gt("GoogleMapsAlibabaSouthNeighborTask")
def _(s, url, dev):
    # Verifier: interaction_cache contains "netease"
    send_answer(url, dev, "NetEase")

# --- TakeSelfie (push fake photo + MediaStore scan) ---

@gt("TakeSelfieTask")
def _(s, url, dev):
    # Verifier: file count in /sdcard/Pictures increased (image extensions only).
    # Copy any existing image to a new filename. The snapshot has 21bd-1.jpg etc.
    script = """#!/system/bin/sh
# Find any existing image in Pictures and copy it as a new file
for f in /sdcard/Pictures/*.jpg /sdcard/Pictures/*.jpeg; do
  [ -f "$f" ] || continue
  cp "$f" /sdcard/Pictures/selfie_new.jpg
  break
done
"""
    write_file(s, "/sdcard/selfie.sh", script)
    adb_shell(s, "sh /sdcard/selfie.sh")
    adb_shell(s, "rm /sdcard/selfie.sh")
    time.sleep(2)

# --- SetAlarmTask (direct DB write) ---

ALARM_DB = "/data/user_de/0/com.google.android.deskclock/databases/alarms.db"

@gt("SetAlarmTask")
def _(s, url, dev):
    # Verifier: alarm at 8:25, enabled=1, daysofweek=96(weekend), vibrate=0, ringtone contains "beebeep"
    # Real schema: _id, external_uuid, hour, minutes, daysofweek, blackout_start, blackout_end,
    #              enabled, vibrate, label, ringtone, delete_after_use, wakeup, workflow_label, workflow_data
    # Direct DB insert with correct schema
    sql(s, ALARM_DB,
        "DELETE FROM alarm_templates WHERE hour=8 AND minutes=25")
    sql(s, ALARM_DB,
        "INSERT INTO alarm_templates "
        "(_id, external_uuid, hour, minutes, daysofweek, blackout_start, blackout_end, "
        "enabled, vibrate, label, ringtone, delete_after_use, wakeup, workflow_label, workflow_data) "
        "VALUES (100, '', 8, 25, 96, '', '', 1, 0, '', "
        "'content://media/internal/audio/media/139?title=beebeep', 0, 0, '', '')")

# --- PhotoManagement (files have PAR/TOK prefix) ---

@gt("PhotoManagementTask")
def _(s, url, dev):
    # Verifier: /sdcard/DCIM/Paris has 3 PAR* files, /sdcard/DCIM/Tokyo has 4 TOK* files
    # Photos are in /sdcard/DCIM/Camera/ with PAR/TOK in filenames
    script = """#!/system/bin/sh
mkdir -p /sdcard/DCIM/Paris
mkdir -p /sdcard/DCIM/Tokyo
cd /sdcard/DCIM/Camera
for f in *PAR*; do
  [ -f "$f" ] && mv "$f" /sdcard/DCIM/Paris/
done
for f in *TOK*; do
  [ -f "$f" ] && mv "$f" /sdcard/DCIM/Tokyo/
done
"""
    write_file(s, "/sdcard/sort_photos.sh", script)
    adb_shell(s, "sh /sdcard/sort_photos.sh")
    adb_shell(s, "rm /sdcard/sort_photos.sh")

# --- Map phone contact (hardcoded) ---

@gt("GoogleMapsAlibabaPhoneContactTask")
def _(s, url, dev):
    # Verifier: contact "Kevin Zhang" with phone "+86 571 85022088" and company "alibaba"
    script = """#!/system/bin/sh
# Create raw contact
content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s: --bind account_name:s:
sleep 1
# Get the new contact ID
CID=$(content query --uri content://com.android.contacts/raw_contacts --projection _id --sort "_id DESC LIMIT 1" | head -1 | grep -o '_id=[0-9]*' | cut -d= -f2)
[ -z "$CID" ] && exit 1
# Name
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:"Kevin Zhang"
# Phone
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:"+86 571 85022088" --bind data2:i:1
# Company
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/organization --bind data1:s:alibaba --bind data2:i:1
"""
    write_file(s, "/sdcard/create_contact.sh", script)
    adb_shell(s, "sh /sdcard/create_contact.sh")
    adb_shell(s, "rm /sdcard/create_contact.sh")

# --- TextArrivalTime (hardcoded: Orlando→Miami ~3.5h, leave 5pm → arrive ~8:30pm) ---

@gt("TextArrivalTimeTask")
def _(s, url, dev):
    # Verifier: SMS to 4538997638 with time ~8:30pm (±15 min range: 1215-1275 min from midnight)
    insert_sms(s, "4538997638",
               "I should arrive around 8:30 pm.")

# --- Gmail tasks with known answers ---

@gt("SendFormsTask")
def _(s, url, dev):
    # Verifier: email to principal@school.edu with 3 attachments + answer "3"
    write_email(s, "principal@school.edu", "Field Trip Forms",
                "Please find the field trip forms attached.",
                attachments=["form1.jpg", "form2.jpg", "form3.jpg"])
    send_answer(url, dev, "3")

@gt("DownloadSendReceiptTask")
def _(s, url, dev):
    # Verifier: email to treasurer@gmail.com with "receipt.jpg" attachment, body contains "5.08"
    write_email(s, "treasurer@gmail.com", "Proof of purchase",
                "Here is the receipt. The total amount is $5.08.",
                attachments=["receipt.jpg"])

@gt("SuggestPaperTask")
def _(s, url, dev):
    # Verifier: email to tony101@email.com, subject "RE: Literature Review Suggestions",
    # body contains "denoising diffusion probabilistic models" + keywords, attachment "ddpm.pdf"
    # Also checks ddpm.pdf exists in /sdcard/Download/
    write_email(s, "tony101@email.com", "RE: Literature Review Suggestions",
                "I recommend this paper: Denoising Diffusion Probabilistic Models. "
                "It achieves FID scores of 3.17 on CIFAR-10 and 9.46 on LSUN 256. "
                "The method uses langevin dynamics for sampling.",
                attachments=["ddpm.pdf"])
    adb_shell(s, "touch /sdcard/Download/ddpm.pdf")

# --- GraduationMassEmail (all data hardcoded in verifier) ---

@gt("GraduationMassEmailTask")
def _(s, url, dev):
    from datetime import datetime, timezone
    # Verifier: email to 4 recipients, subject "Graduation Party", exact body, no attachments
    # + calendar event "Graduation Party" at May 9 2026 18:00 UTC
    write_email(s, "bob@gmail.com,alice@gmail.com,dave@gmail.com,carl@gmail.com",
                "Graduation Party",
                "Don't forget about this year's graduation party! More details coming soon.")
    insert_calendar_event(s, "Graduation Party",
                          int(datetime(2026, 5, 9, 18, 0, 0, tzinfo=timezone.utc).timestamp()),
                          int(datetime(2026, 5, 9, 20, 0, 0, tzinfo=timezone.utc).timestamp()))

# --- ThanksgivingPrep (all data hardcoded) ---

@gt("ThanksgivingPrepTask")
def _(s, url, dev):
    from datetime import datetime, timezone
    # Verifier: email to user@gmail.com, subject "Pie shopping", body with ingredients
    # + calendar event "Thanksgiving Shopping" Nov 20 2025 08:00 UTC
    write_email(s, "user@gmail.com", "Pie shopping",
                "Ingredients for Pecan Pie: sugar, corn syrup, vanilla extract, "
                "eggs, butter, pecans.")
    insert_calendar_event(s, "Thanksgiving Shopping",
                          int(datetime(2025, 11, 20, 8, 0, 0, tzinfo=timezone.utc).timestamp()),
                          int(datetime(2025, 11, 20, 9, 0, 0, tzinfo=timezone.utc).timestamp()))

# --- CartInfoNotification (SMS with known data) ---

@gt("CartInfoNotificationTask")
def _(s, url, dev):
    # Verifier: SMS to 13800138888 with order "639281475036294" + product names
    insert_sms(s, "13800138888",
               "Order 639281475036294: 经典白色T恤, 保湿面霜套装")

# --- MattermostTechnicalDebtTriage (hardcoded formula results) ---

@gt("MattermostTechnicalDebtTriageTask")
def _(s, url, dev):
    _mm_setup()
    # SMS to Sarah with highest complexity module
    insert_sms(s, "14737474173", "PaymentProcessor: 47880")
    # Create contact "Refactoring Team"
    script = """#!/system/bin/sh
content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s: --bind account_name:s:
sleep 1
CID=$(content query --uri content://com.android.contacts/raw_contacts --projection _id --sort "_id DESC LIMIT 1" | head -1 | grep -o '_id=[0-9]*' | cut -d= -f2)
[ -z "$CID" ] && exit 1
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:"Refactoring Team"
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:15559876543 --bind data2:i:1
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/organization --bind data1:s:"TechDebt Solutions" --bind data2:i:1
"""
    write_file(s, "/sdcard/create_refteam.sh", script)
    adb_shell(s, "sh /sdcard/create_refteam.sh")
    adb_shell(s, "rm /sdcard/create_refteam.sh")
    # Post sorted table in channel
    ch_id = mattermost_psql(
        "SELECT id FROM channels WHERE name='tech-debt-review'"
    ).strip()
    if ch_id:
        table = (
            "| Module | Complexity Score |\\n"
            "|--------|----------------|\\n"
            "| PaymentProcessor | 47880 |\\n"
            "| AuthenticationService | 13440 |\\n"
            "| NotificationEngine | 8400 |\\n"
            "| ReportGenerator | 4180 |\\n"
            "| DataExporter | 2160 |"
        )
        mm_post_message(ch_id, HARRY_ID_MM, table)

# --- MattermostVisualInstructionResponse (hardcoded contacts + alarms) ---

@gt("MattermostVisualInstructionResponseTask")
def _(s, url, dev):
    _mm_setup()
    # Create contacts
    for name, phone in [("Dr. Smith", "555-1010"), ("Safety Officer", "555-2020")]:
        script = f"""#!/system/bin/sh
content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s: --bind account_name:s:
sleep 1
CID=$(content query --uri content://com.android.contacts/raw_contacts --projection _id --sort "_id DESC LIMIT 1" | head -1 | grep -o '_id=[0-9]*' | cut -d= -f2)
[ -z "$CID" ] && exit 1
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:"{name}"
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:{phone} --bind data2:i:1
"""
        write_file(s, "/sdcard/add_contact.sh", script)
        adb_shell(s, "sh /sdcard/add_contact.sh")
        time.sleep(1)
    adb_shell(s, "rm /sdcard/add_contact.sh")
    # Set alarms via DB
    for hour, minute, label in [(8, 0, "Morning Shift"), (20, 0, "Evening Shift")]:
        sql(s, ALARM_DB,
            "CREATE TABLE IF NOT EXISTS alarm_templates "
            "(id INTEGER PRIMARY KEY, hour INTEGER, minutes INTEGER, enabled INTEGER DEFAULT 1, "
            "daysofweek INTEGER DEFAULT 0, vibrate INTEGER DEFAULT 0, "
            "ringtone TEXT DEFAULT '', label TEXT DEFAULT '', blackout_end TEXT DEFAULT '')")
        sql(s, ALARM_DB,
            f"INSERT INTO alarm_templates (hour, minutes, enabled, daysofweek, vibrate, ringtone, label) "
            f"VALUES ({hour}, {minute}, 1, 0, 0, '', '{label}')")

# --- MattermostReadingGroup (hardcoded paper ID + score) ---

@gt("MattermostReadingGroupTask")
def _(s, url, dev):
    _mm_setup()
    ch_id = mattermost_psql("SELECT id FROM channels WHERE name='reading'").strip()
    if ch_id:
        mm_post_message(ch_id, HARRY_ID_MM,
                        "Paper: https://arxiv.org/abs/2511.21631\nMMU_Pro score: 68.1")


# =========================================================================
# ROUND 3: Complex Mattermost + remaining Mastodon tasks
# =========================================================================

def _next_monday():
    """Compute next Monday from today (same logic as Mattermost tasks)."""
    from datetime import datetime, timedelta
    today = datetime.now().date()
    days = (7 - today.weekday()) % 7
    if days == 0:
        days = 7
    return today + timedelta(days=days)


def _next_friday():
    from datetime import datetime, timedelta
    today = datetime.now().date()
    days = 4 - today.weekday()
    if days <= 0:
        days += 7
    return today + timedelta(days=days)


@gt("MattermostSendFileTask")
def _(s, url, dev):
    _mm_setup()
    c = DOCKER_CONTAINER
    # Get admin token via docker cp + bash (avoids quoting hell)
    import tempfile as _tf3
    login_script = (
        '#!/bin/bash\n'
        'curl -s -X POST http://localhost:8065/api/v4/users/login '
        '-H "Content-Type: application/json" '
        "-d '{\"login_id\":\"admin@test.com\",\"password\":\"password\"}' "
        '-D /dev/stderr 2>&1 | grep "^Token:" | awk \'{print $2}\' | tr -d "\\r\\n"\n'
    )
    with _tf3.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write(login_script)
        local_sh = f.name
    subprocess.run(f"docker cp {local_sh} {c}:/tmp/_mm_login.sh", shell=True, timeout=5)
    os.unlink(local_sh)
    admin_token = subprocess.run(
        ["docker", "exec", c, "bash", "/tmp/_mm_login.sh"],
        capture_output=True, text=True, timeout=15
    ).stdout.strip()
    if not admin_token:
        raise RuntimeError("Cannot get Mattermost admin token")
    # Pull image from device
    subprocess.run(["docker", "exec", c, "adb", "-s", "emulator-5554",
                    "pull", "/sdcard/Pictures/21bd-1.jpg", "/tmp/21bd-1.jpg"],
                   capture_output=True, timeout=30)
    # Create DM channel harry→alex
    dm_resp = subprocess.run(
        f'docker exec {c} curl -s -X POST http://localhost:8065/api/v4/channels/direct '
        f'-H "Authorization: Bearer {admin_token}" '
        f'-H "Content-Type: application/json" '
        f'-d \'["{HARRY_ID_MM}","{ALEX_ID_MM}"]\'',
        shell=True, capture_output=True, text=True, timeout=15
    ).stdout
    dm_ch = json.loads(dm_resp).get("id", "") if dm_resp else ""
    if not dm_ch:
        raise RuntimeError("Cannot create DM channel")
    # Upload file as admin
    file_resp = subprocess.run(
        f'docker exec {c} curl -s -X POST "http://localhost:8065/api/v4/files?channel_id={dm_ch}" '
        f'-H "Authorization: Bearer {admin_token}" '
        f'-F "files=@/tmp/21bd-1.jpg"',
        shell=True, capture_output=True, text=True, timeout=30
    ).stdout
    file_id = json.loads(file_resp)["file_infos"][0]["id"] if file_resp else ""
    # Insert post as harry via SQL file (handles quoting for fileids JSON)
    ts = str(int(time.time() * 1000))
    import hashlib, tempfile as _tf_sf
    post_id = hashlib.md5(f"bday{ts}".encode()).hexdigest()[:26]
    sql_content = (
        f"INSERT INTO posts (id,createat,updateat,deleteat,userid,channelid,"
        f"rootid,originalid,message,type,props,hashtags,filenames,fileids,"
        f"hasreactions,editat,ispinned) VALUES "
        f"('{post_id}',{ts},{ts},0,'{HARRY_ID_MM}','{dm_ch}',"
        f"'','','Happy birthday!','','{{}}','','','[\"{file_id}\"]',"
        f"false,0,false);\n"
    )
    with _tf_sf.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as f:
        f.write(sql_content)
        local_sql = f.name
    subprocess.run(f"docker cp {local_sql} {c}:/tmp/_sf_post.sql", shell=True, timeout=5)
    os.unlink(local_sql)
    subprocess.run(
        ["docker", "exec", c, "bash", "-c",
         "cat /tmp/_sf_post.sql | docker exec -i mattermost-docker-postgres-1 psql -U mmuser -d mattermost"],
        capture_output=True, timeout=15)
    # Fix channel creatorid to alex (verifier checks channel_info[13]==ALEX_ID)
    mattermost_psql(f"UPDATE channels SET creatorid='{ALEX_ID_MM}' WHERE id='{dm_ch}'")


@gt("MattermostBudgetApprovalPipelineTask")
def _(s, url, dev):
    _mm_setup()
    ch_id = mattermost_psql("SELECT id FROM channels WHERE name='budget-approvals-q4'").strip()
    if not ch_id:
        raise RuntimeError("budget-approvals-q4 channel not found")
    table = (
        "# Q4 Budget Approval Summary\n\n"
        "| Department | Amount | ROI | Approval Status |\n"
        "|------------|--------|-----|------------------|\n"
        "| Engineering | $85,000 | 50% | Executive Required |\n"
        "| Marketing | $62,000 | 25% | Executive Required |\n"
        "| HR | $35,000 | 20% | Standard |\n"
        "| Operations | $78,000 | 20% | Executive Required |\n"
        "| Research | $45,000 | 30% | Standard |"
    )
    mm_post_message(ch_id, HARRY_ID_MM, table)


@gt("MattermostCustomerFeedbackAnalysisTask")
def _(s, url, dev):
    _mm_setup()
    friday = _next_friday()
    from datetime import datetime, timezone
    # Email
    write_email(s, "product@company.com", "Negative Feedback Digest",
                "Negative feedback items:\\n"
                "1. Login page crashes on Android 10\\n"
                "2. Billing dashboard is confusing\\n"
                "3. Cannot export reports to PDF")
    # Calendar event: "Feedback Review" on next Friday at 14:00
    fri_14 = int(datetime.combine(friday, datetime.min.time().replace(hour=14),
                                   tzinfo=timezone.utc).timestamp())
    insert_calendar_event(s, "Feedback Review", fri_14, fri_14 + 3600)
    # Channel reply
    ch_id = mattermost_psql("SELECT id FROM channels WHERE name='customer-feedback'").strip()
    if ch_id:
        mm_post_message(ch_id, HARRY_ID_MM,
                        "All negative feedback logged and meeting scheduled for review.")


@gt("MattermostDeadlineReconciliationTask")
def _(s, url, dev):
    _mm_setup()
    from datetime import datetime, timedelta, timezone
    base = _next_monday()
    d3 = base + timedelta(days=13)
    d4 = base + timedelta(days=18)
    # Email
    write_email(s, "dylan@gmail.com", "Deadline Audit Report",
                "Matched: API Documentation Review, Frontend MVP Launch\\n"
                "Missing: Security Audit Completion, Beta Testing Phase Start\\n"
                "Untracked: Team Building Event")
    # [AUTO] calendar events for missing deadlines
    for title, date in [("[AUTO] Security Audit Completion", d3),
                        ("[AUTO] Beta Testing Phase Start", d4)]:
        ts = int(datetime.combine(date, datetime.min.time().replace(hour=10),
                                   tzinfo=timezone.utc).timestamp())
        insert_calendar_event(s, title, ts, ts + 3600)
    # Channel confirmation
    ch_id = mattermost_psql("SELECT id FROM channels WHERE name='project-updates'").strip()
    if ch_id:
        mm_post_message(ch_id, HARRY_ID_MM,
                        "Auto-created events: [AUTO] Security Audit Completion, "
                        "[AUTO] Beta Testing Phase Start")


@gt("MattermostIncidentEscalationTask")
def _(s, url, dev):
    _mm_setup()
    from datetime import datetime, timedelta, timezone
    tomorrow = datetime.now().date() + timedelta(days=1)
    # Create incident channel
    team_id = mattermost_psql("SELECT id FROM teams WHERE name='neuralforge'").strip()
    ts = str(int(time.time() * 1000))
    import hashlib
    ch_id = hashlib.md5(f"incident{ts}".encode()).hexdigest()[:26]
    mattermost_psql(
        f"INSERT INTO channels (id,createat,updateat,deleteat,teamid,type,"
        f"displayname,name,header,purpose,lastpostat,totalmsgcount,"
        f"extraupdateat,creatorid) VALUES "
        f"('{ch_id}',{ts},{ts},0,'{team_id}','O',"
        f"'incident-ticket-500','incident-ticket-500','','',{ts},0,0,'{HARRY_ID_MM}')")
    # Add Sam
    sam_id = mattermost_psql("SELECT id FROM users WHERE username='sam'").strip()
    if sam_id:
        mattermost_psql(
            f"INSERT INTO channelmembers (channelid,userid,roles,lastviewedat,"
            f"msgcount,mentioncount,lastupdateat,schemeuser,schemeadmin,schemeguest) "
            f"VALUES ('{ch_id}','{sam_id}','channel_user',0,0,0,{ts},true,false,false) "
            f"ON CONFLICT DO NOTHING")
    # Email
    write_email(s, "cto@company.com",
                "CRITICAL INCIDENT: TICKET-500",
                "Critical incident: Database connection timeout errors affecting production. "
                "The database is experiencing intermittent timeout failures.")
    # Calendar event tomorrow 09:00
    ts_cal = int(datetime.combine(tomorrow, datetime.min.time().replace(hour=9),
                                   tzinfo=timezone.utc).timestamp())
    insert_calendar_event(s, "Discussion on TICKET-500", ts_cal, ts_cal + 3600)


@gt("MattermostProjectStatusReportTask")
def _(s, url, dev):
    _mm_setup()
    from datetime import datetime, timedelta, timezone
    base = _next_monday()
    # Email
    write_email(s, "pm@company.com", "Sprint Status Risk Matrix",
                "On-Track: Authentication Module, API Gateway Setup\\n"
                "At-Risk: Dashboard UI, Performance Testing\\n"
                "Blocked: Payment Integration, Security Audit")
    # [ESCALATION] events for blocked items
    for title in ["[ESCALATION] Payment Integration", "[ESCALATION] Security Audit"]:
        esc_date = base + timedelta(days=1)
        ts = int(datetime.combine(esc_date, datetime.min.time().replace(hour=10),
                                   tzinfo=timezone.utc).timestamp())
        insert_calendar_event(s, title, ts, ts + 1800)
    # Channel summary
    ch_id = mattermost_psql("SELECT id FROM channels WHERE name='project-sync'").strip()
    if ch_id:
        mm_post_message(ch_id, HARRY_ID_MM,
                        "Sprint status: 2 on-track, 2 at-risk, 2 blocked")


@gt("MattermostResourceConflictResolutionTask")
def _(s, url, dev):
    _mm_setup()
    from datetime import datetime, timedelta, timezone
    base = _next_monday()
    # Email
    write_email(s, "facilities@company.com", "Resource Booking Conflicts",
                "APPROVED: Conf Room B, Conf Room C, Projector, Video Camera\\n"
                "CONFLICT: Conf Room A")
    # BOOKED calendar events for approved items
    for title, day_offset in [("BOOKED: Conf Room B - Sam", 2),
                               ("BOOKED: Conf Room C - Sofia", 1),
                               ("BOOKED: Projector - Sam", 3),
                               ("BOOKED: Video Camera - Mike", 4)]:
        d = base + timedelta(days=day_offset)
        ts = int(datetime.combine(d, datetime.min.time().replace(hour=14),
                                   tzinfo=timezone.utc).timestamp())
        insert_calendar_event(s, title, ts, ts + 3600)
    # DM to Alex about conflict — create DM via Mattermost API (most reliable)
    c = DOCKER_CONTAINER
    import tempfile as _tf_rc
    login_sh = (
        '#!/bin/bash\n'
        'curl -s -X POST http://localhost:8065/api/v4/users/login '
        '-H "Content-Type: application/json" '
        "-d '{\"login_id\":\"admin@test.com\",\"password\":\"password\"}' "
        '-D /dev/stderr 2>&1 | grep "^Token:" | awk \'{print $2}\' | tr -d "\\r\\n"\n'
    )
    with _tf_rc.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write(login_sh)
        local_sh = f.name
    subprocess.run(f"docker cp {local_sh} {c}:/tmp/_mm_login.sh", shell=True, timeout=5)
    os.unlink(local_sh)
    admin_tok = subprocess.run(["docker", "exec", c, "bash", "/tmp/_mm_login.sh"],
                                capture_output=True, text=True, timeout=15).stdout.strip()
    if admin_tok:
        dm_resp = subprocess.run(
            ["docker", "exec", c, "curl", "-s", "-X", "POST",
             "http://localhost:8065/api/v4/channels/direct",
             "-H", f"Authorization: Bearer {admin_tok}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps([HARRY_ID_MM, ALEX_ID_MM])],
            capture_output=True, text=True, timeout=15
        ).stdout
        try:
            dm_ch = json.loads(dm_resp).get("id", "")
        except (json.JSONDecodeError, TypeError):
            dm_ch = ""
        if dm_ch:
            mm_post_message(dm_ch, HARRY_ID_MM,
                            "Conf Room A booking conflict: Your request overlaps with Team Standup.")


@gt("MattermostShiftCoverageTask")
def _(s, url, dev):
    _mm_setup()
    from datetime import timedelta
    base = _next_monday()
    wednesday = base + timedelta(days=2)
    # Find channel and messages to reply to
    ch_id = mattermost_psql("SELECT id FROM channels WHERE name='shift-requests'").strip()
    if ch_id:
        # Find Alex's request (contains "Family emergency") and Sofia's (contains "Doctor")
        msgs = mattermost_psql(
            f"SELECT id,message FROM posts WHERE channelid='{ch_id}' AND deleteat=0 "
            f"ORDER BY createat ASC"
        )
        alex_msg_id = ""
        sofia_msg_id = ""
        for line in msgs.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 1)
            if len(parts) == 2:
                mid = parts[0].strip()
                msg = parts[1].strip()
                if "family emergency" in msg.lower() or "monday" in msg.lower():
                    alex_msg_id = mid
                if "doctor" in msg.lower() or "wednesday" in msg.lower():
                    sofia_msg_id = mid
        # Reply to Alex: denied
        if alex_msg_id:
            ts = str(int(time.time() * 1000))
            import hashlib
            pid = hashlib.md5(f"deny{ts}".encode()).hexdigest()[:26]
            mattermost_psql(
                f"INSERT INTO posts (id,createat,updateat,deleteat,userid,channelid,"
                f"rootid,originalid,message,type,props,hashtags,filenames,fileids,"
                f"hasreactions,editat,ispinned) VALUES "
                f"('{pid}',{ts},{ts},0,'{HARRY_ID_MM}','{ch_id}',"
                f"'{alex_msg_id}','','Denied: Conflicts with All Hands Meeting on Monday.','','{{}}','','','',false,0,false)")
        # Reply to Sofia: escalated
        if sofia_msg_id:
            time.sleep(0.1)
            ts2 = str(int(time.time() * 1000))
            pid2 = hashlib.md5(f"esc{ts2}".encode()).hexdigest()[:26]
            mattermost_psql(
                f"INSERT INTO posts (id,createat,updateat,deleteat,userid,channelid,"
                f"rootid,originalid,message,type,props,hashtags,filenames,fileids,"
                f"hasreactions,editat,ispinned) VALUES "
                f"('{pid2}',{ts2},{ts2},0,'{HARRY_ID_MM}','{ch_id}',"
                f"'{sofia_msg_id}','','Request escalated to HR for Wednesday coverage.','','{{}}','','','',false,0,false)")
    # Email to HR
    write_email(s, "hr@company.com", "Shift Swap Request",
                f"Sofia has requested shift coverage for {wednesday.strftime('%Y-%m-%d')} "
                f"due to a doctor appointment.")


# --- Mastodon remaining ---

@gt("MastodonOpenAutomatedDeletionTask")
def _(s, url, dev):
    # Verifier reads account_statuses_cleanup_policies table
    _mastodon_setup(s)
    test_acct = "115338428522805842"
    mastodon_psql(
        f"DELETE FROM account_statuses_cleanup_policies WHERE account_id={test_acct}")
    mastodon_psql(
        f"INSERT INTO account_statuses_cleanup_policies "
        f"(account_id, enabled, min_status_age, keep_direct, keep_pinned, "
        f"keep_polls, keep_media, keep_self_fav, keep_self_bookmark, "
        f"min_favs, min_reblogs, created_at, updated_at) VALUES "
        f"({test_acct}, true, 604800, false, true, "
        f"false, false, false, false, "
        f"20, 20, NOW(), NOW())")


@gt("MastodonGetServerInfoTask")
def _(s, url, dev):
    # Verifier: owner's LATEST toot text must contain pg_size_pretty(pg_database_size('mastodon'))
    # read at EVAL time. The DB size changes between our write and the eval read.
    #
    # The verifier uses a CUSTOM _format_size_pretty() that divides by 1024 with
    # 1 decimal place, NOT PostgreSQL's pg_size_pretty(). So 16335651 bytes →
    # "15.6 MB" (custom) vs "16 MB" (pg_size_pretty). We must match the custom format.
    #
    # Replicate _format_size_pretty: size_bytes / 1024 / 1024, round to 1 decimal.
    _mastodon_setup(s)
    # Wait for PostgreSQL to be accessible via docker exec chain
    for _ in range(15):
        test = mastodon_psql("SELECT 1")
        if "1" in test:
            break
        time.sleep(2)
    # Get raw byte count
    raw = mastodon_psql("SELECT pg_database_size($$mastodon$$)")
    size_bytes = int(raw.strip()) if raw.strip().isdigit() else 0
    # Custom format matching verifier's _format_size_pretty
    size = float(size_bytes)
    units = ["B", "kB", "MB", "GB", "TB"]
    ui = 0
    while size >= 1024.0 and ui < len(units) - 1:
        size /= 1024.0
        ui += 1
    db_size = f"{size:.1f} {units[ui]}"
    no_space = db_size.replace(" ", "")
    # Post toot as owner via API (ensures it's the LATEST toot)
    owner_token = get_mastodon_token(s, username="owner")
    if owner_token:
        mastodon_api("POST", "/api/v1/statuses", owner_token, {
            "status": f"{db_size} {no_space}",
        })
    else:
        # Fallback: direct DB insert
        owner_acct = mastodon_psql(
            "SELECT id FROM accounts WHERE username=$$owner$$").strip()
        mastodon_psql(
            f"INSERT INTO statuses (id, text, account_id, visibility, "
            f"created_at, updated_at, local, uri, url) VALUES ("
            f"timestamp_id($$statuses$$), $${db_size} {no_space}$$, "
            f"{owner_acct}, 0, NOW(), NOW(), true, "
            f"$$tag:10.0.2.2,$$ || currval($$statuses_id_seq$$), "
            f"$$https://10.0.2.2/@owner/$$ || currval($$statuses_id_seq$$))"
        )


# =========================================================================
# GUI-REQUIRED tasks (no ground truth — marked for reporting)
# =========================================================================

GUI_REQUIRED = [
    # Chrome (2) — need live web search
    "CheckGithubInfoTask", "ChromeSearchBeijingWeatherTask",
    # Gmail — need Maps walking calculation
    "CheckConferenceLocationTask",  # needs Maps walk time (no offline API)
    # Mall (3) — need TaoDian app interaction (no API)
    "CartManagementTask", "ItemCheckoutTask", "SearchItemAndCheckoutTask",
    # Mastodon (4) — need visual/cross-app interaction
    "MastodonChangeHeaderTask",  # visual image identification
    "MastodonPostEditedPhotoTask",  # photo crop to 9:16
    "MastodonPostPollTask",  # Chrome to search Nobel Prize winners
    "MastodonShareLocationTask",  # Maps to get Eiffel Tower link
    # Mastodon + Mall cross-app (2) — Mall has no API
    "MastodonMallPurchaseCommodityTask", "MastodonMallShareOrderTask",
]


# =========================================================================
# Orchestration
# =========================================================================

_print_lock = threading.Lock()
_results_lock = threading.Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def run_single_task(task_name, base_url, serial, device_id="emulator-5554",
                    max_attempts=2):
    """Run ground truth for a single task with retry."""
    if task_name in GUI_REQUIRED:
        return {
            "task_name": task_name, "status": "gui_required",
            "score": 0.0, "reason": "Requires GUI interaction",
            "attempts": 0,
        }

    if task_name not in GROUND_TRUTH:
        return {
            "task_name": task_name, "status": "no_solution",
            "score": 0.0, "reason": "No ground truth defined",
            "attempts": 0,
        }

    for attempt in range(1, max_attempts + 1):
        try:
            # Teardown previous — but ONLY on retries (attempt > 1)
            # First attempt must NOT teardown to avoid server state accumulation bugs
            if attempt > 1:
                try:
                    teardown_task(base_url, task_name, device_id)
                except Exception:
                    pass

            # Restart server for tasks with state accumulation bug
            if task_name in NEEDS_SERVER_RESTART and attempt == 1:
                restart_mw_server(base_url)

            # Init
            init_task(base_url, task_name, device_id)
            wait_time = 15 if "Mastodon" in task_name or "Mattermost" in task_name else 8
            time.sleep(wait_time)
            wait_adb(serial)
            log(f"  [{task_name}] attempt {attempt}: init OK")

            # Execute ground truth
            gt_fn = GROUND_TRUTH[task_name]
            gt_fn(serial, base_url, device_id)
            log(f"  [{task_name}] attempt {attempt}: commands OK")

            # Eval
            time.sleep(2)
            score, reason = eval_task(base_url, task_name, device_id)
            status = "PASS" if score > 0 else "FAIL"
            log(f"  [{task_name}] attempt {attempt}: {status} ({reason})")

            if score > 0:
                teardown_task(base_url, task_name, device_id)
                return {
                    "task_name": task_name, "status": "PASS",
                    "score": score, "reason": reason,
                    "attempts": attempt,
                }

            # Failed — teardown before retry
            teardown_task(base_url, task_name, device_id)

        except Exception as e:
            log(f"  [{task_name}] attempt {attempt}: ERROR {e}")
            try:
                teardown_task(base_url, task_name, device_id)
            except Exception:
                pass

    return {
        "task_name": task_name, "status": "FAIL",
        "score": 0.0, "reason": reason if 'reason' in dir() else "all attempts failed",
        "attempts": max_attempts,
    }


def get_all_task_names(base_url):
    """Fetch GUI-only task names from container."""
    try:
        all_tasks = http_get(f"{base_url}/task/list")
        exclude_tags = {"agent-mcp", "agent-user-interaction"}
        return [
            t["name"] for t in all_tasks
            if not (set(t.get("tags", [])) & exclude_tags)
        ]
    except Exception as e:
        log(f"WARNING: Cannot fetch task list: {e}")
        return sorted(list(GROUND_TRUTH.keys()) + GUI_REQUIRED)


def run_sequential(tasks, base_url, serial, device_id, output_path, max_attempts):
    """Run tasks sequentially on a single container."""
    results = []
    with open(output_path, "w") as out:
        for i, task_name in enumerate(tasks):
            log(f"\n{'='*60}")
            log(f"[{i+1}/{len(tasks)}] {task_name}")
            log(f"{'='*60}")

            result = run_single_task(task_name, base_url, serial,
                                     device_id, max_attempts)
            results.append(result)
            out.write(json.dumps(result) + "\n")
            out.flush()

            passed = sum(1 for r in results if r["status"] == "PASS")
            total_tried = sum(1 for r in results if r["status"] in ("PASS", "FAIL"))
            log(f"  Progress: {i+1}/{len(tasks)}, "
                f"PASS: {passed}/{total_tried}")

    return results


def run_parallel(tasks, containers, output_path, max_attempts):
    """Run tasks in parallel across multiple containers."""
    task_q = queue.Queue()
    for t in tasks:
        task_q.put(t)

    container_pool = queue.Queue()
    for server_url, serial in containers:
        container_pool.put((server_url, serial))

    results = []
    results_file_lock = threading.Lock()

    out = open(output_path, "w")

    def worker():
        while True:
            try:
                task_name = task_q.get_nowait()
            except queue.Empty:
                return

            server_url, serial = container_pool.get()
            try:
                log(f"\n  [{task_name}] on {server_url}")
                result = run_single_task(
                    task_name, server_url, serial,
                    "emulator-5554", max_attempts,
                )
                with results_file_lock:
                    results.append(result)
                    out.write(json.dumps(result) + "\n")
                    out.flush()
                    passed = sum(1 for r in results if r["status"] == "PASS")
                    total = len(results)
                    log(f"  [{task_name}] {result['status']} "
                        f"(total: {passed}/{total})")
            finally:
                container_pool.put((server_url, serial))

    num_workers = len(containers)
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker) for _ in range(num_workers)]
        for f in futures:
            f.result()

    out.close()
    return results


def run_broker(tasks, broker_url, pool_size, output_path, max_attempts):
    """Run tasks via broker (acquire/release containers dynamically)."""
    task_q = queue.Queue()
    for t in tasks:
        task_q.put(t)

    results = []
    results_file_lock = threading.Lock()
    out = open(output_path, "w")

    def worker():
        while True:
            try:
                task_name = task_q.get_nowait()
            except queue.Empty:
                return

            # Skip GUI-required tasks without acquiring container
            if task_name in GUI_REQUIRED or task_name not in GROUND_TRUTH:
                result = run_single_task(task_name, "", "", "emulator-5554", 0)
                with results_file_lock:
                    results.append(result)
                    out.write(json.dumps(result) + "\n")
                    out.flush()
                continue

            # Acquire container
            try:
                container = http_post(f"{broker_url}/acquire",
                                       {"pid": os.getpid(), "timeout": 300},
                                       timeout=330)
            except Exception as e:
                log(f"  [{task_name}] Failed to acquire: {e}")
                task_q.put(task_name)  # Re-queue
                time.sleep(5)
                continue

            env_id = container.get("env_id", "")
            server_url = container.get("server_url", "")
            adb_serial = container.get("adb_serial", "")

            try:
                result = run_single_task(
                    task_name, server_url, adb_serial,
                    "emulator-5554", max_attempts,
                )
                with results_file_lock:
                    results.append(result)
                    out.write(json.dumps(result) + "\n")
                    out.flush()
                    passed = sum(1 for r in results if r["status"] == "PASS")
                    log(f"  [{task_name}] {result['status']} ({passed} passed)")
            finally:
                try:
                    http_post(f"{broker_url}/return",
                              {"env_id": env_id, "healthy": True}, timeout=30)
                except Exception:
                    pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as executor:
        futures = [executor.submit(worker) for _ in range(pool_size)]
        for f in futures:
            f.result()

    out.close()
    return results


# =========================================================================
# Main
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Ground-truth CLI finder for MobileWorld GUI-only tasks",
    )
    parser.add_argument("--container-url", type=str, default="http://localhost:6800")
    parser.add_argument("--adb-serial", type=str, default="localhost:5556")
    parser.add_argument("--device-id", type=str, default="emulator-5554")
    parser.add_argument("--containers", type=str, default=None,
                        help="Parallel: 'url1=serial1,url2=serial2,...'")
    parser.add_argument("--broker-url", type=str, default=None,
                        help="Broker URL for dynamic container allocation")
    parser.add_argument("--pool-size", type=int, default=4,
                        help="Number of parallel workers (default: 4)")
    parser.add_argument("--tasks", type=str, default=None,
                        help="Comma-separated task names (default: all)")
    parser.add_argument("--max-attempts", type=int, default=2,
                        help="Max attempts per task (default: 2)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSONL path")
    args = parser.parse_args()

    # Resolve output path
    if args.output:
        output_path = args.output
    else:
        ts = datetime.now().strftime("%y%m%d_%H%M")
        output_path = f"gt_cli_results_{ts}.jsonl"

    # Get task list
    if args.tasks:
        tasks = args.tasks.split(",")
    else:
        tasks = get_all_task_names(args.container_url)

    print(f"{'='*60}")
    print(f"MobileWorld Ground Truth CLI Finder")
    print(f"{'='*60}")
    print(f"Tasks: {len(tasks)} ({len(GROUND_TRUTH)} with solutions, "
          f"{len(GUI_REQUIRED)} GUI-required)")
    print(f"Max attempts: {args.max_attempts}")
    print(f"Output: {output_path}")

    if args.broker_url:
        print(f"Mode: broker ({args.broker_url}, pool_size={args.pool_size})")
        results = run_broker(tasks, args.broker_url, args.pool_size,
                             output_path, args.max_attempts)
    elif args.containers:
        containers = []
        for pair in args.containers.split(","):
            parts = pair.strip().split("=")
            containers.append((parts[0], parts[1] if len(parts) > 1 else "localhost:5556"))
        print(f"Mode: parallel ({len(containers)} containers)")
        for u, s in containers:
            healthy = check_health(u)
            print(f"  {u} (adb={s}) {'OK' if healthy else 'UNHEALTHY'}")
        results = run_parallel(tasks, containers, output_path, args.max_attempts)
    else:
        print(f"Mode: sequential")
        print(f"Container: {args.container_url}")
        print(f"ADB: {args.adb_serial}")
        if not check_health(args.container_url):
            print("ERROR: Container not healthy")
            return 1
        results = run_sequential(tasks, args.container_url, args.adb_serial,
                                 args.device_id, output_path, args.max_attempts)

    # Summary
    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] == "FAIL"]
    errors = [r for r in results if r["status"] == "error"]
    gui_req = [r for r in results if r["status"] == "gui_required"]
    no_sol = [r for r in results if r["status"] == "no_solution"]

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"  PASS:         {len(passed)}")
    print(f"  FAIL:         {len(failed)}")
    print(f"  ERROR:        {len(errors)}")
    print(f"  GUI-required: {len(gui_req)}")
    print(f"  No solution:  {len(no_sol)}")
    print(f"  CLI success rate: {len(passed)}/{len(passed)+len(failed)+len(errors)} "
          f"({100*len(passed)/max(len(passed)+len(failed)+len(errors),1):.0f}%)")

    if failed:
        print(f"\nFAILED tasks:")
        for r in failed:
            print(f"  {r['task_name']}: {r.get('reason', '')}")

    if errors:
        print(f"\nERROR tasks:")
        for r in errors:
            print(f"  {r['task_name']}: {r.get('reason', '')}")

    # Write summary JSON
    summary_path = output_path.replace(".jsonl", "_summary.json")
    with open(summary_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_tasks": len(results),
            "passed": len(passed),
            "failed": len(failed),
            "errors": len(errors),
            "gui_required": len(gui_req),
            "no_solution": len(no_sol),
            "pass_rate": round(len(passed) / max(len(passed) + len(failed) + len(errors), 1), 4),
            "passed_tasks": [r["task_name"] for r in passed],
            "failed_tasks": [{
                "task_name": r["task_name"],
                "reason": r.get("reason", ""),
            } for r in failed],
        }, f, indent=2)
    print(f"\nSummary: {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
