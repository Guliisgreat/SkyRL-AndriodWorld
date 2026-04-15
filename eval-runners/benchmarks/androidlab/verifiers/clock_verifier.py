"""ADB verifiers for Android-Lab Clock tasks (22 operation tasks)."""

from .base import ADBVerifier

ALARM_DB = "/data/user_de/0/com.google.android.deskclock/databases/alarms.db"


class ClockVerifierBase(ADBVerifier):
    """Base with alarm query helpers."""

    def get_alarms(self) -> list:
        """Get all alarms from the Clock DB."""
        result = self.sqlite_query(
            ALARM_DB,
            "SELECT _id,hour,minutes,daysofweek,enabled,vibrate,label,ringtone "
            "FROM alarm_templates"
        )
        alarms = []
        for line in result.strip().split("\n"):
            if line.startswith("_id") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 7:
                alarms.append({
                    "_id": parts[0],
                    "hour": int(parts[1]) if parts[1].isdigit() else 0,
                    "minutes": int(parts[2]) if parts[2].isdigit() else 0,
                    "daysofweek": int(parts[3]) if parts[3].isdigit() else 0,
                    "enabled": int(parts[4]) if parts[4].isdigit() else 0,
                    "vibrate": int(parts[5]) if parts[5].isdigit() else 0,
                    "label": parts[6] if len(parts) > 6 else "",
                    "ringtone": parts[7] if len(parts) > 7 else "",
                })
        return alarms

    def find_alarm(self, hour: int, minutes: int = 0) -> dict:
        """Find an alarm matching the given time."""
        for a in self.get_alarms():
            if a["hour"] == hour and a["minutes"] == minutes:
                return a
        return {}


class Clock1_Alarm3PM_Meeting(ClockVerifierBase):
    """clock_1: Set alarm for 3PM with label 'meeting'."""
    task_id = "clock_1"

    def is_successful(self):
        alarm = self.find_alarm(15, 0)
        exists = bool(alarm)
        label_ok = alarm.get("label", "").lower() == "meeting" if alarm else False
        return {"complete": exists and label_ok, "1": exists, "2": label_ok}


class Clock2_Alarm645AM(ClockVerifierBase):
    """clock_2: Set alarm 6:45AM, no vibrate, ringtone Argon."""
    task_id = "clock_2"

    def is_successful(self):
        alarm = self.find_alarm(6, 45)
        exists = bool(alarm)
        vibrate_ok = alarm.get("vibrate", 1) == 0 if alarm else False
        ring_ok = "argon" in alarm.get("ringtone", "").lower() if alarm else False
        return {
            "complete": exists and vibrate_ok and ring_ok,
            "1": exists, "2": vibrate_ok, "3": ring_ok,
        }


class Clock3_AlarmWeekdays7AM(ClockVerifierBase):
    """clock_3: Alarm every Mon-Fri, 7AM."""
    task_id = "clock_3"

    def is_successful(self):
        alarm = self.find_alarm(7, 0)
        exists = bool(alarm)
        # Mon-Fri bitmask: Mon=2,Tue=4,Wed=8,Thu=16,Fri=32 = 62
        # Or Mon=1,Tue=2,...,Fri=16 = 31 (depends on implementation)
        dow = alarm.get("daysofweek", 0) if alarm else 0
        days_ok = dow in (31, 62)  # accept both conventions
        return {"complete": exists and days_ok, "1": exists, "2": days_ok}


class Clock4_9AM_Everyday(ClockVerifierBase):
    """clock_4: Change 9AM alarm to ring everyday."""
    task_id = "clock_4"

    def is_successful(self):
        alarm = self.find_alarm(9, 0)
        exists = bool(alarm)
        dow = alarm.get("daysofweek", 0) if alarm else 0
        days_ok = dow in (127, 254)  # all 7 days
        return {"complete": exists and days_ok, "1": exists, "2": days_ok}


class Clock5_Alarm1030AM(ClockVerifierBase):
    """clock_5: Set alarm at 10:30AM tomorrow."""
    task_id = "clock_5"

    def is_successful(self):
        alarm = self.find_alarm(10, 30)
        exists = bool(alarm)
        return {"complete": exists, "1": exists}


class Clock6_1030PM_Weekends(ClockVerifierBase):
    """clock_6: 10:30PM weekends, label 'Watch Football Games'."""
    task_id = "clock_6"

    def is_successful(self):
        alarm = self.find_alarm(22, 30)
        exists = bool(alarm)
        dow = alarm.get("daysofweek", 0) if alarm else 0
        # Sat+Sun: 64+1=65 or 32+64=96 (depends on convention)
        days_ok = dow in (65, 96, 192)
        label_ok = "watch football" in alarm.get("label", "").lower() if alarm else False
        return {
            "complete": exists and days_ok and label_ok,
            "1": exists, "2": days_ok, "3": label_ok,
        }


