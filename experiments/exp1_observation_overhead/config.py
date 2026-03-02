"""
Configuration for Experiment 1: Per-Step Observation Overhead Micro-benchmark.

All ADB commands use bare `adb` prefix. The benchmark runner prepends
`-s <serial>` at runtime so configs stay clean and portable.
"""

import os

# ---------------------------------------------------------------------------
# Repetition & timing
# ---------------------------------------------------------------------------
NUM_REPETITIONS = 100
NUM_WARMUP = 5
COOLDOWN_BETWEEN_CONDITIONS = 2.0   # seconds between condition switches
COOLDOWN_BETWEEN_REPS = 0.1         # seconds between repetitions
ADB_TIMEOUT = 30                    # seconds per ADB command

# ---------------------------------------------------------------------------
# App screens to measure on (navigated via ADB before each condition block)
# ---------------------------------------------------------------------------
APP_SCREENS = [
    {
        "name": "home",
        "setup_cmd": "adb shell input keyevent KEYCODE_HOME",
        "description": "Android home screen",
    },
    {
        "name": "settings_main",
        "setup_cmd": "adb shell am start -a android.settings.SETTINGS",
        "description": "Top-level Settings activity",
    },
    {
        "name": "clock",
        "setup_cmd": "adb shell am start -n com.google.android.deskclock/com.android.deskclock.DeskClock",
        "description": "Clock app (moderate UI complexity)",
    },
]

# ---------------------------------------------------------------------------
# Conditions to benchmark
# ---------------------------------------------------------------------------
CONDITIONS = [
    # --- Screenshot: end-to-end (capture + transfer) ---
    {
        "name": "screenshot_png",
        "category": "Screenshot",
        "cmd": "adb shell screencap -p /sdcard/screen.png && adb pull /sdcard/screen.png /dev/null",
        "description": "Capture PNG screenshot + pull to host",
    },
    {
        "name": "screenshot_raw",
        "category": "Screenshot",
        "cmd": "adb shell screencap /sdcard/screen.raw && adb pull /sdcard/screen.raw /dev/null",
        "description": "Capture raw framebuffer + pull to host",
    },
    # --- Screenshot: breakdown (capture only, no transfer) ---
    {
        "name": "screencap_png_only",
        "category": "Screenshot (breakdown)",
        "cmd": "adb shell screencap -p /sdcard/screen.png",
        "description": "PNG capture on-device only (no pull)",
    },
    {
        "name": "screencap_raw_only",
        "category": "Screenshot (breakdown)",
        "cmd": "adb shell screencap /sdcard/screen.raw",
        "description": "Raw framebuffer capture on-device only (no pull)",
    },
    {
        "name": "pull_png_only",
        "category": "Screenshot (breakdown)",
        "cmd": "adb pull /sdcard/screen.png /dev/null",
        "description": "Pull existing PNG from device (transfer cost only)",
    },
    {
        "name": "pull_raw_only",
        "category": "Screenshot (breakdown)",
        "cmd": "adb pull /sdcard/screen.raw /dev/null",
        "description": "Pull existing raw framebuffer from device (transfer cost only)",
    },
    # --- A11y tree: all known methods ---
    {
        "name": "a11y_uiautomator_dump",
        "category": "A11y Tree",
        "cmd": "adb shell uiautomator dump /sdcard/ui.xml && adb pull /sdcard/ui.xml /dev/null",
        "description": "UIAutomator XML dump + pull (cold JVM start each call)",
    },
    {
        "name": "a11y_uiautomator_stdout",
        "category": "A11y Tree",
        "cmd": "adb shell uiautomator dump /dev/tty",
        "description": "UIAutomator dump to stdout (no file I/O, still cold JVM)",
    },
    {
        "name": "a11y_dumpsys_accessibility",
        "category": "A11y Tree",
        "cmd": "adb shell dumpsys accessibility",
        "description": "dumpsys accessibility (service metadata only, no node tree)",
    },
    {
        "name": "a11y_dumpsys_activity_top",
        "category": "A11y Tree",
        "cmd": "adb shell dumpsys activity top",
        "description": "View hierarchy of top activity (partial tree, no a11y props)",
    },
    # --- Direct ADB (baseline) ---
    {
        "name": "adb_getprop",
        "category": "Direct ADB",
        "cmd": "adb shell getprop ro.build.display.id",
        "description": "Read a build property (minimal payload)",
    },
    {
        "name": "adb_wm_size",
        "category": "Direct ADB",
        "cmd": "adb shell wm size",
        "description": "Query window manager display size",
    },
    {
        "name": "adb_input_tap",
        "category": "Direct ADB",
        "cmd": "adb shell input tap 0 0",
        "description": "Send a no-op tap at (0,0)",
    },
]

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "results")
