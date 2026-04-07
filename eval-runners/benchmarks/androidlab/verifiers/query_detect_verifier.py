"""Rule-based verifiers for Android-Lab query_detect tasks (45 tasks).

No LLM judge — uses string/numeric matching against ground truth.
Ground truth answers extracted from Android-Lab's judge classes.
"""

import re
from .base import ADBVerifier

# ─── Number parsing helpers ──────────────────────────────────────────────────

def extract_numbers(text: str) -> list:
    """Extract all numbers from text (handles commas, decimals)."""
    # Match numbers like 11,400.00 or 3.14 or 512
    matches = re.findall(r'[\d,]+\.?\d*', text.replace(",", ""))
    nums = []
    for m in matches:
        try:
            nums.append(float(m))
        except ValueError:
            pass
    return nums


def word_to_num(text: str) -> int:
    """Convert word numbers to digits."""
    words = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "no": 0, "none": 0,
    }
    for word, num in words.items():
        if word in text.lower():
            return num
    return -1


def normalize(text: str) -> str:
    """Normalize text for comparison."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def contains_number(text: str, target: float, tolerance: float = 0.01) -> bool:
    """Check if text contains a number matching target."""
    for n in extract_numbers(text):
        if abs(n - target) <= tolerance:
            return True
    return False


def contains_any(text: str, keywords: list) -> bool:
    """Check if text contains any of the keywords (case-insensitive)."""
    t = text.lower()
    return any(k.lower() in t for k in keywords)


# ─── Per-task verifiers ──────────────────────────────────────────────────────

class QueryVerifier(ADBVerifier):
    """Base for query_detect verifiers."""

    def check_answer(self, agent_answer: str) -> bool:
        raise NotImplementedError

    def is_successful(self, agent_answer: str = "") -> dict:
        ok = self.check_answer(agent_answer)
        return {"complete": ok, "1": ok}


# ── Bluecoins ────────────────────────────────────────────────────────────────

class Bluecoins1(QueryVerifier):
    """How much I spent on May 10, 2024? → 11,400.00 CNY"""
    task_id = "bluecoins_1"
    def check_answer(self, a):
        return contains_number(a, 11400, tolerance=1)


class Bluecoins2(QueryVerifier):
    """Reason behind 388.88 CNY on May 3? → Buying cake"""
    task_id = "bluecoins_2"
    def check_answer(self, a):
        return contains_any(a, ["cake", "buying cake"])


class Bluecoins3(QueryVerifier):
    """Total spent on May 6, 2024? → 69.51 CNY"""
    task_id = "bluecoins_3"
    def check_answer(self, a):
        return contains_number(a, 69.51, tolerance=0.1)


class Bluecoins4(QueryVerifier):
    """How many transactions on May 6? → Three transactions"""
    task_id = "bluecoins_4"
    def check_answer(self, a):
        return contains_number(a, 3) or contains_any(a, ["three"])


class Bluecoins5(QueryVerifier):
    """Total spent on taxis this week? → 60.12 CNY"""
    task_id = "bluecoins_5"
    def check_answer(self, a):
        return contains_number(a, 60.12, tolerance=0.1)


# ── Clock ────────────────────────────────────────────────────────────────────

class Clock10(QueryVerifier):
    """Earliest alarm which is open? → 7:30AM"""
    task_id = "clock_10"
    def check_answer(self, a):
        return contains_any(a, ["7:30", "7:30am", "7:30 am", "730"])


class Clock11(QueryVerifier):
    """Alarm set on 4PM everyday? → No"""
    task_id = "clock_11"
    def check_answer(self, a):
        a_lower = a.lower().strip()
        return a_lower.startswith("no") or "no," in a_lower or "no." in a_lower or a_lower == "no"


class Clock12(QueryVerifier):
    """Alarm at 4PM turn on vibrate? → Yes"""
    task_id = "clock_12"
    def check_answer(self, a):
        a_lower = a.lower().strip()
        # Accept "yes" anywhere, or descriptions like "vibrate turned on", "vibrate is on"
        return ("yes" in a_lower or "turned on" in a_lower or "vibrate on" in a_lower
                or "vibrate is on" in a_lower or "vibrate is enabled" in a_lower
                or "has vibrate" in a_lower)


class Clock13(QueryVerifier):
    """How many alarms turned on? → Two alarms"""
    task_id = "clock_13"
    def check_answer(self, a):
        return contains_number(a, 2) or contains_any(a, ["two"])


class Clock14(QueryVerifier):
    """Alarm at 9AM been turned on? → No"""
    task_id = "clock_14"
    def check_answer(self, a):
        a_lower = a.lower().strip()
        return a_lower.startswith("no") or "no," in a_lower or "no." in a_lower or a_lower == "no"


class Clock16(QueryVerifier):
    """Barcelona time difference with local? → 6 hours behind"""
    task_id = "clock_16"
    def check_answer(self, a):
        return contains_number(a, 6) and contains_any(a, ["behind", "hour", "hr"])


# ── Contacts ─────────────────────────────────────────────────────────────────

class Contacts12(QueryVerifier):
    """ABC's phone number? → 22331144 or (223) 311-44"""
    task_id = "contacts_12"
    def check_answer(self, a):
        return contains_any(a, ["22331144", "(223) 311-44", "223-311-44", "223311-44", "2233 1144"])


