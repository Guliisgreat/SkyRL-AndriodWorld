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

"""Tier 4 tasks for Contacts - ADB-exclusive."""

import re
import time
import random
from typing import Any

from android_world.env import adb_utils
from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.task_evals.common_validators import sms_validators
from android_world.task_evals.utils import user_data_generation
from android_world.utils import contacts_utils

_RAW_CONTACTS_URI = "content://com.android.contacts/raw_contacts"
_CONTACTS_DATA_URI = "content://com.android.contacts/data"
_CONTACTS_PHONES_URI = "content://contacts/phones/"
_SMS_INBOX_URI = "content://sms/inbox"


# ── Contact creation helpers ───────────────────────────────────────────

def _get_last_raw_contact_id(env: interface.AsyncEnv) -> str:
  """Return the _id of the most recently inserted raw contact."""
  res = adb_utils.issue_generic_request(
      ["shell", "content", "query", "--uri", _RAW_CONTACTS_URI,
       "--projection", "_id", "--sort", "_id DESC"],
      env.controller,
  )
  m = re.search(r"Row: 0 _id=(\d+)", res.generic.output.decode())
  return m.group(1) if m else ""


def _insert_raw_contact(env: interface.AsyncEnv) -> str:
  """Insert a blank raw contact and return its _id."""
  adb_utils.issue_generic_request(
      ["shell", "content", "insert", "--uri", _RAW_CONTACTS_URI],
      env.controller,
  )
  return _get_last_raw_contact_id(env)


def _insert_contact_data(
    raw_id: str, mimetype: str, data1: str, env: interface.AsyncEnv,
    extra_binds: list[str] | None = None,
) -> None:
  """Insert a data row for a raw contact."""
  cmd = ["shell", "content", "insert", "--uri", _CONTACTS_DATA_URI,
         "--bind", f"raw_contact_id:l:{raw_id}",
         "--bind", f"mimetype:s:{mimetype}",
         "--bind", f"data1:s:{data1}"]
  if extra_binds:
    cmd.extend(extra_binds)
  adb_utils.issue_generic_request(cmd, env.controller)


def _add_contact_with_email(
    name: str, phone: str, email: str, env: interface.AsyncEnv
) -> None:
  """Add a contact with name, phone number, and email address."""
  raw_id = _insert_raw_contact(env)
  if not raw_id:
    return
  _insert_contact_data(raw_id, "vnd.android.cursor.item/name", name, env)
  _insert_contact_data(raw_id, "vnd.android.cursor.item/phone_v2", phone, env)
  _insert_contact_data(raw_id, "vnd.android.cursor.item/email_v2", email, env)
  time.sleep(0.5)


def _add_contact_birthday_only(
    name: str, birthday: str, env: interface.AsyncEnv
) -> None:
  """Add a contact with name and birthday but no phone number."""
  raw_id = _insert_raw_contact(env)
  if not raw_id:
    return
  _insert_contact_data(raw_id, "vnd.android.cursor.item/name", name, env)
  _insert_contact_data(
      raw_id, "vnd.android.cursor.item/contact_event", birthday, env,
      extra_binds=["--bind", "data2:i:3"],  # data2=3 → TYPE_BIRTHDAY
  )
  time.sleep(0.5)


def _insert_sms_inbox(
    address: str, body: str, date_ms: int, env: interface.AsyncEnv
) -> None:
  """Insert a received SMS via content provider."""
  adb_utils.issue_generic_request(
      ["shell", "content", "insert", "--uri", _SMS_INBOX_URI,
       "--bind", f"address:s:{address}",
       "--bind", f"body:s:{body}",
       "--bind", f"date:l:{date_ms}",
       "--bind", "read:i:1",
       "--bind", "type:i:1"],
      env.controller,
  )


# ── Task classes ───────────────────────────────────────────────────────

