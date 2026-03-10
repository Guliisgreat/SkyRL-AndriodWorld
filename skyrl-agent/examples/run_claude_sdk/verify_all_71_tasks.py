#!/usr/bin/env python3
"""
Verify all 71 ADB-solvable AndroidWorld tasks with scripted commands.

Usage:
    python verify_all_71_tasks.py --pool-size 4 --base-env-id 500
    python verify_all_71_tasks.py --pool-size 2 --tasks 3,4,5   # specific tasks
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

# ============================================================================
# Infrastructure (containers, HTTP)
# ============================================================================

def start_container(env_id: int, image: str) -> dict:
    server_port = 5000 + 2 * env_id
    emulator_port = 5574 + 2 * env_id
    grpc_port = emulator_port + 3000
    adb_server_port = 5037 + env_id
    name = f"verify_adb_{env_id}"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    log_dir = f"/tmp/verify_adb/env{env_id}/log"
    os.makedirs(log_dir, exist_ok=True)
    cmd = [
        "docker", "run", "-d", "--name", name, "--network", "host",
        "--device", "/dev/kvm", "-v", f"{log_dir}:/data/log",
        "-e", f"ENV_ID={env_id}", "-e", f"SERVER_PORT={server_port}",
        "-e", f"EMULATOR_PORT={emulator_port}", "-e", f"GRPC_PORT={grpc_port}",
        "-e", f"ADB_SERVER_PORT={adb_server_port}", "-e", "ENV_SNAPSHOT=clean",
        "-e", "ENV_SAMPLE_MODE=sequential", "-e", "ENV_SAVE_IMAGES=False",
        "-e", "ENV_TASK_FAMILY=android_world", "-e", "ENV_SKIP_SCREENSHOT=True",
        image,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start container {name}: {result.stderr}")
    return {"name": name, "env_id": env_id, "server_port": server_port,
            "url": f"http://localhost:{server_port}"}


def wait_for_healthy(container: dict, timeout: int = 300) -> bool:
    url = f"{container['url']}/health"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def stop_container(c: dict):
    subprocess.run(["docker", "rm", "-f", c["name"]], capture_output=True)


def http_post(base_url: str, endpoint: str, payload: dict, timeout: int = 60) -> dict:
    url = f"{base_url}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reset_task(base_url: str, task_id: int, seed: int) -> dict:
    return http_post(base_url, "/reset", {
        "seed": seed, "options": {"task_id": task_id, "go_home_on_reset": True}
    }, timeout=180)


# Per-task command recording
_current_task_commands: list[dict] = []

def adb(base_url: str, command: str, thought: str = "") -> str:
    """Execute ADB command, return command_output."""
    r = http_post(base_url, "/step_adb", {
        "command": command, "thought": thought or command
    })
    output = r.get("command_output", "")
    _current_task_commands.append({"type": "adb", "command": command, "output": output})
    return output


def finish(base_url: str, desc: str = "done") -> float:
    """Send FINISH, return reward."""
    r = http_post(base_url, "/step_adb", {
        "command": f"FINISH(content='{desc}')", "thought": "done"
    })
    _current_task_commands.append({"type": "finish", "status": "complete", "description": desc})
    return r.get("reward", 0.0)


def answer_and_finish(base_url: str, answer: str) -> float:
    """For IR tasks: set interaction_cache then finish."""
    http_post(base_url, "/step", {
        "action": {"action_type": "answer", "text": answer}, "thought": answer
    })
    r = http_post(base_url, "/step", {
        "action": {"action_type": "status", "goal_status": "complete"},
        "thought": "done"
    })
    _current_task_commands.append({"type": "answer_and_finish", "answer": answer})
    return r.get("reward", 0.0)


# ============================================================================
# SQLite helper
# ============================================================================

def sqlite_b64(base_url: str, db_path: str, sql: str) -> str:
    """Run sqlite3 with base64-encoded SQL. Handles ANY quoting (single quotes, %, etc.)."""
    import base64
    b64 = base64.b64encode(sql.encode()).decode()
    return adb(base_url, f"adb shell \"sh -c 'echo {b64} | base64 -d | sqlite3 {db_path}'\"")


# Alias for backwards compat
sqlite = sqlite_b64


# DB paths
BROCCOLI_DB = "/data/data/com.flauschcode.broccoli/databases/broccoli"
CALENDAR_DB = "/data/data/com.simplemobiletools.calendar.pro/databases/events.db"
EXPENSE_DB = "/data/data/com.arduia.expense/databases/accounting.db"
MARKOR_DIR = "/storage/emulated/0/Documents/Markor"
STORAGE = "/storage/emulated/0"

# Expense categories (from Pro Expense app)
EXPENSE_CATEGORIES = {
    "others": 1, "income": 2, "food": 3, "housing": 4, "social": 5,
    "entertainment": 6, "transportation": 7, "clothes": 8, "health care": 9,
    "education": 10, "donation": 11,
    # Common aliases
    "other": 1, "clothing": 8, "health": 9, "transport": 7,
}

# ============================================================================
# Task handlers — each returns (reward, log_lines)
# ============================================================================

# --- System Settings (14 tasks) ---

def task_system(base_url, task_text):
    log = []
    tx = task_text.lower()
    cmds = []

    # Split by "then"/"," to handle multi-action tasks like "Turn off WiFi, then enable bluetooth"
    clauses = re.split(r',\s*then\s+|,\s*|\bthen\b', tx)

    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue

        # WiFi
        if "wifi" in clause:
            if any(w in clause for w in ["turn on", "enable", "turn wifi on"]):
                cmds.append("adb shell svc wifi enable")
            elif any(w in clause for w in ["turn off", "disable", "turn wifi off"]):
                cmds.append("adb shell svc wifi disable")
        # Bluetooth
        if "bluetooth" in clause:
            if any(w in clause for w in ["turn on", "enable", "turn bluetooth on"]):
                cmds.append("adb shell svc bluetooth enable")
            elif any(w in clause for w in ["turn off", "disable", "turn bluetooth off"]):
                cmds.append("adb shell svc bluetooth disable")
        # Brightness
        if "brightness" in clause and "max" in clause:
            cmds.append("adb shell settings put system screen_brightness_mode 0")
            cmds.append("adb shell settings put system screen_brightness 255")
        if "brightness" in clause and "min" in clause:
            cmds.append("adb shell settings put system screen_brightness_mode 0")
            cmds.append("adb shell settings put system screen_brightness 1")
        # Contacts app
        if "open the contacts app" in clause or "open contacts" in clause:
            cmds.append("adb shell am start -n com.google.android.contacts/com.android.contacts.activities.PeopleActivity")

    # Fallback: if no clauses matched, try the whole text (simple single-action tasks)
    if not cmds:
        if "wifi" in tx and any(w in tx for w in ["turn on", "enable"]):
            cmds.append("adb shell svc wifi enable")
        elif "wifi" in tx and any(w in tx for w in ["turn off", "disable"]):
            cmds.append("adb shell svc wifi disable")
        if "bluetooth" in tx and any(w in tx for w in ["turn on", "enable"]):
            cmds.append("adb shell svc bluetooth enable")
        elif "bluetooth" in tx and any(w in tx for w in ["turn off", "disable"]):
            cmds.append("adb shell svc bluetooth disable")
        if "brightness" in tx and "max" in tx:
            cmds.append("adb shell settings put system screen_brightness_mode 0")
            cmds.append("adb shell settings put system screen_brightness 255")
        if "brightness" in tx and "min" in tx:
            cmds.append("adb shell settings put system screen_brightness_mode 0")
            cmds.append("adb shell settings put system screen_brightness 1")
        if "open the contacts app" in tx or "open contacts" in tx:
            cmds.append("adb shell am start -n com.google.android.contacts/com.android.contacts.activities.PeopleActivity")

    for cmd in cmds:
        out = adb(base_url, cmd)
        log.append(f"  {cmd} → {out.strip()[:80]}")

    reward = finish(base_url, "Settings applied")
    return reward, log


# --- Delete File Operations ---

def task_12_delete_all_markor(base_url, task_text):
    log = []
    out = adb(base_url, f"adb shell ls {MARKOR_DIR}/")
    log.append(f"  ls: {out.strip()[:100]}")
    # Delete all files (various extensions)
    for ext in ["*.md", "*.txt", "*"]:
        adb(base_url, f"adb shell rm -f {MARKOR_DIR}/{ext}")
    out = adb(base_url, f"adb shell ls {MARKOR_DIR}/")
    log.append(f"  after: {out.strip()[:100]}")
    reward = finish(base_url, "Deleted all notes")
    return reward, log


def task_13_delete_markor_note(base_url, task_text):
    log = []
    # Extract note name from task text
    m = re.search(r'named?\s+(\S+)', task_text)
    note_name = m.group(1).rstrip('.') if m else ""
    log.append(f"  target: {note_name}")

    out = adb(base_url, f"adb shell ls {MARKOR_DIR}/")
    log.append(f"  ls: {out.strip()[:120]}")

    # Try exact name, then with .md, then with .txt
    for suffix in ["", ".md", ".txt"]:
        adb(base_url, f"adb shell rm -f {MARKOR_DIR}/{note_name}{suffix}")

    out = adb(base_url, f"adb shell ls {MARKOR_DIR}/")
    log.append(f"  after: {out.strip()[:120]}")
    reward = finish(base_url, f"Deleted {note_name}")
    return reward, log


def task_23_delete_newest_markor(base_url, task_text):
    log = []
    # List files sorted by modification time (newest first)
    out = adb(base_url, f'adb shell "ls -t {MARKOR_DIR}/"')
    log.append(f"  ls -t: {out.strip()[:150]}")
    files = [f.strip() for f in out.strip().split("\n") if f.strip() and f.strip() != "$"]
    # Filter out the ls command echo
    files = [f for f in files if not f.startswith("$") and not f.startswith("ls")]
    if files:
        newest = files[0]
        log.append(f"  newest: {newest}")
        adb(base_url, f"adb shell rm -f '{MARKOR_DIR}/{newest}'")
    reward = finish(base_url, "Deleted newest note")
    return reward, log


def task_62_delete_file(base_url, task_text):
    log = []
    # "Delete the file backup_funny_zebra.mp4 from the Android filesystem located in the Movies folder"
    m = re.search(r'file\s+(\S+)\s+from', task_text)
    filename = m.group(1) if m else "backup_funny_zebra.mp4"
    path = f"{STORAGE}/Movies/{filename}"
    adb(base_url, f"adb shell rm -f {path}")
    log.append(f"  rm {path}")
    reward = finish(base_url, f"Deleted {filename}")
    return reward, log


# --- Delete SQLite ---

def task_delete_recipes(base_url, task_text):
    log = []
    # Extract recipe names from text like "Delete the following recipes from Broccoli app: X, Y, Z."
    m = re.search(r'Broccoli app:\s*(.+?)\.?\s*$', task_text)
    if m:
        names = [n.strip() for n in m.group(1).split(",")]
    else:
        names = []
    log.append(f"  recipes to delete: {names}")

    for name in names:
        escaped = name.replace("'", "''")
        sqlite_b64(base_url, BROCCOLI_DB, f"DELETE FROM recipes WHERE title='{escaped}'")
        log.append(f"  deleted: {name}")

    reward = finish(base_url, "Deleted recipes")
    return reward, log


def task_5_delete_calendar_on_date(base_url, task_text):
    log = []
    # "delete all the calendar events on 2023-10-25"
    m = re.search(r'(\d{4}-\d{2}-\d{2})', task_text)
    if m:
        from datetime import datetime, timezone
        dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        ts_start = int(dt.timestamp())
        ts_end = ts_start + 86400
    else:
        ts_start, ts_end = 0, 0

    out = sqlite_b64(base_url, CALENDAR_DB,
        f"SELECT id, title FROM events WHERE start_ts >= {ts_start} AND start_ts < {ts_end}")
    log.append(f"  events on date: {out.strip()[:150]}")

    sqlite_b64(base_url, CALENDAR_DB,
        f"DELETE FROM events WHERE start_ts >= {ts_start} AND start_ts < {ts_end}")
    log.append(f"  deleted events for {m.group(1) if m else '?'}")
    reward = finish(base_url, "Deleted events")
    return reward, log


def task_6_delete_specific_calendar_event(base_url, task_text):
    log = []
    # "delete the calendar event on 2023-10-25 at 4h with the title 'Review session for Project X'"
    m_date = re.search(r'(\d{4}-\d{2}-\d{2})', task_text)
    m_title = re.search(r"title '([^']+)'", task_text)

    if m_date:
        from datetime import datetime, timezone
        dt = datetime.strptime(m_date.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        ts_start = int(dt.timestamp())
        ts_end = ts_start + 86400
    else:
        ts_start, ts_end = 0, 0

    title = m_title.group(1) if m_title else ""
    escaped_title = title.replace("'", "''")

    sqlite_b64(base_url, CALENDAR_DB,
        f"DELETE FROM events WHERE title='{escaped_title}' AND start_ts >= {ts_start} AND start_ts < {ts_end}")
    log.append(f"  deleted '{title}' on {m_date.group(1) if m_date else '?'}")
    reward = finish(base_url, "Deleted event")
    return reward, log


def task_61_delete_events_this_wednesday(base_url, task_text):
    log = []
    # Device date is Oct 15, 2023 (Sunday). This Wednesday = Oct 18.
    # Get device date to be safe
    date_out = adb(base_url, "adb shell date +%s")
    now = 0
    for line in date_out.strip().split("\n"):
        line = line.strip()
        if line.isdigit():
            now = int(line)
            break

    # Find this Wednesday's timestamp range
    from datetime import datetime, timezone, timedelta
    dt_now = datetime.fromtimestamp(now, tz=timezone.utc)
    # Wednesday is weekday 2 (Monday=0)
    days_until_wed = (2 - dt_now.weekday()) % 7
    if days_until_wed == 0 and dt_now.weekday() != 2:
        days_until_wed = 7
    wed = dt_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_wed)
    ts_start = int(wed.timestamp())
    ts_end = ts_start + 86400
    log.append(f"  Wednesday: {wed.strftime('%Y-%m-%d')}, ts=[{ts_start}, {ts_end})")

    out = sqlite_b64(base_url, CALENDAR_DB,
        f"SELECT id, title FROM events WHERE start_ts >= {ts_start} AND start_ts < {ts_end}")
    log.append(f"  events: {out.strip()[:150]}")

    sqlite_b64(base_url, CALENDAR_DB,
        f"DELETE FROM events WHERE start_ts >= {ts_start} AND start_ts < {ts_end}")
    reward = finish(base_url, "Deleted Wednesday events")
    return reward, log


def task_delete_expenses(base_url, task_text):
    log = []
    # "Delete the following expenses from pro expense: X, Y, Z."
    m = re.search(r'pro expense:\s*(.+?)\.?\s*$', task_text)
    if m:
        names = [n.strip() for n in m.group(1).split(",")]
    else:
        names = []

    for name in names:
        escaped = name.replace("'", "''")
        sqlite_b64(base_url, EXPENSE_DB, f"DELETE FROM expense WHERE name='{escaped}'")
        log.append(f"  deleted: {name}")

    reward = finish(base_url, "Deleted expenses")
    return reward, log


def task_90_delete_broccoli_directions(base_url, task_text):
    log = []
    # "Delete the recipes from Broccoli app that use broccoli in the directions."
    out = sqlite_b64(base_url, BROCCOLI_DB,
        "SELECT recipeId, title FROM recipes WHERE directions LIKE '%broccoli%'")
    log.append(f"  matching: {out.strip()[:200]}")

    sqlite_b64(base_url, BROCCOLI_DB,
        "DELETE FROM recipes WHERE directions LIKE '%broccoli%'")

    out = sqlite_b64(base_url, BROCCOLI_DB, "SELECT recipeId, title FROM recipes")
    log.append(f"  remaining: {out.strip()[:200]}")
    reward = finish(base_url, "Deleted recipes with broccoli in directions")
    return reward, log


# --- Dedup ---

def task_dedup_recipes(base_url, task_text):
    log = []
    out = sqlite_b64(base_url, BROCCOLI_DB, "SELECT recipeId, title FROM recipes")
    log.append(f"  before: {out.strip()[:200]}")

    sqlite_b64(base_url, BROCCOLI_DB,
        "DELETE FROM recipes WHERE recipeId NOT IN "
        "(SELECT MIN(recipeId) FROM recipes GROUP BY title, description, servings, preparationTime, ingredients, directions)")
    # Also clean the categories join table
    sqlite_b64(base_url, BROCCOLI_DB,
        "DELETE FROM recipes_with_categories WHERE recipeId NOT IN (SELECT recipeId FROM recipes)")

    out = sqlite_b64(base_url, BROCCOLI_DB, "SELECT recipeId, title FROM recipes")
    log.append(f"  after: {out.strip()[:200]}")
    reward = finish(base_url, "Deduplicated recipes")
    return reward, log


def task_dedup_expenses(base_url, task_text):
    log = []
    out = sqlite_b64(base_url, EXPENSE_DB, "SELECT expense_id, name, amount FROM expense")
    log.append(f"  before: {out.strip()[:200]}")

    sqlite_b64(base_url, EXPENSE_DB,
        "DELETE FROM expense WHERE expense_id NOT IN "
        "(SELECT MIN(expense_id) FROM expense GROUP BY name, amount, category, note, created_date, modified_date)")

    out = sqlite_b64(base_url, EXPENSE_DB, "SELECT expense_id, name, amount FROM expense")
    log.append(f"  after: {out.strip()[:200]}")
    reward = finish(base_url, "Deduplicated expenses")
    return reward, log


# --- Create File ---

def task_22_create_folder(base_url, task_text):
    log = []
    m = re.search(r'named\s+(\S+)', task_text)
    folder = m.group(1).rstrip('.') if m else "folder"
    adb(base_url, f"adb shell mkdir -p {MARKOR_DIR}/{folder}")
    log.append(f"  mkdir {folder}")
    reward = finish(base_url, f"Created folder {folder}")
    return reward, log


def task_create_note(base_url, task_text):
    log = []
    # "Create a new note in Markor named X.md with the following text: Y"
    m_name = re.search(r'named\s+(\S+)', task_text)
    note_name = m_name.group(1).rstrip('.') if m_name else "note.md"

    m_text = re.search(r'(?:following text|text):\s*(.+)', task_text, re.DOTALL)
    content = m_text.group(1).strip() if m_text else ""

    # If there's a Share/SMS instruction after the text, strip it
    share_idx = content.lower().find('. share ')
    if share_idx > 0:
        content = content[:share_idx + 1]  # keep the period before "Share"

    # Check if the task also asks to share via SMS
    share_sms = "sms" in task_text.lower() and "share" in task_text.lower()

    # Ensure Markor directory exists and write file using sh -c + base64
    import base64
    adb(base_url, f"adb shell mkdir -p {MARKOR_DIR}")
    b64 = base64.b64encode(content.encode()).decode()
    adb(base_url, f"adb shell \"sh -c 'echo {b64} | base64 -d > {MARKOR_DIR}/{note_name}'\"")
    log.append(f"  created {note_name}: {content[:60]}")

    if share_sms:
        # Extract phone number
        m_phone = re.search(r'(\+\d+)', task_text)
        phone = m_phone.group(1) if m_phone else ""
        if phone:
            try:
                import base64 as b64mod
                # Open SMS compose WITHOUT body text (avoids shell quoting issues with special chars like ')
                adb(base_url, f'adb shell am start -a android.intent.action.SENDTO -d sms:{phone} com.simplemobiletools.smsmessenger')
                time.sleep(3)
                # Dump UI to find message input field
                a11y = adb(base_url, "adb shell uiautomator dump /sdcard/window_dump.xml && adb shell cat /sdcard/window_dump.xml")
                # Find message input
                msg_input = re.search(r'resource-id="[^"]*message[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', a11y, re.IGNORECASE)
                if not msg_input:
                    msg_input = re.search(r'class="android.widget.EditText"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', a11y)
                if msg_input:
                    mx = (int(msg_input.group(1)) + int(msg_input.group(3))) // 2
                    my = (int(msg_input.group(2)) + int(msg_input.group(4))) // 2
                    adb(base_url, f"adb shell input tap {mx} {my}")
                    time.sleep(1)
                # Type the message via base64-decoded script (handles special chars like ')
                msg_b64 = b64mod.b64encode(content.encode()).decode()
                script = f'#!/system/bin/sh\nMSG=$(echo {msg_b64} | base64 -d)\ninput text "$MSG"\n'
                script_b64 = b64mod.b64encode(script.encode()).decode()
                adb(base_url, f"adb shell \"sh -c 'echo {script_b64} | base64 -d > /sdcard/type_script.sh'\"")
                adb(base_url, 'adb shell sh /sdcard/type_script.sh')
                time.sleep(1)
                # Find and tap send button
                a11y = adb(base_url, "adb shell uiautomator dump /sdcard/window_dump.xml && adb shell cat /sdcard/window_dump.xml")
                send_match = re.search(r'content-desc="Send"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', a11y)
                if not send_match:
                    send_match = re.search(r'resource-id="[^"]*send[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', a11y, re.IGNORECASE)
                if send_match:
                    x = (int(send_match.group(1)) + int(send_match.group(3))) // 2
                    y = (int(send_match.group(2)) + int(send_match.group(4))) // 2
                    adb(base_url, f"adb shell input tap {x} {y}")
                    log.append(f"  sent SMS to {phone}")
                else:
                    log.append(f"  could not find send button")
            except Exception as e:
                log.append(f"  SMS send error: {e}")

    reward = finish(base_url, f"Created {note_name}")
    return reward, log


# --- Edit File ---

def task_24_edit_note(base_url, task_text):
    log = []
    # "Edit note_ujOeH.txt in Markor. Replace the text with ..."
    m_name = re.search(r'Edit\s+(\S+)\s+in Markor', task_text)
    note_name = m_name.group(1) if m_name else ""

    m_content = re.search(r'Replace the text with\s+(.*)', task_text, re.DOTALL)
    content = m_content.group(1).strip() if m_content else ""

    # Write content using sh -c + base64 to avoid shell quoting issues
    import base64
    b64 = base64.b64encode(content.encode()).decode()
    adb(base_url, f"adb shell \"sh -c 'echo {b64} | base64 -d > {MARKOR_DIR}/{note_name}'\"")
    log.append(f"  wrote to {note_name}: {content[:60]}")
    reward = finish(base_url, f"Edited {note_name}")
    return reward, log


def task_51_update_and_rename(base_url, task_text):
    log = []
    # "Update the content of X.md to "Y" in Markor and change its name to Z.md."
    m_src = re.search(r'content of\s+(\S+)\s+to', task_text)
    m_content = re.search(r'to "([^"]+)"', task_text)
    m_dst = re.search(r'name to\s+(\S+)', task_text)

    src = m_src.group(1).rstrip('.') if m_src else ""
    content = m_content.group(1) if m_content else ""
    dst = m_dst.group(1).rstrip('.') if m_dst else ""

    import base64
    adb(base_url, f"adb shell mkdir -p {MARKOR_DIR}")
    b64 = base64.b64encode(content.encode()).decode()
    adb(base_url, f"adb shell \"sh -c 'echo {b64} | base64 -d > {MARKOR_DIR}/{src}'\"")
    if dst and dst != src:
        adb(base_url, f"adb shell mv {MARKOR_DIR}/{src} {MARKOR_DIR}/{dst}")
    log.append(f"  {src} → {dst}, content: {content[:40]}")
    reward = finish(base_url, f"Updated and renamed")
    return reward, log


def task_69_prepend_and_rename(base_url, task_text):
    log = []
    # "Update the Markor note X.md by adding the following text, along with a new blank line
    #  before the existing content: "Y", and rename it to Z.txt."
    m_src = re.search(r'note\s+(\S+)\s+by', task_text)
    m_text = re.search(r'"([^"]+)"', task_text)
    m_dst = re.search(r'rename it to\s+(\S+)', task_text)

    src = m_src.group(1).rstrip('.') if m_src else ""
    new_text = m_text.group(1) if m_text else ""
    dst = m_dst.group(1).rstrip('.') if m_dst else ""

    # Read existing content — preserve trailing newline (evaluator expects it)
    existing = adb(base_url, f"adb shell cat {MARKOR_DIR}/{src}")
    # Remove the command echo line but keep raw content including trailing newline
    lines = existing.split("\n")
    existing_clean = "\n".join(l for l in lines if not l.startswith("$"))
    # Strip leading whitespace only, preserve trailing content exactly
    existing_clean = existing_clean.lstrip()

    # Prepend new text + blank line before existing content
    combined = new_text + "\n\n" + existing_clean
    import base64
    b64 = base64.b64encode(combined.encode()).decode()
    adb(base_url, f"adb shell \"sh -c 'echo {b64} | base64 -d > {MARKOR_DIR}/{src}'\"")

    if dst and dst != src:
        adb(base_url, f"adb shell mv {MARKOR_DIR}/{src} {MARKOR_DIR}/{dst}")

    log.append(f"  prepended to {src}, renamed to {dst}")
    reward = finish(base_url, "Updated note")
    return reward, log


def task_87_merge_notes(base_url, task_text):
    log = []
    # "Merge the contents of Markor notes X.md, Y.md and Z.md ... into a new Markor note named W"
    m_notes = re.findall(r'(\w+(?:\.\w+)?\.(?:md|txt))', task_text)
    m_dest = re.search(r'named\s+(\S+)', task_text)
    dest = m_dest.group(1).rstrip('.') if m_dest else "merged"

    # If dest doesn't have extension, keep as-is (the task says "named IizHJIQg")
    contents = []
    for note in m_notes:
        if note == dest or note == dest + ".md":
            continue
        out = adb(base_url, f"adb shell cat {MARKOR_DIR}/{note}")
        # Clean command echo
        clean = "\n".join(l for l in out.strip().split("\n") if not l.startswith("$"))
        contents.append(clean)
        log.append(f"  read {note}: {clean[:50]}")

    merged = "\n\n".join(contents)
    import base64
    adb(base_url, f"adb shell mkdir -p {MARKOR_DIR}")
    b64 = base64.b64encode(merged.encode()).decode()
    adb(base_url, f"adb shell \"sh -c 'echo {b64} | base64 -d > {MARKOR_DIR}/{dest}'\"")
    log.append(f"  wrote merged to {dest}")
    reward = finish(base_url, "Merged notes")
    return reward, log


# --- Move File ---

def task_54_move_markor_note(base_url, task_text):
    log = []
    # "In Markor, move the note X.md from FolderA to FolderB."
    m_note = re.search(r'note\s+(\S+)\s+from', task_text)
    m_from = re.search(r'from\s+(\S+)\s+to', task_text)
    m_to = re.search(r'to\s+(\S+)', task_text)

    note = m_note.group(1).rstrip('.') if m_note else ""
    from_dir = m_from.group(1).rstrip('.') if m_from else ""
    to_dir = m_to.group(1).rstrip('.') if m_to else ""

    adb(base_url, f"adb shell mkdir -p {MARKOR_DIR}/{to_dir}")
    adb(base_url, f"adb shell mv {MARKOR_DIR}/{from_dir}/{note} {MARKOR_DIR}/{to_dir}/{note}")
    log.append(f"  moved {note}: {from_dir} → {to_dir}")
    reward = finish(base_url, "Moved note")
    return reward, log


def task_63_move_file(base_url, task_text):
    log = []
    # "Move the file X from Movies ... to the DCIM"
    m_file = re.search(r'file\s+(\S+)\s+from', task_text)
    filename = m_file.group(1) if m_file else ""

    m_from = re.search(r'from\s+(\w+)', task_text)
    m_to = re.search(r'to the\s+(\w+)', task_text)
    from_dir = m_from.group(1) if m_from else "Movies"
    to_dir = m_to.group(1) if m_to else "DCIM"

    src = f"{STORAGE}/{from_dir}/{filename}"
    dst_dir = f"{STORAGE}/{to_dir}"
    adb(base_url, f"adb shell mkdir -p {dst_dir}")
    adb(base_url, f"adb shell mv {src} {dst_dir}/{filename}")
    log.append(f"  moved {filename}: {from_dir} → {to_dir}")
    reward = finish(base_url, f"Moved {filename}")
    return reward, log


# --- Create SQLite entries ---

def task_add_expenses(base_url, task_text):
    log = []
    # Parse expenses from multi-line task text
    expenses = []
    current = {}
    for line in task_text.split("\n"):
        line = line.strip()
        if line.startswith("Expense:"):
            if current:
                expenses.append(current)
            current = {"name": line.split(":", 1)[1].strip()}
        elif line.startswith("amount_dollars:"):
            val = line.split(":", 1)[1].strip().replace("$", "")
            current["amount"] = int(round(float(val) * 100))
        elif line.startswith("category_name:"):
            cat_name = line.split(":", 1)[1].strip().lower()
            current["category"] = EXPENSE_CATEGORIES.get(cat_name, 0)
        elif line.startswith("note:"):
            current["note"] = line.split(":", 1)[1].strip()
    if current and "name" in current:
        expenses.append(current)

    log.append(f"  parsed {len(expenses)} expenses")

    now_ms = int(time.time()) * 1000
    for exp in expenses:
        name = exp.get("name", "").replace("'", "''")
        amount = exp.get("amount", 0)
        category = exp.get("category", 0)
        note = exp.get("note", "").replace("'", "''")
        sqlite_b64(base_url, EXPENSE_DB,
            f"INSERT INTO expense (name, amount, category, note, created_date, modified_date) "
            f"VALUES ('{name}', {amount}, {category}, '{note}', {now_ms}, {now_ms})")
        log.append(f"  added: {exp['name']} ${amount/100:.2f}")

    reward = finish(base_url, "Added expenses")
    return reward, log


def task_add_recipes(base_url, task_text):
    log = []
    recipes = []
    current = {}
    for line in task_text.split("\n"):
        line = line.strip()
        if line.startswith("Recipe:"):
            if current and "title" in current:
                recipes.append(current)
            current = {"title": line.split(":", 1)[1].strip()}
        elif line.startswith("description:"):
            current["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("servings:"):
            current["servings"] = line.split(":", 1)[1].strip()
        elif line.startswith("preparationTime:"):
            current["preparationTime"] = line.split(":", 1)[1].strip()
        elif line.startswith("ingredients:"):
            current["ingredients"] = line.split(":", 1)[1].strip()
        elif line.startswith("directions:"):
            current["directions"] = line.split(":", 1)[1].strip()
    if current and "title" in current:
        recipes.append(current)

    log.append(f"  parsed {len(recipes)} recipes")

    for r in recipes:
        title = r.get("title", "").replace("'", "''")
        desc = r.get("description", "").replace("'", "''")
        servings = r.get("servings", "").replace("'", "''")
        prep = r.get("preparationTime", "").replace("'", "''")
        ingr = r.get("ingredients", "").replace("'", "''")
        dirs = r.get("directions", "").replace("'", "''")
        sqlite_b64(base_url, BROCCOLI_DB,
            f"INSERT INTO recipes (title, description, servings, preparationTime, ingredients, directions, imageName, source, favorite) "
            f"VALUES ('{title}', '{desc}', '{servings}', '{prep}', '{ingr}', '{dirs}', '', '', 0)")
        log.append(f"  added recipe: {r['title'][:40]}")

    reward = finish(base_url, "Added recipes")
    return reward, log


def _get_device_date(base_url):
    """Get device current date as datetime."""
    from datetime import datetime, timezone
    out = adb(base_url, "adb shell date +%s")
    now = 0
    for line in out.strip().split("\n"):
        line = line.strip()
        if line.isdigit():
            now = int(line)
            break
    return datetime.fromtimestamp(now, tz=timezone.utc), now


def _get_day_ts(base_url, day_desc):
    """Get start-of-day timestamp for a relative day description."""
    from datetime import datetime, timezone, timedelta
    dt_now, now_ts = _get_device_date(base_url)

    day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
               "friday": 4, "saturday": 5, "sunday": 6}

    if day_desc == "tomorrow":
        target = dt_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif day_desc.startswith("two weeks"):
        target = dt_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(weeks=2)
    elif day_desc.startswith("this "):
        weekday_name = day_desc.replace("this ", "").lower()
        target_wd = day_map.get(weekday_name, 0)
        days = (target_wd - dt_now.weekday()) % 7
        if days == 0:
            days = 7
        target = dt_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
    elif day_desc.startswith("20"):  # explicit date like 2023-10-25
        target = datetime.strptime(day_desc, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        target = dt_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    return int(target.timestamp())


def task_create_calendar_event(base_url, task_text):
    log = []
    # Parse event details
    m_title = re.search(r"titled?\s+'([^']+)'", task_text)
    m_desc = re.search(r"description\s+(?:should be\s+)?'([^']+)'", task_text)
    m_duration = re.search(r'last(?:s|ing)? (?:for )?(\d+) min', task_text)
    m_date = re.search(r'on (\d{4}-\d{2}-\d{2})', task_text)
    m_hour = re.search(r'at (\d+)h', task_text)
    m_recurring = re.search(r'recurs\s+(weekly|daily|monthly|yearly)', task_text, re.IGNORECASE)

    title = m_title.group(1) if m_title else "Event"
    desc = m_desc.group(1) if m_desc else ""
    duration_min = int(m_duration.group(1)) if m_duration else 60
    hour = int(m_hour.group(1)) if m_hour else 4

    # Determine start date
    tx_lower = task_text.lower()
    if m_date:
        day_ts = _get_day_ts(base_url, m_date.group(1))
    elif "tomorrow" in tx_lower:
        day_ts = _get_day_ts(base_url, "tomorrow")
    elif "this wednesday" in tx_lower:
        day_ts = _get_day_ts(base_url, "this wednesday")
    elif "this friday" in tx_lower:
        day_ts = _get_day_ts(base_url, "this friday")
    elif "two weeks" in tx_lower:
        day_ts = _get_day_ts(base_url, "two weeks")
    else:
        day_ts = _get_day_ts(base_url, "tomorrow")

    start_ts = day_ts + hour * 3600
    end_ts = start_ts + duration_min * 60

    # Recurring?
    repeat_interval = 0
    repeat_limit = 0
    repeat_rule = 0
    if m_recurring:
        freq = m_recurring.group(1).lower()
        if freq == "weekly":
            repeat_interval = 604800  # 7 days in seconds
            # Simple Calendar Pro uses day-of-week bitmask: Mon=1, Tue=2, Wed=4, ...
            from datetime import datetime, timezone
            dt_start = datetime.fromtimestamp(start_ts, tz=timezone.utc)
            iso_dow = dt_start.isoweekday()  # 1=Mon, 7=Sun
            repeat_rule = 1 << (iso_dow - 1)
        elif freq == "daily":
            repeat_interval = 86400

    escaped_title = title.replace("'", "''")
    escaped_desc = desc.replace("'", "''")

    sqlite_b64(base_url, CALENDAR_DB,
        f"INSERT INTO events (start_ts, end_ts, title, location, description, "
        f"reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, "
        f"reminder_1_type, reminder_2_type, reminder_3_type, "
        f"repeat_interval, repeat_rule, repeat_limit, repetition_exceptions, "
        f"attendees, import_id, time_zone, flags, event_type, parent_id, "
        f"last_updated, source, availability, color, type) "
        f"VALUES ({start_ts}, {end_ts}, '{escaped_title}', '', '{escaped_desc}', "
        f"-1, -1, -1, 0, 0, 0, "
        f"{repeat_interval}, {repeat_rule}, 0, '[]', "
        f"'', '', 'UTC', 0, 1, 0, "
        f"0, 'imported-ics', 0, 0, 0)")

    log.append(f"  created: '{title}' at ts={start_ts}, duration={duration_min}m, repeat={repeat_interval}")
    reward = finish(base_url, f"Created event '{title}'")
    return reward, log


# --- SMS ---

def task_67_send_sms(base_url, task_text):
    log = []
    m_phone = re.search(r'to\s+(\+\d+)', task_text)
    m_msg = re.search(r'message:\s*(.+?)\.?\s*$', task_text)
    phone = m_phone.group(1) if m_phone else ""
    msg = m_msg.group(1).strip() if m_msg else ""

    escaped = msg.replace('"', '\\"')
    adb(base_url, f'adb shell "am start -a android.intent.action.SENDTO -d sms:{phone} --es sms_body \\"{escaped}\\" com.simplemobiletools.smsmessenger"')
    time.sleep(3)

    # Find send button
    a11y = adb(base_url, "adb shell uiautomator dump /sdcard/window_dump.xml && adb shell cat /sdcard/window_dump.xml")
    send_match = re.search(r'content-desc="Send"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', a11y)
    if not send_match:
        send_match = re.search(r'resource-id="[^"]*send[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', a11y, re.IGNORECASE)
    if send_match:
        x = (int(send_match.group(1)) + int(send_match.group(3))) // 2
        y = (int(send_match.group(2)) + int(send_match.group(4))) // 2
        adb(base_url, f"adb shell input tap {x} {y}")
        log.append(f"  sent SMS to {phone}: {msg}")
    else:
        log.append(f"  could not find send button")

    time.sleep(1)
    reward = finish(base_url, f"Sent SMS")
    return reward, log


# --- IR Queries (Calendar) ---

def _get_weekday_ts_range(base_url, weekday_name):
    """Get (start_ts, end_ts) for the UPCOMING instance of the given weekday."""
    from datetime import datetime, timezone, timedelta
    dt_now, _ = _get_device_date(base_url)
    day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
               "friday": 4, "saturday": 5, "sunday": 6}
    target_wd = day_map.get(weekday_name.lower(), 0)
    # Find the NEXT occurrence (or today if it's that weekday)
    days_diff = (target_wd - dt_now.weekday()) % 7
    if days_diff == 0:
        days_diff = 0  # today IS the target weekday — use today
    target = dt_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_diff)
    return int(target.timestamp()), int(target.timestamp()) + 86400


def task_ir_calendar(base_url, task_text, task_id):
    log = []
    tx = task_text.lower()
    from datetime import datetime, timezone, timedelta

    dt_now, now_ts = _get_device_date(base_url)

    if task_id == 92:
        # Next upcoming event
        out = sqlite_b64(base_url, CALENDAR_DB,
            f"SELECT title FROM events WHERE start_ts > {now_ts} ORDER BY start_ts ASC LIMIT 1")
        answer = out.strip().split("\n")[0].strip() if out.strip() else "No events"

    elif task_id == 91:
        # Events on Tuesday
        ts_s, ts_e = _get_weekday_ts_range(base_url, "tuesday")
        out = sqlite_b64(base_url, CALENDAR_DB,
            f"SELECT title FROM events WHERE start_ts >= {ts_s} AND start_ts < {ts_e} ORDER BY start_ts")
        titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        answer = ", ".join(titles) if titles else "No events"

    elif task_id == 93:
        # Schedule for Friday at 10:00am
        ts_s, _ = _get_weekday_ts_range(base_url, "friday")
        target_ts = ts_s + 10 * 3600  # 10:00 AM
        # Events that overlap with 10:00am (start <= 10am < end)
        out = sqlite_b64(base_url, CALENDAR_DB,
            f"SELECT title FROM events WHERE start_ts <= {target_ts} AND end_ts > {target_ts}")
        titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        answer = ", ".join(titles) if titles else "No events"

    elif task_id == 94:
        # Events October 20
        from datetime import datetime as dt2
        oct20 = int(datetime(2023, 10, 20, tzinfo=timezone.utc).timestamp())
        out = sqlite_b64(base_url, CALENDAR_DB,
            f"SELECT title FROM events WHERE start_ts >= {oct20} AND start_ts < {oct20 + 86400} ORDER BY start_ts")
        titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        answer = ", ".join(titles) if titles else "No events"

    elif task_id == 95:
        # When is next meeting with Emily
        out = sqlite_b64(base_url, CALENDAR_DB,
            f"SELECT start_ts FROM events WHERE title LIKE '%Emily%' AND start_ts > {now_ts} ORDER BY start_ts LIMIT 1")
        ts_val = out.strip().split("\n")[0].strip() if out.strip() else ""
        if ts_val and ts_val.isdigit():
            dt_event = datetime.fromtimestamp(int(ts_val), tz=timezone.utc)
            # Task asks for 24-hour format: <month name> <day> <year> <HH>:<MM>
            answer = f"{dt_event.strftime('%B')} {dt_event.day} {dt_event.year} {dt_event.hour}:{dt_event.strftime('%M')}"
        else:
            answer = "No meeting found"

    elif task_id == 96:
        # Location of Coding challenge event
        out = sqlite_b64(base_url, CALENDAR_DB,
            "SELECT location FROM events WHERE title LIKE '%Coding challenge%' LIMIT 1")
        answer = out.strip().split("\n")[0].strip() if out.strip() else "No location"

    elif task_id == 97:
        # Events in next week (Monday to Sunday)
        # Find next Monday
        days_to_mon = (0 - dt_now.weekday()) % 7
        if days_to_mon == 0:
            days_to_mon = 7
        mon = dt_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_to_mon)
        sun_end = mon + timedelta(days=7)
        ts_s = int(mon.timestamp())
        ts_e = int(sun_end.timestamp())
        out = sqlite_b64(base_url, CALENDAR_DB,
            f"SELECT title FROM events WHERE start_ts >= {ts_s} AND start_ts < {ts_e} ORDER BY start_ts")
        titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        answer = ", ".join(titles) if titles else "No events"

    elif task_id == 98:
        # First event after 10:30am Friday — search from 10:30 onward (no upper bound)
        ts_s, ts_e = _get_weekday_ts_range(base_url, "friday")
        target_ts = ts_s + 10 * 3600 + 30 * 60
        out = sqlite_b64(base_url, CALENDAR_DB,
            f"SELECT title FROM events WHERE start_ts >= {target_ts} ORDER BY start_ts LIMIT 1")
        answer = out.strip().split("\n")[0].strip() if out.strip() else "No events"

    elif task_id == 99:
        # Events between 12pm and 8pm Tuesday
        ts_s, _ = _get_weekday_ts_range(base_url, "tuesday")
        ts_12 = ts_s + 12 * 3600
        ts_20 = ts_s + 20 * 3600
        out = sqlite_b64(base_url, CALENDAR_DB,
            f"SELECT title FROM events WHERE start_ts >= {ts_12} AND start_ts < {ts_20} ORDER BY start_ts")
        titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        answer = ", ".join(titles) if titles else "No events"

    else:
        answer = "Unknown query"

    log.append(f"  answer: {answer[:100]}")
    reward = answer_and_finish(base_url, answer)
    return reward, log


# --- IR Queries (Tasks app) ---

def task_ir_tasks_app(base_url, task_text, task_id):
    log = []
    from datetime import datetime, timezone, timedelta
    dt_now, now_ts = _get_device_date(base_url)

    # Discover Tasks app DB
    tasks_db = None
    for pkg in ["org.tasks", "org.dmfs.tasks"]:
        out = adb(base_url, f'adb shell "ls /data/data/{pkg}/databases/ 2>/dev/null"')
        if out.strip() and "No such" not in out:
            dbs = [f.strip() for f in out.strip().split("\n") if f.strip() and not f.startswith("$")]
            log.append(f"  {pkg} dbs: {dbs}")
            for db_name in ["database", "tasks.db", "tasks"]:
                if db_name in dbs:
                    tasks_db = f"/data/data/{pkg}/databases/{db_name}"
                    break
            if not tasks_db and dbs:
                tasks_db = f"/data/data/{pkg}/databases/{dbs[0]}"
            if tasks_db:
                break

    if not tasks_db:
        log.append("  ERROR: Tasks DB not found")
        reward = answer_and_finish(base_url, "No tasks found")
        return reward, log

    # Get schema
    schema = sqlite_b64(base_url, tasks_db, ".schema")
    log.append(f"  schema: {schema[:200]}")

    # Find task table
    tables = re.findall(r'CREATE TABLE\s+`?(\w+)`?', schema)
    log.append(f"  tables: {tables}")

    # Find the main tasks table (usually 'tasks' or 'task')
    task_table = None
    for t in tables:
        if t.lower() in ["tasks", "task"]:
            task_table = t
            break
    if not task_table:
        for t in tables:
            sample = sqlite_b64(base_url, tasks_db, f"SELECT * FROM {t} LIMIT 1")
            if sample.strip() and "Error" not in sample:
                task_table = t
                break
    if not task_table:
        task_table = tables[0] if tables else "tasks"

    # Get columns
    cols_out = sqlite_b64(base_url, tasks_db, f"PRAGMA table_info({task_table})")
    log.append(f"  columns: {cols_out[:200]}")

    # Parse column names
    col_names = []
    for line in cols_out.strip().split("\n"):
        parts = line.strip().split("|")
        if len(parts) >= 2:
            col_names.append(parts[1])

    # List all tasks for debugging
    all_tasks = sqlite_b64(base_url, tasks_db, f"SELECT * FROM {task_table}")
    log.append(f"  all tasks: {all_tasks[:300]}")

    # Determine which columns represent title, priority, due_date, completed
    title_col = next((c for c in col_names if c.lower() in ["title", "name"]), col_names[1] if len(col_names) > 1 else "title")
    priority_col = next((c for c in col_names if "priority" in c.lower() or "importance" in c.lower()), None)
    due_col = next((c for c in col_names if "due" in c.lower()), None)
    completed_col = next((c for c in col_names if "completed" in c.lower() or "completion" in c.lower() or "complete" in c.lower()), None)

    log.append(f"  title={title_col}, priority={priority_col}, due={due_col}, completed={completed_col}")

    if task_id == 100:
        # Tasks due October 20 2023
        oct20_ms = int(datetime(2023, 10, 20, tzinfo=timezone.utc).timestamp()) * 1000
        oct21_ms = oct20_ms + 86400000
        if due_col:
            out = sqlite_b64(base_url, tasks_db,
                f"SELECT {title_col} FROM {task_table} WHERE {due_col} >= {oct20_ms} AND {due_col} < {oct21_ms}")
        else:
            out = ""
        titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        answer = ", ".join(titles) if titles else "No tasks"

    elif task_id == 101:
        # High priority tasks
        # org.tasks: importance 0=high(!!!), 1=medium(!!), 2=low(!), 3=none
        if priority_col:
            out = sqlite_b64(base_url, tasks_db,
                f"SELECT DISTINCT {title_col} FROM {task_table} WHERE {priority_col} = 0")
            titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        else:
            titles = []
        answer = ", ".join(titles) if titles else "No tasks"

    elif task_id == 102:
        # High priority tasks due Friday
        ts_s, ts_e = _get_weekday_ts_range(base_url, "friday")
        ts_s_ms, ts_e_ms = ts_s * 1000, ts_e * 1000
        if priority_col and due_col:
            out = sqlite_b64(base_url, tasks_db,
                f"SELECT DISTINCT {title_col} FROM {task_table} WHERE {priority_col} = 0 "
                f"AND {due_col} >= {ts_s_ms} AND {due_col} < {ts_e_ms}")
            titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        else:
            titles = []
        answer = ", ".join(titles) if titles else "No tasks"

    elif task_id == 103:
        # How many tasks due next week
        days_to_mon = (0 - dt_now.weekday()) % 7
        if days_to_mon == 0:
            days_to_mon = 7
        mon = dt_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_to_mon)
        sun_end = mon + timedelta(days=7)
        ts_s_ms = int(mon.timestamp()) * 1000
        ts_e_ms = int(sun_end.timestamp()) * 1000
        if due_col:
            out = sqlite_b64(base_url, tasks_db,
                f"SELECT COUNT(*) FROM {task_table} WHERE {due_col} >= {ts_s_ms} AND {due_col} < {ts_e_ms}")
            answer = out.strip().split("\n")[0].strip()
        else:
            answer = "0"

    elif task_id == 104:
        # Completed tasks for October 16
        oct16_ms = int(datetime(2023, 10, 16, tzinfo=timezone.utc).timestamp()) * 1000
        oct17_ms = oct16_ms + 86400000
        if completed_col and due_col:
            out = sqlite_b64(base_url, tasks_db,
                f"SELECT {title_col} FROM {task_table} WHERE {completed_col} > 0 "
                f"AND {due_col} >= {oct16_ms} AND {due_col} < {oct17_ms}")
        elif completed_col:
            out = sqlite_b64(base_url, tasks_db,
                f"SELECT {title_col} FROM {task_table} WHERE {completed_col} >= {oct16_ms} AND {completed_col} < {oct17_ms}")
        else:
            out = ""
        titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        answer = ", ".join(titles) if titles else "No tasks"

    elif task_id == 105:
        # Incomplete tasks by October 25
        oct25_ms = int(datetime(2023, 10, 25, tzinfo=timezone.utc).timestamp()) * 1000
        if completed_col and due_col:
            out = sqlite_b64(base_url, tasks_db,
                f"SELECT {title_col} FROM {task_table} WHERE ({completed_col} = 0 OR {completed_col} IS NULL) "
                f"AND {due_col} <= {oct25_ms}")
        elif due_col:
            out = sqlite_b64(base_url, tasks_db,
                f"SELECT {title_col} FROM {task_table} WHERE {due_col} <= {oct25_ms}")
        else:
            out = ""
        titles = [l.strip() for l in out.strip().split("\n") if l.strip()]
        answer = ", ".join(titles) if titles else "No tasks"

    else:
        answer = "Unknown"

    log.append(f"  answer: {answer[:100]}")
    reward = answer_and_finish(base_url, answer)
    return reward, log


# --- Cross-App Tasks ---

def task_81_recipes_from_file(base_url, task_text):
    log = []
    # Read recipes.txt from Markor
    out = adb(base_url, f"adb shell cat {MARKOR_DIR}/recipes.txt")
    content = "\n".join(l for l in out.strip().split("\n") if not l.startswith("$"))
    log.append(f"  file content ({len(content)} chars): {content[:200]}")

    # Parse recipes from file
    recipes = _parse_recipes_from_text(content)
    log.append(f"  parsed {len(recipes)} recipes")

    # Filter if task 82 (only 2 hrs prep time)
    if "2 hrs" in task_text.lower() or "2 hours" in task_text.lower():
        filtered = []
        for r in recipes:
            prep = r.get("preparationTime", "").lower()
            if any(p in prep for p in ["2 hrs", "2 hours", "120 min", "2h", "2 h"]):
                filtered.append(r)
        recipes = filtered
        log.append(f"  filtered to {len(recipes)} recipes with 2 hrs prep")

    for r in recipes:
        title = r.get("title", "").replace("'", "''")
        desc = r.get("description", "").replace("'", "''")
        servings = r.get("servings", "").replace("'", "''")
        prep = r.get("preparationTime", "").replace("'", "''")
        ingr = r.get("ingredients", "").replace("'", "''")
        dirs = r.get("directions", "").replace("'", "''")
        sqlite_b64(base_url, BROCCOLI_DB,
            f"INSERT INTO recipes (title, description, servings, preparationTime, ingredients, directions, imageName, source, favorite) "
            f"VALUES ('{title}', '{desc}', '{servings}', '{prep}', '{ingr}', '{dirs}', '', '', 0)")
        log.append(f"  added: {r['title'][:40]}")

    reward = finish(base_url, "Added recipes from file")
    return reward, log


def _parse_recipes_from_text(text):
    """Parse recipe blocks from a text file (supports both key:value and pipe-delimited CSV)."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return []

    # Detect pipe-delimited CSV format (header contains |)
    if "|" in lines[0]:
        header = [h.strip().lower() for h in lines[0].split("|")]
        recipes = []
        for line in lines[1:]:
            cols = line.split("|")
            if len(cols) < 2:
                continue
            row = {}
            for i, h in enumerate(header):
                if i < len(cols):
                    row[h] = cols[i].strip()
            recipe = {
                "title": row.get("title", row.get("name", row.get("recipe", ""))),
                "description": row.get("description", row.get("desc", "")),
                "servings": row.get("servings", row.get("serving", "")),
                "preparationTime": row.get("preparationtime", row.get("preparation_time", row.get("prep_time", ""))),
                "ingredients": row.get("ingredients", row.get("ingredient", "")),
                "directions": row.get("directions", row.get("direction", row.get("steps", ""))),
            }
            if recipe["title"]:
                recipes.append(recipe)
        return recipes

    # Fallback: key:value format
    recipes = []
    current = {}
    for line in lines:
        if line.lower().startswith("recipe:") or line.lower().startswith("name:"):
            if current and "title" in current:
                recipes.append(current)
            current = {"title": line.split(":", 1)[1].strip()}
        elif ":" in line:
            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip()
            if key in ["description", "desc"]:
                current["description"] = val
            elif key in ["servings", "serving"]:
                current["servings"] = val
            elif key in ["preparationtime", "preparation_time", "prep_time", "prep time", "preparation time"]:
                current["preparationTime"] = val
            elif key in ["ingredients", "ingredient"]:
                current["ingredients"] = val
            elif key in ["directions", "direction", "steps"]:
                current["directions"] = val
            elif key in ["title"]:
                if current and "title" in current:
                    recipes.append(current)
                current = {"title": val}
    if current and "title" in current:
        recipes.append(current)
    return recipes


