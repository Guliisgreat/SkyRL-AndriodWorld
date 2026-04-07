"""ADB verifiers for Android-Lab Cantook/Aldiko tasks (7 operation tasks)."""

from .base import ADBVerifier

CANTOOK_DB = "/data/data/com.aldiko.android/databases/cantook.db"


class CantookVerifierBase(ADBVerifier):
    """Base with Cantook DB query helpers."""

    def get_publications(self) -> list:
        result = self.sqlite_query(
            CANTOOK_DB,
            "SELECT id, title, finished, progression FROM publications"
        )
        pubs = []
        for line in result.strip().split("\n"):
            if line.startswith("id") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                pubs.append({
                    "id": parts[0],
                    "title": parts[1],
                    "finished": int(parts[2]) if parts[2].isdigit() else 0,
                    "progression": float(parts[3]) if parts[3] else 0.0,
                })
        return pubs

    def get_collections(self) -> list:
        result = self.sqlite_query(CANTOOK_DB, "SELECT id, name FROM collections")
        colls = []
        for line in result.strip().split("\n"):
            if line.startswith("id") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                colls.append({"id": parts[0], "name": parts[1]})
        return colls

    def find_publication(self, title_fragment: str) -> dict:
        for p in self.get_publications():
            if title_fragment.lower() in p["title"].lower():
                return p
        return {}


class Cantook6_ImportAlice(CantookVerifierBase):
    """cantook_6: Import Alice's Adventures in Wonderland from /Download/Ebooks/."""
    task_id = "cantook_6"

    def is_successful(self):
        pub = self.find_publication("Alice")
        ok = bool(pub)
        return {"complete": ok, "1": ok}


class Cantook7_DeleteDonQuixote(CantookVerifierBase):
    """cantook_7: Delete Don Quixote from my books."""
    task_id = "cantook_7"

    def is_successful(self):
        pub = self.find_publication("Don Quixote")
        ok = not bool(pub)
        return {"complete": ok, "1": ok}


class Cantook8_MarkHamletRead(CantookVerifierBase):
    """cantook_8: Mark Hamlet as read."""
    task_id = "cantook_8"

    def is_successful(self):
        pub = self.find_publication("Hamlet")
        ok = pub.get("finished", 0) == 1 if pub else False
        return {"complete": ok, "1": ok}


class Cantook9_MarkSecondUnread(CantookVerifierBase):
    """cantook_9: Mark the second book I recently read as unread."""
    task_id = "cantook_9"

    def is_successful(self):
        # Get books sorted by last_read descending
        result = self.sqlite_query(
            CANTOOK_DB,
            "SELECT id, title, finished FROM publications "
            "WHERE last_read IS NOT NULL ORDER BY last_read DESC"
        )
        books = []
        for line in result.strip().split("\n"):
            if line.startswith("id") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                books.append({
                    "id": parts[0], "title": parts[1],
                    "finished": int(parts[2]) if parts[2].isdigit() else 0,
                })
        if len(books) >= 2:
            ok = books[1]["finished"] == 0
        else:
            ok = False
        return {"complete": ok, "1": ok}


class Cantook10_OpenRomeoJuliet(CantookVerifierBase):
    """cantook_10: Open Romeo and Juliet."""
    task_id = "cantook_10"

    def is_successful(self):
        activity = self.foreground_activity()
        ok = "aldiko" in activity.lower() or "reader" in activity.lower()
        return {"complete": ok, "1": ok}


class Cantook11_OpenTragedies(CantookVerifierBase):
    """cantook_11: Open the category named 'Tragedies'."""
    task_id = "cantook_11"

    def is_successful(self):
        activity = self.foreground_activity()
        ok = "aldiko" in activity.lower()
        return {"complete": ok, "1": ok}


class Cantook12_CreateFavorite(CantookVerifierBase):
    """cantook_12: Create a new collection called 'Favorite'."""
    task_id = "cantook_12"

    def is_successful(self):
        colls = self.get_collections()
        ok = any("favorite" in c["name"].lower() for c in colls)
        return {"complete": ok, "1": ok}


FUNCTION_MAP = {
    "cantook_6": Cantook6_ImportAlice,
    "cantook_7": Cantook7_DeleteDonQuixote,
    "cantook_8": Cantook8_MarkHamletRead,
    "cantook_9": Cantook9_MarkSecondUnread,
    "cantook_10": Cantook10_OpenRomeoJuliet,
    "cantook_11": Cantook11_OpenTragedies,
    "cantook_12": Cantook12_CreateFavorite,
}
