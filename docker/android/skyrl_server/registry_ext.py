"""
Extended task registry with custom difficulty tiers.

Wraps the upstream android_world TaskRegistry without modifying it.
Our env.py calls ``get_registry(family)`` — this module intercepts
custom family names (easy, medium, hard, …) and delegates everything
else to upstream.
"""

from android_world import registry as _upstream_registry
from android_world.task_evals.composite import markor_sms
from android_world.task_evals.composite import system as system_composite
from android_world.task_evals.single import audio_recorder
from android_world.task_evals.single import browser
from android_world.task_evals.single import camera
from android_world.task_evals.single import clock
from android_world.task_evals.single import contacts
from android_world.task_evals.single import expense
from android_world.task_evals.single import files
from android_world.task_evals.single import markor
from android_world.task_evals.single import osmand
from android_world.task_evals.single import recipe
from android_world.task_evals.single import retro_music
from android_world.task_evals.single import simple_draw_pro
from android_world.task_evals.single import simple_gallery_pro
from android_world.task_evals.single import sms
from android_world.task_evals.single import system
from android_world.task_evals.single import vlc
from android_world.task_evals.single.calendar import calendar
from .tier4 import broccoli as tier4_broccoli
from .tier4 import calendar as tier4_calendar
from .tier4 import contacts as tier4_contacts
from .tier4 import cross_app as tier4_cross_app
from .tier4 import expense as tier4_expense
from .tier4 import joplin as tier4_joplin
from .tier4 import opentracks as tier4_opentracks
from .tier4 import retro_music as tier4_retro_music
from .tier4 import tasks_app as tier4_tasks_app
from .tier4 import files as tier4_files
from .tier4 import markor as tier4_markor
from .tier4 import sms as tier4_sms
from .tier4 import system as tier4_system

# ── Custom difficulty tiers ──────────────────────────────────────────

_EASY_TASKS = (
    audio_recorder.AudioRecorderRecordAudio,
    clock.ClockStopWatchRunning,
    system.OpenAppTaskEval,
    recipe.RecipeDeleteMultipleRecipes,
    recipe.RecipeDeleteSingleRecipe,
    calendar.SimpleCalendarDeleteEvents,
    calendar.SimpleCalendarDeleteOneEvent,
    system.SystemBluetoothTurnOn,
    camera.CameraTakePhoto,
    contacts.ContactsAddContact,
    contacts.ContactsNewContactDraft,
    expense.ExpenseDeleteSingle,
    markor.MarkorDeleteAllNotes,
    markor.MarkorDeleteNote,
    recipe.RecipeDeleteDuplicateRecipes,
    expense.ExpenseDeleteMultiple,
    system_composite.TurnOnWifiAndOpenApp,
    system.SystemBluetoothTurnOff,
    system.SystemWifiTurnOff,
    system.SystemWifiTurnOn,
    clock.ClockTimerEntry,
    expense.ExpenseAddSingle,
    markor.MarkorCreateFolder,
    markor.MarkorDeleteNewestNote,
    markor.MarkorEditNote,
    system.SystemBrightnessMax,
    system.SystemBrightnessMin,
    system.SystemCopyToClipboard,
    audio_recorder.AudioRecorderRecordAudioWithFileName,
    browser.BrowserDraw,
    browser.BrowserMaze,
    recipe.RecipeAddSingleRecipe,
    recipe.RecipeDeleteSingleWithRecipeWithNoise,
    retro_music.RetroPlayingQueue,
    calendar.SimpleCalendarAddOneEventRelativeDay,
    calendar.SimpleCalendarAddOneEventTomorrow,
    calendar.SimpleCalendarAddRepeatingEvent,
    simple_draw_pro.SimpleDrawProCreateDrawing,
    sms.SimpleSmsReply,
    sms.SimpleSmsSendClipboardContent,
    clock.ClockStopWatchPausedVerify,
    system.SystemBluetoothTurnOffVerify,
    system.SystemBluetoothTurnOnVerify,
    system.SystemBrightnessMaxVerify,
    system.SystemBrightnessMinVerify,
    system.SystemWifiTurnOffVerify,
    system.SystemWifiTurnOnVerify,
)

