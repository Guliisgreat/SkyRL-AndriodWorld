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

"""Tier 4 tasks for Simple Calendar Pro - ADB-exclusive."""

import datetime
import re
import random
import time
from typing import Any

from android_world.env import adb_utils
from android_world.env import interface
from android_world.task_evals import task_eval

_CALENDAR_EVENTS_URI = "content://com.android.calendar/events"
_CALENDAR_REMINDERS_URI = "content://com.android.calendar/reminders"
_MARKOR_DIR = "/storage/emulated/0/Documents/Markor"
_CLEANUP_PREFIX = "tier4cal_"


# ── Calendar helpers ───────────────────────────────────────────────────

def _insert_event(
    title: str,
    dtstart_ms: int,
    dtend_ms: int,
    env: interface.AsyncEnv,
    calendar_id: int = 1,
) -> str:
  """Insert a calendar event and return its _id string."""
  adb_utils.issue_generic_request(
      ["shell", "content", "insert", "--uri", _CALENDAR_EVENTS_URI,
       "--bind", f"title:s:{title}",
       "--bind", f"dtstart:l:{dtstart_ms}",
       "--bind", f"dtend:l:{dtend_ms}",
       "--bind", f"calendar_id:i:{calendar_id}",
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


def _insert_reminder(event_id: str, minutes: int, env: interface.AsyncEnv) -> None:
  """Add a reminder alert to a calendar event."""
  adb_utils.issue_generic_request(
      ["shell", "content", "insert", "--uri", _CALENDAR_REMINDERS_URI,
       "--bind", f"event_id:l:{event_id}",
       "--bind", f"minutes:i:{minutes}",
       "--bind", "method:i:1"],
      env.controller,
  )


def _delete_tier4_events(env: interface.AsyncEnv) -> None:
  """Delete all events created by tier4 calendar tasks (by title prefix)."""
  adb_utils.issue_generic_request(
      ["shell", "content", "delete", "--uri", _CALENDAR_EVENTS_URI,
       "--where", f"title LIKE '{_CLEANUP_PREFIX}%'"],
      env.controller,
  )


def _ms(dt: datetime.datetime) -> int:
  """Convert a UTC datetime to milliseconds since epoch."""
  return int(dt.timestamp() * 1000)


def _month_start_ms() -> int:
  """Return the start of the current UTC month in ms."""
  now = datetime.datetime.utcnow()
  return _ms(datetime.datetime(now.year, now.month, 1))


# ── Task classes ───────────────────────────────────────────────────────

class Tier4BulkDeleteCalendarTestEvents(task_eval.TaskEval):
  """Delete all calendar events with 'test' in title. ADB-exclusive."""

  app_names = ("simple calendar pro",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Delete all events in Simple Calendar Pro whose title contains the word"
      " 'test' (case-insensitive)."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    now_ms = int(time.time() * 1000)
    # 3-5 events with "test" in title
    self._test_event_ids: list[str] = []
    for i in range(random.randint(3, 5)):
      title = f"{_CLEANUP_PREFIX}test_event_{i}"
      eid = _insert_event(title, now_ms + i * 3600000, now_ms + (i + 1) * 3600000, env)
      self._test_event_ids.append(eid)
    # 2 events without "test" in title
    self._keep_event_ids: list[str] = []
    for i in range(2):
      title = f"{_CLEANUP_PREFIX}regular_event_{i}"
      eid = _insert_event(title, now_ms + (i + 10) * 3600000, now_ms + (i + 11) * 3600000, env)
      self._keep_event_ids.append(eid)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    res = adb_utils.issue_generic_request(
        ["shell", "content", "query", "--uri", _CALENDAR_EVENTS_URI,
         "--projection", "_id"],
        env.controller,
    )
    existing_ids = set(re.findall(r"_id=(\d+)", res.generic.output.decode()))
    for eid in self._test_event_ids:
      if eid in existing_ids:
        return 0.0
    for eid in self._keep_event_ids:
      if eid not in existing_ids:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4CrossAppCalendarToMarkor(task_eval.TaskEval):
  """Find calendar events with keyword, write to Markor note. ADB-exclusive."""

  app_names = ("simple calendar pro", "markor")
  complexity = 2.0
  schema = {
      "type": "object",
      "properties": {"keyword": {"type": "string"}},
      "required": ["keyword"],
  }
  template = (
      "Find all events in Simple Calendar Pro whose title contains '{keyword}'."
      " Create a Markor note named '{keyword}_events.md' listing the event"
      " titles and dates (one per line)."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    keyword = self.params.get("keyword", "meeting")
    self._keyword = keyword
    now_ms = int(time.time() * 1000)
    # 3 events matching keyword
    self._ground_truth: list[str] = []
    for i in range(3):
      title = f"{_CLEANUP_PREFIX}{keyword}_item_{i}"
      _insert_event(title, now_ms + i * 86400000, now_ms + i * 86400000 + 3600000, env)
      self._ground_truth.append(title)
    # 2 events not matching
    for i in range(2):
      _insert_event(f"{_CLEANUP_PREFIX}other_event_{i}",
                    now_ms + (i + 5) * 86400000,
                    now_ms + (i + 5) * 86400000 + 3600000, env)
    self._note_path = f"{_MARKOR_DIR}/{keyword}_events.md"

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
    adb_utils.issue_generic_request(
        ["shell", "rm", "-f", self._note_path], env.controller
    )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    res = adb_utils.issue_generic_request(
        ["shell", "find", _MARKOR_DIR, "-name",
         f"{self._keyword}_events.md"],
        env.controller,
    )
    if not res.generic.output.decode().strip():
      return 0.0
    res = adb_utils.issue_generic_request(
        ["shell", "cat", self._note_path], env.controller
    )
    content = res.generic.output.decode()
    for title in self._ground_truth:
      if title not in content:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {"keyword": random.choice(["meeting", "review", "standup", "sync"])}


class Tier4FilterCalendarLongNoReminder(task_eval.TaskEval):
  """List 'meeting' events >2h with no reminder. ADB-exclusive."""

  app_names = ("simple calendar pro",)
  complexity = 2.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all calendar events that have no reminder set, last more than 2"
      " hours, and contain 'meeting' in the title. Output the event titles."
  )

  _TWO_HOURS_MS = 2 * 3600 * 1000

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    base_ms = int(time.time() * 1000) + 3600000
    self._ground_truth: list[str] = []

    # 2 events: meeting + >2h + NO reminder → should appear
    for i in range(2):
      title = f"{_CLEANUP_PREFIX}meeting_long_noreminder_{i}"
      dtstart = base_ms + i * 86400000
      _insert_event(title, dtstart, dtstart + self._TWO_HOURS_MS + 600000, env)
      self._ground_truth.append(title)

    # 2 events: meeting + >2h + HAS reminder → should not appear
    for i in range(2):
      title = f"{_CLEANUP_PREFIX}meeting_long_reminder_{i}"
      dtstart = base_ms + (i + 3) * 86400000
      eid = _insert_event(title, dtstart, dtstart + self._TWO_HOURS_MS + 600000, env)
      _insert_reminder(eid, 15, env)

    # 1 event: meeting + <2h + no reminder → too short
    title = f"{_CLEANUP_PREFIX}meeting_short_{0}"
    _insert_event(title, base_ms + 7 * 86400000, base_ms + 7 * 86400000 + 3600000, env)

    # 1 event: no "meeting" + >2h + no reminder → wrong title
    title = f"{_CLEANUP_PREFIX}other_long_{0}"
    _insert_event(title, base_ms + 8 * 86400000, base_ms + 8 * 86400000 + self._TWO_HOURS_MS + 600000, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
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


class Tier4AggregationCalendarTotalDuration(task_eval.TaskEval):
  """Total duration of all calendar events this month in minutes. ADB-exclusive."""

  app_names = ("simple calendar pro",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What is the total duration (in minutes) of all calendar events this"
      " month in Simple Calendar Pro? Output the number."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    base_ms = _month_start_ms() + 86400000  # day 2 of this month
    durations_min = [60, 90, 45, 120, 75]
    self._ground_truth: int = sum(durations_min)
    for i, dur in enumerate(durations_min):
      dtstart = base_ms + i * 86400000
      dtend = dtstart + dur * 60 * 1000
      _insert_event(f"{_CLEANUP_PREFIX}dur_{i}", dtstart, dtend, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    numbers = re.findall(r"\b\d+\b", cache)
    for n in numbers:
      if abs(int(n) - self._ground_truth) <= 5:
        return 1.0
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4DedupCalendarDeleteDuplicateEvents(task_eval.TaskEval):
  """Delete duplicate calendar events (same title + start time). ADB-exclusive."""

  app_names = ("simple calendar pro",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Delete duplicate calendar events in Simple Calendar Pro (events with"
      " the same title AND the same start time), keeping only one copy of each."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    base_ms = int(time.time() * 1000) + 86400000
    # 3 duplicate pairs
    dup_configs = [
        (f"{_CLEANUP_PREFIX}dup_meeting", base_ms),
        (f"{_CLEANUP_PREFIX}dup_review", base_ms + 86400000),
        (f"{_CLEANUP_PREFIX}dup_standup", base_ms + 2 * 86400000),
    ]
    self._dup_pairs: list[tuple[str, int]] = []
    for title, dtstart in dup_configs:
      dtend = dtstart + 3600000
      _insert_event(title, dtstart, dtend, env)
      _insert_event(title, dtstart, dtend, env)  # exact duplicate
      self._dup_pairs.append((title, dtstart))
    # 2 unique events
    self._unique_event_ids: list[str] = []
    for i in range(2):
      dtstart = base_ms + (i + 5) * 86400000
      eid = _insert_event(f"{_CLEANUP_PREFIX}unique_{i}", dtstart, dtstart + 3600000, env)
      self._unique_event_ids.append(eid)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    # Each dup pair should have exactly 1 event remaining
    for title, dtstart in self._dup_pairs:
      res = adb_utils.issue_generic_request(
          ["shell", "content", "query", "--uri", _CALENDAR_EVENTS_URI,
           "--where", f"title='{title}' AND dtstart={dtstart}",
           "--projection", "_id"],
          env.controller,
      )
      count = len(re.findall(r"_id=\d+", res.generic.output.decode()))
      if count != 1:
        return 0.0
    # Unique events still exist
    res = adb_utils.issue_generic_request(
        ["shell", "content", "query", "--uri", _CALENDAR_EVENTS_URI,
         "--projection", "_id"],
        env.controller,
    )
    existing_ids = set(re.findall(r"_id=(\d+)", res.generic.output.decode()))
    for eid in self._unique_event_ids:
      if eid not in existing_ids:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4TopKCalendarEarliestEvent(task_eval.TaskEval):
  """What is the earliest calendar event? ADB-exclusive."""

  app_names = ("simple calendar pro",)
  complexity = 1.2
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What is the earliest (oldest by start date) event in Simple Calendar"
      " Pro? Output the event title and its date."
  )

  # Fixed historical dates to ensure clear ordering
  _DATES = [
      datetime.datetime(2019, 3, 15, 10, 0),
      datetime.datetime(2020, 7, 22, 14, 0),
      datetime.datetime(2021, 11, 8, 9, 0),
      datetime.datetime(2022, 5, 1, 16, 0),
      datetime.datetime(2023, 9, 30, 11, 0),
  ]

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    dates = list(self._DATES)
    random.shuffle(dates)
    earliest_dt = min(dates)
    named: list[tuple[str, datetime.datetime]] = []
    for i, dt in enumerate(dates):
      title = f"{_CLEANUP_PREFIX}hist_event_{i}"
      dtstart_ms = _ms(dt)
      _insert_event(title, dtstart_ms, dtstart_ms + 3600000, env)
      named.append((title, dt))
    earliest = min(named, key=lambda x: x[1])
    self._ground_truth_title: str = earliest[0]
    self._ground_truth_date: str = earliest[1].strftime("%Y-%m-%d")

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    return 1.0 if self._ground_truth_title in cache else 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4CoverageCalendarEventsHaveReminders(task_eval.TaskEval):
  """Confirm all this-month calendar events have reminders; list those missing. ADB-exclusive."""

  app_names = ("simple calendar pro",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Confirm that all calendar events this month in Simple Calendar Pro have"
      " a reminder set. If any events don't have a reminder, list their titles."
      " If all have reminders, output 'All events have reminders'."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    base_ms = _month_start_ms() + 86400000  # day 2 of this month

    # 3 events WITH reminders
    for i in range(3):
      dtstart = base_ms + i * 86400000
      eid = _insert_event(f"{_CLEANUP_PREFIX}reminder_yes_{i}", dtstart, dtstart + 3600000, env)
      _insert_reminder(eid, 30, env)

    # 2 events WITHOUT reminders → ground truth
    self._ground_truth: list[str] = []
    for i in range(2):
      dtstart = base_ms + (i + 5) * 86400000
      title = f"{_CLEANUP_PREFIX}reminder_no_{i}"
      _insert_event(title, dtstart, dtstart + 3600000, env)
      self._ground_truth.append(title)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
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


# ── tier4_extra ──────────────────────────────────────────────────────────


class Tier4ExtraAggregationCalendarEventsPerDay(task_eval.TaskEval):
  """Which day this month has the most calendar events? ADB-exclusive (aggregation)."""

  app_names = ("simple calendar pro",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Which day this month has the most calendar events in Simple Calendar Pro?"
      " Output the date and the number of events."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    base_ms = _month_start_ms()
    # Distribute events: day 5 → 4 events, day 10 → 2, day 15 → 1, day 3 → 3
    day_events = {5: 4, 10: 2, 15: 1, 3: 3}
    for day_offset, count in day_events.items():
      for i in range(count):
        dtstart = base_ms + (day_offset - 1) * 86400000 + i * 3600000
        dtend = dtstart + 3600000
        _insert_event(f"{_CLEANUP_PREFIX}daycount_{day_offset}_{i}",
                      dtstart, dtend, env)
    now = datetime.datetime.utcnow()
    # Day 5 has the most events (4)
    self._ground_truth_day: str = f"{now.year}-{now.month:02d}-05"
    self._ground_truth_count: int = 4

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    if str(self._ground_truth_count) not in cache:
      return 0.0
    # Check for day reference (accept "5", "05", or full date)
    if "5" in cache:
      return 1.0
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraFilterCalendarWeekendEvents(task_eval.TaskEval):
  """List events that start on a Saturday or Sunday. ADB-exclusive."""

  app_names = ("simple calendar pro",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all calendar events in Simple Calendar Pro that start on a Saturday"
      " or Sunday. Output the event titles."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    # Create events on known dates: need to find actual weekend days
    now = datetime.datetime.utcnow()
    self._ground_truth: list[str] = []
    for offset in range(14):
      dt = now + datetime.timedelta(days=offset)
      dtstart_ms = _ms(dt)
      dtend_ms = dtstart_ms + 3600000
      title = f"{_CLEANUP_PREFIX}wkday_{offset}"
      _insert_event(title, dtstart_ms, dtend_ms, env)
      if dt.weekday() in (5, 6):  # Saturday=5, Sunday=6
        self._ground_truth.append(title)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
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


class Tier4ExtraTopKCalendarLongestEvents(task_eval.TaskEval):
  """List the 3 longest calendar events by duration. ADB-exclusive."""

  app_names = ("simple calendar pro",)
  complexity = 1.2
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What are the 3 longest calendar events by duration in Simple Calendar"
      " Pro? Output the event titles."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    base_ms = int(time.time() * 1000) + 86400000
    # 7 events with varying durations (minutes)
    durations_min = [30, 60, 120, 180, 45, 240, 90]
    random.shuffle(durations_min)
    named: list[tuple[str, int]] = []
    for i, dur in enumerate(durations_min):
      title = f"{_CLEANUP_PREFIX}longev_{i}"
      dtstart = base_ms + i * 86400000
      dtend = dtstart + dur * 60 * 1000
      _insert_event(title, dtstart, dtend, env)
      named.append((title, dur))
    top3 = sorted(named, key=lambda x: x[1], reverse=True)[:3]
    self._ground_truth: list[str] = [t for t, _ in top3]

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
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


class Tier4ExtraBulkAddReminderToAllEvents(task_eval.TaskEval):
  """Add a 15-minute reminder to all events that lack one. ADB-exclusive."""

  app_names = ("simple calendar pro",)
  complexity = 2.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Add a 15-minute reminder to all calendar events in Simple Calendar Pro"
      " that do not already have a reminder set."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _delete_tier4_events(env)
    base_ms = int(time.time() * 1000) + 86400000

    self._needs_reminder_ids: list[str] = []
    self._has_reminder_ids: list[str] = []

    # 3 events WITHOUT reminder → agent should add one
    for i in range(3):
      dtstart = base_ms + i * 86400000
      eid = _insert_event(f"{_CLEANUP_PREFIX}noremind_{i}",
                          dtstart, dtstart + 3600000, env)
      self._needs_reminder_ids.append(eid)

    # 2 events WITH reminder → agent should skip
    for i in range(2):
      dtstart = base_ms + (i + 5) * 86400000
      eid = _insert_event(f"{_CLEANUP_PREFIX}hasremind_{i}",
                          dtstart, dtstart + 3600000, env)
      _insert_reminder(eid, 30, env)
      self._has_reminder_ids.append(eid)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _delete_tier4_events(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    # Check that events that needed reminders now have one
    for eid in self._needs_reminder_ids:
      res = adb_utils.issue_generic_request(
          ["shell", "content", "query", "--uri", _CALENDAR_REMINDERS_URI,
           "--where", f"event_id={eid}",
           "--projection", "minutes"],
          env.controller,
      )
      output = res.generic.output.decode()
      if "No result found" in output:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
