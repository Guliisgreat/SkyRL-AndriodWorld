#!/usr/bin/env python3
"""
Minimal mw_env.py — CLI bridge between GT runner and MobileWorld container.

Each subcommand translates to HTTP calls to the MW server's /exec endpoint
(or other endpoints as needed).

Environment variables:
    MW_SERVER_URL   — MW container URL (e.g. http://localhost:6804)
    MW_DEVICE_ID    — Emulator device ID (default: emulator-5554)
    MW_STATE_FILE   — Path to state tracking JSON file
    MW_DISABLE_TREE — "1" to skip accessibility tree capture
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

SERVER_URL = os.environ.get("MW_SERVER_URL", "http://localhost:6804")
DEVICE_ID = os.environ.get("MW_DEVICE_ID", "emulator-5554")


def _exec(command, timeout=120):
    """Execute command via MW server's /exec endpoint."""
    data = json.dumps({"command": command}).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/exec", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            return result.get("command_output", "")
    except Exception as e:
        return f"ERROR: {e}"


def _step(payload, timeout=30):
    """Call MW server's /step endpoint."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/step", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def cmd_adb(args):
    command = args.command
    print(f"$ {command}")
    output = _exec(command)
    print(output)


def cmd_sql(args):
    db_path = args.db_path
    query = args.query
    # Execute sqlite3 via adb shell with su root
    # Try multiple quoting strategies
    cmd = f'''adb shell "su 0 sqlite3 {db_path} '{query}'"'''
    print(f"$ sqlite3 {db_path}")
    print(f"  SQL: {query}")
    output = _exec(cmd)
    if not output or "error" in output.lower():
        # Retry with different quoting
        cmd2 = f'adb shell su 0 sqlite3 {db_path} "{query}"'
        output2 = _exec(cmd2)
        if output2 and "error" not in output2.lower():
            output = output2
    if not output:
        print("(no output)")
    else:
        print(output)


def cmd_read_file(args):
    path = args.path
    if path.endswith(".pdf"):
        # PDFs can't be cat'd meaningfully, just check existence
        print(f"$ cat {path}")
        output = _exec(f"adb shell ls -la {path}")
        print(output if output else "(file not found)")
    elif path.startswith("/sdcard/") or path.startswith("/data/"):
        print(f"$ cat {path}")
        output = _exec(f"adb shell cat {path}")
        print(output if output else "(no output)")
    else:
        # Host filesystem
        print(f"$ cat {path}")
        output = _exec(f"cat {path}")
        print(output if output else "(no output)")


def cmd_write_file(args):
    path = args.path
    content = args.content
    if path.startswith("/sdcard/") or path.startswith("/data/"):
        # Write to device via adb shell
        # Use base64 to avoid quoting issues
        import base64
        encoded = base64.b64encode(content.encode()).decode()
        cmd = f"adb shell 'echo {encoded} | base64 -d > {path}'"
        output = _exec(cmd)
        if not output or "error" in (output or "").lower():
            # Fallback: write to container, push to device
            import tempfile
            _exec(f"echo '{encoded}' | base64 -d > /tmp/_mwenv_write")
            _exec(f"adb push /tmp/_mwenv_write {path}")
            _exec("rm -f /tmp/_mwenv_write")
        print(f"$ write {path} ({len(content)} bytes)")
    else:
        # Host filesystem — write via exec
        import base64
        encoded = base64.b64encode(content.encode()).decode()
        _exec(f"mkdir -p $(dirname {path})")
        _exec(f"echo '{encoded}' | base64 -d > {path}")
        print(f"$ write {path} ({len(content)} bytes)")


def cmd_find_files(args):
    directory = args.directory
    pattern = args.pattern
    print(f"$ find {directory} -name '{pattern}'")
    output = _exec(f"adb shell find {directory} -name '{pattern}' 2>/dev/null")
    print(output if output else "(no files found)")


def cmd_exec(args):
    command = args.command
    print(f"$ {command}")
    output = _exec(command, timeout=120)
    print(output if output else "(no output)")


def cmd_http(args):
    method = args.method.upper()
    url = args.url
    headers = args.headers or ""
    data = args.data or ""

    # If URL targets localhost:6800, it's the MW server itself
    if "localhost:6800" in url or "localhost:680" in url:
        # Rewrite to use our server URL
        import re
        url = re.sub(r'http://localhost:680\d', SERVER_URL, url)

    print(f"$ {method} {url}")

    if url.startswith("file://"):
        # file:// URLs write callback files
        file_path = url.replace("file://", "")
        # Extract X-Filename header
        filename = ""
        if "X-Filename:" in headers or "X-Filename" in headers:
            import re
            m = re.search(r'X-Filename[:\s]+(\S+)', headers)
            if m:
                filename = m.group(1)
        if filename and data:
            full_path = f"{file_path}/{filename}"
            import base64
            encoded = base64.b64encode(data.encode()).decode()
            _exec(f"mkdir -p {file_path}")
            _exec(f"echo '{encoded}' | base64 -d > {full_path}")
            print(f"Written callback: {full_path}")
        return

    # Build urllib request
    req_data = data.encode() if data else None
    req = urllib.request.Request(url, data=req_data, method=method)
    req.add_header("Content-Type", "application/json")
    if "Authorization" in headers:
        import re
        m = re.search(r'Bearer\s+(\S+)', headers)
        if m:
            req.add_header("Authorization", f"Bearer {m.group(1)}")

    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            result = resp.read().decode()
            print(result[:2000])
    except Exception as e:
        print(f"HTTP ERROR: {e}")


def cmd_finish(args):
    status = args.status or "complete"
    description = args.description or ""

    # Submit answer if description looks like a value
    if description:
        _step({
            "device": DEVICE_ID,
            "action": {"action_type": "answer", "text": description}
        })
    print(f"FINISH: status={status} description={description}")


def main():
    parser = argparse.ArgumentParser(description="MobileWorld environment CLI")
    subparsers = parser.add_subparsers(dest="subcommand")

    # adb
    p_adb = subparsers.add_parser("adb")
    p_adb.add_argument("command")
    p_adb.add_argument("--no-tree", action="store_true")

    # sql
    p_sql = subparsers.add_parser("sql")
    p_sql.add_argument("db_path")
    p_sql.add_argument("query")

    # read-file
    p_rf = subparsers.add_parser("read-file")
    p_rf.add_argument("path")

    # write-file
    p_wf = subparsers.add_parser("write-file")
    p_wf.add_argument("path")
    p_wf.add_argument("content")

    # find-files
    p_ff = subparsers.add_parser("find-files")
    p_ff.add_argument("directory")
    p_ff.add_argument("pattern")

    # exec
    p_exec = subparsers.add_parser("exec")
    p_exec.add_argument("command")

    # http
    p_http = subparsers.add_parser("http")
    p_http.add_argument("method")
    p_http.add_argument("url")
    p_http.add_argument("--headers", default="")
    p_http.add_argument("--data", default="")

    # finish
    p_finish = subparsers.add_parser("finish")
    p_finish.add_argument("--status", default="complete")
    p_finish.add_argument("--description", default="")

    args = parser.parse_args()

    handlers = {
        "adb": cmd_adb,
        "sql": cmd_sql,
        "read-file": cmd_read_file,
        "write-file": cmd_write_file,
        "find-files": cmd_find_files,
        "exec": cmd_exec,
        "http": cmd_http,
        "finish": cmd_finish,
    }

    handler = handlers.get(args.subcommand)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