# [EXCLUDED] Removed from Tier 4 benchmark — not registered.
# class Tier4CrossAppContactsNoRecentSms(task_eval.TaskEval):
#   """List contacts with email but no SMS in last 6 months. ADB-exclusive."""
#
#   app_names = ("contacts", "simple sms messenger")
#   complexity = 2.0
#   schema = {"type": "object", "properties": {}, "required": []}
#   template = (
#       "List all contacts that have an email address but have NOT received any"
#       " SMS from them in the last 6 months. Output the contact names."
#   )
#
#   def initialize_task(self, env: interface.AsyncEnv) -> None:
#     super().initialize_task(env)
#     adb_utils.delete_contacts(env.controller)
#     sms_validators.clear_sms_and_threads(env.controller)
#     time.sleep(2)
#
#     now_ms = int(time.time() * 1000)
#     # 2 contacts with email + recent SMS (should NOT appear in output)
#     self._sms_contacts: list[str] = []
#     for i in range(2):
#       name = f"ContactSms{i}"
#       phone = user_data_generation.generate_random_number()
#       _add_contact_with_email(name, phone, f"sms{i}@test.com", env)
#       _insert_sms_inbox(phone, "hello", now_ms, env)
#       self._sms_contacts.append(name)
#
#     # 2 contacts with email + NO SMS (should appear in output)
#     self._ground_truth: list[str] = []
#     for i in range(2):
#       name = f"ContactNoSms{i}"
#       phone = user_data_generation.generate_random_number()
#       _add_contact_with_email(name, phone, f"nosms{i}@test.com", env)
#       self._ground_truth.append(name)
#
#   def tear_down(self, env: interface.AsyncEnv) -> None:
#     adb_utils.delete_contacts(env.controller)
#     sms_validators.clear_sms_and_threads(env.controller)
#     super().tear_down(env)
#
#   def is_successful(self, env: interface.AsyncEnv) -> float:
#     super().is_successful(env)
#     if not self._ground_truth:
#       return 0.0
#     cache = getattr(env, "interaction_cache", "") or ""
#     for name in self._ground_truth:
#       if name not in cache:
#         return 0.0
#     return 1.0
#
#   @classmethod
#   def generate_random_params(cls) -> dict[str, Any]:
#     return {}


