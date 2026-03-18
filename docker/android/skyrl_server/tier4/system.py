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

"""Tier 4 tasks for system introspection - ADB-exclusive."""

import re
from typing import Any

from android_world.env import adb_utils
from android_world.env import interface
from android_world.task_evals import task_eval

# Package names for the 3 apps we query
_APP_PACKAGES = {
    "Markor": "net.gsantner.markor",
    "Pro Expense": "com.arduia.expense",
    "Simple Calendar Pro": "com.simplemobiletools.calendar.pro",
}


def _get_app_version(package: str, env: interface.AsyncEnv) -> str:
  """Get app version via dumpsys package. Returns version string."""
  res = adb_utils.issue_generic_request(
      ["shell", "dumpsys", "package", package], env.controller
  )
  output = res.generic.output.decode()
  version_code = None
  version_name = None
  for line in output.split("\n"):
    if "versionCode=" in line:
      m = re.search(r"versionCode=(\d+)", line)
      if m:
        version_code = m.group(1)
    if "versionName=" in line:
      m = re.search(r"versionName=([^\s]+)", line)
      if m:
        version_name = m.group(1)
  return version_name or version_code or "unknown"


class Tier4HiddenStateListAppVersions(task_eval.TaskEval):
  """List version of Markor, Pro Expense, Simple Calendar Pro. ADB-exclusive."""

  app_names = ("settings",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List the version of each of the following apps: Markor, Pro Expense,"
      " Simple Calendar Pro. Output each app name and its version."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    self._ground_truth: dict[str, str] = {}
    for app_name, pkg in _APP_PACKAGES.items():
      self._ground_truth[app_name] = _get_app_version(pkg, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    for app_name, expected_version in self._ground_truth.items():
      if app_name not in cache:
        return 0.0
      if expected_version not in cache and str(expected_version) not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
