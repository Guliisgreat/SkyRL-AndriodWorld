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

"""Tier 4: ADB-exclusive tasks (56 tasks).

These tasks are designed for CLI/ADB agents. GUI agents can complete them
only with high cost and error-prone multi-step interactions.

Categories:
  A — Compute across items  (Aggregation/TopK)  13 tasks
  B — Bulk operations        (Bulk/Dedup)        11 tasks
  C — Multi-condition filter (Filter/Coverage)   12 tasks
  D — Cross-app correlation  (CrossApp)          10 tasks
  E — Hidden device state    (HiddenState)       10 tasks
"""

from . import broccoli
from . import calendar
from . import contacts
from . import cross_app
from . import expense
from . import joplin
from . import opentracks
from . import retro_music
from . import tasks_app
from . import files
from . import markor
from . import sms
from . import system

__all__ = [
    # ── A: Compute across items (13) ────────────────────────────────────
    "Tier4AggregationLongestMarkorNote",
    "Tier4AggregationDownloadSizeTop3",
    "Tier4AggregationExpenseCategoryTop3",
    "Tier4AggregationExpenseSuspectedDuplicates",
    "Tier4AggregationExpenseAllCategorized",
    "Tier4AggregationContactsDuplicatePhones",
    "Tier4AggregationOpenTracksWeeklyStats",
    "Tier4TopKMarkorMostModifiedNotes",
    "Tier4TopKLargestDownloadFiles",
    "Tier4TopKSmsThreadsByCount",
    "Tier4TopKExpenseHighestAmount",
    "Tier4TopKOpenTracksFastestActivity",
    "Tier4TopKRetroMusicLongestSongs",
    # ── B: Bulk operations (11) ─────────────────────────────────────────
    "Tier4BulkDeleteTmpInDownloads",
    "Tier4BulkDeleteApkFiles",
    "Tier4BulkDeleteSmallExpenses",
    "Tier4BulkDeleteCalendarTestEvents",
    "Tier4BulkRenameScreenshots",
    "Tier4BulkMoveLargeFiles",
    "Tier4BulkAppendFooterToMarkdown",
    "Tier4BulkRecategorizeExpense",
    "Tier4BulkChangePriorityTasks",
    "Tier4DedupMergeContactsSamePhone",
    "Tier4DedupCalendarDeleteDuplicateEvents",
    # ── C: Multi-condition filter (12) ──────────────────────────────────
    "Tier4FilterContactsBirthdayNoPhone",
    "Tier4FilterContactsNoFamilyName",
    "Tier4FilterExpenseHighTravelLastMonth",
    "Tier4FilterExpenseAboveAverage",
    "Tier4FilterJoplinContainsNotContains",
    "Tier4FilterRetroMusicMultiCondition",
    "Tier4FilterSmsContainingUrl",
    "Tier4FilterLargeOldFiles",
    "Tier4FilterEmptyFilesInDownloads",
    "Tier4FilterCalendarWeekendEvents",
    "Tier4CoverageSmsAllFromKnownContacts",
    "Tier4CoverageCalendarEventsHaveReminders",
    # ── D: Cross-app correlation (10) ───────────────────────────────────
    "Tier4CrossAppSmsNumbersNotInContacts",
    "Tier4CrossAppExpenseToMarkorCalendar",
    "Tier4CrossAppBroccoliToMarkorIndex",
    "Tier4CrossAppMarkorPhonesVsContacts",
    "Tier4CrossAppCalendarToMarkor",
    "Tier4CrossAppContactsToMarkor",
    "Tier4CrossAppCalendarSmsConflicts",
    "Tier4CrossAppSmsKeywordToTasks",
    "Tier4CrossAppOpenTracksToMarkor",
    "Tier4CrossAppJoplinToCalendar",
    # ── E: Hidden device state (10) ─────────────────────────────────────
    "Tier4HiddenStateListAppVersions",
    "Tier4HiddenStateLocationPermissions",
    "Tier4HiddenStateAudioRouting",
    "Tier4HiddenStateAppsCameraPermission",
    "Tier4HiddenStatePhoneTemperature",
    "Tier4HiddenStateRecentInstalls",
    "Tier4HiddenStateUptime",
    "Tier4HiddenStateBackgroundLocationApps",
    "Tier4HiddenStateSignalStrength",
    "Tier4HiddenStateSmsDbSize",
]

# ── A: Compute across items ─────────────────────────────────────────────
Tier4AggregationLongestMarkorNote = markor.Tier4AggregationLongestMarkorNote
Tier4AggregationDownloadSizeTop3 = files.Tier4AggregationDownloadSizeTop3
Tier4AggregationExpenseCategoryTop3 = expense.Tier4AggregationExpenseCategoryTop3
Tier4AggregationExpenseSuspectedDuplicates = expense.Tier4AggregationExpenseSuspectedDuplicates
Tier4AggregationExpenseAllCategorized = expense.Tier4AggregationExpenseAllCategorized
Tier4AggregationContactsDuplicatePhones = contacts.Tier4AggregationContactsDuplicatePhones
Tier4AggregationOpenTracksWeeklyStats = opentracks.Tier4AggregationOpenTracksWeeklyStats
Tier4TopKMarkorMostModifiedNotes = markor.Tier4TopKMarkorMostModifiedNotes
Tier4TopKLargestDownloadFiles = files.Tier4TopKLargestDownloadFiles
Tier4TopKSmsThreadsByCount = sms.Tier4TopKSmsThreadsByCount
Tier4TopKExpenseHighestAmount = expense.Tier4TopKExpenseHighestAmount
Tier4TopKOpenTracksFastestActivity = opentracks.Tier4TopKOpenTracksFastestActivity
Tier4TopKRetroMusicLongestSongs = retro_music.Tier4TopKRetroMusicLongestSongs