_MEDIUM_TASKS = (
    camera.CameraTakeVideo,
    expense.ExpenseAddMultiple,
    expense.ExpenseDeleteDuplicates,
    expense.ExpenseDeleteDuplicates2,
    markor.MarkorChangeNoteContent,
    markor.MarkorCreateNote,
    markor.MarkorCreateNoteFromClipboard,
    markor.MarkorMoveNote,
    markor.MarkorTranscribeReceipt,
    recipe.RecipeAddMultipleRecipes,
    recipe.RecipeDeleteMultipleRecipesWithNoise,
    retro_music.RetroCreatePlaylist,
    retro_music.RetroPlaylistDuration,
    calendar.SimpleCalendarAddOneEventInTwoWeeks,
    calendar.SimpleCalendarDeleteEventsOnRelativeDay,
    files.FilesDeleteFile,
    files.FilesMoveFile,
    system_composite.TurnOffWifiAndTurnOnBluetooth,
    sms.SimpleSmsReplyMostRecent,
    sms.SimpleSmsResend,
    sms.SimpleSmsSend,
    sms.SimpleSmsSendReceivedAddress,
    markor.MarkorAddNoteHeader,
    recipe.RecipeDeleteDuplicateRecipes2,
    recipe.RecipeDeleteDuplicateRecipes3,
    vlc.VlcCreatePlaylist,
    vlc.VlcCreateTwoPlaylists,
    osmand.OsmAndFavorite,
)

_HARD_TASKS = (
    browser.BrowserMultiply,
    expense.ExpenseAddMultipleFromGallery,
    expense.ExpenseDeleteMultiple2,
    markor.MarkorTranscribeVideo,
    markor_sms.MarkorCreateNoteAndSms,
    recipe.RecipeAddMultipleRecipesFromImage,
    recipe.RecipeAddMultipleRecipesFromMarkor,
    recipe.RecipeAddMultipleRecipesFromMarkor2,
    retro_music.RetroSavePlaylist,
    simple_gallery_pro.SaveCopyOfReceiptTaskEval,
    calendar.SimpleCalendarAddOneEvent,
    expense.ExpenseAddMultipleFromMarkor,
    markor.MarkorMergeNotes,
    osmand.OsmAndMarker,
    osmand.OsmAndTrack,
    recipe.RecipeDeleteMultipleRecipesWithConstraint,
)

# Information-retrieval tier splits
_IR_EASY = {
    'SimpleCalendarNextEvent',
    'SimpleCalendarAnyEventsOnDate',
    'SimpleCalendarLocationOfEvent',
    'SimpleCalendarEventsInNextWeek',
    'SimpleCalendarFirstEventAfterStartTime',
    'SimpleCalendarEventsInTimeRange',
    'TasksDueOnDate',
    'TasksIncompleteTasksOnDate',
    'SportsTrackerActivitiesCountForWeek',
    'SportsTrackerActivityDuration',
    'SportsTrackerLongestDistanceActivity',
    'NotesRecipeIngredientCount',
    'NotesMeetingAttendeeCount',
    'NotesIsTodo',
}

_IR_MEDIUM = {
    'SimpleCalendarEventsOnDate',
    'SimpleCalendarEventOnDateAtTime',
    'SimpleCalendarNextMeetingWithPerson',
    'TasksHighPriorityTasks',
    'TasksHighPriorityTasksDueOnDate',
    'TasksDueNextWeek',
    'TasksCompletedTasksForDate',
    'NotesTodoItemCount',
}

_IR_HARD = {
    'SportsTrackerActivitiesOnDate',
    'SportsTrackerTotalDurationForCategoryThisWeek',
    'SportsTrackerTotalDistanceForCategoryOverInterval',
}


