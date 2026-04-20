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

"""Unit tests for tier4_extra tasks."""

from unittest import mock

from absl.testing import absltest
from android_env.proto import adb_pb2
from android_world.env import adb_utils
from android_world.task_evals.common_validators import sms_validators
from android_world.task_evals.utils import sqlite_schema_utils
from android_world.task_evals.utils import sqlite_utils
from skyrl_server.tier4 import calendar as tier4_calendar
from skyrl_server.tier4 import cross_app as tier4_cross_app
from skyrl_server.tier4 import expense as tier4_expense
from skyrl_server.tier4 import files
from skyrl_server.tier4 import sms
from skyrl_server.tier4 import system
from android_world.utils import test_utils


# ── System tier4_extra tests ─────────────────────────────────────────────


class TestTier4ExtraHiddenStateRemainingStorage(test_utils.AdbEvalTestBase):

  def test_is_successful_when_gb_matches(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateRemainingStorage({})
    task._ground_truth_gb = 12.3
    env.interaction_cache = "Free storage: 12.3 GB remaining"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_with_tolerance(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateRemainingStorage({})
    task._ground_truth_gb = 12.3
    env.interaction_cache = "Free storage: 12.5 GB"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_wrong_gb(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateRemainingStorage({})
    task._ground_truth_gb = 12.3
    env.interaction_cache = "Free storage: 20.0 GB"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4ExtraHiddenStateRecentInstalls(test_utils.AdbEvalTestBase):

  def test_is_successful_when_packages_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateRecentInstalls({})
    task._ground_truth = ["com.app.one", "com.app.two", "com.app.three"]
    env.interaction_cache = "com.app.one, com.app.two, com.app.three"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_one_missing(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateRecentInstalls({})
    task._ground_truth = ["com.app.one", "com.app.two", "com.app.three"]
    env.interaction_cache = "com.app.one, com.app.two"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4ExtraHiddenStateUptime(test_utils.AdbEvalTestBase):

  def test_is_successful_when_hours_and_minutes_match(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateUptime({})
    task._ground_truth_hours = 5
    task._ground_truth_minutes = 30
    env.interaction_cache = "Device uptime: 5 hours 30 minutes"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_wrong_hours(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateUptime({})
    task._ground_truth_hours = 5
    task._ground_truth_minutes = 30
    env.interaction_cache = "Device uptime: 3 hours 30 minutes"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4ExtraHiddenStateBatteryDrain(test_utils.AdbEvalTestBase):

  def test_is_successful_when_pkg_and_pct_match(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateBatteryDrain({})
    task._ground_truth_pkg = "com.android.chrome"
    task._ground_truth_pct = 15.2
    env.interaction_cache = "com.android.chrome used 15.2% battery"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_partial_when_pkg_only(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateBatteryDrain({})
    task._ground_truth_pkg = "com.android.chrome"
    task._ground_truth_pct = 15.2
    env.interaction_cache = "com.android.chrome is the biggest battery user"
    self.assertEqual(task.is_successful(env), 0.5)

  def test_is_successful_fails_when_wrong_pkg(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateBatteryDrain({})
    task._ground_truth_pkg = "com.android.chrome"
    task._ground_truth_pct = 15.2
    env.interaction_cache = "com.facebook.katana used 15.2% battery"
    self.assertEqual(task.is_successful(env), 0.0)


class TestTier4ExtraHiddenStateMobileDataUsage(test_utils.AdbEvalTestBase):

  def test_is_successful_when_pkg_and_mb_match(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateMobileDataUsage({})
    task._ground_truth_pkg = "com.android.chrome"
    task._ground_truth_mb = 150.0
    env.interaction_cache = "com.android.chrome used 150.0 MB of mobile data"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_partial_when_pkg_only(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateMobileDataUsage({})
    task._ground_truth_pkg = "com.android.chrome"
    task._ground_truth_mb = 150.0
    env.interaction_cache = "com.android.chrome used the most mobile data"
    self.assertEqual(task.is_successful(env), 0.5)

  def test_is_successful_fails_when_empty(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = system.Tier4ExtraHiddenStateMobileDataUsage({})
    task._ground_truth_pkg = ""
    task._ground_truth_mb = 0.0
    env.interaction_cache = "no mobile data usage found"
    self.assertEqual(task.is_successful(env), 0.0)


# ── SMS tier4_extra tests ────────────────────────────────────────────────


class TestTier4ExtraAggregationSmsAvgLength(test_utils.AdbEvalTestBase):

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()

  def test_is_successful_when_avg_matches(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4ExtraAggregationSmsAvgLength({})
    task._ground_truth = 22
    env.interaction_cache = "The average SMS length is 22 characters"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_with_tolerance(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4ExtraAggregationSmsAvgLength({})
    task._ground_truth = 22
    env.interaction_cache = "Average length: 23 chars"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraFilterSmsContainingUrl(test_utils.AdbEvalTestBase):

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()

  def test_is_successful_when_url_senders_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4ExtraFilterSmsContainingUrl({})
    task._ground_truth = ["5551234567", "5559876543"]
    env.interaction_cache = "5551234567 and 5559876543"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraTopKSmsOldestMessages(test_utils.AdbEvalTestBase):

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()

  def test_is_successful_when_oldest_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4ExtraTopKSmsOldestMessages({})
    task._ground_truth = ["5550001111", "5550002222", "5550003333"]
    env.interaction_cache = "5550001111, 5550002222, 5550003333"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraCoverageSmsAllFromKnownContacts(test_utils.AdbEvalTestBase):

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()
    mock.patch.object(adb_utils, "delete_contacts").start()

  def test_is_successful_all_known(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4ExtraCoverageSmsAllFromKnownContacts({"variant": "all_known"})
    task._unknown_count = 0
    env.interaction_cache = "all known contacts"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_has_unknown(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = sms.Tier4ExtraCoverageSmsAllFromKnownContacts({"variant": "has_unknown"})
    task._unknown_count = 2
    env.interaction_cache = "2 messages from unknown numbers"
    self.assertEqual(task.is_successful(env), 1.0)


# ── Files tier4_extra tests ──────────────────────────────────────────────


class TestTier4ExtraAggregationFileCountByExtension(test_utils.AdbEvalTestBase):

  def test_is_successful_when_counts_match(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4ExtraAggregationFileCountByExtension({})
    task._ground_truth = {".txt": 3, ".log": 2, ".bin": 4, ".dat": 1}
    env.interaction_cache = ".txt: 3, .log: 2, .bin: 4, .dat: 1"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraFilterEmptyFilesInDownloads(test_utils.AdbEvalTestBase):

  def test_is_successful_when_empty_files_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4ExtraFilterEmptyFilesInDownloads({})
    task._ground_truth = ["tier4ext_empty_1234.txt", "tier4ext_empty_5678.txt"]
    env.interaction_cache = "tier4ext_empty_1234.txt, tier4ext_empty_5678.txt"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraBulkFlattenSubdirectories(test_utils.AdbEvalTestBase):

  def test_is_successful_when_files_moved_and_dirs_removed(self):
    res_found = adb_pb2.AdbResponse()
    res_found.generic.output = b"/storage/emulated/0/Download/tier4ext_nested_0_0.txt\n"
    res_no_dir = adb_pb2.AdbResponse()
    res_no_dir.generic.output = b""

    self.mock_issue_generic_request.side_effect = [
        res_found, res_found,  # find for 2 files
        res_no_dir, res_no_dir,  # test for 2 subdirs
        res_found, res_found,  # find for remaining files
        res_no_dir, res_no_dir,  # test for remaining subdirs
    ]

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = files.Tier4ExtraBulkFlattenSubdirectories({})
    task._files = ["tier4ext_nested_0_0.txt", "tier4ext_nested_0_1.txt"]
    task._subdirs = ["tier4ext_subdir_1234", "tier4ext_subdir_5678"]
    self.assertEqual(task.is_successful(env), 1.0)


# ── Calendar tier4_extra tests ───────────────────────────────────────────


class TestTier4ExtraAggregationCalendarEventsPerDay(test_utils.AdbEvalTestBase):

  def test_is_successful_when_day_and_count_match(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_calendar.Tier4ExtraAggregationCalendarEventsPerDay({})
    task._ground_truth_count = 4
    task._ground_truth_day = "2026-04-05"
    env.interaction_cache = "April 5 has 4 events"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraFilterCalendarWeekendEvents(test_utils.AdbEvalTestBase):

  def test_is_successful_when_weekend_events_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_calendar.Tier4ExtraFilterCalendarWeekendEvents({})
    task._ground_truth = ["tier4cal_wkday_5", "tier4cal_wkday_6"]
    env.interaction_cache = "tier4cal_wkday_5, tier4cal_wkday_6"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraTopKCalendarLongestEvents(test_utils.AdbEvalTestBase):

  def test_is_successful_when_longest_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_calendar.Tier4ExtraTopKCalendarLongestEvents({})
    task._ground_truth = ["tier4cal_longev_0", "tier4cal_longev_1", "tier4cal_longev_2"]
    env.interaction_cache = "tier4cal_longev_0, tier4cal_longev_1, tier4cal_longev_2"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraBulkAddReminderToAllEvents(test_utils.AdbEvalTestBase):

  def test_is_successful_when_reminders_added(self):
    res = adb_pb2.AdbResponse()
    res.generic.output = b"Row: 0 minutes=15\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_calendar.Tier4ExtraBulkAddReminderToAllEvents({})
    task._needs_reminder_ids = ["1", "2", "3"]
    task._has_reminder_ids = ["4", "5"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_reminder_missing(self):
    res = adb_pb2.AdbResponse()
    res.generic.output = b"No result found."
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_calendar.Tier4ExtraBulkAddReminderToAllEvents({})
    task._needs_reminder_ids = ["1", "2", "3"]
    task._has_reminder_ids = ["4", "5"]
    self.assertEqual(task.is_successful(env), 0.0)


# ── Expense tier4_extra tests ────────────────────────────────────────────


class TestTier4ExtraAggregationExpenseAvgPerCategory(test_utils.AdbEvalTestBase):

  def test_is_successful_when_categories_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4ExtraAggregationExpenseAvgPerCategory({})
    task._ground_truth_highest = "Housing"
    task._ground_truth_avg = "25.00"
    env.interaction_cache = "Housing: $25.00, Food: $6.67, Entertainment: $4.00"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraFilterExpenseAboveAverage(test_utils.AdbEvalTestBase):

  def test_is_successful_when_above_avg_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4ExtraFilterExpenseAboveAverage({})
    task._ground_truth = ["aboveavg_3", "aboveavg_4"]
    env.interaction_cache = "aboveavg_3, aboveavg_4"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraTopKExpenseDaysMostSpent(test_utils.AdbEvalTestBase):

  def test_is_successful_when_top_days_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4ExtraTopKExpenseDaysMostSpent({})
    task._ground_truth_days = ["2026-04-01", "2026-04-07", "2026-04-03"]
    env.interaction_cache = "2026-04-01, 2026-04-07, 2026-04-03"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraCoverageExpenseAllCategorized(test_utils.AdbEvalTestBase):

  def test_is_successful_all_valid(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4ExtraCoverageExpenseAllCategorized(
        {"variant": "all_valid"}
    )
    task._uncategorized_names = []
    env.interaction_cache = "all categorized"
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_has_uncategorized(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_expense.Tier4ExtraCoverageExpenseAllCategorized(
        {"variant": "has_uncategorized"}
    )
    task._uncategorized_names = ["cat_missing_0", "cat_missing_1"]
    env.interaction_cache = "cat_missing_0, cat_missing_1 are uncategorized"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraBulkDeleteSmallExpenses(test_utils.AdbEvalTestBase):

  def setUp(self):
    super().setUp()
    self.mock_get_expenses = mock.patch.object(
        tier4_expense, "_get_expenses"
    ).start()

  def test_is_successful_when_small_deleted(self):
    # Simulate: only normal expenses remain
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
    task = tier4_expense.Tier4ExtraBulkDeleteSmallExpenses({})
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
    task = tier4_expense.Tier4ExtraBulkDeleteSmallExpenses({})
    task._small_names = ["tiny_0", "tiny_1", "tiny_2"]
    task._keep_names = ["normal_0", "normal_1", "normal_2"]
    self.assertEqual(task.is_successful(env), 0.0)


# ── Cross-app tier4_extra tests ──────────────────────────────────────────


class TestTier4ExtraCrossAppContactsToMarkor(test_utils.AdbEvalTestBase):

  def setUp(self):
    super().setUp()
    mock.patch.object(adb_utils, "delete_contacts").start()

  def test_is_successful_when_contacts_in_note(self):
    res = adb_pb2.AdbResponse()
    res.generic.output = b"Alice Smith: +15550001001\nBob Jones: +15550001002\nCarol Lee: +15550001003\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4ExtraCrossAppContactsToMarkor({})
    task._contacts = [
        ("Alice Smith", "+15550001001"),
        ("Bob Jones", "+15550001002"),
        ("Carol Lee", "+15550001003"),
    ]
    task._note_path = "/storage/emulated/0/Documents/Markor/contacts_export.md"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraCrossAppCalendarSmsConflicts(test_utils.AdbEvalTestBase):

  def setUp(self):
    super().setUp()
    mock.patch.object(sms_validators, "clear_sms_and_threads").start()

  def test_is_successful_when_conflicting_sms_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4ExtraCrossAppCalendarSmsConflicts({})
    task._ground_truth = ["5551112222", "5553334444"]
    env.interaction_cache = "5551112222, 5553334444"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraCrossAppExpenseVsCalendar(test_utils.AdbEvalTestBase):

  def test_is_successful_when_matching_events_listed(self):
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4ExtraCrossAppExpenseVsCalendar({})
    task._ground_truth = ["tier4xa_today_meeting", "tier4xa_yesterday_review"]
    env.interaction_cache = "tier4xa_today_meeting, tier4xa_yesterday_review"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraCrossAppSmsKeywordToTasks(test_utils.AdbEvalTestBase):

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
            deleted=0, due_date=0,
        ),
        sqlite_schema_utils.Task(
            title="urgent review needed for PR #42",
            importance=0, created=0, modified=0, completed=0,
            deleted=0, due_date=0,
        ),
    ]
    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4ExtraCrossAppSmsKeywordToTasks({})
    task._urgent_bodies = [
        "urgent: server down, check immediately",
        "urgent review needed for PR #42",
    ]
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraCrossAppOpenTracksToMarkor(test_utils.AdbEvalTestBase):

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
    task = tier4_cross_app.Tier4ExtraCrossAppOpenTracksToMarkor({})
    task._ground_truth_count = 3
    task._ground_truth_km = 20.2
    task._note_path = "/storage/emulated/0/Documents/Markor/weekly_stats.md"
    self.assertEqual(task.is_successful(env), 1.0)


class TestTier4ExtraCrossAppJoplinToCalendar(test_utils.AdbEvalTestBase):

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
    task = tier4_cross_app.Tier4ExtraCrossAppJoplinToCalendar({})
    task._todo_titles = ["tier4xa_todo_note_0", "tier4xa_todo_note_1"]
    self.assertEqual(task.is_successful(env), 1.0)

  def test_is_successful_fails_when_event_missing(self):
    res = adb_pb2.AdbResponse()
    res.generic.output = b"Row: 0 title=tier4xa_todo_note_0\n"
    self.mock_issue_generic_request.return_value = res

    env = mock.MagicMock()
    env.controller = self.mock_env.controller
    task = tier4_cross_app.Tier4ExtraCrossAppJoplinToCalendar({})
    task._todo_titles = ["tier4xa_todo_note_0", "tier4xa_todo_note_1"]
    self.assertEqual(task.is_successful(env), 0.0)


if __name__ == "__main__":
  absltest.main()
