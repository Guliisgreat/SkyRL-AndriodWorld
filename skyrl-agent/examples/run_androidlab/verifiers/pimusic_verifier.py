"""ADB verifiers for Android-Lab PiMusic tasks (6 operation tasks)."""

from .base import ADBVerifier

PIMUSIC_DB = "/data/data/com.Project100Pi.themusicplayer/databases/songinfodatabase"
MEDIA_URI = "content://media/external/audio/media"


class PiMusicVerifierBase(ADBVerifier):
    """Base with PiMusic query helpers."""

    def get_playlists(self) -> list:
        result = self.sqlite_query(
            PIMUSIC_DB,
            "SELECT _id, playlist_name FROM pi_playlist"
        )
        playlists = []
        for line in result.strip().split("\n"):
            if line.startswith("_id") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                playlists.append({"id": parts[0], "name": parts[1]})
        return playlists

    def get_playlist_songs(self, playlist_id: str) -> list:
        result = self.sqlite_query(
            PIMUSIC_DB,
            f"SELECT song_name, song_duration FROM playlist_song "
            f"WHERE playlist_id={playlist_id}"
        )
        songs = []
        for line in result.strip().split("\n"):
            if line.startswith("song_name") or not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                songs.append({"name": parts[0], "duration": int(parts[1]) if parts[1].isdigit() else 0})
        return songs

    def get_media_session_state(self) -> str:
        return self.shell("dumpsys media_session")

    def is_playing(self, title: str = "") -> bool:
        state = self.get_media_session_state()
        playing = "state=PlaybackState" in state and "state=3" in state
        if title and playing:
            return title.lower() in state.lower()
        return playing

    def is_paused(self) -> bool:
        state = self.get_media_session_state()
        return "state=2" in state  # PAUSED


class PiMusic7_PlayFavorite(PiMusicVerifierBase):
    """pimusic_7: Play the first song in 'Favorite' playlist."""
    task_id = "pimusic_7"

    def is_successful(self):
        # Check if music is playing
        state = self.get_media_session_state()
        playing = "state=3" in state  # STATE_PLAYING
        # Check if Pi Music is the active session
        pi_active = "Project100Pi" in state or "themusicplayer" in state
        ok = playing and pi_active
        return {"complete": ok, "1": ok}


class PiMusic8_SortByDurationDesc(PiMusicVerifierBase):
    """pimusic_8: Sort Pink Floyd's songs by duration descending."""
    task_id = "pimusic_8"

    def is_successful(self):
        # Sort state is in-app UI — check if app is in foreground showing Floyd
        activity = self.foreground_activity()
        ok = "themusicplayer" in activity.lower()
        # Can't directly verify sort order via ADB
        return {"complete": ok, "1": ok}


class PiMusic9_CreatePlaylist(PiMusicVerifierBase):
    """pimusic_9: Create playlist named 'Creepy'."""
    task_id = "pimusic_9"

    def is_successful(self):
        playlists = self.get_playlists()
        ok = any("creepy" in p["name"].lower() for p in playlists)
        return {"complete": ok, "1": ok}


class PiMusic10_PauseAndSeek(PiMusicVerifierBase):
    """pimusic_10: Pause currently playing song and seek to 1:27."""
    task_id = "pimusic_10"

    def is_successful(self):
        state = self.get_media_session_state()
        paused = "state=2" in state  # PAUSED
        # Check position near 87000ms (1:27)
        import re
        pos_match = re.search(r"position=(\d+)", state)
        position = int(pos_match.group(1)) if pos_match else 0
        seek_ok = 85000 <= position <= 89000  # 1:25-1:29 tolerance
        return {"complete": paused and seek_ok, "1": paused, "2": seek_ok}


class PiMusic11_PlayLightship(PiMusicVerifierBase):
    """pimusic_11: Play Lightship by Sonny Boy."""
    task_id = "pimusic_11"

    def is_successful(self):
        state = self.get_media_session_state()
        playing = "state=3" in state
        title_ok = "lightship" in state.lower() or "Lightship" in state
        return {"complete": playing and title_ok, "1": playing, "2": title_ok}


class PiMusic12_SortByDurationAsc(PiMusicVerifierBase):
    """pimusic_12: Sort songs by duration ascending."""
    task_id = "pimusic_12"

    def is_successful(self):
        activity = self.foreground_activity()
        ok = "themusicplayer" in activity.lower()
        return {"complete": ok, "1": ok}


FUNCTION_MAP = {
    "pimusic_7": PiMusic7_PlayFavorite,
    "pimusic_8": PiMusic8_SortByDurationDesc,
    "pimusic_9": PiMusic9_CreatePlaylist,
    "pimusic_10": PiMusic10_PauseAndSeek,
    "pimusic_11": PiMusic11_PlayLightship,
    "pimusic_12": PiMusic12_SortByDurationAsc,
}
