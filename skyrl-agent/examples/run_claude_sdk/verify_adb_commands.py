#!/usr/bin/env python3
"""
Verify that each of the 10 AndroidWorld tasks can be solved with
pure ADB commands (no GUI interaction).

Spins up containers, resets each task, runs the ideal ADB sequence,
sends FINISH, and reports the reward.

Usage:
    python verify_adb_commands.py --pool-size 2
    python verify_adb_commands.py --pool-size 4 --image androidworld:full_adb_agent
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import subprocess
import re
import signal

# ---------------------------------------------------------------------------
# Container management (minimal, no dependency on skyrl_agent)
# ---------------------------------------------------------------------------

def start_container(env_id: int, image: str) -> dict:
    """Start a single Android container, return its config."""
    server_port = 5000 + 2 * env_id
    emulator_port = 5574 + 2 * env_id
    grpc_port = emulator_port + 3000
    adb_server_port = 5037 + env_id
    name = f"verify_adb_{env_id}"

    # Remove if exists
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    # Create log dir (container expects a mounted /data/log)
    log_dir = f"/tmp/verify_adb/env{env_id}/log"
    os.makedirs(log_dir, exist_ok=True)

    cmd = [
        "docker", "run", "-d",
        "--name", name,
        "--network", "host",
        "--device", "/dev/kvm",
        "-v", f"{log_dir}:/data/log",
        "-e", f"ENV_ID={env_id}",
        "-e", f"SERVER_PORT={server_port}",
        "-e", f"EMULATOR_PORT={emulator_port}",
        "-e", f"GRPC_PORT={grpc_port}",
        "-e", f"ADB_SERVER_PORT={adb_server_port}",
        "-e", "ENV_SNAPSHOT=clean",
        "-e", "ENV_SAMPLE_MODE=sequential",
        "-e", "ENV_SAVE_IMAGES=False",
        "-e", "ENV_TASK_FAMILY=android_world",
        "-e", "ENV_SKIP_SCREENSHOT=True",
        image,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start container {name}: {result.stderr}")

    return {
        "name": name,
        "env_id": env_id,
        "server_port": server_port,
        "url": f"http://localhost:{server_port}",
    }


def wait_for_healthy(container: dict, timeout: int = 300) -> bool:
    """Wait for container's /health endpoint to respond."""
    url = f"{container['url']}/health"
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def stop_container(container: dict):
    """Stop and remove container."""
    subprocess.run(["docker", "rm", "-f", container["name"]], capture_output=True)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def http_post(base_url: str, endpoint: str, payload: dict, timeout: int = 300) -> dict:
    """POST JSON to container, return parsed response."""
    url = f"{base_url}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reset_task(base_url: str, task_id: int, seed: int) -> dict:
    """Reset container to a specific task."""
    return http_post(base_url, "/reset", {
        "seed": seed,
        "options": {"task_id": task_id, "go_home_on_reset": True},
    })


def run_adb(base_url: str, command: str, thought: str = "") -> dict:
    """Execute an ADB command via /step_adb."""
    return http_post(base_url, "/step_adb", {
        "command": command,
        "thought": thought or command,
    })


def finish_task(base_url: str, answer: str = "done") -> dict:
    """Send FINISH to evaluate the task."""
    return http_post(base_url, "/step_adb", {
        "command": f"FINISH(content='{answer}')",
        "thought": "Task complete",
    })


def answer_task(base_url: str, answer: str) -> dict:
    """For info retrieval tasks: set interaction_cache via /step with action_type=answer,
    then finish with status=complete."""
    # Step 1: Set the answer (interaction_cache)
    http_post(base_url, "/step", {
        "action": {"action_type": "answer", "text": answer},
        "thought": f"Answer: {answer}",
    })
    # Step 2: Finish the task
    return http_post(base_url, "/step", {
        "action": {"action_type": "status", "goal_status": "complete"},
        "thought": "Task complete",
    })


# ---------------------------------------------------------------------------
# Task definitions: each returns a callable(base_url) -> (reward, log)
# ---------------------------------------------------------------------------

