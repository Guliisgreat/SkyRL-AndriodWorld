#!/usr/bin/env python3
"""
Reproduce Android-Lab paper results: GPT-4o XML-only GUI agent.

Replicates the TextOnlyMobileTask_AutoTest flow from Android-Lab:
1. Dump XML → compress → send to GPT-4o
2. GPT-4o returns code (do(action=...) or finish(message=...))
3. Execute action via ADB (tap, swipe, type, etc.)
4. Repeat for max_rounds steps
5. Save traces for post-hoc evaluation

Usage:
    # Sequential
    python run_gui_agent_androidlab.py \\
        --container-url http://localhost:6789

    # Parallel via broker
    python run_gui_agent_androidlab.py \\
        --broker-url http://localhost:9200 --pool-size 8
"""

import argparse
import json
import os
import re
import sys
import time
import traceback

from openai import OpenAI

from androidlab_common import (
    androidlab_reset,
    broker_acquire,
    broker_release,
    check_health,
    format_androidlab_instruction,
    http_post,
    load_androidlab_tasks,
    print_summary,
    save_results,
)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES_DIR = os.path.dirname(_THIS_DIR)

# ─── GPT-4o System Prompt (from Android-Lab: SYSTEM_PROMPT_ANDROID_TEXT_GPT) ─

SYSTEM_PROMPT = '''# Setup
You are a professional android operation agent assistant that can fulfill user's high-level instructions. Given the XML information of the android screenshot at each step, you plan operations in python-style pseudo code using provided functions, or customize functions (if necessary) and then provide their implementations.

# More details about the code
Your code should be readable, simple, and only **ONE-LINE-OF-CODE** at a time. You are not allowed to use `while` statement and `if-else` control. Predefined functions are as follow:

```

def do(action, element=None, **kwargs):
    """
    Perform a single operation on an Android mobile device.

    Args:
        action (str): Specifies the action to be performed. Valid options are:
                      "Tap", "Type", "Swipe", "Long Press", "Home", "Back", "Enter", "Wait".
        element (list, optional): Defines the screen area or starting point for the action.
                                  - For "Tap" and "Long Press", provide coordinates [x1, y1, x2, y2]
                                    to define a rectangle from top-left (x1, y1) to bottom-right (x2, y2).
                                  - For "Swipe", provide coordinates either as [x1, y1, x2, y2] for a defined path
                                    or [x, y] for a starting point. If omitted, defaults to the screen center.

    Keyword Args:
        text (str, optional): The text to type. Required for the "Type" action.
        direction (str, optional): The direction to swipe. Valid directions are "up", "down", "left", "right".
                                   Required if action is "Swipe".
        dist (str, optional): The distance of the swipe, with options "long", "medium", "short".
                              Defaults to "medium". Required if action is "Swipe" and direction is specified.

    Returns:
        None. The device state or the foreground application state will be updated after executing the action.
    """


def finish(message=None):
    """
    Terminates the program. Optionally prints a provided message to the standard output before exiting.

    Args:
        message (str, optional): A message to print before exiting. Defaults to None.

    Returns:
        None
    """

```

REMEMBER:
- Only **ONE-LINE-OF-CODE** at a time.
- Don't generate an operation element that you do not see in the screenshot.
- You are acting in a real world, try your best not to reject user's demand. Solve all the problem you encounter.
- On a dropdown element (Calendar, Nationality, Language, etc.), first try directly typing in the option you want.
- To accomplish the task, try switching to as many different pages as you can, and don't stay on the same page too often, based on historical conversation information.
- To complete the task, explore the app fully, i.e., tap more on different elements of the app
- Please do not translate proper nouns into English.
'''


# ─── XML compression (simplified UIXMLTree) ─────────────────────────────────

def compress_xml(raw_xml):
    """Compress raw uiautomator XML into Android-Lab's text format.

    Simplified version of UIXMLTree.process() — extracts key attributes
    and formats as indented text tree.
    """
    try:
        from lxml import etree
        root = etree.fromstring(raw_xml.encode('utf-8'))
    except Exception:
        return raw_xml[:8000]

    lines = []
    _compress_node(root, lines, indent=0)
    result = "\n".join(lines)
    # Truncate to avoid context overflow
    if len(result) > 16000:
        result = result[:16000] + "\n... (truncated)"
    return result


