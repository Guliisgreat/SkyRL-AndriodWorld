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

"""Tier 4 tasks for SMS - ADB-exclusive."""

import random
import re
import time
from typing import Any

from android_world.env import adb_utils
from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.task_evals.common_validators import sms_validators
from android_world.task_evals.utils import user_data_generation
from android_world.utils import contacts_utils


def _count_unread_sms(env: interface.AsyncEnv) -> int:
  """Count unread SMS via content query."""
  res = adb_utils.issue_generic_request(
      [
          "shell",
          "content",
          "query",
          "--uri",
          "content://sms/inbox",
          "--projection",
          "_id",
          "--where",
          "read=0",
      ],
      env.controller,
  )
  output = res.generic.output.decode()
  if "No result found" in output or not output.strip():
    return 0
  return len(output.strip().split("\n"))


class Tier4AggregationCountUnreadSMS(task_eval.TaskEval):
  """Count total unread SMS. ADB-exclusive: GUI cannot prove completeness."""

  app_names = ("simple sms messenger",)
  complexity = 1.2
  schema = {"type": "object", "properties": {}, "required": []}
  template = "How many unread SMS messages do you have in total?"

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    sms_validators.clear_sms_and_threads(env.controller)
    time.sleep(2)
    # Send 5-7 SMS to device via text_emulator (creates received/unread)
    n = 5 + (hash(str(self.params)) % 3)  # Deterministic 5-7
    for _ in range(n):
      adb_utils.text_emulator(
          env.controller,
          user_data_generation.generate_random_number(),
          "test msg",
      )
      time.sleep(1)
    self._ground_truth = _count_unread_sms(env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    try:
      # Try to extract number from agent output
      numbers = re.findall(r"\b\d+\b", cache)
      for n in numbers:
        if int(n) == self._ground_truth:
          return 1.0
    except (ValueError, TypeError):
      pass
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4CrossAppSmsNumbersNotInContacts(task_eval.TaskEval):
  """List SMS numbers from last 7 days not in Contacts. ADB-exclusive."""

  app_names = ("simple sms messenger", "contacts")
  complexity = 2.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all phone numbers you have received SMS from in the last 7 days"
      " that are NOT in your contacts. Output the numbers."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    adb_utils.delete_contacts(env.controller)
    sms_validators.clear_sms_and_threads(env.controller)
    time.sleep(2)
    # Add 1 contact (number that will receive SMS - for noise)
    self._contact_number = user_data_generation.generate_random_number()
    contacts_utils.add_contact("ContactA", self._contact_number, env.controller)
    time.sleep(2)
    # Numbers NOT in contacts
    self._not_in_contacts = [
        user_data_generation.generate_random_number() for _ in range(2)
    ]
    # Send SMS from not-in-contacts numbers
    for num in self._not_in_contacts:
      adb_utils.text_emulator(env.controller, num, "msg from unknown")
      time.sleep(1)
    # Send SMS from in-contacts number (noise)
    adb_utils.text_emulator(env.controller, self._contact_number, "msg from contact")
    time.sleep(1)
    self._ground_truth = set(
        n.replace("-", "").replace(" ", "") for n in self._not_in_contacts
    )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
    adb_utils.delete_contacts(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    cache_clean = cache.replace("-", "").replace(" ", "")
    for num in self._ground_truth:
      if num not in cache_clean:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


_SMS_INBOX_URI = "content://sms/inbox"
_SMS_DB = "/data/data/com.android.providers.telephony/databases/mmssms.db"


def _insert_sms_inbox(
    address: str, body: str, date_ms: int, env: interface.AsyncEnv
) -> None:
  """Insert an SMS into the inbox via content provider."""
  adb_utils.issue_generic_request(
      ["shell", "content", "insert", "--uri", _SMS_INBOX_URI,
       "--bind", f"address:s:{address}",
       "--bind", f"body:s:{body}",
       "--bind", f"date:l:{date_ms}",
       "--bind", "read:i:1",
       "--bind", "type:i:1"],
      env.controller,
  )


class Tier4FilterDeleteOldNonContactKeywordSms(task_eval.TaskEval):
  """Delete SMS: >30 days + non-contact + keyword. ADB-exclusive (3-condition AND)."""

  app_names = ("simple sms messenger", "contacts")
  complexity = 2.0
  schema = {
      "type": "object",
      "properties": {"keyword": {"type": "string"}},
      "required": ["keyword"],
  }
  template = (
      "Delete all SMS messages that meet ALL of these conditions:\n"
      "1. Older than 30 days\n"
      "2. From a number NOT in your contacts\n"
      "3. Contains the word '{keyword}'\n"
      "Do not delete messages that fail any of these conditions."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    sms_validators.clear_sms_and_threads(env.controller)
    adb_utils.delete_contacts(env.controller)
    time.sleep(2)

    keyword = self.params.get("keyword", "promo")
    self._keyword = keyword
    now_ms = int(time.time() * 1000)
    old_ms = now_ms - (35 * 24 * 3600 * 1000)  # 35 days ago

    # 1 contact (SMS from them should survive even if old + keyword)
    self._contact_num = user_data_generation.generate_random_number()
    contacts_utils.add_contact("TestContact", self._contact_num, env.controller)
    time.sleep(1)

    # SMS to DELETE: old + non-contact + keyword
    self._to_delete_nums: list[str] = []
    for _ in range(3):
      num = user_data_generation.generate_random_number()
      _insert_sms_inbox(num, f"Get {keyword} deal now!", old_ms, env)
      self._to_delete_nums.append(num)

    # SMS to KEEP: recent + non-contact + keyword (not old enough)
    _insert_sms_inbox(
        user_data_generation.generate_random_number(),
        f"Special {keyword} offer today",
        now_ms, env,
    )
    # SMS to KEEP: old + from contact + keyword (is a contact)
    _insert_sms_inbox(self._contact_num, f"Hello {keyword}", old_ms, env)
    # SMS to KEEP: old + non-contact + no keyword
    _insert_sms_inbox(
        user_data_generation.generate_random_number(),
        "Hello how are you",
        old_ms, env,
    )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
    adb_utils.delete_contacts(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    old_threshold_ms = int(time.time() * 1000) - (30 * 24 * 3600 * 1000)
    res = adb_utils.issue_generic_request(
        ["shell", "content", "query", "--uri", _SMS_INBOX_URI,
         "--projection", "address,body,date"],
        env.controller,
    )
    output = res.generic.output.decode()
    for num in self._to_delete_nums:
      norm = num.replace("-", "").replace(" ", "")
      for line in output.split("\n"):
        if norm in line and self._keyword in line:
          date_m = re.search(r"date=(\d+)", line)
          if date_m and int(date_m.group(1)) < old_threshold_ms:
            return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {"keyword": random.choice(["promo", "sale", "offer", "deal"])}


class Tier4TopKSmsThreadsByCount(task_eval.TaskEval):
  """Which 3 numbers have the most SMS messages? ADB-exclusive."""

  app_names = ("simple sms messenger",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Which 3 phone numbers have the most SMS messages in your inbox?"
      " List their phone numbers."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    sms_validators.clear_sms_and_threads(env.controller)
    time.sleep(2)

    now_ms = int(time.time() * 1000)
    counts = [7, 5, 4, 2, 1]
    random.shuffle(counts)
    self._num_counts: list[tuple[str, int]] = []
    for count in counts:
      num = user_data_generation.generate_random_number()
      for i in range(count):
        _insert_sms_inbox(num, f"message {i}", now_ms - i * 1000, env)
      self._num_counts.append((num, count))

    self._ground_truth: list[str] = [
        num for num, _ in sorted(
            self._num_counts, key=lambda x: x[1], reverse=True
        )[:3]
    ]

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    cache_clean = cache.replace("-", "").replace(" ", "")
    for num in self._ground_truth:
      norm = num.replace("-", "").replace(" ", "")
      if norm not in cache_clean:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


_SMS_INBOX_URI_COVERAGE = "content://sms/inbox"


class Tier4CoverageAllSmsRead(task_eval.TaskEval):
  """Confirm all SMS are read; if any unread, report the count. ADB-exclusive.

  Two variants:
    - all_read: messages already marked read → agent should report 0
    - has_unread: 3 unread messages → agent should report 3
  """

  app_names = ("simple sms messenger",)
  complexity = 1.2
  schema = {
      "type": "object",
      "properties": {"variant": {"type": "string", "enum": ["all_read", "has_unread"]}},
      "required": ["variant"],
  }
  template = (
      "Confirm that all SMS messages have been read (no unread messages remain)."
      " If any are unread, output how many. If all are read, output '0' or 'all read'."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    sms_validators.clear_sms_and_threads(env.controller)
    variant = self.params.get("variant", "has_unread")
    self._variant = variant
    now_ms = int(time.time() * 1000)
    for i in range(3):
      adb_utils.issue_generic_request(
          ["shell", "content", "insert", "--uri", _SMS_INBOX_URI_COVERAGE,
           "--bind", f"address:s:+1555000{i:04d}",
           "--bind", f"body:s:Test message {i}",
           "--bind", f"date:l:{now_ms - i * 60000}",
           "--bind", "read:i:0", "--bind", "type:i:1"],
          env.controller,
      )
    if variant == "all_read":
      adb_utils.issue_generic_request(
          ["shell", "content", "update", "--uri", _SMS_INBOX_URI_COVERAGE,
           "--bind", "read:i:1"],
          env.controller,
      )
      self._ground_truth: int = 0
    else:
      self._ground_truth = 3

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    if self._ground_truth == 0:
      return 1.0 if ("0" in cache or "none" in cache or "all read" in cache) else 0.0
    return 1.0 if str(self._ground_truth) in cache else 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {"variant": random.choice(["all_read", "has_unread"])}


# ── tier4_extra ──────────────────────────────────────────────────────────


class Tier4ExtraAggregationSmsAvgLength(task_eval.TaskEval):
  """Average character length of all inbox SMS. ADB-exclusive (aggregation)."""

  app_names = ("simple sms messenger",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What is the average character length of all SMS messages in your inbox?"
      " Output the number (rounded to nearest integer)."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    sms_validators.clear_sms_and_threads(env.controller)
    time.sleep(2)
    now_ms = int(time.time() * 1000)
    bodies = [
        "Hi",                           # 2
        "How are you doing today?",     # 24
        "Meeting at 3pm tomorrow",      # 24
        "Please send the report ASAP. We need it before the deadline.",  # 58
        "ok",                           # 2
    ]
    for i, body in enumerate(bodies):
      _insert_sms_inbox(
          user_data_generation.generate_random_number(),
          body, now_ms - i * 60000, env,
      )
    total = sum(len(b) for b in bodies)
    self._ground_truth: int = round(total / len(bodies))

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    numbers = re.findall(r"\b\d+\b", cache)
    for n in numbers:
      if abs(int(n) - self._ground_truth) <= 2:
        return 1.0
    return 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraFilterSmsContainingUrl(task_eval.TaskEval):
  """List SMS messages that contain a URL. ADB-exclusive (content query + regex)."""

  app_names = ("simple sms messenger",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all SMS messages in the inbox that contain a URL (http:// or"
      " https://). Output the sender phone numbers."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    sms_validators.clear_sms_and_threads(env.controller)
    time.sleep(2)
    now_ms = int(time.time() * 1000)
    self._ground_truth: list[str] = []
    # SMS WITH URLs
    url_sms = [
        ("Check this out https://example.com/page", None),
        ("Visit http://test.org for details", None),
    ]
    for body, _ in url_sms:
      num = user_data_generation.generate_random_number()
      _insert_sms_inbox(num, body, now_ms, env)
      self._ground_truth.append(num.replace("-", "").replace(" ", ""))
      now_ms -= 60000
    # SMS WITHOUT URLs
    for body in ["Hello there", "Meeting at 3pm", "Thanks!"]:
      num = user_data_generation.generate_random_number()
      _insert_sms_inbox(num, body, now_ms, env)
      now_ms -= 60000

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    cache_clean = cache.replace("-", "").replace(" ", "")
    for num in self._ground_truth:
      if num not in cache_clean:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraTopKSmsOldestMessages(task_eval.TaskEval):
  """List the 3 oldest SMS messages by date. ADB-exclusive."""

  app_names = ("simple sms messenger",)
  complexity = 1.2
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "What are the 3 oldest SMS messages in your inbox?"
      " List the sender phone numbers."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    sms_validators.clear_sms_and_threads(env.controller)
    time.sleep(2)
    now_ms = int(time.time() * 1000)
    # 7 messages with varying dates
    offsets_days = [0, 1, 5, 15, 30, 60, 90]
    random.shuffle(offsets_days)
    named: list[tuple[str, int]] = []
    for offset in offsets_days:
      num = user_data_generation.generate_random_number()
      date_ms = now_ms - offset * 86400 * 1000
      _insert_sms_inbox(num, f"msg from {offset} days ago", date_ms, env)
      named.append((num.replace("-", "").replace(" ", ""), date_ms))
    named.sort(key=lambda x: x[1])
    self._ground_truth: list[str] = [n for n, _ in named[:3]]

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    cache_clean = cache.replace("-", "").replace(" ", "")
    for num in self._ground_truth:
      if num not in cache_clean:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


# ── tier4_extra ──


class Tier4ExtraCoverageSmsAllFromKnownContacts(task_eval.TaskEval):
  """Verify whether all inbox SMS are from known contacts. ADB-exclusive (cross-check)."""

  app_names = ("simple sms messenger", "contacts")
  complexity = 1.5
  schema = {
      "type": "object",
      "properties": {"variant": {"type": "string", "enum": ["all_known", "has_unknown"]}},
      "required": ["variant"],
  }
  template = (
      "Are all SMS messages in the inbox from phone numbers that are in your"
      " contacts? If yes, output 'all known'. If not, output how many are from"
      " unknown numbers."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    sms_validators.clear_sms_and_threads(env.controller)
    adb_utils.delete_contacts(env.controller)
    time.sleep(2)
    variant = self.params.get("variant", "has_unknown")
    now_ms = int(time.time() * 1000)

    # Add 3 contacts and send SMS from each
    contact_nums: list[str] = []
    for i in range(3):
      num = user_data_generation.generate_random_number()
      contacts_utils.add_contact(f"Contact{i}", num, env.controller)
      time.sleep(0.5)
      _insert_sms_inbox(num, f"hello from contact {i}", now_ms - i * 60000, env)
      contact_nums.append(num)

    if variant == "has_unknown":
      # Add 2 SMS from unknown numbers
      self._unknown_count: int = 2
      for i in range(2):
        num = user_data_generation.generate_random_number()
        _insert_sms_inbox(num, f"unknown msg {i}", now_ms - (i + 5) * 60000, env)
    else:
      self._unknown_count = 0

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
    adb_utils.delete_contacts(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = (getattr(env, "interaction_cache", "") or "").lower()
    if self._unknown_count == 0:
      return 1.0 if ("all known" in cache or "all" in cache and "known" in cache) else 0.0
    return 1.0 if str(self._unknown_count) in cache else 0.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {"variant": random.choice(["all_known", "has_unknown"])}
