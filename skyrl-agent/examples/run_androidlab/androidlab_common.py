"""
Shared infrastructure for running agents on the Android-Lab benchmark.

Provides:
- Android-Lab-specific container reset (snapshot + date + GPS + app launch)
- Hybrid evaluation (LLM judge for query_detect, XML dump for operation)
- Task loading from Android-Lab JSONL format
- Post-agent app launch + XML state capture for operation tasks
"""

import json
import os
import time
import urllib.request
import urllib.error

# ─── Paths ───────────────────────────────────────────────────────────────────

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ANDROIDLAB_TASKS_FILE = os.path.join(_THIS_DIR, "androidlab_tasks.jsonl")

# ─── Constants ───────────────────────────────────────────────────────────────

ANDROIDLAB_DATE = "2024-05-10 12:00:00"


# ─── HTTP helpers ────────────────────────────────────────────────────────────

def http_post(url, payload, timeout=300):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ─── Container helpers ───────────────────────────────────────────────────────

def check_health(base_url):
    """Check if container or broker is healthy."""
    try:
        data = http_get(f"{base_url}/health", timeout=5)
        return data.get("ready", False) or data.get("status") == "ok"
    except Exception:
        return False


def androidlab_reset(container_url, package=""):
    """Reset container for an Android-Lab task.

    1. Restore clean AVD snapshot via /reset
    2. Set date to 2024-05-10 12:00:00
    3. Launch target app (if package provided)
    """
    # Step 1: Restore snapshot (emulator restart — takes ~60-90s)
    http_post(f"{container_url}/reset", {
        "seed": None,
        "options": {},
    }, timeout=300)

    # Step 2: Set fixed date
    _adb_exec(container_url, f"adb shell date '{ANDROIDLAB_DATE}'")

    # Step 3: Set GPS
    _adb_exec(
        container_url,
        "adb shell settings put secure location_providers_allowed gps"
    )

    # Step 4: Launch target app
    if package:
        _adb_exec(
            container_url,
            f"adb shell monkey -p {package} "
            f"-c android.intent.category.LAUNCHER 1"
        )
        time.sleep(5)  # wait for app to fully launch


def _adb_exec(container_url, command):
    """Execute an ADB command via the container's /step endpoint."""
    try:
        return http_post(f"{container_url}/step", {
            "action": {"action_type": "adb", "command": command},
            "thought": "androidlab setup",
        }, timeout=30)
    except Exception as e:
        print(f"  ADB exec warning: {e}")
        return {}


# ─── Evaluation ──────────────────────────────────────────────────────────────

def dump_xml_state(container_url):
    """Dump current UI XML state from the emulator.

    Returns the raw XML string from uiautomator dump.
    """
    resp = _adb_exec(
        container_url,
        "adb shell uiautomator dump /sdcard/window_dump.xml "
        "&& adb shell cat /sdcard/window_dump.xml"
    )
    # The command output contains the XML
    output = resp.get("observation", "")
    if not output:
        output = resp.get("command_output", "")
    return output


def post_agent_xml_dump(container_url, package):
    """After agent finishes, launch app and dump XML for evaluation.

    For operation tasks: the evaluator checks XML state, so we need
    to open the app and capture what the UI looks like.
    """
    # Launch the target app
    _adb_exec(
        container_url,
        f"adb shell monkey -p {package} "
        f"-c android.intent.category.LAUNCHER 1"
    )
    time.sleep(8)  # wait for app to fully render

    # Dump XML
    return dump_xml_state(container_url)


def evaluate_query_detect(question, agent_answer, standard_answer,
                          judge_model="gpt-4o"):
    """LLM judge for query_detect tasks.

    Asks the LLM to compare the agent's answer against the standard answer.
    Returns True/False.
    """
    from openai import OpenAI

    prompt = (
        f"You need to judge the model answer is True or False based on "
        f"Standard Answer we provided. You should whether answer [True] or "
        f"[False].\n\n"
        f"Question: {question}\n\n"
        f"Model Answer: {agent_answer}\n\n"
        f"Standard Answer: {standard_answer}"
    )

    client = OpenAI()
    for attempt in range(5):
        try:
            r = client.chat.completions.create(
                model=judge_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.001,
            )
            text = r.choices[0].message.content
            if "True" in text:
                return True
            elif "False" in text:
                return False
        except Exception as e:
            print(f"  Judge attempt {attempt+1} failed: {e}")
            time.sleep(2)

    return False  # default to False if judge can't decide


# ─── Task loading ────────────────────────────────────────────────────────────

