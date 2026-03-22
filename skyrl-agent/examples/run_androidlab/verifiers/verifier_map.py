"""Registry mapping task_id to verifier class for all 93 operation tasks."""

from .settings_verifier import FUNCTION_MAP as SETTINGS_MAP
from .contacts_verifier import FUNCTION_MAP as CONTACTS_MAP
from .clock_verifier import FUNCTION_MAP as CLOCK_MAP
from .bluecoins_verifier import FUNCTION_MAP as BLUECOINS_MAP
from .cantook_verifier import FUNCTION_MAP as CANTOOK_MAP
from .pimusic_verifier import FUNCTION_MAP as PIMUSIC_MAP
from .mapme_verifier import FUNCTION_MAP as MAPME_MAP
from .calendar_verifier import FUNCTION_MAP as CALENDAR_MAP
from .zoom_verifier import FUNCTION_MAP as ZOOM_MAP

# Aggregate all operation task verifiers
VERIFIER_MAP = {}
VERIFIER_MAP.update(SETTINGS_MAP)     # 14 tasks
VERIFIER_MAP.update(CONTACTS_MAP)     # 11 tasks
VERIFIER_MAP.update(CLOCK_MAP)        # 21 tasks
VERIFIER_MAP.update(BLUECOINS_MAP)    # 10 tasks
VERIFIER_MAP.update(CANTOOK_MAP)      #  7 tasks
VERIFIER_MAP.update(PIMUSIC_MAP)      #  6 tasks
VERIFIER_MAP.update(MAPME_MAP)        #  5 tasks
VERIFIER_MAP.update(CALENDAR_MAP)     # 14 tasks
VERIFIER_MAP.update(ZOOM_MAP)         #  5 tasks
                                      # Total: 93

# Tasks excluded from terminal evaluation (GUI-only, no terminal path)
EXCLUDED_TASKS = {
    # Calendar (14) — Realm DB, no content provider, no CLI API
    "calendar_1", "calendar_2", "calendar_3", "calendar_4", "calendar_5",
    "calendar_6", "calendar_7", "calendar_8", "calendar_9", "calendar_10",
    "calendar_11", "calendar_12", "calendar_13", "calendar_14",
    # Maps.me operation (5) — location search + navigation require GUI
    "map_11", "map_12", "map_13", "map_14", "map_15",
    # Zoom (5) — no local DB/prefs, all UI form filling
    "zoom_1", "zoom_2", "zoom_3", "zoom_4", "zoom_5",
    # PiMusic sort (2) — sort order is UI-only state
    "pimusic_8", "pimusic_12",
}

# Kept for backward compat
UNVERIFIABLE_TASKS = EXCLUDED_TASKS


def get_verifier(task_id: str):
    """Get verifier class for a task_id, or None if not available."""
    return VERIFIER_MAP.get(task_id)