def task_86_expenses_from_file(base_url, task_text):
    log = []
    # Read my_expenses.txt from Markor
    out = adb(base_url, f"adb shell cat {MARKOR_DIR}/my_expenses.txt")
    content = "\n".join(l for l in out.strip().split("\n") if not l.startswith("$"))
    log.append(f"  file content ({len(content)} chars): {content[:200]}")

    # File is pipe-delimited CSV: name|amount_dollars|category_name|note
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if not lines:
        reward = finish(base_url, "No expenses found")
        return reward, log

    # First line is header
    header = lines[0].split("|")
    header_lower = [h.strip().lower() for h in header]
    log.append(f"  header: {header_lower}")

    expenses = []
    for line in lines[1:]:
        cols = line.split("|")
        if len(cols) < len(header):
            continue
        row = {}
        for i, h in enumerate(header_lower):
            row[h] = cols[i].strip()
        expenses.append(row)

    log.append(f"  parsed {len(expenses)} expenses from CSV")

    # Check if task asks for reimbursable only
    reimbursable_only = "reimbursable" in task_text.lower()
    if reimbursable_only:
        # Filter by "Reimbursable" in the note field (evaluator appends ". Reimbursable." to target rows)
        if "reimbursable" in header_lower:
            expenses = [e for e in expenses if e.get("reimbursable", "").lower() in ("yes", "true", "1")]
        else:
            expenses = [e for e in expenses if "reimbursable" in e.get("note", e.get("notes", "")).lower()]
        log.append(f"  {len(expenses)} reimbursable expenses")

    now_ms = int(time.time()) * 1000
    for exp in expenses:
        name = exp.get("name", exp.get("expense", "")).replace("'", "''")
        amount_str = exp.get("amount_dollars", exp.get("amount", "0"))
        amount_str = amount_str.replace("$", "").replace(",", "").strip()
        try:
            amount = int(round(float(amount_str) * 100))
        except ValueError:
            amount = 0
        cat_name = exp.get("category_name", exp.get("category", "other")).lower()
        category = EXPENSE_CATEGORIES.get(cat_name, 0)
        note = exp.get("note", exp.get("notes", ""))
        # Strip ". Reimbursable." suffix — evaluator reference has original note
        import re as _re
        note = _re.sub(r'\.\s*Reimbursable\.?\s*$', '', note, flags=_re.IGNORECASE).strip()
        note = note.replace("'", "''")
        sqlite_b64(base_url, EXPENSE_DB,
            f"INSERT INTO expense (name, amount, category, note, created_date, modified_date) "
            f"VALUES ('{name}', {amount}, {category}, '{note}', {now_ms}, {now_ms})")
        log.append(f"  added: {name}")

    reward = finish(base_url, "Logged expenses")
    return reward, log


