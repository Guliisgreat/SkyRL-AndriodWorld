#!/usr/bin/env python3
"""
Compatibility server that wraps Android-Lab's emulator with our skyrl API.

Provides /health, /reset, /step endpoints compatible with:
- android_env.py (our Claude CLI tool)
- pool_broker.py / androidlab_broker.py (our container broker)

Runs on port 5000 (configurable via SERVER_PORT env var).
Internally uses the same emulator/ADB setup as Android-Lab's adb_client.py.
"""

import json
import os
import subprocess
import signal
import sys
import time

from flask import Flask, request, jsonify

AVD_NAME = os.environ.get("AVD_NAME", "Pixel_7_Pro_API_33")
ADB_PATH = "/root/.android/platform-tools/adb"
EMULATOR_PATH = "/root/.android/emulator/emulator"
SERVER_PORT = int(os.environ.get("SERVER_PORT", 5000))
# ADB port for this emulator — each container gets its own port
# so ADB commands target the right device even in host-network mode.
ADB_PORT = int(os.environ.get("ADB_PORT", 5037))
EMULATOR_PORT = int(os.environ.get("EMULATOR_PORT", 5554))

app = Flask(__name__)


# ─── Emulator management ────────────────────────────────────────────────────

class EmulatorManager:
    def __init__(self):
        self.process = None
        self.device = None
        self.ready = False
        self._log_file = None

    def execute_adb(self, command):
        """Execute an ADB command, return (stdout, returncode)."""
        if command.startswith("adb"):
            # Target our specific device and ADB port to avoid conflicts
            # in host-network mode where many emulators share the ADB server
            rest = command[3:]
            # If command already specifies -s, don't override
            if " -s " not in rest and self.device:
                command = f"{ADB_PATH} -P {ADB_PORT} -s {self.device}" + rest
            else:
                command = f"{ADB_PATH} -P {ADB_PORT}" + rest
        env = os.environ.copy()
        env["ANDROID_ADB_SERVER_PORT"] = str(ADB_PORT)
        try:
            result = subprocess.run(
                command, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=120, env=env,
            )
            return result.stdout.strip(), result.returncode
        except subprocess.TimeoutExpired:
            return "TIMEOUT", 1
        except Exception as e:
            return f"ERROR: {e}", 1

    def start(self):
        """Start the emulator from snapshot (no-snapshot-save)."""
        if self.process and self.process.poll() is None:
            print("Emulator already running, skipping start")
            return True

        # Kill any existing ADB server on our port
        subprocess.run(
            f"{ADB_PATH} -P {ADB_PORT} kill-server",
            shell=True, capture_output=True,
        )
        time.sleep(1)
        # Start dedicated ADB server on our port
        subprocess.Popen(
            f"{ADB_PATH} -P {ADB_PORT} start-server",
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "ANDROID_ADB_SERVER_PORT": str(ADB_PORT)},
        )
        time.sleep(2)

        print(f"Starting emulator: {AVD_NAME} (port={EMULATOR_PORT}, adb_port={ADB_PORT})")
        os.makedirs("/logs", exist_ok=True)
        self._log_file = open("/logs/emulator_output.txt", "a")

        self.process = subprocess.Popen(
            [EMULATOR_PATH, "-avd", AVD_NAME,
             "-no-snapshot-save", "-no-window", "-no-audio",
             "-gpu", "swiftshader_indirect",
             "-port", str(EMULATOR_PORT),
             "-read-only"],
            stdout=self._log_file,
            stderr=self._log_file,
            env={**os.environ, "ANDROID_ADB_SERVER_PORT": str(ADB_PORT)},
        )

        # Wait for boot — target our specific emulator device
        self.device = f"emulator-{EMULATOR_PORT}"
        print(f"Waiting for emulator boot (device={self.device})...")
        for _ in range(180):  # up to 3 minutes
            time.sleep(1)
            out, rc = self.execute_adb(
                f"adb -s {self.device} shell getprop init.svc.bootanim"
            )
            if rc == 0 and out.strip() == "stopped":
                print("Emulator boot complete")
                self.ready = True
                time.sleep(3)
                return True

        print("ERROR: Emulator failed to boot in 180s")
        return False

    def stop(self):
        """Stop the emulator."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
        if self._log_file:
            self._log_file.close()
            self._log_file = None
        self.ready = False
        self.device = None

    def restart(self):
        """Restart emulator (for reset / snapshot restore)."""
        print("Restarting emulator for clean state...")
        self.stop()
        time.sleep(2)
        return self.start()

    def _get_device(self):
        """Get the emulator device name."""
        out, rc = self.execute_adb("adb devices")
        if rc != 0:
            return None
        for line in out.split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                return parts[0]
        return None

    def is_healthy(self):
        """Quick health check."""
        if not self.ready or not self.process:
            return False
        if self.process.poll() is not None:
            self.ready = False
            return False
        out, rc = self.execute_adb("adb shell echo ok")
        return rc == 0 and "ok" in out


emu = EmulatorManager()


# ─── API endpoints (skyrl-compatible) ────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok" if emu.is_healthy() else "unhealthy",
        "ready": emu.ready,
        "device": emu.device,
    })


@app.route("/reset", methods=["POST"])
def reset():
    """Reset the emulator by restarting from snapshot.

    Android-Lab uses -no-snapshot-save, so restarting restores the
    original snapshot state. This is equivalent to our snapshot restore.
    """
    ok = emu.restart()
    if ok:
        return jsonify({"status": "ok", "message": "Emulator restarted from snapshot"})
    else:
        return jsonify({"status": "error", "message": "Restart failed"}), 500


@app.route("/step", methods=["POST"])
def step():
    """Execute an action — compatible with android_env.py.

    Expects: {"action": {"action_type": "adb", "command": "adb shell ..."}}
    Returns: {"observation": "...", "reward": 0.0, ...}
    """
    data = request.json or {}
    action = data.get("action", {})
    action_type = action.get("action_type", "")

    if action_type == "adb":
        command = action.get("command", "")
        if not command:
            return jsonify({"error": "No command provided"}), 400

        output, rc = emu.execute_adb(command)
        return jsonify({
            "observation": output,
            "command_output": output,
            "reward": 0.0,
            "terminated": False,
            "step_count": 0,
        })

    elif action_type == "status":
        # Force evaluation — not supported in Android-Lab (no task framework)
        # Just return 0.0 reward
        return jsonify({
            "observation": "Android-Lab: no built-in task evaluation",
            "reward": 0.0,
            "terminated": True,
        })

    elif action_type == "answer":
        # Agent providing an answer — store it but can't evaluate
        return jsonify({
            "observation": "Answer recorded",
            "reward": 0.0,
            "terminated": False,
        })

    else:
        return jsonify({"error": f"Unknown action_type: {action_type}"}), 400


@app.route("/step_adb", methods=["POST"])
def step_adb():
    """Execute ADB command — compatible with android_env.py's /step_adb.

    Expects: {"command": "adb shell ...", "thought": "...", "count_step": true}
    Returns: {"command_output": "...", "reward": 0.0, ...}
    """
    data = request.json or {}
    command = data.get("command", "")
    if not command:
        return jsonify({"error": "No command provided"}), 400

    output, rc = emu.execute_adb(command)
    return jsonify({
        "command_output": output,
        "reward": 0.0,
        "terminated": False,
        "truncated": False,
        "step_count": 0,
    })


# Also keep Android-Lab's original /execute endpoint for compatibility
@app.route("/execute", methods=["POST"])
def execute():
    command = request.json.get("command", "")
    if not command:
        return jsonify({"error": "No command provided"}), 400
    output, rc = emu.execute_adb(command)
    return jsonify({"result": output})


@app.route("/start", methods=["POST"])
def start():
    """Start emulator (Android-Lab compat)."""
    ok = emu.start()
    return jsonify({"result": "started" if ok else "failed"})


@app.route("/stop", methods=["POST"])
def stop():
    """Stop emulator (Android-Lab compat)."""
    emu.stop()
    return jsonify({"result": "stopped"})


# ─── Main ────────────────────────────────────────────────────────────────────

def signal_handler(sig, frame):
    print("Shutting down...")
    emu.stop()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Auto-start emulator
    print(f"Auto-starting emulator {AVD_NAME}...")
    emu.start()

    print(f"Starting skyrl-compat server on port {SERVER_PORT}")
    app.run(host="0.0.0.0", port=SERVER_PORT)
