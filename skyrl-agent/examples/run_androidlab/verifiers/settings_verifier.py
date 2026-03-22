"""ADB verifiers for Android-Lab Settings tasks (14 operation tasks)."""

from .base import ADBVerifier


class Setting1_WifiAutoOff(ADBVerifier):
    """setting_1: Turn off auto wifi."""
    task_id = "setting_1"

    def is_successful(self):
        # Android has two related keys — either being 0 counts
        v1 = self.settings_get("global", "wifi_scan_always_enabled")
        v2 = self.settings_get("global", "wifi_wakeup_enabled")
        ok = v1 == "0" or v2 == "0"
        return {"complete": ok, "1": ok}


class Setting2_PrivateDNS(ADBVerifier):
    """setting_2: Set private DNS to dns.google."""
    task_id = "setting_2"

    def is_successful(self):
        mode = self.settings_get("global", "private_dns_mode")
        specifier = self.settings_get("global", "private_dns_specifier")
        mode_ok = mode == "hostname"
        dns_ok = specifier == "dns.google"
        return {"complete": mode_ok and dns_ok, "1": mode_ok, "2": dns_ok}


class Setting3_BluetoothOff(ADBVerifier):
    """setting_3: Turn off bluetooth."""
    task_id = "setting_3"

    def is_successful(self):
        val = self.settings_get("global", "bluetooth_on")
        ok = val == "0"
        return {"complete": ok, "1": ok}


class Setting4_BluetoothName(ADBVerifier):
    """setting_4: Change bluetooth device name to 'my AVD'."""
    task_id = "setting_4"

    def is_successful(self):
        val = self.settings_get("secure", "bluetooth_name")
        ok = val == "my AVD"
        return {"complete": ok, "1": ok}


class Setting5_BatteryPercentage(ADBVerifier):
    """setting_5: Show battery percentage in status bar."""
    task_id = "setting_5"

    def is_successful(self):
        # Try multiple possible keys across Android versions
        for ns, key in [
            ("system", "status_bar_show_battery_percent"),
            ("secure", "battery_percentage_enabled"),
            ("system", "show_battery_percent"),
            ("global", "battery_percentage_enabled"),
        ]:
            val = self.settings_get(ns, key)
            if val == "1":
                return {"complete": True, "1": True}
        # Fallback: check via QS tiles or statusbar dump
        result = self.shell("dumpsys statusbar | grep -i battery_percent")
        if "true" in result.lower():
            return {"complete": True, "1": True}
        return {"complete": False, "1": False}


class Setting7_DarkTheme(ADBVerifier):
    """setting_7: Turn phone to Dark theme."""
    task_id = "setting_7"

    def is_successful(self):
        val = self.settings_get("secure", "ui_night_mode")
        ok = val == "2"  # 2 = dark mode
        return {"complete": ok, "1": ok}


class Setting8_Brightness(ADBVerifier):
    """setting_8: Change brightness level to 0%."""
    task_id = "setting_8"

    def is_successful(self):
        val = self.settings_get("system", "screen_brightness")
        try:
            brightness = int(val)
            ok = brightness <= 1  # 0 or 1 (UI min may be 1)
        except (ValueError, TypeError):
            ok = False
        return {"complete": ok, "1": ok}


class Setting13_RingVibrationOff(ADBVerifier):
    """setting_13: Turn off ring vibration."""
    task_id = "setting_13"

    def is_successful(self):
        val = self.settings_get("system", "vibrate_when_ringing")
        ok = val == "0"
        return {"complete": ok, "1": ok}


class Setting15_AddSpanish(ADBVerifier):
    """setting_15: Add Español (Estados Unidos) as second favorite language."""
    task_id = "setting_15"

    def is_successful(self):
        val = self.settings_get("system", "system_locales")
        ok = "es-US" in val or "es_US" in val
        return {"complete": ok, "1": ok}


class Setting18_DisableContactsNotif(ADBVerifier):
    """setting_18: Disable Contacts' APP notifications."""
    task_id = "setting_18"

    def is_successful(self):
        result = self.shell(
            "cmd appops get com.google.android.contacts POST_NOTIFICATION"
        )
        ok = "deny" in result.lower() or "ignore" in result.lower()
        if not ok:
            # Alternative check via notification policy
            result2 = self.shell(
                "cmd notification list_channels com.google.android.contacts"
            )
            # If all channels have importance=0, notifications are disabled
            ok = "importance=0" in result2 or "enabled=false" in result2.lower()
        return {"complete": ok, "1": ok}


class Setting19_DefaultBrowserFirefox(ADBVerifier):
    """setting_19: Change default browser to Firefox."""
    task_id = "setting_19"

    def is_successful(self):
        result = self.shell(
            "cmd package resolve-activity --brief "
            "-a android.intent.action.VIEW -d http://example.com"
        )
        ok = "firefox" in result.lower() or "org.mozilla" in result.lower()
        return {"complete": ok, "1": ok}


class Setting20_UninstallBooking(ADBVerifier):
    """setting_20: Uninstall booking app."""
    task_id = "setting_20"

    def is_successful(self):
        ok = not self.package_installed("com.booking")
        return {"complete": ok, "1": ok}


class Setting21_OpenSettings(ADBVerifier):
    """setting_21: Open settings."""
    task_id = "setting_21"

    def is_successful(self):
        activity = self.foreground_activity()
        # Must be the actual Settings activity, not FallbackHome
        ok = ("com.android.settings" in activity
              and "FallbackHome" not in activity)
        return {"complete": ok, "1": ok}


class Setting22_AirplaneModeStatus(ADBVerifier):
    """setting_22: Check airplane mode status (query via adb_query)."""
    task_id = "setting_22"

    def is_successful(self):
        # This is actually checking if agent can report status
        # The original judge checks if agent opens settings and sees the toggle
        # For terminal: just check the value is queryable
        val = self.settings_get("global", "airplane_mode_on")
        # The task asks "Does my airplane mode open or not" — it's a UI check
        # Success = agent navigated to and displayed the status
        # For terminal evaluation: if agent queried and reported, count as success
        # Since we can't verify what agent reported, just check foreground
        activity = self.foreground_activity()
        ok = "com.android.settings" in activity
        return {"complete": ok, "1": ok}


FUNCTION_MAP = {
    "setting_1": Setting1_WifiAutoOff,
    "setting_2": Setting2_PrivateDNS,
    "setting_3": Setting3_BluetoothOff,
    "setting_4": Setting4_BluetoothName,
    "setting_5": Setting5_BatteryPercentage,
    "setting_7": Setting7_DarkTheme,
    "setting_8": Setting8_Brightness,
    "setting_13": Setting13_RingVibrationOff,
    "setting_15": Setting15_AddSpanish,
    "setting_18": Setting18_DisableContactsNotif,
    "setting_19": Setting19_DefaultBrowserFirefox,
    "setting_20": Setting20_UninstallBooking,
    "setting_21": Setting21_OpenSettings,
    "setting_22": Setting22_AirplaneModeStatus,
}
