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


# ── tier4_extra ──────────────────────────────────────────────────────────

_SMS_INBOX_URI = "content://sms/inbox"
_CONTACTS_PHONES_URI = "content://contacts/phones/"
_RAW_CONTACTS_URI = "content://com.android.contacts/raw_contacts"
_CONTACTS_DATA_URI = "content://com.android.contacts/data"


class Tier4ExtraCrossAppContactsToMarkor(task_eval.TaskEval):
  """Export all contact names and phone numbers to a Markor note. ADB-exclusive (cross-app)."""

  app_names = ("contacts", "markor")
  complexity = 2.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Export all contacts (name and phone number) to a Markor note named"
      " 'contacts_export.md'. Write one contact per line in the format:"
      " 'Name: phone_number'."
  )

  _NOTE_NAME = "contacts_export.md"

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    adb_utils.delete_contacts(env.controller)
    import time
    time.sleep(2)
    self._contacts: list[tuple[str, str]] = [
        ("Alice Smith", "+15550001001"),
        ("Bob Jones", "+15550001002"),
        ("Carol Lee", "+15550001003"),
    ]
    for name, phone in self._contacts:
      contacts_utils.add_contact(name, phone, env.controller)
      time.sleep(0.5)
    self._note_path = f"{_MARKOR_DIR}/{self._NOTE_NAME}"

  def tear_down(self, env: interface.AsyncEnv) -> None:
    adb_utils.delete_contacts(env.controller)
    adb_utils.issue_generic_request(
        ["shell", "rm", "-f", self._note_path], env.controller
    )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    res = adb_utils.issue_generic_request(
        ["shell", "cat", self._note_path], env.controller
    )
    content = res.generic.output.decode()
    for name, _ in self._contacts:
      if name not in content:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraCrossAppCalendarSmsConflicts(task_eval.TaskEval):
  """List SMS received during calendar events. ADB-exclusive (time-range join)."""

  app_names = ("simple calendar pro", "simple sms messenger")
  complexity = 2.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all SMS messages that were received during an active calendar"
      " event (i.e., the SMS timestamp falls within the event's start-end"
      " window). Output the sender phone numbers."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_xa_events(env)
    from android_world.task_evals.common_validators import sms_validators
    sms_validators.clear_sms_and_threads(env.controller)
    import time
    time.sleep(2)

    now_ms = int(time.time() * 1000)
    # Event: 2 hours ago → 1 hour ago
    ev_start = now_ms - 2 * 3600000
    ev_end = now_ms - 1 * 3600000
    _insert_cal_event(f"{_CALENDAR_CLEANUP_PREFIX}smsev",
                      ev_start, ev_end, env)

    self._ground_truth: list[str] = []
    from android_world.task_evals.utils import user_data_generation

    # SMS during event (90 min ago)
    for i in range(2):
      num = user_data_generation.generate_random_number()
      sms_time = now_ms - 90 * 60 * 1000 + i * 60000
      adb_utils.issue_generic_request(
          ["shell", "content", "insert", "--uri", _SMS_INBOX_URI,
           "--bind", f"address:s:{num}",
           "--bind", f"body:s:msg during event {i}",
           "--bind", f"date:l:{sms_time}",
           "--bind", "read:i:1", "--bind", "type:i:1"],
          env.controller,
      )
      self._ground_truth.append(num.replace("-", "").replace(" ", ""))

    # SMS outside event (30 min ago)
    num_outside = user_data_generation.generate_random_number()
    adb_utils.issue_generic_request(
        ["shell", "content", "insert", "--uri", _SMS_INBOX_URI,
         "--bind", f"address:s:{num_outside}",
         "--bind", "body:s:msg outside event",
         "--bind", f"date:l:{now_ms - 30 * 60000}",
         "--bind", "read:i:1", "--bind", "type:i:1"],
        env.controller,
    )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_xa_events(env)
    from android_world.task_evals.common_validators import sms_validators
    sms_validators.clear_sms_and_threads(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = (getattr(env, "interaction_cache", "") or "")
    cache_clean = cache.replace("-", "").replace(" ", "")
    for num in self._ground_truth:
      if num not in cache_clean:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraCrossAppExpenseVsCalendar(task_eval.TaskEval):
  """Match expenses to calendar event dates and list events with spending. ADB-exclusive."""

  app_names = ("pro expense", "simple calendar pro")
  complexity = 2.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "For each calendar event this week, check if any expenses in Pro Expense"
      " were recorded on the same day. List the event titles that have"
      " associated expenses."
  )

  _EXPENSE_DB_PATH = '/data/data/com.arduia.expense/databases/accounting.db'
  _EXPENSE_TABLE = 'expense'
  _EXPENSE_APP = 'pro expense'

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_xa_events(env)
    from android_world.task_evals.utils import sqlite_utils
    from android_world.task_evals.utils import sqlite_schema_utils
    sqlite_utils.delete_all_rows_from_table(
        self._EXPENSE_TABLE, self._EXPENSE_DB_PATH, env, self._EXPENSE_APP
    )
    import datetime
    now = datetime.datetime.utcnow()
    now_ms = int(now.timestamp() * 1000)

    self._ground_truth: list[str] = []

    # Event A: today → has expense on same day → should appear
    ev_a_title = f"{_CALENDAR_CLEANUP_PREFIX}today_meeting"
    _insert_cal_event(ev_a_title, now_ms, now_ms + 3600000, env)
    sqlite_utils.insert_rows_to_remote_db(
        [sqlite_schema_utils.Expense(
            name='today_lunch', amount=1500, category=3,
            created_date=now_ms, modified_date=now_ms,
        )],
        'expense_id', self._EXPENSE_TABLE, self._EXPENSE_DB_PATH,
        self._EXPENSE_APP, env,
    )
    self._ground_truth.append(ev_a_title)

    # Event B: yesterday → has expense → should appear
    yesterday_ms = now_ms - 86400000
    ev_b_title = f"{_CALENDAR_CLEANUP_PREFIX}yesterday_review"
    _insert_cal_event(ev_b_title, yesterday_ms, yesterday_ms + 3600000, env)
    sqlite_utils.insert_rows_to_remote_db(
        [sqlite_schema_utils.Expense(
            name='yesterday_coffee', amount=500, category=3,
            created_date=yesterday_ms, modified_date=yesterday_ms,
        )],
        'expense_id', self._EXPENSE_TABLE, self._EXPENSE_DB_PATH,
        self._EXPENSE_APP, env,
    )
    self._ground_truth.append(ev_b_title)

    # Event C: 2 days ago → no expense → should NOT appear
    two_days_ms = now_ms - 2 * 86400000
    _insert_cal_event(f"{_CALENDAR_CLEANUP_PREFIX}twodays_standup",
                      two_days_ms, two_days_ms + 3600000, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_xa_events(env)
    from android_world.task_evals.utils import sqlite_utils
    sqlite_utils.delete_all_rows_from_table(
        self._EXPENSE_TABLE, self._EXPENSE_DB_PATH, env, self._EXPENSE_APP
    )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    for title in self._ground_truth:
      if title not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraCrossAppSmsKeywordToTasks(task_eval.TaskEval):
  """Find SMS containing 'urgent', create a task for each. ADB-exclusive (cross-app)."""

  app_names = ("simple sms messenger", "tasks")
  complexity = 2.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Find all SMS messages in the inbox that contain the word 'urgent' and"
      " create a task in the Tasks app for each one, using the SMS body as the"
      " task title."
  )

  _TASKS_DB_PATH = '/data/data/org.tasks/databases/database'
  _TASKS_TABLE = 'tasks'
  _TASKS_APP = 'tasks'

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    from android_world.task_evals.common_validators import sms_validators
    sms_validators.clear_sms_and_threads(env.controller)
    from android_world.task_evals.utils import sqlite_utils
    sqlite_utils.delete_all_rows_from_table(
        self._TASKS_TABLE, self._TASKS_DB_PATH, env, self._TASKS_APP
    )
    import time
    time.sleep(2)

    now_ms = int(time.time() * 1000)
    from android_world.task_evals.utils import user_data_generation

    self._urgent_bodies: list[str] = [
        "urgent: server down, check immediately",
        "urgent review needed for PR #42",
    ]
    for body in self._urgent_bodies:
      num = user_data_generation.generate_random_number()
      adb_utils.issue_generic_request(
          ["shell", "content", "insert", "--uri", _SMS_INBOX_URI,
           "--bind", f"address:s:{num}",
           "--bind", f"body:s:{body}",
           "--bind", f"date:l:{now_ms}",
           "--bind", "read:i:1", "--bind", "type:i:1"],
          env.controller,
      )
      now_ms -= 60000

    # Non-urgent SMS (noise)
    num = user_data_generation.generate_random_number()
    adb_utils.issue_generic_request(
        ["shell", "content", "insert", "--uri", _SMS_INBOX_URI,
         "--bind", f"address:s:{num}",
         "--bind", "body:s:just a normal message",
         "--bind", f"date:l:{now_ms}",
         "--bind", "read:i:1", "--bind", "type:i:1"],
        env.controller,
    )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    from android_world.task_evals.common_validators import sms_validators
    sms_validators.clear_sms_and_threads(env.controller)
    from android_world.task_evals.utils import sqlite_utils
    sqlite_utils.delete_all_rows_from_table(
        self._TASKS_TABLE, self._TASKS_DB_PATH, env, self._TASKS_APP
    )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    from android_world.task_evals.utils import sqlite_utils
    from android_world.task_evals.utils import sqlite_schema_utils
    try:
      tasks = sqlite_utils.get_rows_from_remote_device(
          self._TASKS_TABLE, self._TASKS_DB_PATH,
          sqlite_schema_utils.Task, env,
      )
    except Exception:
      return 0.0
    task_titles = [t.title or '' for t in tasks]
    for body in self._urgent_bodies:
      found = any(body in title or 'urgent' in title.lower()
                  for title in task_titles)
      if not found:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraCrossAppOpenTracksToMarkor(task_eval.TaskEval):
  """Write weekly running stats from OpenTracks to a Markor note. ADB-exclusive."""

  app_names = ("activity tracker", "markor")
  complexity = 2.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Summarize this week's activities from OpenTracks (total distance in km"
      " and number of activities) and write the summary to a Markor note named"
      " 'weekly_stats.md'."
  )

  _OPENTRACKS_DB = '/data/data/de.dennisguse.opentracks/databases/database.db'
  _OPENTRACKS_TABLE = 'tracks'
  _OPENTRACKS_APP = 'activity tracker'
  _NOTE_NAME = 'weekly_stats.md'

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    from android_world.task_evals.utils import sqlite_utils
    from android_world.task_evals.utils import sqlite_schema_utils
    import uuid, datetime
    sqlite_utils.delete_all_rows_from_table(
        self._OPENTRACKS_TABLE, self._OPENTRACKS_DB, env, self._OPENTRACKS_APP
    )
    now = datetime.datetime.utcnow()
    monday = now - datetime.timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_ms = int(monday.timestamp() * 1000)

    configs = [
        ('Morning Run', 5000),
        ('Evening Jog', 3200),
        ('Long Run', 12000),
    ]
    rows = []
    for i, (name, dist_m) in enumerate(configs):
      starttime = week_start_ms + i * 86400000 + 3600000
      rows.append(sqlite_schema_utils.SportsActivity(
          name=name, category='running', activity_type='running',
          totaldistance=dist_m, totaltime=3600000, movingtime=3600000,
          starttime=starttime, stoptime=starttime + 3600000,
          avgspeed=dist_m / 3600, avgmovingspeed=dist_m / 3600,
          uuid=uuid.uuid4().bytes,
      ))
    sqlite_utils.insert_rows_to_remote_db(
        rows, '_id', self._OPENTRACKS_TABLE, self._OPENTRACKS_DB,
        self._OPENTRACKS_APP, env,
    )
    self._ground_truth_count: int = 3
    self._ground_truth_km: float = sum(d for _, d in configs) / 1000.0
    self._note_path = f"{_MARKOR_DIR}/{self._NOTE_NAME}"

  def tear_down(self, env: interface.AsyncEnv) -> None:
    from android_world.task_evals.utils import sqlite_utils
    sqlite_utils.delete_all_rows_from_table(
        self._OPENTRACKS_TABLE, self._OPENTRACKS_DB, env, self._OPENTRACKS_APP
    )
    adb_utils.issue_generic_request(
        ["shell", "rm", "-f", self._note_path], env.controller
    )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    res = adb_utils.issue_generic_request(
        ["shell", "cat", self._note_path], env.controller
    )
    content = res.generic.output.decode()
    if str(self._ground_truth_count) not in content:
      return 0.0
    # Check total distance with tolerance
    import re
    numbers = re.findall(r'\b\d+\.?\d*\b', content)
    for n in numbers:
      if abs(float(n) - self._ground_truth_km) <= 0.5:
        return 1.0
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraCrossAppJoplinToCalendar(task_eval.TaskEval):
  """Find Joplin notes with 'TODO' and create calendar events for them. ADB-exclusive."""

  app_names = ("joplin", "simple calendar pro")
  complexity = 2.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Find all Joplin notes whose body contains 'TODO'. For each such note,"
      " create a calendar event in Simple Calendar Pro with the note title as"
      " the event title, scheduled for tomorrow at 9 AM."
  )

  _JOPLIN_DB = '/data/data/net.cozic.joplin/databases/joplin.sqlite'
  _JOPLIN_TABLE = 'notes'
  _JOPLIN_APP = 'joplin'

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_xa_events(env)
    from android_world.task_evals.utils import sqlite_utils
    from android_world.task_evals.utils import sqlite_schema_utils
    sqlite_utils.delete_all_rows_from_table(
        self._JOPLIN_TABLE, self._JOPLIN_DB, env, self._JOPLIN_APP
    )
    import time
    now_ms = int(time.time() * 1000)

    self._todo_titles: list[str] = []
    # Notes WITH TODO → should create events
    for i in range(2):
      title = f"tier4xa_todo_note_{i}"
      note = sqlite_schema_utils.JoplinNote(
          id=f'todo{i:032d}',
          title=title,
          body=f'Some content\nTODO: finish task {i}\nMore content',
          created_time=now_ms,
          updated_time=now_ms,
          is_todo=0,
          parent_id='',
      )
      sqlite_utils.insert_rows_to_remote_db(
          [note], 'id', self._JOPLIN_TABLE, self._JOPLIN_DB,
          self._JOPLIN_APP, env,
      )
      self._todo_titles.append(title)

    # Notes WITHOUT TODO
    for i in range(2):
      note = sqlite_schema_utils.JoplinNote(
          id=f'noto{i:032d}',
          title=f'tier4xa_regular_note_{i}',
          body=f'Just normal content without the keyword',
          created_time=now_ms,
          updated_time=now_ms,
          is_todo=0,
          parent_id='',
      )
      sqlite_utils.insert_rows_to_remote_db(
          [note], 'id', self._JOPLIN_TABLE, self._JOPLIN_DB,
          self._JOPLIN_APP, env,
      )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_xa_events(env)
    from android_world.task_evals.utils import sqlite_utils
    sqlite_utils.delete_all_rows_from_table(
        self._JOPLIN_TABLE, self._JOPLIN_DB, env, self._JOPLIN_APP
    )
    # Also clean calendar events created by agent
    import re
    for title in self._todo_titles:
      adb_utils.issue_generic_request(
          ["shell", "content", "delete", "--uri", _CALENDAR_EVENTS_URI,
           "--where", f"title='{title}'"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    import re
    res = adb_utils.issue_generic_request(
        ["shell", "content", "query", "--uri", _CALENDAR_EVENTS_URI,
         "--projection", "title"],
        env.controller,
    )
    cal_output = res.generic.output.decode()
    for title in self._todo_titles:
      if title not in cal_output:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
