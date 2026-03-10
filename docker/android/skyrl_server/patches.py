"""
Runtime monkey-patches for android_world / android_env.

Applied once at server startup via apply_all(). Each patch is idempotent.
"""

import os
import time
import logging

import numpy as np

logger = logging.getLogger(__name__)


def patch_adb_port():
    """Override ADB server port for per-container host-network mode.

    android_world hardcodes ADB port 5037. In our multi-container setup,
    each container uses a unique port (ADB_SERVER_PORT env var).
    """
    from android_world.env import android_world_controller
    from android_env.components import config_classes

    if getattr(android_world_controller, '_adb_port_patched', False):
        return

    _write_default_task_proto = android_world_controller._write_default_task_proto

    def _patched_get_controller(
        console_port=5554,
        adb_path=android_world_controller.DEFAULT_ADB_PATH,
        grpc_port=8554,
    ):
        adb_server_port = int(os.environ.get("ADB_SERVER_PORT", "5037"))
        config = config_classes.AndroidEnvConfig(
            task=config_classes.FilesystemTaskConfig(
                path=_write_default_task_proto()
            ),
            simulator=config_classes.EmulatorConfig(
                emulator_launcher=config_classes.EmulatorLauncherConfig(
                    emulator_console_port=console_port,
                    adb_port=console_port + 1,
                    grpc_port=grpc_port,
                ),
                adb_controller=config_classes.AdbControllerConfig(
                    adb_path=adb_path,
                    adb_server_port=adb_server_port,
                ),
            ),
        )
        return android_world_controller.AndroidWorldController(
            loader.load(config)
        )

    from android_env import loader
    android_world_controller.get_controller = _patched_get_controller
    android_world_controller._adb_port_patched = True
    logger.info(
        "Patched get_controller for ADB_SERVER_PORT=%s",
        os.environ.get("ADB_SERVER_PORT", "5037"),
    )


def patch_skip_screenshot():
    """Skip screenshot capture when ENV_SKIP_SCREENSHOT=true.

    Replaces the expensive pixel-capture call with a zero-filled array.
    """
    if os.getenv("ENV_SKIP_SCREENSHOT", "false").lower() not in ("true", "1", "yes"):
        return

    from android_env.components import coordinator as _coordinator

    def _gather_no_screenshot(self):
        now = time.time()
        delta = (
            0 if self._latest_observation_time == 0
            else (now - self._latest_observation_time) * 1e6
        )
        self._latest_observation_time = now
        h = self._device_settings.screen_height()
        w = self._device_settings.screen_width()
        return {
            'pixels': np.zeros((h, w, 3), dtype=np.uint8),
            'orientation': self._device_settings.get_orientation(),
            'timedelta': np.array(delta, dtype=np.int64),
        }

    _coordinator.Coordinator._gather_simulator_signals = _gather_no_screenshot
    logger.info("Patched screenshot capture to skip (ENV_SKIP_SCREENSHOT=true)")


def apply_all():
    """Apply all runtime patches. Call once at server startup."""
    patch_adb_port()
    patch_skip_screenshot()