def _compress_node(node, lines, indent):
    """Recursively compress XML nodes."""
    if node.tag == "hierarchy":
        for child in node:
            _compress_node(child, lines, indent)
        return

    attrs = node.attrib
    bounds = attrs.get("bounds", "")
    text = attrs.get("text", "")
    content_desc = attrs.get("content-desc", "")
    cls = attrs.get("class", "").split(".")[-1] if attrs.get("class") else ""
    resource_id = attrs.get("resource-id", "")
    if resource_id and ":id/" in resource_id:
        resource_id = resource_id.split(":id/")[-1]

    # Build action list
    actions = []
    for k, v in {"clickable": "click", "scrollable": "scroll",
                  "long-clickable": "long-click", "checkable": "check"}.items():
        if attrs.get(k) == "true":
            actions.append(v)

    # Build description
    desc_parts = []
    if cls:
        desc_parts.append(cls)
    if actions:
        desc_parts.append(";".join(actions))
    if text:
        desc_parts.append(text)
    if content_desc and content_desc != text:
        desc_parts.append(content_desc)

    # Status
    status_parts = []
    if attrs.get("checked") == "true":
        status_parts.append("checked")
    if attrs.get("selected") == "true":
        status_parts.append("selected")
    if attrs.get("checkable") == "true" and attrs.get("checked") == "false":
        status_parts.append("unchecked")

    # Skip non-visible / non-interactive elements with no text
    has_content = text or content_desc or actions
    if not has_content and not list(node):
        return

    desc = " ;".join(desc_parts)
    if status_parts:
        desc += " (" + ", ".join(status_parts) + ")"

    prefix = "    " * indent
    if bounds:
        lines.append(f"{prefix}[{cls}] {desc}: ")
        lines.append(f"{prefix}    bounds: {bounds}")
    else:
        lines.append(f"{prefix}[{cls}] {desc}")

    for child in node:
        _compress_node(child, lines, indent + 1)


# ─── Action execution via ADB ───────────────────────────────────────────────

def execute_action(container_url, action_dict):
    """Execute a do() action via ADB commands."""
    action = action_dict.get("action", "")
    element = action_dict.get("element")
    kwargs = {k: v for k, v in action_dict.items() if k not in ("action", "element")}

    if action == "Tap":
        if element and len(element) == 4:
            cx = int((element[0] + element[2]) / 2)
            cy = int((element[1] + element[3]) / 2)
        elif element and len(element) == 2:
            cx, cy = int(element[0]), int(element[1])
        else:
            return
        _adb(container_url, f"adb shell input tap {cx} {cy}")

    elif action == "Long Press":
        if element and len(element) >= 2:
            if len(element) == 4:
                cx = int((element[0] + element[2]) / 2)
                cy = int((element[1] + element[3]) / 2)
            else:
                cx, cy = int(element[0]), int(element[1])
            _adb(container_url, f"adb shell input swipe {cx} {cy} {cx} {cy} 1500")

    elif action == "Type":
        text = kwargs.get("text", "")
        # Escape special characters for adb shell input
        escaped = text.replace("'", "'\\''").replace(" ", "%s").replace("&", "\\&")
        _adb(container_url, f"adb shell input text '{escaped}'")
        time.sleep(0.5)
        _adb(container_url, "adb shell input keyevent 66")  # Enter

    elif action == "Swipe":
        direction = kwargs.get("direction", "up")
        dist = kwargs.get("dist", "medium")
        if element and len(element) == 4:
            cx = int((element[0] + element[2]) / 2)
            cy = int((element[1] + element[3]) / 2)
        elif element and len(element) == 2:
            cx, cy = int(element[0]), int(element[1])
        else:
            cx, cy = 540, 1200  # screen center default

        dist_px = {"short": 200, "medium": 500, "long": 900}.get(dist, 500)
        dx, dy = 0, 0
        if direction == "up":
            dy = -dist_px
        elif direction == "down":
            dy = dist_px
        elif direction == "left":
            dx = -dist_px
        elif direction == "right":
            dx = dist_px
        _adb(container_url, f"adb shell input swipe {cx} {cy} {cx+dx} {cy+dy} 300")

    elif action == "Enter":
        _adb(container_url, "adb shell input keyevent 66")

    elif action == "Home":
        _adb(container_url, "adb shell input keyevent 3")

    elif action == "Back":
        _adb(container_url, "adb shell input keyevent 4")

    elif action == "Wait":
        time.sleep(5)

    time.sleep(1)  # settling time after action