# --- Contact Creation ---

def task_9_create_contact(base_url, task_text):
    log = []
    # "Create a new contact for David Li. Their number is +16018159083."
    m_name = re.search(r'contact for\s+(.+?)\.\s', task_text)
    m_phone = re.search(r'(\+\d+)', task_text)
    full_name = m_name.group(1).strip() if m_name else ""
    phone = m_phone.group(1) if m_phone else ""

    parts = full_name.split()
    given_name = parts[0] if parts else ""
    family_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    # Escape spaces with backslash for adb shell content insert
    full_name_escaped = full_name.replace(" ", "\\ ")
    given_name_escaped = given_name.replace(" ", "\\ ")
    family_name_escaped = family_name.replace(" ", "\\ ")

    log.append(f"  contact: {full_name}, phone: {phone}")

    # Insert raw contact
    adb(base_url, 'adb shell content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s: --bind account_name:s:')
    # Get the raw_contact_id
    out = adb(base_url, 'adb shell content query --uri content://com.android.contacts/raw_contacts --projection _id')
    raw_id = "1"
    # Find the last (highest) _id
    for m_id in re.finditer(r'_id=(\d+)', out):
        raw_id = m_id.group(1)
    log.append(f"  raw_contact_id: {raw_id}")

    # Insert display name (StructuredName) — wrap whole command in quotes, escape spaces
    adb(base_url,
        f'adb shell "content insert --uri content://com.android.contacts/data '
        f'--bind raw_contact_id:i:{raw_id} '
        f'--bind mimetype:s:vnd.android.cursor.item/name '
        f'--bind data1:s:{full_name_escaped} '
        f'--bind data2:s:{given_name_escaped} '
        f'--bind data3:s:{family_name_escaped}"')

    # Insert phone number
    adb(base_url,
        f'adb shell "content insert --uri content://com.android.contacts/data '
        f'--bind raw_contact_id:i:{raw_id} '
        f'--bind mimetype:s:vnd.android.cursor.item/phone_v2 '
        f'--bind data1:s:{phone} '
        f'--bind data2:i:2"')

    log.append(f"  inserted name and phone")

    # Verify
    out = adb(base_url, 'adb shell content query --uri content://com.android.contacts/contacts --projection display_name')
    log.append(f"  contacts: {out.strip()[:150]}")

    reward = finish(base_url, f"Created contact {full_name}")
    return reward, log