def task_4_delete_broccoli_recipe(base_url):
    """Delete 'Chicken Caesar Salad Wrap' from Broccoli."""
    log = []

    # First, discover the schema
    r = run_adb(base_url, 'adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \'.tables\'"')
    log.append(("tables", r.get("command_output", "")))

    r = run_adb(base_url, 'adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \'.schema recipes\'"')
    log.append(("schema", r.get("command_output", "")))

    # List recipes before
    r = run_adb(base_url, 'adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \'SELECT recipeId, title FROM recipes\'"')
    log.append(("before", r.get("command_output", "")))

    # Delete
    r = run_adb(base_url,
        "adb shell \"sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli"
        " 'DELETE FROM recipes WHERE title=\\\"Chicken Caesar Salad Wrap\\\"'\"")
    log.append(("delete", r.get("command_output", "")))

    # Verify
    r = run_adb(base_url, 'adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \'SELECT recipeId, title FROM recipes\'"')
    log.append(("after", r.get("command_output", "")))

    # Finish
    r = finish_task(base_url, "Deleted Chicken Caesar Salad Wrap from Broccoli")
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


def task_5_delete_calendar_events(base_url):
    """Delete all calendar events on 2023-10-25."""
    log = []

    # Discover schema
    r = run_adb(base_url, 'adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \'.schema events\'"')
    log.append(("schema", r.get("command_output", "")))

    # List events to find timestamp format
    r = run_adb(base_url, 'adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \'SELECT id, title, start_ts, end_ts FROM events ORDER BY start_ts\'"')
    log.append(("all_events", r.get("command_output", "")))

    # Oct 25 2023 00:00:00 UTC = 1698192000, Oct 26 2023 00:00:00 UTC = 1698278400
    # Check if timestamps are in seconds or milliseconds by looking at the data
    output = r.get("command_output", "")
    # Heuristic: if values > 10^12, they're milliseconds
    uses_ms = any(int(x) > 1e12 for x in re.findall(r'\d{13,}', output))
    if uses_ms:
        ts_start, ts_end = 1698192000000, 1698278400000
    else:
        ts_start, ts_end = 1698192000, 1698278400

    # Show events on that date
    r = run_adb(base_url,
        f'adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db'
        f" 'SELECT id, title, start_ts FROM events WHERE start_ts >= {ts_start} AND start_ts < {ts_end}'\"")
    log.append(("target_events", r.get("command_output", "")))

    # Delete
    r = run_adb(base_url,
        f'adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db'
        f" 'DELETE FROM events WHERE start_ts >= {ts_start} AND start_ts < {ts_end}'\"")
    log.append(("delete", r.get("command_output", "")))

    # Finish
    r = finish_task(base_url, "Deleted all calendar events on 2023-10-25")
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


def task_9_create_contact(base_url):
    """Create contact David Li, +16018159083.

    Must use intent + UI Save (content provider insert doesn't show in
    content://contacts/phones/ which the evaluator queries).
    """
    log = []
    import time as _time

    # Use AM intent to open new-contact form with pre-filled data
    r = run_adb(base_url,
        'adb shell "am start -a android.intent.action.INSERT'
        ' -t vnd.android.cursor.dir/contact'
        ' -e name \\\"David Li\\\"'
        ' -e phone +16018159083"')
    log.append(("intent", r.get("command_output", "")))

    # Wait for contacts UI to load
    _time.sleep(3)

    # Find and tap the Save button via accessibility tree
    r = run_adb(base_url,
        'adb shell uiautomator dump /sdcard/window_dump.xml'
        ' && adb shell cat /sdcard/window_dump.xml')
    a11y = r.get("command_output", "")

    # Parse Save button bounds
    save_match = re.search(
        r'text="Save"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', a11y)
    if save_match:
        x = (int(save_match.group(1)) + int(save_match.group(3))) // 2
        y = (int(save_match.group(2)) + int(save_match.group(4))) // 2
        log.append(("save_btn", f"at ({x},{y})"))
    else:
        # Fallback: try common Save button position
        x, y = 975, 1305
        log.append(("save_btn", f"fallback ({x},{y})"))

    r = run_adb(base_url, f"adb shell input tap {x} {y}")
    log.append(("tap_save", r.get("command_output", "")))

    _time.sleep(2)

    # Verify via evaluator's query path
    r = run_adb(base_url,
        'adb shell content query --uri content://contacts/phones/'
        ' --projection display_name:number')
    log.append(("verify", r.get("command_output", "")))

    r = finish_task(base_url, "Created contact David Li")
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


