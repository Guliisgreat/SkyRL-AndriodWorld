"""LLM judge for Android-Lab query_detect tasks (45 tasks).

Ground truth answers extracted from Android-Lab judge classes.
Uses GPT-4o as LLM judge (same as Android-Lab's evaluation).
"""

import time
from .base import ADBVerifier

# Ground truth answers extracted from Android-Lab's judge code
GROUND_TRUTH = {
    # Bluecoins (5 query tasks)
    "bluecoins_1": "11,400.00 CNY",
    "bluecoins_2": "Buying cake",
    "bluecoins_3": "69.51 CNY",
    "bluecoins_4": "Three transactions",
    "bluecoins_5": "60.12 CNY",
    # Clock (6 query tasks)
    "clock_10": "7:30AM",
    "clock_11": "No",
    "clock_12": "Yes",
    "clock_13": "Two alarms",
    "clock_14": "No",
    "clock_16": "6 hours behind",
    # Contacts (4 query tasks)
    "contacts_12": "22331144 or (223) 311-44",
    "contacts_13": "22334455@gmail.com",
    "contacts_14": "October 24, 1996",
    "contacts_15": "Tsinghua university",
    # Settings (8 query tasks)
    "setting_0": None,   # dynamic: adb shell settings get global airplane_mode_on
    "setting_6": None,   # dynamic: storage query
    "setting_9": None,   # dynamic: volume query
    "setting_10": None,  # dynamic: alarm volume
    "setting_11": None,  # dynamic: TTS language
    "setting_12": None,  # dynamic: date set
    "setting_14": None,  # dynamic: timezone
    "setting_16": "English (United States)",
    "setting_17": None,  # dynamic: Android version
    # Map.me (10 query tasks)
    "map_1": "73 km, 12 hr 58 min",
    "map_2": "7.0 km, 8 min",
    "map_3": "4 hr 7 min",
    "map_4": "subway 824 and subway EB",
    "map_5": "public transportation",
    "map_6": "public transportation",
    "map_7": "Teleferic Barcelona",
    "map_8": "Teleferic Barcelona, about 3min",
    "map_9": "The Clement Hotel - All Inclusive",
    "map_10": "9min",
    # PiMusic (6 query tasks)
    "pimusic_1": "12 songs",
    "pimusic_2": "4 songs",
    "pimusic_3": "Pulse Live",
    "pimusic_4": "1 hour, 21 minutes and 3 seconds",
    "pimusic_5": "The second song is 'Dark Side Of The Moon' and the fourth song is 'Future sounds'",
    "pimusic_6": "11 minutes and 50 seconds",
    # Cantook (5 query tasks)
    "cantook_1": "No",
    "cantook_2": "The Scarlet Letter",
    "cantook_3": "William Shakespeare",
    "cantook_4": "Two",
    "cantook_5": "37.8%",
}


def get_dynamic_answer(task_id: str, adb_func) -> str:
    """Get ground truth for tasks that depend on device state."""
    if task_id == "setting_0":
        val = adb_func("adb shell settings get global airplane_mode_on").strip()
        return "on" if val == "1" else "off"
    elif task_id == "setting_9":
        return adb_func("adb shell settings list system | grep volume_ring_speaker").strip()
    elif task_id == "setting_10":
        return adb_func("adb shell settings list system | grep volume_alarm_speaker").strip()
    elif task_id == "setting_14":
        return adb_func("adb shell getprop persist.sys.timezone").strip()
    elif task_id == "setting_17":
        return adb_func("adb shell getprop ro.build.version.release").strip()
    return ""


def judge_query_detect(task_id: str, question: str, agent_answer: str,
                       adb_func=None, judge_model: str = "gpt-4o") -> dict:
    """Evaluate a query_detect task using LLM judge.

    Returns {"complete": bool, "1": bool}
    """
    if not agent_answer or not agent_answer.strip():
        return {"complete": False, "1": False}

    ground_truth = GROUND_TRUTH.get(task_id)
    if ground_truth is None and adb_func:
        ground_truth = get_dynamic_answer(task_id, adb_func)

    if not ground_truth:
        # Can't evaluate without ground truth
        return {"complete": False, "1": False, "details": "no_ground_truth"}

    # Use LLM judge
    try:
        from openai import OpenAI
        client = OpenAI()

        prompt = (
            f"You need to judge the model answer is True or False based on "
            f"Standard Answer we provided. You should whether answer [True] or "
            f"[False].\n\n"
            f"Question: {question}\n\n"
            f"Model Answer: {agent_answer}\n\n"
            f"Standard Answer: {ground_truth}"
        )

        for attempt in range(3):
            try:
                r = client.chat.completions.create(
                    model=judge_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=64,
                    temperature=0.001,
                )
                text = r.choices[0].message.content or ""
                if "True" in text:
                    return {"complete": True, "1": True}
                elif "False" in text:
                    return {"complete": False, "1": False}
            except Exception:
                time.sleep(2)
    except ImportError:
        pass

    return {"complete": False, "1": False}
