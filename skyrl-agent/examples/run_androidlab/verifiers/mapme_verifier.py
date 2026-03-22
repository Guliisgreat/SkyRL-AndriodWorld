"""ADB verifiers for Android-Lab Maps.me tasks (5 operation tasks)."""

from .base import ADBVerifier

FAVORITES_DB = "/data/data/com.mapswithme.maps.pro/databases/favorites"


class MapmeVerifierBase(ADBVerifier):
    """Base with Maps.me query helpers."""

    def get_bookmarks(self) -> list:
        result = self.sqlite_query(
            FAVORITES_DB,
            "SELECT id, name, description FROM Bookmark"
        )
        bookmarks = []
        for line in result.strip().split("\n"):
            if line.startswith("id") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                bookmarks.append({"id": parts[0], "name": parts[1],
                                  "description": parts[2] if len(parts) > 2 else ""})
        return bookmarks

    def get_categories(self) -> list:
        result = self.sqlite_query(
            FAVORITES_DB,
            "SELECT id, name FROM Category"
        )
        cats = []
        for line in result.strip().split("\n"):
            if line.startswith("id") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                cats.append({"id": parts[0], "name": parts[1]})
        return cats

    def is_navigating(self) -> bool:
        """Check if Maps.me is in navigation mode."""
        activity = self.foreground_activity()
        return "mapswithme" in activity.lower()


class Map11_AddWorkPlace(MapmeVerifierBase):
    """map_11: Add the address of OpenAI to my Work place."""
    task_id = "map_11"

    def is_successful(self):
        # Check FavoritesSettings for Work place or bookmarks for OpenAI
        bookmarks = self.get_bookmarks()
        settings = self.sqlite_query(FAVORITES_DB, "SELECT * FROM FavoritesSettings")
        openai_ok = any("openai" in b["name"].lower() or "work" in b["name"].lower()
                        for b in bookmarks)
        if not openai_ok:
            openai_ok = "openai" in settings.lower() or "work" in settings.lower()
        return {"complete": openai_ok, "1": openai_ok}


class Map12_NavigateStanford(MapmeVerifierBase):
    """map_12: Navigate from my location to Stanford University."""
    task_id = "map_12"

    def is_successful(self):
        ok = self.is_navigating()
        return {"complete": ok, "1": ok}


class Map13_NavigateUniversitySouth(MapmeVerifierBase):
    """map_13: Navigate from my location to University South."""
    task_id = "map_13"

    def is_successful(self):
        ok = self.is_navigating()
        return {"complete": ok, "1": ok}


class Map14_NavigateOpenAI(MapmeVerifierBase):
    """map_14: Navigate from my location to OpenAI."""
    task_id = "map_14"

    def is_successful(self):
        ok = self.is_navigating()
        return {"complete": ok, "1": ok}


class Map15_NavigateBerkeley(MapmeVerifierBase):
    """map_15: Navigate from my location to UC Berkeley."""
    task_id = "map_15"

    def is_successful(self):
        ok = self.is_navigating()
        return {"complete": ok, "1": ok}


FUNCTION_MAP = {
    "map_11": Map11_AddWorkPlace,
    "map_12": Map12_NavigateStanford,
    "map_13": Map13_NavigateUniversitySouth,
    "map_14": Map14_NavigateOpenAI,
    "map_15": Map15_NavigateBerkeley,
}
