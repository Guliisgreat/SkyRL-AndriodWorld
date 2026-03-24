# Copyright 2025 The android_world Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations in the License.

"""Verify Tier 4 tasks on emulator: initialize + simulate agent + eval.

No agent or visualization needed. Runs each task's:
  1. initialize_task(env) - setup on emulator
  2. Simulate agent output (ADB commands or interaction_cache)
  3. is_successful(env) - verify eval logic

Usage:
  # Emulator must be running (e.g. emulator-5556)
  python verify_tier4_on_emulator.py --console_port 5556 --grpc_port 8556

  # Run specific task only
  python verify_tier4_on_emulator.py --console_port 5556 --task Tier4BulkDeleteTmpInDownloads

  # Show verbose logs (adb commands, etc.)
  python verify_tier4_on_emulator.py --console_port 5556 --verbose
"""

import logging as std_logging
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ANDROID_HOME", "/shared/ken/.android")
os.environ.setdefault("ANDROID_SDK_ROOT", "/shared/ken/.android")
os.environ.setdefault("TMPDIR", os.path.join(_PROJECT_ROOT, ".aw_tmp"))
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GRPC_TRACE"] = "none"

os.makedirs(os.environ["TMPDIR"], exist_ok=True)

from absl import app, flags, logging

# Apply ADB port patch before importing env_launcher (required for per-container ADB ports)
from skyrl_server.patches import patch_adb_port
patch_adb_port()

from android_world.env import adb_utils, device_constants, env_launcher

# Suppress verbose logs by default (adb_controller "Executing ADB command", etc.)
# Use --verbose to show them
from android_world.task_evals.common_validators import sms_validators
from android_world.utils import contacts_utils

# Import tier4 tasks from skyrl_server package (not upstream android_world)
_SKYRL_SERVER_DIR = os.path.join(_PROJECT_ROOT, "docker", "android")
if _SKYRL_SERVER_DIR not in sys.path:
    sys.path.insert(0, _SKYRL_SERVER_DIR)
from skyrl_server.tier4 import files, sms, system

FLAGS = flags.FLAGS
flags.DEFINE_integer("console_port", 5556, "Emulator console port (e.g. 5556 for emulator-5556)")
flags.DEFINE_integer("grpc_port", 8556, "gRPC port for emulator")
flags.DEFINE_string("task", None, "Run only this task (omit to run all 12)")
flags.DEFINE_string("adb_path", "/shared/ken/.android/platform-tools/adb", "Path to adb")
flags.DEFINE_bool("verbose", False, "Show verbose logs (adb commands, etc.)")


def _find_adb():
    for p in [
        "/shared/ken/.android/platform-tools/adb",
        os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
        os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
    ]:
        if os.path.isfile(p):
            return p
    return FLAGS.adb_path


def _run_tier4_bulk_delete(env):
    """Tier4BulkDeleteTmpInDownloads: init creates tmp files; simulate agent deletes them."""
    task = files.Tier4BulkDeleteTmpInDownloads({})
    task.initialize_task(env)
    res = adb_utils.issue_generic_request(
        ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp"],
        env.controller,
    )
    count = len([x for x in res.generic.output.decode().strip().split("\n") if x.strip()])
    print(f"    1. init:   ✓ created {count} tmp files in Downloads")
    cmd = f"adb shell find {device_constants.DOWNLOAD_DATA} -name *.tmp -delete"
    print(f"    2. execute: {cmd}")
    print(f"       reason: find and delete all .tmp files")
    adb_utils.issue_generic_request(
        ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp", "-delete"],
        env.controller,
    )
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_bulk_delete_wrong(env):
    """Tier4BulkDeleteTmpInDownloads (wrong): find but no -delete, files remain → FAIL."""
    task = files.Tier4BulkDeleteTmpInDownloads({})
    task.initialize_task(env)
    res = adb_utils.issue_generic_request(
        ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp"],
        env.controller,
    )
    count = len([x for x in res.generic.output.decode().strip().split("\n") if x.strip()])
    print(f"    1. init:   ✓ created {count} tmp files in Downloads")
    cmd = f"adb shell find {device_constants.DOWNLOAD_DATA} -name *.tmp  # NO -delete"
    print(f"    2. execute: {cmd}")
    print(f"       reason: wrong - agent finds but does not delete")
    # Only run find (no -delete), so files stay
    adb_utils.issue_generic_request(
        ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp"],
        env.controller,
    )
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_find_tmp_and_parse(env):
    """Run find for tmp files, return (basenames, agent_output from result)."""
    res = adb_utils.issue_generic_request(
        ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp"],
        env.controller,
    )
    lines = [l.strip() for l in res.generic.output.decode().strip().split("\n") if l.strip()]
    basenames = [line.split("/")[-1] for line in lines]
    agent_output = "None" if not basenames else " ".join(basenames)
    return basenames, agent_output