class Contacts13(QueryVerifier):
    """Li's working email? → 22334455@gmail.com"""
    task_id = "contacts_13"
    def check_answer(self, a):
        return contains_any(a, ["22334455@gmail.com", "22334455"])


class Contacts14(QueryVerifier):
    """ABC's birthday? → October 24, 1996"""
    task_id = "contacts_14"
    def check_answer(self, a):
        return (contains_any(a, ["october 24", "oct 24", "10/24", "10-24", "1996-10-24"])
                and contains_any(a, ["1996"]))


class Contacts15(QueryVerifier):
    """AAA's company? → Tsinghua university"""
    task_id = "contacts_15"
    def check_answer(self, a):
        return contains_any(a, ["tsinghua"])


# ── Settings ─────────────────────────────────────────────────────────────────

class Setting0(QueryVerifier):
    """Turn on airplane mode → check it's on"""
    task_id = "setting_0"
    def check_answer(self, a):
        # This is actually an operation verified by adb_query
        val = self.shell("settings get global airplane_mode_on").strip()
        return val == "1"


class Setting6(QueryVerifier):
    """How much storage does Apps use? → dynamic"""
    task_id = "setting_6"
    def check_answer(self, a):
        # Agent must provide a storage value (e.g., "1.5 GB", "500 MB")
        return contains_any(a, ["gb", "mb", "kb", "byte"]) and len(extract_numbers(a)) > 0


class Setting9(QueryVerifier):
    """Ring & notification volume to 0% → verify"""
    task_id = "setting_9"
    def check_answer(self, a):
        val = self.shell("settings list system | grep volume_ring_speaker").strip()
        return "=0" in val


class Setting10(QueryVerifier):
    """Set alarm volume to max → verify"""
    task_id = "setting_10"
    def check_answer(self, a):
        val = self.shell("settings list system | grep volume_alarm_speaker").strip()
        # Max is typically 7 or 15
        nums = extract_numbers(val)
        return len(nums) > 0 and nums[-1] >= 7


class Setting11(QueryVerifier):
    """Change TTS language to Chinese → verify"""
    task_id = "setting_11"
    def check_answer(self, a):
        return contains_any(a, ["chinese", "zh", "中文", "cmn", "zho"])


class Setting12(QueryVerifier):
    """Set time to 2024-5-1 → verify"""
    task_id = "setting_12"
    def check_answer(self, a):
        val = self.shell("date").strip()
        return "May" in val and "2024" in val and " 1 " in val


class Setting14(QueryVerifier):
    """What is my time zone? → dynamic"""
    task_id = "setting_14"
    def check_answer(self, a):
        val = self.shell("getprop persist.sys.timezone").strip()
        # Agent answer should contain the timezone
        return val.lower() in a.lower() or a.lower() in val.lower()