# --- Clipboard ---

def task_27_clipboard(base_url, task_text):
    log = []
    # "Copy the following text to the clipboard: Membership ID: ABC123"
    m = re.search(r'clipboard:\s*(.+?)\.?\s*$', task_text)
    text = m.group(1).strip() if m else ""
    log.append(f"  text: {text}")

    # Use ca.zgrs.clipper broadcast (installed on the device)
    escaped = text.replace("'", "'\\''")
    adb(base_url, f"adb shell \"am broadcast -a clipper.set --es text '{escaped}'\"")
    log.append(f"  set clipboard via clipper broadcast")

    reward = finish(base_url, f"Copied to clipboard: {text}")
    return reward, log


# --- Retro Music Playlists ---

RETRO_MUSIC_DB = "/data/data/code.name.monkey.retromusic/databases/playlist.db"
MEDIA_DB = "/data/data/com.google.android.providers.media.module/databases/external.db"


def _safe_int(val, default=0):
    """Convert value to int, defaulting NULL/empty/invalid to default."""
    if val is None or val in ("NULL", "null", ""):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _get_media_songs(base_url):
    """Query media provider for all songs, return list of dicts."""
    out = adb(base_url, 'adb shell content query --uri content://media/external/audio/media --projection _id:title:duration:track:year:_data:album_id:album:artist_id:artist:composer:album_artist')
    songs = []
    for line in out.strip().split("\n"):
        if "Row:" not in line:
            continue
        song = {}
        for m in re.finditer(r'(\w+)=([^,]+?)(?:,\s|$)', line):
            song[m.group(1)] = m.group(2).strip()
        if song.get("title"):
            songs.append(song)
    return songs


