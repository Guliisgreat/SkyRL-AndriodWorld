"""
RuntimeClientADB - Extends RuntimeClient with step_adb() for ADB command execution.

Used by the ADB agent when running against containers that expose POST /step_adb.
Does not modify RuntimeClient; all new behavior is in this subclass.
"""

import asyncio
import logging
from typing import Dict, Tuple

import aiohttp

from .runtime_client import RuntimeClient
from .exceptions import ContainerDeadError

logger = logging.getLogger(__name__)


class RuntimeClientADB(RuntimeClient):
    """
    RuntimeClient that adds step_adb() for raw ADB command execution.

    Requires the container to expose POST /step_adb (e.g. server_adb.py).
    """

    async def step_adb(
        self, payload: Dict
    ) -> Tuple[Dict, str, float, bool, bool, Dict]:
        """
        Execute an ADB command via the container's /step_adb endpoint.

        Uses the same retry/timeout behavior as step().

        Args:
            payload: Dict with "command" (str) and optional "thought" (str).
                     e.g. {"command": "adb shell input tap 540 960", "thought": "..."}

        Returns:
            (observation, command_output, reward, terminated, truncated, info)
        """
        await self._ensure_session()

        last_error = None
        for attempt in range(self.STEP_MAX_RETRIES + 1):
            try:
                async with self.session.post(
                    f"{self.base_url}/step_adb",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.HTTP_TIMEOUT),
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        raise Exception(
                            f"step_adb request to {self.base_url}/step_adb failed "
                            f"with status {response.status}: {body[:500]}"
                        )

                    data = await response.json()

                observation = data.get("observation")
                if observation:
                    observation = self._deserialize_observation(observation)
                else:
                    observation = {}

                command_output = data.get("command_output", "")
                reward = data.get("reward", 0.0)
                terminated = data.get("terminated", False)
                truncated = data.get("truncated", False)
                info = data.get("info", {})

                if attempt > 0:
                    logger.info(
                        f"step_adb succeeded after {attempt} retries on {self.base_url}"
                    )

                return (
                    observation,
                    command_output,
                    reward,
                    terminated,
                    truncated,
                    info,
                )

            except (aiohttp.ClientError, Exception) as e:
                last_error = e
                if attempt < self.STEP_MAX_RETRIES:
                    delay = self.STEP_RETRY_BASE_DELAY
                    logger.warning(
                        f"step_adb request to {self.base_url} failed "
                        f"(attempt {attempt+1}/{self.STEP_MAX_RETRIES+1}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"step_adb request to {self.base_url} failed after "
                        f"{self.STEP_MAX_RETRIES+1} attempts: {e}"
                    )

        raise ContainerDeadError(
            self.container.env_id,
            f"step_adb failed after {self.STEP_MAX_RETRIES+1} attempts: {last_error}",
        )
