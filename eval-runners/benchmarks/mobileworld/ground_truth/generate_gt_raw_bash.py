#!/usr/bin/env python3
"""
Generate raw-bash GT commands for all 117 MobileWorld GUI-only tasks.

Converts all action types to actual bash commands executable via
subprocess.run(cmd, shell=True) inside the MobileWorld container.

Output: gt_commands_raw_bash.json with format:
{
  "TaskName": [
    {"thought": "description", "cmd": "bash command"},
    ...
  ]
}

All commands are real bash — no custom action types (sql, write-file, etc.).
Mastodon $TOKEN is pre-resolved via a standard token discovery prefix.
"""

import json
import os
import re
import sys

# Mastodon token discovery steps (prepended to all Mastodon API tasks)
MASTODON_TOKEN_DISCOVERY = [
    {
        "thought": "Get Mastodon account IDs from device database",
        "cmd": 'adb shell "su 0 sqlite3 /data/data/org.joinmastodon.android.mastodon/databases/accounts.db \'SELECT id FROM accounts\'"',
    },
    {
        "thought": "Get access token for test user from Mastodon accounts database",
        "cmd": 'adb shell "su 0 sqlite3 /data/data/org.joinmastodon.android.mastodon/databases/accounts.db \'SELECT token FROM accounts WHERE id=\\\"10.0.2.2_115338428522805842\\\"\'"',
    },
]

# Mattermost wait step (for tasks that need Mattermost backend)
MATTERMOST_WAIT = {
    "thought": "Wait for Mattermost PostgreSQL to be ready",
    "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT 1"',
}


def convert_adb(cmd):
    """adb "adb shell ..." or adb --no-tree "adb shell ..." → adb shell ..."""
    if cmd.startswith("adb --no-tree "):
        inner = cmd[len("adb --no-tree "):].strip('" ')
    else:
        inner = cmd[len("adb "):].strip('" ')
    return inner


def convert_sql(cmd):
    """sql /db/path "QUERY" → adb shell "su 0 sqlite3 /db/path 'QUERY'" """
    parts = cmd[4:].strip().split(" ", 1)
    db_path = parts[0]
    query = parts[1].strip('" ') if len(parts) > 1 else ""
    # Escape single quotes in query for shell
    query_escaped = query.replace("'", "'\\''")
    return f"adb shell \"su 0 sqlite3 {db_path} '{query_escaped}'\""


def convert_write_file(cmd):
    """write-file /path 'content' → echo BASE64 | base64 -d > /tmp/f && adb push /tmp/f /path"""
    import base64
    rest = cmd[11:].strip()
    if " '" in rest:
        path, content = rest.split(" '", 1)
        content = content.rstrip("'")
    elif ' "' in rest:
        path, content = rest.split(' "', 1)
        content = content.rstrip('"')
    else:
        path = rest
        content = ""
    encoded = base64.b64encode(content.encode()).decode()
    return f"echo '{encoded}' | base64 -d > /tmp/_gt_write && adb push /tmp/_gt_write {path} && rm -f /tmp/_gt_write"


def convert_read_file(cmd):
    """read-file /path → adb shell cat /path"""
    path = cmd[10:].strip()
    return f"adb shell cat {path}"


def convert_find_files(cmd):
    """find-files /dir "pattern" → adb shell find /dir -name "pattern" """
    parts = cmd[11:].strip().split(" ", 1)
    directory = parts[0]
    pattern = parts[1].strip('" ') if len(parts) > 1 else "*"
    return f'adb shell find {directory} -name "{pattern}" 2>/dev/null'


def convert_exec(cmd):
    """exec "command" → command (unwrap quotes, unescape)"""
    inner = cmd[5:]
    if (inner.startswith('"') and inner.endswith('"')) or \
       (inner.startswith("'") and inner.endswith("'")):
        inner = inner[1:-1]
    inner = inner.replace('\\"', '"').replace("\\'", "'")
    return inner