def _adb(container_url, command):
    """Execute ADB command via container."""
    try:
        return http_post(f"{container_url}/step_adb", {
            "command": command,
            "thought": "",
            "count_step": False,
        }, timeout=30)
    except Exception as e:
        print(f"    ADB error: {e}")
        return {}


def dump_and_compress_xml(container_url):
    """Dump XML from emulator and compress it."""
    # Two separate calls to avoid shell quoting issues with &&
    _adb(container_url, "adb shell uiautomator dump /sdcard/window_dump.xml")
    time.sleep(0.5)
    resp = _adb(container_url, "adb shell cat /sdcard/window_dump.xml")
    raw = resp.get("command_output", "") if isinstance(resp, dict) else ""
    # Extract XML from output (may have "UI hierarchy dumped" prefix)
    xml_start = raw.find("<?xml")
    if xml_start >= 0:
        raw_xml = raw[xml_start:]
        return compress_xml(raw_xml), raw_xml
    return raw[:8000], raw


# ─── Code parsing ────────────────────────────────────────────────────────────

def parse_code(response_text):
    """Extract code from GPT-4o response (```...``` block)."""
    match = re.search(r'```.*?([\s\S]+?)```', response_text)
    if match:
        code = match.group(1).strip()
        # Take last line if multi-line
        lines = [l.strip() for l in code.split("\n") if l.strip()]
        if lines:
            return lines[-1]
    return response_text.strip().split("\n")[-1]


def parse_action(code_line):
    """Parse a do() or finish() call into a dict."""
    code_line = re.sub(r'\b0+(\d)', r'\1', code_line)  # remove leading zeros

    result = {"type": "unknown", "code": code_line}

    if "finish(" in code_line or "finished(" in code_line:
        result["type"] = "finish"
        # Extract message
        match = re.search(r'(?:finish|finished)\((.*?)\)', code_line, re.DOTALL)
        if match:
            args = match.group(1).strip()
            msg_match = re.search(r'message\s*=\s*["\'](.+?)["\']', args)
            if msg_match:
                result["message"] = msg_match.group(1)
            elif args.startswith('"') or args.startswith("'"):
                result["message"] = args.strip("\"'")
            else:
                result["message"] = args
        return result

    if "do(" in code_line:
        result["type"] = "do"
        try:
            # Use a safe exec to parse the do() call
            captured = {}
            def fake_do(action=None, element=None, **kwargs):
                captured["action"] = action
                captured["element"] = element
                captured.update(kwargs)
            exec(code_line, {"do": fake_do, "finish": lambda **kw: None})
            result.update(captured)
        except Exception as e:
            result["error"] = str(e)
        return result

    # Low-level API: tap(), text(), etc.
    for func in ["tap", "long_press", "swipe", "back", "home", "text"]:
        if code_line.startswith(f"{func}("):
            result["type"] = "lowlevel"
            result["func"] = func
            try:
                captured = {}
                def fake_tap(x1=0, y1=0, x2=0, y2=0):
                    captured["element"] = [x1, y1, x2, y2]
                    captured["action"] = "Tap"
                def fake_lp(x1=0, y1=0, x2=0, y2=0):
                    captured["element"] = [x1, y1, x2, y2]
                    captured["action"] = "Long Press"
                def fake_swipe(x1=0, y1=0, x2=0, y2=0, direction="up", dist="medium"):
                    captured["element"] = [x1, y1, x2, y2]
                    captured["action"] = "Swipe"
                    captured["direction"] = direction
                    captured["dist"] = dist
                def fake_text(t=""):
                    captured["action"] = "Type"
                    captured["text"] = t
                def fake_back():
                    captured["action"] = "Back"
                def fake_home():
                    captured["action"] = "Home"
                exec(code_line, {
                    "tap": fake_tap, "long_press": fake_lp,
                    "swipe": fake_swipe, "text": fake_text,
                    "back": fake_back, "home": fake_home,
                })
                result.update(captured)
            except Exception as e:
                result["error"] = str(e)
            return result

    return result