class Setting16(QueryVerifier):
    """Primary language? → English (United States)"""
    task_id = "setting_16"
    def check_answer(self, a):
        return contains_any(a, ["english", "en-us", "en_us", "united states"])


class Setting17(QueryVerifier):
    """Android Version? → dynamic"""
    task_id = "setting_17"
    def check_answer(self, a):
        val = self.shell("getprop ro.build.version.release").strip()
        return val in a


# ── Maps.me ──────────────────────────────────────────────────────────────────

class Map1(QueryVerifier):
    """Walking distance Stanford↔Oxford bus stops? → 73 km, 12 hr 58 min"""
    task_id = "map_1"
    def check_answer(self, a):
        # Must mention both distance and time
        has_dist = contains_number(a, 73, tolerance=5) or contains_any(a, ["73"])
        has_time = contains_any(a, ["12 hr", "12 hour", "12:58", "12 h", "58 min"])
        return has_dist and has_time


class Map2(QueryVerifier):
    """Driving distance 2700 Coast↔Route 51? → 7.0 km, 8 min"""
    task_id = "map_2"
    def check_answer(self, a):
        has_dist = contains_number(a, 7, tolerance=1)
        has_time = contains_number(a, 8, tolerance=2) and contains_any(a, ["min"])
        return has_dist and has_time


class Map3(QueryVerifier):
    """Riding time Stanford↔Oxford? → 4 hr 7 min"""
    task_id = "map_3"
    def check_answer(self, a):
        return contains_any(a, ["4 hr", "4 hour", "4:07", "4 h"]) and contains_any(a, ["7 min", "07"])


class Map4(QueryVerifier):
    """Public transportation 2700 Coast↔Route 51? → subway 824 and subway EB"""
    task_id = "map_4"
    def check_answer(self, a):
        return contains_any(a, ["824"]) and contains_any(a, ["eb", "EB"])


class Map5(QueryVerifier):
    """Less time riding or public transit 2700↔51? → public transportation"""
    task_id = "map_5"
    def check_answer(self, a):
        return contains_any(a, ["public transport", "transit", "bus", "subway"])


class Map6(QueryVerifier):
    """Less time riding or transit Stanford↔Oxford? → public transportation"""
    task_id = "map_6"
    def check_answer(self, a):
        return contains_any(a, ["public transport", "transit", "bus", "subway"])


class Map7(QueryVerifier):
    """Nearest restaurant? → Teleferic Barcelona"""
    task_id = "map_7"
    def check_answer(self, a):
        return contains_any(a, ["teleferic", "barcelona"])


class Map8(QueryVerifier):
    """Walk time to nearest restaurant? → about 3min"""
    task_id = "map_8"
    def check_answer(self, a):
        return contains_number(a, 3, tolerance=1) and contains_any(a, ["min", "walk"])


class Map9(QueryVerifier):
    """Nearest hotel? → The Clement Hotel"""
    task_id = "map_9"
    def check_answer(self, a):
        return contains_any(a, ["clement"])


class Map10(QueryVerifier):
    """Drive time to nearest IKEA? → 9min"""
    task_id = "map_10"
    def check_answer(self, a):
        return contains_number(a, 9, tolerance=2) and contains_any(a, ["min", "driv"])


# ── PiMusic ──────────────────────────────────────────────────────────────────

class PiMusic1(QueryVerifier):
    """Total songs? → 12 songs"""
    task_id = "pimusic_1"
    def check_answer(self, a):
        return contains_number(a, 12) or contains_any(a, ["twelve"])


class PiMusic2(QueryVerifier):
    """Pink Floyd songs? → 4 songs"""
    task_id = "pimusic_2"
    def check_answer(self, a):
        return contains_number(a, 4) or contains_any(a, ["four"])


