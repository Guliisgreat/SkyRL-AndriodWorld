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

"""Tier 4 tasks for Joplin app - ADB-exclusive."""

import random
from typing import Any

from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.task_evals.utils import sqlite_schema_utils
from android_world.task_evals.utils import sqlite_utils

_NOTES_TABLE = 'notes'
_NOTES_NORMALIZED_TABLE = 'notes_normalized'
_FOLDER_TABLE = 'folders'
_DB_PATH = '/data/data/net.cozic.joplin/databases/joplin.sqlite'
_APP_NAME = 'joplin'
_EXCLUDE_FIELD = 'deleted_time'


def _insert_notes(notes: list[sqlite_schema_utils.JoplinNote],
                  env: interface.AsyncEnv) -> None:
  """Insert notes into both notes and notes_normalized tables."""
  sqlite_utils.insert_rows_to_remote_db(
      notes, None, _NOTES_TABLE, _DB_PATH, _APP_NAME, env
  )
  normalized = [
      sqlite_schema_utils.JoplinNormalizedNote(
          id=n.id, parent_id=n.parent_id, title=n.title.lower(),
          body=n.body.lower(), is_todo=n.is_todo,
          user_created_time=n.user_created_time,
          user_updated_time=n.user_updated_time,
      )
      for n in notes
  ]
  sqlite_utils.insert_rows_to_remote_db(
      normalized, None, _NOTES_NORMALIZED_TABLE, _DB_PATH, _APP_NAME, env
  )


def _get_notes(env: interface.AsyncEnv) -> list[sqlite_schema_utils.JoplinNote]:
  return sqlite_utils.get_rows_from_remote_device(
      _NOTES_TABLE, _DB_PATH, sqlite_schema_utils.JoplinNote, env
  )


def _clear_notes(env: interface.AsyncEnv) -> None:
  sqlite_utils.delete_all_rows_from_table(
      _NOTES_TABLE, _DB_PATH, env, _APP_NAME
  )
  sqlite_utils.delete_all_rows_from_table(
      _NOTES_NORMALIZED_TABLE, _DB_PATH, env, _APP_NAME
  )


class Tier4FilterJoplinContainsNotContains(task_eval.TaskEval):
  """List Joplin notes containing keyword_A but NOT keyword_B. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 2.0
  schema = {
      'type': 'object',
      'properties': {
          'keyword_a': {'type': 'string'},
          'keyword_b': {'type': 'string'},
      },
      'required': ['keyword_a', 'keyword_b'],
  }
  template = (
      "List all Joplin notes that contain '{keyword_a}' but do NOT contain"
      " '{keyword_b}'. Output the note titles."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_notes(env)
    kw_a = self.params.get('keyword_a', 'project')
    kw_b = self.params.get('keyword_b', 'urgent')
    self._ground_truth: list[str] = []
    notes = []

    # 2 notes: has A, no B → ground truth
    for i in range(2):
      title = f'note_a_only_{i}'
      notes.append(sqlite_schema_utils.JoplinNote(
          title=title,
          body=f'This note is about {kw_a} planning and updates.',
      ))
      self._ground_truth.append(title)

    # 1 note: has A AND B → excluded
    notes.append(sqlite_schema_utils.JoplinNote(
        title='note_a_and_b',
        body=f'This is a {kw_a} note marked as {kw_b}.',
    ))

    # 1 note: has B only → excluded
    notes.append(sqlite_schema_utils.JoplinNote(
        title='note_b_only',
        body=f'This is {kw_b} and needs attention.',
    ))

    # 1 note: neither → excluded
    notes.append(sqlite_schema_utils.JoplinNote(
        title='note_neither',
        body='Random thoughts about nothing in particular.',
    ))
    _insert_notes(notes, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_notes(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth:
      return 0.0
    cache = getattr(env, 'interaction_cache', '') or ''
    for title in self._ground_truth:
      if title not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    pairs = [
        ('project', 'urgent'),
        ('meeting', 'canceled'),
        ('recipe', 'draft'),
        ('travel', 'booked'),
    ]
    kw_a, kw_b = random.choice(pairs)
    return {'keyword_a': kw_a, 'keyword_b': kw_b}


class Tier4DedupJoplinSameTitleNotes(task_eval.TaskEval):
  """List all Joplin notes that have the same title as another note. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 1.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "List all Joplin notes that have the same title as another note"
      " (i.e., duplicate titles). Output the duplicate titles."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_notes(env)
    notes = []
    self._ground_truth: list[str] = []

    # 2 pairs of duplicate titles
    dup_titles = ['Meeting Notes', 'Project Plan']
    for title in dup_titles:
      notes.append(sqlite_schema_utils.JoplinNote(
          title=title, body='First copy of this note.',
      ))
      notes.append(sqlite_schema_utils.JoplinNote(
          title=title, body='Second copy, slightly different content.',
      ))
      self._ground_truth.append(title)

    # 2 unique titles
    notes.append(sqlite_schema_utils.JoplinNote(
        title='Shopping List', body='Milk, eggs, bread.',
    ))
    notes.append(sqlite_schema_utils.JoplinNote(
        title='Journal Entry', body='Today was a good day.',
    ))
    _insert_notes(notes, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_notes(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth:
      return 0.0
    cache = getattr(env, 'interaction_cache', '') or ''
    for title in self._ground_truth:
      if title not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