def task_13_delete_markor_note(base_url):
    """Delete Markor note named eHwd_helpful_jacket."""
    log = []

    # List files
    r = run_adb(base_url, 'adb shell ls /storage/emulated/0/Documents/markor/')
    log.append(("ls_before", r.get("command_output", "")))

    # Delete — try exact name first (no extension), then with .md
    r = run_adb(base_url, 'adb shell rm -f /storage/emulated/0/Documents/markor/eHwd_helpful_jacket')
    log.append(("delete_noext", r.get("command_output", "")))

    r = run_adb(base_url, 'adb shell rm -f /storage/emulated/0/Documents/markor/eHwd_helpful_jacket.md')
    log.append(("delete_md", r.get("command_output", "")))

    # Verify
    r = run_adb(base_url, 'adb shell ls /storage/emulated/0/Documents/markor/')
    log.append(("ls_after", r.get("command_output", "")))

    r = finish_task(base_url, "Deleted eHwd_helpful_jacket from Markor")
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


def task_16_wifi_and_contacts(base_url):
    """Turn on WiFi, then open contacts app."""
    log = []

    # Turn on WiFi
    r = run_adb(base_url, "adb shell svc wifi enable")
    log.append(("wifi_enable", r.get("command_output", "")))

    # Verify WiFi is on
    r = run_adb(base_url, "adb shell dumpsys wifi | head -5")
    log.append(("wifi_check", r.get("command_output", "")))

    # Open contacts app
    r = run_adb(base_url, "adb shell am start -n com.google.android.contacts/com.android.contacts.activities.PeopleActivity")
    log.append(("open_contacts", r.get("command_output", "")))

    # Small wait for app to open
    r = run_adb(base_url, "adb shell sleep 2 && adb shell dumpsys activity activities | grep mResumedActivity")
    log.append(("verify_app", r.get("command_output", "")))

    r = finish_task(base_url, "WiFi enabled and contacts app opened")
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


def task_11_delete_expense(base_url):
    """Delete expense 'Taxi Fare' from Pro Expense."""
    log = []

    # Discover DB and schema
    r = run_adb(base_url, 'adb shell "ls /data/data/com.arduia.expense/databases/"')
    log.append(("ls_db", r.get("command_output", "")))

    # Try common DB names
    for db_name in ["accounting.db", "expense.db", "pro_expense.db", "database"]:
        r = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db_name} \'.tables\'"')
        output = r.get("command_output", "")
        log.append((f"tables_{db_name}", output))
        if output and "Error" not in output and "unable" not in output.lower():
            db = db_name
            break
    else:
        db = "accounting.db"  # fallback

    # Get schema of expense-related tables
    r = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'.schema\'"')
    log.append(("schema", r.get("command_output", "")))

    # List expenses before
    schema_output = r.get("command_output", "")
    # Find the expense table name from schema
    table_match = re.findall(r'CREATE TABLE\s+`?(\w+)`?', schema_output)
    log.append(("tables_found", str(table_match)))

    # Try to find the right table and column
    for table in table_match:
        r = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'SELECT * FROM {table} LIMIT 3\'"')
        output = r.get("command_output", "")
        log.append((f"sample_{table}", output))
        if "Taxi" in output or "taxi" in output:
            # Found the table with our expense
            # Get column names
            r2 = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'PRAGMA table_info({table})\'"')
            log.append((f"columns_{table}", r2.get("command_output", "")))

            # Delete by name (try common column names)
            for col in ["name", "title", "description", "expense_name"]:
                r3 = run_adb(base_url,
                    f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db}'
                    f" 'DELETE FROM {table} WHERE {col}=\\\"Taxi Fare\\\"'\"")
                output3 = r3.get("command_output", "")
                log.append((f"delete_{table}_{col}", output3))
                if "Error" not in output3 and "no such column" not in output3.lower():
                    break

            # Verify
            r4 = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'SELECT * FROM {table}\'"')
            log.append((f"after_{table}", r4.get("command_output", "")))
            break

    r = finish_task(base_url, "Deleted Taxi Fare from Pro Expense")
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


