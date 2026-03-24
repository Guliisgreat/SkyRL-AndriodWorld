"""Base class for ADB-based task verification."""

import json
import re
import urllib.request
from typing import Callable, Dict, Optional


class ADBVerifier:
    """Base class for verifying Android-Lab task completion via ADB.

    Each subclass implements is_successful() which returns a dict:
        {"complete": bool, "1": bool, "2": bool, ...}

    This mirrors Android-Lab's SingleTask.judge() return format.
    """

    task_id: str = ""

    def __init__(self, container_url: str):
        self.container_url = container_url

    def is_successful(self) -> Dict:
        """Check if the task was completed successfully.

        Returns dict with "complete" (bool) and optional sub-goal keys.
        """
        raise NotImplementedError

    def adb(self, command: str) -> str:
        """Execute an ADB command via the container's HTTP API."""
        if not command.startswith("adb"):
            command = f"adb shell {command}"
        data = json.dumps({
            "command": command,
            "thought": "verification",
        }).encode()
        req = urllib.request.Request(
            f"{self.container_url}/step_adb",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                return result.get("command_output", "")
        except Exception as e:
            return f"ERROR: {e}"

    def shell(self, command: str) -> str:
        """Shorthand for adb shell commands."""
        return self.adb(f"adb shell {command}")

    def settings_get(self, namespace: str, key: str) -> str:
        """Read an Android setting. Returns the value string."""
        return self.shell(f"settings get {namespace} {key}").strip()

    def sqlite_query(self, db_path: str, sql: str) -> str:
        """Query a SQLite database. Returns pipe-separated output."""
        # Escape single quotes in SQL by doubling them
        escaped_sql = sql.replace("'", "'\\''")
        return self.shell(
            f"'sqlite3 -header {db_path} \"{escaped_sql}\"'"
        )

    def content_query(self, uri: str, projection: str = "",
                      where: str = "") -> str:
        """Query an Android content provider."""
        cmd = f"content query --uri {uri}"
        if projection:
            cmd += f" --projection {projection}"
        if where:
            cmd += f' --where "{where}"'
        return self.shell(cmd)

    def package_installed(self, package: str) -> bool:
        """Check if a package is installed."""
        result = self.shell(f"pm list packages {package}")
        return f"package:{package}" in result

    def foreground_activity(self) -> str:
        """Get the current foreground activity."""
        # mFocusedApp is more reliable than mResumedActivity
        result = self.shell(
            "dumpsys activity activities | grep mFocusedApp"
        )
        if not result.strip():
            result = self.shell(
                "dumpsys window | grep mCurrentFocus"
            )
        return result.strip()

    def parse_content_rows(self, output: str) -> list:
        """Parse content query output into list of dicts.

        Input format: "Row: 0 key1=val1, key2=val2\nRow: 1 ..."
        """
        rows = []
        for line in output.strip().split("\n"):
            if not line.startswith("Row:"):
                continue
            # Remove "Row: N " prefix
            data_part = re.sub(r"^Row: \d+ ", "", line)
            row = {}
            for pair in data_part.split(", "):
                if "=" in pair:
                    key, val = pair.split("=", 1)
                    row[key.strip()] = val.strip()
            rows.append(row)
        return rows