def task_58_create_playlist(base_url, task_text):
    log = []
    # "Create a playlist in Retro Music titled "Hip Hop Hits 332" with the following songs, in order: X, Y"
    m_title = re.search(r'titled?\s+"([^"]+)"', task_text)
    playlist_name = m_title.group(1) if m_title else ""

    m_songs = re.search(r'(?:songs?,?\s*in order:\s*|songs:\s*)(.+?)\.?\s*$', task_text)
    song_names = [s.strip() for s in m_songs.group(1).split(",")] if m_songs else []

    log.append(f"  playlist: {playlist_name}, songs: {song_names}")

    # Get all media songs
    all_songs = _get_media_songs(base_url)
    log.append(f"  media songs found: {len(all_songs)}")

    # Create playlist
    sqlite_b64(base_url, RETRO_MUSIC_DB,
        f"INSERT INTO PlaylistEntity (playlist_name) VALUES ('{playlist_name.replace(chr(39), chr(39)*2)}')")

    # Get playlist_id
    out = sqlite_b64(base_url, RETRO_MUSIC_DB,
        f"SELECT playlist_id FROM PlaylistEntity WHERE playlist_name='{playlist_name.replace(chr(39), chr(39)*2)}'")
    playlist_id = out.strip().split("\n")[0].strip() if out.strip() else "1"
    log.append(f"  playlist_id: {playlist_id}")

    # Match and insert songs in order
    for i, song_name in enumerate(song_names):
        matched = None
        for s in all_songs:
            if s.get("title", "").lower().strip() == song_name.lower().strip():
                matched = s
                break
        if not matched:
            # Try partial match
            for s in all_songs:
                if song_name.lower() in s.get("title", "").lower():
                    matched = s
                    break

        if matched:
            sid = _safe_int(matched.get("_id"), 0)
            title = matched.get("title", "").replace("'", "''")
            track = _safe_int(matched.get("track"), 0)
            year = _safe_int(matched.get("year"), 0)
            duration = _safe_int(matched.get("duration"), 0)
            data = matched.get("_data", "").replace("'", "''")
            album_id = _safe_int(matched.get("album_id"), 0)
            album = matched.get("album", "").replace("'", "''")
            artist_id = _safe_int(matched.get("artist_id"), 0)
            artist = matched.get("artist", "").replace("'", "''")
            composer = matched.get("composer", "") or ""
            if composer in ("NULL", "null"):
                composer = ""
            composer = composer.replace("'", "''")
            album_artist = matched.get("album_artist", "").replace("'", "''")

            sqlite_b64(base_url, RETRO_MUSIC_DB,
                f"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) "
                f"VALUES ({playlist_id}, {sid}, '{title}', {track}, {year}, {duration}, '{data}', 0, {album_id}, '{album}', {artist_id}, '{artist}', '{composer}', '{album_artist}')")
            log.append(f"  added song: {song_name} (id={sid})")
        else:
            log.append(f"  MISS: {song_name}")

    reward = finish(base_url, f"Created playlist '{playlist_name}'")
    return reward, log