def task_92_query_next_event(base_url):
    """Query next upcoming event in Simple Calendar Pro."""
    log = []

    # Get current time on device
    r = run_adb(base_url, 'adb shell date +%s')
    log.append(("current_time", r.get("command_output", "")))
    now_str = r.get("command_output", "").strip()
    # Parse current timestamp
    now_ts = 0
    for line in now_str.split("\n"):
        line = line.strip()
        if line.isdigit():
            now_ts = int(line)
            break

    # Get events schema
    r = run_adb(base_url, 'adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \'.schema events\'"')
    log.append(("schema", r.get("command_output", "")))

    # Query upcoming events (try both seconds and milliseconds)
    r = run_adb(base_url,
        f'adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db'
        f" 'SELECT title, start_ts FROM events WHERE start_ts > {now_ts} ORDER BY start_ts ASC LIMIT 5'\"")
    output = r.get("command_output", "")
    log.append(("upcoming_sec", output))

    answer_titles = []
    if output.strip() and "|" in output:
        # Parse pipe-separated results
        for line in output.strip().split("\n"):
            line = line.strip()
            if "|" in line:
                title = line.split("|")[0].strip()
                if title:
                    answer_titles.append(title)

    if not answer_titles:
        # Try milliseconds
        r = run_adb(base_url,
            f'adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db'
            f" 'SELECT title, start_ts FROM events WHERE start_ts > {now_ts * 1000} ORDER BY start_ts ASC LIMIT 5'\"")
        output = r.get("command_output", "")
        log.append(("upcoming_ms", output))
        for line in output.strip().split("\n"):
            line = line.strip()
            if "|" in line:
                title = line.split("|")[0].strip()
                if title:
                    answer_titles.append(title)

    if not answer_titles:
        # Fallback: get ALL events sorted
        r = run_adb(base_url,
            'adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db'
            " 'SELECT title, start_ts FROM events ORDER BY start_ts ASC'\"")
        output = r.get("command_output", "")
        log.append(("all_events", output))
        # The "next" event is ambiguous; get the first one with the smallest start_ts > now
        for line in output.strip().split("\n"):
            line = line.strip()
            if "|" in line:
                parts = line.split("|")
                title = parts[0].strip()
                ts = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
                if ts > now_ts or ts > now_ts * 1000:
                    answer_titles.append(title)
                    break

    # Find events with the same earliest start_ts (multiple events at same time)
    # Task says "next upcoming event" — return only the first one
    answer = answer_titles[0] if answer_titles else "No upcoming events"
    log.append(("answer", answer))

    # Info retrieval task: use answer_task to set interaction_cache
    r = answer_task(base_url, answer)
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


def task_49_deduplicate_expenses(base_url):
    """Delete duplicate expenses, keep one of each."""
    log = []

    # Discover DB
    r = run_adb(base_url, 'adb shell "ls /data/data/com.arduia.expense/databases/"')
    log.append(("ls_db", r.get("command_output", "")))

    # Find the right database
    db = None
    for db_name in ["accounting.db", "expense.db", "pro_expense.db", "database"]:
        r = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db_name} \'.tables\'"')
        output = r.get("command_output", "")
        log.append((f"tables_{db_name}", output))
        if output.strip() and "Error" not in output and "unable" not in output.lower():
            db = db_name
            break
    if not db:
        db = "accounting.db"

    # Get full schema
    r = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'.schema\'"')
    schema = r.get("command_output", "")
    log.append(("schema", schema))

    # Find expense table
    tables = re.findall(r'CREATE TABLE\s+`?(\w+)`?', schema)
    expense_table = None
    for t in tables:
        r = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'SELECT * FROM {t} LIMIT 5\'"')
        output = r.get("command_output", "")
        log.append((f"sample_{t}", output))
        if output.strip() and "Error" not in output:
            # Check if this looks like an expense table (has multiple rows)
            lines = [l for l in output.strip().split("\n") if l.strip()]
            if len(lines) >= 2:
                expense_table = t
                break

    if not expense_table:
        expense_table = tables[0] if tables else "expense"

    # Get column info
    r = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'PRAGMA table_info({expense_table})\'"')
    columns_output = r.get("command_output", "")
    log.append(("columns", columns_output))

    # Parse column names
    col_names = []
    for line in columns_output.strip().split("\n"):
        parts = line.strip().split("|")
        if len(parts) >= 2:
            col_names.append(parts[1])
    log.append(("col_names", str(col_names)))

    # List all expenses before
    r = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'SELECT * FROM {expense_table}\'"')
    log.append(("before", r.get("command_output", "")))

    # Build dedup query using all non-ID columns
    # Typically: keep MIN(rowid) for each unique combination of name, amount, date, etc.
    # Exclude likely auto-increment ID columns
    group_cols = [c for c in col_names if c.lower() not in ('id', 'rowid', '_id', 'expense_id', 'expenseid')]
    if not group_cols:
        group_cols = col_names[1:]  # skip first (likely ID)

    group_by = ", ".join(group_cols)

    # Get the primary key column
    pk_col = col_names[0] if col_names else "rowid"

    # Delete duplicates keeping the one with MIN pk
    delete_sql = (
        f"DELETE FROM {expense_table} WHERE {pk_col} NOT IN "
        f"(SELECT MIN({pk_col}) FROM {expense_table} GROUP BY {group_by})"
    )
    log.append(("delete_sql", delete_sql))

    r = run_adb(base_url,
        f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'{delete_sql}\'"')
    log.append(("delete", r.get("command_output", "")))

    # Verify
    r = run_adb(base_url, f'adb shell "sqlite3 /data/data/com.arduia.expense/databases/{db} \'SELECT * FROM {expense_table}\'"')
    log.append(("after", r.get("command_output", "")))

    r = finish_task(base_url, "Deduplicated expenses, kept one of each unique expense")
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


