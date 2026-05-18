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
    if not self._ground_truth:
      return 0.0
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


class Tier4HiddenStateAppsCameraPermission(task_eval.TaskEval):
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


# [EXCLUDED] Removed from Tier 4 benchmark — not registered.
# class Tier4CoverageWifiConnected(task_eval.TaskEval):
#   """Report WiFi enabled state and connected SSID. ADB-exclusive."""
#
#   app_names = ("settings",)
#   complexity = 1.0
#   schema = {"type": "object", "properties": {}, "required": []}
#   template = (
#       "Is WiFi currently enabled and connected? If so, what SSID is it"
#       " connected to? Output WiFi state (enabled/disabled) and the SSID"
#       " (or 'not connected' if disconnected)."
#   )
#
#   def initialize_task(self, env: interface.AsyncEnv) -> None:
#     super().initialize_task(env)
#     wifi_res = adb_utils.issue_generic_request(
#         ["shell", "settings", "get", "global", "wifi_on"], env.controller
#     )
#     wifi_on = wifi_res.generic.output.decode().strip() == "1"
#     self._wifi_enabled: bool = wifi_on
#     ssid = "not connected"
#     if wifi_on:
#       dump_res = adb_utils.issue_generic_request(
#           ["shell", "dumpsys", "wifi"], env.controller
#       )
#       dump_out = dump_res.generic.output.decode()
#       m = re.search(r'SSID[=:]\s*"?([^",\n]+)"?', dump_out)
#       if m:
#         ssid = m.group(1).strip()
#     self._ground_truth_ssid: str = ssid
#
#   def tear_down(self, env: interface.AsyncEnv) -> None:
#     super().tear_down(env)
#
#   def is_successful(self, env: interface.AsyncEnv) -> float:
#     super().is_successful(env)
#     cache = (getattr(env, "interaction_cache", "") or "").lower()
#     state_word = "enabled" if self._wifi_enabled else "disabled"
#     if state_word not in cache:
#       return 0.0
#     if self._ground_truth_ssid.lower() not in cache:
#       if self._ground_truth_ssid != "not connected" or "not connected" not in cache:
#         return 0.0
#     return 1.0
#
#   @classmethod
#   def generate_random_params(cls) -> dict[str, Any]:
#     return {}




class Tier4HiddenStatePhoneTemperature(task_eval.TaskEval):
  """Report phone temperature from dumpsys battery. ADB-exclusive."""

  app_names = ("settings",)
  complexity = 1.2
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What is my phone's current temperature? Is it overheating?"
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    res = adb_utils.issue_generic_request(
        ["shell", "dumpsys", "battery"], env.controller
    )
    output = res.generic.output.decode()
    # Parse "temperature: <value>" (in tenths of degrees Celsius)
    m = re.search(r"temperature:\s*(\d+)", output)
    if m:
      self._ground_truth_tenths: int = int(m.group(1))
      self._ground_truth_celsius: float = self._ground_truth_tenths / 10.0
    else:
      self._ground_truth_tenths = 0
      self._ground_truth_celsius = 0.0

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if self._ground_truth_celsius == 0.0:
      return 0.0
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    # Accept temperature in Celsius with ±2°C tolerance
    numbers = re.findall(r"\b\d+\.?\d*\b", cache)
    for n in numbers:
      try:
        val = float(n)
        if abs(val - self._ground_truth_celsius) <= 2.0:
          return 1.0
      except ValueError:
        continue
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}





class Tier4HiddenStateRecentInstalls(task_eval.TaskEval):
  """List the 3 most recently installed apps. ADB-exclusive (dumpsys package)."""

  app_names = ("settings",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What are the 3 most recently installed apps on the device?"
      " Output their package names."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    res = adb_utils.issue_generic_request(
        ["shell", "dumpsys", "package", "packages"], env.controller
    )
    output = res.generic.output.decode()
    # Parse firstInstallTime per package
    pkg_times: list[tuple[str, str]] = []
    current_pkg = ""
    for line in output.split("\n"):
      pkg_match = re.search(r"Package \[(.+?)\]", line)
      if pkg_match:
        current_pkg = pkg_match.group(1)
      time_match = re.search(r"firstInstallTime=(.+)", line)
      if time_match and current_pkg:
        pkg_times.append((current_pkg, time_match.group(1).strip()))
        current_pkg = ""
    # Sort by install time descending (lexicographic works for date strings)
    pkg_times.sort(key=lambda x: x[1], reverse=True)
    self._ground_truth: list[str] = [pkg for pkg, _ in pkg_times[:3]]

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    for pkg in self._ground_truth:
      if pkg not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}