# ─── GPT-4o Agent ────────────────────────────────────────────────────────────

def run_gui_agent(task_def, container_url, model="gpt-4o", max_rounds=25,
                  request_interval=3):
    """Run the Android-Lab GUI agent (GPT-4o XML-only) on one task."""
    task_id = task_def["task_id"]
    app = task_def["app"]
    package = task_def["package"]
    metric_type = task_def["metric_type"]
    instruction = format_androidlab_instruction(task_def)

    print(f"\n{'='*70}")
    print(f"TASK {task_id} ({app}, {metric_type}): {task_def['task'][:80]}")
    print(f"{'='*70}")
    sys.stdout.flush()

    # Reset container
    try:
        androidlab_reset(container_url, package=package)
        print(f"  Reset OK")
    except Exception as e:
        print(f"  Reset FAILED: {e}")
        return _error_result(task_def, f"reset: {e}")

    # Initialize OpenAI client
    client = OpenAI()

    # Build conversation
    system_msg = SYSTEM_PROMPT + f"\n\nTask Instruction: {instruction}"
    messages = [{"role": "system", "content": system_msg}]

    start_time = time.time()
    finish_message = ""
    is_finished = False
    step_count = 0
    total_input_tokens = 0
    total_output_tokens = 0
    traces = []  # Save for post-hoc evaluation

    # Per-step XML saves for post-hoc XML verification (matching original eval.py)
    _xml_save_dir = ""
    try:
        _out_path = os.environ.get("ANDROIDLAB_OUTPUT_PATH", "")
        if _out_path:
            _xml_save_dir = os.path.join(os.path.dirname(_out_path), "xml_dumps", task_id)
            os.makedirs(_xml_save_dir, exist_ok=True)
    except OSError:
        pass

    # Collect ADB query results at each step (for query_detect tasks)
    _adb_query_map = {
        "setting_0": "adb shell settings get global airplane_mode_on",
        "setting_3": "adb shell settings get global bluetooth_on",
        "setting_9": "adb shell settings list system | grep volume_ring_speaker",
        "setting_10": "adb shell settings list system | grep volume_alarm_speaker",
        "setting_14": "adb shell 'getprop persist.sys.timezone'",
        "setting_17": "adb shell getprop ro.build.version.release",
        "setting_20": "adb shell pm list packages | grep 'com.booking'",
        "setting_22": "adb shell settings get global airplane_mode_on",
    }

    for round_num in range(max_rounds):
        # Dump and compress XML
        compressed_xml, raw_xml = dump_and_compress_xml(container_url)

        # Save raw XML to file for post-hoc XML verification
        if _xml_save_dir and raw_xml and "<?xml" in raw_xml:
            with open(os.path.join(_xml_save_dir, f"{round_num}.xml"), "w") as _xf:
                _xf.write(raw_xml)

        # Collect ADB query at this step (for tasks that check command output)
        _step_command = {}
        if task_id in _adb_query_map:
            _qcmd = _adb_query_map[task_id]
            _qr = _adb(container_url, _qcmd)
            _qval = (_qr.get("command_output", "") if isinstance(_qr, dict) else "").strip()
            _step_command[_qcmd] = _qval

        # Build user message
        if round_num == 0:
            user_msg = compressed_xml
        else:
            user_msg = "** XML **\n" + compressed_xml

        messages.append({"role": "user", "content": user_msg})

        # Call GPT-4o
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=512,
                temperature=0.001,
            )
            rsp_text = response.choices[0].message.content or ""
            total_input_tokens += response.usage.prompt_tokens
            total_output_tokens += response.usage.completion_tokens
        except Exception as e:
            print(f"  Round {round_num}: GPT-4o error: {e}")
            time.sleep(5)
            continue

        messages.append({"role": "assistant", "content": rsp_text})

        # Parse code
        code_line = parse_code(rsp_text)
        action = parse_action(code_line)

        # Build parsed_action in EXACT original Android-Lab trace format.
        # Original finish: {"operation":"finish", "action":"finish", "kwargs":{"message":"..."}}
        # Original do:     {"operation":"do", "action":"Tap", "kwargs":{"element":[...]}}
        _orig_parsed = {}
        if action.get("type") == "finish":
            _orig_parsed = {
                "operation": "finish",
                "action": "finish",
                "kwargs": {"message": action.get("message", "")},
            }
        elif action.get("type") in ("do", "lowlevel"):
            _kw = {}
            if action.get("element"):
                _kw["element"] = action["element"]
            if action.get("text"):
                _kw["text"] = action["text"]
            if action.get("direction"):
                _kw["direction"] = action["direction"]
                _kw["dist"] = action.get("dist", "medium")
            _orig_parsed = {
                "operation": "do",
                "action": action.get("action", ""),
                "kwargs": _kw,
            }
        else:
            _orig_parsed = {"operation": "unknown", "action": action.get("type", "")}

        # Save trace matching EXACT original trace.jsonl format
        traces.append({
            "round": round_num,
            "xml_compressed": compressed_xml[:2000],
            "response": rsp_text[:1000],
            "code": code_line,
            "action": action,
            # Fields matching original trace format for XML verifier
            "parsed_action": _orig_parsed,
            "command": _step_command if _step_command else None,
            "target": instruction,  # Fix #2: needed by check_answer()
            "xml_file": os.path.join(_xml_save_dir, f"{round_num}.xml") if _xml_save_dir else None,
        })

        print(f"  Round {round_num}: {code_line[:80]}")

        if action["type"] == "finish":
            finish_message = action.get("message", "")
            is_finished = True
            step_count = round_num + 1
            print(f"  FINISHED: {finish_message[:80]}")
            break

        if action["type"] in ("do", "lowlevel") and "action" in action:
            execute_action(container_url, action)
            step_count = round_num + 1
        else:
            print(f"    (unparsed action: {action.get('type')})")

        # Repeat detection: same action 5 times
        if len(traces) >= 5:
            last_5 = [t["code"] for t in traces[-5:]]
            if len(set(last_5)) == 1:
                print(f"  AUTO-STOP: same action repeated 5 times")
                break

        time.sleep(request_interval)

    elapsed = time.time() - start_time

    # Cost estimate (GPT-4o pricing: $2.50/1M input, $10/1M output)
    cost = (total_input_tokens * 2.5 + total_output_tokens * 10) / 1_000_000

    status_str = "FINISH" if is_finished else "TIMEOUT"
    print(f"  >>> {status_str}, steps={step_count}, elapsed={elapsed:.0f}s")
    print(f"      tokens: in={total_input_tokens}, out={total_output_tokens}, "
          f"cost=${cost:.4f}")
    sys.stdout.flush()

    # ── Inline evaluation: BOTH ADB + XML verifiers for cross-validation ──

    # 1. ADB rule-based verifier (agent-agnostic, checks device state)
    adb_eval = {"complete": False}
    try:
        from verifiers.verifier_map import get_verifier as _get_verifier
        from verifiers.query_detect_verifier import FUNCTION_MAP as _QD_MAP
        if metric_type == "operation":
            _vcls = _get_verifier(task_id)
            if _vcls:
                adb_eval = _vcls(container_url).is_successful()
        elif metric_type == "query_detect":
            _qcls = _QD_MAP.get(task_id)
            if _qcls:
                adb_eval = _qcls(container_url).is_successful(
                    agent_answer=finish_message)
    except Exception as _e:
        adb_eval = {"complete": False, "error": str(_e)[:200]}

    # 2. Original XML verifier — EXACTLY matches eval.py:_evaluate_single_task():
    #    - Iterate ALL per-step XML dumps (saved during agent loop above)
    #    - For each step: compress XML via get_compressed_xml, call judge(tree, line)
    #    - If judge_page=False: skip (continue to next step)
    #    - If judge_page=True or not present: keep as final_result (overwrite)
    #    - Repeat detection: same action 5 times → stop
    xml_eval = {"complete": False}
    _final_xml_raw = ""
    _cxml = None
    try:
        _orig_cwd = os.getcwd()
        sys.path.insert(0, "/shared/ligu/projects/SkyRL-AndriodWorld/Android-Lab")
        os.chdir("/shared/ligu/projects/SkyRL-AndriodWorld/Android-Lab")
        from utils_mobile.utils import get_compressed_xml as _get_cxml
        from evaluation.task import dump_xml as _dump_xml
        import importlib as _impmod

        # Module and class name mapping (from actual Android-Lab codebase files)
        _app_mod = {
            "setting": ("evaluation.tasks.setting.setting", "SingleTask_Setting_{}"),
            "contacts": ("evaluation.tasks.contacts.contacts", "SingleTask_Contacts_{}"),
            "clock": ("evaluation.tasks.clock.clock", "SingleTask_Clock_{}"),
            "bluecoins": ("evaluation.tasks.bluecoins.bluecoins", "SingleTask_bluecoins_{}"),
            "cantook": ("evaluation.tasks.cantook.cantook", "SingleTask_cantook_{}"),
            "pimusic": ("evaluation.tasks.pimusic.pimusic", "SingleTask_pimusic_{}"),
            "map": ("evaluation.tasks.map_me.map", "SingleTask_Mapme_{}"),
            "calendar": ("evaluation.tasks.calendar.calendar", "SingleTask_calendar_{}"),
            "zoom": ("evaluation.tasks.zoom.zoom", "SingleTask_Zoom_{}"),
        }
        _app_key = task_id.split("_")[0]
        _task_num = task_id.split("_")[1]
        _entry = _app_mod.get(_app_key)
        _judge = None
        if _entry:
            _mod_name, _cls_tmpl = _entry
            _cls_name = _cls_tmpl.format(_task_num)
            try:
                _mod = _impmod.import_module(_mod_name)
                _judge_cls = getattr(_mod, _cls_name, None)
                if _judge_cls:
                    # Fix #6: args needs judge_model for detect_answer() in query_detect tasks
                    class _JudgeArgs:
                        judge_model = "gpt-4o-2024-05-13"
                        api_key = ""  # uses OPENAI_API_KEY env var
                    _judge = _judge_cls(_JudgeArgs())
            except ImportError as _ie:
                xml_eval = {"complete": False, "error": f"import: {_ie}"}

        if _judge:
            # Iterate all per-step XMLs — exactly like eval.py lines 133-172
            _num_repeat = 0
            _last_action = None

            for _trace in traces:
                # Repeat detection (same as original eval.py lines 136-143)
                _current_action = json.dumps(_trace.get("parsed_action", {}))
                if _current_action == _last_action:
                    _num_repeat += 1
                    if _num_repeat > 5:
                        break
                else:
                    _num_repeat = 0
                    _last_action = _current_action

                # Get XML file path (saved during agent loop)
                _xml_file = _trace.get("xml_file")
                if not _xml_file or not os.path.exists(_xml_file):
                    continue

                # Compress XML — use original dump_xml() which does
                # get_compressed_xml(path) → json.loads()
                _xml_compressed = _dump_xml(_xml_file)
                if _xml_compressed is None:
                    continue

                # Build line dict matching original trace format
                _line = {
                    "parsed_action": _trace.get("parsed_action", {"action": ""}),
                }
                # Add command dict if this task has ADB queries
                if _trace.get("command"):
                    _line["command"] = _trace["command"]

                try:
                    _result = _judge.judge(_xml_compressed, _line)

                    # Same logic as eval.py lines 167-170:
                    # if judge_page is False → skip
                    # otherwise → keep as final result
                    if "judge_page" in _result and not _result.get("judge_page"):
                        continue
                    else:
                        xml_eval = _result
                except Exception:
                    pass

            # Save the last XML for post-hoc
            if traces and traces[-1].get("xml_file") and os.path.exists(traces[-1]["xml_file"]):
                with open(traces[-1]["xml_file"]) as _f:
                    _final_xml_raw = _f.read()

    except Exception as _e:
        xml_eval = {"complete": False, "error": str(_e)[:200]}
    finally:
        try:
            os.chdir(_orig_cwd)
        except Exception:
            pass

    adb_reward = 1.0 if adb_eval.get("complete") else 0.0
    xml_reward = 1.0 if xml_eval.get("complete") else 0.0

    # Per-step XMLs already saved in _xml_save_dir during agent loop

    return {
        "task_id": task_id,
        "app": app,
        "package": package,
        "metric_type": metric_type,
        "seed": 0,
        "task": task_def["task"],
        "reward": adb_reward,
        "xml_reward": xml_reward,
        "adb_eval": adb_eval,
        "xml_eval": xml_eval,
        "step_count": step_count,
        "finished": is_finished,
        "finish_description": finish_message,
        "elapsed_seconds": elapsed,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": cost,
        "num_turns": step_count,
        "traces": traces,
        "xml_dump_dir": _xml_save_dir,
    }


