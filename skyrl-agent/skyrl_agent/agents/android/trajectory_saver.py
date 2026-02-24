"""
TrajectorySaver -- writes per-trajectory JSON + optional screenshot PNGs.

Designed to be called from the runner's on_trajectory_complete callback
so that each trajectory is persisted as soon as it finishes, without
blocking the dispatch loop (I/O is cheap compared to LLM inference).
"""

import json
import os
from typing import Dict, Any, List, Optional

import numpy as np
from loguru import logger


class TrajectorySaver:
    """Saves trajectory data (steps, screenshots, metadata) to disk."""

    def __init__(self, save_dir: str, save_screenshots: bool = True):
        self.save_dir = save_dir
        self.save_screenshots = save_screenshots
        os.makedirs(save_dir, exist_ok=True)

    def save(
        self,
        traj_result: Dict[str, Any],
        task_text: str = "",
        model_name: str = "",
    ) -> str:
        """Save a single trajectory to disk.

        Creates ``<save_dir>/<instance_id>/trajectory.json`` and optional
        ``step_<N>.png`` screenshot files.

        Returns the path to the saved JSON file.
        """
        instance_id = str(traj_result.get("instance_id", "unknown"))
        traj_id = traj_result.get("trajectory_id", 0)
        traj_dir = os.path.join(self.save_dir, instance_id)
        os.makedirs(traj_dir, exist_ok=True)

        step_records: List[Dict] = list(traj_result.get("step_records", []))

        # Save screenshots as PNGs and update step records with relative paths
        if self.save_screenshots:
            history_images: List[np.ndarray] = traj_result.get("history_images", [])
            for record in step_records:
                idx = record.get("screenshot_idx")
                if idx is not None and 0 <= idx < len(history_images):
                    img = history_images[idx]
                    if isinstance(img, np.ndarray):
                        img_filename = f"step_{record['step_idx']}.png"
                        img_path = os.path.join(traj_dir, img_filename)
                        try:
                            from PIL import Image
                            Image.fromarray(img).save(img_path)
                            record["screenshot_path"] = img_filename
                        except Exception as e:
                            logger.debug(f"Failed to save screenshot: {e}")

        # Strip non-serialisable fields before writing JSON
        clean_records = []
        for record in step_records:
            r = dict(record)
            r.pop("screenshot_idx", None)
            clean_records.append(r)

        payload = {
            "instance_id": instance_id,
            "trajectory_id": traj_id,
            "task": task_text,
            "model": model_name,
            "reward": traj_result.get("reward", 0.0),
            "finish_reason": traj_result.get("finish_reason", ""),
            "step_count": traj_result.get("step_count", 0),
            "total_input_tokens": traj_result.get("total_input_tokens", 0),
            "total_output_tokens": traj_result.get("total_output_tokens", 0),
            "steps": clean_records,
        }

        json_path = os.path.join(traj_dir, "trajectory.json")
        with open(json_path, "w") as f:
            json.dump(payload, f, indent=2, default=str)

        logger.debug(f"[TrajectorySaver] Saved trajectory {instance_id}/{traj_id} to {json_path}")
        return json_path