class Clock7_TurnOffAll(ClockVerifierBase):
    """clock_7: Turn off all alarms."""
    task_id = "clock_7"

    def is_successful(self):
        alarms = self.get_alarms()
        all_off = all(a["enabled"] == 0 for a in alarms)
        return {"complete": all_off, "1": all_off}


class Clock8_DeleteAfter2PM(ClockVerifierBase):
    """clock_8: Delete all alarms after 2PM."""
    task_id = "clock_8"

    def is_successful(self):
        alarms = self.get_alarms()
        after_2pm = [a for a in alarms if a["hour"] >= 14]
        ok = len(after_2pm) == 0
        return {"complete": ok, "1": ok}


class Clock9_TurnOff4PM(ClockVerifierBase):
    """clock_9: Turn off alarm at 4PM."""
    task_id = "clock_9"

    def is_successful(self):
        alarm = self.find_alarm(16, 0)
        ok = alarm.get("enabled", 1) == 0 if alarm else False
        return {"complete": ok, "1": ok}


class Clock15_AddWorldClocks(ClockVerifierBase):
    """clock_15: Add London and Barcelona time."""
    task_id = "clock_15"

    def _read_clock_prefs(self):
        """Read clock prefs from all possible locations."""
        paths = [
            "/data/data/com.google.android.deskclock/shared_prefs/com.google.android.deskclock_preferences.xml",
            "/data/user_de/0/com.google.android.deskclock/shared_prefs/com.google.android.deskclock_preferences.xml",
            "/data/data/com.google.android.deskclock/shared_prefs/primes.xml",
        ]
        combined = ""
        for p in paths:
            r = self.shell(f"cat {p} 2>/dev/null")
            combined += r
        # Also check all XML files in shared_prefs
        r = self.shell("cat /data/data/com.google.android.deskclock/shared_prefs/*.xml 2>/dev/null")
        combined += r
        r = self.shell("cat /data/user_de/0/com.google.android.deskclock/shared_prefs/*.xml 2>/dev/null")
        combined += r
        return combined

    def is_successful(self):
        prefs = self._read_clock_prefs()
        london_ok = "London" in prefs or "Europe/London" in prefs
        barcelona_ok = "Barcelona" in prefs or "Europe/Madrid" in prefs
        return {
            "complete": london_ok and barcelona_ok,
            "1": london_ok, "2": barcelona_ok,
        }


class Clock17_DeleteBarcelona(ClockVerifierBase):
    """clock_17: Delete Barcelona time from clock."""
    task_id = "clock_17"

    def is_successful(self):
        prefs = Clock15_AddWorldClocks._read_clock_prefs(self)
        # If prefs are empty, we can't confirm deletion — check that
        # Barcelona was never added rather than claiming success
        if not prefs.strip():
            return {"complete": False, "1": False}
        ok = "Barcelona" not in prefs and "Europe/Madrid" not in prefs
        return {"complete": ok, "1": ok}


class Clock25_OpenClock(ClockVerifierBase):
    """clock_25: Open clock app."""
    task_id = "clock_25"

    def is_successful(self):
        activity = self.foreground_activity()
        if "deskclock" in activity.lower():
            return {"complete": True, "1": True}
        # Check recents
        recents = self.shell("dumpsys activity recents | grep deskclock")
        ok = "deskclock" in recents.lower()
        return {"complete": ok, "1": ok}


class Clock26_Close730AM(ClockVerifierBase):
    """clock_26: Close 7:30AM alarm."""
    task_id = "clock_26"

    def is_successful(self):
        alarm = self.find_alarm(7, 30)
        ok = alarm.get("enabled", 1) == 0 if alarm else False
        return {"complete": ok, "1": ok}


class Clock27_SetAlarm3PM(ClockVerifierBase):
    """clock_27: Set alarm at 3PM."""
    task_id = "clock_27"

    def is_successful(self):
        alarm = self.find_alarm(15, 0)
        exists = bool(alarm)
        return {"complete": exists, "1": exists}


# Tasks 18-24 require UI state or shared_prefs that are harder to verify
# Using simplified checks where possible

class Clock18_Timer1h15m(ClockVerifierBase):
    """clock_18: Set countdown timer for 1h15m, don't start."""
    task_id = "clock_18"

    def is_successful(self):
        # Timer state is in app memory, check via dumpsys
        result = self.shell("dumpsys activity service com.google.android.deskclock")
        ok = "75" in result or "1:15" in result or "4500" in result
        return {"complete": ok, "1": ok}


