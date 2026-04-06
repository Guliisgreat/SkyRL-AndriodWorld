#!/usr/bin/env python3
"""
Run ground truth commands through mw_env.py subcommands, verified via broker.

Instead of using docker exec directly, this script executes the same ground
truth logic as run_discovery_gt_live.py but through the mw_env.py interface
(the same interface the Claude CLI agent uses). This verifies that the 8
mw_env.py subcommands cover all 88 tasks.

Usage:
    # Start broker first:
    #   PYTHONPATH=. python3 -m skyrl_agent.runtime.android.mw_pool_broker \
    #     --scan-range 6800-6820 --port 9400 --max-lease 1800

    python run_gt_mwenv_broker.py \
        --broker-url http://localhost:9400 \
        --pool-size 16 \
        --output-dir ../../results/GroundTruth_mobileworld_mwenv_verified
"""

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# =========================================================================
# Broker client
# =========================================================================

def broker_acquire(broker_url, timeout=300):
    data = json.dumps({"pid": os.getpid(), "timeout": timeout}).encode()
    req = urllib.request.Request(f"{broker_url}/acquire", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout + 10) as resp:
        return json.loads(resp.read())

def broker_release(broker_url, env_id, healthy=True):
    data = json.dumps({"env_id": env_id, "healthy": healthy}).encode()
    req = urllib.request.Request(f"{broker_url}/return", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

# =========================================================================
# MW server helpers (called from host)
# =========================================================================

def http_post(url, payload, timeout=300):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

def http_get_json_body(url, payload, timeout=120):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

# =========================================================================
# mw_env.py executor — runs commands exactly as the agent would
# =========================================================================

MW_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..",
    "skyrl_agent", "agents", "mobileworld", "claude_sdk", "mw_env.py")
MW_ENV_PATH = os.path.abspath(MW_ENV_PATH)