def task_59_create_playlist_duration(base_url, task_text):
    log = []
    # "Create a playlist in Retro Music titled "Hip Hop Hits 332" with a duration between 45 and 50 minutes"
    m_title = re.search(r'titled?\s+"([^"]+)"', task_text)
    playlist_name = m_title.group(1) if m_title else ""

    m_min = re.search(r'between\s+(\d+)\s+and\s+(\d+)\s+min', task_text)
    min_dur = int(m_min.group(1)) * 60 * 1000 if m_min else 45 * 60 * 1000  # ms
    max_dur = int(m_min.group(2)) * 60 * 1000 if m_min else 50 * 60 * 1000  # ms

    log.append(f"  playlist: {playlist_name}, duration: {min_dur/60000:.0f}-{max_dur/60000:.0f} min")

    # Get all songs
    all_songs = _get_media_songs(base_url)
    log.append(f"  total songs: {len(all_songs)}")

    # Sort by duration and greedily pick songs to fill target duration
    valid_songs = [s for s in all_songs if s.get("duration", "0").isdigit() and int(s["duration"]) > 0]
    valid_songs.sort(key=lambda s: int(s["duration"]), reverse=True)

    selected = []
    total_ms = 0
    for s in valid_songs:
        dur = int(s["duration"])
        if total_ms + dur <= max_dur:
            selected.append(s)
            total_ms += dur
        if total_ms >= min_dur:
            break

    # If we haven't reached min_dur, try adding shorter songs
    if total_ms < min_dur:
        remaining = [s for s in valid_songs if s not in selected]
        remaining.sort(key=lambda s: int(s["duration"]))
        for s in remaining:
            dur = int(s["duration"])
            if total_ms + dur <= max_dur:
                selected.append(s)
                total_ms += dur
            if total_ms >= min_dur:
                break

    log.append(f"  selected {len(selected)} songs, total: {total_ms/60000:.1f} min")

    # Create playlist
    sqlite_b64(base_url, RETRO_MUSIC_DB,
        f"INSERT INTO PlaylistEntity (playlist_name) VALUES ('{playlist_name.replace(chr(39), chr(39)*2)}')")

    out = sqlite_b64(base_url, RETRO_MUSIC_DB,
        f"SELECT playlist_id FROM PlaylistEntity WHERE playlist_name='{playlist_name.replace(chr(39), chr(39)*2)}'")
    playlist_id = out.strip().split("\n")[0].strip() if out.strip() else "1"

    for s in selected:
        sid = _safe_int(s.get("_id"), 0)
        title = s.get("title", "").replace("'", "''")
        track = _safe_int(s.get("track"), 0)
        year = _safe_int(s.get("year"), 0)
        duration = _safe_int(s.get("duration"), 0)
        data = s.get("_data", "").replace("'", "''")
        album_id = _safe_int(s.get("album_id"), 0)
        album = s.get("album", "").replace("'", "''")
        artist_id = _safe_int(s.get("artist_id"), 0)
        artist = s.get("artist", "").replace("'", "''")
        composer = s.get("composer", "") or ""
        if composer in ("NULL", "null"):
            composer = ""
        composer = composer.replace("'", "''")
        album_artist = s.get("album_artist", "").replace("'", "''")

        sqlite_b64(base_url, RETRO_MUSIC_DB,
            f"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) "
            f"VALUES ({playlist_id}, {sid}, '{title}', {track}, {year}, {duration}, '{data}', 0, {album_id}, '{album}', {artist_id}, '{artist}', '{composer}', '{album_artist}')")

    reward = finish(base_url, f"Created playlist '{playlist_name}' ({total_ms/60000:.1f} min)")
    return reward, log


# --- SMS Cross-App (read SMS + send to contact) ---

def task_68_text_address(base_url, task_text):
    log = []
    # "Text the address of the event to David Li that Sara Lopez just sent me in Simple SMS Messenger"

    # Step 1: Read SMS inbox for the address (no --sort to avoid quoting issues)
    out = adb(base_url, 'adb shell content query --uri content://sms/inbox --projection address:body:date')
    log.append(f"  sms inbox: {out.strip()[:200]}")

    # Find message body (look for address-like content)
    address_text = ""
    for line in out.strip().split("\n"):
        if "body=" in line:
            m_body = re.search(r'body=(.+?)(?:,\s*\w+=|$)', line)
            if m_body:
                body = m_body.group(1).strip()
                # Look for address patterns (street number + name)
                if re.search(r'\d+\s+\w+\s+(?:St|Ave|Rd|Blvd|Dr|Ln|Way|Ct|Pl|Cir)', body):
                    address_text = body
                    break
                # If no clear street pattern, just use the body
                if not address_text:
                    address_text = body

    log.append(f"  found address: {address_text}")

    # Step 2: Find David Li's phone number
    out = adb(base_url, 'adb shell content query --uri content://contacts/phones --projection display_name:number')
    log.append(f"  contacts: {out.strip()[:200]}")

    target_phone = ""
    # Extract target name from task
    m_target = re.search(r'to\s+(\w+\s+\w+)\s+that', task_text)
    target_name = m_target.group(1) if m_target else "David Li"

    for line in out.strip().split("\n"):
        if target_name.lower() in line.lower():
            m_num = re.search(r'number=([+\d]+)', line)
            if m_num:
                target_phone = m_num.group(1)
                break

    log.append(f"  target: {target_name}, phone: {target_phone}")

    if not target_phone or not address_text:
        log.append(f"  ERROR: missing phone or address")
        reward = finish(base_url, "Could not find address or contact")
        return reward, log

    # Step 3: Open SMS compose to target phone
    adb(base_url, f"adb shell am start -a android.intent.action.SENDTO -d smsto:{target_phone} com.simplemobiletools.smsmessenger")
    time.sleep(4)

    # Step 4: Tap message input at known position (bottom of screen),
    # type address, tap send — avoid uiautomator dump which crashes containers
    # Message input is typically around y=1454 center, send button at x=1006
    adb(base_url, "adb shell input tap 540 1454")  # tap message input area
    time.sleep(1)

    # Type the address text (replace spaces with %s for input text)
    escaped_text = address_text.replace(" ", "%s")
    adb(base_url, f'adb shell input text "{escaped_text}"')
    time.sleep(2)

    # Tap send button at known position (right side of message bar)
    adb(base_url, "adb shell input tap 1006 1454")
    time.sleep(2)
    log.append(f"  typed and sent SMS to {target_phone}")

    reward = finish(base_url, f"Sent address to {target_name}")
    return reward, log


# --- File Copy ---

def task_84_copy_file(base_url, task_text):
    log = []
    # "In Simple Gallery Pro, copy receipt_4nfz_cool_guitar.jpg in DCIM and save a copy with the same name in Download"
    m_file = re.search(r'copy\s+(\S+)\s+in\s+(\w+)', task_text)
    filename = m_file.group(1) if m_file else ""
    src_dir = m_file.group(2) if m_file else "DCIM"

    m_dest = re.search(r'in\s+(\w+)\s*$', task_text)
    dst_dir = m_dest.group(1) if m_dest else "Download"

    src = f"{STORAGE}/{src_dir}/{filename}"
    dst = f"{STORAGE}/{dst_dir}/{filename}"

    adb(base_url, f"adb shell mkdir -p {STORAGE}/{dst_dir}")
    adb(base_url, f"adb shell cp {src} {dst}")
    # Trigger media scan so Gallery sees it
    adb(base_url, f"adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst}")

    out = adb(base_url, f"adb shell ls -la {dst}")
    log.append(f"  copied {src} → {dst}: {out.strip()[:80]}")

    reward = finish(base_url, f"Copied {filename}")
    return reward, log


# --- IR: OpenTracks ---

OPENTRACKS_DB = "/data/data/de.dennisguse.opentracks/databases/database.db"


def _opentracks_week_range(base_url):
    """Get (monday_ts_ms, sunday_end_ts_ms) for current week on device."""
    from datetime import datetime, timezone, timedelta
    dt_now, _ = _get_device_date(base_url)
    # Monday of current week
    days_since_mon = dt_now.weekday()  # Monday=0
    monday = dt_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_mon)
    sunday_end = monday + timedelta(days=7)
    return int(monday.timestamp()) * 1000, int(sunday_end.timestamp()) * 1000