def _error_result(task_def, error_msg):
    return {
        "task_id": task_def["task_id"],
        "app": task_def.get("app", ""),
        "package": task_def.get("package", ""),
        "metric_type": task_def.get("metric_type", ""),
        "seed": 0,
        "task": task_def.get("task", ""),
        "reward": 0.0,
        "error": error_msg,
    }


# ─── Orchestration ───────────────────────────────────────────────────────────

def run_sequential(tasks, container_url, output_path, task_runner):
    results = []
    with open(output_path, "w") as out:
        for i, task_def in enumerate(tasks):
            result = task_runner(task_def, container_url)
            results.append(result)
            # Don't save traces to JSONL (too large)
            save_r = {k: v for k, v in result.items() if k != "traces"}
            out.write(json.dumps(save_r) + "\n")
            out.flush()
            successes = sum(1 for r in results if r.get("finished"))
            print(f"\n  Progress: {i+1}/{len(tasks)}, "
                  f"Finished: {successes}/{len(results)}")
    return results


def run_parallel(tasks, broker_url, pool_size, output_path, task_runner):
    import concurrent.futures
    import queue
    import threading

    task_queue = queue.Queue()
    for t in tasks:
        task_queue.put(t)

    results = []
    results_lock = threading.Lock()
    completed = [0]
    out_file = open(output_path, "w")
    out_lock = threading.Lock()

    def worker(wid):
        while True:
            try:
                task_def = task_queue.get_nowait()
            except queue.Empty:
                return

            env_id = None
            try:
                info = broker_acquire(broker_url)
                env_id = info["env_id"]
                port = info["server_port"]
                url = f"http://localhost:{port}"
                print(f"  [w{wid}] Acquired env{env_id} for {task_def['task_id']}")
                result = task_runner(task_def, url)
                healthy = True
            except Exception as e:
                print(f"  [w{wid}] ERROR: {e}")
                result = _error_result(task_def, str(e))
                healthy = False
            finally:
                if env_id is not None:
                    broker_release(broker_url, env_id, healthy=healthy)

            with results_lock:
                results.append(result)
                completed[0] += 1
                finished = sum(1 for r in results if r.get("finished"))
                print(f"\n  Progress: {completed[0]}/{len(tasks)}, "
                      f"Finished: {finished}/{len(results)}")

            save_r = {k: v for k, v in result.items() if k != "traces"}
            with out_lock:
                out_file.write(json.dumps(save_r) + "\n")
                out_file.flush()

            task_queue.task_done()

    num_workers = min(pool_size, len(tasks))
    print(f"Starting {num_workers} parallel workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as ex:
        futures = [ex.submit(worker, i) for i in range(num_workers)]
        concurrent.futures.wait(futures)

    out_file.close()
    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Reproduce Android-Lab: GPT-4o XML-only GUI agent"
    )
    parser.add_argument("--data", default=None)
    parser.add_argument("--tasks", type=str, default=None)
    parser.add_argument("--apps", nargs="+", default=None)
    parser.add_argument("--metric-type", default=None,
                        choices=["operation", "query_detect"])
    parser.add_argument("--model", default="gpt-4o",
                        help="OpenAI model (default: gpt-4o)")
    parser.add_argument("--max-rounds", type=int, default=25,
                        help="Max rounds per task (default: 25)")
    parser.add_argument("--request-interval", type=float, default=3,
                        help="Seconds between rounds (default: 3)")
    parser.add_argument("--output", default=None)

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container-url")
    group.add_argument("--broker-url")
    parser.add_argument("--pool-size", type=int, default=8)

    args = parser.parse_args()

    tasks = load_androidlab_tasks(
        data_path=args.data, task_ids=args.tasks,
        apps=args.apps, metric_type=args.metric_type,
    )
    if not tasks:
        print("No tasks.")
        return 1

    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        model_short = args.model.replace("-", "").replace(".", "")
        ts = time.strftime("%y%m%d_%H%M")
        exp_name = f"AndroidLab_GUIAgent_{model_short}_{ts}"
        output_dir = os.path.join(_EXAMPLES_DIR, os.pardir, "results", exp_name)
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "results.jsonl")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.environ["ANDROIDLAB_OUTPUT_PATH"] = output_path

    from functools import partial
    task_runner = partial(
        run_gui_agent,
        model=args.model,
        max_rounds=args.max_rounds,
        request_interval=args.request_interval,
    )

    print(f"Android-Lab GUI Agent Reproduction")
    print(f"Model: {args.model}, max_rounds={args.max_rounds}")
    print(f"Tasks: {len(tasks)}")
    print(f"Output: {output_path}")

    if args.broker_url:
        if not check_health(args.broker_url):
            print(f"ERROR: Broker not healthy")
            return 1
        results = run_parallel(
            tasks, args.broker_url, args.pool_size, output_path, task_runner
        )
    else:
        if not check_health(args.container_url):
            print(f"ERROR: Container not healthy")
            return 1
        results = run_sequential(
            tasks, args.container_url, output_path, task_runner
        )

    print_summary(results)

    # Cross-validation summary
    adb_successes = sum(1 for r in results if r.get("reward", 0) > 0)
    xml_successes = sum(1 for r in results if r.get("xml_reward", 0) > 0)
    both_pass = sum(1 for r in results if r.get("reward", 0) > 0 and r.get("xml_reward", 0) > 0)
    adb_only = sum(1 for r in results if r.get("reward", 0) > 0 and r.get("xml_reward", 0) == 0)
    xml_only = sum(1 for r in results if r.get("reward", 0) == 0 and r.get("xml_reward", 0) > 0)
    both_fail = sum(1 for r in results if r.get("reward", 0) == 0 and r.get("xml_reward", 0) == 0)

    print(f"\n{'='*60}")
    print(f"CROSS-VALIDATION: ADB vs XML Verifiers")
    print(f"{'='*60}")
    print(f"  ADB Verifier:  {adb_successes}/{len(results)} ({100*adb_successes/max(len(results),1):.1f}%)")
    print(f"  XML Verifier:  {xml_successes}/{len(results)} ({100*xml_successes/max(len(results),1):.1f}%)")
    print(f"  Both PASS:     {both_pass}")
    print(f"  ADB only:      {adb_only}  (ADB too loose or XML too strict)")
    print(f"  XML only:      {xml_only}  (ADB too strict or XML too loose)")
    print(f"  Both FAIL:     {both_fail}")
    print(f"  Agreement:     {both_pass + both_fail}/{len(results)} ({100*(both_pass+both_fail)/max(len(results),1):.1f}%)")

    if adb_only > 0 or xml_only > 0:
        print(f"\n  Disagreements:")
        for r in sorted(results, key=lambda x: x.get("task_id", "")):
            a = r.get("reward", 0) > 0
            x = r.get("xml_reward", 0) > 0
            if a != x:
                print(f"    {r['task_id']:20s} ADB={'PASS' if a else 'FAIL'} XML={'PASS' if x else 'FAIL'}")

    save_results(results, output_path, extra_meta={
        "model": args.model,
        "max_rounds": args.max_rounds,
        "agent": "GUIAgent_XMLOnly",
        "purpose": "reproduce_paper_with_adb_eval",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
