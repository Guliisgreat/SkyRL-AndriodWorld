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

"""Tier 4 tasks for Files app - ADB-exclusive."""

import random
from typing import Any

from android_world.env import adb_utils
from android_world.env import device_constants
from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.utils import file_utils


class Tier4BulkDeleteTmpInDownloads(task_eval.TaskEval):
  """Delete all .tmp files in Downloads. ADB-exclusive: GUI needs one-by-one."""

  app_names = ("files",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = "Delete all .tmp files in the Downloads folder."

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    # Create 3-5 .tmp files in Downloads
    for i in range(random.randint(3, 5)):
      name = f"temp_{random.randint(1000, 9999)}.tmp"
      file_utils.create_file(
          name, device_constants.DOWNLOAD_DATA, env.controller, content="x"
      )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    # Clean up: remove any remaining .tmp files
    res = adb_utils.issue_generic_request(
        ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp"],
        env.controller,
    )
    output = res.generic.output.decode().strip()
    if output:
      adb_utils.issue_generic_request(
          ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp", "-delete"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    res = adb_utils.issue_generic_request(
        ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp"],
        env.controller,
    )
    output = res.generic.output.decode().strip()
    return 1.0 if not output else 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4CoverageNoTmpInDownloads(task_eval.TaskEval):
  """Confirm no .tmp files in Downloads. Output 'None' or list them. ADB-exclusive."""

  app_names = ("files",)
  complexity = 1.2
  schema = {
      "type": "object",
      "properties": {"variant": {"type": "string", "enum": ["empty", "has_tmp"]}},
      "required": [],
  }
  template = (
      "Confirm that there are no files with extension .tmp in the Downloads"
      " folder. If any exist, list their names. If none exist, output 'None' or"
      " '0'."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    variant = self.params.get("variant", "empty")
    self._ground_truth: list[str] = []
    if variant == "has_tmp":
      for i in range(random.randint(2, 3)):
        name = f"check_{random.randint(100, 999)}.tmp"
        self._ground_truth.append(name)
        file_utils.create_file(
            name, device_constants.DOWNLOAD_DATA, env.controller, content="x"
        )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    adb_utils.issue_generic_request(
        ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp", "-delete"],
        env.controller,
    )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    res = adb_utils.issue_generic_request(
        ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", "*.tmp"],
        env.controller,
    )
    actual_files = [
        line.strip().split("/")[-1]
        for line in res.generic.output.decode().strip().split("\n")
        if line.strip()
    ]
    # Compare agent output in interaction_cache to ground truth
    cache = getattr(env, "interaction_cache", "") or ""
    cache_lower = cache.lower()
    if not self._ground_truth:
      # Variant A: expect "none" or "0"
      if "none" in cache_lower or cache.strip() == "0":
        return 1.0
      return 0.0
    # Variant B: agent should list the files
    for f in self._ground_truth:
      if f not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {"variant": random.choice(["empty", "has_tmp"])}