def task_12_delete_all_markor_notes(base_url):
    """Delete all Markor notes."""
    log = []

    r = run_adb(base_url, 'adb shell ls /storage/emulated/0/Documents/markor/')
    log.append(("ls_before", r.get("command_output", "")))

    r = run_adb(base_url, 'adb shell rm -f /storage/emulated/0/Documents/markor/*.md')
    log.append(("delete_md", r.get("command_output", "")))

    # Also delete .txt files just in case
    r = run_adb(base_url, 'adb shell rm -f /storage/emulated/0/Documents/markor/*.txt')
    log.append(("delete_txt", r.get("command_output", "")))

    r = run_adb(base_url, 'adb shell ls /storage/emulated/0/Documents/markor/')
    log.append(("ls_after", r.get("command_output", "")))

    r = finish_task(base_url, "Deleted all Markor notes")
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


def task_3_delete_three_broccoli_recipes(base_url):
    """Delete 3 specific Broccoli recipes."""
    log = []

    # List recipes before
    r = run_adb(base_url, 'adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \'SELECT recipeId, title FROM recipes\'"')
    log.append(("before", r.get("command_output", "")))

    # Delete each recipe individually (more reliable than IN clause with quoting)
    for recipe in ["Chicken Caesar Salad Wrap", "Kale and Quinoa Salad", "Greek Salad Pita Pockets"]:
        escaped = recipe.replace('"', '\\"')
        r = run_adb(base_url,
            f'adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli'
            f" 'DELETE FROM recipes WHERE title=\\\"{escaped}\\\"'\"")
        log.append((f"delete_{recipe[:15]}", r.get("command_output", "")))

    # Verify
    r = run_adb(base_url, 'adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \'SELECT recipeId, title FROM recipes\'"')
    log.append(("after", r.get("command_output", "")))

    r = finish_task(base_url, "Deleted 3 recipes from Broccoli")
    reward = r.get("reward", 0.0)
    log.append(("finish", f"reward={reward}"))
    return reward, log


# ---------------------------------------------------------------------------
# Task registry
# ---------------------------------------------------------------------------

TASKS = [
    {"task_id": 4,  "seed": 7, "name": "Delete Broccoli recipe",       "fn": task_4_delete_broccoli_recipe},
    {"task_id": 5,  "seed": 7, "name": "Delete calendar events",       "fn": task_5_delete_calendar_events},
    {"task_id": 9,  "seed": 7, "name": "Create contact David Li",      "fn": task_9_create_contact},
    {"task_id": 13, "seed": 7, "name": "Delete Markor note",           "fn": task_13_delete_markor_note},
    {"task_id": 16, "seed": 7, "name": "WiFi + open contacts",         "fn": task_16_wifi_and_contacts},
    {"task_id": 11, "seed": 7, "name": "Delete expense Taxi Fare",     "fn": task_11_delete_expense},
    {"task_id": 92, "seed": 7, "name": "Query next calendar event",    "fn": task_92_query_next_event},
    {"task_id": 49, "seed": 7, "name": "Deduplicate expenses",         "fn": task_49_deduplicate_expenses},
    {"task_id": 12, "seed": 7, "name": "Delete all Markor notes",      "fn": task_12_delete_all_markor_notes},
    {"task_id": 3,  "seed": 7, "name": "Delete 3 Broccoli recipes",    "fn": task_3_delete_three_broccoli_recipes},
]

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_task_on_container(task_def: dict, container: dict) -> dict:
    """Reset container to task, run commands, return result."""
    base_url = container["url"]
    task_id = task_def["task_id"]
    seed = task_def["seed"]
    name = task_def["name"]

    print(f"\n{'='*60}")
    print(f"TASK {task_id} (seed={seed}): {name}")
    print(f"Container: {container['name']} ({base_url})")
    print(f"{'='*60}")

    # Reset
    print(f"  Resetting to task_id={task_id}, seed={seed}...")
    try:
        reset_resp = reset_task(base_url, task_id, seed)
        print(f"  Reset OK. Task: {reset_resp.get('info', {}).get('task', 'N/A')[:80]}")
    except Exception as e:
        print(f"  RESET FAILED: {e}")
        return {"task_id": task_id, "name": name, "reward": 0.0, "error": str(e), "log": []}

    # Run task commands
    try:
        reward, log = task_def["fn"](base_url)
    except Exception as e:
        print(f"  EXECUTION FAILED: {e}")
        import traceback
        traceback.print_exc()
        return {"task_id": task_id, "name": name, "reward": 0.0, "error": str(e), "log": []}

    # Print log
    for step_name, step_output in log:
        output_preview = str(step_output)[:200].replace("\n", " | ")
        print(f"  [{step_name}] {output_preview}")

    status = "SUCCESS" if reward > 0 else "FAIL"
    print(f"\n  >>> REWARD: {reward} ({status})")

    return {"task_id": task_id, "name": name, "reward": reward, "log": log}


