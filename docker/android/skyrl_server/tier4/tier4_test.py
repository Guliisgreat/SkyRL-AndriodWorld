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

"""Unit tests for Tier 4 ADB-exclusive tasks."""

from unittest import mock

from absl.testing import absltest
from android_env.proto import adb_pb2
from android_world.env import adb_utils
from android_world.task_evals.common_validators import sms_validators
from skyrl_server.tier4 import files
from skyrl_server.tier4 import sms
from skyrl_server.tier4 import system
from android_world.utils import test_utils


class TestTier4BulkDeleteTmpInDownloads(test_utils.AdbEvalTestBase):
  """Tests for Tier4BulkDeleteTmpInDownloads."""

  def test_is_successful_when_no_tmp_files(self):
    """When find returns empty, task succeeds."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b""  # No .tmp files
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4BulkDeleteTmpInDownloads({})
    self.assertEqual(test_utils.perform_task(task, env), 1.0)

  def test_is_successful_when_tmp_files_remain(self):
    """When find returns .tmp files, task fails."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b"/storage/emulated/0/Download/foo.tmp\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4BulkDeleteTmpInDownloads({})
    self.assertEqual(test_utils.perform_task(task, env), 0.0)


class TestTier4CoverageNoTmpInDownloads(test_utils.AdbEvalTestBase):
  """Tests for Tier4CoverageNoTmpInDownloads."""

  def test_is_successful_empty_variant_expects_none(self):
    """Empty variant: agent outputs 'None' or '0' -> success."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b""  # No files
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "None"
    task = files.Tier4CoverageNoTmpInDownloads({"variant": "empty"})
    task.initialize_task(env)
    self.assertEqual(task.is_successful(env), 1.0)
    task.tear_down(env)

  def test_is_successful_empty_variant_expects_zero(self):
    """Empty variant: agent outputs '0' -> success."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b""
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "0"
    task = files.Tier4CoverageNoTmpInDownloads({"variant": "empty"})
    task.initialize_task(env)
    self.assertEqual(task.is_successful(env), 1.0)
    task.tear_down(env)

  def test_is_successful_has_tmp_variant_lists_files(self):
    """Has_tmp variant: agent lists created files -> success."""
    res_with_files = adb_pb2.AdbResponse()
    res_with_files.generic.output = b"/path/check_123.tmp\n/path/check_456.tmp"
    self.mock_issue_generic_request.return_value = res_with_files

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4CoverageNoTmpInDownloads({"variant": "has_tmp"})
    task.initialize_task(env)
    # Agent output must contain all ground truth filenames
    env.interaction_cache = " ".join(task._ground_truth)
    self.assertEqual(task.is_successful(env), 1.0)
    task.tear_down(env)


class TestTier4HiddenStateListAppVersions(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateListAppVersions."""

  def test_is_successful_when_answer_matches(self):
    """Agent output contains app names and versions -> success."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b"versionName=2.9.0\nversionCode=123\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Markor 2.9.0, Pro Expense 1.0, Simple Calendar Pro 6.0"
    task = system.Tier4HiddenStateListAppVersions({})
    task.initialize_task(env)
    task._ground_truth = {
        "Markor": "2.9.0",
        "Pro Expense": "1.0",
        "Simple Calendar Pro": "6.0",
    }
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4AggregationCountUnreadSMS(test_utils.AdbEvalTestBase):
  """Tests for Tier4AggregationCountUnreadSMS."""

  def setUp(self):
    super().setUp()
    self.mock_text_emulator = mock.patch.object(
        adb_utils, "text_emulator"
    ).start()
    self.mock_clear_sms = mock.patch.object(
        sms_validators, "clear_sms_and_threads"
    ).start()

  def test_is_successful_when_count_matches(self):
    """Agent outputs correct unread count -> success."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "6"
    task = sms.Tier4AggregationCountUnreadSMS({})
    task.initialize_task(env)
    # Override ground truth (normally from _count_unread_sms)
    task._ground_truth = 6
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4CrossAppSmsNumbersNotInContacts(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppSmsNumbersNotInContacts."""

  def setUp(self):
    super().setUp()
    mock.patch.object(adb_utils, "delete_contacts").start()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()
    mock.patch.object(adb_utils, "text_emulator").start()

  def test_is_successful_when_numbers_listed(self):
    """Agent lists non-contact numbers -> success."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "5551234567, 5559876543"
    task = sms.Tier4CrossAppSmsNumbersNotInContacts({})
    task.initialize_task(env)
    # Override ground truth (normally from setup)
    task._ground_truth = {"5551234567", "5559876543"}
    self.assertEqual(task.is_successful(env), 1.0)


if __name__ == "__main__":
  absltest.main()