def _run_tier4_coverage_empty(env):
    """Tier4CoverageNoTmpInDownloads variant=empty: no tmp files; agent outputs None."""
    task = files.Tier4CoverageNoTmpInDownloads({"variant": "empty"})
    task.initialize_task(env)
    print(f"    1. init:   ✓ no tmp files (variant=empty)")
    cmd = f"adb shell find {device_constants.DOWNLOAD_DATA} -name *.tmp"
    print(f"    2. execute: {cmd}")
    basenames, agent_output = _run_find_tmp_and_parse(env)
    print(f"       reason: check if .tmp files exist; result={agent_output!r} → agent output")
    env.interaction_cache = agent_output  # derive from actual find result
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_coverage_empty_wrong(env):
    """Tier4CoverageNoTmpInDownloads (empty, wrong): agent says fake file → FAIL."""
    task = files.Tier4CoverageNoTmpInDownloads({"variant": "empty"})
    task.initialize_task(env)
    print(f"    1. init:   ✓ no tmp files (variant=empty) - wrong case test")
    cmd = f"adb shell find {device_constants.DOWNLOAD_DATA} -name *.tmp"
    print(f"    2. execute: {cmd}")
    _run_find_tmp_and_parse(env)  # run find (agent's check), but we set wrong output
    print(f"       reason: result empty but agent wrongly says 'fake.tmp'")
    env.interaction_cache = "fake.tmp"  # wrong: find returned nothing
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_coverage_has_tmp(env):
    """Tier4CoverageNoTmpInDownloads variant=has_tmp: agent lists the tmp files."""
    task = files.Tier4CoverageNoTmpInDownloads({"variant": "has_tmp"})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created {len(task._ground_truth)} tmp files")
    cmd = f"adb shell find {device_constants.DOWNLOAD_DATA} -name *.tmp"
    print(f"    2. execute: {cmd}")
    basenames, agent_output = _run_find_tmp_and_parse(env)
    print(f"       reason: check if .tmp files exist; result={agent_output!r} → agent output")
    env.interaction_cache = agent_output  # derive from actual find result
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_coverage_has_tmp_wrong(env):
    """Tier4CoverageNoTmpInDownloads (has_tmp, wrong): agent says None → FAIL."""
    task = files.Tier4CoverageNoTmpInDownloads({"variant": "has_tmp"})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created {len(task._ground_truth)} tmp files")
    cmd = f"adb shell find {device_constants.DOWNLOAD_DATA} -name *.tmp"
    print(f"    2. execute: {cmd}")
    basenames, _ = _run_find_tmp_and_parse(env)
    print(f"       reason: result has {len(basenames)} files but agent wrongly says 'None'")
    env.interaction_cache = "None"  # wrong: find returned files
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_dumpsys_app_versions(env):
    """Run dumpsys package for each app, return agent output from actual result."""
    app_packages = system._APP_PACKAGES
    result = {name: system._get_app_version(pkg, env) for name, pkg in app_packages.items()}
    return ", ".join(f"{k} {v}" for k, v in result.items())


