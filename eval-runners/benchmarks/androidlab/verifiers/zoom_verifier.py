"""ADB verifiers for Android-Lab Zoom tasks (5 operation tasks).

Zoom stores minimal local state — most verification requires UI inspection.
We use foreground activity + XML dump as fallback.
"""

from .base import ADBVerifier


class ZoomVerifierBase(ADBVerifier):
    """Base for Zoom tasks — mostly UI-based verification."""

    def is_zoom_foreground(self) -> bool:
        activity = self.foreground_activity()
        return "zoom" in activity.lower()

    def dump_ui_xml(self) -> str:
        """Dump current UI XML for text matching."""
        self.shell("uiautomator dump /sdcard/window_dump.xml")
        return self.shell("cat /sdcard/window_dump.xml")


class Zoom1_JoinMeeting(ZoomVerifierBase):
    """zoom_1: Join meeting 1234567890 (don't click join)."""
    task_id = "zoom_1"

    def is_successful(self):
        if not self.is_zoom_foreground():
            return {"complete": False, "1": False}
        xml = self.dump_ui_xml()
        ok = "1234567890" in xml
        return {"complete": ok, "1": ok}


class Zoom2_JoinAsAlice(ZoomVerifierBase):
    """zoom_2: Join meeting 0987654321, name as 'Alice'."""
    task_id = "zoom_2"

    def is_successful(self):
        if not self.is_zoom_foreground():
            return {"complete": False, "1": False, "2": False}
        xml = self.dump_ui_xml()
        meeting_ok = "0987654321" in xml
        name_ok = "Alice" in xml
        return {"complete": meeting_ok and name_ok, "1": meeting_ok, "2": name_ok}


class Zoom3_JoinNoAudioVideo(ZoomVerifierBase):
    """zoom_3: Join meeting 1234567890 without audio and video."""
    task_id = "zoom_3"

    def is_successful(self):
        if not self.is_zoom_foreground():
            return {"complete": False, "1": False, "2": False, "3": False}
        xml = self.dump_ui_xml()
        meeting_ok = "1234567890" in xml
        # Check if audio/video toggles are off (checked state in XML)
        audio_off = 'Don' in xml and 'Audio' in xml  # "Don't Connect To Audio"
        video_off = 'Turn Off' in xml and 'Video' in xml
        return {
            "complete": meeting_ok and (audio_off or video_off),
            "1": meeting_ok, "2": audio_off, "3": video_off,
        }


class Zoom4_AutoConnectAudio(ZoomVerifierBase):
    """zoom_4: Set auto connect to audio when wifi connected."""
    task_id = "zoom_4"

    def is_successful(self):
        # Check Zoom's SharedPreferences if available
        prefs = self.shell(
            "cat /data/data/us.zoom.videomeetings/shared_prefs/*.xml 2>/dev/null"
        )
        if "auto_connect" in prefs.lower() and "wifi" in prefs.lower():
            return {"complete": True, "1": True}
        # Fallback: check UI
        if self.is_zoom_foreground():
            xml = self.dump_ui_xml()
            ok = "Auto-Connect" in xml or "Wi-Fi" in xml
            return {"complete": ok, "1": ok}
        return {"complete": False, "1": False}


class Zoom5_ReactionSkinTone(ZoomVerifierBase):
    """zoom_5: Change reaction skin to Medium-light."""
    task_id = "zoom_5"

    def is_successful(self):
        prefs = self.shell(
            "cat /data/data/us.zoom.videomeetings/shared_prefs/*.xml 2>/dev/null"
        )
        if "medium" in prefs.lower() and "light" in prefs.lower():
            return {"complete": True, "1": True}
        if self.is_zoom_foreground():
            xml = self.dump_ui_xml()
            ok = "Medium-Light" in xml or "medium-light" in xml
            return {"complete": ok, "1": ok}
        return {"complete": False, "1": False}


FUNCTION_MAP = {
    "zoom_1": Zoom1_JoinMeeting,
    "zoom_2": Zoom2_JoinAsAlice,
    "zoom_3": Zoom3_JoinNoAudioVideo,
    "zoom_4": Zoom4_AutoConnectAudio,
    "zoom_5": Zoom5_ReactionSkinTone,
}