def task_106_opentracks_activities(base_url, task_text):
    log = []
    # "What activities did I do October 03 in OpenTracks? Answer with activity type only."
    m_date = re.search(r'October\s+(\d+)', task_text)
    day = int(m_date.group(1)) if m_date else 3
    from datetime import datetime, timezone
    dt = datetime(2023, 10, day, tzinfo=timezone.utc)
    date_str = dt.strftime("%Y-%m-%d")

    out = sqlite_b64(base_url, OPENTRACKS_DB,
        f"SELECT activity_type FROM tracks WHERE datetime(starttime/1000, 'unixepoch') LIKE '{date_str}%'")
    log.append(f"  raw: {out.strip()[:200]}")

    types = [l.strip() for l in out.strip().split("\n") if l.strip()]
    answer = ", ".join(types) if types else "No activities"
    log.append(f"  answer: {answer}")

    reward = answer_and_finish(base_url, answer)
    return reward, log


def task_107_opentracks_swimming_count(base_url, task_text):
    log = []
    # "How many swimming activities did I do this week?"
    ts_start, ts_end = _opentracks_week_range(base_url)
    log.append(f"  week range: {ts_start} - {ts_end}")

    out = sqlite_b64(base_url, OPENTRACKS_DB,
        f"SELECT COUNT(*) FROM tracks WHERE (category='swimming' OR activity_type='swimming') "
        f"AND starttime >= {ts_start} AND starttime < {ts_end}")
    count = out.strip().split("\n")[0].strip() if out.strip() else "0"
    log.append(f"  answer: {count}")

    reward = answer_and_finish(base_url, count)
    return reward, log


def task_108_opentracks_swimming_duration(base_url, task_text):
    log = []
    # "How long was my swimming activity October 10 2023? Express in minutes."
    m = re.search(r'October\s+(\d+)\s+(\d{4})', task_text)
    day = int(m.group(1)) if m else 10
    year = int(m.group(2)) if m else 2023
    from datetime import datetime, timezone
    dt = datetime(year, 10, day, tzinfo=timezone.utc)
    ts_start = int(dt.timestamp()) * 1000
    ts_end = ts_start + 86400000

    out = sqlite_b64(base_url, OPENTRACKS_DB,
        f"SELECT totaltime FROM tracks WHERE (category='swimming' OR activity_type='swimming') "
        f"AND starttime >= {ts_start} AND starttime < {ts_end}")
    log.append(f"  raw: {out.strip()[:200]}")

    # Sum all swimming durations on that day (should be one)
    total_ms = 0
    for line in out.strip().split("\n"):
        line = line.strip()
        if line and line.isdigit():
            total_ms += int(line)
        elif line:
            try:
                total_ms += int(float(line))
            except ValueError:
                pass

    minutes = round(total_ms / 60000)
    log.append(f"  answer: {minutes}")

    reward = answer_and_finish(base_url, str(minutes))
    return reward, log


def task_109_opentracks_swimming_max_distance(base_url, task_text):
    log = []
    # "Longest distance in swimming activity this week?"
    ts_start, ts_end = _opentracks_week_range(base_url)

    out = sqlite_b64(base_url, OPENTRACKS_DB,
        f"SELECT MAX(totaldistance) FROM tracks WHERE (category='swimming' OR activity_type='swimming') "
        f"AND starttime >= {ts_start} AND starttime < {ts_end}")
    log.append(f"  raw: {out.strip()[:200]}")

    val = out.strip().split("\n")[0].strip()
    try:
        answer = str(round(float(val)))
    except ValueError:
        answer = "0"
    log.append(f"  answer: {answer}")

    reward = answer_and_finish(base_url, answer)
    return reward, log


def task_110_opentracks_swimming_total_duration(base_url, task_text):
    log = []
    # "Total duration of swimming activities this week? In minutes."
    ts_start, ts_end = _opentracks_week_range(base_url)

    out = sqlite_b64(base_url, OPENTRACKS_DB,
        f"SELECT SUM(totaltime) FROM tracks WHERE (category='swimming' OR activity_type='swimming') "
        f"AND starttime >= {ts_start} AND starttime < {ts_end}")
    log.append(f"  raw: {out.strip()[:200]}")

    val = out.strip().split("\n")[0].strip()
    try:
        minutes = round(int(float(val)) / 60000)
    except ValueError:
        minutes = 0
    log.append(f"  answer: {minutes}")

    reward = answer_and_finish(base_url, str(minutes))
    return reward, log


def task_111_opentracks_skiing_distance(base_url, task_text):
    log = []
    # "Total distance for skiing activities Oct 06-11 2023?"
    m_from = re.search(r'from\s+October\s+(\d+)\s+(\d{4})', task_text)
    m_to = re.search(r'to\s+October\s+(\d+)\s+(\d{4})', task_text)
    from datetime import datetime, timezone

    day_from = int(m_from.group(1)) if m_from else 6
    day_to = int(m_to.group(1)) if m_to else 11
    year = int(m_from.group(2)) if m_from else 2023

    ts_start = int(datetime(year, 10, day_from, tzinfo=timezone.utc).timestamp()) * 1000
    ts_end = int(datetime(year, 10, day_to + 1, tzinfo=timezone.utc).timestamp()) * 1000  # inclusive end day

    out = sqlite_b64(base_url, OPENTRACKS_DB,
        f"SELECT SUM(totaldistance) FROM tracks WHERE category='skiing' "
        f"AND starttime >= {ts_start} AND starttime < {ts_end}")
    log.append(f"  raw: {out.strip()[:200]}")

    val = out.strip().split("\n")[0].strip()
    try:
        answer = str(round(float(val)))
    except ValueError:
        answer = "0"
    log.append(f"  answer: {answer}")

    reward = answer_and_finish(base_url, answer)
    return reward, log


# --- IR: Joplin ---

JOPLIN_DB = "/data/data/net.cozic.joplin/databases/joplin.sqlite"


def task_112_joplin_recipe_ingredient(base_url, task_text):
    log = []
    # "What quantity of goji berries do I need for the recipe 'Beef Stew' in Joplin?"
    m_item = re.search(r'quantity of\s+(.+?)\s+do I need', task_text)
    m_recipe = re.search(r"recipe '([^']+)'", task_text)
    ingredient = m_item.group(1).strip() if m_item else ""
    recipe = m_recipe.group(1).strip() if m_recipe else ""

    log.append(f"  recipe: {recipe}, ingredient: {ingredient}")

    escaped_recipe = recipe.replace("'", "''")
    out = sqlite_b64(base_url, JOPLIN_DB,
        f"SELECT body FROM notes WHERE title='{escaped_recipe}'")
    log.append(f"  body ({len(out)} chars): {out[:300]}")

    # Find the ingredient line
    answer = "Not found"
    for line in out.split("\n"):
        if ingredient.lower() in line.lower():
            # Extract quantity: typically "- 1/2 cup goji berries" or "1/2 cup goji berries"
            m_qty = re.search(r'[-*]?\s*(\d+(?:/\d+)?\s*\w+)\s+' + re.escape(ingredient), line, re.IGNORECASE)
            if m_qty:
                answer = m_qty.group(1).strip()
                break
            # Try another pattern: "amount unit ingredient"
            m_qty2 = re.search(r'(\d+(?:[./]\d+)?\s+\w+)\s+' + re.escape(ingredient), line, re.IGNORECASE)
            if m_qty2:
                answer = m_qty2.group(1).strip()
                break

    log.append(f"  answer: {answer}")
    reward = answer_and_finish(base_url, answer)
    return reward, log


def task_113_joplin_meeting_attendees(base_url, task_text):
    log = []
    # "How many attendees were present in the meeting titled 'Financial Performance Analysis'?"
    m_title = re.search(r"titled '([^']+)'", task_text)
    title = m_title.group(1).strip() if m_title else ""

    escaped_title = title.replace("'", "''")
    out = sqlite_b64(base_url, JOPLIN_DB,
        f"SELECT body FROM notes WHERE title='{escaped_title}'")
    log.append(f"  body ({len(out)} chars): {out[:300]}")

    # Count attendees - look for attendee/participant section
    answer = "0"
    lines = out.split("\n")
    in_attendees = False
    attendee_count = 0
    for line in lines:
        ll = line.lower().strip()
        if "attendee" in ll or "participant" in ll:
            in_attendees = True
            # Check if count is mentioned on same line: "Attendees: 25" or "25 attendees"
            m_num = re.search(r'(\d+)', line)
            if m_num and (":" in line or "attendee" in ll):
                # Could be a header with count or a list marker
                pass
            continue
        if in_attendees:
            # Count list items (lines starting with -, *, numbers, or names)
            if ll.startswith("-") or ll.startswith("*") or re.match(r'\d+[\.\)]\s', ll):
                attendee_count += 1
            elif ll == "" and attendee_count > 0:
                break  # End of list
            elif ll and not ll.startswith("#"):
                # Could be a name without bullet
                attendee_count += 1

    if attendee_count > 0:
        answer = str(attendee_count)
    else:
        # Try to find a number directly stated (various phrasings)
        m_count = re.search(
            r'(\d+)\s*(?:attendee|participant|individual|people|member|person)s?\s*(?:attended|present|joined)?',
            out, re.IGNORECASE)
        if not m_count:
            # Fallback: "N <word> attended"
            m_count = re.search(r'(\d+)\s+\w+\s+attended', out, re.IGNORECASE)
        if m_count:
            answer = m_count.group(1)

    log.append(f"  answer: {answer}")
    reward = answer_and_finish(base_url, answer)
    return reward, log


def task_114_joplin_is_todo(base_url, task_text):
    log = []
    # "Is the note titled 'Research Notes' in Joplin marked as a todo item?"
    m_title = re.search(r"titled '([^']+)'", task_text)
    title = m_title.group(1).strip() if m_title else ""

    escaped_title = title.replace("'", "''")
    out = sqlite_b64(base_url, JOPLIN_DB,
        f"SELECT is_todo FROM notes WHERE title='{escaped_title}'")
    log.append(f"  raw: {out.strip()}")

    val = out.strip().split("\n")[0].strip()
    answer = "True" if val == "1" else "False"
    log.append(f"  answer: {answer}")

    reward = answer_and_finish(base_url, answer)
    return reward, log


def task_115_joplin_todo_count(base_url, task_text):
    log = []
    # "How many to-dos do I have in the 'Ideas' folder in Joplin?"
    m_folder = re.search(r"'([^']+)'\s*folder", task_text)
    folder_name = m_folder.group(1).strip() if m_folder else ""

    log.append(f"  folder: {folder_name}")

    # Get folder ID
    escaped_folder = folder_name.replace("'", "''")
    out = sqlite_b64(base_url, JOPLIN_DB,
        f"SELECT id FROM folders WHERE title='{escaped_folder}'")
    folder_id = out.strip().split("\n")[0].strip() if out.strip() else ""
    log.append(f"  folder_id: {folder_id}")

    if not folder_id:
        reward = answer_and_finish(base_url, "0")
        return reward, log

    # Count todos in that folder
    escaped_fid = folder_id.replace("'", "''")
    out = sqlite_b64(base_url, JOPLIN_DB,
        f"SELECT COUNT(*) FROM notes WHERE parent_id='{escaped_fid}' AND is_todo=1")
    count = out.strip().split("\n")[0].strip() if out.strip() else "0"
    log.append(f"  answer: {count}")

    reward = answer_and_finish(base_url, count)
    return reward, log


# ============================================================================
# Task Registry
# ============================================================================