class Clock19_Bedtime(ClockVerifierBase):
    """clock_19: Set bedtime 10PM, wake up 7AM."""
    task_id = "clock_19"

    def is_successful(self):
        prefs = Clock15_AddWorldClocks._read_clock_prefs(self)
        bedtime_ok = "22" in prefs or "10:00 PM" in prefs or "bedtime" in prefs.lower()
        wake_ok = "7:00" in prefs or "7:00 AM" in prefs or "wake" in prefs.lower()
        # Also check via settings
        if not bedtime_ok:
            r = self.settings_get("secure", "bedtime_mode")
            bedtime_ok = r not in ("null", "")
        return {"complete": bedtime_ok and wake_ok, "1": bedtime_ok, "2": wake_ok}


class Clock20_SleepSoundsDeepSpace(ClockVerifierBase):
    """clock_20: Set sleep sounds to deep space."""
    task_id = "clock_20"

    def is_successful(self):
        prefs = Clock15_AddWorldClocks._read_clock_prefs(self)
        ok = "deep_space" in prefs.lower() or "deep space" in prefs.lower()
        return {"complete": ok, "1": ok}


class Clock21_WakeUpAlarm(ClockVerifierBase):
    """clock_21: Turn on Wake-up alarm in Bedtime."""
    task_id = "clock_21"

    def is_successful(self):
        prefs = Clock15_AddWorldClocks._read_clock_prefs(self)
        # Check for wake_up or wakeup enabled
        ok = ("wake" in prefs.lower() and "true" in prefs.lower()) or \
             "wakeup_enabled" in prefs.lower()
        if not ok:
            # Agent may have written to settings
            r = self.settings_get("secure", "alarm_enabled")
            ok = r == "1"
        return {"complete": ok, "1": ok}


class Clock22_AnalogStyle(ClockVerifierBase):
    """clock_22: Set alarm style to Analog."""
    task_id = "clock_22"

    def is_successful(self):
        prefs = Clock15_AddWorldClocks._read_clock_prefs(self)
        ok = "analog" in prefs.lower() or "ANALOG" in prefs
        if not ok:
            # Check settings
            r = self.settings_get("system", "clock_style")
            ok = r.lower() in ("analog", "1") if r != "null" else False
        return {"complete": ok, "1": ok}


class Clock23_TimezoneTokyo(ClockVerifierBase):
    """clock_23: Change home timezone to Tokyo."""
    task_id = "clock_23"

    def is_successful(self):
        prefs = Clock15_AddWorldClocks._read_clock_prefs(self)
        ok = "Asia/Tokyo" in prefs or "Tokyo" in prefs
        if not ok:
            # Check system timezone settings
            r = self.settings_get("global", "time_zone")
            ok = "Tokyo" in r or "Asia/Tokyo" in r
        if not ok:
            r = self.shell("getprop persist.sys.timezone")
            ok = "Tokyo" in r
        return {"complete": ok, "1": ok}


class Clock24_SilenceAfter5Min(ClockVerifierBase):
    """clock_24: Modify silence after to 5 minutes."""
    task_id = "clock_24"

    def is_successful(self):
        prefs = Clock15_AddWorldClocks._read_clock_prefs(self)
        # Look for silence_after or auto_silence with value 5
        ok = "silence_after" in prefs and "5" in prefs
        if not ok:
            ok = "auto_silence" in prefs.lower() and "5" in prefs
        return {"complete": ok, "1": ok}


FUNCTION_MAP = {
    "clock_1": Clock1_Alarm3PM_Meeting,
    "clock_2": Clock2_Alarm645AM,
    "clock_3": Clock3_AlarmWeekdays7AM,
    "clock_4": Clock4_9AM_Everyday,
    "clock_5": Clock5_Alarm1030AM,
    "clock_6": Clock6_1030PM_Weekends,
    "clock_7": Clock7_TurnOffAll,
    "clock_8": Clock8_DeleteAfter2PM,
    "clock_9": Clock9_TurnOff4PM,
    "clock_15": Clock15_AddWorldClocks,
    "clock_17": Clock17_DeleteBarcelona,
    "clock_18": Clock18_Timer1h15m,
    "clock_19": Clock19_Bedtime,
    "clock_20": Clock20_SleepSoundsDeepSpace,
    "clock_21": Clock21_WakeUpAlarm,
    "clock_22": Clock22_AnalogStyle,
    "clock_23": Clock23_TimezoneTokyo,
    "clock_24": Clock24_SilenceAfter5Min,
    "clock_25": Clock25_OpenClock,
    "clock_26": Clock26_Close730AM,
    "clock_27": Clock27_SetAlarm3PM,
}