def convert_http(cmd, token_var="$TOKEN"):
    """http METHOD URL --headers ... --data ... → curl command"""
    parts = cmd[5:].strip().split(" ", 1)
    method = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    url = rest.split(" --")[0].strip()

    # Collect headers
    all_headers = {}
    for hm in re.finditer(r'--headers\s+"([^"]*)"', rest):
        key_val = hm.group(1)
        if ":" in key_val:
            k, v = key_val.split(":", 1)
            all_headers[k.strip()] = v.strip()

    # Parse data
    data = ""
    dm = re.search(r"--data\s+'(.*)'$", rest, re.DOTALL)
    if dm:
        data = dm.group(1)
    elif "--data " in rest:
        data = rest.split("--data ")[1].strip('" ')

    # Handle file:// callbacks
    if url.startswith("file://"):
        file_path = url.replace("file://", "")
        filename = all_headers.get("X-Filename", "callback.json")
        return f"curl -s -X POST http://localhost:6800/task/callback -H 'Content-Type: application/json' -d '{{\"device\":\"emulator-5554\",\"callback_data\":{data}}}'"

    # Handle Mastodon API (10.0.2.2) → curl inside container
    if "10.0.2.2" in url:
        container_url = re.sub(r'https?://10\.0\.2\.2', 'https://localhost', url)
        curl_parts = [f"curl -sk -X {method}"]
        curl_parts.append('-H "Host: 10.0.2.2"')
        auth = all_headers.get("Authorization", "")
        if auth:
            curl_parts.append(f'-H "Authorization: {auth}"')
        elif token_var in cmd:
            curl_parts.append(f'-H "Authorization: Bearer {token_var}"')
        if data:
            curl_parts.append('-H "Content-Type: application/json"')
            data_escaped = data.replace("'", "'\\''")
            curl_parts.append(f"-d '{data_escaped}'")
        curl_parts.append(f'"{container_url}"')
        return " ".join(curl_parts)

    # Handle localhost:6800/step (answer submission)
    if "localhost:6800" in url and "/step" in url:
        return f"curl -s -X POST http://localhost:6800/step -H 'Content-Type: application/json' -d '{data}'"

    # Handle localhost:6800 (other MW server endpoints)
    if "localhost:6800" in url:
        curl_parts = [f"curl -s -X {method}"]
        if data:
            curl_parts.append("-H 'Content-Type: application/json'")
            curl_parts.append(f"-d '{data}'")
        curl_parts.append(f'"{url}"')
        return " ".join(curl_parts)

    return f"curl -s -X {method} '{url}'"


def convert_finish(cmd):
    """finish --status X --description "Y" → curl POST /step with answer (if short value)"""
    desc = ""
    if "--description " in cmd:
        desc = cmd.split("--description ")[1].strip('" ')
    if desc and len(desc) < 100:
        # Submit as answer
        desc_escaped = desc.replace('"', '\\"')
        return f'curl -s -X POST http://localhost:6800/step -H \'Content-Type: application/json\' -d \'{{"device":"emulator-5554","action":{{"action_type":"answer","text":"{desc_escaped}"}}}}\''
    return None  # No command needed for non-answer finish


def convert_bare_get(cmd):
    """GET /config/callback → curl"""
    endpoint = cmd[4:].strip()
    return f"curl -s http://localhost:6800{endpoint}"


def convert_bare_post(cmd):
    """POST /api/v1/media → curl (Mastodon media upload)"""
    endpoint = cmd[5:].strip()
    return f'curl -sk -X POST -H "Host: 10.0.2.2" -H "Authorization: Bearer $TOKEN" https://localhost{endpoint}'


def convert_command(cmd):
    """Convert a single GT command to raw bash."""
    if cmd.startswith("adb "):
        return convert_adb(cmd)
    elif cmd.startswith("sql "):
        return convert_sql(cmd)
    elif cmd.startswith("write-file "):
        return convert_write_file(cmd)
    elif cmd.startswith("read-file "):
        return convert_read_file(cmd)
    elif cmd.startswith("find-files "):
        return convert_find_files(cmd)
    elif cmd.startswith("exec "):
        return convert_exec(cmd)
    elif cmd.startswith("http "):
        return convert_http(cmd)
    elif cmd.startswith("finish "):
        return convert_finish(cmd)
    elif cmd.startswith("GET /"):
        return convert_bare_get(cmd)
    elif cmd.startswith("POST /"):
        return convert_bare_post(cmd)
    else:
        return cmd  # Unknown — pass through


def needs_mastodon_token(steps):
    """Check if any step references $TOKEN or Mastodon API."""
    for s in steps:
        cmd = s.get("cmd", s) if isinstance(s, dict) else s
        if "$TOKEN" in cmd or "10.0.2.2/api" in cmd:
            return True
    return False


