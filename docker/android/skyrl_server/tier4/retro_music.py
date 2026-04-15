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

"""Tier 4 tasks for Retro Music app - ADB-exclusive."""

import dataclasses
import os
import random
from typing import Any

from android_world.env import adb_utils
from android_world.env import device_constants
from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.task_evals.utils import sqlite_schema_utils
from android_world.task_evals.utils import sqlite_utils
from android_world.task_evals.utils import user_data_generation
from android_world.utils import file_utils

_APP_NAME = 'retro music'
_PLAYLIST_DB_PATH = (
    '/data/data/code.name.monkey.retromusic/databases/playlist.db'
)


@dataclasses.dataclass(frozen=True)
class _SongRow(sqlite_schema_utils.SQLiteRow):
  title: str
  duration: int  # milliseconds
  artist: str = ''


def _get_all_songs(env: interface.AsyncEnv) -> list[_SongRow]:
  """Pull playlist DB and query all SongEntity rows."""
  with env.controller.pull_file(_PLAYLIST_DB_PATH, timeout_sec=5) as local_dir:
    local_path = file_utils.convert_to_posix_path(
        local_dir, os.path.split(_PLAYLIST_DB_PATH)[1]
    )
    return sqlite_utils.execute_query(
        'SELECT title, duration FROM SongEntity;', local_path, _SongRow
    )


def _clear_music(env: interface.AsyncEnv) -> None:
  """Remove all MP3 files and clear playlist DB tables."""
  adb_utils.issue_generic_request(
      ['shell', 'rm', '-f',
       f'{device_constants.MUSIC_DATA}/tier4rm_*.mp3'],
      env.controller,
  )
  for table in ('PlaylistEntity', 'SongEntity'):
    try:
      sqlite_utils.delete_all_rows_from_table(
          table, _PLAYLIST_DB_PATH, env, _APP_NAME
      )
    except Exception:
      pass


def _scan_music(env: interface.AsyncEnv) -> None:
  adb_utils.send_android_intent(
      command='broadcast',
      action='android.intent.action.MEDIA_SCANNER_SCAN_FILE',
      env=env.controller,
      data_uri='file:///storage/emulated/0/Music',
  )
  adb_utils.close_app(_APP_NAME, env.controller)


class Tier4FilterRetroMusicMultiCondition(task_eval.TaskEval):
  """List songs by artist longer than 4 min; exclude recently played. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 2.0
  schema = {
      'type': 'object',
      'properties': {'artist': {'type': 'string'}},
      'required': ['artist'],
  }
  template = (
      "List all songs in Retro Music by artist '{artist}' that are longer"
      " than 4 minutes. Output the song titles."
  )

  _FOUR_MIN_MS = 4 * 60 * 1000

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_music(env)
    artist = self.params.get('artist', 'TestArtist')
    self._ground_truth: list[str] = []
    self._mp3_names: list[str] = []

    # 3 songs by target artist, >4 min → ground truth
    for i in range(3):
      title = f'tier4rm_long_{artist}_{i}'
      fname = f'{title}.mp3'
      dur_ms = self._FOUR_MIN_MS + random.randint(30000, 120000)
      user_data_generation.write_mp3_file_to_device(
          file_utils.convert_to_posix_path(device_constants.MUSIC_DATA, fname),
          env, artist=artist, title=title, duration_milliseconds=dur_ms,
      )
      self._ground_truth.append(title)
      self._mp3_names.append(fname)

    # 2 songs by target artist, <4 min → excluded
    for i in range(2):
      title = f'tier4rm_short_{artist}_{i}'
      fname = f'{title}.mp3'
      dur_ms = random.randint(60000, self._FOUR_MIN_MS - 1000)
      user_data_generation.write_mp3_file_to_device(
          file_utils.convert_to_posix_path(device_constants.MUSIC_DATA, fname),
          env, artist=artist, title=title, duration_milliseconds=dur_ms,
      )
      self._mp3_names.append(fname)

    # 2 songs by different artist, >4 min → excluded
    for i in range(2):
      title = f'tier4rm_other_artist_{i}'
      fname = f'{title}.mp3'
      dur_ms = self._FOUR_MIN_MS + 60000
      user_data_generation.write_mp3_file_to_device(
          file_utils.convert_to_posix_path(device_constants.MUSIC_DATA, fname),
          env, artist='OtherBand', title=title, duration_milliseconds=dur_ms,
      )
      self._mp3_names.append(fname)

    _scan_music(env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_music(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, 'interaction_cache', '') or ''
    for title in self._ground_truth:
      if title not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {'artist': random.choice(['TestArtist', 'SampleBand', 'MockSinger'])}


class Tier4TopKRetroMusicLongestSongs(task_eval.TaskEval):
  """List the 5 longest songs in Retro Music by duration. ADB-exclusive."""

  app_names = (_APP_NAME,)
  complexity = 1.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "What are the 5 longest songs in Retro Music by duration?"
      " List their titles."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    _clear_music(env)
    # 8 songs with known durations (ms)
    durations = [60000, 120000, 180000, 240000, 300000, 360000, 420000, 480000]
    random.shuffle(durations)
    self._mp3_names: list[str] = []
    named = []
    for i, dur_ms in enumerate(durations):
      title = f'tier4rm_song_{i}'
      fname = f'{title}.mp3'
      user_data_generation.write_mp3_file_to_device(
          file_utils.convert_to_posix_path(device_constants.MUSIC_DATA, fname),
          env, artist='TestArtist', title=title,
          duration_milliseconds=dur_ms,
      )
      self._mp3_names.append(fname)
      named.append((title, dur_ms))
    _scan_music(env)
    top5 = sorted(named, key=lambda x: x[1], reverse=True)[:5]
    self._ground_truth: list[str] = [t for t, _ in top5]

  def tear_down(self, env: interface.AsyncEnv) -> None:
    _clear_music(env)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, 'interaction_cache', '') or ''
    for title in self._ground_truth:
      if title not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