_TIER4_TASKS = (
    tier4_files.Tier4BulkDeleteTmpInDownloads,
    tier4_files.Tier4CoverageNoTmpInDownloads,
    tier4_system.Tier4HiddenStateListAppVersions,
    tier4_sms.Tier4AggregationCountUnreadSMS,
    tier4_sms.Tier4CrossAppSmsNumbersNotInContacts,
    # Phase 1: Files/Markor
    tier4_files.Tier4BulkRenameScreenshots,
    tier4_files.Tier4BulkMoveLargeFiles,
    tier4_files.Tier4FilterRecentLogFiles,
    tier4_markor.Tier4BulkAppendFooterToMarkdown,
    tier4_markor.Tier4AggregationLongestMarkorNote,
    tier4_markor.Tier4TopKMarkorMostModifiedNotes,
    # Phase 2: SMS/Contacts
    tier4_sms.Tier4FilterDeleteOldNonContactKeywordSms,
    tier4_sms.Tier4TopKSmsThreadsByCount,
    tier4_contacts.Tier4CrossAppContactsNoRecentSms,
    tier4_contacts.Tier4FilterContactsBirthdayNoPhone,
    tier4_contacts.Tier4AggregationLongestContactName,
    tier4_contacts.Tier4DedupContactsDuplicatePhones,
    tier4_contacts.Tier4DedupMergeContactsSamePhone,
    # Phase 8: DB-based — Pro Expense
    tier4_expense.Tier4BulkRecategorizeExpense,
    tier4_expense.Tier4FilterExpenseHighTravelLastMonth,
    tier4_expense.Tier4AggregationExpenseCategoryTop3,
    tier4_expense.Tier4DedupExpenseSuspectedDuplicates,
    tier4_expense.Tier4TopKExpenseHighestAmount,
    tier4_expense.Tier4CrossAppExpenseToMarkorCalendar,
    # Phase 8: DB-based — Tasks.org
    tier4_tasks_app.Tier4BulkChangePriorityTasks,
    tier4_tasks_app.Tier4CoverageOverdueTasksCompleted,
    # Phase 8: DB-based — Joplin
    tier4_joplin.Tier4FilterJoplinContainsNotContains,
    tier4_joplin.Tier4DedupJoplinSameTitleNotes,
    # Phase 8: DB-based — OpenTracks
    tier4_opentracks.Tier4AggregationOpenTracksWeeklyStats,
    tier4_opentracks.Tier4TopKOpenTracksFastestActivity,
    tier4_opentracks.Tier4CrossAppOpenTracksToTasks,
    # Phase 8: DB-based — Retro Music
    tier4_retro_music.Tier4FilterRetroMusicMultiCondition,
    tier4_retro_music.Tier4TopKRetroMusicLongestSongs,
    # Phase 8: DB-based — Broccoli
    tier4_broccoli.Tier4CrossAppBroccoliToMarkorIndex,
    # Phase 6: Cross-app non-DB
    tier4_cross_app.Tier4CrossAppFilesCreatedDuringEvents,
    tier4_cross_app.Tier4CrossAppMarkorPhonesVsContacts,
    # Phase 5: Files + SMS Coverage
    tier4_files.Tier4AggregationDownloadSizeTop3,
    tier4_files.Tier4TopKLargestDownloadFiles,
    tier4_sms.Tier4CoverageAllSmsRead,
    # Phase 4: System/Settings
    tier4_system.Tier4HiddenStateLocationPermissions,
    tier4_system.Tier4HiddenStateAudioRouting,
    tier4_system.Tier4CoverageAppsCameraPermission,
    tier4_system.Tier4CoverageWifiConnected,
    # Phase 3: Calendar
    tier4_calendar.Tier4BulkDeleteCalendarTestEvents,
    tier4_calendar.Tier4CrossAppCalendarToMarkor,
    tier4_calendar.Tier4FilterCalendarLongNoReminder,
    tier4_calendar.Tier4AggregationCalendarTotalDuration,
    tier4_calendar.Tier4DedupCalendarDeleteDuplicateEvents,
    tier4_calendar.Tier4TopKCalendarEarliestEvent,
    tier4_calendar.Tier4CoverageCalendarEventsHaveReminders,
    # ── Tier4 extras (IDs 50–76) ──────────────────────────────────────
    # System
    tier4_system.Tier4ExtraHiddenStateRemainingStorage,
    tier4_system.Tier4ExtraHiddenStateRecentInstalls,
    tier4_system.Tier4ExtraHiddenStateUptime,
    tier4_system.Tier4ExtraHiddenStateBatteryDrain,
    tier4_system.Tier4ExtraHiddenStateMobileDataUsage,
    # SMS
    tier4_sms.Tier4ExtraAggregationSmsAvgLength,
    tier4_sms.Tier4ExtraFilterSmsContainingUrl,
    tier4_sms.Tier4ExtraTopKSmsOldestMessages,
    tier4_sms.Tier4ExtraCoverageSmsAllFromKnownContacts,
    # Files
    tier4_files.Tier4ExtraAggregationFileCountByExtension,
    tier4_files.Tier4ExtraFilterEmptyFilesInDownloads,
    tier4_files.Tier4ExtraBulkFlattenSubdirectories,
    # Expense
    tier4_expense.Tier4ExtraAggregationExpenseAvgPerCategory,
    tier4_expense.Tier4ExtraFilterExpenseAboveAverage,
    tier4_expense.Tier4ExtraTopKExpenseDaysMostSpent,
    tier4_expense.Tier4ExtraCoverageExpenseAllCategorized,
    tier4_expense.Tier4ExtraBulkDeleteSmallExpenses,
    # Calendar
    tier4_calendar.Tier4ExtraAggregationCalendarEventsPerDay,
    tier4_calendar.Tier4ExtraFilterCalendarWeekendEvents,
    tier4_calendar.Tier4ExtraTopKCalendarLongestEvents,
    tier4_calendar.Tier4ExtraBulkAddReminderToAllEvents,
    # Cross-app
    tier4_cross_app.Tier4ExtraCrossAppContactsToMarkor,
    tier4_cross_app.Tier4ExtraCrossAppCalendarSmsConflicts,
    tier4_cross_app.Tier4ExtraCrossAppExpenseVsCalendar,
    tier4_cross_app.Tier4ExtraCrossAppSmsKeywordToTasks,
    tier4_cross_app.Tier4ExtraCrossAppOpenTracksToMarkor,
    tier4_cross_app.Tier4ExtraCrossAppJoplinToCalendar,
)


