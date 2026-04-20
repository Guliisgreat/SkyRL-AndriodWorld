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


# ── tier4_extra ──────────────────────────────────────────────────────────


class Tier4ExtraHiddenStateRemainingStorage(task_eval.TaskEval):
  """Report remaining storage space on /data. ADB-exclusive (df)."""

  app_names = ("settings",)
  complexity = 1.2
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "How much free storage space is remaining on the device (internal"
      " storage)? Output the amount in GB (rounded to 1 decimal place)."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    res = adb_utils.issue_generic_request(
        ["shell", "df", "/data"], env.controller
    )
    output = res.generic.output.decode()
    # df output: Filesystem  1K-blocks  Used  Available  Use%  Mounted on
    lines = [l for l in output.strip().split("\n") if "/data" in l]
    if lines:
      parts = lines[0].split()
      # Available is typically the 4th column (index 3) in 1K-blocks
      try:
        avail_kb = int(parts[3])
        self._ground_truth_gb: float = round(avail_kb / (1024 * 1024), 1)
      except (IndexError, ValueError):
        self._ground_truth_gb = 0.0
    else:
      self._ground_truth_gb = 0.0

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    # Check for the GB number with tolerance ±0.5 GB
    numbers = re.findall(r"\b\d+\.?\d*\b", cache)
    for n in numbers:
      try:
        if abs(float(n) - self._ground_truth_gb) <= 0.5:
          return 1.0
      except ValueError:
        continue
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# Backward-compatible alias for old class name
Tier4ExtraHiddenStateBatteryHealth = Tier4ExtraHiddenStateRemainingStorage


# ── tier4_extra ──


class Tier4ExtraHiddenStateRecentInstalls(task_eval.TaskEval):
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


# ── tier4_extra ──


class Tier4ExtraHiddenStateUptime(task_eval.TaskEval):
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


# ── tier4_extra ──


class Tier4ExtraHiddenStateBatteryDrain(task_eval.TaskEval):
  """Report the app that consumed the most battery. ADB-exclusive (dumpsys)."""

  app_names = ("settings",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Which app has consumed the most battery since last full charge?"
      " Output the app package name and its estimated battery usage"
      " percentage."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    res = adb_utils.issue_generic_request(
        ["shell", "dumpsys", "batterystats"], env.controller
    )
    output = res.generic.output.decode()
    # Parse "Uid <uid> <pkg>: <pct>" from Estimated power use section
    pkg_pcts: list[tuple[str, float]] = []
    in_section = False
    for line in output.split("\n"):
      if "Estimated power use" in line:
        in_section = True
        continue
      if in_section:
        if line.strip() == "" or line.startswith("  ") is False:
          if pkg_pcts:
            break
        # Match lines like "    Uid 10123: 15.2 ( cpu=10.1 ... )"
        m = re.search(r"Uid\s+\S+:\s+(\d+\.?\d*)", line)
        if m:
          pct = float(m.group(1))
          # Try to get package name from same line or uid mapping
          pkg_m = re.search(r"Uid\s+(\S+):", line)
          if pkg_m:
            uid_str = pkg_m.group(1)
            pkg_pcts.append((uid_str, pct))
    # Also try the simpler per-app format
    if not pkg_pcts:
      for line in output.split("\n"):
        m = re.search(r"^\s+Uid\s+(\S+):\s+(\d+\.?\d*)", line)
        if m:
          pkg_pcts.append((m.group(1), float(m.group(2))))
    if pkg_pcts:
      pkg_pcts.sort(key=lambda x: x[1], reverse=True)
      self._ground_truth_pkg: str = pkg_pcts[0][0]
      self._ground_truth_pct: float = pkg_pcts[0][1]
    else:
      self._ground_truth_pkg = ""
      self._ground_truth_pct = 0.0

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth_pkg:
      return 0.0
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    # Check the package name (or last segment) appears
    pkg_lower = self._ground_truth_pkg.lower()
    if pkg_lower not in cache:
      last_seg = pkg_lower.split(".")[-1] if "." in pkg_lower else pkg_lower
      if last_seg not in cache:
        return 0.0
    # Check the percentage is approximately correct (±2%)
    numbers = re.findall(r"\b\d+\.?\d*\b", cache)
    for n in numbers:
      try:
        if abs(float(n) - self._ground_truth_pct) <= 2.0:
          return 1.0
      except ValueError:
        continue
    # If the package is found, accept even without exact percentage
    return 0.5

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# Backward-compatible alias for old class name
Tier4ExtraHiddenStateDisabledApps = Tier4ExtraHiddenStateBatteryDrain


# ── tier4_extra ──


class Tier4ExtraHiddenStateMobileDataUsage(task_eval.TaskEval):
  """Report which app used the most mobile data. ADB-exclusive (netstats)."""

  app_names = ("settings",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Which app has used the most mobile data (cellular data) on the device?"
      " Output the app package name and approximate data usage in MB."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    # Get per-uid mobile data usage
    res = adb_utils.issue_generic_request(
        ["shell", "dumpsys", "netstats", "detail"], env.controller
    )
    output = res.generic.output.decode()
    # Parse uid-level rx/tx bytes from the mobile (ident) section
    uid_bytes: dict[str, int] = {}
    current_uid = ""
    in_mobile = False
    for line in output.split("\n"):
      # Look for mobile interface section
      if "iface=" in line and ("rmnet" in line or "ccmni" in line or "mobile" in line.lower()):
        in_mobile = True
        uid_m = re.search(r"uid=(\d+)", line)
        if uid_m:
          current_uid = uid_m.group(1)
      elif "iface=" in line:
        in_mobile = False
        current_uid = ""
      if in_mobile and current_uid:
        rx_m = re.search(r"rxBytes=(\d+)", line)
        tx_m = re.search(r"txBytes=(\d+)", line)
        total = 0
        if rx_m:
          total += int(rx_m.group(1))
        if tx_m:
          total += int(tx_m.group(1))
        if total > 0:
          uid_bytes[current_uid] = uid_bytes.get(current_uid, 0) + total
    # Map UID to package name
    best_uid = ""
    best_bytes = 0
    for uid, total in uid_bytes.items():
      if total > best_bytes:
        best_bytes = total
        best_uid = uid
    if best_uid:
      pkg_res = adb_utils.issue_generic_request(
          ["shell", "pm", "list", "packages", "--uid", best_uid],
          env.controller,
      )
      pkg_out = pkg_res.generic.output.decode().strip()
      m = re.search(r"package:(\S+)", pkg_out)
      self._ground_truth_pkg: str = m.group(1) if m else best_uid
      self._ground_truth_mb: float = round(best_bytes / (1024 * 1024), 1)
    else:
      self._ground_truth_pkg = ""
      self._ground_truth_mb = 0.0

  def tear_down(self, env: interface.AsyncEnv) -> None:
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._ground_truth_pkg:
      return 0.0
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    pkg_lower = self._ground_truth_pkg.lower()
    if pkg_lower not in cache:
      last_seg = pkg_lower.split(".")[-1] if "." in pkg_lower else pkg_lower
      if last_seg not in cache:
        return 0.0
    # Check MB within tolerance ±5 MB
    numbers = re.findall(r"\b\d+\.?\d*\b", cache)
    for n in numbers:
      try:
        if abs(float(n) - self._ground_truth_mb) <= 5.0:
          return 1.0
      except ValueError:
        continue
    # Package found but no matching MB — partial credit
    return 0.5

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# Backward-compatible alias for old class name
Tier4ExtraHiddenStateAppStorageUsage = Tier4ExtraHiddenStateMobileDataUsage
