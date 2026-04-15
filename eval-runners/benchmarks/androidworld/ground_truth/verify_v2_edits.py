#!/usr/bin/env python3
"""
Verify v2 ground truth edits against a live AndroidWorld container.

Tests the specific changes made in androidworld_ground_truth_reference_v2.md:
1. SMS tasks: content insert with default SMS app swap
2. VLC tasks: PRAGMA writable_schema trigger drop + correct columns
3. Task 083: Download/ path (no 's') with correct quoting
4. Calendar: full INSERT with all 26 columns
5. Schema inspection: .schema / .tables commands work

Usage:
    python verify_v2_edits.py --server-port 5000
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests

SEED = 7
RESET_TIMEOUT = 180
ADB_TIMEOUT = 60
FINISH_TIMEOUT = 120


# ─── Container helpers ──────────────────────────────────────────────────────

def container_reset(base_url: str, task_id: int) -> Dict:
    resp = requests.post(
        f"{base_url}/reset",
        json={"seed": SEED, "options": {"task_id": task_id}},
        timeout=RESET_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def step_adb(base_url: str, command: str, timeout: int = ADB_TIMEOUT) -> str:
    resp = requests.post(
        f"{base_url}/step_adb",
        json={"command": command},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("command_output", "")


def container_finish(base_url: str, desc: str) -> Dict:
    resp = requests.post(
        f"{base_url}/step_adb",
        json={"command": f"FINISH(content='{desc}')"},
        timeout=FINISH_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def container_answer(base_url: str, answer_text: str) -> Dict:
    resp = requests.post(
        f"{base_url}/step",
        json={"action": {"action_type": "answer", "text": answer_text},
              "thought": f"Answer: {answer_text}"},
        timeout=FINISH_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


# ─── Parse helpers ───────────────────────────────────────────────────────────

def parse_media_fields(output: str) -> Dict[str, str]:
    """Parse content query output like 'Row: 0 _id=123, duration=456, ...'"""
    fields = {}
    all_keys = ['_id', 'title', 'duration', '_data', 'album_id', 'album',
                'artist_id', 'artist', 'date_modified']
    sorted_keys = sorted(all_keys, key=len, reverse=True)
    next_key_pattern = '|'.join(re.escape(k) for k in sorted_keys)
    for key in all_keys:
        m = re.search(
            rf'(?:^|[\s,]){re.escape(key)}=(.*?)(?:,\s*(?:{next_key_pattern})=|$)',
            output)
        if m:
            fields[key] = m.group(1).strip()
    return fields


# ─── Test Result ─────────────────────────────────────────────────────────────

class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.reward: float = 0
        self.passed: bool = False
        self.error: str = ""

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name} (reward={self.reward})"


# ─── Test 1: Schema inspection ──────────────────────────────────────────────

def test_schema_inspection(base_url: str) -> TestResult:
    """Verify .schema commands work for all app databases."""
    result = TestResult("Schema inspection (all apps)")
    print("  Testing .schema/.tables for all app databases...")

    schemas = [
        ("Broccoli", "/data/data/com.flauschcode.broccoli/databases/broccoli", ".schema recipes"),
        ("SimpleCalendar", "/data/data/com.simplemobiletools.calendar.pro/databases/events.db", ".schema events"),
        ("ProExpense", "/data/data/com.arduia.expense/databases/accounting.db", ".schema expense"),
        ("RetroMusic(playlist)", "/data/data/code.name.monkey.retromusic/databases/playlist.db", ".tables"),
        ("RetroMusic(playback)", "/data/data/code.name.monkey.retromusic/databases/playlist.db", ".schema SongEntity"),
        ("OsmAnd", "/data/data/net.osmand/databases/map_markers_db", ".schema map_markers"),
        ("Tasks", "/data/data/org.tasks/databases/database", ".schema tasks"),
        ("OpenTracks", "/data/data/de.dennisguse.opentracks/databases/database.db", ".schema tracks"),
        ("Joplin", "/data/data/net.cozic.joplin/databases/joplin.sqlite", ".schema notes"),
    ]

    try:
        container_reset(base_url, 7)
    except Exception as e:
        result.error = f"Reset failed: {e}"
        return result

    all_ok = True
    for name, db_path, schema_cmd in schemas:
        try:
            cmd = f'adb shell "sqlite3 {db_path} \\"{schema_cmd}\\""'
            out = step_adb(base_url, cmd)
            has_output = bool(out.strip())
            has_error = "Error" in out or "error" in out.lower()
            ok = has_output and not has_error
            status = "OK" if ok else "FAIL"
            print(f"    {name}: {status} — {out.strip()[:80]}")
            if not ok:
                all_ok = False
        except Exception as e:
            print(f"    {name}: ERROR — {e}")
            all_ok = False

    result.passed = all_ok
    result.reward = 1.0 if all_ok else 0.0
    return result


# ─── Test 2: SMS send with default app swap (Task 067) ──────────────────────

def test_sms_send(base_url: str) -> TestResult:
    """Task 067 (SimpleSmsSend): content insert with default SMS app swap."""
    result = TestResult("Task 067: SimpleSmsSend (content insert + app swap)")

    reset = container_reset(base_url, 67)
    goal = reset["info"]["task"]
    print(f"  Goal: {goal[:80]}")

    m = re.search(r"to\s+(\S+)\s+with message:\s+(.*?)(?:\s+in Simple SMS|\s*$)", goal, re.DOTALL)
    if not m:
        result.error = f"Could not parse goal"
        print(f"    ERROR: {result.error}")
        return result

    number, message = m.group(1), m.group(2).strip()

    try:
        # Step 1: Set shell as default SMS app
        step_adb(base_url, "adb shell settings put secure sms_default_application com.android.shell")
        print("    Step 1: Set shell as default SMS app")

        # Step 2: Content insert
        cmd = (f'adb shell "content insert --uri content://sms '
               f'--bind address:s:{number} '
               f'--bind \\\"body:s:{message}\\\" '
               f'--bind type:i:2 '
               f'--bind date:l:$(date +%s)000 '
               f'--bind read:i:1 '
               f'--bind seen:i:1"')
        out = step_adb(base_url, cmd)
        print(f"    Step 2: content insert → {repr(out[:60])}")

        # Step 3: Restore default SMS app
        step_adb(base_url, "adb shell settings put secure sms_default_application com.simplemobiletools.smsmessenger")
        print("    Step 3: Restored default SMS app")

        # Step 4: Launch SMS app
        step_adb(base_url, "adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity")
        print("    Step 4: Launched SMS app")

        finish = container_finish(base_url, "verify sms send")
        result.reward = finish.get("reward", 0)
        result.passed = (result.reward == 1.0)
        print(f"    REWARD: {result.reward} {'PASS' if result.passed else 'FAIL'}")
    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")
    return result


# ─── Test 3: SMS reply (Task 038) ───────────────────────────────────────────

def test_sms_reply(base_url: str) -> TestResult:
    """Task 038 (SimpleSmsReply): content insert with default SMS app swap."""
    result = TestResult("Task 038: SimpleSmsReply (content insert + app swap)")

    reset = container_reset(base_url, 38)
    goal = reset["info"]["task"]
    print(f"  Goal: {goal[:80]}")

    m = re.search(r"Reply to\s+(\S+)\s+with message:\s+(.*?)(?:\s+in Simple SMS|\s*$)", goal, re.DOTALL)
    if not m:
        result.error = f"Could not parse goal"
        print(f"    ERROR: {result.error}")
        return result

    number, message = m.group(1), m.group(2).strip()

    try:
        step_adb(base_url, "adb shell settings put secure sms_default_application com.android.shell")
        cmd = (f'adb shell "content insert --uri content://sms '
               f'--bind address:s:{number} '
               f'--bind \\\"body:s:{message}\\\" '
               f'--bind type:i:2 '
               f'--bind date:l:$(date +%s)000 '
               f'--bind read:i:1 '
               f'--bind seen:i:1"')
        out = step_adb(base_url, cmd)
        print(f"    content insert → {repr(out[:60])}")
        step_adb(base_url, "adb shell settings put secure sms_default_application com.simplemobiletools.smsmessenger")
        step_adb(base_url, "adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity")

        finish = container_finish(base_url, "verify sms reply")
        result.reward = finish.get("reward", 0)
        result.passed = (result.reward == 1.0)
        print(f"    REWARD: {result.reward} {'PASS' if result.passed else 'FAIL'}")
    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")
    return result


# ─── Test 4: SMS reply most recent (Task 065) ───────────────────────────────

def test_sms_reply_most_recent(base_url: str) -> TestResult:
    """Task 065: Query most recent address, then content insert."""
    result = TestResult("Task 065: SimpleSmsReplyMostRecent (content insert + app swap)")

    reset = container_reset(base_url, 65)
    goal = reset["info"]["task"]
    print(f"  Goal: {goal[:80]}")

    m = re.search(r"with message:\s+(.*?)(?:\s+in Simple SMS|\s*$)", goal, re.DOTALL)
    if not m:
        result.error = "Could not parse goal"
        print(f"    ERROR: {result.error}")
        return result
    message = m.group(1).strip()

    try:
        # Query most recent incoming SMS address
        db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
        out = step_adb(base_url,
            f'adb shell "sqlite3 {db} \\"SELECT address FROM sms WHERE type=1 ORDER BY date DESC LIMIT 1;\\""')
        number = out.strip()
        print(f"    Most recent incoming from: {number}")

        # SMS insert with app swap
        step_adb(base_url, "adb shell settings put secure sms_default_application com.android.shell")
        cmd = (f'adb shell "content insert --uri content://sms '
               f'--bind address:s:{number} '
               f'--bind \\\"body:s:{message}\\\" '
               f'--bind type:i:2 '
               f'--bind date:l:$(date +%s)000 '
               f'--bind read:i:1 '
               f'--bind seen:i:1"')
        step_adb(base_url, cmd)
        step_adb(base_url, "adb shell settings put secure sms_default_application com.simplemobiletools.smsmessenger")
        step_adb(base_url, "adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity")

        finish = container_finish(base_url, "verify sms reply most recent")
        result.reward = finish.get("reward", 0)
        result.passed = (result.reward == 1.0)
        print(f"    REWARD: {result.reward} {'PASS' if result.passed else 'FAIL'}")
    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")
    return result


# ─── Test 5: SMS resend (Task 066) ──────────────────────────────────────────

def test_sms_resend(base_url: str) -> TestResult:
    """Task 066: Query last sent, then content insert."""
    result = TestResult("Task 066: SimpleSmsResend (content insert + app swap)")

    reset = container_reset(base_url, 66)
    goal = reset["info"]["task"]
    print(f"  Goal: {goal[:80]}")

    try:
        db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
        out = step_adb(base_url,
            f'adb shell "sqlite3 {db} \\"SELECT address, body FROM sms WHERE type=2 ORDER BY date DESC LIMIT 1;\\""')
        parts = out.strip().split("|", 1)
        number = parts[0] if parts else ""
        body = parts[1] if len(parts) > 1 else ""
        print(f"    Last sent: {number} → {body[:40]}")

        step_adb(base_url, "adb shell settings put secure sms_default_application com.android.shell")
        body_esc = body.replace("'", "''")
        cmd = (f'adb shell "content insert --uri content://sms '
               f'--bind address:s:{number} '
               f'--bind \\\"body:s:{body_esc}\\\" '
               f'--bind type:i:2 '
               f'--bind date:l:$(date +%s)000 '
               f'--bind read:i:1 '
               f'--bind seen:i:1"')
        step_adb(base_url, cmd)
        step_adb(base_url, "adb shell settings put secure sms_default_application com.simplemobiletools.smsmessenger")
        step_adb(base_url, "adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity")

        finish = container_finish(base_url, "verify sms resend")
        result.reward = finish.get("reward", 0)
        result.passed = (result.reward == 1.0)
        print(f"    REWARD: {result.reward} {'PASS' if result.passed else 'FAIL'}")
    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")
    return result


# ─── Test 6: VLC trigger drop (Task 072) ────────────────────────────────────

def test_vlc_trigger_drop(base_url: str) -> TestResult:
    """Task 072: drop triggers, use real schema columns."""
    result = TestResult("Task 072: VlcCreatePlaylist (trigger drop + real schema)")

    reset = container_reset(base_url, 72)
    goal = reset["info"]["task"]
    print(f"  Goal: {goal[:80]}")

    try:
        db = "/data/data/org.videolan.vlc/app_db/vlc_media.db"

        # Stop VLC
        step_adb(base_url, "adb shell am force-stop org.videolan.vlc")

        # Inspect schema (expect error)
        out = step_adb(base_url, f'adb shell "sqlite3 {db} \\".schema\\" 2>&1 | head -3"')
        print(f"    Schema inspect: {out.strip()[:100]}")

        # Drop ALL triggers
        step_adb(base_url,
            f'adb shell "sqlite3 {db} \\"PRAGMA writable_schema=ON; '
            f"DELETE FROM sqlite_master WHERE type='trigger'; "
            f'PRAGMA writable_schema=OFF;\\""')
        print("    Dropped triggers")

        # Verify .tables works
        out = step_adb(base_url, f'adb shell "sqlite3 {db} \\".tables\\""')
        print(f"    Tables: {out.strip()[:100]}")

        # Parse playlist name and files from goal
        pl_match = re.search(r'"([^"]+)"', goal)
        pl_name = pl_match.group(1) if pl_match else "Test"
        files = re.findall(r'[\w.]+\.mp4', goal)

        # Create playlist with creation_date
        step_adb(base_url,
            f'adb shell "sqlite3 {db} \\"INSERT INTO Playlist (name, creation_date) '
            f"VALUES ('{pl_name}', strftime('%s','now'));\\\"\"")

        # Get playlist ID
        out = step_adb(base_url,
            f'adb shell "sqlite3 {db} \\"SELECT MAX(id_playlist) FROM Playlist;\\""')
        pl_id = out.strip() or "1"
        print(f"    Playlist '{pl_name}' ID: {pl_id}")

        # Add each media file with import_type
        for pos, fname in enumerate(files):
            step_adb(base_url,
                f'adb shell "sqlite3 {db} \\"INSERT INTO Media (filename, import_type) '
                f"VALUES ('{fname}', 0);\\\"\"")
            out = step_adb(base_url,
                f'adb shell "sqlite3 {db} \\"SELECT MAX(id_media) FROM Media;\\""')
            mid = out.strip() or str(pos + 1)
            step_adb(base_url,
                f'adb shell "sqlite3 {db} \\"INSERT INTO PlaylistMediaRelation '
                f"(playlist_id, media_id, position) VALUES ({pl_id}, {mid}, {pos});\\\"\"")
            print(f"    {fname} → media_id={mid}, pos={pos}")

        finish = container_finish(base_url, "verify vlc playlist")
        result.reward = finish.get("reward", 0)
        result.passed = (result.reward == 1.0)
        print(f"    REWARD: {result.reward} {'PASS' if result.passed else 'FAIL'}")
    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")
    return result


# ─── Test 7: Calendar full INSERT (Task 085) ────────────────────────────────

def test_calendar_full_insert(base_url: str) -> TestResult:
    """Task 085: full INSERT with all 26 columns."""
    result = TestResult("Task 085: SimpleCalendarAddOneEvent (full 26-col INSERT)")

    reset = container_reset(base_url, 85)
    goal = reset["info"]["task"]
    print(f"  Goal: {goal[:80]}")

    try:
        db = "/data/data/com.simplemobiletools.calendar.pro/databases/events.db"
        step_adb(base_url, "adb shell am force-stop com.simplemobiletools.calendar.pro")

        # Schema inspection
        out = step_adb(base_url, f'adb shell "sqlite3 {db} \\".schema events\\""')
        print(f"    Schema: {out.strip()[:100]}")

        # Full INSERT with all 26 columns
        sql = (
            "INSERT INTO events (start_ts, end_ts, title, location, description, "
            "reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, "
            "reminder_1_type, reminder_2_type, reminder_3_type, "
            "repeat_interval, repeat_rule, repeat_limit, "
            "repetition_exceptions, attendees, import_id, time_zone, "
            "flags, event_type, parent_id, last_updated, source, "
            "availability, color, type) "
            "VALUES (1698206400, 1698210000, "
            "'Review session for Project X', '', "
            "'We will finalize business objectives.', "
            "-1, -1, -1, 0, 0, 0, 0, 0, 0, "
            "'', '', '', '', "
            "0, 0, 0, strftime('%s','now'), '', 0, 0, 0);"
        )
        out = step_adb(base_url, f'adb shell "sqlite3 {db} \\"{sql}\\""')
        print(f"    INSERT result: {repr(out.strip()[:80])}")

        finish = container_finish(base_url, "verify calendar insert")
        result.reward = finish.get("reward", 0)
        result.passed = (result.reward == 1.0)
        print(f"    REWARD: {result.reward} {'PASS' if result.passed else 'FAIL'}")
    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")
    return result


# ─── Test 8: RetroSavePlaylist Download/ path (Task 083) ────────────────────

def test_retro_save_playlist(base_url: str) -> TestResult:
    """Task 083: playlist + m3u in Download/ (no 's')."""
    result = TestResult("Task 083: RetroSavePlaylist (Download/ path)")

    reset = container_reset(base_url, 83)
    goal = reset["info"]["task"]
    print(f"  Goal: {goal[:80]}")

    try:
        retro_db = "/data/data/code.name.monkey.retromusic/databases/playlist.db"

        step_adb(base_url, "adb shell am force-stop code.name.monkey.retromusic")

        # Schema inspection
        out = step_adb(base_url, f'adb shell "sqlite3 {retro_db} \\".schema PlaylistEntity\\""')
        print(f"    PlaylistEntity: {out.strip()[:80]}")

        # Ensure Download dir (no 's')
        step_adb(base_url, "adb shell mkdir -p /storage/emulated/0/Download")

        # Parse playlist name and songs
        pl_match = re.search(r'"([^"]+)"', goal)
        pl_name = pl_match.group(1) if pl_match else "Test"
        songs_match = re.search(r'following songs.*?:\s*(.*?)\.?\s*Then export', goal, re.DOTALL)
        songs = [s.strip() for s in songs_match.group(1).split(",")] if songs_match else []

        # Create playlist
        step_adb(base_url,
            f'adb shell "sqlite3 {retro_db} \\"INSERT INTO PlaylistEntity (playlist_name) '
            f"VALUES ('{pl_name}');\\\"\"")
        out = step_adb(base_url,
            f'adb shell "sqlite3 {retro_db} \\"SELECT MAX(playlist_id) FROM PlaylistEntity;\\""')
        pl_id = out.strip() or "1"
        print(f"    Playlist '{pl_name}' ID: {pl_id}")

        # For each song
        for song in songs:
            song = song.strip()
            if not song:
                continue

            # Query MediaStore
            out = step_adb(base_url,
                f'adb shell "content query --uri content://media/external/audio/media '
                f"--projection _id:duration:_data:album_id:album:artist_id:artist:date_modified "
                f"--where \\\"title='{song}'\\\" | head -1\"")
            fields = parse_media_fields(out)
            sid = fields.get('_id', '0')
            dur = fields.get('duration', '0')
            data = fields.get('_data', '').replace("'", "''")
            aid = fields.get('album_id', '0')
            alb = fields.get('album', '').replace("'", "''")
            arid = fields.get('artist_id', '0')
            art = fields.get('artist', '').replace("'", "''")
            dmod = fields.get('date_modified', '0')
            print(f"    '{song}': id={sid}, dur={dur}")

            # Insert into SongEntity
            step_adb(base_url,
                f'adb shell "sqlite3 {retro_db} \\"INSERT INTO SongEntity '
                f"(playlist_creator_id, id, title, track_number, year, duration, data, "
                f"date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) "
                f"VALUES ({pl_id}, {sid}, '{song}', 0, 0, {dur}, '{data}', {dmod}, "
                f"{aid}, '{alb}', {arid}, '{art}', '', '');\\\"\"")

            # Append to m3u in Download/ (no 's') — quote the full path to handle spaces
            data_raw = fields.get('_data', '')
            step_adb(base_url,
                f"adb shell \"echo '{data_raw}' >> '/storage/emulated/0/Download/{pl_name}.m3u'\"")

        # Verify m3u exists
        out = step_adb(base_url,
            f"adb shell \"cat '/storage/emulated/0/Download/{pl_name}.m3u'\"")
        print(f"    m3u content: {out.strip()[:100]}")

        finish = container_finish(base_url, "verify retro save playlist")
        result.reward = finish.get("reward", 0)
        result.passed = (result.reward == 1.0)
        print(f"    REWARD: {result.reward} {'PASS' if result.passed else 'FAIL'}")
    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")
    return result


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Verify v2 ground truth edits")
    parser.add_argument("--server-port", type=int, default=5000,
                        help="Container server port (default 5000)")
    args = parser.parse_args()

    base_url = f"http://localhost:{args.server_port}"

    try:
        r = requests.get(f"{base_url}/health", timeout=10)
        print(f"Container healthy: {r.json()}\n")
    except Exception as e:
        print(f"Container not healthy: {e}")
        sys.exit(1)

    print("=" * 70)
    print("VERIFYING v2 GROUND TRUTH EDITS (post-fix)")
    print("=" * 70)

    results = []

    tests = [
        ("Test 1: Schema Inspection", test_schema_inspection),
        ("Test 2: SMS Send (Task 067)", test_sms_send),
        ("Test 3: SMS Reply (Task 038)", test_sms_reply),
        ("Test 4: SMS Reply Most Recent (Task 065)", test_sms_reply_most_recent),
        ("Test 5: SMS Resend (Task 066)", test_sms_resend),
        ("Test 6: VLC Trigger Drop (Task 072)", test_vlc_trigger_drop),
        ("Test 7: Calendar Full INSERT (Task 085)", test_calendar_full_insert),
        ("Test 8: RetroSavePlaylist (Task 083)", test_retro_save_playlist),
    ]

    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        results.append(test_fn(base_url))

    # Summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        extra = f" ({r.error})" if r.error else ""
        print(f"  [{status}] {r.name}{extra}")
    print(f"\n  Total: {passed}/{total} passed")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
