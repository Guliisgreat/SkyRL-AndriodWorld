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

"""Unit tests for Tier 4 ADB-exclusive tasks (56 tasks).

Categories:
  A — Compute across items  (Aggregation/TopK)  13 tasks
  B — Bulk operations        (Bulk/Dedup)        11 tasks
  C — Multi-condition filter (Filter/Coverage)   12 tasks
  D — Cross-app correlation  (CrossApp)          10 tasks
  E — Hidden device state    (HiddenState)       10 tasks
"""

from unittest import mock

from absl.testing import absltest
from android_env.proto import adb_pb2
from android_world.env import adb_utils
from android_world.task_evals.common_validators import sms_validators
from android_world.task_evals.utils import sqlite_schema_utils
from android_world.task_evals.utils import sqlite_utils
from skyrl_server.tier4 import broccoli as tier4_broccoli
from skyrl_server.tier4 import calendar as tier4_calendar
from skyrl_server.tier4 import contacts as tier4_contacts
from skyrl_server.tier4 import cross_app as tier4_cross_app
from skyrl_server.tier4 import expense as tier4_expense
from skyrl_server.tier4 import files
from skyrl_server.tier4 import joplin as tier4_joplin
from skyrl_server.tier4 import markor
from skyrl_server.tier4 import opentracks as tier4_opentracks
from skyrl_server.tier4 import retro_music as tier4_retro_music
from skyrl_server.tier4 import sms
from skyrl_server.tier4 import system
from skyrl_server.tier4 import tasks_app as tier4_tasks_app
from android_world.utils import test_utils


# ══════════════════════════════════════════════════════════════════════════
# A — Compute across items (Aggregation / TopK)  13 tests
# ══════════════════════════════════════════════════════════════════════════