class PiMusic3(QueryVerifier):
    """Album of Wish You Were Here? → Pulse Live"""
    task_id = "pimusic_3"
    def check_answer(self, a):
        return contains_any(a, ["pulse live", "pulse"])


class PiMusic4(QueryVerifier):
    """Longest Pink Floyd song duration? → 1 hour, 21 minutes and 3 seconds"""
    task_id = "pimusic_4"
    def check_answer(self, a):
        # The Wall is 81 min 3 sec = 1h 21m 3s
        return (contains_any(a, ["1 hour", "1:21", "81 min", "1h 21", "1 hr 21"])
                or (contains_number(a, 81) and contains_any(a, ["min"])))


class PiMusic5(QueryVerifier):
    """2nd and 4th songs sorted by title? → Dark Side Of The Moon, Future sounds"""
    task_id = "pimusic_5"
    def check_answer(self, a):
        return contains_any(a, ["dark side"]) and contains_any(a, ["future sound"])


class PiMusic6(QueryVerifier):
    """Total duration Eason Chan songs? → 11 minutes and 50 seconds"""
    task_id = "pimusic_6"
    def check_answer(self, a):
        return contains_number(a, 11) and contains_any(a, ["50 sec", "11:50", "11 min"])


# ── Cantook ──────────────────────────────────────────────────────────────────

class Cantook1(QueryVerifier):
    """Pride and Prejudice on bookshelf? → No"""
    task_id = "cantook_1"
    def check_answer(self, a):
        a_lower = a.lower().strip()
        return a_lower.startswith("no") or "no," in a_lower or "no." in a_lower or a_lower == "no"


class Cantook2(QueryVerifier):
    """Last book recently read? → The Scarlet Letter"""
    task_id = "cantook_2"
    def check_answer(self, a):
        return contains_any(a, ["scarlet letter"])


class Cantook3(QueryVerifier):
    """Author of 2nd book in recently added? → William Shakespeare"""
    task_id = "cantook_3"
    def check_answer(self, a):
        return contains_any(a, ["shakespeare", "william shakespeare"])


class Cantook4(QueryVerifier):
    """How many Charles Dickens books? → Two"""
    task_id = "cantook_4"
    def check_answer(self, a):
        return contains_number(a, 2) or contains_any(a, ["two"])


class Cantook5(QueryVerifier):
    """Progress reading Romeo and Juliet? → 37.8%"""
    task_id = "cantook_5"
    def check_answer(self, a):
        return contains_number(a, 37.8, tolerance=0.5)


# ─── Function map ────────────────────────────────────────────────────────────

FUNCTION_MAP = {
    "bluecoins_1": Bluecoins1, "bluecoins_2": Bluecoins2,
    "bluecoins_3": Bluecoins3, "bluecoins_4": Bluecoins4,
    "bluecoins_5": Bluecoins5,
    "clock_10": Clock10, "clock_11": Clock11, "clock_12": Clock12,
    "clock_13": Clock13, "clock_14": Clock14, "clock_16": Clock16,
    "contacts_12": Contacts12, "contacts_13": Contacts13,
    "contacts_14": Contacts14, "contacts_15": Contacts15,
    "setting_0": Setting0, "setting_6": Setting6, "setting_9": Setting9,
    "setting_10": Setting10, "setting_11": Setting11, "setting_12": Setting12,
    "setting_14": Setting14, "setting_16": Setting16, "setting_17": Setting17,
    "map_1": Map1, "map_2": Map2, "map_3": Map3, "map_4": Map4,
    "map_5": Map5, "map_6": Map6, "map_7": Map7, "map_8": Map8,
    "map_9": Map9, "map_10": Map10,
    "pimusic_1": PiMusic1, "pimusic_2": PiMusic2, "pimusic_3": PiMusic3,
    "pimusic_4": PiMusic4, "pimusic_5": PiMusic5, "pimusic_6": PiMusic6,
    "cantook_1": Cantook1, "cantook_2": Cantook2, "cantook_3": Cantook3,
    "cantook_4": Cantook4, "cantook_5": Cantook5,
}
