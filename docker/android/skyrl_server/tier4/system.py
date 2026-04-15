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


class Tier4HiddenStateLocationPermissions(task_eval.TaskEval):
  """List all apps granted location permission. ADB-exclusive."""

  app_names = ("settings",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all apps (by package name or app name) that have been granted"
      " location permission on this device. If none, output 'None'."
  )

  _LOCATION_OPS = ("android:coarseLocation", "android:fineLocation")

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    res = adb_utils.issue_generic_request(
        ["shell", "dumpsys", "package", "permissions"], env.controller
    )
    output = res.generic.output.decode()
    granted: list[str] = []
    current_pkg = None
    for line in output.split("\n"):
      pkg_m = re.search(r"Package\s+([^\s:]+)\s*:", line)
      if pkg_m:
        current_pkg = pkg_m.group(1)
      if current_pkg and any(op in line for op in self._LOCATION_OPS):
        if "granted=true" in line and current_pkg not in granted:
          granted.append(current_pkg)
    self._ground_truth: list[str] = granted

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    if not self._ground_truth:
      return 1.0 if "none" in cache else 0.0
    for pkg in self._ground_truth:
      if pkg not in cache and pkg.split(".")[-1] not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4HiddenStateAudioRouting(task_eval.TaskEval):
  """Report current audio output routing and media volume. ADB-exclusive."""

  app_names = ("settings",)
  complexity = 1.2
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What is the current audio output routing device and the current media"
      " volume level? Output the routing device name and the volume number."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    # Get media volume (stream 3 = STREAM_MUSIC)
    vol_res = adb_utils.issue_generic_request(
        ["shell", "settings", "get", "system", "volume_music"], env.controller
    )
    vol_str = vol_res.generic.output.decode().strip()
    self._ground_truth_volume: str = vol_str if vol_str else "unknown"
    # Get audio routing from dumpsys audio
    audio_res = adb_utils.issue_generic_request(
        ["shell", "dumpsys", "audio"], env.controller
    )
    audio_out = audio_res.generic.output.decode()
    # Look for "- DEVICE_OUT_*" or "BT" or "speaker" routing hints
    device = "unknown"
    for line in audio_out.split("\n"):
      if "routing" in line.lower() and ("speaker" in line.lower()
                                         or "earpiece" in line.lower()
                                         or "bluetooth" in line.lower()
                                         or "headset" in line.lower()):
        device = line.strip()
        break
    # Fallback: look for active stream output device
    if device == "unknown":
      m = re.search(r"Output.*?device:.*?(0x[0-9a-fA-F]+|\w+speaker\w*|\w+earpiece\w*)", audio_out)
      if m:
        device = m.group(1)
    self._ground_truth_device: str = device

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    # Volume must be present
    if self._ground_truth_volume not in cache:
      return 0.0
    # Device string or a recognizable keyword must be present
    if self._ground_truth_device.lower() not in cache:
      # Acceptable aliases
      if not any(kw in cache for kw in ("speaker", "earpiece", "bluetooth", "headset", "wired")):
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4CoverageAppsCameraPermission(task_eval.TaskEval):
  """List all apps granted Camera permission. ADB-exclusive."""

  app_names = ("settings",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all apps (by package name or app name) that have been granted"
      " Camera permission on this device. If none, output 'None'."
  )

  _CAMERA_OP = "android:camera"

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    res = adb_utils.issue_generic_request(
        ["shell", "dumpsys", "package", "permissions"], env.controller
    )
    output = res.generic.output.decode()
    granted: list[str] = []
    current_pkg = None
    for line in output.split("\n"):
      pkg_m = re.search(r"Package\s+([^\s:]+)\s*:", line)
      if pkg_m:
        current_pkg = pkg_m.group(1)
      if current_pkg and self._CAMERA_OP in line and "granted=true" in line:
        if current_pkg not in granted:
          granted.append(current_pkg)
    self._ground_truth: list[str] = granted

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    if not self._ground_truth:
      return 1.0 if "none" in cache else 0.0
    for pkg in self._ground_truth:
      if pkg not in cache and pkg.split(".")[-1] not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4CoverageWifiConnected(task_eval.TaskEval):
  """Report WiFi enabled state and connected SSID. ADB-exclusive."""

  app_names = ("settings",)
  complexity = 1.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Is WiFi currently enabled and connected? If so, what SSID is it"
      " connected to? Output WiFi state (enabled/disabled) and the SSID"
      " (or 'not connected' if disconnected)."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    wifi_res = adb_utils.issue_generic_request(
        ["shell", "settings", "get", "global", "wifi_on"], env.controller
    )
    wifi_on = wifi_res.generic.output.decode().strip() == "1"
    self._wifi_enabled: bool = wifi_on
    ssid = "not connected"
    if wifi_on:
      dump_res = adb_utils.issue_generic_request(
          ["shell", "dumpsys", "wifi"], env.controller
      )
      dump_out = dump_res.generic.output.decode()
      m = re.search(r'SSID[=:]\s*"?([^",\n]+)"?', dump_out)
      if m:
        ssid = m.group(1).strip()
    self._ground_truth_ssid: str = ssid

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    state_word = "enabled" if self._wifi_enabled else "disabled"
    if state_word not in cache:
      return 0.0
    if self._ground_truth_ssid.lower() not in cache:
      if self._ground_truth_ssid != "not connected" or "not connected" not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
