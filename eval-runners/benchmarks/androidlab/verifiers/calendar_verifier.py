"""ADB verifiers for Android-Lab Calendar/Calendario tasks (14 operation tasks).

Calendario uses Realm DB (not SQLite). We verify by:
1. Grepping Realm binary for event title strings
2. Checking if the app is in the expected state
"""

from .base import ADBVerifier

REALM_PATH = "/data/data/com.skuld.calendario/files/default.realm"


class CalendarVerifierBase(ADBVerifier):
    """Base with Calendario Realm query helpers."""

    def realm_contains(self, text: str) -> bool:
        """Check if the Realm DB contains a text string."""
        result = self.shell(
            f"strings {REALM_PATH} 2>/dev/null | grep -i '{text}'"
        )
        return text.lower() in result.lower()

    def realm_strings(self) -> str:
        """Get all readable strings from the Realm DB."""
        return self.shell(f"strings {REALM_PATH} 2>/dev/null")


class Calendar1_AddWork5PM(CalendarVerifierBase):
    """calendar_1: Add event 'work' at 5:00PM today."""
    task_id = "calendar_1"

    def is_successful(self):
        ok = self.realm_contains("work")
        return {"complete": ok, "1": ok}


class Calendar2_HomeworkMay21(CalendarVerifierBase):
    """calendar_2: Event 'homework' May 21, notification 10 minutes before."""
    task_id = "calendar_2"

    def is_successful(self):
        ok = self.realm_contains("homework")
        return {"complete": ok, "1": ok}


class Calendar3_MeetingMay13(CalendarVerifierBase):
    """calendar_3: Event 'meeting' May 13, note 'conference room B202'."""
    task_id = "calendar_3"

    def is_successful(self):
        title_ok = self.realm_contains("meeting")
        note_ok = self.realm_contains("B202") or self.realm_contains("conference")
        return {"complete": title_ok and note_ok, "1": title_ok, "2": note_ok}


class Calendar4_MonthlyRepeat(CalendarVerifierBase):
    """calendar_4: Event starting 2024/6/1, repeats monthly."""
    task_id = "calendar_4"

    def is_successful(self):
        # Check for any new event in Realm
        strings = self.realm_strings()
        # Monthly repeat might show as "MONTHLY" or similar in Realm
        has_event = len(strings.strip().split("\n")) > 30  # more content than empty
        return {"complete": has_event, "1": has_event}


class Calendar5_EditWorkEndTime(CalendarVerifierBase):
    """calendar_5: Edit 'work' event, change end time to 7:00 PM."""
    task_id = "calendar_5"

    def is_successful(self):
        ok = self.realm_contains("work")
        return {"complete": ok, "1": ok}


class Calendar6_HomeworkNote(CalendarVerifierBase):
    """calendar_6: Add note 'classroom 101' to event 'homework'."""
    task_id = "calendar_6"

    def is_successful(self):
        title_ok = self.realm_contains("homework")
        note_ok = self.realm_contains("classroom 101") or self.realm_contains("classroom")
        return {"complete": title_ok and note_ok, "1": title_ok, "2": note_ok}


class Calendar7_MeetingNotification(CalendarVerifierBase):
    """calendar_7: Change notification of 'meeting' to 5 and 10 minutes before."""
    task_id = "calendar_7"

    def is_successful(self):
        ok = self.realm_contains("meeting")
        return {"complete": ok, "1": ok}


class Calendar8_WorkNote(CalendarVerifierBase):
    """calendar_8: Edit 'work', add note 'computer'."""
    task_id = "calendar_8"

    def is_successful(self):
        title_ok = self.realm_contains("work")
        note_ok = self.realm_contains("computer")
        return {"complete": title_ok and note_ok, "1": title_ok, "2": note_ok}


class Calendar9_WorkDaily(CalendarVerifierBase):
    """calendar_9: Set 'work' event recurrence to daily."""
    task_id = "calendar_9"

    def is_successful(self):
        ok = self.realm_contains("work")
        return {"complete": ok, "1": ok}


class Calendar10_AddThisDay(CalendarVerifierBase):
    """calendar_10: Arrange event 'this day'."""
    task_id = "calendar_10"

    def is_successful(self):
        ok = self.realm_contains("this day")
        return {"complete": ok, "1": ok}


class Calendar11_ThisDayWeekly(CalendarVerifierBase):
    """calendar_11: Edit 'this day', make it repeat weekly."""
    task_id = "calendar_11"

    def is_successful(self):
        ok = self.realm_contains("this day")
        return {"complete": ok, "1": ok}


class Calendar12_TodayNoteHello(CalendarVerifierBase):
    """calendar_12: Add note 'Hello' to event 'Today'."""
    task_id = "calendar_12"

    def is_successful(self):
        title_ok = self.realm_contains("Today")
        note_ok = self.realm_contains("Hello")
        return {"complete": title_ok and note_ok, "1": title_ok, "2": note_ok}


class Calendar13_AddExam(CalendarVerifierBase):
    """calendar_13: Arrange event 'exam'."""
    task_id = "calendar_13"

    def is_successful(self):
        ok = self.realm_contains("exam")
        return {"complete": ok, "1": ok}


class Calendar14_ExamAllDay(CalendarVerifierBase):
    """calendar_14: Edit 'exam', make it all-day event."""
    task_id = "calendar_14"

    def is_successful(self):
        ok = self.realm_contains("exam")
        return {"complete": ok, "1": ok}


FUNCTION_MAP = {
    "calendar_1": Calendar1_AddWork5PM,
    "calendar_2": Calendar2_HomeworkMay21,
    "calendar_3": Calendar3_MeetingMay13,
    "calendar_4": Calendar4_MonthlyRepeat,
    "calendar_5": Calendar5_EditWorkEndTime,
    "calendar_6": Calendar6_HomeworkNote,
    "calendar_7": Calendar7_MeetingNotification,
    "calendar_8": Calendar8_WorkNote,
    "calendar_9": Calendar9_WorkDaily,
    "calendar_10": Calendar10_AddThisDay,
    "calendar_11": Calendar11_ThisDayWeekly,
    "calendar_12": Calendar12_TodayNoteHello,
    "calendar_13": Calendar13_AddExam,
    "calendar_14": Calendar14_ExamAllDay,
}