def _build_registry(task_classes):
    return {cls.__name__: cls for cls in task_classes}


def _filter_ir(ir_registry, allowed_names):
    return {k: v for k, v in ir_registry.items() if k in allowed_names}


# ── v8-compatible task ordering ──────────────────────────────────────
# The old forked registry (androidworld:v8) returned tasks in this
# specific order for the ``android_world`` family.  JSONL data files
# use positional ``task_id`` indices that depend on this ordering.
# We replicate it here so existing data files work unchanged.

_V8_ANDROID_WORLD_ORDER = (
    audio_recorder.AudioRecorderRecordAudio,          # 0
    clock.ClockStopWatchRunning,                       # 1
    system.OpenAppTaskEval,                            # 2
    recipe.RecipeDeleteMultipleRecipes,                # 3
    recipe.RecipeDeleteSingleRecipe,                   # 4
    calendar.SimpleCalendarDeleteEvents,               # 5
    calendar.SimpleCalendarDeleteOneEvent,             # 6
    system.SystemBluetoothTurnOn,                      # 7
    camera.CameraTakePhoto,                            # 8
    contacts.ContactsAddContact,                       # 9
    contacts.ContactsNewContactDraft,                  # 10
    expense.ExpenseDeleteSingle,                       # 11
    markor.MarkorDeleteAllNotes,                       # 12
    markor.MarkorDeleteNote,                           # 13
    recipe.RecipeDeleteDuplicateRecipes,               # 14
    expense.ExpenseDeleteMultiple,                     # 15
    system_composite.TurnOnWifiAndOpenApp,             # 16
    system.SystemBluetoothTurnOff,                     # 17
    system.SystemWifiTurnOff,                          # 18
    system.SystemWifiTurnOn,                           # 19
    clock.ClockTimerEntry,                             # 20
    expense.ExpenseAddSingle,                          # 21
    markor.MarkorCreateFolder,                         # 22
    markor.MarkorDeleteNewestNote,                     # 23
    markor.MarkorEditNote,                             # 24
    system.SystemBrightnessMax,                        # 25
    system.SystemBrightnessMin,                        # 26
    system.SystemCopyToClipboard,                      # 27
    audio_recorder.AudioRecorderRecordAudioWithFileName,  # 28
    browser.BrowserDraw,                               # 29
    browser.BrowserMaze,                               # 30
    recipe.RecipeAddSingleRecipe,                      # 31
    recipe.RecipeDeleteSingleWithRecipeWithNoise,      # 32
    retro_music.RetroPlayingQueue,                     # 33
    calendar.SimpleCalendarAddOneEventRelativeDay,     # 34
    calendar.SimpleCalendarAddOneEventTomorrow,        # 35
    calendar.SimpleCalendarAddRepeatingEvent,          # 36
    simple_draw_pro.SimpleDrawProCreateDrawing,        # 37
    sms.SimpleSmsReply,                                # 38
    sms.SimpleSmsSendClipboardContent,                 # 39
    clock.ClockStopWatchPausedVerify,                  # 40
    system.SystemBluetoothTurnOffVerify,               # 41
    system.SystemBluetoothTurnOnVerify,                # 42
    system.SystemBrightnessMaxVerify,                  # 43
    system.SystemBrightnessMinVerify,                  # 44
    system.SystemWifiTurnOffVerify,                    # 45
    system.SystemWifiTurnOnVerify,                     # 46
    camera.CameraTakeVideo,                            # 47
    expense.ExpenseAddMultiple,                        # 48
    expense.ExpenseDeleteDuplicates,                   # 49
    expense.ExpenseDeleteDuplicates2,                  # 50
    markor.MarkorChangeNoteContent,                    # 51
    markor.MarkorCreateNote,                           # 52
    markor.MarkorCreateNoteFromClipboard,              # 53
    markor.MarkorMoveNote,                             # 54
    markor.MarkorTranscribeReceipt,                    # 55
    recipe.RecipeAddMultipleRecipes,                   # 56
    recipe.RecipeDeleteMultipleRecipesWithNoise,       # 57
    retro_music.RetroCreatePlaylist,                   # 58
    retro_music.RetroPlaylistDuration,                 # 59
    calendar.SimpleCalendarAddOneEventInTwoWeeks,      # 60
    calendar.SimpleCalendarDeleteEventsOnRelativeDay,  # 61
    files.FilesDeleteFile,                             # 62
    files.FilesMoveFile,                               # 63
    system_composite.TurnOffWifiAndTurnOnBluetooth,    # 64
    sms.SimpleSmsReplyMostRecent,                      # 65
    sms.SimpleSmsResend,                               # 66
    sms.SimpleSmsSend,                                 # 67
    sms.SimpleSmsSendReceivedAddress,                  # 68
    markor.MarkorAddNoteHeader,                        # 69
    recipe.RecipeDeleteDuplicateRecipes2,              # 70
    recipe.RecipeDeleteDuplicateRecipes3,              # 71
    vlc.VlcCreatePlaylist,                             # 72
    vlc.VlcCreateTwoPlaylists,                         # 73
    osmand.OsmAndFavorite,                             # 74
    browser.BrowserMultiply,                           # 75
    expense.ExpenseAddMultipleFromGallery,             # 76
    expense.ExpenseDeleteMultiple2,                    # 77
    markor.MarkorTranscribeVideo,                      # 78
    markor_sms.MarkorCreateNoteAndSms,                 # 79
    recipe.RecipeAddMultipleRecipesFromImage,          # 80
    recipe.RecipeAddMultipleRecipesFromMarkor,         # 81
    recipe.RecipeAddMultipleRecipesFromMarkor2,        # 82
    retro_music.RetroSavePlaylist,                     # 83
    simple_gallery_pro.SaveCopyOfReceiptTaskEval,      # 84
    calendar.SimpleCalendarAddOneEvent,                # 85
    expense.ExpenseAddMultipleFromMarkor,              # 86
    markor.MarkorMergeNotes,                           # 87
    osmand.OsmAndMarker,                               # 88
    osmand.OsmAndTrack,                                # 89
    recipe.RecipeDeleteMultipleRecipesWithConstraint,  # 90
)