def dispatch_task(base_url, task_id, task_text):
    """Route task_id to the appropriate handler."""

    # System settings
    if task_id in [7, 16, 17, 18, 19, 25, 26, 41, 42, 43, 44, 45, 46, 64]:
        return task_system(base_url, task_text)

    # Delete file
    if task_id == 12:
        return task_12_delete_all_markor(base_url, task_text)
    if task_id == 13:
        return task_13_delete_markor_note(base_url, task_text)
    if task_id == 23:
        return task_23_delete_newest_markor(base_url, task_text)
    if task_id == 62:
        return task_62_delete_file(base_url, task_text)

    # Delete sqlite - recipes
    if task_id in [3, 4, 32, 57]:
        return task_delete_recipes(base_url, task_text)

    # Delete sqlite - calendar events
    if task_id == 5:
        return task_5_delete_calendar_on_date(base_url, task_text)
    if task_id == 6:
        return task_6_delete_specific_calendar_event(base_url, task_text)
    if task_id == 61:
        return task_61_delete_events_this_wednesday(base_url, task_text)

    # Delete sqlite - expenses
    if task_id in [11, 15, 77]:
        return task_delete_expenses(base_url, task_text)

    # Delete conditional
    if task_id == 90:
        return task_90_delete_broccoli_directions(base_url, task_text)

    # Dedup
    if task_id in [14, 70, 71]:
        return task_dedup_recipes(base_url, task_text)
    if task_id in [49, 50]:
        return task_dedup_expenses(base_url, task_text)

    # Create file
    if task_id == 22:
        return task_22_create_folder(base_url, task_text)
    if task_id in [52, 79]:
        return task_create_note(base_url, task_text)

    # Edit file
    if task_id == 24:
        return task_24_edit_note(base_url, task_text)
    if task_id == 51:
        return task_51_update_and_rename(base_url, task_text)
    if task_id == 69:
        return task_69_prepend_and_rename(base_url, task_text)
    if task_id == 87:
        return task_87_merge_notes(base_url, task_text)

    # Move file
    if task_id == 54:
        return task_54_move_markor_note(base_url, task_text)
    if task_id == 63:
        return task_63_move_file(base_url, task_text)

    # Create sqlite - expenses
    if task_id in [21, 48]:
        return task_add_expenses(base_url, task_text)

    # Create sqlite - recipes
    if task_id in [31, 56]:
        return task_add_recipes(base_url, task_text)

    # Create sqlite - calendar events
    if task_id in [34, 35, 36, 60, 85]:
        return task_create_calendar_event(base_url, task_text)

    # SMS
    if task_id == 67:
        return task_67_send_sms(base_url, task_text)

    # IR - Calendar
    if task_id in [91, 92, 93, 94, 95, 96, 97, 98, 99]:
        return task_ir_calendar(base_url, task_text, task_id)

    # IR - Tasks app
    if task_id in [100, 101, 102, 103, 104, 105]:
        return task_ir_tasks_app(base_url, task_text, task_id)

    # Cross-app
    if task_id in [81, 82]:
        return task_81_recipes_from_file(base_url, task_text)
    if task_id == 86:
        return task_86_expenses_from_file(base_url, task_text)

    # Contact creation
    if task_id == 9:
        return task_9_create_contact(base_url, task_text)

    # Clipboard
    if task_id == 27:
        return task_27_clipboard(base_url, task_text)

    # Retro Music playlists
    if task_id == 58:
        return task_58_create_playlist(base_url, task_text)
    if task_id == 59:
        return task_59_create_playlist_duration(base_url, task_text)

    # SMS cross-app
    if task_id == 68:
        return task_68_text_address(base_url, task_text)

    # File copy
    if task_id == 84:
        return task_84_copy_file(base_url, task_text)

    # IR - OpenTracks
    if task_id == 106:
        return task_106_opentracks_activities(base_url, task_text)
    if task_id == 107:
        return task_107_opentracks_swimming_count(base_url, task_text)
    if task_id == 108:
        return task_108_opentracks_swimming_duration(base_url, task_text)
    if task_id == 109:
        return task_109_opentracks_swimming_max_distance(base_url, task_text)
    if task_id == 110:
        return task_110_opentracks_swimming_total_duration(base_url, task_text)
    if task_id == 111:
        return task_111_opentracks_skiing_distance(base_url, task_text)

    # IR - Joplin
    if task_id == 112:
        return task_112_joplin_recipe_ingredient(base_url, task_text)
    if task_id == 113:
        return task_113_joplin_meeting_attendees(base_url, task_text)
    if task_id == 114:
        return task_114_joplin_is_todo(base_url, task_text)
    if task_id == 115:
        return task_115_joplin_todo_count(base_url, task_text)

    return 0.0, [f"  ERROR: No handler for task_id={task_id}"]


# ============================================================================
# Main
# ============================================================================

def run_one_task(task_def, container):
    """Run a task. Returns (result_dict, container_alive)."""
    base_url = container["url"]
    task_id = task_def["task_id"]
    seed = task_def["seed"]
    task_text = task_def["task"]

    print(f"\n{'='*60}")
    print(f"TASK {task_id} (seed={seed}) on {container['name']}: {task_text[:60]}")
    print(f"{'='*60}")
    sys.stdout.flush()

    try:
        reset_resp = reset_task(base_url, task_id, seed)
        time.sleep(10)  # Wait for a11y tree to stabilize after reset
        # Use task text from container (some tasks generate params at runtime)
        container_task = reset_resp.get("info", {}).get("task", "")
        if container_task:
            task_text = container_task
        print(f"  Reset OK. Task: {task_text[:80]}")
    except Exception as e:
        print(f"  RESET FAILED: {e}")
        is_dead = "Connection refused" in str(e) or "RemoteDisconnected" in str(e)
        return {"task_id": task_id, "reward": 0.0, "error": str(e)}, not is_dead

    _current_task_commands.clear()
    try:
        reward, log = dispatch_task(base_url, task_id, task_text)
    except Exception as e:
        print(f"  EXECUTION FAILED: {e}")
        is_dead = "Connection refused" in str(e) or "RemoteDisconnected" in str(e)
        return {"task_id": task_id, "reward": 0.0, "error": str(e)}, not is_dead

    for line in log:
        print(line[:120])

    status = "OK" if reward > 0 else "FAIL"
    print(f"  >>> REWARD: {reward} ({status})")
    sys.stdout.flush()
    result = {"task_id": task_id, "reward": reward, "task": task_text[:60]}
    if reward > 0:
        result["commands"] = list(_current_task_commands)
    return result, True


def discover_broker_containers() -> list[dict]:
    """Discover healthy containers managed by the broker."""
    containers = []
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )
    names = [n.strip() for n in result.stdout.strip().split("\n") if n.strip()]
    env_names = sorted(
        [n for n in names if re.match(r"^env\d+$", n)],
        key=lambda n: int(n.replace("env", "")),
    )
    for name in env_names:
        info = subprocess.run(
            ["docker", "inspect", name, "--format",
             "{{range .Config.Env}}{{println .}}{{end}}"],
            capture_output=True, text=True,
        )
        env_vars = {}
        for line in info.stdout.strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                env_vars[k] = v
        port = env_vars.get("SERVER_PORT", "")
        env_id = env_vars.get("ENV_ID", "")
        if not port:
            continue
        url = f"http://localhost:{port}"
        # Quick health check
        try:
            with urllib.request.urlopen(
                urllib.request.Request(f"{url}/health"), timeout=5
            ) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") == "healthy" and data.get("ready"):
                    containers.append({
                        "name": name, "env_id": int(env_id),
                        "server_port": int(port), "url": url,
                    })
        except Exception:
            pass
    return containers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool-size", type=int, default=0,
                        help="Max containers to use (0 = all available)")
    parser.add_argument("--image", default="androidworld:full_adb_agent")
    parser.add_argument("--base-env-id", type=int, default=500)
    parser.add_argument("--tasks", type=str, default=None, help="Comma-separated task IDs")
    parser.add_argument("--data", default=None, help="JSONL file (default: val_data_seed7_no_gui.jsonl)")
    parser.add_argument("--output", default="./verify_71_results.json")
    parser.add_argument("--use-broker", action="store_true", default=True,
                        help="Use existing broker containers (default: True)")
    parser.add_argument("--no-broker", action="store_true",
                        help="Start own containers instead of using broker")
    args = parser.parse_args()

    # Load tasks
    data_file = args.data or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "androidworld_original", "val_data_seed7_no_gui.jsonl"
    )
    # Fallback path
    if not os.path.exists(data_file):
        data_file = "/shared/ligu/projects/SkyRL-AndriodWorld/skyrl-agent/data/androidworld_original/val_data_seed7_no_gui.jsonl"

    with open(data_file) as f:
        all_tasks = [json.loads(l) for l in f if l.strip()]

    if args.tasks:
        task_ids = set(int(x) for x in args.tasks.split(","))
        all_tasks = [t for t in all_tasks if t["task_id"] in task_ids]

    # Discover or start containers
    own_containers = False
    if args.no_broker:
        own_containers = True
        pool_size = args.pool_size or 2
        print(f"Starting {pool_size} own containers...")
        containers = []
        for i in range(pool_size):
            env_id = args.base_env_id + i
            print(f"  Starting env_id={env_id}...")
            try:
                c = start_container(env_id, args.image)
                containers.append(c)
            except Exception as e:
                print(f"  Failed: {e}")
        healthy = []
        for c in containers:
            print(f"  {c['name']}...", end=" ", flush=True)
            if wait_for_healthy(c):
                print("OK")
                healthy.append(c)
            else:
                print("TIMEOUT")
                stop_container(c)
        containers = healthy
    else:
        print("Discovering broker containers...")
        containers = discover_broker_containers()
        if args.pool_size > 0:
            containers = containers[:args.pool_size]

    if not containers:
        print("No containers available.")
        return 1

    print(f"\n{len(containers)} containers ready. Running {len(all_tasks)} tasks.\n")

    # Run tasks (round-robin across containers, with health checks)
    results = []
    dead_containers = set()
    for i, task_def in enumerate(all_tasks):
        # Find a healthy container (round-robin, skip dead ones)
        container = None
        chosen_idx = None
        for attempt in range(len(containers)):
            idx = (i + attempt) % len(containers)
            if idx in dead_containers:
                continue
            candidate = containers[idx]
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(f"{candidate['url']}/health"), timeout=5
                ) as resp:
                    container = candidate
                    chosen_idx = idx
                    break
            except Exception:
                print(f"  {candidate['name']} is down, marking dead")
                dead_containers.add(idx)

        if container is None:
            print(f"  No healthy containers left, skipping task {task_def['task_id']}")
            results.append({"task_id": task_def["task_id"], "reward": 0.0, "error": "no_containers"})
            continue

        result, alive = run_one_task(task_def, container)
        results.append(result)
        if not alive and chosen_idx is not None:
            print(f"  Marking {container['name']} as dead")
            dead_containers.add(chosen_idx)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    successes = sum(1 for r in results if r["reward"] > 0)
    for r in results:
        s = "OK" if r["reward"] > 0 else "FAIL"
        err = f" ({r.get('error', '')[:40]})" if r.get("error") else ""
        print(f"  task_id={r['task_id']:3d} [{s:4s}] {r.get('task', '')[:55]}{err}")

    print(f"\nTotal: {successes}/{len(results)} ({100*successes/max(len(results),1):.0f}%)")

    # Save JSON summary
    output_file = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w") as f:
        json.dump({"results": results, "total": len(results), "successes": successes}, f, indent=2)
    print(f"Results: {output_file}")

    # Save JSONL with recorded commands (only successful tasks)
    jsonl_file = output_file.replace(".json", "_commands.jsonl")
    # Load full task texts from data file
    task_full_text = {}
    with open(args.data) as f:
        for line in f:
            d = json.loads(line)
            task_full_text[d["task_id"]] = d["task"]
    with open(jsonl_file, "w") as f:
        for r in sorted(results, key=lambda x: x["task_id"]):
            if r["reward"] > 0 and "commands" in r:
                entry = {
                    "task_id": r["task_id"],
                    "seed": 7,
                    "task": task_full_text.get(r["task_id"], r.get("task", "")),
                    "commands": r["commands"],
                    "reward": r["reward"],
                }
                f.write(json.dumps(entry) + "\n")
    n_exported = sum(1 for r in results if r["reward"] > 0 and "commands" in r)
    print(f"Commands JSONL: {jsonl_file} ({n_exported} tasks)")

    # Cleanup only own containers
    if own_containers:
        print("\nCleaning up...")
        for c in containers:
            stop_container(c)

    return 0 if successes == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
