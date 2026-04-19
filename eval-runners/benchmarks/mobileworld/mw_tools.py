#!/usr/bin/env python3
"""
mw_tools.py — CLI tool suite for Claude Code agent on MobileWorld.

Each subcommand translates to HTTP calls against the MobileWorld container's
/exec or /step endpoint.  Tools handle escaping, encoding, and multi-layer
command nesting so the agent generates high-level commands instead of fragile
raw bash.

Environment variables:
    MW_SERVER_URL   — MW container URL (e.g. http://localhost:6804)
    MW_DEVICE_ID    — Emulator device ID (default: emulator-5554)
    MW_STATE_FILE   — Path to state tracking JSON file
"""

import argparse
import base64
import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SERVER_URL = os.environ.get("MW_SERVER_URL", "http://localhost:6804")
DEVICE_ID = os.environ.get("MW_DEVICE_ID", "emulator-5554")
MAX_OUTPUT = 4000  # Truncation limit for tool output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    """Truncate text and append marker if over limit."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated]"


def _exec(command: str, timeout: int = 120) -> str:
    """Execute command via MW server's /exec endpoint."""
    data = json.dumps({"command": command}).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/exec", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            return result.get("command_output", "")
    except urllib.error.URLError as e:
        return f"ERROR: connection failed: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def _step(payload: dict, timeout: int = 30) -> dict:
    """Call MW server's /step endpoint."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/step", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def _is_device_path(path: str) -> bool:
    """Check if path is on the Android device (vs host filesystem)."""
    return path.startswith("/sdcard/") or path.startswith("/data/")


# =========================================================================
# CORE TOOLS (Phase 1)
# =========================================================================

def cmd_adb(args):
    """Run an ADB command on the device."""
    command = args.command
    print(f"$ {command}")
    output = _exec(command)
    print(_truncate(output) if output else "(no output)")


def cmd_exec(args):
    """Run any shell command inside the container."""
    command = args.command
    timeout = getattr(args, "timeout", 120) or 120
    print(f"$ {command}")
    output = _exec(command, timeout=timeout)
    print(_truncate(output) if output else "(no output)")


def cmd_sql(args):
    """Execute SQLite query on a device database (auto root, stdin piping)."""
    db_path = args.db_path
    query = args.query
    print(f"$ sqlite3 {db_path}")
    print(f"  SQL: {query}")

    # Strategy 1: pipe SQL via stdin with base64 (most reliable)
    encoded = base64.b64encode(query.encode()).decode()
    cmd = f"adb shell \"echo {encoded} | base64 -d | su 0 sqlite3 {db_path}\""
    output = _exec(cmd)

    # Strategy 2: direct quoting fallback
    if not output or "error" in output.lower() or "not found" in output.lower():
        cmd2 = f'''adb shell "su 0 sqlite3 {db_path} '{query}'"'''
        output2 = _exec(cmd2)
        if output2 and "error" not in output2.lower():
            output = output2

    # Strategy 3: alternate quoting
    if not output or "error" in output.lower():
        cmd3 = f'adb shell su 0 sqlite3 {db_path} "{query}"'
        output3 = _exec(cmd3)
        if output3 and "error" not in output3.lower():
            output = output3

    print(_truncate(output) if output else "(no output)")


def cmd_read_file(args):
    """Read file from device or container. Supports PDF text extraction."""
    path = args.path
    print(f"$ read {path}")

    if path.lower().endswith(".pdf"):
        # Try pdftotext first (on container)
        if _is_device_path(path):
            # Pull to container tmp, then extract
            _exec(f"adb pull {shlex.quote(path)} /tmp/_mw_pdf_read.pdf")
            pdf_tmp = "/tmp/_mw_pdf_read.pdf"
        else:
            pdf_tmp = path

        output = _exec(f"pdftotext {shlex.quote(pdf_tmp)} -")
        if not output or "error" in output.lower() or "not found" in output.lower():
            # Fallback: python3 with PyMuPDF
            py_cmd = (
                f"python3 -c \""
                f"import fitz; doc=fitz.open('{pdf_tmp}'); "
                f"print('\\n'.join(p.get_text() for p in doc))\""
            )
            output = _exec(py_cmd)
        if not output or "error" in output.lower():
            # Last resort: strings
            output = _exec(f"strings {shlex.quote(pdf_tmp)}")
        if _is_device_path(path):
            _exec("rm -f /tmp/_mw_pdf_read.pdf")
        print(_truncate(output) if output else "(could not extract PDF text)")
        return

    # Regular file
    if _is_device_path(path):
        output = _exec(f"adb shell cat {shlex.quote(path)}")
    else:
        output = _exec(f"cat {shlex.quote(path)}")
    print(_truncate(output) if output else "(empty or not found)")


def cmd_write_file(args):
    """Write content to file on device or container (base64-safe)."""
    path = args.path
    content = args.content
    append = getattr(args, "append", False)
    operator = ">>" if append else ">"

    encoded = base64.b64encode(content.encode()).decode()

    if _is_device_path(path):
        # Write via adb shell with base64
        cmd = f"adb shell \"echo {encoded} | base64 -d {operator} {path}\""
        output = _exec(cmd)
        if output and "error" in output.lower():
            # Fallback: write to container tmp, then push
            _exec(f"echo '{encoded}' | base64 -d > /tmp/_mw_write_tmp")
            if append:
                # Pull existing, append, push back
                _exec(f"adb pull {shlex.quote(path)} /tmp/_mw_write_existing 2>/dev/null")
                _exec("cat /tmp/_mw_write_tmp >> /tmp/_mw_write_existing")
                _exec(f"adb push /tmp/_mw_write_existing {shlex.quote(path)}")
                _exec("rm -f /tmp/_mw_write_existing /tmp/_mw_write_tmp")
            else:
                _exec(f"adb push /tmp/_mw_write_tmp {shlex.quote(path)}")
                _exec("rm -f /tmp/_mw_write_tmp")
    else:
        # Host filesystem
        dir_path = os.path.dirname(path)
        if dir_path:
            _exec(f"mkdir -p {shlex.quote(dir_path)}")
        _exec(f"echo '{encoded}' | base64 -d {operator} {shlex.quote(path)}")

    mode = "appended" if append else "wrote"
    print(f"{mode} {path} ({len(content)} bytes)")


def cmd_find_files(args):
    """Search files by glob pattern."""
    directory = args.directory
    pattern = args.pattern
    maxdepth = getattr(args, "maxdepth", 5) or 5
    print(f"$ find {directory} -name '{pattern}' -maxdepth {maxdepth}")

    if _is_device_path(directory) or directory == "/":
        cmd = f"adb shell find {shlex.quote(directory)} -maxdepth {maxdepth} -name {shlex.quote(pattern)} 2>/dev/null"
    else:
        cmd = f"find {shlex.quote(directory)} -maxdepth {maxdepth} -name {shlex.quote(pattern)} 2>/dev/null"
    output = _exec(cmd)
    print(_truncate(output) if output else "(no files found)")


def cmd_http(args):
    """Make an HTTP request."""
    method = args.method.upper()
    url = args.url
    headers_str = args.headers or ""
    data = args.data or ""

    # Rewrite localhost:6800 to our server URL
    if re.search(r'localhost:680\d', url):
        url = re.sub(r'http://localhost:680\d', SERVER_URL, url)

    print(f"$ {method} {url}")

    req_data = data.encode() if data else None
    req = urllib.request.Request(url, data=req_data, method=method)
    req.add_header("Content-Type", "application/json")

    # Parse headers
    if headers_str:
        for part in headers_str.split(";"):
            part = part.strip()
            if ":" in part:
                k, v = part.split(":", 1)
                req.add_header(k.strip(), v.strip())

    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            result = resp.read().decode()
            print(_truncate(result))
    except Exception as e:
        print(f"ERROR: {e}")


def cmd_finish(args):
    """Signal task completion."""
    status = args.status or "complete"
    description = args.description or ""

    if description:
        _step({
            "device": DEVICE_ID,
            "action": {"action_type": "answer", "text": description},
        })
    print(f"FINISH: status={status} description={description}")


# =========================================================================
# BACKEND & DOCKER TOOLS (Phase 2)
# =========================================================================

def cmd_pg(args):
    """Query PostgreSQL database running in a Docker container."""
    container_pattern = args.container_pattern
    database = args.database
    query = args.query
    user = getattr(args, "user", "postgres") or "postgres"

    print(f"$ pg [{container_pattern}] {database}")
    print(f"  SQL: {query}")

    # Auto-discover container name
    discover_cmd = f"docker ps --format '{{{{.Names}}}}' | grep -i {shlex.quote(container_pattern)}"
    container_names = _exec(discover_cmd).strip()

    if not container_names:
        print(f"ERROR: no running container matching '{container_pattern}'")
        return

    # Use the first match
    container = container_names.split("\n")[0].strip()
    print(f"  container: {container}")

    # Pipe SQL via stdin to avoid escaping issues
    encoded = base64.b64encode(query.encode()).decode()
    cmd = f"echo {encoded} | base64 -d | docker exec -i {shlex.quote(container)} psql -U {shlex.quote(user)} -d {shlex.quote(database)} -t"
    output = _exec(cmd, timeout=30)
    print(_truncate(output) if output else "(no output)")


def cmd_service_status(args):
    """Check Docker service health, or start/stop compose services."""
    pattern = getattr(args, "pattern", None)
    start_dir = getattr(args, "start", None)
    stop_dir = getattr(args, "stop", None)

    if start_dir:
        print(f"$ docker compose up -d (in {start_dir})")
        # Try docker-compose.yml variants
        compose_files = _exec(f"ls {shlex.quote(start_dir)}/docker-compose*.yml 2>/dev/null").strip()
        if not compose_files:
            compose_files = _exec(f"ls {shlex.quote(start_dir)}/compose*.yml 2>/dev/null").strip()
        if not compose_files:
            print(f"ERROR: no compose file found in {start_dir}")
            return

        # Build -f flags for all compose files
        files = compose_files.split("\n")
        f_flags = " ".join(f"-f {shlex.quote(f.strip())}" for f in files if f.strip())
        cmd = f"cd {shlex.quote(start_dir)} && docker compose {f_flags} up -d"
        output = _exec(cmd, timeout=120)
        print(_truncate(output) if output else "(started)")
        return

    if stop_dir:
        print(f"$ docker compose down (in {stop_dir})")
        cmd = f"cd {shlex.quote(stop_dir)} && docker compose down"
        output = _exec(cmd, timeout=60)
        print(_truncate(output) if output else "(stopped)")
        return

    # List running containers
    fmt = "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    cmd = f"docker ps --format '{fmt}'"
    if pattern:
        cmd += f" | grep -i {shlex.quote(pattern)}"
        print(f"$ docker ps | grep {pattern}")
    else:
        print("$ docker ps")

    output = _exec(cmd)
    print(_truncate(output) if output else "(no running containers)")


# =========================================================================
# STRUCTURED DATA TOOLS (Phase 3)
# =========================================================================

def _json_path_extract(data, expr: str):
    """Simple jq-like path evaluator: .key, .[0], .key[0].subkey, .key[*].subkey"""
    if not expr or expr == ".":
        return data

    # Tokenize: split on '.' but respect [n]
    tokens = []
    for part in re.findall(r'[^.\[\]]+|\[\d+\]|\[\*\]', expr):
        if part.startswith("[") and part.endswith("]"):
            inner = part[1:-1]
            tokens.append(int(inner) if inner != "*" else "*")
        elif part:
            tokens.append(part)

    current = data
    for token in tokens:
        if token == "*":
            if isinstance(current, list):
                # Collect remaining path from rest of tokens
                rest_idx = tokens.index(token) + 1
                rest_tokens = tokens[rest_idx:]
                if not rest_tokens:
                    return current
                rest_expr = "." + ".".join(
                    f"[{t}]" if isinstance(t, int) else str(t) for t in rest_tokens
                )
                return [_json_path_extract(item, rest_expr) for item in current]
            return current
        elif isinstance(token, int):
            if isinstance(current, list) and -len(current) <= token < len(current):
                current = current[token]
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(token)
            if current is None:
                return None
        else:
            return None
    return current


def cmd_json_read(args):
    """Read and parse JSON file, optionally extract fields."""
    path = args.path
    expr = getattr(args, "expr", None)

    print(f"$ json-read {path}" + (f" {expr}" if expr else ""))

    # Read raw content
    if _is_device_path(path):
        raw = _exec(f"adb shell cat {shlex.quote(path)}")
    else:
        raw = _exec(f"cat {shlex.quote(path)}")

    if not raw or raw.startswith("ERROR:"):
        print(raw or "(empty or not found)")
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}")
        print(_truncate(raw))
        return

    if expr:
        result = _json_path_extract(data, expr)
        if result is None:
            print(f"(no match for '{expr}')")
        elif isinstance(result, (dict, list)):
            print(_truncate(json.dumps(result, indent=2, ensure_ascii=False)))
        else:
            print(str(result))
    else:
        print(_truncate(json.dumps(data, indent=2, ensure_ascii=False)))


def cmd_json_write(args):
    """Write structured JSON to file."""
    path = args.path
    content = args.content
    merge = getattr(args, "merge", False)

    print(f"$ json-write {path}" + (" (merge)" if merge else ""))

    # Validate JSON
    try:
        new_data = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON input: {e}")
        return

    if merge:
        # Read existing file
        if _is_device_path(path):
            raw = _exec(f"adb shell cat {shlex.quote(path)}")
        else:
            raw = _exec(f"cat {shlex.quote(path)}")
        if raw and not raw.startswith("ERROR:"):
            try:
                existing = json.loads(raw)
                if isinstance(existing, dict) and isinstance(new_data, dict):
                    existing.update(new_data)
                    new_data = existing
            except json.JSONDecodeError:
                pass  # Overwrite if existing is not valid JSON

    final_json = json.dumps(new_data, ensure_ascii=False)
    encoded = base64.b64encode(final_json.encode()).decode()

    if _is_device_path(path):
        cmd = f"adb shell \"echo {encoded} | base64 -d > {path}\""
        output = _exec(cmd)
        if output and "error" in output.lower():
            _exec(f"echo '{encoded}' | base64 -d > /tmp/_mw_json_tmp")
            _exec(f"adb push /tmp/_mw_json_tmp {shlex.quote(path)}")
            _exec("rm -f /tmp/_mw_json_tmp")
    else:
        dir_path = os.path.dirname(path)
        if dir_path:
            _exec(f"mkdir -p {shlex.quote(dir_path)}")
        _exec(f"echo '{encoded}' | base64 -d > {shlex.quote(path)}")

    print(f"wrote {path} ({len(final_json)} bytes)")


# =========================================================================
# ANDROID PLATFORM TOOLS (Phase 4)
# =========================================================================

def cmd_content(args):
    """Android content provider operations."""
    operation = args.operation  # query, insert, update, delete
    uri = args.uri

    print(f"$ content {operation} {uri}")

    if operation == "query":
        cmd_parts = [f"adb shell content query --uri {uri}"]
        if args.projection:
            cmd_parts.append(f"--projection {args.projection}")
        if args.where:
            cmd_parts.append(f"--where {shlex.quote(args.where)}")
        if args.sort:
            cmd_parts.append(f"--sort {shlex.quote(args.sort)}")
        output = _exec(" ".join(cmd_parts))

    elif operation == "insert":
        cmd_parts = [f"adb shell content insert --uri {uri}"]
        for bind in (args.bind or []):
            cmd_parts.append(f"--bind {bind}")
        output = _exec(" ".join(cmd_parts))

    elif operation == "update":
        cmd_parts = [f"adb shell content update --uri {uri}"]
        if args.where:
            cmd_parts.append(f"--where {shlex.quote(args.where)}")
        for bind in (args.bind or []):
            cmd_parts.append(f"--bind {bind}")
        output = _exec(" ".join(cmd_parts))

    elif operation == "delete":
        cmd_parts = [f"adb shell content delete --uri {uri}"]
        if args.where:
            cmd_parts.append(f"--where {shlex.quote(args.where)}")
        output = _exec(" ".join(cmd_parts))

    else:
        print(f"ERROR: unknown operation '{operation}'. Use: query, insert, update, delete")
        return

    print(_truncate(output) if output else "(no output)")


def cmd_intent(args):
    """Fire Android intents (am start / am broadcast)."""
    mode = args.mode  # start or broadcast
    target = args.target
    extras = args.extra or []
    data_uri = getattr(args, "data", None)
    flags = getattr(args, "flags", None)

    # Build am command
    if mode == "start":
        cmd_parts = ["adb shell am start"]
    elif mode == "broadcast":
        cmd_parts = ["adb shell am broadcast"]
    else:
        print(f"ERROR: unknown mode '{mode}'. Use: start, broadcast")
        return

    # Detect action vs component
    if target.startswith("android.") or target.startswith("-a "):
        if not target.startswith("-a "):
            cmd_parts.append(f"-a {target}")
        else:
            cmd_parts.append(target)
    elif "/" in target:
        cmd_parts.append(f"-n {target}")
    else:
        # Assume action
        cmd_parts.append(f"-a {target}")

    # Data URI
    if data_uri:
        cmd_parts.append(f"-d {shlex.quote(data_uri)}")

    # Flags
    if flags:
        cmd_parts.append(f"--flags {flags}")

    # Extras: type:key:value
    type_map = {
        "s": "--es", "i": "--ei", "z": "--ez",
        "l": "--el", "f": "--ef", "u": "--eu",
    }
    for extra in extras:
        parts = extra.split(":", 2)
        if len(parts) != 3:
            print(f"ERROR: invalid extra '{extra}'. Format: type:key:value (e.g., s:name:John)")
            return
        etype, ekey, evalue = parts
        flag = type_map.get(etype)
        if not flag:
            print(f"ERROR: unknown extra type '{etype}'. Use: s(tring), i(nt), z(bool), l(ong), f(loat)")
            return
        cmd_parts.append(f"{flag} {ekey} {shlex.quote(evalue)}")

    full_cmd = " ".join(cmd_parts)
    print(f"$ {full_cmd}")
    output = _exec(full_cmd)
    print(_truncate(output) if output else "(no output)")


# =========================================================================
# CLI entry point
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="MobileWorld CLI tool suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # --- Core tools ---
    p_adb = subparsers.add_parser("adb", help="Run ADB command")
    p_adb.add_argument("command")
    p_adb.add_argument("--no-tree", action="store_true")

    p_exec = subparsers.add_parser("exec", help="Run shell command in container")
    p_exec.add_argument("command")
    p_exec.add_argument("--timeout", type=int, default=120)

    p_sql = subparsers.add_parser("sql", help="SQLite query on device")
    p_sql.add_argument("db_path")
    p_sql.add_argument("query")

    p_rf = subparsers.add_parser("read-file", help="Read file from device/container")
    p_rf.add_argument("path")

    p_wf = subparsers.add_parser("write-file", help="Write file to device/container")
    p_wf.add_argument("path")
    p_wf.add_argument("content")
    p_wf.add_argument("--append", action="store_true")

    p_ff = subparsers.add_parser("find-files", help="Search files")
    p_ff.add_argument("directory")
    p_ff.add_argument("pattern")
    p_ff.add_argument("--maxdepth", type=int, default=5)

    p_http = subparsers.add_parser("http", help="HTTP request")
    p_http.add_argument("method")
    p_http.add_argument("url")
    p_http.add_argument("--headers", default="")
    p_http.add_argument("--data", default="")

    p_finish = subparsers.add_parser("finish", help="Signal task completion")
    p_finish.add_argument("--status", default="complete")
    p_finish.add_argument("--description", default="")

    # --- Backend & Docker tools ---
    p_pg = subparsers.add_parser("pg", help="PostgreSQL query via Docker")
    p_pg.add_argument("container_pattern", help="grep pattern for container name")
    p_pg.add_argument("database")
    p_pg.add_argument("query")
    p_pg.add_argument("--user", default="postgres")

    p_ss = subparsers.add_parser("service-status", help="Docker service status")
    p_ss.add_argument("pattern", nargs="?", default=None)
    p_ss.add_argument("--start", metavar="DIR", default=None)
    p_ss.add_argument("--stop", metavar="DIR", default=None)

    # --- Structured data tools ---
    p_jr = subparsers.add_parser("json-read", help="Read and parse JSON")
    p_jr.add_argument("path")
    p_jr.add_argument("expr", nargs="?", default=None)

    p_jw = subparsers.add_parser("json-write", help="Write structured JSON")
    p_jw.add_argument("path")
    p_jw.add_argument("content")
    p_jw.add_argument("--merge", action="store_true")

    # --- Android platform tools ---
    p_ct = subparsers.add_parser("content", help="Content provider operations")
    p_ct.add_argument("operation", choices=["query", "insert", "update", "delete"])
    p_ct.add_argument("uri")
    p_ct.add_argument("--projection", default=None)
    p_ct.add_argument("--where", default=None)
    p_ct.add_argument("--sort", default=None)
    p_ct.add_argument("--bind", action="append", default=None)

    p_in = subparsers.add_parser("intent", help="Fire Android intents")
    p_in.add_argument("mode", choices=["start", "broadcast"])
    p_in.add_argument("target")
    p_in.add_argument("--extra", action="append", default=None)
    p_in.add_argument("--data", default=None)
    p_in.add_argument("--flags", default=None)

    # --- Dispatch ---
    args = parser.parse_args()
    handlers = {
        "adb": cmd_adb,
        "exec": cmd_exec,
        "sql": cmd_sql,
        "read-file": cmd_read_file,
        "write-file": cmd_write_file,
        "find-files": cmd_find_files,
        "http": cmd_http,
        "finish": cmd_finish,
        "pg": cmd_pg,
        "service-status": cmd_service_status,
        "json-read": cmd_json_read,
        "json-write": cmd_json_write,
        "content": cmd_content,
        "intent": cmd_intent,
    }

    handler = handlers.get(args.subcommand)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
