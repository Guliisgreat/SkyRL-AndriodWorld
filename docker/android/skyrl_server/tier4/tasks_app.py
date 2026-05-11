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

"""Tier 4 tasks for Tasks.org app - ADB-exclusive."""

import random
import time
import uuid
from typing import Any

from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.task_evals.utils import sqlite_schema_utils
from android_world.task_evals.utils import sqlite_utils

_DB_PATH = '/data/data/org.tasks/databases/database'
_TABLE = 'tasks'
_APP_NAME = 'tasks'
_DB_KEY = '_id'

# Importance levels: 0=None, 1=Low, 2=Medium, 3=High
_PRIORITY_NONE = 0
_PRIORITY_LOW = 1
_PRIORITY_MEDIUM = 2
_PRIORITY_HIGH = 3


def _now_ms() -> int:
  return int(time.time() * 1000)


def _make_task(title: str, importance: int, due_ms: int = 0,
               completed: int = 0) -> sqlite_schema_utils.Task:
  now = _now_ms()
  return sqlite_schema_utils.Task(
      title=title,
      importance=importance,
      dueDate=due_ms,
      completed=completed,
      created=now,
      modified=now,
      remoteId=uuid.uuid4().hex,
  )


def _insert_tasks(rows: list[sqlite_schema_utils.Task],
                  env: interface.AsyncEnv) -> None:
  sqlite_utils.insert_rows_to_remote_db(
      rows, _DB_KEY, _TABLE, _DB_PATH, _APP_NAME, env
  )


def _get_tasks(env: interface.AsyncEnv) -> list[sqlite_schema_utils.Task]:
  return sqlite_utils.get_rows_from_remote_device(
      _TABLE, _DB_PATH, sqlite_schema_utils.Task, env
  )


def _clear_tasks(env: interface.AsyncEnv) -> None:
  sqlite_utils.delete_all_rows_from_table(_TABLE, _DB_PATH, env, _APP_NAME)


class Tier4BulkChangePriorityTasks(task_eval.TaskEval):
  """Change all overdue tasks to High priority. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 1.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "Change all overdue tasks in the Tasks app to High priority."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_tasks(env)
    rows = []
    self._overdue_titles: list[str] = []
    past_ms = _now_ms() - 3 * 24 * 3600 * 1000  # 3 days ago
    future_ms = _now_ms() + 3 * 24 * 3600 * 1000  # 3 days ahead
    # 4 overdue tasks (past due date, Low priority, not completed)
    for i in range(4):
      title = f'overdue_task_{i}'
      rows.append(_make_task(title, _PRIORITY_LOW,
                             due_ms=past_ms - i * 86400000))
      self._overdue_titles.append(title)
    # 2 non-overdue tasks with Low priority (should stay unchanged)
    for i in range(2):
      rows.append(_make_task(f'future_task_{i}', _PRIORITY_LOW,
                             due_ms=future_ms + i * 86400000))
    _insert_tasks(rows, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_tasks(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._overdue_titles:
      return 0.0
    rows = _get_tasks(env)
    for row in rows:
      if row.title in self._overdue_titles:
        if row.importance != _PRIORITY_HIGH:
          return 0.0
      elif row.title.startswith('future_task_'):
        # Non-overdue tasks should NOT have been changed to High
        if row.importance == _PRIORITY_HIGH:
          return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# [EXCLUDED] Removed from Tier 4 benchmark — not registered.
# class Tier4CoverageOverdueTasksCompleted(task_eval.TaskEval):
#   """Confirm all overdue tasks are marked completed; list any that aren't. ADB-exclusive."""
#
#   app_names = (_APP_NAME,)
#   complexity = 1.5
#   schema = {'type': 'object', 'properties': {}, 'required': []}
#   template = (
#       "Confirm all overdue tasks in the Tasks app are marked completed."
#       " If any are not completed, list their titles."
#       " If all are completed, output 'all completed'."
#   )
#
#   def initialize_task(self, env: interface.AsyncEnv) -> None:
#     super().initialize_task(env)
#     _clear_tasks(env)
#     # Overdue = dueDate in the past
#     past_ms = _now_ms() - 7 * 24 * 3600 * 1000  # 7 days ago
#     rows = []
#     self._ground_truth: list[str] = []
#
#     # 2 overdue + completed (should not appear)
#     for i in range(2):
#       rows.append(_make_task(f'overdue_done_{i}', _PRIORITY_MEDIUM,
#                              due_ms=past_ms, completed=_now_ms()))
#
#     # 2 overdue + NOT completed → should appear in output
#     for i in range(2):
#       title = f'overdue_pending_{i}'
#       rows.append(_make_task(title, _PRIORITY_MEDIUM,
#                              due_ms=past_ms, completed=0))
#       self._ground_truth.append(title)
#
#     # 1 not overdue, not completed (future due date — ok)
#     future_ms = _now_ms() + 7 * 24 * 3600 * 1000
#     rows.append(_make_task('future_task', _PRIORITY_LOW, due_ms=future_ms))
#     _insert_tasks(rows, env)
#
#   def tear_down(self, env: interface.AsyncEnv) -> None:
#     _clear_tasks(env)
#     super().tear_down(env)
#
#   def is_successful(self, env: interface.AsyncEnv) -> float:
#     super().is_successful(env)
#     cache = (getattr(env, 'interaction_cache', '') or '').lower()
#     if not self._ground_truth:
#       return 1.0 if 'all' in cache or 'none' in cache else 0.0
#     for title in self._ground_truth:
#       if title not in cache:
#         return 0.0
#     return 1.0
#
#   @classmethod
#   def generate_random_params(cls) -> dict[str, Any]:
#     return {}
