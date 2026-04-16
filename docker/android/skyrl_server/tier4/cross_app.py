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
# limitations under the License.

"""Tier 4 cross-app tasks (non-DB) - ADB-exclusive."""

import random
import re
import time
from typing import Any

from android_world.env import adb_utils
from android_world.env import device_constants
from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.utils import contacts_utils
from android_world.utils import file_utils

_CALENDAR_EVENTS_URI = "content://com.android.calendar/events"
_CALENDAR_CLEANUP_PREFIX = "tier4xa_"
_MARKOR_DIR = "/storage/emulated/0/Documents/Markor"


# ── Calendar helpers (local copies to avoid circular import) ────────────

def _insert_cal_event(title: str, dtstart_ms: int, dtend_ms: int,
                      env: interface.AsyncEnv) -> str:
  adb_utils.issue_generic_request(
      ["shell", "content", "insert", "--uri", _CALENDAR_EVENTS_URI,
       "--bind", f"title:s:{title}",
       "--bind", f"dtstart:l:{dtstart_ms}",
       "--bind", f"dtend:l:{dtend_ms}",
       "--bind", "calendar_id:i:1",
       "--bind", "eventTimezone:s:UTC"],
      env.controller,
  )
  res = adb_utils.issue_generic_request(
      ["shell", "content", "query", "--uri", _CALENDAR_EVENTS_URI,
       "--projection", "_id", "--sort", "_id DESC"],
      env.controller,
  )
  m = re.search(r"Row: 0 _id=(\d+)", res.generic.output.decode())
  return m.group(1) if m else ""


def _delete_xa_events(env: interface.AsyncEnv) -> None:
  adb_utils.issue_generic_request(
      ["shell", "content", "delete", "--uri", _CALENDAR_EVENTS_URI,
       "--where", f"title LIKE '{_CALENDAR_CLEANUP_PREFIX}%'"],
      env.controller,
  )


# ── Task classes ────────────────────────────────────────────────────────

class Tier4CrossAppFilesCreatedDuringEvents(task_eval.TaskEval):
  """List Downloads files whose mtime falls within a calendar event window. ADB-exclusive."""

  app_names = ("files", "simple calendar pro")
  complexity = 2.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all files in the Downloads folder whose last-modified time falls"
      " within any calendar event time window. Output the filenames."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_xa_events(env)
    now_s = int(time.time())
    now_ms = now_s * 1000

    # Event window A: 2 hours ago → 1 hour ago
    a_start_ms = now_ms - 2 * 3600 * 1000
    a_end_ms   = now_ms - 1 * 3600 * 1000
    _insert_cal_event(f"{_CALENDAR_CLEANUP_PREFIX}event_A",
                      a_start_ms, a_end_ms, env)

    # Event window B: 4 hours ago → 3 hours ago
    b_start_ms = now_ms - 4 * 3600 * 1000
    b_end_ms   = now_ms - 3 * 3600 * 1000
    _insert_cal_event(f"{_CALENDAR_CLEANUP_PREFIX}event_B",
                      b_start_ms, b_end_ms, env)

    self._ground_truth: list[str] = []
    self._all_files: list[str] = []

    # Files INSIDE window A (mtime = 90 min ago)
    for i in range(2):
      name = f"tier4xa_inA_{i}.bin"
      file_utils.create_file(name, device_constants.DOWNLOAD_DATA,
                             env.controller, content="x")
      ts_90min_ago = now_s - 90 * 60
      touch_ts = _epoch_to_touch(ts_90min_ago)
      adb_utils.issue_generic_request(
          ["shell", "touch", "-t", touch_ts,
           f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
      self._ground_truth.append(name)
      self._all_files.append(name)

    # Files INSIDE window B (mtime = 210 min ago)
    for i in range(2):
      name = f"tier4xa_inB_{i}.bin"
      file_utils.create_file(name, device_constants.DOWNLOAD_DATA,
                             env.controller, content="x")
      ts_210min_ago = now_s - 210 * 60
      touch_ts = _epoch_to_touch(ts_210min_ago)
      adb_utils.issue_generic_request(
          ["shell", "touch", "-t", touch_ts,
           f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
      self._ground_truth.append(name)
      self._all_files.append(name)

    # Files OUTSIDE any window (mtime = 30 min ago, 5 hours ago)
    for offset_min, label in [(30, "recent"), (300, "old")]:
      name = f"tier4xa_out_{label}.bin"
      file_utils.create_file(name, device_constants.DOWNLOAD_DATA,
                             env.controller, content="x")
      touch_ts = _epoch_to_touch(now_s - offset_min * 60)
      adb_utils.issue_generic_request(
          ["shell", "touch", "-t", touch_ts,
           f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
      self._all_files.append(name)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_xa_events(env)
    for name in self._all_files:
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth:
      return 0.0
    cache = (getattr(env, "interaction_cache", "") or "")
    for name in self._ground_truth:
      if name not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4CrossAppMarkorPhonesVsContacts(task_eval.TaskEval):
  """Extract phone numbers from Markor notes; list those NOT in contacts. ADB-exclusive."""

  app_names = ("markor", "contacts")
  complexity = 2.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Extract all phone numbers mentioned in Markor notes, then list the"
      " ones that are NOT in your contacts. Output the numbers."
  )

  _NOTE_PREFIX = "tier4xa_phones"

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    # Phone numbers: 2 in contacts, 2 not in contacts
    contact_nums = ["+15550001001", "+15550001002"]
    non_contact_nums = ["+15550009901", "+15550009902"]
    self._ground_truth: list[str] = list(non_contact_nums)
    self._note_names: list[str] = []

    # Add contacts
    adb_utils.delete_contacts(env.controller)
    for i, num in enumerate(contact_nums):
      contacts_utils.add_contact(f"ContactXA{i}", num, env.controller)

    # Create Markor note containing all 4 numbers
    note_name = f"{self._NOTE_PREFIX}_note.md"
    all_nums = contact_nums + non_contact_nums
    random.shuffle(all_nums)
    note_content = (
        "Phone directory:\n" +
        "\n".join(f"- {n}" for n in all_nums) +
        "\n"
    )
    file_utils.create_file(note_name, _MARKOR_DIR, env.controller,
                           content=note_content)
    self._note_names.append(note_name)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    for name in self._note_names:
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{_MARKOR_DIR}/{name}"], env.controller
      )
    adb_utils.delete_contacts(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth:
      return 0.0
    cache = (getattr(env, "interaction_cache", "") or "")
    cache_clean = cache.replace("-", "").replace(" ", "").replace("+", "")
    for num in self._ground_truth:
      norm = num.replace("-", "").replace(" ", "").replace("+", "")
      if norm not in cache_clean:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


def _epoch_to_touch(epoch_s: int) -> str:
  """Convert epoch seconds to touch -t format: [[CC]YY]MMDDhhmm[.SS]"""
  import datetime
  dt = datetime.datetime.utcfromtimestamp(epoch_s)
  return dt.strftime("%Y%m%d%H%M.%S")