class TestTier4AggregationLongestMarkorNote(test_utils.AdbEvalTestBase):
  """Tests for Tier4AggregationLongestMarkorNote."""

  def test_is_successful_when_correct_filename(self):
    """Agent output contains the longest note filename -> success."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "The longest note is longtest_9999.md"
    task = markor.Tier4AggregationLongestMarkorNote({})
    task._ground_truth = "longtest_9999.md"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_wrong_filename(self):
    """Agent output has wrong filename -> fail."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "longtest_1111.md"
    task = markor.Tier4AggregationLongestMarkorNote({})
    task._ground_truth = "longtest_9999.md"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4AggregationDownloadSizeTop3(test_utils.AdbEvalTestBase):
  """Tests for Tier4AggregationDownloadSizeTop3."""

  def test_is_successful_when_total_and_top3_present(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Total: 63488 bytes. Top 3: tier4dl_5_32768.bin tier4dl_4_16384.bin tier4dl_3_8192.bin"
    task = files.Tier4AggregationDownloadSizeTop3({})
    task._ground_truth_total = 63488
    task._ground_truth_top3 = ["tier4dl_5_32768.bin", "tier4dl_4_16384.bin", "tier4dl_3_8192.bin"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_total_wrong(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Total: 999 bytes. Top 3: tier4dl_5_32768.bin tier4dl_4_16384.bin tier4dl_3_8192.bin"
    task = files.Tier4AggregationDownloadSizeTop3({})
    task._ground_truth_total = 63488
    task._ground_truth_top3 = ["tier4dl_5_32768.bin", "tier4dl_4_16384.bin", "tier4dl_3_8192.bin"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4AggregationExpenseCategoryTop3(test_utils.AdbEvalTestBase):
  """Tests for Tier4AggregationExpenseCategoryTop3."""

  def test_is_successful_when_top3_in_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Top 3: Housing, Transportation, Food"
    task = tier4_expense.Tier4AggregationExpenseCategoryTop3({})
    task._ground_truth = ['Housing', 'Transportation', 'Food']
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_category_missing_from_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Housing, Transportation"
    task = tier4_expense.Tier4AggregationExpenseCategoryTop3({})
    task._ground_truth = ['Housing', 'Transportation', 'Food']
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4AggregationExpenseSuspectedDuplicates(test_utils.AdbEvalTestBase):
  """Tests for Tier4AggregationExpenseSuspectedDuplicates."""

  def test_is_successful_when_count_correct(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Found 3 suspected duplicate expenses."
    task = tier4_expense.Tier4AggregationExpenseSuspectedDuplicates({})
    task._ground_truth = 3
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_count_wrong(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Found 2 suspected duplicate expenses."
    task = tier4_expense.Tier4AggregationExpenseSuspectedDuplicates({})
    task._ground_truth = 3
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4AggregationExpenseAllCategorized(test_utils.AdbEvalTestBase):
  """Tests for Tier4AggregationExpenseAllCategorized."""

  def test_is_successful_all_valid(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4AggregationExpenseAllCategorized(
        {"variant": "all_valid"}
    )
    task._uncategorized_names = []
    env.interaction_cache = "all categorized"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_has_uncategorized(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4AggregationExpenseAllCategorized(
        {"variant": "has_uncategorized"}
    )
    task._uncategorized_names = ["cat_missing_0", "cat_missing_1"]
    env.interaction_cache = "cat_missing_0, cat_missing_1 are uncategorized"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4AggregationContactsDuplicatePhones(test_utils.AdbEvalTestBase):
  """Tests for Tier4AggregationContactsDuplicatePhones."""

  def test_is_successful_when_all_dup_names_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "AliceA BobA CarolB DaveB"
    task = tier4_contacts.Tier4AggregationContactsDuplicatePhones({})
    task._dup_names = ["AliceA", "BobA", "CarolB", "DaveB"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_dup_name_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "AliceA BobA"
    task = tier4_contacts.Tier4AggregationContactsDuplicatePhones({})
    task._dup_names = ["AliceA", "BobA", "CarolB", "DaveB"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4AggregationOpenTracksWeeklyStats(test_utils.AdbEvalTestBase):
  """Tests for Tier4AggregationOpenTracksWeeklyStats."""

  def test_is_successful_when_total_and_longest_in_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Total: 22.3 km, longest: Long Run"
    task = tier4_opentracks.Tier4AggregationOpenTracksWeeklyStats({})
    task._ground_truth_total_km = 22.3
    task._ground_truth_longest = 'Long Run'
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_longest_activity_missing_from_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Total: 22.3 km"
    task = tier4_opentracks.Tier4AggregationOpenTracksWeeklyStats({})
    task._ground_truth_total_km = 22.3
    task._ground_truth_longest = 'Long Run'
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4TopKMarkorMostModifiedNotes(test_utils.AdbEvalTestBase):
  """Tests for Tier4TopKMarkorMostModifiedNotes."""

  def test_is_successful_when_all_top5_listed(self):
    """Agent output contains all 5 most-recent filenames -> success."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = (
        "recent_1.md recent_2.md recent_3.md recent_4.md recent_5.md"
    )
    task = markor.Tier4TopKMarkorMostModifiedNotes({})
    task._ground_truth = [
        "recent_1.md", "recent_2.md", "recent_3.md", "recent_4.md", "recent_5.md"
    ]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_one_missing(self):
    """Agent output missing one of the top-5 filenames -> fail."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "recent_1.md recent_2.md recent_3.md recent_4.md"
    task = markor.Tier4TopKMarkorMostModifiedNotes({})
    task._ground_truth = [
        "recent_1.md", "recent_2.md", "recent_3.md", "recent_4.md", "recent_5.md"
    ]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4TopKLargestDownloadFiles(test_utils.AdbEvalTestBase):
  """Tests for Tier4TopKLargestDownloadFiles."""

  def test_is_successful_when_top5_present(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    top5 = [f"tier4top5_{i}.bin" for i in range(5)]
    env.interaction_cache = " ".join(top5)
    task = files.Tier4TopKLargestDownloadFiles({})
    task._ground_truth = top5
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_one_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    top5 = [f"tier4top5_{i}.bin" for i in range(5)]
    env.interaction_cache = " ".join(top5[:4])
    task = files.Tier4TopKLargestDownloadFiles({})
    task._ground_truth = top5
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4TopKSmsThreadsByCount(test_utils.AdbEvalTestBase):
  """Tests for Tier4TopKSmsThreadsByCount."""

  def test_is_successful_when_top3_listed(self):
    """Agent output contains all top-3 numbers -> success."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "5551111111 5552222222 5553333333"
    task = sms.Tier4TopKSmsThreadsByCount({})
    task._ground_truth = ["5551111111", "5552222222", "5553333333"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_one_missing(self):
    """Agent output missing one top-3 number -> fail."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "5551111111 5552222222"
    task = sms.Tier4TopKSmsThreadsByCount({})
    task._ground_truth = ["5551111111", "5552222222", "5553333333"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4TopKExpenseHighestAmount(test_utils.AdbEvalTestBase):
  """Tests for Tier4TopKExpenseHighestAmount."""

  def test_is_successful_when_all_top5_in_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    top5 = [f'expense_amt_{i}' for i in range(5, 10)]
    env.interaction_cache = ", ".join(top5)
    task = tier4_expense.Tier4TopKExpenseHighestAmount({})
    task._ground_truth = top5
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_one_top5_missing_from_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "expense_amt_5, expense_amt_6, expense_amt_7, expense_amt_8"
    task = tier4_expense.Tier4TopKExpenseHighestAmount({})
    task._ground_truth = [f'expense_amt_{i}' for i in range(5, 10)]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4TopKOpenTracksFastestActivity(test_utils.AdbEvalTestBase):
  """Tests for Tier4TopKOpenTracksFastestActivity."""

  def test_is_successful_when_sprint_in_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Fastest activity: Sprint (5.0 m/s)"
    task = tier4_opentracks.Tier4TopKOpenTracksFastestActivity({})
    task._ground_truth = 'Sprint'
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_wrong_activity_in_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Fastest activity: Bike Ride"
    task = tier4_opentracks.Tier4TopKOpenTracksFastestActivity({})
    task._ground_truth = 'Sprint'
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4TopKRetroMusicLongestSongs(test_utils.AdbEvalTestBase):
  """Tests for Tier4TopKRetroMusicLongestSongs."""

  def test_is_successful_when_top5_in_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    top5 = [f'tier4rm_song_{i}' for i in range(5)]
    env.interaction_cache = ", ".join(top5)
    task = tier4_retro_music.Tier4TopKRetroMusicLongestSongs({})
    task._ground_truth = top5
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_song_missing_from_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "tier4rm_song_0, tier4rm_song_1"
    task = tier4_retro_music.Tier4TopKRetroMusicLongestSongs({})
    task._ground_truth = [f'tier4rm_song_{i}' for i in range(5)]
    self.assertEqual(task.is_successful(env), 0.0)


# ══════════════════════════════════════════════════════════════════════════
# B — Bulk operations (Bulk / Dedup)  11 tests
# ══════════════════════════════════════════════════════════════════════════


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


class TestTier4BulkDeleteApkFiles(test_utils.AdbEvalTestBase):
  """Tests for Tier4BulkDeleteApkFiles."""

  def test_is_successful_when_apks_deleted(self):
    res_not_found = adb_pb2.AdbResponse()
    res_not_found.generic.output = b""
    res_found = adb_pb2.AdbResponse()
    res_found.generic.output = b"exists"

    self.mock_issue_generic_request.side_effect = [
        res_not_found, res_not_found, res_not_found, res_not_found,
        res_found, res_found,
    ]

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4BulkDeleteApkFiles({})
    task._apk_files = [f"tier4ext_app_{i}.apk" for i in range(4)]
    task._other_files = ["tier4ext_notes.txt", "tier4ext_photo.jpg"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_apk_still_exists(self):
    res_found = adb_pb2.AdbResponse()
    res_found.generic.output = b"exists"

    self.mock_issue_generic_request.return_value = res_found

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4BulkDeleteApkFiles({})
    task._apk_files = ["tier4ext_app_0.apk"]
    task._other_files = ["tier4ext_notes.txt"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4BulkDeleteSmallExpenses(test_utils.AdbEvalTestBase):
  """Tests for Tier4BulkDeleteSmallExpenses."""

  def setUp(self):
    super().setUp()
    self.mock_get_expenses = mock.patch.object(
        tier4_expense, "_get_expenses"
    ).start()

  def test_is_successful_when_small_deleted(self):
    self.mock_get_expenses.return_value = [
        sqlite_schema_utils.Expense(
            name="normal_0", amount=500, category=3,
            created_date=0, modified_date=0,
        ),
        sqlite_schema_utils.Expense(
            name="normal_1", amount=1000, category=3,
            created_date=0, modified_date=0,
        ),
        sqlite_schema_utils.Expense(
            name="normal_2", amount=2000, category=3,
            created_date=0, modified_date=0,
        ),
    ]
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4BulkDeleteSmallExpenses({})
    task._small_names = ["tiny_0", "tiny_1", "tiny_2"]
    task._keep_names = ["normal_0", "normal_1", "normal_2"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_small_remains(self):
    self.mock_get_expenses.return_value = [
        sqlite_schema_utils.Expense(
            name="tiny_0", amount=50, category=3,
            created_date=0, modified_date=0,
        ),
        sqlite_schema_utils.Expense(
            name="normal_0", amount=500, category=3,
            created_date=0, modified_date=0,
        ),
    ]
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4BulkDeleteSmallExpenses({})
    task._small_names = ["tiny_0", "tiny_1", "tiny_2"]
    task._keep_names = ["normal_0", "normal_1", "normal_2"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4BulkDeleteCalendarTestEvents(test_utils.AdbEvalTestBase):
  """Tests for Tier4BulkDeleteCalendarTestEvents."""

  def test_is_successful_when_test_events_deleted(self):
    """All test event IDs gone, keep IDs still present -> success."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    self.mock_issue_generic_request.return_value = adb_pb2.AdbResponse(
        generic=adb_pb2.AdbResponse.GenericResponse(
            output=b"Row: 0 _id=99\nRow: 1 _id=100\n"
        )
    )
    task = tier4_calendar.Tier4BulkDeleteCalendarTestEvents({})
    task._test_event_ids = ["1", "2", "3"]
    task._keep_event_ids = ["99", "100"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_test_event_still_exists(self):
    """A test event ID is still present -> fail."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    self.mock_issue_generic_request.return_value = adb_pb2.AdbResponse(
        generic=adb_pb2.AdbResponse.GenericResponse(
            output=b"Row: 0 _id=1\nRow: 1 _id=99\n"
        )
    )
    task = tier4_calendar.Tier4BulkDeleteCalendarTestEvents({})
    task._test_event_ids = ["1", "2"]
    task._keep_event_ids = ["99"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4BulkRenameScreenshots(test_utils.AdbEvalTestBase):
  """Tests for Tier4BulkRenameScreenshots."""

  def test_is_successful_when_renamed(self):
    """No Screenshot_* remain and expected renamed files exist -> success."""
    res_no_old = adb_pb2.AdbResponse()
    res_no_old.generic.output = b""
    res_found = adb_pb2.AdbResponse()
    res_found.generic.output = b"/storage/emulated/0/Pictures/20220310_080100.png\n"
    self.mock_issue_generic_request.side_effect = [res_no_old, res_found]

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4BulkRenameScreenshots({})
    task._ground_truth = {"Screenshot_1234.png": "20220310_080100.png"}
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_old_files_remain(self):
    """Screenshot_* files still exist -> fail."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b"/storage/emulated/0/Pictures/Screenshot_1234.png\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4BulkRenameScreenshots({})
    task._ground_truth = {"Screenshot_1234.png": "20220310_080100.png"}
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4BulkMoveLargeFiles(test_utils.AdbEvalTestBase):
  """Tests for Tier4BulkMoveLargeFiles."""

  def test_is_successful_when_moved(self):
    """Large files in Archive and not in Download -> success."""
    res_in_archive = adb_pb2.AdbResponse()
    res_in_archive.generic.output = b"/storage/emulated/0/Archive/large_1234.dat\n"
    res_not_in_download = adb_pb2.AdbResponse()
    res_not_in_download.generic.output = b""
    self.mock_issue_generic_request.side_effect = [
        res_in_archive, res_not_in_download
    ]

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4BulkMoveLargeFiles({})
    task._large_names = ["large_1234.dat"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_not_moved(self):
    """Large files still in Download -> fail."""
    res_not_in_archive = adb_pb2.AdbResponse()
    res_not_in_archive.generic.output = b""
    self.mock_issue_generic_request.return_value = res_not_in_archive

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4BulkMoveLargeFiles({})
    task._large_names = ["large_1234.dat"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4BulkAppendFooterToMarkdown(test_utils.AdbEvalTestBase):
  """Tests for Tier4BulkAppendFooterToMarkdown."""

  def test_is_successful_when_footer_appended(self):
    """All files end with footer -> success."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b"---\nGenerated by AutoBot"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = markor.Tier4BulkAppendFooterToMarkdown({})
    task._filenames = ["note_1234.md", "note_5678.md"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_footer_missing(self):
    """One file missing footer -> fail."""
    res_ok = adb_pb2.AdbResponse()
    res_ok.generic.output = b"---\nGenerated by AutoBot"
    res_fail = adb_pb2.AdbResponse()
    res_fail.generic.output = b"Some other content"
    self.mock_issue_generic_request.side_effect = [res_ok, res_fail]

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = markor.Tier4BulkAppendFooterToMarkdown({})
    task._filenames = ["note_1234.md", "note_5678.md"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4BulkRecategorizeExpense(test_utils.AdbEvalTestBase):
  """Tests for Tier4BulkRecategorizeExpense."""

  def test_is_successful_when_food_changed_to_entertainment(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4BulkRecategorizeExpense({})
    task._food_names = ['food_item_0', 'food_item_1', 'food_item_2', 'food_item_3']
    mock_expenses = []
    for i in range(4):
      e = mock.MagicMock()
      e.name = f'food_item_{i}'
      e.category = 6  # Entertainment
      mock_expenses.append(e)
    with mock.patch('skyrl_server.tier4.expense._get_expenses',
                    return_value=mock_expenses):
      self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_food_not_recategorized(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4BulkRecategorizeExpense({})
    task._food_names = ['food_item_0']
    e = mock.MagicMock()
    e.name = 'food_item_0'
    e.category = 3  # Still Food
    with mock.patch('skyrl_server.tier4.expense._get_expenses',
                    return_value=[e]):
      self.assertEqual(task.is_successful(env), 0.0)


class TestTier4BulkChangePriorityTasks(test_utils.AdbEvalTestBase):
  """Tests for Tier4BulkChangePriorityTasks (overdue -> High)."""

  def test_is_successful_when_overdue_changed_to_high(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_tasks_app.Tier4BulkChangePriorityTasks({})
    task._overdue_titles = [f'overdue_task_{i}' for i in range(4)]
    mock_tasks = []
    for i in range(4):
      t = mock.MagicMock()
      t.title = f'overdue_task_{i}'
      t.importance = 3  # High
      mock_tasks.append(t)
    for i in range(2):
      t = mock.MagicMock()
      t.title = f'future_task_{i}'
      t.importance = 1  # Low (unchanged)
      mock_tasks.append(t)
    with mock.patch('skyrl_server.tier4.tasks_app._get_tasks',
                    return_value=mock_tasks):
      self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_overdue_task_not_changed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_tasks_app.Tier4BulkChangePriorityTasks({})
    task._overdue_titles = ['overdue_task_0']
    t = mock.MagicMock()
    t.title = 'overdue_task_0'
    t.importance = 1  # Still Low
    with mock.patch('skyrl_server.tier4.tasks_app._get_tasks',
                    return_value=[t]):
      self.assertEqual(task.is_successful(env), 0.0)

  def test_fails_when_future_task_changed_to_high(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_tasks_app.Tier4BulkChangePriorityTasks({})
    task._overdue_titles = ['overdue_task_0']
    mock_tasks = [mock.MagicMock(title='overdue_task_0', importance=3)]
    mock_tasks.append(mock.MagicMock(title='future_task_0', importance=3))
    with mock.patch('skyrl_server.tier4.tasks_app._get_tasks',
                    return_value=mock_tasks):
      self.assertEqual(task.is_successful(env), 0.0)


class TestTier4DedupMergeContactsSamePhone(test_utils.AdbEvalTestBase):
  """Tests for Tier4DedupMergeContactsSamePhone."""

  def test_is_successful_when_deleted_names_gone(self):
    """Deleted names absent, kept names present -> success."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b"Row: 0 display_name=Alice\nRow: 1 display_name=Carlos\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_contacts.Tier4DedupMergeContactsSamePhone({})
    task._kept_names = ["Alice", "Carlos"]
    task._deleted_names = ["Zack", "Maria"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_deleted_name_still_present(self):
    """Deleted name still in contacts -> fail."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b"Row: 0 display_name=Zack\nRow: 1 display_name=Alice\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_contacts.Tier4DedupMergeContactsSamePhone({})
    task._kept_names = ["Alice", "Carlos"]
    task._deleted_names = ["Zack", "Maria"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4DedupCalendarDeleteDuplicateEvents(test_utils.AdbEvalTestBase):
  """Tests for Tier4DedupCalendarDeleteDuplicateEvents."""

  def test_is_successful_when_one_copy_each_and_unique_present(self):
    """Each dup pair has exactly 1 remaining; unique events present -> success."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    dup_resp = adb_pb2.AdbResponse(generic=adb_pb2.AdbResponse.GenericResponse(
        output=b"Row: 0 _id=10\n"
    ))
    unique_resp = adb_pb2.AdbResponse(generic=adb_pb2.AdbResponse.GenericResponse(
        output=b"Row: 0 _id=50\nRow: 1 _id=51\n"
    ))
    self.mock_issue_generic_request.side_effect = [
        dup_resp, dup_resp, dup_resp, unique_resp
    ]
    task = tier4_calendar.Tier4DedupCalendarDeleteDuplicateEvents({})
    task._dup_pairs = [
        ("tier4cal_dup_meeting", 1000000),
        ("tier4cal_dup_review", 2000000),
        ("tier4cal_dup_standup", 3000000),
    ]
    task._unique_event_ids = ["50", "51"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_duplicate_still_has_two(self):
    """One dup pair still has 2 events -> fail."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    two_resp = adb_pb2.AdbResponse(generic=adb_pb2.AdbResponse.GenericResponse(
        output=b"Row: 0 _id=10\nRow: 1 _id=11\n"
    ))
    self.mock_issue_generic_request.return_value = two_resp
    task = tier4_calendar.Tier4DedupCalendarDeleteDuplicateEvents({})
    task._dup_pairs = [("tier4cal_dup_meeting", 1000000)]
    task._unique_event_ids = []
    self.assertEqual(task.is_successful(env), 0.0)


# ══════════════════════════════════════════════════════════════════════════
# C — Multi-condition filter (Filter / Coverage)  12 tests
# ══════════════════════════════════════════════════════════════════════════


class TestTier4FilterContactsBirthdayNoPhone(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterContactsBirthdayNoPhone."""

  def test_is_successful_when_names_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "BirthdayOnly0 BirthdayOnly1"
    task = tier4_contacts.Tier4FilterContactsBirthdayNoPhone({})
    task._ground_truth = ["BirthdayOnly0", "BirthdayOnly1"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "BirthdayOnly0"
    task = tier4_contacts.Tier4FilterContactsBirthdayNoPhone({})
    task._ground_truth = ["BirthdayOnly0", "BirthdayOnly1"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4FilterContactsNoFamilyName(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterContactsNoFamilyName."""

  def test_is_successful_when_correct_name(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Dr. Alexandra Montgomery-Harper"
    task = tier4_contacts.Tier4FilterContactsNoFamilyName({})
    task._ground_truth = "Dr. Alexandra Montgomery-Harper"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_wrong_name(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "Al"
    task = tier4_contacts.Tier4FilterContactsNoFamilyName({})
    task._ground_truth = "Dr. Alexandra Montgomery-Harper"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4FilterExpenseHighTravelLastMonth(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterExpenseHighTravelLastMonth."""

  def test_is_successful_when_all_names_in_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "travel_high_0, travel_high_1, travel_high_2"
    task = tier4_expense.Tier4FilterExpenseHighTravelLastMonth({})
    task._ground_truth = ['travel_high_0', 'travel_high_1', 'travel_high_2']
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_name_missing_from_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "travel_high_0, travel_high_1"
    task = tier4_expense.Tier4FilterExpenseHighTravelLastMonth({})
    task._ground_truth = ['travel_high_0', 'travel_high_1', 'travel_high_2']
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4FilterExpenseAboveAverage(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterExpenseAboveAverage."""

  def test_is_successful_when_above_avg_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4FilterExpenseAboveAverage({})
    task._ground_truth = ["aboveavg_3", "aboveavg_4"]
    env.interaction_cache = "aboveavg_3, aboveavg_4"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4FilterJoplinContainsNotContains(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterJoplinContainsNotContains."""

  def test_is_successful_when_correct_titles_in_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "note_a_only_0, note_a_only_1"
    task = tier4_joplin.Tier4FilterJoplinContainsNotContains(
        {'keyword_a': 'project', 'keyword_b': 'urgent'})
    task._ground_truth = ['note_a_only_0', 'note_a_only_1']
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_title_missing_from_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "note_a_only_0"
    task = tier4_joplin.Tier4FilterJoplinContainsNotContains(
        {'keyword_a': 'project', 'keyword_b': 'urgent'})
    task._ground_truth = ['note_a_only_0', 'note_a_only_1']
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4FilterRetroMusicMultiCondition(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterRetroMusicMultiCondition."""

  def test_is_successful_when_all_long_songs_in_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    ground_truth = [f'tier4rm_long_TestArtist_{i}' for i in range(3)]
    env.interaction_cache = ", ".join(ground_truth)
    task = tier4_retro_music.Tier4FilterRetroMusicMultiCondition({'artist': 'TestArtist'})
    task._ground_truth = ground_truth
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_song_missing_from_cache(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = (
        "tier4rm_long_TestArtist_0, tier4rm_long_TestArtist_1"
    )
    task = tier4_retro_music.Tier4FilterRetroMusicMultiCondition({'artist': 'TestArtist'})
    task._ground_truth = [f'tier4rm_long_TestArtist_{i}' for i in range(3)]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4FilterSmsContainingUrl(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterSmsContainingUrl."""

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()

  def test_is_successful_when_url_senders_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4FilterSmsContainingUrl({})
    task._ground_truth = ["5551234567", "5559876543"]
    env.interaction_cache = "5551234567 and 5559876543"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4FilterLargeOldFiles(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterLargeOldFiles."""

  def test_is_successful_when_large_old_files_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4FilterLargeOldFiles({})
    task._ground_truth = ["tier4ext_bigold_video.mp4", "tier4ext_bigold_backup.zip"]
    env.interaction_cache = "tier4ext_bigold_video.mp4, tier4ext_bigold_backup.zip"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_non_matching_included(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4FilterLargeOldFiles({})
    task._ground_truth = ["tier4ext_bigold_video.mp4"]
    env.interaction_cache = "tier4ext_bigold_video.mp4, tier4ext_bigrecent_data.bin"
    self.assertEqual(task.is_successful(env), 0.0)

  def test_fails_when_file_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4FilterLargeOldFiles({})
    task._ground_truth = ["tier4ext_bigold_video.mp4", "tier4ext_bigold_backup.zip"]
    env.interaction_cache = "tier4ext_bigold_video.mp4"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4FilterEmptyFilesInDownloads(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterEmptyFilesInDownloads."""

  def test_is_successful_when_empty_files_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4FilterEmptyFilesInDownloads({})
    task._ground_truth = ["tier4ext_empty_1234.txt", "tier4ext_empty_5678.txt"]
    env.interaction_cache = "tier4ext_empty_1234.txt, tier4ext_empty_5678.txt"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4FilterCalendarWeekendEvents(test_utils.AdbEvalTestBase):
  """Tests for Tier4FilterCalendarWeekendEvents."""

  def test_is_successful_when_weekend_events_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_calendar.Tier4FilterCalendarWeekendEvents({})
    task._ground_truth = ["tier4cal_wkday_5", "tier4cal_wkday_6"]
    env.interaction_cache = "tier4cal_wkday_5, tier4cal_wkday_6"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4CoverageSmsAllFromKnownContacts(test_utils.AdbEvalTestBase):
  """Tests for Tier4CoverageSmsAllFromKnownContacts."""

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()
    mock.patch.object(adb_utils, "delete_contacts").start()

  def test_is_successful_all_known(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4CoverageSmsAllFromKnownContacts({"variant": "all_known"})
    task._unknown_count = 0
    env.interaction_cache = "all known contacts"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_has_unknown(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4CoverageSmsAllFromKnownContacts({"variant": "has_unknown"})
    task._unknown_count = 2
    env.interaction_cache = "2 messages from unknown numbers"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4CoverageCalendarEventsHaveReminders(test_utils.AdbEvalTestBase):
  """Tests for Tier4CoverageCalendarEventsHaveReminders."""

  def test_is_successful_when_no_reminder_titles_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = (
        "Events without reminders: tier4cal_reminder_no_0, tier4cal_reminder_no_1"
    )
    task = tier4_calendar.Tier4CoverageCalendarEventsHaveReminders({})
    task._ground_truth = ["tier4cal_reminder_no_0", "tier4cal_reminder_no_1"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_no_reminder_title_absent(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "All events have reminders"
    task = tier4_calendar.Tier4CoverageCalendarEventsHaveReminders({})
    task._ground_truth = ["tier4cal_reminder_no_0", "tier4cal_reminder_no_1"]
    self.assertEqual(task.is_successful(env), 0.0)


# ══════════════════════════════════════════════════════════════════════════
# D — Cross-app correlation (CrossApp)  10 tests
# ══════════════════════════════════════════════════════════════════════════


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
    task = sms.Tier4CrossAppSmsNumbersNotInContacts({})
    task.initialize_task(env)
    task._ground_truth = {"5551234567", "5559876543"}
    env.interaction_cache = "5551234567, 5559876543"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4CrossAppExpenseToMarkorCalendar(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppExpenseToMarkorCalendar."""

  def test_is_successful_when_note_and_calendar_have_total(self):
    res_note = adb_pb2.AdbResponse()
    res_note.generic.output = b"Total expenses: $77.50"
    res_cal = adb_pb2.AdbResponse()
    res_cal.generic.output = b"Row: 0 title=Monthly Expense: $77.50"
    self.mock_issue_generic_request.side_effect = [res_note, res_cal]

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4CrossAppExpenseToMarkorCalendar({})
    task._ground_truth_dollars = '77.50'
    task._note_path = '/storage/emulated/0/Documents/Markor/monthly_summary.md'
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_note_missing_total(self):
    res_note = adb_pb2.AdbResponse()
    res_note.generic.output = b"This month summary"  # no dollar amount
    self.mock_issue_generic_request.return_value = res_note

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4CrossAppExpenseToMarkorCalendar({})
    task._ground_truth_dollars = '77.50'
    task._note_path = '/storage/emulated/0/Documents/Markor/monthly_summary.md'
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4CrossAppBroccoliToMarkorIndex(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppBroccoliToMarkorIndex."""

  def test_is_successful_when_unreplied_contacts_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_broccoli.Tier4CrossAppBroccoliToMarkorIndex({})
    task._ground_truth = ['Bob Martinez', 'Carol Davis']
    env.interaction_cache = "Bob Martinez, Carol Davis haven't been replied to"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_unreplied_contact_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_broccoli.Tier4CrossAppBroccoliToMarkorIndex({})
    task._ground_truth = ['Bob Martinez', 'Carol Davis']
    env.interaction_cache = "Bob Martinez"
    self.assertEqual(task.is_successful(env), 0.0)

  def test_fails_when_replied_contact_included(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_broccoli.Tier4CrossAppBroccoliToMarkorIndex({})
    task._ground_truth = ['Bob Martinez', 'Carol Davis']
    env.interaction_cache = "Alice Johnson, Bob Martinez, Carol Davis"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4CrossAppMarkorPhonesVsContacts(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppMarkorPhonesVsContacts."""

  def test_is_successful_when_non_contact_numbers_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "+15550009901 +15550009902"
    task = tier4_cross_app.Tier4CrossAppMarkorPhonesVsContacts({})
    task._ground_truth = ["+15550009901", "+15550009902"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_non_contact_number_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "+15550009901"
    task = tier4_cross_app.Tier4CrossAppMarkorPhonesVsContacts({})
    task._ground_truth = ["+15550009901", "+15550009902"]
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4CrossAppCalendarToMarkor(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppCalendarToMarkor."""

  def test_is_successful_when_note_contains_all_titles(self):
    """Note exists and contains all matching event titles -> success."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    titles = ["tier4cal_meeting_item_0", "tier4cal_meeting_item_1", "tier4cal_meeting_item_2"]
    self.mock_issue_generic_request.side_effect = [
        adb_pb2.AdbResponse(generic=adb_pb2.AdbResponse.GenericResponse(
            output=b"/storage/emulated/0/Documents/Markor/meeting_events.md\n"
        )),
        adb_pb2.AdbResponse(generic=adb_pb2.AdbResponse.GenericResponse(
            output="\n".join(titles).encode()
        )),
    ]
    task = tier4_calendar.Tier4CrossAppCalendarToMarkor({"keyword": "meeting"})
    task._keyword = "meeting"
    task._ground_truth = titles
    task._note_path = "/storage/emulated/0/Documents/Markor/meeting_events.md"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_note_missing(self):
    """Note file not found -> fail."""
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    self.mock_issue_generic_request.return_value = adb_pb2.AdbResponse(
        generic=adb_pb2.AdbResponse.GenericResponse(output=b"")
    )
    task = tier4_calendar.Tier4CrossAppCalendarToMarkor({"keyword": "meeting"})
    task._keyword = "meeting"
    task._ground_truth = ["tier4cal_meeting_item_0"]
    task._note_path = "/storage/emulated/0/Documents/Markor/meeting_events.md"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4CrossAppContactsToMarkor(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppContactsToMarkor."""

  def setUp(self):
    super().setUp()
    mock.patch.object(adb_utils, "delete_contacts").start()

  def test_is_successful_when_contacts_in_note(self):
    res = adb_pb2.AdbResponse()
    res.generic.output = b"Alice Smith: +15550001001\nBob Jones: +15550001002\nCarol Lee: +15550001003\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4CrossAppContactsToMarkor({})
    task._contacts = [
        ("Alice Smith", "+15550001001"),
        ("Bob Jones", "+15550001002"),
        ("Carol Lee", "+15550001003"),
    ]
    task._note_path = "/storage/emulated/0/Documents/Markor/contacts_export.md"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4CrossAppCalendarSmsConflicts(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppCalendarSmsConflicts."""

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()

  def test_is_successful_when_conflicting_sms_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4CrossAppCalendarSmsConflicts({})
    task._ground_truth = ["5551112222", "5553334444"]
    env.interaction_cache = "5551112222, 5553334444"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4CrossAppSmsKeywordToTasks(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppSmsKeywordToTasks."""

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()
    self.mock_get_rows = mock.patch.object(
        sqlite_utils, "get_rows_from_remote_device"
    ).start()
    self.mock_delete_rows = mock.patch.object(
        sqlite_utils, "delete_all_rows_from_table"
    ).start()

  def test_is_successful_when_tasks_created(self):
    self.mock_get_rows.return_value = [
        sqlite_schema_utils.Task(
            title="urgent: server down, check immediately",
            importance=0, created=0, modified=0, completed=0,
            deleted=0, dueDate=0,
        ),
        sqlite_schema_utils.Task(
            title="urgent review needed for PR #42",
            importance=0, created=0, modified=0, completed=0,
            deleted=0, dueDate=0,
        ),
    ]
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4CrossAppSmsKeywordToTasks({})
    task._urgent_bodies = [
        "urgent: server down, check immediately",
        "urgent review needed for PR #42",
    ]
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4CrossAppOpenTracksToMarkor(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppOpenTracksToMarkor."""

  def setUp(self):
    super().setUp()
    self.mock_delete_rows = mock.patch.object(
        sqlite_utils, "delete_all_rows_from_table"
    ).start()

  def test_is_successful_when_stats_in_note(self):
    res = adb_pb2.AdbResponse()
    res.generic.output = b"Activities: 3\nTotal distance: 20.2 km\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4CrossAppOpenTracksToMarkor({})
    task._ground_truth_count = 3
    task._ground_truth_km = 20.2
    task._note_path = "/storage/emulated/0/Documents/Markor/weekly_stats.md"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4CrossAppJoplinToCalendar(test_utils.AdbEvalTestBase):
  """Tests for Tier4CrossAppJoplinToCalendar."""

  def setUp(self):
    super().setUp()
    self.mock_delete_rows = mock.patch.object(
        sqlite_utils, "delete_all_rows_from_table"
    ).start()

  def test_is_successful_when_events_created(self):
    res = adb_pb2.AdbResponse()
    res.generic.output = (
        b"Row: 0 title=tier4xa_todo_note_0\n"
        b"Row: 1 title=tier4xa_todo_note_1\n"
    )
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4CrossAppJoplinToCalendar({})
    task._todo_titles = ["tier4xa_todo_note_0", "tier4xa_todo_note_1"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_event_missing(self):
    res = adb_pb2.AdbResponse()
    res.generic.output = b"Row: 0 title=tier4xa_todo_note_0\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4CrossAppJoplinToCalendar({})
    task._todo_titles = ["tier4xa_todo_note_0", "tier4xa_todo_note_1"]
    self.assertEqual(task.is_successful(env), 0.0)


# ══════════════════════════════════════════════════════════════════════════
# E — Hidden device state (HiddenState)  10 tests
# ══════════════════════════════════════════════════════════════════════════


class TestTier4HiddenStateListAppVersions(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateListAppVersions."""

  def test_is_successful_when_answer_matches(self):
    """Agent output contains app names and versions -> success."""
    res = adb_pb2.AdbResponse()
    res.generic.output = b"versionName=2.9.0\nversionCode=123\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateListAppVersions({})
    task.initialize_task(env)
    task._ground_truth = {
        "Markor": "2.9.0",
        "Pro Expense": "1.0",
        "Simple Calendar Pro": "6.0",
    }
    env.interaction_cache = "Markor 2.9.0, Pro Expense 1.0, Simple Calendar Pro 6.0"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4HiddenStateLocationPermissions(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateLocationPermissions."""

  def test_is_successful_when_packages_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "com.example.maps com.example.weather"
    task = system.Tier4HiddenStateLocationPermissions({})
    task._ground_truth = ["com.example.maps", "com.example.weather"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_package_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "com.example.maps"
    task = system.Tier4HiddenStateLocationPermissions({})
    task._ground_truth = ["com.example.maps", "com.example.weather"]
    self.assertEqual(task.is_successful(env), 0.0)

  def test_is_successful_when_none_and_cache_says_none(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "None"
    task = system.Tier4HiddenStateLocationPermissions({})
    task._ground_truth = []
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4HiddenStateAudioRouting(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateAudioRouting."""

  def test_is_successful_when_volume_and_device_present(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "speaker volume 7"
    task = system.Tier4HiddenStateAudioRouting({})
    task._ground_truth_volume = "7"
    task._ground_truth_device = "speaker"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_volume_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "speaker"
    task = system.Tier4HiddenStateAudioRouting({})
    task._ground_truth_volume = "7"
    task._ground_truth_device = "speaker"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4HiddenStateAppsCameraPermission(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateAppsCameraPermission."""

  def test_is_successful_when_packages_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "com.simplemobiletools.camera.pro com.example.scanner"
    task = system.Tier4HiddenStateAppsCameraPermission({})
    task._ground_truth = ["com.simplemobiletools.camera.pro", "com.example.scanner"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_fails_when_package_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "com.simplemobiletools.camera.pro"
    task = system.Tier4HiddenStateAppsCameraPermission({})
    task._ground_truth = ["com.simplemobiletools.camera.pro", "com.example.scanner"]
    self.assertEqual(task.is_successful(env), 0.0)

  def test_is_successful_none_case(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    env.interaction_cache = "None"
    task = system.Tier4HiddenStateAppsCameraPermission({})
    task._ground_truth = []
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4HiddenStatePhoneTemperature(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStatePhoneTemperature."""

  def test_is_successful_when_celsius_matches(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStatePhoneTemperature({})
    task._ground_truth_celsius = 25.0
    env.interaction_cache = "Phone temperature: 25.0 C, not overheating"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_with_tolerance(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStatePhoneTemperature({})
    task._ground_truth_celsius = 25.0
    env.interaction_cache = "Temperature is about 26.5 degrees"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_wrong_temp(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStatePhoneTemperature({})
    task._ground_truth_celsius = 25.0
    env.interaction_cache = "Temperature: 35.0 C"
    self.assertEqual(task.is_successful(env), 0.0)

  def test_is_successful_fails_when_zero(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStatePhoneTemperature({})
    task._ground_truth_celsius = 0.0
    env.interaction_cache = "Temperature: 25.0 C"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4HiddenStateRecentInstalls(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateRecentInstalls."""

  def test_is_successful_when_packages_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateRecentInstalls({})
    task._ground_truth = ["com.app.one", "com.app.two", "com.app.three"]
    env.interaction_cache = "com.app.one, com.app.two, com.app.three"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_one_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateRecentInstalls({})
    task._ground_truth = ["com.app.one", "com.app.two", "com.app.three"]
    env.interaction_cache = "com.app.one, com.app.two"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4HiddenStateUptime(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateUptime."""

  def test_is_successful_when_hours_and_minutes_match(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateUptime({})
    task._ground_truth_hours = 5
    task._ground_truth_minutes = 30
    env.interaction_cache = "Device uptime: 5 hours 30 minutes"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_wrong_hours(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateUptime({})
    task._ground_truth_hours = 5
    task._ground_truth_minutes = 30
    env.interaction_cache = "Device uptime: 3 hours 30 minutes"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4HiddenStateBackgroundLocationApps(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateBackgroundLocationApps."""

  def test_is_successful_when_injected_pkg_found(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateBackgroundLocationApps({})
    task._ground_truth_pkgs = ["com.google.android.gms", "com.android.providers.telephony"]
    env.interaction_cache = "com.google.android.gms accessed location in background"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_when_last_segment_matches(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateBackgroundLocationApps({})
    task._ground_truth_pkgs = ["com.google.android.gms", "com.android.providers.telephony"]
    env.interaction_cache = "gms and telephony accessed location"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_no_pkg_found(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateBackgroundLocationApps({})
    task._ground_truth_pkgs = ["com.google.android.gms", "com.android.providers.telephony"]
    env.interaction_cache = "no apps accessed location"
    self.assertEqual(task.is_successful(env), 0.0)

  def test_is_successful_fails_when_ground_truth_empty(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateBackgroundLocationApps({})
    task._ground_truth_pkgs = []
    env.interaction_cache = "com.google.android.gms"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4HiddenStateSignalStrength(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateSignalStrength."""

  def test_is_successful_when_dbm_matches(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateSignalStrength({})
    task._ground_truth_dbm = -85
    env.interaction_cache = "Signal strength: -85 dBm"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_with_tolerance(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateSignalStrength({})
    task._ground_truth_dbm = -85
    env.interaction_cache = "Signal: -83 dBm"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_wrong_value(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateSignalStrength({})
    task._ground_truth_dbm = -85
    env.interaction_cache = "Signal: -60 dBm"
    self.assertEqual(task.is_successful(env), 0.0)

  def test_is_successful_fails_when_zero(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4HiddenStateSignalStrength({})
    task._ground_truth_dbm = 0
    env.interaction_cache = "Signal: -85 dBm"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4HiddenStateSmsDbSize(test_utils.AdbEvalTestBase):
  """Tests for Tier4HiddenStateSmsDbSize."""

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()

  def test_is_successful_when_bytes_match(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4HiddenStateSmsDbSize({})
    task._ground_truth_bytes = 102400  # 100 KB
    env.interaction_cache = "SMS database size: 102400 bytes"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_when_kb_matches(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4HiddenStateSmsDbSize({})
    task._ground_truth_bytes = 102400  # 100 KB
    env.interaction_cache = "SMS database: 100 KB"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_zero(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4HiddenStateSmsDbSize({})
    task._ground_truth_bytes = 0
    env.interaction_cache = "SMS database: 100 KB"
    self.assertEqual(task.is_successful(env), 0.0)


if __name__ == "__main__":
  absltest.main()