# ── Public API ───────────────────────────────────────────────────────

class ExtendedTaskRegistry(_upstream_registry.TaskRegistry):
    """TaskRegistry with additional difficulty-tier families.

    Adds: easy, medium, hard, easy_medium, easy_medium_hard, android_easy.
    Delegates all upstream families unchanged.
    """

    EASY = 'easy'
    MEDIUM = 'medium'
    HARD = 'hard'
    EASY_MEDIUM = 'easy_medium'
    EASY_MEDIUM_HARD = 'easy_medium_hard'
    ANDROID_EASY = 'android_easy'
    TIER4 = 'tier4'
    ADB_EXCLUSIVE = 'adb_exclusive'

    # IR task names in v8 positional order (indices 91-115)
    _V8_IR_ORDER = (
        'SimpleCalendarEventsOnDate',                        # 91
        'SimpleCalendarNextEvent',                           # 92
        'SimpleCalendarEventOnDateAtTime',                   # 93
        'SimpleCalendarAnyEventsOnDate',                     # 94
        'SimpleCalendarNextMeetingWithPerson',               # 95
        'SimpleCalendarLocationOfEvent',                     # 96
        'SimpleCalendarEventsInNextWeek',                    # 97
        'SimpleCalendarFirstEventAfterStartTime',            # 98
        'SimpleCalendarEventsInTimeRange',                   # 99
        'TasksDueOnDate',                                    # 100
        'TasksHighPriorityTasks',                            # 101
        'TasksHighPriorityTasksDueOnDate',                   # 102
        'TasksDueNextWeek',                                  # 103
        'TasksCompletedTasksForDate',                        # 104
        'TasksIncompleteTasksOnDate',                        # 105
        'SportsTrackerActivitiesOnDate',                     # 106
        'SportsTrackerActivitiesCountForWeek',               # 107
        'SportsTrackerActivityDuration',                     # 108
        'SportsTrackerLongestDistanceActivity',              # 109
        'SportsTrackerTotalDurationForCategoryThisWeek',     # 110
        'SportsTrackerTotalDistanceForCategoryOverInterval', # 111
        'NotesRecipeIngredientCount',                        # 112
        'NotesMeetingAttendeeCount',                         # 113
        'NotesIsTodo',                                       # 114
        'NotesTodoItemCount',                                # 115
    )

    def __init__(self):
        super().__init__()
        # Build tier registries from our curated lists
        self._easy_reg = _build_registry(_EASY_TASKS)
        self._medium_reg = _build_registry(_MEDIUM_TASKS)
        self._hard_reg = _build_registry(_HARD_TASKS)

        ir = self.INFORMATION_RETRIEVAL_TASK_REGISTRY
        self._ir_easy = _filter_ir(ir, _IR_EASY)
        self._ir_medium = _filter_ir(ir, _IR_MEDIUM)
        self._ir_hard = _filter_ir(ir, _IR_HARD)

        self._tier4_reg = _build_registry(_TIER4_TASKS)

        # Build v8-compatible ordered registry (action tasks 0-90 + IR tasks 91-115)
        from collections import OrderedDict
        self._v8_ordered_reg = OrderedDict()
        for cls in _V8_ANDROID_WORLD_ORDER:
            self._v8_ordered_reg[cls.__name__] = cls
        for name in self._V8_IR_ORDER:
            if name in ir:
                self._v8_ordered_reg[name] = ir[name]

    def get_registry(self, family):
        if family in (self.TIER4, self.ADB_EXCLUSIVE):
            return self._tier4_reg
        elif family == self.EASY:
            return {**self._easy_reg, **self._ir_easy}
        elif family == self.MEDIUM:
            return {**self._medium_reg, **self._ir_medium}
        elif family == self.HARD:
            return {**self._hard_reg, **self._ir_hard}
        elif family == self.EASY_MEDIUM:
            return {
                **self._easy_reg, **self._ir_easy,
                **self._medium_reg, **self._ir_medium,
            }
        elif family == self.EASY_MEDIUM_HARD:
            return {
                **self._easy_reg, **self._ir_easy,
                **self._medium_reg, **self._ir_medium,
                **self._hard_reg, **self._ir_hard,
            }
        elif family == self.ANDROID_EASY:
            return self._easy_reg
        elif family in ('android_world', 'android'):
            # Return tasks in v8-compatible positional order so that
            # JSONL data files (which use numeric task_id as index) work
            # unchanged with the upstream 2026 packages.
            return self._v8_ordered_reg
        else:
            return super().get_registry(family)


# Singleton — import and use directly
TaskRegistry = ExtendedTaskRegistry
