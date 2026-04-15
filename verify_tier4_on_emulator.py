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
import re
import sys
import time

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
from skyrl_server.tier4 import broccoli as tier4_broccoli
from skyrl_server.tier4 import calendar as tier4_calendar
from skyrl_server.tier4 import contacts as tier4_contacts
from skyrl_server.tier4 import cross_app as tier4_cross_app
from skyrl_server.tier4 import expense as tier4_expense
from skyrl_server.tier4 import files, markor, sms, system
from skyrl_server.tier4 import joplin as tier4_joplin
from skyrl_server.tier4 import opentracks as tier4_opentracks
from skyrl_server.tier4 import retro_music as tier4_retro_music
from skyrl_server.tier4 import tasks_app as tier4_tasks_app

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


# ── Phase 2: SMS ──────────────────────────────────────────────────────

def _run_tier4_filter_delete_old_sms(env):
  """Tier4FilterDeleteOldNonContactKeywordSms: agent deletes old+non-contact+keyword SMS."""
  task = sms.Tier4FilterDeleteOldNonContactKeywordSms({"keyword": "promo"})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._to_delete_nums)} old+keyword SMS + keep SMS")
  old_ms = int(time.time() * 1000) - 35 * 24 * 3600 * 1000
  print(f"    2. execute: query SMS, filter old+non-contact+keyword, delete")
  for num in task._to_delete_nums:
    adb_utils.issue_generic_request(
        ["shell", "content", "delete", "--uri", sms._SMS_INBOX_URI,
         "--where", f"address='{num}' AND body LIKE '%promo%' AND date<{old_ms}"],
        env.controller,
    )
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_filter_delete_old_sms_wrong(env):
  """Tier4FilterDeleteOldNonContactKeywordSms (wrong): agent deletes nothing -> FAIL."""
  task = sms.Tier4FilterDeleteOldNonContactKeywordSms({"keyword": "promo"})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._to_delete_nums)} old+keyword SMS")
  print(f"    2. execute: (agent does nothing)")
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_topk_sms_threads(env):
  """Tier4TopKSmsThreadsByCount: agent lists top-3 numbers by message count."""
  task = sms.Tier4TopKSmsThreadsByCount({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ inserted SMS for {len(task._num_counts)} numbers")
  print(f"    2. execute: content query SMS inbox, count per address, top 3")
  res = adb_utils.issue_generic_request(
      ["shell", "content", "query", "--uri", sms._SMS_INBOX_URI,
       "--projection", "address"],
      env.controller,
  )
  from collections import Counter
  addrs = re.findall(r"address=(\S+)", res.generic.output.decode())
  top3 = [addr for addr, _ in Counter(addrs).most_common(3)]
  agent_output = " ".join(top3)
  print(f"       reason: top3={top3} → agent output")
  env.interaction_cache = agent_output
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_topk_sms_threads_wrong(env):
  """Tier4TopKSmsThreadsByCount (wrong): agent outputs wrong numbers -> FAIL."""
  task = sms.Tier4TopKSmsThreadsByCount({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ inserted SMS for {len(task._num_counts)} numbers")
  print(f"    2. execute: (agent outputs wrong numbers)")
  env.interaction_cache = "0000000000 1111111111 2222222222"
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


# ── Phase 2: Contacts ─────────────────────────────────────────────────

def _run_tier4_contacts_no_recent_sms(env):
  """Tier4CrossAppContactsNoRecentSms: agent lists contacts with email but no SMS."""
  task = tier4_contacts.Tier4CrossAppContactsNoRecentSms({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ contacts with email: {len(task._ground_truth)} no-SMS, 2 with-SMS")
  print(f"    2. execute: query contacts email + SMS join")
  env.interaction_cache = " ".join(task._ground_truth)
  print(f"       reason: no-SMS contact names → agent output")
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_contacts_no_recent_sms_wrong(env):
  """Tier4CrossAppContactsNoRecentSms (wrong): agent lists wrong names -> FAIL."""
  task = tier4_contacts.Tier4CrossAppContactsNoRecentSms({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ contacts ready")
  print(f"    2. execute: (agent outputs wrong names)")
  env.interaction_cache = "WrongContact0 WrongContact1"
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_birthday_no_phone(env):
  """Tier4FilterContactsBirthdayNoPhone: agent lists contacts with birthday but no phone."""
  task = tier4_contacts.Tier4FilterContactsBirthdayNoPhone({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._ground_truth)} birthday-only contacts")
  print(f"    2. execute: query contacts data for birthday vs phone")
  env.interaction_cache = " ".join(task._ground_truth)
  print(f"       reason: birthday-only names → agent output")
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_birthday_no_phone_wrong(env):
  """Tier4FilterContactsBirthdayNoPhone (wrong): agent outputs wrong names -> FAIL."""
  task = tier4_contacts.Tier4FilterContactsBirthdayNoPhone({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ contacts ready")
  print(f"    2. execute: (agent outputs wrong names)")
  env.interaction_cache = "ContactWithPhone0"
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_longest_contact_name(env):
  """Tier4AggregationLongestContactName: agent outputs the longest contact name."""
  task = tier4_contacts.Tier4AggregationLongestContactName({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ contacts added, longest='{task._ground_truth}'")
  print(f"    2. execute: query contacts, find max len name")
  res = adb_utils.issue_generic_request(
      ["shell", "content", "query", "--uri", tier4_contacts._CONTACTS_PHONES_URI,
       "--projection", "display_name"],
      env.controller,
  )
  names = re.findall(r"display_name=(.+)", res.generic.output.decode())
  agent_output = max(names, key=len) if names else ""
  print(f"       reason: longest name='{agent_output}' → agent output")
  env.interaction_cache = agent_output
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_longest_contact_name_wrong(env):
  """Tier4AggregationLongestContactName (wrong): agent outputs short name -> FAIL."""
  task = tier4_contacts.Tier4AggregationLongestContactName({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ contacts added, longest='{task._ground_truth}'")
  print(f"    2. execute: (agent outputs wrong name)")
  env.interaction_cache = "Al"
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_dedup_contacts_list(env):
  """Tier4DedupContactsDuplicatePhones: agent lists contacts sharing a phone."""
  task = tier4_contacts.Tier4DedupContactsDuplicatePhones({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created contacts with shared phones")
  print(f"    2. execute: query contacts, group by number, find dupes")
  env.interaction_cache = " ".join(task._dup_names)
  print(f"       reason: dup names → agent output")
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_dedup_contacts_list_wrong(env):
  """Tier4DedupContactsDuplicatePhones (wrong): agent misses dup names -> FAIL."""
  task = tier4_contacts.Tier4DedupContactsDuplicatePhones({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ contacts ready")
  print(f"    2. execute: (agent outputs only unique contact)")
  env.interaction_cache = "UniqueContact"
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_dedup_merge_contacts(env):
  """Tier4DedupMergeContactsSamePhone: agent merges contacts, keeps alpha-first."""
  task = tier4_contacts.Tier4DedupMergeContactsSamePhone({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._deleted_names)} duplicate pairs")
  print(f"    2. execute: find duplicates, delete non-alpha-first contacts")
  for name in task._deleted_names:
    adb_utils.issue_generic_request(
        ["shell", "content", "delete",
         "--uri", tier4_contacts._CONTACTS_PHONES_URI,
         "--where", f"display_name='{name}'"],
        env.controller,
    )
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_dedup_merge_contacts_wrong(env):
  """Tier4DedupMergeContactsSamePhone (wrong): agent keeps wrong name -> FAIL."""
  task = tier4_contacts.Tier4DedupMergeContactsSamePhone({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ duplicate contacts ready")
  print(f"    2. execute: (agent deletes wrong contacts, keeps non-alpha-first)")
  for name in task._kept_names:
    adb_utils.issue_generic_request(
        ["shell", "content", "delete",
         "--uri", tier4_contacts._CONTACTS_PHONES_URI,
         "--where", f"display_name='{name}'"],
        env.controller,
    )
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


# ── Phase 1: Files ────────────────────────────────────────────────────

def _run_tier4_bulk_rename_screenshots(env):
  """Tier4BulkRenameScreenshots: agent renames Screenshot_* to YYYYMMDD_HHMMSS.png."""
  task = files.Tier4BulkRenameScreenshots({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._ground_truth)} Screenshot_* files in Pictures")
  print(f"    2. execute: mv Screenshot_*.png to YYYYMMDD_HHMMSS.png via mtime")
  for old_name, new_name in task._ground_truth.items():
    adb_utils.issue_generic_request(
        ["shell", "mv",
         f"{files._PICTURES_DIR}/{old_name}",
         f"{files._PICTURES_DIR}/{new_name}"],
        env.controller,
    )
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_bulk_rename_screenshots_wrong(env):
  """Tier4BulkRenameScreenshots (wrong): agent does not rename -> FAIL."""
  task = files.Tier4BulkRenameScreenshots({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._ground_truth)} Screenshot_* files")
  print(f"    2. execute: (agent skips rename)")
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_bulk_move_large_files(env):
  """Tier4BulkMoveLargeFiles: agent moves >50MB files to Archive."""
  task = files.Tier4BulkMoveLargeFiles({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._large_names)} large files in Download")
  print(f"    2. execute: find Download -size +50M, mv to Archive")
  for name in task._large_names:
    adb_utils.issue_generic_request(
        ["shell", "mv",
         f"{device_constants.DOWNLOAD_DATA}/{name}",
         f"{files._ARCHIVE_DIR}/{name}"],
        env.controller,
    )
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_bulk_move_large_files_wrong(env):
  """Tier4BulkMoveLargeFiles (wrong): agent moves nothing -> FAIL."""
  task = files.Tier4BulkMoveLargeFiles({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._large_names)} large files in Download")
  print(f"    2. execute: (agent skips move)")
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_filter_recent_log_files(env):
  """Tier4FilterRecentLogFiles: agent lists .log/.txt files modified <60min ago."""
  task = files.Tier4FilterRecentLogFiles({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._ground_truth)} recent + 2 old log/txt files")
  cmd = "adb shell find Download \\( -name '*.log' -o -name '*.txt' \\) -mmin -60"
  print(f"    2. execute: {cmd}")
  res = adb_utils.issue_generic_request(
      ["shell", "find", device_constants.DOWNLOAD_DATA,
       r"\(", "-name", "*.log", "-o", "-name", "*.txt", r"\)",
       "-mmin", "-60"],
      env.controller,
  )
  lines = [
      l.strip().split("/")[-1]
      for l in res.generic.output.decode().strip().split("\n")
      if l.strip()
  ]
  agent_output = " ".join(lines)
  print(f"       reason: result={agent_output!r} → agent output")
  env.interaction_cache = agent_output
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_filter_recent_log_files_wrong(env):
  """Tier4FilterRecentLogFiles (wrong): agent outputs old filenames -> FAIL."""
  task = files.Tier4FilterRecentLogFiles({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._ground_truth)} recent log/txt files")
  print(f"    2. execute: (agent outputs wrong filenames)")
  env.interaction_cache = "old_0001.log old_0002.txt"
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


# ── Phase 1: Markor ───────────────────────────────────────────────────

def _run_tier4_bulk_append_footer(env):
  """Tier4BulkAppendFooterToMarkdown: agent appends footer to all .md files."""
  task = markor.Tier4BulkAppendFooterToMarkdown({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._filenames)} .md files in Markor/Notes")
  print(f"    2. execute: find Notes -name '*.md', echo >> each")
  for name in task._filenames:
    adb_utils.issue_generic_request(
        ["shell", "sh", "-c",
         f"printf '\\n---\\nGenerated by AutoBot' >> {markor._MARKOR_NOTES_DIR}/{name}"],
        env.controller,
    )
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_bulk_append_footer_wrong(env):
  """Tier4BulkAppendFooterToMarkdown (wrong): agent appends wrong text -> FAIL."""
  task = markor.Tier4BulkAppendFooterToMarkdown({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._filenames)} .md files")
  print(f"    2. execute: (agent appends wrong text)")
  for name in task._filenames:
    adb_utils.issue_generic_request(
        ["shell", "sh", "-c",
         f"echo 'wrong footer' >> {markor._MARKOR_NOTES_DIR}/{name}"],
        env.controller,
    )
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_longest_markor_note(env):
  """Tier4AggregationLongestMarkorNote: agent outputs the longest note filename."""
  task = markor.Tier4AggregationLongestMarkorNote({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._filenames)} notes with varying lengths")
  print(f"    2. execute: wc -c *.md | sort -n | tail -1")
  res = adb_utils.issue_generic_request(
      ["shell", "sh", "-c",
       f"wc -c {markor._MARKOR_DIR}/longtest_*.md | sort -n | tail -2 | head -1"],
      env.controller,
  )
  # Output: "  512 /path/to/longtest_XXXX.md"
  output = res.generic.output.decode().strip()
  agent_output = output.split("/")[-1] if "/" in output else output.split()[-1]
  print(f"       reason: result={agent_output!r} → agent output")
  env.interaction_cache = agent_output
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_longest_markor_note_wrong(env):
  """Tier4AggregationLongestMarkorNote (wrong): agent outputs wrong filename -> FAIL."""
  task = markor.Tier4AggregationLongestMarkorNote({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._filenames)} notes")
  print(f"    2. execute: (agent outputs wrong filename)")
  env.interaction_cache = "wrong_note.md"
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_topk_markor_modified(env):
  """Tier4TopKMarkorMostModifiedNotes: agent lists top-5 most recently modified."""
  task = markor.Tier4TopKMarkorMostModifiedNotes({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._filenames)} notes with staggered mtimes")
  print(f"    2. execute: ls -t Markor/recent_*.md | head -5")
  res = adb_utils.issue_generic_request(
      ["shell", "sh", "-c",
       f"ls -t {markor._MARKOR_DIR}/recent_*.md 2>/dev/null | head -5"],
      env.controller,
  )
  lines = [
      l.strip().split("/")[-1]
      for l in res.generic.output.decode().strip().split("\n")
      if l.strip()
  ]
  agent_output = " ".join(lines)
  print(f"       reason: result={agent_output!r} → agent output")
  env.interaction_cache = agent_output
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
  return score


def _run_tier4_topk_markor_modified_wrong(env):
  """Tier4TopKMarkorMostModifiedNotes (wrong): agent outputs wrong filenames -> FAIL."""
  task = markor.Tier4TopKMarkorMostModifiedNotes({})
  task.initialize_task(env)
  print(f"    1. init:   ✓ created {len(task._filenames)} notes")
  print(f"    2. execute: (agent outputs wrong filenames)")
  env.interaction_cache = "wrong_1.md wrong_2.md wrong_3.md wrong_4.md wrong_5.md"
  score = task.is_successful(env)
  task.tear_down(env)
  print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
  return score


def _run_tier4_files_during_events(env):
    """Tier4CrossAppFilesCreatedDuringEvents: agent lists Downloads files within event windows."""
    task = tier4_cross_app.Tier4CrossAppFilesCreatedDuringEvents({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created {len(task._all_files)} files, {len(task._ground_truth)} inside event windows")
    print("    2. execute: (agent cross-references file mtimes with calendar events)")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_files_during_events_wrong(env):
    """Tier4CrossAppFilesCreatedDuringEvents (wrong): agent lists outside-window files -> FAIL."""
    task = tier4_cross_app.Tier4CrossAppFilesCreatedDuringEvents({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created files with staggered mtimes")
    print("    2. execute: (agent lists all files, ignoring event windows)")
    env.interaction_cache = "tier4xa_out_recent.bin tier4xa_out_old.bin"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_markor_phones_vs_contacts(env):
    """Tier4CrossAppMarkorPhonesVsContacts: agent finds phone numbers in Markor not in contacts."""
    task = tier4_cross_app.Tier4CrossAppMarkorPhonesVsContacts({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created Markor note, added contacts, non-contact nums={task._ground_truth}")
    print("    2. execute: (agent extracts numbers from notes, filters against contacts)")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_markor_phones_vs_contacts_wrong(env):
    """Tier4CrossAppMarkorPhonesVsContacts (wrong): agent includes contact numbers -> FAIL."""
    task = tier4_cross_app.Tier4CrossAppMarkorPhonesVsContacts({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created Markor note and contacts")
    print("    2. execute: (agent outputs wrong number)")
    env.interaction_cache = "+15550001001"  # This IS a contact
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_download_size_top3(env):
    """Tier4AggregationDownloadSizeTop3: agent reports total size and top-3 files."""
    task = files.Tier4AggregationDownloadSizeTop3({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created {len(task._filenames)} files, total={task._ground_truth_total}B, top3={task._ground_truth_top3}")
    print("    2. execute: du -sb Downloads && ls -S Downloads | head -3")
    res = adb_utils.issue_generic_request(
        ["shell", "sh", "-c",
         f"du -sb {device_constants.DOWNLOAD_DATA}/tier4dl_*.bin | awk '{{s+=$1}} END {{print s}}' && "
         f"ls -S {device_constants.DOWNLOAD_DATA}/tier4dl_*.bin | xargs -I{{}} basename {{}} | head -3"],
        env.controller,
    )
    output = res.generic.output.decode().strip()
    lines = [l.strip() for l in output.split("\n") if l.strip()]
    total_line = lines[0] if lines else "0"
    top3_names = lines[1:4]
    env.interaction_cache = f"{total_line} " + " ".join(top3_names)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_download_size_top3_wrong(env):
    """Tier4AggregationDownloadSizeTop3 (wrong): agent outputs wrong total -> FAIL."""
    task = files.Tier4AggregationDownloadSizeTop3({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created files, total={task._ground_truth_total}")
    print("    2. execute: (agent outputs wrong total)")
    env.interaction_cache = "1 bytes"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_topk_largest_downloads(env):
    """Tier4TopKLargestDownloadFiles: agent lists top-5 largest files in Downloads."""
    task = files.Tier4TopKLargestDownloadFiles({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created {len(task._filenames)} files, top5={task._ground_truth}")
    print("    2. execute: ls -S Downloads | head -5")
    res = adb_utils.issue_generic_request(
        ["shell", "sh", "-c",
         f"ls -S {device_constants.DOWNLOAD_DATA}/tier4top5_*.bin 2>/dev/null | xargs -I{{}} basename {{}} | head -5"],
        env.controller,
    )
    lines = [l.strip() for l in res.generic.output.decode().strip().split("\n") if l.strip()]
    env.interaction_cache = " ".join(lines)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_topk_largest_downloads_wrong(env):
    """Tier4TopKLargestDownloadFiles (wrong): agent lists wrong filenames -> FAIL."""
    task = files.Tier4TopKLargestDownloadFiles({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created files")
    print("    2. execute: (agent outputs wrong names)")
    env.interaction_cache = "wrong_1.bin wrong_2.bin wrong_3.bin wrong_4.bin wrong_5.bin"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_coverage_all_sms_read_has_unread(env):
    """Tier4CoverageAllSmsRead (has_unread): agent reports unread count."""
    task = sms.Tier4CoverageAllSmsRead({"variant": "has_unread"})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted {task._ground_truth} unread SMS")
    print("    2. execute: content query --uri content://sms/inbox --where read=0")
    res = adb_utils.issue_generic_request(
        ["shell", "content", "query", "--uri", "content://sms/inbox",
         "--projection", "_id", "--where", "read=0"],
        env.controller,
    )
    output = res.generic.output.decode()
    count = 0 if ("No result" in output or not output.strip()) else len(output.strip().split("\n"))
    env.interaction_cache = str(count)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_coverage_all_sms_read_wrong(env):
    """Tier4CoverageAllSmsRead (has_unread, wrong): agent says 0 when there are unread -> FAIL."""
    task = sms.Tier4CoverageAllSmsRead({"variant": "has_unread"})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted {task._ground_truth} unread SMS")
    print("    2. execute: (agent says 'all read' incorrectly)")
    env.interaction_cache = "all read"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_location_permissions(env):
    """Tier4HiddenStateLocationPermissions: agent lists location-granted packages."""
    task = system.Tier4HiddenStateLocationPermissions({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ found {len(task._ground_truth)} packages with location permission")
    print("    2. execute: (agent outputs all location-granted packages)")
    if task._ground_truth:
        env.interaction_cache = " ".join(task._ground_truth)
    else:
        env.interaction_cache = "None"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_location_permissions_wrong(env):
    """Tier4HiddenStateLocationPermissions (wrong): agent outputs wrong packages -> FAIL."""
    task = system.Tier4HiddenStateLocationPermissions({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ queried location permissions")
    print("    2. execute: (agent outputs wrong packages)")
    env.interaction_cache = "com.nonexistent.wrongapp"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_audio_routing(env):
    """Tier4HiddenStateAudioRouting: agent reports volume and routing device."""
    task = system.Tier4HiddenStateAudioRouting({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ volume={task._ground_truth_volume}, device={task._ground_truth_device!r}")
    print("    2. execute: (agent outputs volume and routing)")
    env.interaction_cache = f"speaker volume {task._ground_truth_volume}"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_audio_routing_wrong(env):
    """Tier4HiddenStateAudioRouting (wrong): agent outputs wrong volume -> FAIL."""
    task = system.Tier4HiddenStateAudioRouting({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ volume={task._ground_truth_volume}")
    print("    2. execute: (agent outputs wrong volume)")
    env.interaction_cache = "9999"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_camera_permission(env):
    """Tier4CoverageAppsCameraPermission: agent lists camera-granted packages."""
    task = system.Tier4CoverageAppsCameraPermission({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ found {len(task._ground_truth)} packages with camera permission")
    print("    2. execute: (agent outputs all camera-granted packages)")
    if task._ground_truth:
        env.interaction_cache = " ".join(task._ground_truth)
    else:
        env.interaction_cache = "None"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_camera_permission_wrong(env):
    """Tier4CoverageAppsCameraPermission (wrong): agent outputs wrong packages -> FAIL."""
    task = system.Tier4CoverageAppsCameraPermission({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ queried camera permissions, found {len(task._ground_truth)}")
    print("    2. execute: (agent outputs wrong packages)")
    env.interaction_cache = "com.nonexistent.wrongapp"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_wifi_connected(env):
    """Tier4CoverageWifiConnected: agent reports WiFi state and SSID."""
    task = system.Tier4CoverageWifiConnected({})
    task.initialize_task(env)
    state = "enabled" if task._wifi_enabled else "disabled"
    print(f"    1. init:   ✓ wifi={state}, ssid={task._ground_truth_ssid!r}")
    print("    2. execute: (agent outputs correct state and SSID)")
    env.interaction_cache = f"WiFi is {state}, connected to {task._ground_truth_ssid}"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_wifi_connected_wrong(env):
    """Tier4CoverageWifiConnected (wrong): agent outputs wrong state -> FAIL."""
    task = system.Tier4CoverageWifiConnected({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ wifi state queried")
    print("    2. execute: (agent outputs wrong info)")
    env.interaction_cache = "WiFi is unknown and SSID is wrong_ssid"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_bulk_delete_calendar_events(env):
    """Tier4BulkDeleteCalendarTestEvents: agent deletes all events with 'test' in title."""
    task = tier4_calendar.Tier4BulkDeleteCalendarTestEvents({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted {len(task._test_event_ids)} test events + {len(task._keep_event_ids)} keep events")
    print("    2. execute: delete events WHERE title LIKE '%test%'")
    for eid in task._test_event_ids:
        adb_utils.issue_generic_request(
            ["shell", "content", "delete", "--uri", tier4_calendar._CALENDAR_EVENTS_URI,
             "--where", f"_id={eid}"],
            env.controller,
        )
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_bulk_delete_calendar_events_wrong(env):
    """Tier4BulkDeleteCalendarTestEvents (wrong): agent deletes nothing -> FAIL."""
    task = tier4_calendar.Tier4BulkDeleteCalendarTestEvents({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted test events")
    print("    2. execute: (agent does nothing)")
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_cross_app_calendar_to_markor(env):
    """Tier4CrossAppCalendarToMarkor: agent finds keyword events, writes Markor note."""
    task = tier4_calendar.Tier4CrossAppCalendarToMarkor({"keyword": "meeting"})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted {len(task._ground_truth)} matching + 2 non-matching events")
    print("    2. execute: query calendar, write Markor note")
    # Write note with all matching titles
    note_content = "\n".join(task._ground_truth)
    adb_utils.issue_generic_request(
        ["shell", "sh", "-c", f"mkdir -p {tier4_calendar._MARKOR_DIR} && printf '{note_content}' > {task._note_path}"],
        env.controller,
    )
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_cross_app_calendar_to_markor_wrong(env):
    """Tier4CrossAppCalendarToMarkor (wrong): note missing some events -> FAIL."""
    task = tier4_calendar.Tier4CrossAppCalendarToMarkor({"keyword": "meeting"})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted events")
    print("    2. execute: (agent writes note with wrong content)")
    adb_utils.issue_generic_request(
        ["shell", "sh", "-c", f"mkdir -p {tier4_calendar._MARKOR_DIR} && printf 'wrong content' > {task._note_path}"],
        env.controller,
    )
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_filter_calendar_long_no_reminder(env):
    """Tier4FilterCalendarLongNoReminder: agent lists meeting events >2h with no reminder."""
    task = tier4_calendar.Tier4FilterCalendarLongNoReminder({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted {len(task._ground_truth)} qualifying events + distractors")
    print("    2. execute: (agent outputs qualifying titles)")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_filter_calendar_long_no_reminder_wrong(env):
    """Tier4FilterCalendarLongNoReminder (wrong): agent includes events with reminders -> FAIL."""
    task = tier4_calendar.Tier4FilterCalendarLongNoReminder({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted events")
    print("    2. execute: (agent outputs wrong titles)")
    env.interaction_cache = "tier4cal_wrong_event"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_aggregation_calendar_total_duration(env):
    """Tier4AggregationCalendarTotalDuration: agent outputs total duration in minutes."""
    task = tier4_calendar.Tier4AggregationCalendarTotalDuration({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted events with total duration {task._ground_truth} min")
    print("    2. execute: (agent computes correct sum)")
    env.interaction_cache = str(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_aggregation_calendar_total_duration_wrong(env):
    """Tier4AggregationCalendarTotalDuration (wrong): agent outputs wrong number -> FAIL."""
    task = tier4_calendar.Tier4AggregationCalendarTotalDuration({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted events, ground truth={task._ground_truth}")
    print("    2. execute: (agent outputs very wrong number)")
    env.interaction_cache = "9999"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_dedup_calendar_events(env):
    """Tier4DedupCalendarDeleteDuplicateEvents: agent deletes all but one of each dup pair."""
    task = tier4_calendar.Tier4DedupCalendarDeleteDuplicateEvents({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted {len(task._dup_pairs)} dup pairs + {len(task._unique_event_ids)} unique events")
    print("    2. execute: query calendar, delete extras")
    for title, dtstart in task._dup_pairs:
        # Query IDs for this dup pair
        res = adb_utils.issue_generic_request(
            ["shell", "content", "query", "--uri", tier4_calendar._CALENDAR_EVENTS_URI,
             "--where", f"title='{title}' AND dtstart={dtstart}",
             "--projection", "_id"],
            env.controller,
        )
        ids = re.findall(r"_id=(\d+)", res.generic.output.decode())
        # Delete all but the first
        for eid in ids[1:]:
            adb_utils.issue_generic_request(
                ["shell", "content", "delete", "--uri", tier4_calendar._CALENDAR_EVENTS_URI,
                 "--where", f"_id={eid}"],
                env.controller,
            )
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_dedup_calendar_events_wrong(env):
    """Tier4DedupCalendarDeleteDuplicateEvents (wrong): agent deletes nothing -> FAIL."""
    task = tier4_calendar.Tier4DedupCalendarDeleteDuplicateEvents({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted dup pairs")
    print("    2. execute: (agent does nothing)")
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_topk_calendar_earliest(env):
    """Tier4TopKCalendarEarliestEvent: agent outputs earliest event title."""
    task = tier4_calendar.Tier4TopKCalendarEarliestEvent({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 5 historical events, earliest={task._ground_truth_title}")
    print("    2. execute: (agent outputs correct earliest title)")
    env.interaction_cache = task._ground_truth_title
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_topk_calendar_earliest_wrong(env):
    """Tier4TopKCalendarEarliestEvent (wrong): agent outputs wrong title -> FAIL."""
    task = tier4_calendar.Tier4TopKCalendarEarliestEvent({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted historical events")
    print("    2. execute: (agent outputs wrong title)")
    env.interaction_cache = "wrong_event_title"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_coverage_calendar_reminders(env):
    """Tier4CoverageCalendarEventsHaveReminders: agent lists events missing reminders."""
    task = tier4_calendar.Tier4CoverageCalendarEventsHaveReminders({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 3 events with reminders, {len(task._ground_truth)} without")
    print("    2. execute: (agent lists titles of events missing reminders)")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_coverage_calendar_reminders_wrong(env):
    """Tier4CoverageCalendarEventsHaveReminders (wrong): agent says all have reminders -> FAIL."""
    task = tier4_calendar.Tier4CoverageCalendarEventsHaveReminders({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted events")
    print("    2. execute: (agent says 'All events have reminders' incorrectly)")
    env.interaction_cache = "All events have reminders"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


# ── Phase 8: DB-based tasks ──────────────────────────────────────────────────

def _run_tier4_bulk_recategorize_expense(env):
    """Tier4BulkRecategorizeExpense: agent updates Food→Entertainment in DB."""
    task = tier4_expense.Tier4BulkRecategorizeExpense({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted 4 Food + 2 Housing expenses")
    print("    2. execute: UPDATE expense SET category=6 WHERE category=3")
    adb_utils.issue_generic_request(
        ['shell', 'sqlite3',
         '/data/data/com.arduia.expense/databases/accounting.db',
         'UPDATE expense SET category=6 WHERE category=3;'],
        env.controller,
    )
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_bulk_recategorize_expense_wrong(env):
    """Tier4BulkRecategorizeExpense (wrong): agent leaves Food expenses unchanged → FAIL."""
    task = tier4_expense.Tier4BulkRecategorizeExpense({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted 4 Food + 2 Housing expenses")
    print("    2. execute: (agent does nothing — Food expenses remain)")
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_filter_expense_high_travel(env):
    """Tier4FilterExpenseHighTravelLastMonth: agent lists 3 matching expense names."""
    task = tier4_expense.Tier4FilterExpenseHighTravelLastMonth({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted expenses; ground_truth={task._ground_truth}")
    print("    2. execute: (agent lists matching expense names)")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_filter_expense_high_travel_wrong(env):
    """Tier4FilterExpenseHighTravelLastMonth (wrong): agent lists wrong names → FAIL."""
    task = tier4_expense.Tier4FilterExpenseHighTravelLastMonth({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted expenses")
    print("    2. execute: (agent lists wrong expense names)")
    env.interaction_cache = "wrong_expense_0, wrong_expense_1"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_aggregation_expense_top3(env):
    """Tier4AggregationExpenseCategoryTop3: agent outputs Housing, Transportation, Food."""
    task = tier4_expense.Tier4AggregationExpenseCategoryTop3({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted expenses; top3={task._ground_truth}")
    env.interaction_cache = "Housing, Transportation, Food"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_aggregation_expense_top3_wrong(env):
    """Tier4AggregationExpenseCategoryTop3 (wrong): agent omits a category → FAIL."""
    task = tier4_expense.Tier4AggregationExpenseCategoryTop3({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted expenses")
    env.interaction_cache = "Housing, Transportation"  # Missing Food
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_dedup_expense_duplicates(env):
    """Tier4DedupExpenseSuspectedDuplicates: agent outputs count=3."""
    task = tier4_expense.Tier4DedupExpenseSuspectedDuplicates({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 3 dup pairs + 3 unique; ground_truth={task._ground_truth}")
    env.interaction_cache = str(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_dedup_expense_duplicates_wrong(env):
    """Tier4DedupExpenseSuspectedDuplicates (wrong): agent outputs wrong count → FAIL."""
    task = tier4_expense.Tier4DedupExpenseSuspectedDuplicates({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted duplicate expenses")
    env.interaction_cache = "Found 1 duplicate"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_topk_expense_highest(env):
    """Tier4TopKExpenseHighestAmount: agent lists top 5 expense names."""
    task = tier4_expense.Tier4TopKExpenseHighestAmount({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 10 expenses; top5={task._ground_truth}")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_topk_expense_highest_wrong(env):
    """Tier4TopKExpenseHighestAmount (wrong): agent lists wrong expenses → FAIL."""
    task = tier4_expense.Tier4TopKExpenseHighestAmount({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted 10 expenses")
    env.interaction_cache = "expense_amt_0, expense_amt_1, expense_amt_2"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_cross_app_expense_to_markor(env):
    """Tier4CrossAppExpenseToMarkorCalendar: agent writes note + calendar event."""
    task = tier4_expense.Tier4CrossAppExpenseToMarkorCalendar({})
    task.initialize_task(env)
    total = task._ground_truth_dollars
    print(f"    1. init:   ✓ inserted 5 expenses; total=${total}")
    # Create Markor note with total
    adb_utils.issue_generic_request(
        ['shell', 'mkdir', '-p', '/storage/emulated/0/Documents/Markor'],
        env.controller,
    )
    adb_utils.issue_generic_request(
        ['shell', 'sh', '-c',
         f'echo "Monthly total: ${total}" > {task._note_path}'],
        env.controller,
    )
    # Create calendar event via content provider
    adb_utils.issue_generic_request(
        ['shell', 'content', 'insert', '--uri',
         'content://com.android.calendar/events',
         '--bind', 'title:s:Monthly Expense: $' + total,
         '--bind', 'dtstart:l:1000000', '--bind', 'dtend:l:2000000',
         '--bind', 'calendar_id:l:1'],
        env.controller,
    )
    print(f"    2. execute: created Markor note + calendar event with ${total}")
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_cross_app_expense_to_markor_wrong(env):
    """Tier4CrossAppExpenseToMarkorCalendar (wrong): agent writes wrong total → FAIL."""
    task = tier4_expense.Tier4CrossAppExpenseToMarkorCalendar({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 5 expenses; total=${task._ground_truth_dollars}")
    # Create note with wrong amount
    adb_utils.issue_generic_request(
        ['shell', 'mkdir', '-p', '/storage/emulated/0/Documents/Markor'],
        env.controller,
    )
    adb_utils.issue_generic_request(
        ['shell', 'sh', '-c',
         f'echo "Monthly total: $99.99" > {task._note_path}'],
        env.controller,
    )
    print("    2. execute: (agent wrote wrong total $99.99 to note)")
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_bulk_change_priority_tasks(env):
    """Tier4BulkChangePriorityTasks: agent updates Low→Medium in DB."""
    task = tier4_tasks_app.Tier4BulkChangePriorityTasks({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 4 Low + 2 High tasks; low_titles={task._low_titles}")
    print("    2. execute: UPDATE tasks SET importance=2 WHERE importance=1")
    adb_utils.issue_generic_request(
        ['shell', 'sqlite3', '/data/data/org.tasks/databases/database',
         'UPDATE tasks SET importance=2 WHERE importance=1;'],
        env.controller,
    )
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_bulk_change_priority_tasks_wrong(env):
    """Tier4BulkChangePriorityTasks (wrong): agent leaves Low tasks unchanged → FAIL."""
    task = tier4_tasks_app.Tier4BulkChangePriorityTasks({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted 4 Low + 2 High tasks")
    print("    2. execute: (agent does nothing)")
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_coverage_overdue_tasks(env):
    """Tier4CoverageOverdueTasksCompleted: agent lists 2 overdue+pending titles."""
    task = tier4_tasks_app.Tier4CoverageOverdueTasksCompleted({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted overdue tasks; pending={task._ground_truth}")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_coverage_overdue_tasks_wrong(env):
    """Tier4CoverageOverdueTasksCompleted (wrong): agent says 'all completed' → FAIL."""
    task = tier4_tasks_app.Tier4CoverageOverdueTasksCompleted({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted overdue tasks with 2 pending")
    print("    2. execute: (agent incorrectly says all completed)")
    env.interaction_cache = "all completed"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_filter_joplin_contains_not_contains(env):
    """Tier4FilterJoplinContainsNotContains: agent lists notes with A but not B."""
    task = tier4_joplin.Tier4FilterJoplinContainsNotContains(
        {'keyword_a': 'project', 'keyword_b': 'urgent'})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 5 notes; ground_truth={task._ground_truth}")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_filter_joplin_contains_not_contains_wrong(env):
    """Tier4FilterJoplinContainsNotContains (wrong): agent lists wrong note → FAIL."""
    task = tier4_joplin.Tier4FilterJoplinContainsNotContains(
        {'keyword_a': 'project', 'keyword_b': 'urgent'})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted 5 notes")
    print("    2. execute: (agent lists a note that should be excluded)")
    env.interaction_cache = "note_a_and_b"  # Has both A and B → excluded
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_dedup_joplin_same_title(env):
    """Tier4DedupJoplinSameTitleNotes: agent lists duplicate note titles."""
    task = tier4_joplin.Tier4DedupJoplinSameTitleNotes({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 6 notes; dup_titles={task._ground_truth}")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_dedup_joplin_same_title_wrong(env):
    """Tier4DedupJoplinSameTitleNotes (wrong): agent lists unique title only → FAIL."""
    task = tier4_joplin.Tier4DedupJoplinSameTitleNotes({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted notes with duplicate titles")
    print("    2. execute: (agent lists a unique title instead of duplicates)")
    env.interaction_cache = "Shopping List"  # Unique, not a duplicate
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_aggregation_opentracks_weekly(env):
    """Tier4AggregationOpenTracksWeeklyStats: agent outputs total km + longest activity."""
    task = tier4_opentracks.Tier4AggregationOpenTracksWeeklyStats({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 4 activities; total={task._ground_truth_total_km} km")
    env.interaction_cache = (
        f"Total: {task._ground_truth_total_km} km, "
        f"longest: {task._ground_truth_longest}"
    )
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_aggregation_opentracks_weekly_wrong(env):
    """Tier4AggregationOpenTracksWeeklyStats (wrong): agent omits longest name → FAIL."""
    task = tier4_opentracks.Tier4AggregationOpenTracksWeeklyStats({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted 4 activities")
    print("    2. execute: (agent reports total but not longest activity)")
    env.interaction_cache = f"Total: {task._ground_truth_total_km} km"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_topk_opentracks_fastest(env):
    """Tier4TopKOpenTracksFastestActivity: agent names Sprint as fastest."""
    task = tier4_opentracks.Tier4TopKOpenTracksFastestActivity({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 5 activities; fastest={task._ground_truth}")
    env.interaction_cache = f"Fastest activity: {task._ground_truth} (5.0 m/s)"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_topk_opentracks_fastest_wrong(env):
    """Tier4TopKOpenTracksFastestActivity (wrong): agent names wrong activity → FAIL."""
    task = tier4_opentracks.Tier4TopKOpenTracksFastestActivity({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted 5 activities")
    print("    2. execute: (agent incorrectly names Bike Ride as fastest)")
    env.interaction_cache = "Fastest activity: Bike Ride"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_cross_app_opentracks_to_tasks(env):
    """Tier4CrossAppOpenTracksToTasks: agent creates Tasks entry for Marathon Prep."""
    from android_world.task_evals.utils import sqlite_utils, sqlite_schema_utils
    import uuid
    import time as _time

    task = tier4_opentracks.Tier4CrossAppOpenTracksToTasks({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 4 activities; longest={task._ground_truth_name}")
    # Simulate agent inserting a task with Marathon Prep + distance
    title = f"{task._ground_truth_name} {task._ground_truth_km} km"
    now = int(_time.time() * 1000)
    task_row = sqlite_schema_utils.Task(
        title=title, importance=0, dueDate=0, completed=0,
        created=now, modified=now, remoteId=uuid.uuid4().hex,
    )
    sqlite_utils.insert_rows_to_remote_db(
        [task_row], '_id', 'tasks',
        '/data/data/org.tasks/databases/database', 'tasks', env,
    )
    print(f"    2. execute: inserted task '{title}' into Tasks DB")
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_cross_app_opentracks_to_tasks_wrong(env):
    """Tier4CrossAppOpenTracksToTasks (wrong): agent creates task with wrong name → FAIL."""
    from android_world.task_evals.utils import sqlite_utils, sqlite_schema_utils
    import uuid
    import time as _time

    task = tier4_opentracks.Tier4CrossAppOpenTracksToTasks({})
    task.initialize_task(env)
    print("    1. init:   ✓ inserted 4 activities")
    # Simulate agent picking the wrong (shorter) activity
    now = int(_time.time() * 1000)
    task_row = sqlite_schema_utils.Task(
        title='Trail Run 8.0 km', importance=0, dueDate=0, completed=0,
        created=now, modified=now, remoteId=uuid.uuid4().hex,
    )
    sqlite_utils.insert_rows_to_remote_db(
        [task_row], '_id', 'tasks',
        '/data/data/org.tasks/databases/database', 'tasks', env,
    )
    print("    2. execute: (agent inserted wrong activity 'Trail Run 8.0 km')")
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_filter_retro_music_multi(env):
    """Tier4FilterRetroMusicMultiCondition: agent lists songs >4 min by artist."""
    task = tier4_retro_music.Tier4FilterRetroMusicMultiCondition({'artist': 'TestArtist'})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created MP3s; ground_truth={task._ground_truth}")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_filter_retro_music_multi_wrong(env):
    """Tier4FilterRetroMusicMultiCondition (wrong): agent lists short songs too → FAIL."""
    task = tier4_retro_music.Tier4FilterRetroMusicMultiCondition({'artist': 'TestArtist'})
    task.initialize_task(env)
    print("    1. init:   ✓ created MP3s")
    print("    2. execute: (agent lists songs that don't meet criteria)")
    env.interaction_cache = "tier4rm_short_TestArtist_0"
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_topk_retro_music_longest(env):
    """Tier4TopKRetroMusicLongestSongs: agent lists top 5 longest song titles."""
    task = tier4_retro_music.Tier4TopKRetroMusicLongestSongs({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ created 8 MP3s; top5={task._ground_truth}")
    env.interaction_cache = " ".join(task._ground_truth)
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_topk_retro_music_longest_wrong(env):
    """Tier4TopKRetroMusicLongestSongs (wrong): agent lists shortest songs → FAIL."""
    task = tier4_retro_music.Tier4TopKRetroMusicLongestSongs({})
    task.initialize_task(env)
    print("    1. init:   ✓ created 8 MP3s")
    print("    2. execute: (agent lists songs not in top 5)")
    env.interaction_cache = "tier4rm_song_0"  # shortest song
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL (expected)'}")
    return score


def _run_tier4_cross_app_broccoli_to_markor(env):
    """Tier4CrossAppBroccoliToMarkorIndex: agent writes recipe titles to Markor note."""
    task = tier4_broccoli.Tier4CrossAppBroccoliToMarkorIndex({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 5 recipes; titles={task._ground_truth}")
    # Create Markor note with all recipe titles as a bulleted list
    adb_utils.issue_generic_request(
        ['shell', 'mkdir', '-p', '/storage/emulated/0/Documents/Markor'],
        env.controller,
    )
    bullet_lines = "\\n".join(f"- {t}" for t in task._ground_truth)
    adb_utils.issue_generic_request(
        ['shell', 'sh', '-c',
         f'printf "{bullet_lines}" > {task._note_path}'],
        env.controller,
    )
    print("    2. execute: created recipes_index.md with all recipe titles")
    score = task.is_successful(env)
    task.tear_down(env)
    print(f"    3. result: score={score} {'✓ PASS' if score >= 1.0 else '✗ FAIL'}")
    return score


def _run_tier4_cross_app_broccoli_to_markor_wrong(env):
    """Tier4CrossAppBroccoliToMarkorIndex (wrong): agent omits a recipe → FAIL."""
    task = tier4_broccoli.Tier4CrossAppBroccoliToMarkorIndex({})
    task.initialize_task(env)
    print(f"    1. init:   ✓ inserted 5 recipes")
    # Write only first 2 recipes — missing the rest
    partial = task._ground_truth[:2]
    bullet_lines = "\\n".join(f"- {t}" for t in partial)
    adb_utils.issue_generic_request(
        ['shell', 'mkdir', '-p', '/storage/emulated/0/Documents/Markor'],
        env.controller,
    )
    adb_utils.issue_generic_request(
        ['shell', 'sh', '-c',
         f'printf "{bullet_lines}" > {task._note_path}'],
        env.controller,
    )
    print(f"    2. execute: (agent wrote only {partial} — missing others)")
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
    # Phase 1: Files
    ("Tier4BulkRenameScreenshots", _run_tier4_bulk_rename_screenshots, True),
    ("Tier4BulkRenameScreenshots (wrong)", _run_tier4_bulk_rename_screenshots_wrong, False),
    ("Tier4BulkMoveLargeFiles", _run_tier4_bulk_move_large_files, True),
    ("Tier4BulkMoveLargeFiles (wrong)", _run_tier4_bulk_move_large_files_wrong, False),
    ("Tier4FilterRecentLogFiles", _run_tier4_filter_recent_log_files, True),
    ("Tier4FilterRecentLogFiles (wrong)", _run_tier4_filter_recent_log_files_wrong, False),
    # Phase 2: SMS
    ("Tier4FilterDeleteOldNonContactKeywordSms", _run_tier4_filter_delete_old_sms, True),
    ("Tier4FilterDeleteOldNonContactKeywordSms (wrong)", _run_tier4_filter_delete_old_sms_wrong, False),
    ("Tier4TopKSmsThreadsByCount", _run_tier4_topk_sms_threads, True),
    ("Tier4TopKSmsThreadsByCount (wrong)", _run_tier4_topk_sms_threads_wrong, False),
    # Phase 2: Contacts
    ("Tier4CrossAppContactsNoRecentSms", _run_tier4_contacts_no_recent_sms, True),
    ("Tier4CrossAppContactsNoRecentSms (wrong)", _run_tier4_contacts_no_recent_sms_wrong, False),
    ("Tier4FilterContactsBirthdayNoPhone", _run_tier4_birthday_no_phone, True),
    ("Tier4FilterContactsBirthdayNoPhone (wrong)", _run_tier4_birthday_no_phone_wrong, False),
    ("Tier4AggregationLongestContactName", _run_tier4_longest_contact_name, True),
    ("Tier4AggregationLongestContactName (wrong)", _run_tier4_longest_contact_name_wrong, False),
    ("Tier4DedupContactsDuplicatePhones", _run_tier4_dedup_contacts_list, True),
    ("Tier4DedupContactsDuplicatePhones (wrong)", _run_tier4_dedup_contacts_list_wrong, False),
    ("Tier4DedupMergeContactsSamePhone", _run_tier4_dedup_merge_contacts, True),
    ("Tier4DedupMergeContactsSamePhone (wrong)", _run_tier4_dedup_merge_contacts_wrong, False),
    # Phase 1: Markor
    ("Tier4BulkAppendFooterToMarkdown", _run_tier4_bulk_append_footer, True),
    ("Tier4BulkAppendFooterToMarkdown (wrong)", _run_tier4_bulk_append_footer_wrong, False),
    ("Tier4AggregationLongestMarkorNote", _run_tier4_longest_markor_note, True),
    ("Tier4AggregationLongestMarkorNote (wrong)", _run_tier4_longest_markor_note_wrong, False),
    ("Tier4TopKMarkorMostModifiedNotes", _run_tier4_topk_markor_modified, True),
    ("Tier4TopKMarkorMostModifiedNotes (wrong)", _run_tier4_topk_markor_modified_wrong, False),
    # Phase 6: Cross-app non-DB
    ("Tier4CrossAppFilesCreatedDuringEvents", _run_tier4_files_during_events, True),
    ("Tier4CrossAppFilesCreatedDuringEvents (wrong)", _run_tier4_files_during_events_wrong, False),
    ("Tier4CrossAppMarkorPhonesVsContacts", _run_tier4_markor_phones_vs_contacts, True),
    ("Tier4CrossAppMarkorPhonesVsContacts (wrong)", _run_tier4_markor_phones_vs_contacts_wrong, False),
    # Phase 5: Files + SMS Coverage
    ("Tier4AggregationDownloadSizeTop3", _run_tier4_download_size_top3, True),
    ("Tier4AggregationDownloadSizeTop3 (wrong)", _run_tier4_download_size_top3_wrong, False),
    ("Tier4TopKLargestDownloadFiles", _run_tier4_topk_largest_downloads, True),
    ("Tier4TopKLargestDownloadFiles (wrong)", _run_tier4_topk_largest_downloads_wrong, False),
    ("Tier4CoverageAllSmsRead (has_unread)", _run_tier4_coverage_all_sms_read_has_unread, True),
    ("Tier4CoverageAllSmsRead (wrong)", _run_tier4_coverage_all_sms_read_wrong, False),
    # Phase 4: System/Settings
    ("Tier4HiddenStateLocationPermissions", _run_tier4_location_permissions, True),
    ("Tier4HiddenStateLocationPermissions (wrong)", _run_tier4_location_permissions_wrong, False),
    ("Tier4HiddenStateAudioRouting", _run_tier4_audio_routing, True),
    ("Tier4HiddenStateAudioRouting (wrong)", _run_tier4_audio_routing_wrong, False),
    ("Tier4CoverageAppsCameraPermission", _run_tier4_camera_permission, True),
    ("Tier4CoverageAppsCameraPermission (wrong)", _run_tier4_camera_permission_wrong, False),
    ("Tier4CoverageWifiConnected", _run_tier4_wifi_connected, True),
    ("Tier4CoverageWifiConnected (wrong)", _run_tier4_wifi_connected_wrong, False),
    # Phase 3: Calendar
    ("Tier4BulkDeleteCalendarTestEvents", _run_tier4_bulk_delete_calendar_events, True),
    ("Tier4BulkDeleteCalendarTestEvents (wrong)", _run_tier4_bulk_delete_calendar_events_wrong, False),
    ("Tier4CrossAppCalendarToMarkor", _run_tier4_cross_app_calendar_to_markor, True),
    ("Tier4CrossAppCalendarToMarkor (wrong)", _run_tier4_cross_app_calendar_to_markor_wrong, False),
    ("Tier4FilterCalendarLongNoReminder", _run_tier4_filter_calendar_long_no_reminder, True),
    ("Tier4FilterCalendarLongNoReminder (wrong)", _run_tier4_filter_calendar_long_no_reminder_wrong, False),
    ("Tier4AggregationCalendarTotalDuration", _run_tier4_aggregation_calendar_total_duration, True),
    ("Tier4AggregationCalendarTotalDuration (wrong)", _run_tier4_aggregation_calendar_total_duration_wrong, False),
    ("Tier4DedupCalendarDeleteDuplicateEvents", _run_tier4_dedup_calendar_events, True),
    ("Tier4DedupCalendarDeleteDuplicateEvents (wrong)", _run_tier4_dedup_calendar_events_wrong, False),
    ("Tier4TopKCalendarEarliestEvent", _run_tier4_topk_calendar_earliest, True),
    ("Tier4TopKCalendarEarliestEvent (wrong)", _run_tier4_topk_calendar_earliest_wrong, False),
    ("Tier4CoverageCalendarEventsHaveReminders", _run_tier4_coverage_calendar_reminders, True),
    ("Tier4CoverageCalendarEventsHaveReminders (wrong)", _run_tier4_coverage_calendar_reminders_wrong, False),
    # Phase 8: DB-based — Pro Expense
    ("Tier4BulkRecategorizeExpense", _run_tier4_bulk_recategorize_expense, True),
    ("Tier4BulkRecategorizeExpense (wrong)", _run_tier4_bulk_recategorize_expense_wrong, False),
    ("Tier4FilterExpenseHighTravelLastMonth", _run_tier4_filter_expense_high_travel, True),
    ("Tier4FilterExpenseHighTravelLastMonth (wrong)", _run_tier4_filter_expense_high_travel_wrong, False),
    ("Tier4AggregationExpenseCategoryTop3", _run_tier4_aggregation_expense_top3, True),
    ("Tier4AggregationExpenseCategoryTop3 (wrong)", _run_tier4_aggregation_expense_top3_wrong, False),
    ("Tier4DedupExpenseSuspectedDuplicates", _run_tier4_dedup_expense_duplicates, True),
    ("Tier4DedupExpenseSuspectedDuplicates (wrong)", _run_tier4_dedup_expense_duplicates_wrong, False),
    ("Tier4TopKExpenseHighestAmount", _run_tier4_topk_expense_highest, True),
    ("Tier4TopKExpenseHighestAmount (wrong)", _run_tier4_topk_expense_highest_wrong, False),
    ("Tier4CrossAppExpenseToMarkorCalendar", _run_tier4_cross_app_expense_to_markor, True),
    ("Tier4CrossAppExpenseToMarkorCalendar (wrong)", _run_tier4_cross_app_expense_to_markor_wrong, False),
    # Phase 8: DB-based — Tasks.org
    ("Tier4BulkChangePriorityTasks", _run_tier4_bulk_change_priority_tasks, True),
    ("Tier4BulkChangePriorityTasks (wrong)", _run_tier4_bulk_change_priority_tasks_wrong, False),
    ("Tier4CoverageOverdueTasksCompleted", _run_tier4_coverage_overdue_tasks, True),
    ("Tier4CoverageOverdueTasksCompleted (wrong)", _run_tier4_coverage_overdue_tasks_wrong, False),
    # Phase 8: DB-based — Joplin
    ("Tier4FilterJoplinContainsNotContains", _run_tier4_filter_joplin_contains_not_contains, True),
    ("Tier4FilterJoplinContainsNotContains (wrong)", _run_tier4_filter_joplin_contains_not_contains_wrong, False),
    ("Tier4DedupJoplinSameTitleNotes", _run_tier4_dedup_joplin_same_title, True),
    ("Tier4DedupJoplinSameTitleNotes (wrong)", _run_tier4_dedup_joplin_same_title_wrong, False),
    # Phase 8: DB-based — OpenTracks
    ("Tier4AggregationOpenTracksWeeklyStats", _run_tier4_aggregation_opentracks_weekly, True),
    ("Tier4AggregationOpenTracksWeeklyStats (wrong)", _run_tier4_aggregation_opentracks_weekly_wrong, False),
    ("Tier4TopKOpenTracksFastestActivity", _run_tier4_topk_opentracks_fastest, True),
    ("Tier4TopKOpenTracksFastestActivity (wrong)", _run_tier4_topk_opentracks_fastest_wrong, False),
    ("Tier4CrossAppOpenTracksToTasks", _run_tier4_cross_app_opentracks_to_tasks, True),
    ("Tier4CrossAppOpenTracksToTasks (wrong)", _run_tier4_cross_app_opentracks_to_tasks_wrong, False),
    # Phase 8: DB-based — Retro Music
    ("Tier4FilterRetroMusicMultiCondition", _run_tier4_filter_retro_music_multi, True),
    ("Tier4FilterRetroMusicMultiCondition (wrong)", _run_tier4_filter_retro_music_multi_wrong, False),
    ("Tier4TopKRetroMusicLongestSongs", _run_tier4_topk_retro_music_longest, True),
    ("Tier4TopKRetroMusicLongestSongs (wrong)", _run_tier4_topk_retro_music_longest_wrong, False),
    # Phase 8: DB-based — Broccoli
    ("Tier4CrossAppBroccoliToMarkorIndex", _run_tier4_cross_app_broccoli_to_markor, True),
    ("Tier4CrossAppBroccoliToMarkorIndex (wrong)", _run_tier4_cross_app_broccoli_to_markor_wrong, False),
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
