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
