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

"""Tier 4: ADB-exclusive tasks.

These tasks are designed for CLI/ADB agents. GUI agents can complete them
only with high cost and error-prone multi-step interactions.
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
    "Tier4BulkDeleteTmpInDownloads",
    "Tier4CoverageNoTmpInDownloads",
    "Tier4HiddenStateListAppVersions",
    "Tier4AggregationCountUnreadSMS",
    "Tier4CrossAppSmsNumbersNotInContacts",
    # Phase 1: Files/Markor
    "Tier4BulkRenameScreenshots",
    "Tier4BulkMoveLargeFiles",
    "Tier4FilterRecentLogFiles",
    "Tier4BulkAppendFooterToMarkdown",
    "Tier4AggregationLongestMarkorNote",
    "Tier4TopKMarkorMostModifiedNotes",
    # Phase 2: SMS/Contacts
    "Tier4FilterDeleteOldNonContactKeywordSms",
    "Tier4TopKSmsThreadsByCount",
    "Tier4CrossAppContactsNoRecentSms",
    "Tier4FilterContactsBirthdayNoPhone",
    "Tier4AggregationLongestContactName",
    "Tier4DedupContactsDuplicatePhones",
    "Tier4DedupMergeContactsSamePhone",
    # Phase 8: DB-based — Pro Expense
    "Tier4BulkRecategorizeExpense",
    "Tier4FilterExpenseHighTravelLastMonth",
    "Tier4AggregationExpenseCategoryTop3",
    "Tier4DedupExpenseSuspectedDuplicates",
    "Tier4TopKExpenseHighestAmount",
    "Tier4CrossAppExpenseToMarkorCalendar",
    # Phase 8: DB-based — Tasks.org
    "Tier4BulkChangePriorityTasks",
    "Tier4CoverageOverdueTasksCompleted",
    # Phase 8: DB-based — Joplin
    "Tier4FilterJoplinContainsNotContains",
    "Tier4DedupJoplinSameTitleNotes",
    # Phase 8: DB-based — OpenTracks
    "Tier4AggregationOpenTracksWeeklyStats",
    "Tier4TopKOpenTracksFastestActivity",
    "Tier4CrossAppOpenTracksToTasks",
    # Phase 8: DB-based — Retro Music
    "Tier4FilterRetroMusicMultiCondition",
    "Tier4TopKRetroMusicLongestSongs",
    # Phase 8: DB-based — Broccoli
    "Tier4CrossAppBroccoliToMarkorIndex",
    # Phase 6: Cross-app non-DB
    "Tier4CrossAppFilesCreatedDuringEvents",
    "Tier4CrossAppMarkorPhonesVsContacts",
    # Phase 5: Files + SMS Coverage
    "Tier4AggregationDownloadSizeTop3",
    "Tier4TopKLargestDownloadFiles",
    "Tier4CoverageAllSmsRead",
    # Phase 4: System/Settings
    "Tier4HiddenStateLocationPermissions",
    "Tier4HiddenStateAudioRouting",
    "Tier4CoverageAppsCameraPermission",
    "Tier4CoverageWifiConnected",
    # Phase 3: Calendar
    "Tier4BulkDeleteCalendarTestEvents",
    "Tier4CrossAppCalendarToMarkor",
    "Tier4FilterCalendarLongNoReminder",
    "Tier4AggregationCalendarTotalDuration",
    "Tier4DedupCalendarDeleteDuplicateEvents",
    "Tier4TopKCalendarEarliestEvent",
    "Tier4CoverageCalendarEventsHaveReminders",
    # ── tier4_extra ──────────────────────────────────────────────────────
    # System (5)
    "Tier4ExtraHiddenStateRemainingStorage",
    "Tier4ExtraHiddenStateRecentInstalls",
    "Tier4ExtraHiddenStateUptime",
    "Tier4ExtraHiddenStateBatteryDrain",
    "Tier4ExtraHiddenStateMobileDataUsage",
    # SMS (4)
    "Tier4ExtraAggregationSmsAvgLength",
    "Tier4ExtraFilterSmsContainingUrl",
    "Tier4ExtraTopKSmsOldestMessages",
    "Tier4ExtraCoverageSmsAllFromKnownContacts",
    # Files (3)
    "Tier4ExtraAggregationFileCountByExtension",
    "Tier4ExtraFilterEmptyFilesInDownloads",
    "Tier4ExtraBulkFlattenSubdirectories",
    # Calendar (4)
    "Tier4ExtraAggregationCalendarEventsPerDay",
    "Tier4ExtraFilterCalendarWeekendEvents",
    "Tier4ExtraTopKCalendarLongestEvents",
    "Tier4ExtraBulkAddReminderToAllEvents",
    # Expense (5)
    "Tier4ExtraAggregationExpenseAvgPerCategory",
    "Tier4ExtraFilterExpenseAboveAverage",
    "Tier4ExtraTopKExpenseDaysMostSpent",
    "Tier4ExtraCoverageExpenseAllCategorized",
    "Tier4ExtraBulkDeleteSmallExpenses",
    # Cross-app (6)
    "Tier4ExtraCrossAppContactsToMarkor",
    "Tier4ExtraCrossAppCalendarSmsConflicts",
    "Tier4ExtraCrossAppExpenseVsCalendar",
    "Tier4ExtraCrossAppSmsKeywordToTasks",
    "Tier4ExtraCrossAppOpenTracksToMarkor",
    "Tier4ExtraCrossAppJoplinToCalendar",
]

Tier4BulkDeleteTmpInDownloads = files.Tier4BulkDeleteTmpInDownloads
Tier4CoverageNoTmpInDownloads = files.Tier4CoverageNoTmpInDownloads
Tier4HiddenStateListAppVersions = system.Tier4HiddenStateListAppVersions
Tier4AggregationCountUnreadSMS = sms.Tier4AggregationCountUnreadSMS
Tier4CrossAppSmsNumbersNotInContacts = sms.Tier4CrossAppSmsNumbersNotInContacts
Tier4BulkRenameScreenshots = files.Tier4BulkRenameScreenshots
Tier4BulkMoveLargeFiles = files.Tier4BulkMoveLargeFiles
Tier4FilterRecentLogFiles = files.Tier4FilterRecentLogFiles
Tier4BulkAppendFooterToMarkdown = markor.Tier4BulkAppendFooterToMarkdown
Tier4AggregationLongestMarkorNote = markor.Tier4AggregationLongestMarkorNote
Tier4TopKMarkorMostModifiedNotes = markor.Tier4TopKMarkorMostModifiedNotes
Tier4FilterDeleteOldNonContactKeywordSms = sms.Tier4FilterDeleteOldNonContactKeywordSms
Tier4TopKSmsThreadsByCount = sms.Tier4TopKSmsThreadsByCount
Tier4CrossAppContactsNoRecentSms = contacts.Tier4CrossAppContactsNoRecentSms
Tier4FilterContactsBirthdayNoPhone = contacts.Tier4FilterContactsBirthdayNoPhone
Tier4AggregationLongestContactName = contacts.Tier4AggregationLongestContactName
Tier4DedupContactsDuplicatePhones = contacts.Tier4DedupContactsDuplicatePhones
Tier4DedupMergeContactsSamePhone = contacts.Tier4DedupMergeContactsSamePhone
Tier4BulkRecategorizeExpense = expense.Tier4BulkRecategorizeExpense
Tier4FilterExpenseHighTravelLastMonth = expense.Tier4FilterExpenseHighTravelLastMonth
Tier4AggregationExpenseCategoryTop3 = expense.Tier4AggregationExpenseCategoryTop3
Tier4DedupExpenseSuspectedDuplicates = expense.Tier4DedupExpenseSuspectedDuplicates
Tier4TopKExpenseHighestAmount = expense.Tier4TopKExpenseHighestAmount
Tier4CrossAppExpenseToMarkorCalendar = expense.Tier4CrossAppExpenseToMarkorCalendar
Tier4BulkChangePriorityTasks = tasks_app.Tier4BulkChangePriorityTasks
Tier4CoverageOverdueTasksCompleted = tasks_app.Tier4CoverageOverdueTasksCompleted
Tier4FilterJoplinContainsNotContains = joplin.Tier4FilterJoplinContainsNotContains
Tier4DedupJoplinSameTitleNotes = joplin.Tier4DedupJoplinSameTitleNotes
Tier4AggregationOpenTracksWeeklyStats = opentracks.Tier4AggregationOpenTracksWeeklyStats
Tier4TopKOpenTracksFastestActivity = opentracks.Tier4TopKOpenTracksFastestActivity
Tier4CrossAppOpenTracksToTasks = opentracks.Tier4CrossAppOpenTracksToTasks
Tier4FilterRetroMusicMultiCondition = retro_music.Tier4FilterRetroMusicMultiCondition
Tier4TopKRetroMusicLongestSongs = retro_music.Tier4TopKRetroMusicLongestSongs
Tier4CrossAppBroccoliToMarkorIndex = broccoli.Tier4CrossAppBroccoliToMarkorIndex
Tier4CrossAppFilesCreatedDuringEvents = cross_app.Tier4CrossAppFilesCreatedDuringEvents
Tier4CrossAppMarkorPhonesVsContacts = cross_app.Tier4CrossAppMarkorPhonesVsContacts
Tier4AggregationDownloadSizeTop3 = files.Tier4AggregationDownloadSizeTop3
Tier4TopKLargestDownloadFiles = files.Tier4TopKLargestDownloadFiles
Tier4CoverageAllSmsRead = sms.Tier4CoverageAllSmsRead
Tier4HiddenStateLocationPermissions = system.Tier4HiddenStateLocationPermissions
Tier4HiddenStateAudioRouting = system.Tier4HiddenStateAudioRouting
Tier4CoverageAppsCameraPermission = system.Tier4CoverageAppsCameraPermission
Tier4CoverageWifiConnected = system.Tier4CoverageWifiConnected
Tier4BulkDeleteCalendarTestEvents = calendar.Tier4BulkDeleteCalendarTestEvents
Tier4CrossAppCalendarToMarkor = calendar.Tier4CrossAppCalendarToMarkor
Tier4FilterCalendarLongNoReminder = calendar.Tier4FilterCalendarLongNoReminder
Tier4AggregationCalendarTotalDuration = calendar.Tier4AggregationCalendarTotalDuration
Tier4DedupCalendarDeleteDuplicateEvents = calendar.Tier4DedupCalendarDeleteDuplicateEvents
Tier4TopKCalendarEarliestEvent = calendar.Tier4TopKCalendarEarliestEvent
Tier4CoverageCalendarEventsHaveReminders = calendar.Tier4CoverageCalendarEventsHaveReminders

# ── tier4_extra re-exports ───────────────────────────────────────────────
# System
Tier4ExtraHiddenStateRemainingStorage = system.Tier4ExtraHiddenStateRemainingStorage
Tier4ExtraHiddenStateRecentInstalls = system.Tier4ExtraHiddenStateRecentInstalls
Tier4ExtraHiddenStateUptime = system.Tier4ExtraHiddenStateUptime
Tier4ExtraHiddenStateBatteryDrain = system.Tier4ExtraHiddenStateBatteryDrain
Tier4ExtraHiddenStateMobileDataUsage = system.Tier4ExtraHiddenStateMobileDataUsage
# Backward-compatible aliases (old names → new classes)
Tier4ExtraHiddenStateBatteryHealth = system.Tier4ExtraHiddenStateBatteryHealth
Tier4ExtraHiddenStateDisabledApps = system.Tier4ExtraHiddenStateDisabledApps
Tier4ExtraHiddenStateAppStorageUsage = system.Tier4ExtraHiddenStateAppStorageUsage
# SMS
Tier4ExtraAggregationSmsAvgLength = sms.Tier4ExtraAggregationSmsAvgLength
Tier4ExtraFilterSmsContainingUrl = sms.Tier4ExtraFilterSmsContainingUrl
Tier4ExtraTopKSmsOldestMessages = sms.Tier4ExtraTopKSmsOldestMessages
Tier4ExtraCoverageSmsAllFromKnownContacts = sms.Tier4ExtraCoverageSmsAllFromKnownContacts
# Files
Tier4ExtraAggregationFileCountByExtension = files.Tier4ExtraAggregationFileCountByExtension
Tier4ExtraFilterEmptyFilesInDownloads = files.Tier4ExtraFilterEmptyFilesInDownloads
Tier4ExtraBulkFlattenSubdirectories = files.Tier4ExtraBulkFlattenSubdirectories
# Calendar
Tier4ExtraAggregationCalendarEventsPerDay = calendar.Tier4ExtraAggregationCalendarEventsPerDay
Tier4ExtraFilterCalendarWeekendEvents = calendar.Tier4ExtraFilterCalendarWeekendEvents
Tier4ExtraTopKCalendarLongestEvents = calendar.Tier4ExtraTopKCalendarLongestEvents
Tier4ExtraBulkAddReminderToAllEvents = calendar.Tier4ExtraBulkAddReminderToAllEvents
# Expense
Tier4ExtraAggregationExpenseAvgPerCategory = expense.Tier4ExtraAggregationExpenseAvgPerCategory
Tier4ExtraFilterExpenseAboveAverage = expense.Tier4ExtraFilterExpenseAboveAverage
Tier4ExtraTopKExpenseDaysMostSpent = expense.Tier4ExtraTopKExpenseDaysMostSpent
Tier4ExtraCoverageExpenseAllCategorized = expense.Tier4ExtraCoverageExpenseAllCategorized
Tier4ExtraBulkDeleteSmallExpenses = expense.Tier4ExtraBulkDeleteSmallExpenses
# Cross-app
Tier4ExtraCrossAppContactsToMarkor = cross_app.Tier4ExtraCrossAppContactsToMarkor
Tier4ExtraCrossAppCalendarSmsConflicts = cross_app.Tier4ExtraCrossAppCalendarSmsConflicts
Tier4ExtraCrossAppExpenseVsCalendar = cross_app.Tier4ExtraCrossAppExpenseVsCalendar
Tier4ExtraCrossAppSmsKeywordToTasks = cross_app.Tier4ExtraCrossAppSmsKeywordToTasks
Tier4ExtraCrossAppOpenTracksToMarkor = cross_app.Tier4ExtraCrossAppOpenTracksToMarkor
Tier4ExtraCrossAppJoplinToCalendar = cross_app.Tier4ExtraCrossAppJoplinToCalendar