# ── B: Bulk operations ──────────────────────────────────────────────────
Tier4BulkDeleteTmpInDownloads = files.Tier4BulkDeleteTmpInDownloads
Tier4BulkDeleteApkFiles = files.Tier4BulkDeleteApkFiles
Tier4BulkDeleteSmallExpenses = expense.Tier4BulkDeleteSmallExpenses
Tier4BulkDeleteCalendarTestEvents = calendar.Tier4BulkDeleteCalendarTestEvents
Tier4BulkRenameScreenshots = files.Tier4BulkRenameScreenshots
Tier4BulkMoveLargeFiles = files.Tier4BulkMoveLargeFiles
Tier4BulkAppendFooterToMarkdown = markor.Tier4BulkAppendFooterToMarkdown
Tier4BulkRecategorizeExpense = expense.Tier4BulkRecategorizeExpense
Tier4BulkChangePriorityTasks = tasks_app.Tier4BulkChangePriorityTasks
Tier4DedupMergeContactsSamePhone = contacts.Tier4DedupMergeContactsSamePhone
Tier4DedupCalendarDeleteDuplicateEvents = calendar.Tier4DedupCalendarDeleteDuplicateEvents

# ── C: Multi-condition filter ───────────────────────────────────────────
Tier4FilterContactsBirthdayNoPhone = contacts.Tier4FilterContactsBirthdayNoPhone
Tier4FilterContactsNoFamilyName = contacts.Tier4FilterContactsNoFamilyName
Tier4FilterExpenseHighTravelLastMonth = expense.Tier4FilterExpenseHighTravelLastMonth
Tier4FilterExpenseAboveAverage = expense.Tier4FilterExpenseAboveAverage
Tier4FilterJoplinContainsNotContains = joplin.Tier4FilterJoplinContainsNotContains
Tier4FilterRetroMusicMultiCondition = retro_music.Tier4FilterRetroMusicMultiCondition
Tier4FilterSmsContainingUrl = sms.Tier4FilterSmsContainingUrl
Tier4FilterLargeOldFiles = files.Tier4FilterLargeOldFiles
Tier4FilterEmptyFilesInDownloads = files.Tier4FilterEmptyFilesInDownloads
Tier4FilterCalendarWeekendEvents = calendar.Tier4FilterCalendarWeekendEvents
Tier4CoverageSmsAllFromKnownContacts = sms.Tier4CoverageSmsAllFromKnownContacts
Tier4CoverageCalendarEventsHaveReminders = calendar.Tier4CoverageCalendarEventsHaveReminders

# ── D: Cross-app correlation ────────────────────────────────────────────
Tier4CrossAppSmsNumbersNotInContacts = sms.Tier4CrossAppSmsNumbersNotInContacts
Tier4CrossAppExpenseToMarkorCalendar = expense.Tier4CrossAppExpenseToMarkorCalendar
Tier4CrossAppBroccoliToMarkorIndex = broccoli.Tier4CrossAppBroccoliToMarkorIndex
Tier4CrossAppMarkorPhonesVsContacts = cross_app.Tier4CrossAppMarkorPhonesVsContacts
Tier4CrossAppCalendarToMarkor = calendar.Tier4CrossAppCalendarToMarkor
Tier4CrossAppContactsToMarkor = cross_app.Tier4CrossAppContactsToMarkor
Tier4CrossAppCalendarSmsConflicts = cross_app.Tier4CrossAppCalendarSmsConflicts
Tier4CrossAppSmsKeywordToTasks = cross_app.Tier4CrossAppSmsKeywordToTasks
Tier4CrossAppOpenTracksToMarkor = cross_app.Tier4CrossAppOpenTracksToMarkor
Tier4CrossAppJoplinToCalendar = cross_app.Tier4CrossAppJoplinToCalendar

# ── E: Hidden device state ──────────────────────────────────────────────
Tier4HiddenStateListAppVersions = system.Tier4HiddenStateListAppVersions
Tier4HiddenStateLocationPermissions = system.Tier4HiddenStateLocationPermissions
Tier4HiddenStateAudioRouting = system.Tier4HiddenStateAudioRouting
Tier4HiddenStateAppsCameraPermission = system.Tier4HiddenStateAppsCameraPermission
Tier4HiddenStatePhoneTemperature = system.Tier4HiddenStatePhoneTemperature
Tier4HiddenStateRecentInstalls = system.Tier4HiddenStateRecentInstalls
Tier4HiddenStateUptime = system.Tier4HiddenStateUptime
Tier4HiddenStateBackgroundLocationApps = system.Tier4HiddenStateBackgroundLocationApps
Tier4HiddenStateSignalStrength = system.Tier4HiddenStateSignalStrength
Tier4HiddenStateSmsDbSize = sms.Tier4HiddenStateSmsDbSize