class Tier4FilterContactsBirthdayNoPhone(task_eval.TaskEval):
  """List contacts with birthday set but no phone number. ADB-exclusive."""

  app_names = ("contacts",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all contacts that have a birthday set but no phone number."
      " Output the contact names."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    adb_utils.delete_contacts(env.controller)
    time.sleep(2)

    # 3 contacts with birthday + phone (should NOT appear)
    for i in range(3):
      contacts_utils.add_contact(
          f"ContactWithPhone{i}",
          user_data_generation.generate_random_number(),
          env.controller,
      )
      time.sleep(0.5)

    # 2 contacts with birthday only, no phone (should appear)
    self._ground_truth: list[str] = []
    for i in range(2):
      name = f"BirthdayOnly{i}"
      _add_contact_birthday_only(name, f"199{i}-05-15", env)
      self._ground_truth.append(name)

    # 1 contact with phone only (no birthday, no phone-less)
    contacts_utils.add_contact(
        "PhoneOnly",
        user_data_generation.generate_random_number(),
        env.controller,
    )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    adb_utils.delete_contacts(env.controller)
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


class Tier4FilterContactsNoFamilyName(task_eval.TaskEval):
  """List contacts with phone but no family name (first name only). ADB-exclusive."""

  app_names = ("contacts",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all contacts that have a phone number but no family name"
      " (first name only)."
  )

  # Contacts: (display_name, given_name, family_name, has_phone)
  _CONTACTS = [
      ("Alice", "Alice", "", True),         # first-only + phone → MATCH
      ("Bob Smith", "Bob", "Smith", True),   # has family name → NO
      ("Charlie", "Charlie", "", True),      # first-only + phone → MATCH
      ("Diana Prince", "Diana", "Prince", True),  # has family → NO
      ("Eve", "Eve", "", False),             # first-only but NO phone → NO
      ("Frank", "Frank", "", True),          # first-only + phone → MATCH
  ]

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    adb_utils.delete_contacts(env.controller)
    time.sleep(2)
    self._ground_truth: list[str] = []
    for display, given, family, has_phone in self._CONTACTS:
      raw_id = _insert_raw_contact(env)
      if not raw_id:
        continue
      # Insert structured name with given/family
      binds = ["--bind", f"data2:s:{given}"]
      if family:
        binds.extend(["--bind", f"data3:s:{family}"])
      _insert_contact_data(
          raw_id, "vnd.android.cursor.item/name", display, env,
          extra_binds=binds,
      )
      if has_phone:
        phone = user_data_generation.generate_random_number()
        _insert_contact_data(
            raw_id, "vnd.android.cursor.item/phone_v2", phone, env,
        )
      time.sleep(0.5)
      if has_phone and not family:
        self._ground_truth.append(display)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    adb_utils.delete_contacts(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    cache = getattr(env, "interaction_cache", "") or ""
    if not self._ground_truth:
      return 0.0
    for name in self._ground_truth:
      if name not in cache:
        return 0.0
    # Make sure contacts WITH family name are not listed
    for display, _, family, _ in self._CONTACTS:
      if family and display in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4AggregationContactsDuplicatePhones(task_eval.TaskEval):
  """List groups of contacts sharing the same phone number. ADB-exclusive."""

  app_names = ("contacts",)
  complexity = 1.5
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "List all groups of contacts that share the same phone number."
      " Output each group with the shared phone number and the contact names."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    adb_utils.delete_contacts(env.controller)
    time.sleep(2)

    # 2 shared numbers, each with 2 contacts; 1 unique contact
    shared_num_a = user_data_generation.generate_random_number()
    shared_num_b = user_data_generation.generate_random_number()

    self._dup_names: list[str] = []
    for name in ["AliceA", "BobA"]:
      contacts_utils.add_contact(name, shared_num_a, env.controller)
      time.sleep(0.5)
      self._dup_names.append(name)
    for name in ["CarolB", "DaveB"]:
      contacts_utils.add_contact(name, shared_num_b, env.controller)
      time.sleep(0.5)
      self._dup_names.append(name)
    contacts_utils.add_contact(
        "UniqueContact",
        user_data_generation.generate_random_number(),
        env.controller,
    )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    adb_utils.delete_contacts(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._dup_names:
      return 0.0
    cache = getattr(env, "interaction_cache", "") or ""
    for name in self._dup_names:
      if name not in cache:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}


class Tier4DedupMergeContactsSamePhone(task_eval.TaskEval):
  """Merge contacts with same phone, keep alphabetically first. ADB-exclusive."""

  app_names = ("contacts",)
  complexity = 2.0
  schema = {"type": "object", "properties": {}, "required": []}
  template = (
      "Some contacts share the same phone number. Merge them by keeping only"
      " the contact whose name comes first alphabetically and deleting the"
      " others. Output the names you kept."
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    adb_utils.delete_contacts(env.controller)
    time.sleep(2)

    # 2 pairs of duplicates + 1 unique
    shared_num_a = user_data_generation.generate_random_number()
    shared_num_b = user_data_generation.generate_random_number()

    pairs = [
        (shared_num_a, ["Alice", "Zack"]),   # keep Alice
        (shared_num_b, ["Carlos", "Maria"]), # keep Carlos
    ]
    self._kept_names: list[str] = []
    self._deleted_names: list[str] = []
    for num, names in pairs:
      self._kept_names.append(min(names))   # alphabetically first
      self._deleted_names.append(max(names))
      for name in names:
        contacts_utils.add_contact(name, num, env.controller)
        time.sleep(0.5)
    contacts_utils.add_contact(
        "UniqueContact",
        user_data_generation.generate_random_number(),
        env.controller,
    )

  def tear_down(self, env: interface.AsyncEnv) -> None:
    adb_utils.delete_contacts(env.controller)
    super().tear_down(env)

  def is_successful(self, env: interface.AsyncEnv) -> float:
    super().is_successful(env)
    if not self._deleted_names:
      return 0.0
    res = adb_utils.issue_generic_request(
        ["shell", "content", "query", "--uri", _CONTACTS_PHONES_URI,
         "--projection", "display_name"],
        env.controller,
    )
    output = res.generic.output.decode()
    for name in self._deleted_names:
      if name in output:
        return 0.0
    for name in self._kept_names:
      if name not in output:
        return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
