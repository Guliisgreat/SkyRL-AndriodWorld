"""Registry mapping task_id to verifier class."""

from .settings_verifier import FUNCTION_MAP as SETTINGS_MAP
from .contacts_verifier import FUNCTION_MAP as CONTACTS_MAP
from .clock_verifier import FUNCTION_MAP as CLOCK_MAP
from .bluecoins_verifier import FUNCTION_MAP as BLUECOINS_MAP
from .cantook_verifier import FUNCTION_MAP as CANTOOK_MAP

# Aggregate all operation task verifiers
VERIFIER_MAP = {}
VERIFIER_MAP.update(SETTINGS_MAP)
VERIFIER_MAP.update(CONTACTS_MAP)
VERIFIER_MAP.update(CLOCK_MAP)
VERIFIER_MAP.update(BLUECOINS_MAP)
VERIFIER_MAP.update(CANTOOK_MAP)

# Tasks without ADB verifiers (need UI fallback):
# calendar_1 through calendar_14 (Realm DB, no SQLite)
# map_11 through map_15 (Maps.me navigation state)
# pimusic_7 through pimusic_12 (playback/sort state)
# zoom_1 through zoom_5 (meeting UI state)
UNVERIFIABLE_TASKS = {
    "calendar_1", "calendar_2", "calendar_3", "calendar_4", "calendar_5",
    "calendar_6", "calendar_7", "calendar_8", "calendar_9", "calendar_10",
    "calendar_11", "calendar_12", "calendar_13", "calendar_14",
    "map_11", "map_12", "map_13", "map_14", "map_15",
    "pimusic_7", "pimusic_8", "pimusic_9", "pimusic_10", "pimusic_11", "pimusic_12",
    "zoom_1", "zoom_2", "zoom_3", "zoom_4", "zoom_5",
}


def get_verifier(task_id: str):
    """Get verifier class for a task_id, or None if not available."""
    return VERIFIER_MAP.get(task_id)
