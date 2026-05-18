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

"""Tier 4 task: unreplied SMS from contacts. ADB-exclusive (SMS × Contacts)."""

import re
import time
from typing import Any

from android_world.env import adb_utils
from android_world.env import interface
from android_world.task_evals import task_eval
from android_world.task_evals.common_validators import sms_validators
from android_world.task_evals.utils import user_data_generation
from android_world.utils import contacts_utils

_SMS_URI = "content://sms"
_SMS_INBOX_URI = "content://sms/inbox"
_SMS_SENT_URI = "content://sms/sent"
_SMS_DB = "/data/data/com.android.providers.telephony/databases/mmssms.db"


def _insert_sms_row_sqlite(address: str, body: str, date_ms: int, type_: int,
                            env: interface.AsyncEnv) -> None:
  """Write an SMS row directly to mmssms.db.

  `content insert --uri content://sms/inbox` is rejected on API 33
  unless the caller is the default SMS app. The provider's read path
  still surfaces sqlite-written rows.
  """
  body_sql = body.replace("'", "''")
  sql = (
      f"INSERT INTO sms (address, body, date, read, type) VALUES "
      f"('{address}', '{body_sql}', {date_ms}, 1, {type_});"
  )
  adb_utils.issue_generic_request(
      ["shell", f'sqlite3 {_SMS_DB} "{sql}"'], env.controller
  )


class Tier4CrossAppBroccoliToMarkorIndex(task_eval.TaskEval):
  """Find contacts who texted me but I haven't replied to. ADB-exclusive."""

  app_names = ("contacts", "simple sms messenger")
  complexity = 2.5
  schema = {'type': 'object', 'properties': {}, 'required': []}
  template = (
      "Which of my contacts texted me but I haven't replied to?"
  )

  def initialize_task(self, env: interface.AsyncEnv) -> None:
    super().initialize_task(env)
    adb_utils.delete_contacts(env.controller)
    sms_validators.clear_sms_and_threads(env.controller)
    time.sleep(2)

    now_ms = int(time.time() * 1000)
    self._ground_truth: list[str] = []

    # Contact A: texted me, I replied → should NOT appear
    num_a = user_data_generation.generate_random_number()
    name_a = "Alice Johnson"
    contacts_utils.add_contact(name_a, num_a, env.controller)
    time.sleep(0.5)
    # Incoming from A
    _insert_sms_row_sqlite(num_a, "Hey are you free tomorrow?",
                            now_ms - 3600000, 1, env)
    # My reply to A (type=2 = sent)
    _insert_sms_row_sqlite(num_a, "Sure, what time?",
                            now_ms - 3000000, 2, env)

    # Contact B: texted me, I did NOT reply → SHOULD appear
    num_b = user_data_generation.generate_random_number()
    name_b = "Bob Martinez"
    contacts_utils.add_contact(name_b, num_b, env.controller)
    time.sleep(0.5)
    _insert_sms_row_sqlite(num_b, "Can you send me the report?",
                            now_ms - 7200000, 1, env)
    self._ground_truth.append(name_b)

    # Contact C: texted me, I did NOT reply → SHOULD appear
    num_c = user_data_generation.generate_random_number()
    name_c = "Carol Davis"
    contacts_utils.add_contact(name_c, num_c, env.controller)
    time.sleep(0.5)
    _insert_sms_row_sqlite(num_c, "Happy birthday!",
                            now_ms - 86400000, 1, env)
    self._ground_truth.append(name_c)

    # Contact D: I texted them, no incoming → should NOT appear
    num_d = user_data_generation.generate_random_number()
    name_d = "David Lee"
    contacts_utils.add_contact(name_d, num_d, env.controller)
    time.sleep(0.5)
    _insert_sms_row_sqlite(num_d, "Meeting at 3pm",
                            now_ms - 1800000, 2, env)

  def tear_down(self, env: interface.AsyncEnv) -> None:
    sms_validators.clear_sms_and_threads(env.controller)
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
    # Ensure replied-to contact is not listed
    if "Alice" in cache:
      return 0.0
    return 1.0

  @classmethod
  def generate_random_params(cls) -> dict[str, Any]:
    return {}
