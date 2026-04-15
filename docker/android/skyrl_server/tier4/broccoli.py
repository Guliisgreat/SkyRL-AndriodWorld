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

"""Tier 4 tasks for Broccoli (recipe) app - ADB-exclusive."""

import random
from typing import Any

from android_world.env import adb_utils
from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.task_evals.utils import sqlite_schema_utils
from android_world.task_evals.utils import sqlite_utils
from android_world.utils import file_utils

_DB_PATH = '/data/data/com.flauschcode.broccoli/databases/broccoli'
_TABLE = 'recipes'
_APP_NAME = 'broccoli app'
_DB_KEY = 'recipeId'

_MARKOR_DIR = '/storage/emulated/0/Documents/Markor'
_NOTE_NAME = 'recipes_index.md'

_SAMPLE_RECIPES = [
    ('Spaghetti Carbonara', 'Classic Italian pasta dish.'),
    ('Chicken Tikka Masala', 'Creamy tomato-based curry.'),
    ('Beef Tacos', 'Mexican street-food favourite.'),
    ('Caesar Salad', 'Crisp romaine with parmesan dressing.'),
    ('Banana Bread', 'Moist quick bread with ripe bananas.'),
    ('Tomato Soup', 'Smooth and warming.'),
]


def _insert_recipes(rows: list[sqlite_schema_utils.Recipe],
                    env: interface.AsyncEnv) -> None:
  sqlite_utils.insert_rows_to_remote_db(
      rows, _DB_KEY, _TABLE, _DB_PATH, _APP_NAME, env
  )


def _get_recipes(env: interface.AsyncEnv) -> list[sqlite_schema_utils.Recipe]:
  return sqlite_utils.get_rows_from_remote_device(
      _TABLE, _DB_PATH, sqlite_schema_utils.Recipe, env
  )


def _clear_recipes(env: interface.AsyncEnv) -> None:
  sqlite_utils.delete_all_rows_from_table(_TABLE, _DB_PATH, env, _APP_NAME)


class Tier4CrossAppBroccoliToMarkorIndex(task_eval.TaskEval):
  """List all Broccoli recipe names as a bulleted Markor note. ADB-exclusive."""

  app_names = (_APP_NAME, 'markor')
  complexity = 2.0
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "List all recipe names from the Broccoli app and write them as a"
      " bulleted list in a Markor note named 'recipes_index.md'."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_recipes(env)
    # Pick 5 random recipes from sample list
    chosen = random.sample(_SAMPLE_RECIPES, 5)
    rows = [
        sqlite_schema_utils.Recipe(title=title, description=desc)
        for title, desc in chosen
    ]
    _insert_recipes(rows, env)
    self._ground_truth: list[str] = [title for title, _ in chosen]
    self._note_path = f'{_MARKOR_DIR}/{_NOTE_NAME}'

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_recipes(env)
    adb_utils.issue_generic_request(
        ['shell', 'rm', '-f', self._note_path], env.controller
    )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    res = adb_utils.issue_generic_request(
        ['shell', 'cat', self._note_path], env.controller
    )
    content = res.generic.output.decode()
    if not content.strip():
      return 0.0
    for title in self._ground_truth:
      if title not in content:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