def load_androidlab_tasks(data_path=None, task_ids=None, apps=None,
                          metric_type=None):
    """Load Android-Lab tasks from JSONL.

    Args:
        data_path: Path to JSONL file. Defaults to bundled androidlab_tasks.jsonl.
        task_ids: Optional comma-separated task IDs to filter.
        apps: Optional list of app names to filter.
        metric_type: Optional "operation" or "query_detect" to filter.
    """
    if data_path is None:
        data_path = ANDROIDLAB_TASKS_FILE

    if not os.path.exists(data_path):
        # Generate from embedded data
        from convert_tasks import generate_jsonl
        generate_jsonl(data_path)

    with open(data_path) as f:
        tasks = [json.loads(line) for line in f if line.strip()]

    if task_ids:
        ids = set(task_ids.split(","))
        tasks = [t for t in tasks if t["task_id"] in ids]

    if apps:
        app_set = set(apps)
        tasks = [t for t in tasks if t["app"] in app_set]

    if metric_type:
        tasks = [t for t in tasks if t["metric_type"] == metric_type]

    return tasks


def format_androidlab_instruction(task_def):
    """Format task instruction the same way Android-Lab does.

    Android-Lab prepends "You should use {app} to complete the following task:"
    """
    app = task_def["app"]
    task = task_def["task"]
    return f"You should use {app} to complete the following task: {task}"


# ─── Broker helpers (reuse from claude_cli_common) ───────────────────────────

def broker_acquire(broker_url, timeout=300, retries=3):
    """Acquire a container from the broker."""
    for attempt in range(retries):
        try:
            return http_post(
                f"{broker_url}/acquire",
                {"pid": os.getpid(), "timeout": timeout},
                timeout=timeout + 30,
            )
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError(
                    f"Failed to acquire container after {retries} attempts: {e}"
                )


def broker_release(broker_url, env_id, healthy=True, retries=3):
    """Return a container to the broker."""
    for attempt in range(retries):
        try:
            return http_post(
                f"{broker_url}/return",
                {"env_id": env_id, "healthy": healthy},
                timeout=120,
            )
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                print(f"  WARNING: Failed to return env_id={env_id}: {e}")


def broker_androidlab_reset(broker_url, env_id, package=""):
    """Reset a leased container via broker's /androidlab_reset endpoint."""
    return http_post(
        f"{broker_url}/androidlab_reset",
        {"env_id": env_id, "package": package},
        timeout=180,
    )


# ─── Summary / finalization ─────────────────────────────────────────────────

def print_summary(results):
    """Print Android-Lab benchmark results summary."""
    total = len(results)
    successes = sum(1 for r in results if r.get("reward", 0) > 0)

    print(f"\n{'='*70}")
    print(f"ANDROID-LAB RESULTS: {successes}/{total} "
          f"({100*successes/max(total,1):.1f}%)")
    print(f"{'='*70}")

    # Per-app breakdown
    app_results = {}
    for r in results:
        app = r.get("app", "unknown")
        if app not in app_results:
            app_results[app] = {"total": 0, "success": 0}
        app_results[app]["total"] += 1
        if r.get("reward", 0) > 0:
            app_results[app]["success"] += 1

    print(f"\nPer-app breakdown:")
    print(f"  {'App':20s} {'SR':>8s}  {'Success':>7s} / {'Total':>5s}")
    print(f"  {'-'*45}")
    for app, counts in sorted(app_results.items()):
        sr = 100 * counts["success"] / max(counts["total"], 1)
        print(f"  {app:20s} {sr:7.1f}%  {counts['success']:7d} / {counts['total']:5d}")

    # Per-metric-type breakdown
    type_results = {}
    for r in results:
        mt = r.get("metric_type", "unknown")
        if mt not in type_results:
            type_results[mt] = {"total": 0, "success": 0}
        type_results[mt]["total"] += 1
        if r.get("reward", 0) > 0:
            type_results[mt]["success"] += 1

    print(f"\nPer-metric-type breakdown:")
    for mt, counts in sorted(type_results.items()):
        sr = 100 * counts["success"] / max(counts["total"], 1)
        print(f"  {mt:20s} {sr:7.1f}%  {counts['success']:3d}/{counts['total']:3d}")

    # Cost summary
    total_cost = sum(r.get("cost_usd", 0) for r in results)
    total_input = sum(r.get("input_tokens", 0) for r in results)
    total_output = sum(r.get("output_tokens", 0) for r in results)
    print(f"\nCost: ${total_cost:.2f} "
          f"(in={total_input:,}, out={total_output:,} tokens)")


def save_results(results, output_path, extra_meta=None):
    """Save results JSONL + summary JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Write JSONL
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    # Write summary
    total = len(results)
    successes = sum(1 for r in results if r.get("reward", 0) > 0)
    summary = {
        "benchmark": "Android-Lab",
        "total": total,
        "success": successes,
        "success_rate": successes / max(total, 1),
        "total_cost_usd": round(sum(r.get("cost_usd", 0) for r in results), 4),
    }
    if extra_meta:
        summary.update(extra_meta)

    summary_path = os.path.join(os.path.dirname(output_path), "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nResults: {output_path}")
    print(f"Summary: {summary_path}")