def needs_mattermost(steps):
    """Check if any step references Mattermost docker exec."""
    for s in steps:
        cmd = s.get("cmd", s) if isinstance(s, dict) else s
        if "mattermost-docker" in cmd.lower():
            return True
    return False


def main():
    # Load existing JSON GT
    gt_path = os.path.join(os.path.dirname(__file__), "gt_commands_mwenv.json")
    with open(gt_path) as f:
        old_gt = json.load(f)

    # Load Python GT overrides from ground_truth_cli_finder.py
    # We'll use the existing JSON where available + add Python-only tasks
    # For Python-only tasks, we need to manually define the raw bash steps

    # Python-only tasks that need manual raw bash GT
    python_only_tasks = build_python_only_tasks()

    # Convert all tasks
    new_gt = {}
    all_tasks = set(old_gt.keys()) | set(python_only_tasks.keys())

    for task_name in sorted(all_tasks):
        if task_name in python_only_tasks:
            # Use the manually defined raw bash steps
            steps = python_only_tasks[task_name]
        elif task_name in old_gt:
            # Convert existing JSON commands to raw bash
            old_steps = old_gt[task_name]
            steps = []
            has_token = needs_mastodon_token(old_steps)
            has_mm = needs_mattermost(old_steps)

            # Add token discovery prefix if needed
            if has_token:
                steps.extend(MASTODON_TOKEN_DISCOVERY)

            # Add Mattermost wait if needed
            if has_mm:
                steps.append(MATTERMOST_WAIT)

            for s in old_steps:
                thought = s.get("thought", "") if isinstance(s, dict) else ""
                cmd = s.get("cmd", s) if isinstance(s, dict) else s

                bash_cmd = convert_command(cmd)
                if bash_cmd is None:
                    continue  # Skip non-answer finish commands

                # Replace $TOKEN placeholder with actual token extraction reference
                if "$TOKEN" in bash_cmd:
                    # The token was discovered in the prefix steps
                    # In the actual bash, it would be stored in a variable
                    # For SFT, show the actual curl with TOKEN placeholder
                    # (agent learns to substitute from discovery step output)
                    pass

                steps.append({"thought": thought, "cmd": bash_cmd})
        else:
            continue

        new_gt[task_name] = steps

    # Write output
    out_path = os.path.join(os.path.dirname(__file__), "gt_commands_raw_bash.json")
    with open(out_path, "w") as f:
        json.dump(new_gt, f, indent=2, ensure_ascii=False)

    print(f"Generated {len(new_gt)} tasks with raw bash commands")
    total_steps = sum(len(s) for s in new_gt.values())
    print(f"Total steps: {total_steps}")


