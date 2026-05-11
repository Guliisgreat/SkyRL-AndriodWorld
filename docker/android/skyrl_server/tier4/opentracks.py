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

"""Tier 4 tasks for OpenTracks app - ADB-exclusive."""

import random
import time
import uuid
from typing import Any

from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.task_evals.utils import sqlite_schema_utils
from android_world.task_evals.utils import sqlite_utils

_TABLE = 'tracks'
_DB_PATH = '/data/data/de.dennisguse.opentracks/databases/database.db'
_APP_NAME = 'activity tracker'
_DB_KEY = '_id'

_METERS_PER_KM = 1000.0


def _now_ms() -> int:
  return int(time.time() * 1000)


def _week_start_ms() -> int:
  """Start of the current UTC week (Monday)."""
  import datetime
  now = datetime.datetime.utcnow()
  monday = now - datetime.timedelta(days=now.weekday())
  monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
  return int(monday.timestamp() * 1000)


def _make_activity(name: str, distance_m: float, duration_ms: int,
                   starttime_ms: int) -> sqlite_schema_utils.SportsActivity:
  stoptime_ms = starttime_ms + duration_ms
  avg_speed = distance_m / (duration_ms / 1000) if duration_ms > 0 else 0.0
  return sqlite_schema_utils.SportsActivity(
      name=name,
      category='running',
      activity_type='running',
      totaldistance=distance_m,
      totaltime=duration_ms,
      movingtime=duration_ms,
      starttime=starttime_ms,
      stoptime=stoptime_ms,
      avgspeed=avg_speed,
      avgmovingspeed=avg_speed,
      uuid=uuid.uuid4().bytes,
  )


def _insert_activities(rows: list[sqlite_schema_utils.SportsActivity],
                       env: interface.AsyncEnv) -> None:
  sqlite_utils.insert_rows_to_remote_db(
      rows, _DB_KEY, _TABLE, _DB_PATH, _APP_NAME, env
  )


def _get_activities(
    env: interface.AsyncEnv,
) -> list[sqlite_schema_utils.SportsActivity]:
  return sqlite_utils.get_rows_from_remote_device(
      _TABLE, _DB_PATH, sqlite_schema_utils.SportsActivity, env
  )


def _clear_activities(env: interface.AsyncEnv) -> None:
  sqlite_utils.delete_all_rows_from_table(_TABLE, _DB_PATH, env, _APP_NAME)


class Tier4AggregationOpenTracksWeeklyStats(task_eval.TaskEval):
  """Total distance this week + longest activity name. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 2.0
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "What is the total distance of all activities this week in OpenTracks,"
      " and which activity covered the longest distance?"
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_activities(env)
    week_start = _week_start_ms()
    # 4 activities this week with known distances (meters)
    configs = [
        ('Morning Run', 5000),
        ('Evening Jog', 3200),
        ('Long Run', 12000),
        ('Recovery Walk', 2100),
    ]
    rows = []
    for i, (name, dist_m) in enumerate(configs):
      starttime = week_start + i * 3600000
      rows.append(_make_activity(name, dist_m, 3600000, starttime))
    _insert_activities(rows, env)

    total_km = sum(d for _, d in configs) / _METERS_PER_KM
    self._ground_truth_total_km: float = total_km
    self._ground_truth_longest: str = 'Long Run'

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_activities(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, 'interaction_cache', '') or ''
    # Check longest activity name
    if self._ground_truth_longest not in cache:
      return 0.0
    # Check total distance with ±0.5 km tolerance
    import re
    numbers = re.findall(r'\b\d+\.?\d*\b', cache)
    for n in numbers:
      if abs(float(n) - self._ground_truth_total_km) <= 0.5:
        return 1.0
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4TopKOpenTracksFastestActivity(task_eval.TaskEval):
  """Which activity had the highest average speed? ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 1.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "Which activity in OpenTracks had the highest average speed?"
      " Output the activity name and its average speed."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_activities(env)
    now_ms = _now_ms()
    # 5 activities with varying speeds (m/s)
    configs = [
        ('Slow Walk', 1000, 1800000),    # ~0.56 m/s
        ('Easy Run', 5000, 1800000),     # ~2.78 m/s
        ('Fast Run', 10000, 2400000),    # ~4.17 m/s
        ('Sprint', 3000, 600000),        # 5.0 m/s → fastest
        ('Bike Ride', 15000, 3600000),   # ~4.17 m/s
    ]
    rows = []
    for i, (name, dist_m, dur_ms) in enumerate(configs):
      starttime = now_ms - (5 - i) * 86400000
      rows.append(_make_activity(name, dist_m, dur_ms, starttime))
    _insert_activities(rows, env)
    # Sprint: 3000m / 600s = 5.0 m/s → fastest
    self._ground_truth: str = 'Sprint'

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_activities(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, 'interaction_cache', '') or ''
    return 1.0 if self._ground_truth in cache else 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# [EXCLUDED] Removed from Tier 4 benchmark — not registered.
# class Tier4CrossAppOpenTracksToTasks(task_eval.TaskEval):
#   """Find longest OpenTracks activity this week, save to Markor note. ADB-exclusive."""
#
#   app_names = (_APP_NAME, 'markor')
#   complexity = 2.5
#   schema = {'type': 'object', 'properties': {}, 'required': []}
#   template = (
#       "What was my longest exercise this week in OpenTracks? Save its name"
#       " and distance to a note called 'best_run' in Markor."
#   )
#
#   _MARKOR_DIR = '/storage/emulated/0/Documents/Markor'
#   _NOTE_NAME = 'best_run.md'
#
#   def initialize_task(self, env: interface.AsyncEnv) -> None:
#     super().initialize_task(env)
#     _clear_activities(env)
#     now_ms = _now_ms()
#     configs = [
#         ('Trail Run', 8000),
#         ('City Walk', 3500),
#         ('Marathon Prep', 21000),   # longest: 21 km
#         ('Recovery Jog', 4000),
#     ]
#     rows = []
#     for i, (name, dist_m) in enumerate(configs):
#       starttime = now_ms - (4 - i) * 86400000
#       rows.append(_make_activity(name, dist_m, 7200000, starttime))
#     _insert_activities(rows, env)
#     self._ground_truth_name: str = 'Marathon Prep'
#     self._ground_truth_km: float = 21.0
#     self._note_path = f"{self._MARKOR_DIR}/{self._NOTE_NAME}"
#
#   def tear_down(self, env: interface.AsyncEnv) -> None:
#     _clear_activities(env)
#     from android_world.utils import adb_utils
#     adb_utils.issue_generic_request(
#         ["shell", "rm", "-f", self._note_path], env.controller
#     )
#     super().tear_down(env)
#
#   def is_successful(self, env: interface.AsyncEnv) -> float:
#     super().is_successful(env)
#     from android_world.utils import adb_utils
#     res = adb_utils.issue_generic_request(
#         ["shell", "cat", self._note_path], env.controller
#     )
#     content = res.generic.output.decode()
#     # Check that activity name is present
#     if self._ground_truth_name not in content:
#       return 0.0
#     # Check distance with ±0.5 km tolerance
#     import re
#     numbers = re.findall(r'\b\d+\.?\d*\b', content)
#     for n in numbers:
#       if abs(float(n) - self._ground_truth_km) <= 0.5:
#         return 1.0
#     return 0.0
#
#   @classmethod
#   def generate_random_params(cls) -> dict[str, Any]:
#     return {}