class Tier4HiddenStateUptime(task_eval.TaskEval):
  """Report device uptime in hours and minutes. ADB-exclusive (/proc/uptime)."""

  app_names = ("settings",)
  complexity = 1.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "How long has the device been running since last reboot?"
      " Output the uptime in hours and minutes."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    res = adb_utils.issue_generic_request(
        ["shell", "cat", "/proc/uptime"], env.controller
    )
    output = res.generic.output.decode().strip()
    # /proc/uptime: "12345.67 23456.78" (seconds)
    uptime_sec = float(output.split()[0])
    self._ground_truth_hours: int = int(uptime_sec // 3600)
    self._ground_truth_minutes: int = int((uptime_sec % 3600) // 60)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    numbers = re.findall(r"\b\d+\b", cache)
    int_nums = [int(n) for n in numbers]
    # Allow ±2 minute tolerance due to time elapsed during task
    if self._ground_truth_hours in int_nums:
      for n in int_nums:
        if abs(n - self._ground_truth_minutes) <= 2:
          return 1.0
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}




class Tier4HiddenStateBackgroundLocationApps(task_eval.TaskEval):
  """Report apps that accessed location in background. ADB-exclusive (appops)."""

  app_names = ("settings",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Which apps have recently accessed my location in the background?"
  )

  # Packages we inject background-location-access records for.
  # These must be packages that exist on the emulator.
  _INJECT_PKGS = [
      "com.google.android.gms",
      "com.android.providers.telephony",
  ]

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    import time
    # Inject background location access by granting the op.
    # On API 33 the op name must be fully qualified ("android:coarse_location");
    # the unqualified short name from older Android versions is rejected.
    # The `appops note` subcommand was removed in API 33 — `set allow` is
    # enough for dumpsys to list the package under the op.
    for pkg in self._INJECT_PKGS:
      adb_utils.issue_generic_request(
          ["shell", "appops", "set", pkg, "android:coarse_location", "allow"],
          env.controller,
      )
    time.sleep(1)

    # Read back to confirm and build ground truth
    res = adb_utils.issue_generic_request(
        ["shell", "dumpsys", "appops"], env.controller
    )
    output = res.generic.output.decode()
    self._ground_truth_pkgs: list[str] = list(self._INJECT_PKGS)
    # Also pick up any other packages with location access
    current_pkg = ""
    for line in output.split("\n"):
      pkg_m = re.search(r"Package\s+(\S+):", line)
      if pkg_m:
        current_pkg = pkg_m.group(1)
        continue
      if current_pkg and current_pkg not in self._ground_truth_pkgs:
        if ("coarse_location" in line.lower()
            or "fine_location" in line.lower()):
          if "time=" in line or "Access:" in line:
            self._ground_truth_pkgs.append(current_pkg)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    for pkg in self._INJECT_PKGS:
      adb_utils.issue_generic_request(
          ["shell", "appops", "set", pkg, "android:coarse_location", "default"],
          env.controller,
      )
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth_pkgs:
      return 0.0
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    # Check how many injected packages the agent found
    # We only require the injected ones (deterministic) to be found
    found = 0
    for pkg in self._INJECT_PKGS:
      pkg_lower = pkg.lower()
      if pkg_lower in cache:
        found += 1
      else:
        # Accept last segment match (e.g. "gms", "telephony")
        last_seg = pkg_lower.split(".")[-1]
        if last_seg in cache:
          found += 1
    # Require at least 1 of the injected packages to be mentioned
    return 1.0 if found >= 1 else 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}





class Tier4HiddenStateSignalStrength(task_eval.TaskEval):
  """Report current network signal strength in dBm. ADB-exclusive."""

  app_names = ("settings",)
  complexity = 1.2
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What is my current network signal strength in dBm?"
  )

  # Default signal level to inject if emulator has no real signal
  _MOCK_SIGNAL_LEVEL = 3  # 0-4 scale; maps to ~-85 dBm in emulator

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    # Try to inject a known signal level so the agent has something
    # deterministic to read. `cmd phone set-signal-strength` exists on some
    # API levels but not API 33; tolerate failure since the dumpsys parse
    # below has fallback paths (and ultimately a hard-coded mock).
    try:
      adb_utils.issue_generic_request(
          ["shell", "cmd", "phone", "set-signal-strength",
           "-l", str(self._MOCK_SIGNAL_LEVEL)],
          env.controller,
      )
    except Exception:
      pass
    import time
    time.sleep(1)

    # Now read the actual signal strength
    res = adb_utils.issue_generic_request(
        ["shell", "dumpsys", "telephony.registry"], env.controller
    )
    output = res.generic.output.decode()
    self._ground_truth_dbm: int = 0
    # Try rsrp (LTE)
    m = re.search(r"rsrp\s*=\s*(-?\d+)", output)
    if m:
      val = int(m.group(1))
      if -140 <= val <= -40:
        self._ground_truth_dbm = val
    # Fall back to ss (signal strength)
    if self._ground_truth_dbm == 0:
      m = re.search(r"\bss\s*=\s*(-?\d+)", output)
      if m:
        val = int(m.group(1))
        if -120 <= val <= -20:
          self._ground_truth_dbm = val
    # Fall back to mSignalStrength raw value
    if self._ground_truth_dbm == 0:
      m = re.search(r"mSignalStrength\s*=\s*(-?\d+)", output)
      if m:
        self._ground_truth_dbm = int(m.group(1))
    # Final fallback: use a known mock value that the signal level maps to
    if self._ground_truth_dbm == 0:
      # Level 3 typically maps to ~-85 dBm on Android emulator
      self._ground_truth_dbm = -85

  def tear_down(self, env: interface.AsyncEnv) -> None:
    # Reset signal to default (level 4 = full). Same caveat as initialize:
    # the subcommand may not exist on the running API level.
    try:
      adb_utils.issue_generic_request(
          ["shell", "cmd", "phone", "set-signal-strength", "-l", "4"],
          env.controller,
      )
    except Exception:
      pass
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if self._ground_truth_dbm == 0:
      return 0.0
    cache = (getattr(env, "interaction_cache", "") or "")
    # Look for negative dBm values in output
    numbers = re.findall(r"-?\d+", cache)
    for n in numbers:
      try:
        val = int(n)
        # Accept within ±5 dBm (signal can fluctuate slightly)
        if abs(val - self._ground_truth_dbm) <= 5:
          return 1.0
      except ValueError:
        continue
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}