def build_python_only_tasks():
    """Build raw bash GT for the 6 Python-only tasks + any overrides needed."""
    tasks = {}

    # --- MattermostIncidentEscalationTask ---
    tasks["MattermostIncidentEscalationTask"] = [
        {"thought": "Wait for Mattermost PostgreSQL", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT 1"'},
        {"thought": "Get Harry's user ID", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id FROM users WHERE username=\'harry\'"'},
        {"thought": "Get support-tickets channel ID", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id FROM channels WHERE name=\'support-tickets\'"'},
        {"thought": "Read support ticket messages", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT message FROM posts WHERE channelid=\'CHANNEL_ID\' AND deleteat=0 ORDER BY createat"'},
        {"thought": "Get team ID for channel creation", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id FROM teams WHERE name=\'neuralforge\'"'},
        {"thought": "Create incident-ticket-500 channel", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "INSERT INTO channels (id,createat,updateat,deleteat,teamid,type,displayname,name,header,purpose,lastpostat,totalmsgcount,extraupdateat,creatorid) VALUES (\'GENERATED_ID\',TIMESTAMP,TIMESTAMP,0,\'TEAM_ID\',\'O\',\'incident-ticket-500\',\'incident-ticket-500\',\'\',\'\',TIMESTAMP,0,0,\'HARRY_ID\')"'},
        {"thought": "Add Sam to incident channel", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "INSERT INTO channelmembers (channelid,userid,roles,lastviewedat,msgcount,mentioncount,lastupdateat,schemeuser,schemeadmin,schemeguest) VALUES (\'CHANNEL_ID\',\'SAM_ID\',\'channel_user\',0,0,0,TIMESTAMP,true,false,false) ON CONFLICT DO NOTHING"'},
        {"thought": "Email CTO about critical incident", "cmd": "echo 'eyJ0byI6ICJjdG9AY29tcGFueS5jb20iLCAic3ViamVjdCI6ICJDUklUSUNBTCBJTkNJREVOVDogVElDS0VULTUwMCIsICJib2R5IjogIkNyaXRpY2FsIGluY2lkZW50OiBEYXRhYmFzZSBjb25uZWN0aW9uIHRpbWVvdXQgZXJyb3JzIGFmZmVjdGluZyBwcm9kdWN0aW9uLiIsICJhdHRhY2htZW50cyI6IFtdfQ==' | base64 -d > /tmp/_gt_write && adb push /tmp/_gt_write /sdcard/Android/data/com.gmailclone/files/sentEmail.json && rm -f /tmp/_gt_write"},
        {"thought": "Get emulator date for tomorrow's meeting", "cmd": "adb shell date +%s"},
        {"thought": "Create emergency meeting calendar event for tomorrow 09:00", "cmd": 'adb shell "su 0 sqlite3 /data/data/org.fossify.calendar/databases/events.db \'INSERT INTO events (start_ts,end_ts,title,location,description,reminder_1_minutes,reminder_2_minutes,reminder_3_minutes,reminder_1_type,reminder_2_type,reminder_3_type,repeat_interval,repeat_rule,repeat_limit,repetition_exceptions,attendees,import_id,time_zone,flags,event_type,parent_id,last_updated,source,availability,access_level,color,type,status) VALUES (TOMORROW_9AM_TS,TOMORROW_10AM_TS,\'Discussion on TICKET-500\',\'\',\'\',-1,-1,-1,0,0,0,0,0,0,\'\',\'\',\'\',\'UTC\',0,0,0,CURRENT_TS,\'\',0,0,0,0,0)\'"'},
    ]

    # --- MattermostShiftCoverageTask ---
    tasks["MattermostShiftCoverageTask"] = [
        {"thought": "Wait for Mattermost PostgreSQL", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT 1"'},
        {"thought": "Get Harry's user ID", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id FROM users WHERE username=\'harry\'"'},
        {"thought": "Get shift-requests channel ID", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id FROM channels WHERE name=\'shift-requests\'"'},
        {"thought": "Read shift request messages to identify Alex and Sofia's requests", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id,message FROM posts WHERE channelid=\'CHANNEL_ID\' AND deleteat=0 ORDER BY createat ASC"'},
        {"thought": "Reply to Alex: denied (conflicts with All Hands Meeting on Monday)", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "INSERT INTO posts (id,createat,updateat,deleteat,userid,channelid,rootid,originalid,message,type,props,hashtags,filenames,fileids,hasreactions,editat,ispinned) VALUES (\'GENERATED_ID\',TIMESTAMP,TIMESTAMP,0,\'HARRY_ID\',\'CHANNEL_ID\',\'ALEX_MSG_ID\',\'\',\'Denied: Conflicts with All Hands Meeting on Monday.\',\'\',\'{}\',\'\',\'\',\'\',false,0,false)"'},
        {"thought": "Reply to Sofia: escalated to HR for Wednesday coverage", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "INSERT INTO posts (id,createat,updateat,deleteat,userid,channelid,rootid,originalid,message,type,props,hashtags,filenames,fileids,hasreactions,editat,ispinned) VALUES (\'GENERATED_ID\',TIMESTAMP,TIMESTAMP,0,\'HARRY_ID\',\'CHANNEL_ID\',\'SOFIA_MSG_ID\',\'\',\'Request escalated to HR for Wednesday coverage.\',\'\',\'{}\',\'\',\'\',\'\',false,0,false)"'},
        {"thought": "Email HR about Sofia's shift swap request", "cmd": "echo 'BASE64_EMAIL' | base64 -d > /tmp/_gt_write && adb push /tmp/_gt_write /sdcard/Android/data/com.gmailclone/files/sentEmail.json && rm -f /tmp/_gt_write"},
    ]

    # --- MattermostResourceConflictResolutionTask ---
    tasks["MattermostResourceConflictResolutionTask"] = [
        {"thought": "Wait for Mattermost PostgreSQL", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT 1"'},
        {"thought": "Get Harry and Alex user IDs", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id FROM users WHERE username IN (\'harry\',\'alex\')"'},
        {"thought": "Get resource-booking channel ID", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id FROM channels WHERE name=\'resource-booking\'"'},
        {"thought": "Read resource booking messages", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT message FROM posts WHERE channelid=\'CHANNEL_ID\' AND deleteat=0 ORDER BY createat"'},
        {"thought": "Email conflict report to facilities", "cmd": "echo 'BASE64_EMAIL' | base64 -d > /tmp/_gt_write && adb push /tmp/_gt_write /sdcard/Android/data/com.gmailclone/files/sentEmail.json && rm -f /tmp/_gt_write"},
        {"thought": "Create BOOKED calendar events for approved resources (4 events)", "cmd": 'adb shell "su 0 sqlite3 /data/data/org.fossify.calendar/databases/events.db \'INSERT INTO events ... BOOKED: Conf Room B - Sam ...\'"'},
        {"thought": "DM Alex about Conf Room A conflict", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "INSERT INTO posts ... \'Conf Room A booking conflict: Your request overlaps with Team Standup.\' ..."'},
    ]

    # --- MattermostDeadlineReconciliationTask ---
    tasks["MattermostDeadlineReconciliationTask"] = [
        {"thought": "Wait for Mattermost PostgreSQL", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT 1"'},
        {"thought": "Send deadline audit email to dylan@gmail.com", "cmd": "echo 'BASE64_EMAIL' | base64 -d > /tmp/_gt_write && adb push /tmp/_gt_write /sdcard/Android/data/com.gmailclone/files/sentEmail.json && rm -f /tmp/_gt_write"},
        {"thought": "Create [AUTO] Security Audit Completion calendar event (next Monday + 13 days)", "cmd": 'adb shell "su 0 sqlite3 /data/data/org.fossify.calendar/databases/events.db \'INSERT INTO events ...\'"'},
        {"thought": "Create [AUTO] Beta Testing Phase Start calendar event (next Monday + 18 days)", "cmd": 'adb shell "su 0 sqlite3 /data/data/org.fossify.calendar/databases/events.db \'INSERT INTO events ...\'"'},
        {"thought": "Look up project-updates channel ID", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id FROM channels WHERE name=\'project-updates\'"'},
        {"thought": "Post confirmation with both [AUTO] event titles", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "INSERT INTO posts ... \'Auto-created events: [AUTO] Security Audit Completion, [AUTO] Beta Testing Phase Start\' ..."'},
    ]

    # --- MattermostSendFileTask ---
    tasks["MattermostSendFileTask"] = [
        {"thought": "Wait for Mattermost PostgreSQL", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT 1"'},
        {"thought": "Get Harry and Alex user IDs", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "SELECT id FROM users WHERE username IN (\'harry\',\'alex\')"'},
        {"thought": "Get Mattermost admin API token", "cmd": "curl -s -X POST http://localhost:8065/api/v4/users/login -H 'Content-Type: application/json' -d '{\"login_id\":\"admin@test.com\",\"password\":\"password\"}' -D /dev/stderr 2>&1 | grep Token"},
        {"thought": "Pull birthday image from device", "cmd": "adb pull /sdcard/Pictures/21bd-1.jpg /tmp/21bd-1.jpg"},
        {"thought": "Create DM channel harry→alex via Mattermost API", "cmd": "curl -s -X POST http://localhost:8065/api/v4/channels/direct -H 'Authorization: Bearer ADMIN_TOKEN' -H 'Content-Type: application/json' -d '[\"HARRY_ID\",\"ALEX_ID\"]'"},
        {"thought": "Upload birthday image via Mattermost file API", "cmd": "curl -s -X POST 'http://localhost:8065/api/v4/files?channel_id=DM_CHANNEL_ID' -H 'Authorization: Bearer ADMIN_TOKEN' -F 'files=@/tmp/21bd-1.jpg'"},
        {"thought": "Post birthday message with file attachment via SQL file (preserves JSON quotes in fileids)", "cmd": "echo 'INSERT SQL with fileids=[\"FILE_ID\"]' | base64 -d > /tmp/_mm_post.sql && cat /tmp/_mm_post.sql | docker exec -i mattermost-docker-postgres-1 psql -U mmuser -d mattermost && rm -f /tmp/_mm_post.sql"},
        {"thought": "Fix DM channel creator to alex", "cmd": 'docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c "UPDATE channels SET creatorid=\'ALEX_ID\' WHERE id=\'DM_CHANNEL_ID\'"'},
    ]

    # --- MastodonSavePhotosTask ---
    tasks["MastodonSavePhotosTask"] = [
        *MASTODON_TOKEN_DISCOVERY,
        {"thought": "Query media attachment file names from toot 115319571928036858", "cmd": 'docker exec mastodon-docker-db-1 psql -U postgres -d mastodon -t -c "SELECT file_file_name FROM media_attachments WHERE status_id=115319571928036858"'},
        {"thought": "Get media attachment ID for first image", "cmd": 'docker exec mastodon-docker-db-1 psql -U postgres -d mastodon -t -c "SELECT id FROM media_attachments WHERE status_id=115319571928036858 AND file_file_name=\'21bd-1.jpg\'"'},
        {"thought": "Build Mastodon media file path from ID (split into 3-char groups) and copy to device", "cmd": "docker cp mastodon-docker-web-1:/opt/mastodon/public/system/media_attachments/files/ID_PATH/original/21bd-1.jpg /tmp/21bd-1.jpg && adb push /tmp/21bd-1.jpg /sdcard/Download/21bd-1.jpg"},
        {"thought": "Repeat for second image (21bd-2.jpeg)", "cmd": "docker cp mastodon-docker-web-1:/opt/mastodon/public/system/media_attachments/files/ID_PATH/original/21bd-2.jpeg /tmp/21bd-2.jpeg && adb push /tmp/21bd-2.jpeg /sdcard/Download/21bd-2.jpeg"},
        {"thought": "Repeat for third image (21bd-3.jpg)", "cmd": "docker cp mastodon-docker-web-1:/opt/mastodon/public/system/media_attachments/files/ID_PATH/original/21bd-3.jpg /tmp/21bd-3.jpg && adb push /tmp/21bd-3.jpg /sdcard/Download/21bd-3.jpg"},
    ]

    # === Tasks with stub/incomplete commands in old JSON — need full raw bash ===

    # --- MastodonChangeHeaderTask (old JSON has "PATCH update_credentials" stub) ---
    tasks["MastodonChangeHeaderTask"] = [
        *MASTODON_TOKEN_DISCOVERY,
        {"thought": "Pull tiger.jpg from device to container", "cmd": "adb pull /sdcard/Pictures/tiger.jpg /tmp/tiger.jpg"},
        {"thought": "Upload tiger.jpg as new header image via Mastodon API (multipart form)", "cmd": 'curl -sk -X PATCH -H "Authorization: Bearer $TOKEN" -H "Host: 10.0.2.2" -F "header=@/tmp/tiger.jpg" https://localhost/api/v1/accounts/update_credentials'},
    ]

    # --- MastodonPostEditedPhotoTask (old JSON has "python PIL resize" stub) ---
    tasks["MastodonPostEditedPhotoTask"] = [
        *MASTODON_TOKEN_DISCOVERY,
        {"thought": "Pull source photo from device", "cmd": "adb pull /sdcard/Pictures/tiger.jpg /tmp/src_photo.jpg"},
        {"thought": "Crop image to 9:16 (540x960) using Python PIL", "cmd": "python3 -c \"from PIL import Image; img=Image.open('/tmp/src_photo.jpg').resize((540,960)); img.save('/tmp/cropped.jpg')\""},
        {"thought": "Upload cropped image to Mastodon media API", "cmd": 'curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "Host: 10.0.2.2" -F "file=@/tmp/cropped.jpg" https://localhost/api/v1/media'},
        {"thought": "Post #onePhoto toot with uploaded media", "cmd": 'curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "Host: 10.0.2.2" -H "Content-Type: application/json" -d \'{"status": "#onePhoto", "media_ids": ["MEDIA_ID"]}\' https://localhost/api/v1/statuses'},
    ]

    # --- MastodonShareLocationTask (old JSON has incomplete adb pull) ---
    tasks["MastodonShareLocationTask"] = [
        *MASTODON_TOKEN_DISCOVERY,
        {"thought": "Pull Eiffel Tower image from device", "cmd": "adb pull /sdcard/Download/Eiffel_Tower.jpg /tmp/eiffel.jpg"},
        {"thought": "Upload image to Mastodon media API", "cmd": 'curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "Host: 10.0.2.2" -F "file=@/tmp/eiffel.jpg" https://localhost/api/v1/media'},
        {"thought": "Post location toot with Eiffel Tower image and maps link", "cmd": 'curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "Host: 10.0.2.2" -H "Content-Type: application/json" -d \'{"status": "Eiffel Tower https://maps.app.goo.gl/QaAiRFhy3bRf5yPd6", "media_ids": ["MEDIA_ID"]}\' https://localhost/api/v1/statuses'},
    ]

    # --- MastodonMallShareOrderTask (old JSON has incomplete media upload) ---
    tasks["MastodonMallShareOrderTask"] = [
        *MASTODON_TOKEN_DISCOVERY,
        {"thought": "Get mall order config to find watch product", "cmd": "curl -s http://localhost:6800/config/callback"},
        {"thought": "Upload watch image from task assets to Mastodon", "cmd": 'curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "Host: 10.0.2.2" -F "file=@/app/service/src/mobile_world/tasks/definitions/mastodon/assets/mallShare/watch.jpg" https://localhost/api/v1/media'},
        {"thought": "Post toot about smart watch order with image", "cmd": 'curl -sk -X POST -H "Authorization: Bearer $TOKEN" -H "Host: 10.0.2.2" -H "Content-Type: application/json" -d \'{"status": "刚在淘店买了一块智能手表，价格1199元，非常不错！", "media_ids": ["MEDIA_ID"]}\' https://localhost/api/v1/statuses'},
    ]

    # --- ChromeSearchBeijingWeatherTask (dynamic weather API) ---
    tasks["ChromeSearchBeijingWeatherTask"] = [
        {"thought": "Query Open-Meteo weather API for Beijing today's max temperature", "cmd": "curl -s 'https://api.open-meteo.com/v1/forecast?latitude=39.9042&longitude=116.4074&daily=temperature_2m_max&timezone=Asia/Shanghai'"},
        {"thought": "Submit the temperature as answer (rounded to integer)", "cmd": "curl -s -X POST http://localhost:6800/step -H 'Content-Type: application/json' -d '{\"device\":\"emulator-5554\",\"action\":{\"action_type\":\"answer\",\"text\":\"TEMPERATURE\"}}'"},
    ]

    # --- CartInfoNotificationTask (old JSON has bare GET stub) ---
    tasks["CartInfoNotificationTask"] = [
        {"thought": "Query mall config for order history", "cmd": "curl -s http://localhost:6800/config/callback"},
        {"thought": "Send SMS to customer with order number and product names", "cmd": 'adb shell "su 0 sqlite3 /data/user/0/com.android.providers.telephony/databases/mmssms.db \'INSERT INTO sms (address,body,type,date,read,seen) VALUES (\\\"13800138888\\\",\\\"Order 639281475036294: 经典白色T恤, 保湿面霜套装\\\",2,TIMESTAMP,1,1)\'"'},
    ]

    # --- CheckPuchasedItem (old JSON has bare GET stub) ---
    tasks["CheckPuchasedItem"] = [
        {"thought": "Query mall config for order history to find shoe purchase", "cmd": "curl -s http://localhost:6800/config/callback"},
        {"thought": "From order data, the shoe size is 42. Submit answer.", "cmd": "curl -s -X POST http://localhost:6800/step -H 'Content-Type: application/json' -d '{\"device\":\"emulator-5554\",\"action\":{\"action_type\":\"answer\",\"text\":\"42\"}}'"},
    ]

    # --- RecentTotalExpenseTask (old JSON has bare GET stub) ---
    tasks["RecentTotalExpenseTask"] = [
        {"thought": "Query mall config for order history", "cmd": "curl -s http://localhost:6800/config/callback"},
        {"thought": "Calculate total from recent orders: 1196. Submit answer.", "cmd": "curl -s -X POST http://localhost:6800/step -H 'Content-Type: application/json' -d '{\"device\":\"emulator-5554\",\"action\":{\"action_type\":\"answer\",\"text\":\"1196\"}}'"},
    ]

    return tasks


if __name__ == "__main__":
    main()