def main():
    parser = argparse.ArgumentParser(description="Verify ADB commands for 10 AndroidWorld tasks")
    parser.add_argument("--pool-size", type=int, default=2, help="Number of containers to use")
    parser.add_argument("--image", default="androidworld:full_adb_agent", help="Docker image")
    parser.add_argument("--base-env-id", type=int, default=100, help="Starting env_id (avoid conflicts)")
    parser.add_argument("--tasks", type=str, default=None, help="Comma-separated task IDs to run (default: all)")
    parser.add_argument("--output", type=str, default="./verify_results.json", help="Output file")
    args = parser.parse_args()

    # Filter tasks if specified
    tasks_to_run = TASKS
    if args.tasks:
        task_ids = [int(x) for x in args.tasks.split(",")]
        tasks_to_run = [t for t in TASKS if t["task_id"] in task_ids]

    print(f"Will run {len(tasks_to_run)} tasks using {args.pool_size} containers")
    print(f"Image: {args.image}")

    # Start containers
    containers = []
    for i in range(args.pool_size):
        env_id = args.base_env_id + i
        print(f"Starting container env_id={env_id}...")
        try:
            c = start_container(env_id, args.image)
            containers.append(c)
            print(f"  Started {c['name']} → {c['url']}")
        except Exception as e:
            print(f"  Failed: {e}")

    if not containers:
        print("No containers started. Exiting.")
        return 1

    # Wait for all containers to be healthy
    print(f"\nWaiting for {len(containers)} containers to be healthy...")
    healthy = []
    for c in containers:
        print(f"  Checking {c['name']}...", end=" ", flush=True)
        if wait_for_healthy(c, timeout=300):
            print("OK")
            healthy.append(c)
        else:
            print("TIMEOUT - skipping")
            stop_container(c)

    if not healthy:
        print("No healthy containers. Exiting.")
        for c in containers:
            stop_container(c)
        return 1

    containers = healthy
    print(f"\n{len(containers)} containers ready. Running tasks...\n")

    # Run tasks round-robin across containers
    results = []
    for i, task_def in enumerate(tasks_to_run):
        container = containers[i % len(containers)]
        result = run_task_on_container(task_def, container)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total = len(results)
    successes = sum(1 for r in results if r["reward"] > 0)
    for r in results:
        status = "OK" if r["reward"] > 0 else "FAIL"
        error = f" (error: {r.get('error', '')[:50]})" if r.get("error") else ""
        print(f"  task_id={r['task_id']:3d} [{status:4s}] {r['name']}{error}")

    print(f"\nTotal: {successes}/{total} ({100*successes/max(total,1):.0f}%)")
    print(f"{'='*60}")

    # Save results
    output_file = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    # Convert log tuples to lists for JSON serialization
    for r in results:
        if "log" in r:
            r["log"] = [[k, v] for k, v in r["log"]]
    with open(output_file, "w") as f:
        json.dump({"results": results, "summary": {"total": total, "successes": successes}}, f, indent=2)
    print(f"Results saved to {output_file}")

    # Cleanup
    print("\nCleaning up containers...")
    for c in containers:
        stop_container(c)
        print(f"  Removed {c['name']}")

    return 0 if successes == total else 1


if __name__ == "__main__":
    sys.exit(main())
