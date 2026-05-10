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

import datetime
import random
import re
from typing import Any

from android_world.env import adb_utils
from android_world.env import device_constants
from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.utils import file_utils

_PICTURES_DIR = "/storage/emulated/0/Pictures"
_ARCHIVE_DIR = "/storage/emulated/0/Archive"


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


class Tier4BulkRenameScreenshots(task_eval.TaskEval):
  """Rename all Screenshot_* files in Pictures to YYYYMMDD_HHMMSS.png. ADB-exclusive."""

  app_names = ("files",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Rename all files starting with 'Screenshot_' in the Pictures folder"
      " (/storage/emulated/0/Pictures/) to the format YYYYMMDD_HHMMSS.png"
      " based on each file's modification time."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    adb_utils.issue_generic_request(
        ["shell", "mkdir", "-p", _PICTURES_DIR], env.controller
    )
    adb_utils.issue_generic_request(
        ["shell", "find", _PICTURES_DIR, "-name", "Screenshot_*.png", "-delete"],
        env.controller,
    )
    self._ground_truth: dict[str, str] = {}
    base_dt = datetime.datetime(2022, 3, 10, 8, 0, 0)
    for i in range(random.randint(3, 5)):
      dt = base_dt + datetime.timedelta(hours=i * 13 + random.randint(1, 5))
      name = f"Screenshot_{random.randint(1000, 9999)}.png"
      file_utils.create_file(name, _PICTURES_DIR, env.controller, content="img")
      touch_ts = dt.strftime("%Y%m%d%H%M.%S")
      adb_utils.issue_generic_request(
          ["shell", "touch", "-t", touch_ts, f"{_PICTURES_DIR}/{name}"],
          env.controller,
      )
      self._ground_truth[name] = dt.strftime("%Y%m%d_%H%M%S") + ".png"

  def tear_down(self, env: interface.AsyncEnv) -> None:
    adb_utils.issue_generic_request(
        ["shell", "find", _PICTURES_DIR, "-name", "Screenshot_*.png", "-delete"],
        env.controller,
    )
    for expected in self._ground_truth.values():
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{_PICTURES_DIR}/{expected}"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth:
      return 0.0
    res = adb_utils.issue_generic_request(
        ["shell", "find", _PICTURES_DIR, "-name", "Screenshot_*.png"],
        env.controller,
    )
    if res.generic.output.decode().strip():
      return 0.0
    for expected in self._ground_truth.values():
      res = adb_utils.issue_generic_request(
          ["shell", "find", _PICTURES_DIR, "-name", expected],
          env.controller,
      )
      if not res.generic.output.decode().strip():
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4BulkMoveLargeFiles(task_eval.TaskEval):
  """Move all files >50MB in Download to Archive. ADB-exclusive."""

  app_names = ("files",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Move all files larger than 50MB in the Download folder to the Archive"
      " folder (/storage/emulated/0/Archive/). Create the Archive folder if it"
      " doesn't exist."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    adb_utils.issue_generic_request(
        ["shell", "mkdir", "-p", _ARCHIVE_DIR], env.controller
    )
    self._large_names: list[str] = []
    self._small_names: list[str] = []
    for _ in range(random.randint(2, 3)):
      name = f"large_{random.randint(1000, 9999)}.dat"
      adb_utils.issue_generic_request(
          ["shell", "dd", "if=/dev/zero",
           f"of={device_constants.DOWNLOAD_DATA}/{name}",
           "bs=1048576", "count=52"],
          env.controller,
      )
      self._large_names.append(name)
    for _ in range(2):
      name = f"small_{random.randint(1000, 9999)}.dat"
      file_utils.create_file(
          name, device_constants.DOWNLOAD_DATA, env.controller, content="small"
      )
      self._small_names.append(name)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    for name in self._large_names + self._small_names:
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{_ARCHIVE_DIR}/{name}"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._large_names:
      return 0.0
    for name in self._large_names:
      res = adb_utils.issue_generic_request(
          ["shell", "find", _ARCHIVE_DIR, "-name", name], env.controller
      )
      if not res.generic.output.decode().strip():
        return 0.0
      res = adb_utils.issue_generic_request(
          ["shell", "find", device_constants.DOWNLOAD_DATA, "-name", name],
          env.controller,
      )
      if res.generic.output.decode().strip():
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4FilterRecentLogFiles(task_eval.TaskEval):
  """List .log and .txt files in Downloads modified within last 60 min. ADB-exclusive."""

  app_names = ("files",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all .log and .txt files in the Downloads folder that were modified"
      " within the last 60 minutes. Output the filenames."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    self._all_names: list[str] = []
    self._ground_truth: list[str] = []
    for _ in range(random.randint(3, 4)):
      ext = random.choice([".log", ".txt"])
      name = f"recent_{random.randint(1000, 9999)}{ext}"
      file_utils.create_file(
          name, device_constants.DOWNLOAD_DATA, env.controller, content="log data"
      )
      self._all_names.append(name)
      self._ground_truth.append(name)
    # Create 2 old files with mtime definitely > 60 min ago
    for _ in range(2):
      ext = random.choice([".log", ".txt"])
      name = f"old_{random.randint(1000, 9999)}{ext}"
      file_utils.create_file(
          name, device_constants.DOWNLOAD_DATA, env.controller, content="old log"
      )
      adb_utils.issue_generic_request(
          ["shell", "touch", "-t", "202001010000.00",
           f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
      self._all_names.append(name)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    for name in self._all_names:
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth:
      return 0.0
    cache = getattr(env, "interaction_cache", "") or ""
    for name in self._ground_truth:
      if name not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4AggregationDownloadSizeTop3(task_eval.TaskEval):
  """Report total size of Downloads and identify 3 largest files. ADB-exclusive."""

  app_names = ("files",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What is the total size (in bytes) of all files in the Downloads folder,"
      " and what are the 3 largest files? Output the total size and the 3"
      " largest filenames."
  )

  _SIZES = [1024, 2048, 4096, 8192, 16384, 32768]

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    self._filenames: list[str] = []
    sizes = list(self._SIZES)
    random.shuffle(sizes)
    named: list[tuple[str, int]] = []
    for i, sz in enumerate(sizes):
      name = f"tier4dl_{i}_{sz}.bin"
      adb_utils.issue_generic_request(
          ["shell", "dd", "if=/dev/zero",
           f"of={device_constants.DOWNLOAD_DATA}/{name}",
           "bs=1", f"count={sz}"],
          env.controller,
      )
      named.append((name, sz))
      self._filenames.append(name)
    self._ground_truth_total: int = sum(sizes)
    top3 = sorted(named, key=lambda x: x[1], reverse=True)[:3]
    self._ground_truth_top3: list[str] = [n for n, _ in top3]

  def tear_down(self, env: interface.AsyncEnv) -> None:
    for name in self._filenames:
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth_top3:
      return 0.0
    cache = (getattr(env, "interaction_cache", "") or "")
    numbers = re.findall(r"\b\d+\b", cache)
    total_ok = any(
        abs(int(n) - self._ground_truth_total) <= self._ground_truth_total * 0.1
        for n in numbers
    )
    if not total_ok:
      return 0.0
    for name in self._ground_truth_top3:
      if name not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4TopKLargestDownloadFiles(task_eval.TaskEval):
  """List the 5 largest files in Downloads by size. ADB-exclusive."""

  app_names = ("files",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What are the 5 largest files in the Downloads folder? List their"
      " filenames and sizes."
  )

  _SIZES = [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    self._filenames: list[str] = []
    sizes = list(self._SIZES)
    random.shuffle(sizes)
    named: list[tuple[str, int]] = []
    for i, sz in enumerate(sizes):
      name = f"tier4top5_{i}_{sz}.bin"
      adb_utils.issue_generic_request(
          ["shell", "dd", "if=/dev/zero",
           f"of={device_constants.DOWNLOAD_DATA}/{name}",
           "bs=1", f"count={sz}"],
          env.controller,
      )
      named.append((name, sz))
      self._filenames.append(name)
    top5 = sorted(named, key=lambda x: x[1], reverse=True)[:5]
    self._ground_truth: list[str] = [n for n, _ in top5]

  def tear_down(self, env: interface.AsyncEnv) -> None:
    for name in self._filenames:
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


# ── tier4_extra ──────────────────────────────────────────────────────────


class Tier4ExtraAggregationFileCountByExtension(task_eval.TaskEval):
  """Count files per extension in Downloads. ADB-exclusive (aggregation)."""

  app_names = ("files",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Count how many files of each extension type (.txt, .log, .bin, .dat)"
      " are in the Downloads folder. Output the counts per extension."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    self._filenames: list[str] = []
    ext_counts = {".txt": 3, ".log": 2, ".bin": 4, ".dat": 1}
    self._ground_truth: dict[str, int] = dict(ext_counts)
    for ext, count in ext_counts.items():
      for i in range(count):
        name = f"tier4ext_count_{i}{ext}"
        file_utils.create_file(
            name, device_constants.DOWNLOAD_DATA, env.controller, content="data"
        )
        self._filenames.append(name)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    for name in self._filenames:
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    # Check that each count appears in the output
    for ext, count in self._ground_truth.items():
      if str(count) not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraFilterEmptyFilesInDownloads(task_eval.TaskEval):
  """List zero-byte files in Downloads. ADB-exclusive (stat check)."""

  app_names = ("files",)
  complexity = 1.2
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all zero-byte (empty) files in the Downloads folder."
      " Output the filenames."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    self._all_names: list[str] = []
    self._ground_truth: list[str] = []
    # Create 3 empty files
    for i in range(3):
      name = f"tier4ext_empty_{random.randint(1000, 9999)}.txt"
      adb_utils.issue_generic_request(
          ["shell", "touch", f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
      self._all_names.append(name)
      self._ground_truth.append(name)
    # Create 2 non-empty files
    for i in range(2):
      name = f"tier4ext_notempty_{random.randint(1000, 9999)}.txt"
      file_utils.create_file(
          name, device_constants.DOWNLOAD_DATA, env.controller,
          content="has content"
      )
      self._all_names.append(name)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    for name in self._all_names:
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{device_constants.DOWNLOAD_DATA}/{name}"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    for name in self._ground_truth:
      if name not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraBulkFlattenSubdirectories(task_eval.TaskEval):
  """Move all files from subdirectories into Downloads root. ADB-exclusive."""

  app_names = ("files",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Move all files from any subdirectories within Downloads"
      " (/storage/emulated/0/Download/) into the Downloads root folder,"
      " then remove the empty subdirectories."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    self._subdirs: list[str] = []
    self._files: list[str] = []
    # Create 2 subdirectories with files
    for i in range(2):
      subdir = f"tier4ext_subdir_{random.randint(1000, 9999)}"
      subdir_path = f"{device_constants.DOWNLOAD_DATA}/{subdir}"
      adb_utils.issue_generic_request(
          ["shell", "mkdir", "-p", subdir_path], env.controller
      )
      self._subdirs.append(subdir)
      for j in range(2):
        fname = f"tier4ext_nested_{i}_{j}.txt"
        file_utils.create_file(fname, subdir_path, env.controller, content="nested")
        self._files.append(fname)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    for fname in self._files:
      adb_utils.issue_generic_request(
          ["shell", "rm", "-f", f"{device_constants.DOWNLOAD_DATA}/{fname}"],
          env.controller,
      )
    for subdir in self._subdirs:
      adb_utils.issue_generic_request(
          ["shell", "rm", "-rf", f"{device_constants.DOWNLOAD_DATA}/{subdir}"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    # All files should be in root Downloads
    for fname in self._files:
      res = adb_utils.issue_generic_request(
          ["shell", "find", device_constants.DOWNLOAD_DATA, "-maxdepth", "1",
           "-name", fname],
          env.controller,
      )
      if not res.generic.output.decode().strip():
        return 0.0
    # Subdirectories should be gone
    for subdir in self._subdirs:
      res = adb_utils.issue_generic_request(
          ["shell", "test", "-d",
           f"{device_constants.DOWNLOAD_DATA}/{subdir}",
           "&&", "echo", "exists"],
          env.controller,
      )
      if "exists" in res.generic.output.decode():
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
