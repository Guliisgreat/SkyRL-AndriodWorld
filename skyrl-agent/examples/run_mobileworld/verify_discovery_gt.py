#!/usr/bin/env python3
"""
Verify discovery ground truth trajectories on live MobileWorld containers.

Executes each trajectory's commands on a real container, resolves variables
($TOKEN, {account_id}, etc.) from actual command outputs, records real
observations, and checks verifier score.

Usage:
    python verify_discovery_gt.py \
        --container mobile_world_env_1 \
        --server-url http://localhost:6805 \
        --output verified_discovery.jsonl

    # Specific tasks
    python verify_discovery_gt.py --tasks "task_000,task_010"
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


# =========================================================================
# Execution helpers
# =========================================================================

def http_post(url, payload, timeout=300):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get_json_body(url, payload, timeout=120):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                headers={"Content-Type": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def exec_on_container(container, device, command, timeout=30):
    """Execute a discovery command on the container. Returns stdout.

    Translates the abstract command format to actual docker exec commands:
    - adb shell ... → docker exec container adb -s device shell ...
    - sql db "query" → docker exec container adb -s device shell 'su root sh -c "echo b64 | base64 -d | sqlite3 db"'
    - http METHOD url ... → docker exec container curl ... OR docker exec container docker exec postgres psql ...
    - read-file path → docker exec container adb -s device shell cat path
    - write-file path content → docker exec container adb -s device push ...
    - find-files dir pattern → docker exec container adb -s device shell find dir -name pattern
    """
    import base64

    if command.startswith("adb shell "):
        shell_cmd = command[len("adb shell "):]
        r = subprocess.run(
            ["docker", "exec", container, "adb", "-s", device, "shell", shell_cmd],
            capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()

    elif command.startswith("sql "):
        # sql /path/to/db "QUERY"
        m = re.match(r'sql\s+(\S+)\s+"(.+)"', command)
        if not m:
            m = re.match(r"sql\s+(\S+)\s+'(.+)'", command)
        if not m:
            return f"ERROR: cannot parse sql command: {command[:80]}"
        db_path, query = m.group(1), m.group(2)
        enc = base64.b64encode(query.encode()).decode()
        r = subprocess.run(
            ["docker", "exec", container, "adb", "-s", device, "shell",
             f'su root sh -c "echo {enc} | base64 -d | sqlite3 {db_path}"'],
            capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()

    elif command.startswith("read-file "):
        path = command[len("read-file "):]
        r = subprocess.run(
            ["docker", "exec", container, "adb", "-s", device, "shell", f"cat {path}"],
            capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()[:4000]  # truncate large files

    elif command.startswith("write-file "):
        # write-file /path 'content'
        m = re.match(r"write-file\s+(\S+)\s+'(.*)'", command, re.DOTALL)
        if not m:
            m = re.match(r'write-file\s+(\S+)\s+"(.*)"', command, re.DOTALL)
        if not m:
            return f"ERROR: cannot parse write-file: {command[:80]}"
        path, content = m.group(1), m.group(2)
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tmp', delete=False) as f:
            f.write(content)
            local = f.name
        subprocess.run(f"docker cp {local} {container}:/tmp/_wf.tmp", shell=True, timeout=10)
        os.unlink(local)
        subprocess.run(["docker", "exec", container, "adb", "-s", device,
                        "push", "/tmp/_wf.tmp", path], capture_output=True, timeout=30)
        return ""

    elif command.startswith("find-files "):
        parts = command.split(" ", 2)
        if len(parts) >= 3:
            directory, pattern = parts[1], parts[2].strip('"').strip("'")
            r = subprocess.run(
                ["docker", "exec", container, "adb", "-s", device, "shell",
                 f"find {directory} -name '{pattern}' 2>/dev/null"],
                capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip()
        return "ERROR: bad find-files command"

    elif command.startswith("http "):
        # http METHOD url [--headers "..." ...] [--data '...']
        # Parse method, url, headers, data
        parts = command.split(" ", 3)
        method = parts[1] if len(parts) > 1 else "GET"
        rest = " ".join(parts[2:]) if len(parts) > 2 else ""

        # Extract URL
        url_m = re.match(r'(\S+)', rest)
        url = url_m.group(1) if url_m else ""

        # Handle psql:// as PostgreSQL query
        if url.startswith("psql://mastodon"):
            data_m = re.search(r"--data\s+'(.+?)(?:'|$)", rest)
            if not data_m:
                data_m = re.search(r'--data\s+"(.+?)(?:"|$)', rest)
            query = data_m.group(1) if data_m else ""
            r = subprocess.run(
                ["docker", "exec", container, "docker", "exec", "mastodon-docker-db-1",
                 "psql", "-U", "postgres", "-d", "mastodon", "-t", "-c", query],
                capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip()

        elif url.startswith("psql://mattermost"):
            data_m = re.search(r"--data\s+'(.+?)(?:'|$)", rest)
            if not data_m:
                data_m = re.search(r'--data\s+"(.+?)(?:"|$)', rest)
            query = data_m.group(1) if data_m else ""
            r = subprocess.run(
                ["docker", "exec", container, "docker", "exec", "mattermost-docker-postgres-1",
                 "psql", "-U", "mmuser", "-d", "mattermost", "-t", "-c", query],
                capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip()

        elif url.startswith("file://"):
            # Mall callback write
            data_m = re.search(r"--data\s+'(.+?)(?:'|$)", rest)
            if data_m:
                import tempfile
                content = data_m.group(1)
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                    f.write(content)
                    local = f.name
                ts = time.strftime("%Y%m%d_%H%M%S")
                remote = f"/app/service/artifacts/{device}/task_callbacks/callback_{ts}.json"
                subprocess.run(f"docker exec {container} mkdir -p /app/service/artifacts/{device}/task_callbacks",
                               shell=True, timeout=5)
                subprocess.run(f"docker cp {local} {container}:{remote}", shell=True, timeout=5)
                os.unlink(local)
            return ""

        elif "localhost" in url and "/step" in url:
            # MobileWorld server endpoint — execute via HTTP from host
            data_m = re.search(r"--data\s+'(.+?)(?:'|$)", rest)
            payload = json.loads(data_m.group(1)) if data_m else {}
            try:
                resp = http_post(url, payload, timeout=30)
                return json.dumps(resp)[:500]
            except Exception as e:
                return f"ERROR: {e}"

        elif "localhost" in url and "/config" in url:
            # Config endpoint
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    return resp.read().decode()[:2000]
            except Exception as e:
                return f"ERROR: {e}"

        else:
            # Mastodon/external API — route via docker exec curl
            curl_cmd = ["docker", "exec", container, "curl", "-sk", "-X", method]

            # Parse headers
            for hm in re.finditer(r'--headers\s+"([^"]+)"', rest):
                curl_cmd.extend(["-H", hm.group(1)])

            # Parse data
            data_m = re.search(r"--data\s+'(.+?)(?:'|$)", rest)
            if data_m:
                curl_cmd.extend(["-d", data_m.group(1)])
                if "Content-Type" not in rest:
                    curl_cmd.extend(["-H", "Content-Type: application/json"])

            # Handle multipart
            if "multipart:" in rest:
                file_m = re.search(r"file=@(\S+)", rest)
                if file_m:
                    curl_cmd.extend(["-F", f"file=@{file_m.group(1)}"])

            curl_cmd.append(url)

            r = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip()[:2000]

    elif command.startswith("#"):
        # Comment/reasoning — no execution
        return ""

    else:
        return f"UNKNOWN COMMAND TYPE: {command[:50]}"


def resolve_variables(command, variables):
    """Replace $TOKEN, {account_id}, etc. with resolved values."""
    resolved = command
    for var, val in variables.items():
        resolved = resolved.replace(f"${var}", val)
        resolved = resolved.replace(f"${{{var}}}", val)
    return resolved


def extract_token(output):
    """Extract access_token from SQL query output."""
    try:
        d = json.loads(output)
        return d.get("access_token", "")
    except (json.JSONDecodeError, TypeError):
        # Try regex
        m = re.search(r'"access_token"\s*:\s*"([^"]+)"', output)
        return m.group(1) if m else output.strip()


# =========================================================================
# Main verification loop
# =========================================================================

def verify_task(traj_path, container, device, server_url):
    """Execute a discovery trajectory and verify with eval."""
    with open(traj_path) as f:
        traj = json.load(f)

    task_name = traj["extra"]["task_name"]
    task_id = traj["final_metrics"]["extra"]["task_id"]

    # Variables resolved from observations
    variables = {}

    # Init task
    try:
        http_post(f"{server_url}/task/init",
                  {"task_name": task_name, "req_device": device})
    except Exception as e:
        return {"task_name": task_name, "task_id": task_id, "status": "init_failed", "error": str(e)}

    # Wait for backends
    wait = 15 if "Mastodon" in task_name or "Mattermost" in task_name else 8
    time.sleep(wait)

    # Execute each agent step
    executed_steps = []
    for step in traj["steps"]:
        if step["source"] != "agent":
            continue
        if "tool_calls" not in step:
            # Reasoning step — record but don't execute
            executed_steps.append({
                "step_id": step["step_id"],
                "thought": step.get("message", ""),
                "command": None,
                "observation": None,
                "type": "reasoning",
            })
            continue

        command = step["tool_calls"][0]["arguments"]["command"]
        thought = step.get("message", "")

        # Resolve variables
        command = resolve_variables(command, variables)

        # Skip if still has unresolved variables
        if "{" in command and "}" in command:
            executed_steps.append({
                "step_id": step["step_id"],
                "thought": thought,
                "command": command,
                "observation": "SKIPPED: unresolved variables",
                "type": "skipped",
            })
            continue

        # Execute
        try:
            observation = exec_on_container(container, device, command, timeout=30)
        except Exception as e:
            observation = f"ERROR: {e}"

        executed_steps.append({
            "step_id": step["step_id"],
            "thought": thought,
            "command": command,
            "observation": observation[:500],
            "type": "executed",
        })

        # Extract variables from observations
        if "SELECT token" in command and observation:
            token = extract_token(observation)
            if token:
                variables["TOKEN"] = token

        # Extract IDs from search results
        if observation:
            # Account IDs
            for m in re.finditer(r'"id"\s*:\s*"(\d+)"', observation):
                if "account_id" not in variables:
                    variables["account_id"] = m.group(1)
            # List IDs
            for m in re.finditer(r'"id"\s*:\s*"([a-zA-Z0-9_-]+)"', observation):
                if "list_id" not in variables:
                    variables["list_id"] = m.group(1)
                if "filter_id" not in variables:
                    variables["filter_id"] = m.group(1)

    # Eval
    time.sleep(2)
    try:
        eval_resp = http_get_json_body(f"{server_url}/task/eval",
                                        {"task_name": task_name, "req_device": device})
        score = eval_resp.get("score", 0.0)
        reason = eval_resp.get("reason", "")
    except Exception as e:
        score = 0.0
        reason = f"eval_error: {e}"

    # Teardown
    try:
        http_post(f"{server_url}/task/tear_down",
                  {"task_name": task_name, "req_device": device})
    except Exception:
        pass

    status = "PASS" if score > 0 else "FAIL"
    return {
        "task_name": task_name,
        "task_id": task_id,
        "status": status,
        "score": score,
        "reason": reason,
        "steps_executed": len([s for s in executed_steps if s["type"] == "executed"]),
        "steps_skipped": len([s for s in executed_steps if s["type"] == "skipped"]),
        "steps_reasoning": len([s for s in executed_steps if s["type"] == "reasoning"]),
        "executed_steps": executed_steps,
    }


def main():
    parser = argparse.ArgumentParser(description="Verify discovery GT on live container")
    parser.add_argument("--container", required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument("--input-dir", default="../../results/GroundTruth_mobileworld_discovery/atif_trajectories")
    parser.add_argument("--tasks", type=str, default=None, help="Comma-separated task files (e.g. task_000,task_010)")
    parser.add_argument("--output", default="verified_discovery.jsonl")
    parser.add_argument("--max-tasks", type=int, default=None)
    args = parser.parse_args()

    input_dir = os.path.abspath(args.input_dir)
    if args.tasks:
        task_files = [f"{t}.json" for t in args.tasks.split(",")]
    else:
        task_files = sorted(f for f in os.listdir(input_dir) if f.endswith(".json"))

    if args.max_tasks:
        task_files = task_files[:args.max_tasks]

    print(f"Verifying {len(task_files)} discovery trajectories")
    print(f"Container: {args.container}, Server: {args.server_url}")

    results = []
    out = open(args.output, "w")

    for i, fname in enumerate(task_files):
        traj_path = os.path.join(input_dir, fname)
        print(f"\n[{i+1}/{len(task_files)}] {fname}")

        result = verify_task(traj_path, args.container, args.device, args.server_url)
        results.append(result)
        out.write(json.dumps(result) + "\n")
        out.flush()

        status = result["status"]
        print(f"  {status}: score={result['score']}, "
              f"executed={result['steps_executed']}, "
              f"skipped={result['steps_skipped']}, "
              f"reason={result.get('reason', '')[:60]}")

    out.close()

    # Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "init_failed")
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{len(results)} PASS, {failed} FAIL, {errors} ERROR")
    print(f"Output: {args.output}")

    if failed:
        print(f"\nFailed tasks:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"  {r['task_name']}: {r.get('reason', '')[:80]}")


if __name__ == "__main__":
    main()
