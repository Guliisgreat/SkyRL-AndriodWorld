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

# No unverifiable tasks — all 93 operation tasks have verifiers
UNVERIFIABLE_TASKS = set()


def get_verifier(task_id: str):
    """Get verifier class for a task_id, or None if not available."""
    return VERIFIER_MAP.get(task_id)