def _run_tier4_app_versions(env):
    """Tier4HiddenStateListAppVersions: agent lists app names and versions."""
    task = system.Tier4HiddenStateListAppVersions({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ app versions ready")
    pkgs = ", ".join(system._APP_PACKAGES.values())
    print(f"    2. execute: adb shell dumpsys package <pkg>  # {pkgs}")
    agent_output = _run_dumpsys_app_versions(env)
    print(f"       reason: query each app version; result → agent output")
    env.interaction_cache = agent_output
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_app_versions_wrong(env):
    """Tier4HiddenStateListAppVersions (wrong): agent outputs wrong version → FAIL."""
    task = system.Tier4HiddenStateListAppVersions({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ app versions ready")
    pkgs = ", ".join(system._APP_PACKAGES.values())
    print(f"    2. execute: adb shell dumpsys package <pkg>  # {pkgs}")
    print(f"       reason: agent reports wrong version numbers (99.99)")
    wrong_parts = [f"{k} 99.99" for k in task._ground_truth]
    env.interaction_cache = ", ".join(wrong_parts)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_content_query_unread_count(env):
    """Run content query for unread SMS, return count from actual result."""
    return sms._count_unread_sms(env)


def _run_tier4_count_unread_sms(env):
    """Tier4AggregationCountUnreadSMS: agent outputs unread count."""
    task = sms.Tier4AggregationCountUnreadSMS({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ SMS with unread count ready")
    cmd = "adb shell content query --uri content://sms/inbox --projection _id --where read=0"
    print(f"    2. execute: {cmd}")
    agent_output = str(_run_content_query_unread_count(env))
    print(f"       reason: count unread SMS; result={agent_output} → agent output")
    env.interaction_cache = agent_output
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_count_unread_sms_wrong(env):
    """Tier4AggregationCountUnreadSMS (wrong): agent outputs wrong count → FAIL."""
    task = sms.Tier4AggregationCountUnreadSMS({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ SMS with unread count ready (actual={task._ground_truth})")
    cmd = "adb shell content query --uri content://sms/inbox --projection _id --where read=0"
    print(f"    2. execute: {cmd}")
    wrong_count = 0 if task._ground_truth > 0 else 999
    print(f"       reason: result={task._ground_truth} but agent wrongly says '{wrong_count}'")
    env.interaction_cache = str(wrong_count)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_query_sms_numbers_not_in_contacts(env):
    """Query SMS inbox + contacts, return numbers in SMS but not in contacts."""
    # 1. Get SMS inbox addresses
    res = adb_utils.issue_generic_request(
        ["shell", "content", "query", "--uri", "content://sms/inbox"],
        env.controller,
    )
    messages = sms_validators._decode_messages_from_response(res)
    sms_normalized_to_addr = {}  # digits -> original addr (for output format)
    for msg in messages:
        try:
            fields = sms_validators.parse_message(msg)
            addr = fields.get("address", "").replace("-", "").replace(" ", "")
            if addr:
                norm = contacts_utils.clean_phone_number(addr)
                sms_normalized_to_addr[norm] = addr
        except (KeyError, ValueError):
            pass
    # 2. Get contact numbers (digits only)
    contacts = contacts_utils.list_contacts(env.controller)
    contact_numbers = {c.number for c in contacts}
    # 3. SMS addresses not in contacts
    not_in_contacts = set(sms_normalized_to_addr.keys()) - contact_numbers
    return sorted(sms_normalized_to_addr[n] for n in not_in_contacts)


def _run_tier4_sms_not_in_contacts(env):
    """Tier4CrossAppSmsNumbersNotInContacts: agent lists non-contact numbers."""
    task = sms.Tier4CrossAppSmsNumbersNotInContacts({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ SMS from non-contacts ready")
    cmd_sms = "adb shell content query --uri content://sms/inbox"
    cmd_contacts = "adb shell content query --uri content://contacts/phones/"
    print(f"    2. execute: {cmd_sms} + {cmd_contacts}")
    numbers = _run_query_sms_numbers_not_in_contacts(env)
    agent_output = ", ".join(numbers)
    print(f"       reason: query SMS + contacts; numbers not in contacts → agent output")
    env.interaction_cache = agent_output
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_sms_not_in_contacts_wrong(env):
    """Tier4CrossAppSmsNumbersNotInContacts (wrong): agent reports wrong numbers → FAIL."""
    task = sms.Tier4CrossAppSmsNumbersNotInContacts({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ SMS from non-contacts ready")
    cmd_sms = "adb shell content query --uri content://sms/inbox"
    cmd_contacts = "adb shell content query --uri content://contacts/phones/"
    print(f"    2. execute: {cmd_sms} + {cmd_contacts}")
    print(f"       reason: result has numbers but agent wrongly says '5551234567'")
    env.interaction_cache = "5551234567"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


_TASKS = [
    # (name, run_fn, expect_pass) - expect_pass=False means we expect score<1.0 (wrong output)
    ("Tier4BulkDeleteTmpInDownloads", _run_tier4_bulk_delete, True),
    ("Tier4BulkDeleteTmpInDownloads (wrong)", _run_tier4_bulk_delete_wrong, False),
    ("Tier4CoverageNoTmpInDownloads (empty)", _run_tier4_coverage_empty, True),
    ("Tier4CoverageNoTmpInDownloads (empty, wrong)", _run_tier4_coverage_empty_wrong, False),
    ("Tier4CoverageNoTmpInDownloads (has_tmp)", _run_tier4_coverage_has_tmp, True),
    ("Tier4CoverageNoTmpInDownloads (has_tmp, wrong)", _run_tier4_coverage_has_tmp_wrong, False),
    ("Tier4HiddenStateListAppVersions", _run_tier4_app_versions, True),
    ("Tier4HiddenStateListAppVersions (wrong)", _run_tier4_app_versions_wrong, False),
    ("Tier4AggregationCountUnreadSMS", _run_tier4_count_unread_sms, True),
    ("Tier4AggregationCountUnreadSMS (wrong)", _run_tier4_count_unread_sms_wrong, False),
    ("Tier4CrossAppSmsNumbersNotInContacts", _run_tier4_sms_not_in_contacts, True),
    ("Tier4CrossAppSmsNumbersNotInContacts (wrong)", _run_tier4_sms_not_in_contacts_wrong, False),
]


def main(argv):
    del argv
    logging.set_verbosity(logging.INFO if FLAGS.verbose else logging.WARNING)
    # Suppress expected "Skipping app snapshot loading" for Tier4 (no snapshot needed)
    std_logging.getLogger("android_world.task_evals.task_eval").setLevel(std_logging.ERROR)
    console_port = FLAGS.console_port
    grpc_port = FLAGS.grpc_port
    adb_path = _find_adb()

    print("=" * 70)
    print("Tier 4 Emulator Verification (init + simulated agent + eval)")
    print("=" * 70)
    print(f"Console port: {console_port} | gRPC port: {grpc_port}")
    print(f"ADB: {adb_path}")
    print()

    env = env_launcher.load_and_setup_env(
        console_port=console_port,
        emulator_setup=False,
        freeze_datetime=True,
        adb_path=adb_path,
        grpc_port=grpc_port,
    )
    env.reset(go_home=True)

    # Ensure interaction_cache exists
    if not hasattr(env, "interaction_cache"):
        env.interaction_cache = ""

    results = []
    tasks_to_run = _TASKS
    if FLAGS.task:
        tasks_to_run = [(n, f, e) for n, f, e in _TASKS if FLAGS.task in n]
        if not tasks_to_run:
            print(f"Task '{FLAGS.task}' not found. Available: {[t[0] for t in _TASKS]}")
            sys.exit(1)

    for name, run_fn, expect_pass in tasks_to_run:
        print(f"\n  [{name}]")
        try:
            score = run_fn(env)
            # expect_pass: want score>=1.0; expect_fail: want score<1.0
            ok = (score >= 1.0) == expect_pass
            results.append((name, ok, score))
            status = "✓" if ok else "✗"
            print(f"  => {status} {name}")
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"  ✗ {name}: ERROR - {e}")

    env.close()

    print()
    print("=" * 70)
    passed = sum(1 for _, ok, _ in results if ok is True)
    print(f"Passed: {passed}/{len(results)}")
    print("=" * 70)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    app.run(main)