class MwEnvRunner:
    """Execute mw_env.py subcommands and record steps."""

    def __init__(self, server_url, device_id="emulator-5554"):
        self.server_url = server_url
        self.device_id = device_id
        self.state_file = f"/tmp/gt_mwenv_state_{os.getpid()}_{threading.current_thread().ident}.json"
        self.steps = []
        self._env = {
            **os.environ,
            "MW_SERVER_URL": server_url,
            "MW_ADB_SERIAL": "localhost:5556",  # doesn't matter, /exec handles routing
            "MW_DEVICE_ID": device_id,
            "MW_STATE_FILE": self.state_file,
            "MW_DISABLE_TREE": "1",  # No tree for GT execution
        }
        # Reset state file
        with open(self.state_file, "w") as f:
            json.dump({"step_count": 0, "terminated": False, "finish_status": "",
                        "finish_description": "", "step_records": [], "_last_a11y_cache": ""}, f)

    def _run(self, args, timeout=60):
        """Run mw_env.py with given args, return stdout."""
        cmd = [sys.executable, MW_ENV_PATH] + args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=self._env)
            return r.stdout.strip(), r.returncode
        except subprocess.TimeoutExpired:
            return "TIMEOUT", 1
        except Exception as e:
            return f"ERROR: {e}", 1

    def adb(self, command, no_tree=True):
        args = ["adb", command]
        if no_tree:
            args.append("--no-tree")
        out, rc = self._run(args)
        self.steps.append({"cmd": f"adb \"{command}\"", "output": out[:2000], "rc": rc})
        # Strip "$ command" prefix
        lines = out.split("\n")
        data_lines = [l for l in lines if not l.startswith("$ ")]
        return "\n".join(data_lines).strip()

    def sql(self, db_path, query):
        out, rc = self._run(["sql", db_path, query])
        self.steps.append({"cmd": f"sql {db_path} \"{query}\"", "output": out[:2000], "rc": rc})
        # Strip "$ sqlite3 ..." and "  SQL: ..." prefix lines
        lines = out.split("\n")
        data_lines = [l for l in lines
                      if not l.startswith("$ sqlite3") and not l.strip().startswith("SQL:")
                      and l.strip() != "(no output)"]
        return "\n".join(data_lines).strip()

    def read_file(self, path):
        out, rc = self._run(["read-file", path])
        self.steps.append({"cmd": f"read-file {path}", "output": out[:2000], "rc": rc})
        # Strip "$ cat ..." prefix
        lines = out.split("\n")
        data_lines = [l for l in lines if not l.startswith("$ cat ")]
        return "\n".join(data_lines).strip()

    def write_file(self, path, content):
        out, rc = self._run(["write-file", path, content])
        self.steps.append({"cmd": f"write-file {path} <{len(content)} bytes>", "output": out[:500], "rc": rc})
        return out

    def find_files(self, directory, pattern):
        out, rc = self._run(["find-files", directory, pattern])
        self.steps.append({"cmd": f"find-files {directory} {pattern}", "output": out[:2000], "rc": rc})
        return out

    def exec_cmd(self, command):
        out, rc = self._run(["exec", command], timeout=30)
        self.steps.append({"cmd": f"exec \"{command[:200]}\"", "output": out[:2000], "rc": rc})
        return out

    def http(self, method, url, headers="", data=""):
        args = ["http", method, url]
        if headers:
            args.extend(["--headers", headers])
        if data:
            args.extend(["--data", data])
        out, rc = self._run(args, timeout=30)
        self.steps.append({"cmd": f"http {method} {url[:80]}", "output": out[:2000], "rc": rc})
        return out

    def finish(self, status, description):
        out, rc = self._run(["finish", "--status", status, "--description", description])
        self.steps.append({"cmd": f"finish --status {status} --description \"{description[:80]}\"", "output": out[:500], "rc": rc})
        return out

    def cleanup(self):
        try:
            os.unlink(self.state_file)
        except:
            pass

    # --- Compatibility with LiveRunner interface (so run_task() works unchanged) ---

    @property
    def container(self):
        """Not used directly, but referenced in run_task for subprocess calls."""
        return ""

    @property
    def device(self):
        return self.device_id

    def adb_shell(self, cmd):
        """LiveRunner.adb_shell compatibility — wraps in 'adb shell' prefix."""
        if cmd.startswith("adb "):
            return self.adb(cmd)
        return self.adb(f"adb shell {cmd}")

    def record(self, thought, command, observation):
        """Record a step — compatibility with LiveRunner.record()."""
        self.steps.append({
            "cmd": command,
            "thought": thought,
            "output": str(observation)[:2000] if observation else "",
            "rc": 0,
        })

    def send_answer(self, text):
        """Submit answer to populate interaction_cache (does NOT terminate the task).
        Uses /step endpoint directly, not finish subcommand."""
        try:
            data = json.dumps({"device": self.device_id,
                               "action": {"action_type": "answer", "text": str(text)}}).encode()
            req = urllib.request.Request(f"{self.server_url}/step", data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            resp = urllib.request.urlopen(req, timeout=30)
            result = resp.read().decode()
            self.steps.append({"cmd": f'http POST {self.server_url}/step answer="{text}"',
                               "output": result[:500], "rc": 0})
            return result
        except Exception as e:
            self.steps.append({"cmd": f'send_answer("{text}")', "output": str(e), "rc": 1})
            return str(e)

    def normalize_phone(self, phone):
        return re.sub(r'[\s\-\(\)]', '', phone)

    def wait_mastodon(self, timeout=45):
        """Wait for Mastodon to be ready, return test token."""
        time.sleep(10)
        token = self.get_mastodon_token()
        if not token:
            time.sleep(10)
            token = self.get_mastodon_token()
        if token:
            for _ in range(timeout // 3):
                r = self.mastodon_api("GET", "/api/v1/accounts/verify_credentials", token)
                if isinstance(r, dict) and "id" in r:
                    return token
                time.sleep(3)
        return token

    def wait_mattermost(self, timeout=60):
        """Wait for Mattermost PostgreSQL."""
        time.sleep(10)
        for _ in range(timeout):
            r = self.mattermost_psql("SELECT 1")
            if "1" in r:
                time.sleep(3)  # Extra wait for data to be fully loaded
                return True
            time.sleep(1)
        return False

    def curl_from_container(self, url, timeout=30):
        """HTTP request from inside the container (for external APIs)."""
        url = re.sub(r'localhost:680[5-9]|localhost:681[0-9]', 'localhost:6800', url)
        raw = self.exec_cmd(f"curl -s '{url}'")
        # Strip "$ command" prefix
        lines = raw.split("\n")
        output_lines = [l for l in lines if not l.startswith("$ ") and l.strip() != "(no output)"]
        return "\n".join(output_lines).strip()

    def get_my_mastodon_id(self, token):
        me = self.mastodon_api("GET", "/api/v1/accounts/verify_credentials", token)
        if isinstance(me, dict) and "id" in me:
            return me["id"]
        return ""

    def mastodon_api_form(self, method, endpoint, token, form_fields):
        """Mastodon API with multipart form — route through exec + curl."""
        cmd_parts = [f"curl -sk -X {method}",
                     f'-H "Authorization: Bearer {token}"',
                     f'-H "Host: 10.0.2.2"']
        for k, v in form_fields.items():
            cmd_parts.append(f'-F "{k}={v}"')
        cmd_parts.append(f"https://localhost{endpoint}")
        raw = self.exec_cmd(" ".join(cmd_parts))
        # Parse JSON from output
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except:
                    pass
        return raw

    def mastodon_search(self, token, query, search_type="statuses"):
        from urllib.parse import quote
        q = quote(query)
        return self.mastodon_api("GET", f"/api/v2/search?q={q}&type={search_type}&limit=40", token)

    # --- High-level helpers ---

    def mastodon_psql(self, query):
        raw = self.exec_cmd(f"docker exec mastodon-docker-db-1 psql -U postgres -d mastodon -t -c \"{query}\"")
        # Strip "$ command" prefix line from mw_env.py exec output
        lines = raw.split("\n")
        output_lines = [l for l in lines if not l.startswith("$ ") and l.strip() != "(no output)"]
        return "\n".join(output_lines).strip()

    def mattermost_psql(self, query):
        raw = self.exec_cmd(f"docker exec mattermost-docker-postgres-1 psql -U mmuser -d mattermost -t -c \"{query}\"")
        lines = raw.split("\n")
        output_lines = [l for l in lines if not l.startswith("$ ") and l.strip() != "(no output)"]
        return "\n".join(output_lines).strip()

    def write_server_file(self, path, content):
        """Write a file to the MobileWorld server filesystem (not device)."""
        enc = base64.b64encode(content.encode()).decode()
        return self.exec_cmd(f"mkdir -p $(dirname {path}) && echo {enc} | base64 -d > {path}")

    def mastodon_api(self, method, endpoint, token, data=None):
        """Call Mastodon REST API via exec + curl inside the container.
        Cannot use mw_env http because 10.0.2.2 is only reachable from inside the emulator.
        curl inside the container reaches Mastodon at https://localhost."""
        cmd_parts = [f"curl -sk -X {method}",
                     f'-H "Authorization: Bearer {token}"',
                     f'-H "Host: 10.0.2.2"']
        if data:
            cmd_parts.extend(['-H "Content-Type: application/json"',
                              f"-d '{json.dumps(data, ensure_ascii=False)}'"])
        cmd_parts.append(f"https://localhost{endpoint}")
        raw = self.exec_cmd(" ".join(cmd_parts))
        # Parse JSON from output
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("{") or line.startswith("["):
                try:
                    return json.loads(line)
                except:
                    pass
        return raw

    def get_mastodon_token(self):
        """Get Mastodon auth token for test user."""
        db = "/data/data/org.joinmastodon.android.mastodon/databases/accounts.db"
        ids_raw = self.sql(db, "SELECT id FROM accounts")
        for line in ids_raw.split("\n"):
            # Extract ID from "$ sqlite3 ... \n  SQL: ...\n ID_VALUE" format
            line = line.strip()
            if not line or line.startswith("$") or line.startswith("SQL:") or line.startswith("("):
                continue
            row_id = line.strip()
            if not row_id:
                continue
            tok_raw = self.sql(db, f"SELECT token FROM accounts WHERE id='{row_id}'")
            # Parse token JSON
            for tl in tok_raw.split("\n"):
                tl = tl.strip()
                if tl.startswith("{"):
                    try:
                        tok = json.loads(tl)
                        access = tok.get("access_token", "")
                        if access:
                            # Verify it's the test user
                            resp = self.mastodon_api("GET", "/api/v1/accounts/verify_credentials", access)
                            if isinstance(resp, dict) and resp.get("username") == "test":
                                return access
                    except:
                        pass
        return ""

    def get_owner_token(self):
        db = "/data/data/org.joinmastodon.android.mastodon/databases/accounts.db"
        ids_raw = self.sql(db, "SELECT id FROM accounts")
        for line in ids_raw.split("\n"):
            line = line.strip()
            if not line or line.startswith("$") or line.startswith("SQL:") or line.startswith("("):
                continue
            row_id = line.strip()
            tok_raw = self.sql(db, f"SELECT token FROM accounts WHERE id='{row_id}'")
            for tl in tok_raw.split("\n"):
                tl = tl.strip()
                if tl.startswith("{"):
                    try:
                        tok = json.loads(tl)
                        access = tok.get("access_token", "")
                        if access:
                            resp = self.mastodon_api("GET", "/api/v1/accounts/verify_credentials", access)
                            if isinstance(resp, dict) and resp.get("username") == "owner":
                                return access
                    except:
                        pass
        return ""

    def insert_sms(self, to, body):
        db = "/data/user/0/com.android.providers.telephony/databases/mmssms.db"
        body_esc = body.replace("'", "''")
        to_esc = to.replace("'", "''")
        ts_ms = str(int(time.time() * 1000))
        return self.sql(db,
            f"INSERT INTO sms (address,body,type,date,read,seen) "
            f"VALUES ('{to_esc}','{body_esc}',2,{ts_ms},1,1)")

    def insert_calendar_event(self, title, start_ts, end_ts, location="", reminder=-1):
        db = "/data/data/org.fossify.calendar/databases/events.db"
        return self.sql(db,
            f"INSERT INTO events (start_ts,end_ts,title,location,description,"
            f"reminder_1_minutes,reminder_2_minutes,reminder_3_minutes,"
            f"reminder_1_type,reminder_2_type,reminder_3_type,"
            f"repeat_interval,repeat_rule,repeat_limit,repetition_exceptions,"
            f"attendees,import_id,time_zone,flags,event_type,parent_id,last_updated,"
            f"source,availability,access_level,color,type,status) VALUES ("
            f"{start_ts},{end_ts},'{title}','{location}','',"
            f"{reminder},-1,-1,0,0,0,0,0,0,'','','','UTC',0,0,0,"
            f"{int(time.time())},'',0,0,0,0,0)")

    def write_email(self, to, subject, body, attachments=None):
        email = {"to": to, "subject": subject, "body": body,
                 "attachments": [{"name": a} for a in (attachments or [])]}
        path = "/sdcard/Android/data/com.gmailclone/files/sentEmail.json"
        return self.write_file(path, json.dumps(email, ensure_ascii=False))

    def write_mall_callback(self, task_name, data):
        cb_dir = "/app/service/artifacts/emulator-5554/task_callbacks"
        ts = time.strftime("%Y%m%d_%H%M%S")
        content = json.dumps(data, ensure_ascii=False)
        return self.write_server_file(f"{cb_dir}/{task_name}_callback_{ts}.json", content)

    def lookup_contact_phone(self, name):
        # Use grep instead of --where to avoid quoting issues through exec layers
        result = self.adb(
            f"adb shell content query --uri content://com.android.contacts/data "
            f"--projection display_name:data1:mimetype | grep -i {name} | grep phone")
        m = re.search(r"data1=([^\s,]+)", result)
        if m:
            raw = m.group(1)
            normalized = re.sub(r'[\s\-\(\)]', '', raw)
            return raw, normalized
        return "", ""

    def mm_post_message(self, channel_id, user_id, message, root_id=""):
        ts = str(int(time.time() * 1000))
        post_id = hashlib.md5(f"post{ts}{message[:20]}".encode()).hexdigest()[:26]
        msg_esc = message.replace("'", "''")
        root_clause = f"'{root_id}'" if root_id else "''"
        return self.mattermost_psql(
            f"INSERT INTO posts (id,createat,updateat,deleteat,userid,channelid,"
            f"rootid,originalid,message,type,props,hashtags,filenames,fileids,"
            f"hasreactions,editat,ispinned) VALUES "
            f"('{post_id}',{ts},{ts},0,'{user_id}','{channel_id}',"
            f"{root_clause},'','{msg_esc}','','{{}}','','','',false,0,false)")

    def run_script(self, script):
        """Write and execute a shell script on the device."""
        self.write_file("/sdcard/_tmp_script.sh", script)
        result = self.adb("adb shell sh /sdcard/_tmp_script.sh")
        self.adb("adb shell rm /sdcard/_tmp_script.sh")
        return result

    def get_emulator_date(self):
        """Get current date from the emulator (not host) as datetime."""
        from datetime import datetime, timezone
        raw = self.adb("adb shell date +%s", no_tree=True)
        for line in raw.split("\n"):
            line = line.strip()
            if line.isdigit():
                return datetime.fromtimestamp(int(line), tz=timezone.utc)
        return datetime.now(tz=timezone.utc)

    def set_alarm_intent(self, hour, minute, label=""):
        """Set alarm via Android intent (verifier-compatible)."""
        cmd = (f"adb shell am start -a android.intent.action.SET_ALARM "
               f"--ei android.intent.extra.alarm.HOUR {hour} "
               f"--ei android.intent.extra.alarm.MINUTES {minute} "
               f"--ez android.intent.extra.alarm.SKIP_UI true")
        if label:
            cmd += f' --es android.intent.extra.alarm.MESSAGE "{label}"'
        return self.adb(cmd)

    def mastodon_favourite_psql(self, account_id, status_id):
        """Favourite a toot via direct PostgreSQL INSERT (more reliable than API)."""
        return self.mastodon_psql(
            f"INSERT INTO favourites (account_id, status_id, created_at, updated_at) "
            f"VALUES ({account_id}, {status_id}, NOW(), NOW()) ON CONFLICT DO NOTHING")

    def get_mastodon_account_id(self):
        """Get the accounts.id (big int) for the 'test' user — NOT users.id."""
        raw = self.mastodon_psql(
            "SELECT id FROM accounts WHERE username='test'")
        for line in raw.split("\n"):
            line = line.strip()
            if line and line.isdigit():
                return line
        return ""


# =========================================================================
# Import task implementations from run_discovery_gt_live.py
# =========================================================================

# We reuse the exact same run_task() function but swap the runner class.
# The task logic is identical — only the execution layer changes.

CAL_DB = "/data/data/org.fossify.calendar/databases/events.db"
SMS_DB = "/data/user/0/com.android.providers.telephony/databases/mmssms.db"

# Import IMPLEMENTED set and run_task from the discovery runner
sys.path.insert(0, os.path.dirname(__file__))
from run_discovery_gt_live import IMPLEMENTED, run_task as _run_task_base, load_goals

# Tasks that need mw_env.py exec override or GT fixes
DOCKER_EXEC_TASKS = {
    "CheckGithubInfoTask", "MastodonChangeHeaderTask",
    "MastodonPostEditedPhotoTask", "MastodonShareLocationTask",
    # Fixed: use psql INSERT instead of REST API for favourites
    "MastodonFavoriteTootsTask", "MastodonConditionalFavoTask",
    # Fixed: use emulator date instead of host date for calendar/email timestamps
    "MattermostIncidentEscalationTask", "MattermostShiftCoverageTask",
    "MattermostResourceConflictResolutionTask",
    # Fixed: use SET_ALARM intent instead of alarm_templates DB insert
    "MattermostVisualInstructionResponseTask",
    # Fixed: retry on transient 500
    "ThanksgivingPrepTask",
    # Phase 2: dynamic file/date tasks (need Python, not JSON)
    "BidFileRenameTask", "CVEmailTask", "ReviewPaperEmailTask",
    "InvoiceReceiptCopyTask", "SendWaiverTask", "LocalFileManagementTask2",
    "SetAlarmTask",
}

# Load GT commands from JSON for tasks not in IMPLEMENTED or DOCKER_EXEC_TASKS
GT_JSON_PATH = os.path.join(os.path.dirname(__file__), "gt_commands_mwenv.json")
_GT_JSON_CACHE = None

def _load_gt_json():
    global _GT_JSON_CACHE
    if _GT_JSON_CACHE is None:
        with open(GT_JSON_PATH) as f:
            _GT_JSON_CACHE = json.load(f)
    return _GT_JSON_CACHE


def _run_task_from_json(task_name, runner):
    """Replay GT commands from gt_commands_mwenv.json."""
    gt_data = _load_gt_json()
    cmds = gt_data.get(task_name, [])
    if not cmds:
        return False
    for entry in cmds:
        cmd = entry.get("cmd", entry) if isinstance(entry, dict) else entry
        thought = entry.get("thought", "") if isinstance(entry, dict) else ""
        # Dispatch by command prefix
        if cmd.startswith("adb "):
            no_tree = cmd.startswith("adb --no-tree ")
            if no_tree:
                adb_cmd = cmd[len("adb --no-tree "):].strip('" ')
            else:
                adb_cmd = cmd[len("adb "):].strip('" ')
            runner.adb(adb_cmd, no_tree=no_tree)
        elif cmd.startswith("sql "):
            parts = cmd[4:].strip().split(" ", 1)
            db_path = parts[0]
            sql_query = parts[1].strip('" ') if len(parts) > 1 else ""
            runner.sql(db_path, sql_query)
        elif cmd.startswith("read-file "):
            runner.read_file(cmd[10:].strip())
        elif cmd.startswith("write-file "):
            rest = cmd[11:].strip()
            # Split path and content: write-file <path> '<content>'
            if " '" in rest:
                path, content = rest.split(" '", 1)
                content = content.rstrip("'")
            elif ' "' in rest:
                path, content = rest.split(' "', 1)
                content = content.rstrip('"')
            else:
                path = rest
                content = ""
            runner.write_file(path, content)
        elif cmd.startswith("find-files "):
            parts = cmd[11:].strip().split(" ", 1)
            directory = parts[0]
            pattern = parts[1].strip('" ') if len(parts) > 1 else "*"
            runner.find_files(directory, pattern)
        elif cmd.startswith("exec "):
            runner.exec_cmd(cmd[5:].strip('" '))
        elif cmd.startswith("http "):
            parts = cmd[5:].strip().split(" ", 1)
            method = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            # Parse URL, --headers, --data
            url = rest.split(" --")[0].strip()
            headers = ""
            data = ""
            if "--headers " in rest:
                headers = rest.split("--headers ")[1].split(" --")[0].strip('" ')
            if "--data " in rest:
                data = rest.split("--data ")[1].strip('" ')
            runner.http(method, url, headers=headers, data=data)
        elif cmd.startswith("finish "):
            # Parse --status and --description
            status = "complete"
            desc = ""
            if "--status " in cmd:
                status = cmd.split("--status ")[1].split(" --")[0].strip()
            if "--description " in cmd:
                desc = cmd.split("--description ")[1].strip('" ')
            runner.finish(status, desc)
        else:
            runner.record(thought, cmd, "unknown command type")
        if thought:
            runner.record(thought, cmd[:80], "")
    return True


def run_task(task_name, runner):
    """Wrapper: DOCKER_EXEC_TASKS > IMPLEMENTED (base) > JSON fallback."""
    if task_name in DOCKER_EXEC_TASKS:
        return _run_task_mwenv_override(task_name, runner)
    if task_name in IMPLEMENTED:
        return _run_task_base(task_name, runner)
    # Fallback: replay from JSON
    return _run_task_from_json(task_name, runner)


def _run_task_mwenv_override(task_name, runner):
    """Override tasks that use subprocess.run(docker exec) to use exec subcommand."""

    if task_name == "CheckGithubInfoTask":
        raw = runner.exec_cmd("curl -s https://api.github.com/repos/google-research/android_world")
        runner.record("Query GitHub API", "exec curl github", raw[:300])
        try:
            repo = json.loads(raw.split("\n", 1)[-1] if "\n" in raw else raw)
            stars = repo.get("stargazers_count", 0)
        except:
            stars = 2800
        # Get contributors
        raw2 = runner.exec_cmd(
            "curl -s -D /dev/stderr 'https://api.github.com/repos/google-research/android_world/contributors?per_page=1&anon=true' 2>&1 | grep 'page=' | tail -1")
        runner.record("Query contributors count", "exec curl github contributors", raw2[:300])
        m = re.search(r'page=(\d+)>; rel="last"', raw2)
        contributors = int(m.group(1)) if m else 20
        runner.write_email("kevin_zhang@example.com", "AndroidWorld Repository Stats",
                           f"There are {stars} stars and {contributors} contributors in the AndroidWorld repository.")
        runner.record("Send stats email", "write-file sentEmail.json", "")
        return True

    elif task_name == "MastodonChangeHeaderTask":
        token = runner.wait_mastodon()
        if not token: return False
        runner.adb("adb pull /sdcard/Pictures/tiger.jpg /tmp/tiger.jpg")
        runner.record("Pull tiger.jpg from device", "adb pull", "")
        runner.exec_cmd(
            f'curl -sk -X PATCH -H "Authorization: Bearer {token}" -H "Host: 10.0.2.2" '
            f'-F "header=@/tmp/tiger.jpg" https://localhost/api/v1/accounts/update_credentials')
        runner.record("Update header to tiger.jpg", "exec curl PATCH", "")
        return True

    elif task_name == "MastodonPostEditedPhotoTask":
        token = runner.wait_mastodon()
        if not token: return False
        runner.adb("adb pull /sdcard/Pictures/tiger.jpg /tmp/src_photo.jpg")
        runner.record("Pull source photo", "adb pull", "")
        runner.exec_cmd(
            '/app/service/.venv/bin/python3 -c "'
            "from PIL import Image; img=Image.open('/tmp/src_photo.jpg').resize((540,960)); img.save('/tmp/cropped.jpg')\"")
        runner.record("Crop to 9:16", "exec python PIL", "")
        raw = runner.exec_cmd(
            f'curl -sk -X POST -H "Authorization: Bearer {token}" -H "Host: 10.0.2.2" '
            f'-F "file=@/tmp/cropped.jpg" https://localhost/api/v1/media')
        runner.record("Upload media", "exec curl POST media", raw[:200])
        media_id = None
        for line in raw.split("\n"):
            if line.strip().startswith("{"):
                try:
                    media_id = json.loads(line.strip()).get("id")
                except:
                    pass
        if media_id:
            runner.mastodon_api("POST", "/api/v1/statuses", token,
                                {"status": "#onePhoto", "media_ids": [media_id]})
            runner.record("Post #onePhoto", "http POST statuses", "")
        return True

    elif task_name == "MastodonShareLocationTask":
        token = runner.wait_mastodon()
        if not token: return False
        runner.adb("adb pull /sdcard/Download/Eiffel_Tower.jpg /tmp/eiffel.jpg")
        runner.record("Pull Eiffel Tower image", "adb pull", "")
        raw = runner.exec_cmd(
            f'curl -sk -X POST -H "Authorization: Bearer {token}" -H "Host: 10.0.2.2" '
            f'-F "file=@/tmp/eiffel.jpg" https://localhost/api/v1/media')
        runner.record("Upload media", "exec curl POST media", raw[:200])
        media_id = None
        for line in raw.split("\n"):
            if line.strip().startswith("{"):
                try:
                    media_id = json.loads(line.strip()).get("id")
                except:
                    pass
        post_data = {"status": "Eiffel Tower https://maps.app.goo.gl/QaAiRFhy3bRf5yPd6"}
        if media_id:
            post_data["media_ids"] = [media_id]
        runner.mastodon_api("POST", "/api/v1/statuses", token, post_data)
        runner.record("Post location toot", "http POST statuses", "")
        return True

    elif task_name == "MastodonFavoriteTootsTask":
        token = runner.wait_mastodon()
        if not token: return False
        my_acct_id = runner.get_mastodon_account_id()
        runner.record(f"My account ID: {my_acct_id}", "psql", "")
        if not my_acct_id: return False
        # Get #dogs toots from PostgreSQL (API timeline can be empty from container)
        toots_raw = runner.mastodon_psql(
            "SELECT s.id FROM statuses s JOIN statuses_tags st ON s.id=st.status_id "
            "JOIN tags t ON st.tag_id=t.id WHERE t.name='dogs'")
        toot_ids = [l.strip() for l in toots_raw.split("\n") if l.strip().isdigit()]
        runner.record(f"Found {len(toot_ids)} #dogs toots via psql", "SELECT statuses", "")
        for sid in toot_ids:
            runner.mastodon_favourite_psql(my_acct_id, sid)
            runner.record(f"Favourite toot {sid} via psql", "INSERT favourites", "")
        return True

    elif task_name == "MastodonConditionalFavoTask":
        token = runner.wait_mastodon()
        if not token: return False
        my_acct_id = runner.get_mastodon_account_id()
        runner.record(f"My account ID: {my_acct_id}", "psql", "")
        if not my_acct_id: return False
        # Get existing favourites + bookmarks to skip
        skip_ids = set()
        favs_raw = runner.mastodon_psql(
            f"SELECT status_id FROM favourites WHERE account_id={my_acct_id}")
        for line in favs_raw.split("\n"):
            line = line.strip()
            if line.isdigit():
                skip_ids.add(line)
        bmarks_raw = runner.mastodon_psql(
            f"SELECT status_id FROM bookmarks WHERE account_id={my_acct_id}")
        for line in bmarks_raw.split("\n"):
            line = line.strip()
            if line.isdigit():
                skip_ids.add(line)
        runner.record(f"Skip IDs (already faved/bookmarked): {len(skip_ids)}", "psql", "")
        # Get #dogs toots from PostgreSQL
        toots_raw = runner.mastodon_psql(
            "SELECT s.id FROM statuses s JOIN statuses_tags st ON s.id=st.status_id "
            "JOIN tags t ON st.tag_id=t.id WHERE t.name='dogs'")
        toot_ids = [l.strip() for l in toots_raw.split("\n") if l.strip().isdigit()]
        for sid in toot_ids:
            if sid not in skip_ids:
                runner.mastodon_favourite_psql(my_acct_id, sid)
                runner.record(f"Favourite new #dogs toot {sid}", "INSERT favourites", "")
        return True

    elif task_name == "MattermostIncidentEscalationTask":
        runner.wait_mattermost()
        from datetime import timedelta
        harry_id = runner.mattermost_psql("SELECT id FROM users WHERE username='harry'").strip()
        if not harry_id:
            harry_id = "p11jse4oa3biikeeefcuggns9o"
        ch_id = runner.mattermost_psql("SELECT id FROM channels WHERE name='support-tickets'").strip()
        runner.record(f"support-tickets channel: {ch_id}", "SELECT channels", "")
        if ch_id:
            msgs = runner.mattermost_psql(
                f"SELECT message FROM posts WHERE channelid='{ch_id}' AND deleteat=0 ORDER BY createat")
            runner.record("Read support ticket messages", "SELECT posts", msgs[:500])
        team_id = runner.mattermost_psql("SELECT id FROM teams WHERE name='neuralforge'").strip()
        ts = str(int(time.time() * 1000))
        inc_ch_id = hashlib.md5(f"incident{ts}".encode()).hexdigest()[:26]
        runner.mattermost_psql(
            f"INSERT INTO channels (id,createat,updateat,deleteat,teamid,type,"
            f"displayname,name,header,purpose,lastpostat,totalmsgcount,"
            f"extraupdateat,creatorid) VALUES "
            f"('{inc_ch_id}',{ts},{ts},0,'{team_id}','O',"
            f"'incident-ticket-500','incident-ticket-500','','',{ts},0,0,'{harry_id}')")
        runner.record("Create incident-ticket-500 channel", "INSERT channels", "")
        sam_id = runner.mattermost_psql("SELECT id FROM users WHERE username='sam'").strip()
        if sam_id:
            runner.mattermost_psql(
                f"INSERT INTO channelmembers (channelid,userid,roles,lastviewedat,"
                f"msgcount,mentioncount,lastupdateat,schemeuser,schemeadmin,schemeguest) "
                f"VALUES ('{inc_ch_id}','{sam_id}','channel_user',0,0,0,{ts},true,false,false) "
                f"ON CONFLICT DO NOTHING")
            runner.record("Add Sam to incident channel", "INSERT channelmembers", "")
        runner.write_email("cto@company.com", "CRITICAL INCIDENT: TICKET-500",
                           "Critical incident: Database connection timeout errors affecting production. "
                           "The database is experiencing intermittent timeout failures.")
        runner.record("Email CTO about critical incident", "write sentEmail.json", "")
        # Use EMULATOR date for tomorrow (not host date)
        emu_now = runner.get_emulator_date()
        tomorrow = emu_now.date() + timedelta(days=1)
        from datetime import datetime, timezone
        ts_cal = int(datetime.combine(tomorrow, datetime.min.time().replace(hour=9),
                                       tzinfo=timezone.utc).timestamp())
        runner.insert_calendar_event("Discussion on TICKET-500", ts_cal, ts_cal + 3600)
        runner.record(f"Schedule emergency meeting for {tomorrow} (emulator date)", "INSERT events", "")
        return True

    elif task_name == "MattermostShiftCoverageTask":
        runner.wait_mattermost()
        from datetime import timedelta
        harry_id = runner.mattermost_psql("SELECT id FROM users WHERE username='harry'").strip()
        if not harry_id:
            harry_id = "p11jse4oa3biikeeefcuggns9o"
        ch_id = runner.mattermost_psql("SELECT id FROM channels WHERE name='shift-requests'").strip()
        runner.record(f"shift-requests channel: {ch_id}", "SELECT channels", "")
        # Use emulator date
        emu_now = runner.get_emulator_date()
        today = emu_now.date()
        days_to_mon = (7 - today.weekday()) % 7
        if days_to_mon == 0:
            days_to_mon = 7
        base = today + timedelta(days=days_to_mon)
        wednesday = base + timedelta(days=2)
        if ch_id:
            msgs = runner.mattermost_psql(
                f"SELECT id,message FROM posts WHERE channelid='{ch_id}' AND deleteat=0 ORDER BY createat ASC")
            runner.record("Read shift request messages", "SELECT posts", msgs[:500])
            alex_msg_id, sofia_msg_id = "", ""
            for line in msgs.split("\n"):
                line = line.strip()
                if not line: continue
                parts = line.split("|", 1)
                if len(parts) == 2:
                    mid, msg = parts[0].strip(), parts[1].strip()
                    if "family emergency" in msg.lower() or "monday" in msg.lower():
                        alex_msg_id = mid
                    if "doctor" in msg.lower() or "wednesday" in msg.lower():
                        sofia_msg_id = mid
            if alex_msg_id:
                runner.mm_post_message(ch_id, harry_id,
                    "Denied: Conflicts with All Hands Meeting on Monday.", root_id=alex_msg_id)
                runner.record("Reply to Alex: denied", "INSERT posts (threaded)", "")
            if sofia_msg_id:
                runner.mm_post_message(ch_id, harry_id,
                    "Request escalated to HR for Wednesday coverage.", root_id=sofia_msg_id)
                runner.record("Reply to Sofia: escalated", "INSERT posts (threaded)", "")
        runner.write_email("hr@company.com", "Shift Swap Request",
                           f"Sofia has requested shift coverage for {wednesday.strftime('%Y-%m-%d')} "
                           f"due to a doctor appointment.")
        runner.record(f"Email HR about shift swap (Wednesday={wednesday})", "write sentEmail.json", "")
        return True

    elif task_name == "MattermostResourceConflictResolutionTask":
        runner.wait_mattermost()
        from datetime import timedelta, datetime, timezone
        harry_id = runner.mattermost_psql("SELECT id FROM users WHERE username='harry'").strip()
        if not harry_id:
            harry_id = "p11jse4oa3biikeeefcuggns9o"
        alex_id = runner.mattermost_psql("SELECT id FROM users WHERE username='alex'").strip()
        ch_id = runner.mattermost_psql("SELECT id FROM channels WHERE name='resource-booking'").strip()
        runner.record(f"resource-booking channel: {ch_id}", "SELECT channels", "")
        if ch_id:
            msgs = runner.mattermost_psql(
                f"SELECT message FROM posts WHERE channelid='{ch_id}' AND deleteat=0 ORDER BY createat")
            runner.record("Read resource booking messages", "SELECT posts", msgs[:500])
        runner.write_email("facilities@company.com", "Resource Booking Conflicts",
                           "APPROVED: Conf Room B, Conf Room C, Projector, Video Camera\\n"
                           "CONFLICT: Conf Room A")
        runner.record("Email conflict report to facilities", "write sentEmail.json", "")
        # Use emulator date for next Monday
        emu_now = runner.get_emulator_date()
        today = emu_now.date()
        days_to_mon = (7 - today.weekday()) % 7
        if days_to_mon == 0:
            days_to_mon = 7
        base = today + timedelta(days=days_to_mon)
        for title, day_off in [("BOOKED: Conf Room B - Sam", 2), ("BOOKED: Conf Room C - Sofia", 1),
                                ("BOOKED: Projector - Sam", 3), ("BOOKED: Video Camera - Mike", 4)]:
            d = base + timedelta(days=day_off)
            ts_cal = int(datetime.combine(d, datetime.min.time().replace(hour=14),
                                           tzinfo=timezone.utc).timestamp())
            runner.insert_calendar_event(title, ts_cal, ts_cal + 3600)
            runner.record(f"Create booking event: {title} on {d}", "INSERT events", "")
        if alex_id:
            dm_ch = runner.mattermost_psql(
                f"SELECT id FROM channels WHERE type='D' AND "
                f"(name LIKE '%{harry_id}%{alex_id}%' OR name LIKE '%{alex_id}%{harry_id}%') LIMIT 1").strip()
            if dm_ch:
                runner.mm_post_message(dm_ch, harry_id,
                                       "Conf Room A booking conflict: Your request overlaps with Team Standup.")
                runner.record("DM Alex about Conf Room A conflict", "INSERT posts", "")
        return True

    elif task_name == "MattermostVisualInstructionResponseTask":
        runner.wait_mattermost()
        ch_id = runner.mattermost_psql("SELECT id FROM channels WHERE name='emergency-response'").strip()
        runner.record(f"emergency-response channel: {ch_id}", "SELECT channels", "")
        if ch_id:
            msgs = runner.mattermost_psql(
                f"SELECT message FROM posts WHERE channelid='{ch_id}' AND deleteat=0 ORDER BY createat")
            runner.record("Read emergency response messages", "SELECT posts", msgs[:500])
        # Create contacts via individual ADB commands (scripts fail through /exec)
        for name, phone in [("Dr. Smith", "555-1010"), ("Safety Officer", "555-2020")]:
            runner.adb("adb shell content insert --uri content://com.android.contacts/raw_contacts "
                       "--bind account_type:s: --bind account_name:s:")
            time.sleep(1)
            cid_raw = runner.adb(
                "adb shell content query --uri content://com.android.contacts/raw_contacts "
                "--projection _id --sort '_id DESC LIMIT 1'")
            cid = ""
            m = re.search(r'_id=(\d+)', cid_raw)
            if m:
                cid = m.group(1)
            if cid:
                runner.adb(f"adb shell content insert --uri content://com.android.contacts/data "
                           f"--bind raw_contact_id:i:{cid} "
                           f"--bind mimetype:s:vnd.android.cursor.item/name "
                           f"--bind data1:s:'{name}'")
                runner.adb(f"adb shell content insert --uri content://com.android.contacts/data "
                           f"--bind raw_contact_id:i:{cid} "
                           f"--bind mimetype:s:vnd.android.cursor.item/phone_v2 "
                           f"--bind data1:s:{phone} --bind data2:i:1")
            runner.record(f"Create contact: {name} ({phone})", "adb content insert", f"cid={cid}")
            time.sleep(1)
        # Use SET_ALARM intent instead of alarm_templates DB insert
        runner.set_alarm_intent(8, 0, "Morning Shift")
        runner.record("Set alarm 08:00 via intent", "am start SET_ALARM", "")
        time.sleep(1)
        runner.set_alarm_intent(20, 0, "Evening Shift")
        runner.record("Set alarm 20:00 via intent", "am start SET_ALARM", "")
        return True

    elif task_name == "ThanksgivingPrepTask":
        from datetime import datetime, timezone
        runner.read_file("/sdcard/Android/data/com.gmailclone/files/state.json")
        runner.record("Read email inbox for context", "read-file state.json", "")
        runner.sql("/data/data/org.fossify.calendar/databases/events.db",
                   "SELECT id,title,start_ts,end_ts FROM events")
        runner.record("Read calendar events", "SELECT events", "")
        runner.write_email("user@gmail.com", "Pie shopping",
                           "Ingredients for Pecan Pie: sugar, corn syrup, vanilla extract, "
                           "eggs, butter, pecans.")
        runner.record("Send ingredient email", "write sentEmail.json", "")
        runner.insert_calendar_event("Thanksgiving Shopping",
            int(datetime(2025, 11, 20, 8, 0, 0, tzinfo=timezone.utc).timestamp()),
            int(datetime(2025, 11, 20, 9, 0, 0, tzinfo=timezone.utc).timestamp()))
        runner.record("Create Thanksgiving Shopping event: Nov 20", "INSERT events", "")
        return True

    # === Phase 2: Dynamic file/date tasks ===

    elif task_name == "BidFileRenameTask":
        # List bid_ files with timestamps using single adb shell command
        raw = runner.adb("adb shell 'cd /sdcard/Download && stat -c \"%Y %n\" bid_* 2>/dev/null | sort -n'")
        runner.record("List bid files by creation date", "stat + sort", raw[:300])
        # Parse timestamps and filenames
        pairs = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line or line.startswith("$"): continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[0].isdigit():
                fname = parts[1].strip().rsplit("/", 1)[-1]  # just filename
                pairs.append((int(parts[0]), fname))
        pairs.sort()
        runner.record(f"Found {len(pairs)} bid files sorted by date", "parse", str(pairs))
        # Rename sequentially
        for i, (ts, fname) in enumerate(pairs, 1):
            ext = fname.rsplit(".", 1)[-1] if "." in fname else ""
            new_name = f"bid_{i}.{ext}"
            if fname != new_name:
                runner.adb(f"adb shell mv /sdcard/Download/{fname} /sdcard/Download/{new_name}")
                runner.record(f"Rename {fname} -> {new_name}", "mv", "")
        runner.adb("adb shell ls /sdcard/Download/bid_*")
        runner.record("Verify renamed files", "ls bid_*", "")
        return True

    elif task_name == "CVEmailTask":
        # Discover CV files
        raw = runner.adb("adb shell ls /sdcard/Download/ | grep -i _CV.pdf")
        runner.record("Find CV files in Download", "ls grep CV", raw[:300])
        cv_files = [f.strip() for f in raw.split("\n") if f.strip() and "_CV" in f and not f.startswith("$")]
        runner.record(f"Found {len(cv_files)} CV files", "parse", str(cv_files))
        # Build attachment list
        attachments = [f"/sdcard/Download/{f}" for f in cv_files]
        runner.write_email("HR_chen@gmail.com", "candidates_cv",
                           "Please find the candidate CVs attached.",
                           attachments=attachments)
        runner.record("Send CV email with attachments", "write sentEmail.json", "")
        runner.read_file("/sdcard/Android/data/com.gmailclone/files/sentEmail.json")
        runner.record("Verify email sent", "read sentEmail.json", "")
        return True

    elif task_name == "ReviewPaperEmailTask":
        # Find review PDFs in Documents (they're in subdirectories)
        raw = runner.adb("adb shell find /sdcard/Documents -name 'review_*.pdf' 2>/dev/null")
        runner.record("Find review PDFs in Documents", "find review_*.pdf", raw[:500])
        review_files = [f.strip() for f in raw.split("\n")
                        if f.strip().endswith(".pdf") and "review_" in f
                        and not f.startswith("$") and "/paper/" not in f]
        runner.record(f"Found {len(review_files)} review PDFs", "parse", str(review_files))
        # Check existing paper/ directory
        raw_existing = runner.adb("adb shell ls /sdcard/Documents/paper/ 2>/dev/null")
        runner.record("Check existing paper/ files", "ls", raw_existing[:200])
        # Move review files to paper/
        runner.adb("adb shell mkdir -p /sdcard/Documents/paper")
        for fpath in review_files:
            fname = fpath.rsplit("/", 1)[-1]
            runner.adb(f"adb shell mv {fpath} /sdcard/Documents/paper/{fname}")
            runner.record(f"Move {fname} to paper/", "mv", "")
        # List ALL files in paper/ (including pre-existing ones)
        raw2 = runner.adb("adb shell ls /sdcard/Documents/paper/")
        runner.record("List all files in paper/", "ls", raw2[:300])
        all_files = [f.strip() for f in raw2.split("\n")
                     if f.strip() and not f.startswith("$")]
        # Email ALL files in paper/ (review PDFs + any pre-existing)
        attachments = [f.rsplit("/", 1)[-1] for f in all_files]  # just filenames
        runner.write_email("chen@gmail.com", "paper",
                           "Please find the papers attached.",
                           attachments=attachments)
        runner.record("Send email with all papers", "write sentEmail.json", "")
        return True

    elif task_name == "InvoiceReceiptCopyTask":
        # List invoice/receipt files with dates
        raw = runner.adb("adb shell ls -la /sdcard/Download/ | grep -iE 'invoice|receipt'")
        runner.record("Find invoice/receipt files", "ls grep", raw[:500])
        # Filter November files by checking date in ls output (2025-11-xx)
        nov_files = []
        for line in raw.split("\n"):
            line = line.strip()
            if "2025-11" in line and ".pdf" in line.lower():
                fname = line.rsplit(None, 1)[-1] if line else ""
                if fname:
                    nov_files.append(fname)
        runner.record(f"November invoice/receipt PDFs: {nov_files}", "filter", "")
        runner.adb("adb shell mkdir -p /sdcard/Finance/invoice")
        runner.record("Create Finance/invoice directory", "mkdir", "")
        for f in nov_files:
            runner.adb(f"adb shell cp /sdcard/Download/{f} /sdcard/Finance/invoice/")
            runner.record(f"Copy {f}", "cp", "")
        runner.adb("adb shell ls /sdcard/Finance/invoice/")
        runner.record("Verify copied files", "ls", "")
        return True

    elif task_name == "SendWaiverTask":
        # Find waiver.jpg
        raw = runner.adb("adb shell find /sdcard -name 'waiver.jpg' -o -name 'waiver.jpeg' 2>/dev/null")
        runner.record("Find waiver file", "find waiver", raw[:300])
        waiver_path = ""
        for line in raw.split("\n"):
            line = line.strip()
            if "waiver" in line.lower() and not line.startswith("$"):
                waiver_path = line
                break
        if not waiver_path:
            waiver_path = "/sdcard/Download/waiver.jpg"
        runner.record(f"Waiver at: {waiver_path}", "parse", "")
        runner.read_file("/sdcard/Android/data/com.gmailclone/files/state.json")
        runner.record("Read email inbox for context", "read-file", "")
        waiver_name = waiver_path.rsplit("/", 1)[-1] if "/" in waiver_path else waiver_path
        runner.write_email("bob@gmail.com", "Updated waiver",
                           "Please find the updated waiver attached.",
                           attachments=[waiver_name])
        runner.record("Send waiver email", "write sentEmail.json", "")
        return True

    elif task_name == "LocalFileManagementTask2":
        # List all files in Download
        raw = runner.adb("adb shell ls -la /sdcard/Download/")
        runner.record("List all Download files with dates", "ls -la", raw[:500])
        # Get current date to determine 1-year threshold
        now_raw = runner.adb("adb shell date +%s", no_tree=True)
        runner.record("Get current time", "date +%s", now_raw[:50])
        # Identify old files (>1 year) by checking dates in ls output
        # Files from 2023 and 2024 are definitely older than 1 year (current ~April 2026)
        old_files = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line or line.startswith("$") or line.startswith("total"): continue
            # Match dates like 2024-01-25 or 2023-11-16
            if ("2023-" in line or "2024-" in line) and ".zip" in line:
                fname = line.rsplit(None, 1)[-1] if line else ""
                if fname and fname.endswith(".zip"):
                    old_files.append(fname)
        runner.record(f"Found {len(old_files)} files older than 1 year", "filter", str(old_files))
        # Write a Python script to device, execute it to create zip (no zip binary)
        if old_files:
            files_str = ",".join(f"'{f}'" for f in old_files)
            script = (
                "import zipfile, os\n"
                "os.chdir('/sdcard/Download')\n"
                f"files = [{files_str}]\n"
                "z = zipfile.ZipFile('old_files.zip', 'w', zipfile.ZIP_DEFLATED)\n"
                "for f in files:\n"
                "    if os.path.exists(f):\n"
                "        z.write(f)\n"
                "z.close()\n"
                "for f in files:\n"
                "    if os.path.exists(f):\n"
                "        os.remove(f)\n"
                "print('done')\n"
            )
            runner.write_file("/sdcard/_zip_cleanup.py", script)
            runner.record("Write zip+cleanup Python script", "write-file", "")
            # Android has python3 via termux or we use the container's python via adb
            # Actually the emulator doesn't have python. Use container python to run via adb.
            # Instead, write a shell script that uses toybox for simple archive
            # Actually simplest: pull to container, zip, push back — but avoid adb pull binary
            # Use exec to run the zip from container side
            runner.exec_cmd(
                f"adb -s emulator-5554 pull /sdcard/Download/01_archive_20240924.zip /tmp/ 2>/dev/null; "
                + " ".join(f"adb -s emulator-5554 pull /sdcard/Download/{f} /tmp/ 2>/dev/null;" for f in old_files)
            )
            runner.record(f"Pull {len(old_files)} files to container", "exec adb pull", "")
            runner.exec_cmd(
                "cd /tmp && python3 -c \""
                "import zipfile; z=zipfile.ZipFile('old_files.zip','w',zipfile.ZIP_DEFLATED); "
                "import os; [z.write(f,f) for f in os.listdir('.') if f.endswith('.zip') and f!='old_files.zip']; "
                "z.close(); print('zipped')\""
            )
            runner.record("Create zip via Python in container", "exec python3 zipfile", "")
            runner.exec_cmd("adb -s emulator-5554 push /tmp/old_files.zip /sdcard/Download/old_files.zip")
            runner.record("Push old_files.zip to device", "exec adb push", "")
            # Delete originals
            for f in old_files:
                runner.adb(f"adb shell rm /sdcard/Download/{f}", no_tree=True)
            runner.record(f"Deleted {len(old_files)} old files", "rm", "")
            runner.exec_cmd("rm -f /tmp/*.zip")
        runner.adb("adb shell ls /sdcard/Download/old_files.zip")
        runner.record("Verify zip exists", "ls", "")
        body = "Archived old files: " + ", ".join(old_files)
        runner.write_email("test@gmail.com", "Archived Files", body)
        runner.record("Send email listing deleted files", "write sentEmail.json", "")
        return True

    elif task_name == "SetAlarmTask":
        # Weekend = Saturday + Sunday = daysofweek 96 (32+64)
        # First check existing alarms
        ALARM_DB = "/data/user_de/0/com.google.android.deskclock/databases/alarms.db"
        runner.sql(ALARM_DB, ".tables")
        runner.record("Check alarm tables", "sql .tables", "")
        runner.sql(ALARM_DB, "SELECT * FROM alarm_templates")
        runner.record("Check existing alarms", "SELECT alarm_templates", "")
        # Write SQL to file on device, then execute via script (avoids quoting)
        sql = ("INSERT INTO alarm_templates (hour,minutes,enabled,daysofweek,vibrate,"
               "ringtone,label,delete_after_use,wakeup) VALUES "
               "(8,25,1,96,0,'content://media/internal/audio/media/beebeep','Weekend',0,0);")
        runner.write_file("/sdcard/_alarm.sql", sql)
        script = f"#!/system/bin/sh\nsu root sqlite3 {ALARM_DB} < /sdcard/_alarm.sql\n"
        runner.write_file("/sdcard/_run_alarm.sh", script)
        runner.adb("adb shell sh /sdcard/_run_alarm.sh")
        runner.adb("adb shell rm /sdcard/_alarm.sql /sdcard/_run_alarm.sh")
        runner.record("Insert alarm: 8:25, weekend, beebeep, no vibrate", "INSERT alarm_templates", "")
        # Verify
        raw = runner.sql(ALARM_DB, "SELECT hour,minutes,daysofweek,vibrate,ringtone FROM alarm_templates WHERE hour=8 AND minutes=25")
        runner.record("Verify alarm settings", "SELECT alarm_templates", raw[:200])
        return True

    return False


# =========================================================================
# Main: broker-based parallel execution
# =========================================================================

_print_lock = threading.Lock()

def log(msg):
    with _print_lock:
        print(msg, flush=True)


def restart_mw_server(server_url, container_name=None):
    """Restart MobileWorld server to clear accumulated task state.

    Uses docker exec from the host (can't use /exec because killing the
    server kills the /exec endpoint itself).
    """
    if not container_name:
        # Try to find container by port
        port = server_url.split(":")[-1].rstrip("/")
        r = subprocess.run(
            f"docker ps --format '{{{{.Names}}}}\\t{{{{.Ports}}}}' | grep ':{port}->'",
            shell=True, capture_output=True, text=True, timeout=5)
        if r.stdout.strip():
            container_name = r.stdout.strip().split("\t")[0]
    if not container_name:
        return False

    # Kill and restart server
    subprocess.run(["docker", "exec", container_name, "pkill", "-f", "mobile-world server"],
                   capture_output=True, timeout=10)
    time.sleep(3)
    subprocess.run(
        ["docker", "exec", "-d", container_name, "bash", "-c",
         "cd /app/service && uv run mobile-world server --port 6800 > /var/log/server.log 2>&1"],
        capture_output=True, timeout=10)

    # Wait for server to come back
    for _ in range(20):
        try:
            req = urllib.request.Request(f"{server_url}/health")
            urllib.request.urlopen(req, timeout=3)
            return True
        except:
            time.sleep(1)
    return False


def _find_container_name(server_url):
    """Find Docker container name from server URL port."""
    port = server_url.rstrip("/").split(":")[-1]
    r = subprocess.run(
        f"docker ps --format '{{{{.Names}}}}\\t{{{{.Ports}}}}' | grep ':{port}->'",
        shell=True, capture_output=True, text=True, timeout=5)
    if r.stdout.strip():
        return r.stdout.strip().split("\t")[0].split("\n")[0]
    return None


def run_one_task(task_name, broker_url, results, goals):
    """Acquire container, restart server, init task, run GT, eval, release."""
    container_info = None
    try:
        container_info = broker_acquire(broker_url, timeout=300)
    except Exception as e:
        log(f"  {task_name}: ACQUIRE FAILED: {e}")
        results.append({"task_name": task_name, "status": "ERROR", "reason": str(e), "steps": 0})
        return

    env_id = container_info["env_id"]
    server_url = container_info["server_url"]
    device_id = container_info.get("device_id", "emulator-5554")

    try:
        # Tasks with server state accumulation bug need MW server restart
        NEEDS_SERVER_RESTART = {
            "InvoiceReceiptCopyAskUserTask", "InvoiceReceiptCopyTask",
            "BidFileRenameTask", "CVEmailTask", "ReviewPaperEmailTask",
        }
        if task_name in NEEDS_SERVER_RESTART:
            cname = _find_container_name(server_url)
            if cname:
                restart_mw_server(server_url, container_name=cname)

        # Teardown any previous task state first
        try:
            http_post(f"{server_url}/task/tear_down",
                      {"task_name": task_name, "req_device": device_id})
        except:
            pass
        time.sleep(2)

        # Init task (this restarts Mastodon/Mattermost docker-compose with fresh data)
        http_post(f"{server_url}/task/init",
                  {"task_name": task_name, "req_device": device_id})

        # Wait for backend services (Mastodon docker-compose restart takes ~25s)
        if "Mastodon" in task_name or "Mattermost" in task_name:
            time.sleep(30)
        else:
            time.sleep(8)

        # Create runner with mw_env.py interface
        runner = MwEnvRunner(server_url, device_id)

        # Run the same task logic
        try:
            success = run_task(task_name, runner)
        except Exception as e:
            log(f"  {task_name}: RUN ERROR: {e}")
            success = False

        # Eval
        time.sleep(2)
        try:
            r = http_get_json_body(f"{server_url}/task/eval",
                                   {"task_name": task_name, "req_device": device_id})
            score = r.get("score", 0.0)
            reason = r.get("reason", "")
        except Exception as e:
            score, reason = 0.0, str(e)

        status = "PASS" if score > 0 else "FAIL"
        log(f"  {task_name}: {status} (score={score}, steps={len(runner.steps)}, reason={reason[:60]})")

        results.append({
            "task_name": task_name,
            "status": status,
            "score": score,
            "reason": reason,
            "steps": len(runner.steps),
            "step_details": runner.steps,
        })

        # Teardown
        try:
            http_post(f"{server_url}/task/tear_down",
                      {"task_name": task_name, "req_device": device_id})
        except:
            pass

        runner.cleanup()
        broker_release(broker_url, env_id, healthy=True)

    except Exception as e:
        log(f"  {task_name}: EXCEPTION: {e}")
        results.append({"task_name": task_name, "status": "ERROR", "reason": str(e), "steps": 0})
        if container_info:
            try:
                broker_release(broker_url, env_id, healthy=False)
            except:
                pass


def main():
    parser = argparse.ArgumentParser(description="Run GT through mw_env.py with broker")
    parser.add_argument("--broker-url", required=True, help="Broker URL (e.g. http://localhost:9400)")
    parser.add_argument("--pool-size", type=int, default=16, help="Max parallel workers")
    parser.add_argument("--tasks", type=str, default=None, help="Comma-separated task names (default: all 88)")
    parser.add_argument("--output-dir", default="../../results/GroundTruth_mobileworld_mwenv_verified")
    args = parser.parse_args()

    goals = load_goals()
    os.makedirs(args.output_dir, exist_ok=True)

    if args.tasks:
        task_list = args.tasks.split(",")
    else:
        # Include IMPLEMENTED + DOCKER_EXEC_TASKS + JSON-only tasks
        gt_json = _load_gt_json()
        all_gt_tasks = set(IMPLEMENTED) | DOCKER_EXEC_TASKS | set(gt_json.keys())
        task_list = sorted(t for t in all_gt_tasks if t in goals)

    log(f"Tasks: {len(task_list)}, Pool: {args.pool_size}")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.pool_size) as pool:
        futures = {
            pool.submit(run_one_task, task_name, args.broker_url, results, goals): task_name
            for task_name in task_list
        }
        for future in concurrent.futures.as_completed(futures):
            task_name = futures[future]
            try:
                future.result()
            except Exception as e:
                log(f"  {task_name}: FUTURE ERROR: {e}")

    # Write results
    results.sort(key=lambda r: r["task_name"])
    out_file = os.path.join(args.output_dir, "results.jsonl")
    with open(out_file, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "ERROR")

    log(f"\n{'='*60}")
    log(f"RESULTS: {passed} PASS / {failed} FAIL / {errors} ERROR out of {len(results)}")

    if failed > 0:
        log(f"\nFailed tasks:")
        for r in results:
            if r["status"] == "FAIL":
                log(f"  {r['task_name']:50s} {r['reason'][:60]}")


if __name__ == "__main__":
    main()
