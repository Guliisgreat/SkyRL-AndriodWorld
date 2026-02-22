"""
AndroidADBAgent - ADB command agent that uses the same interface as AndroidAgent.

Subclass of AndroidAgent; overrides prompt, action parsing, and step execution
to use ADB commands and step_adb() / step() for task control.
Requires env_handle to be RuntimeClientADB (supports step_adb).
"""

import copy
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from skyrl_agent.agents.android.android_agent import AndroidAgent
from skyrl_agent.agents.android.adb_agent import (
    build_initial_messages,
    append_assistant as adb_append_assistant,
    append_adb_observation,
    apply_sliding_window,
    parse_adb_command,
    parse_task_control,
)
from skyrl_agent.config.configuration_utils import TrajectoryConfig


# Default system prompt for ADB agent (same as CLI)
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


class AndroidADBAgent(AndroidAgent):
    """
    Android agent that generates raw ADB commands and uses step_adb() for execution.

    Uses ADB_AGENT_PROMPT, parse_adb_command, parse_task_control; calls env_handle.step_adb()
    for shell commands and env_handle.step() for FINISH/INFEASIBLE.
    env_handle must be RuntimeClientADB.
    """

    def format_initial_instruction(
        self,
        template_messages: List[Dict],
        observation: Dict,
        task,
    ) -> List[Dict]:
        """
        Format initial instruction with ADB prompt and first screenshot.

        Uses build_initial_messages from adb_agent (task text, screenshot, resolution).
        """
        task_text = observation.get("task", "") or getattr(task, "goal", "")
        image = observation.get("image")
        if image is None:
            raise ValueError("ADB agent requires observation with 'image'")
        if not isinstance(image, np.ndarray):
            image = np.array(image)
        height, width = image.shape[0], image.shape[1]
        screen_resolution = (width, height)
        system_prompt = DEFAULT_SYSTEM_PROMPT
        if template_messages and isinstance(template_messages[0].get("content"), str):
            system_prompt = template_messages[0]["content"]
        elif template_messages and isinstance(template_messages[0].get("content"), list):
            for block in template_messages[0]["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    system_prompt = block.get("text", system_prompt)
                    break
        return build_initial_messages(
            task_text,
            image,
            screen_resolution,
            system_prompt=system_prompt,
        )

    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """
        Single step: generate -> parse_adb_command -> step_adb or step -> update state.

        Uses apply_sliding_window for message selection; executes via env_handle.step_adb()
        or env_handle.step() for FINISH/INFEASIBLE.
        """
        self.state.step_count += 1
        max_history_steps = getattr(
            getattr(self.memory, "config", None), "max_steps", 10
        )

        # 1. Select messages (sliding window)
        selected_messages = apply_sliding_window(
            self.state.messages,
            max_history_steps=max_history_steps,
        )

        # 2. Prepare inference input and images
        inference_input_ids = self.prepare_input_ids(selected_messages)
        image_data = self.extract_images_for_inference(selected_messages)

        sampling_params = copy.deepcopy(self.sampling_params)
        # Pop max_tokens to avoid conflict with vLLM server which sets its own.
        # We keep the value for reference but remove it from the dict that gets
        # forwarded to SamplingParams via **kwargs.
        _cfg_max = sampling_params.pop("max_tokens", 2048)
        remaining = self.max_prompt_length - len(inference_input_ids)
        # The server will compute max_tokens = max_model_len - len(prompt_ids).
        # If we want a tighter limit, we can pass it; otherwise leave it out.
        if remaining < _cfg_max:
            sampling_params["max_tokens"] = remaining

        # 3. Generate
        result = await self.infer_engine.async_generate_ids(
            input_ids=inference_input_ids,
            sampling_params=sampling_params,
            request_id=self.agent_id,
            image_data=image_data,
            return_token_ids=True,
        )
        response_str, stop_reason, _prompt_token_ids, response_token_ids = result

        if stop_reason == "length":
            self.state.messages = adb_append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None

        # 4. Parse ADB command
        try:
            command, thought = parse_adb_command(response_str)
            self.state.format_reward = 0.0
        except Exception as e:
            self.state.format_reward = -1.0
            command = "INFEASIBLE(content='parse error')"
            thought = str(e)[:200]

        # 5. Execute: task control -> step(); else -> step_adb()
        if command.startswith("FINISH") or command.startswith("INFEASIBLE"):
            action_dict = parse_task_control(command)
            payload = {"action": action_dict, "thought": thought}
            observation, reward, terminated, truncated, info = await self.env_handle.step(
                payload
            )
            command_output = ""
        else:
            payload = {"command": command, "thought": thought}
            (
                observation,
                command_output,
                reward,
                terminated,
                truncated,
                info,
            ) = await self.env_handle.step_adb(payload)

        self.state.reward = reward

        # 6. Update messages
        self.state.messages = adb_append_assistant(self.state.messages, response_str)

        if terminated or truncated:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "FINISH" if terminated else "TRUNCATED", self.state.reward

        image = observation.get("image") if observation else None
        if image is None:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "NO_SCREENSHOT", None

        # 7. Append ADB observation (text feedback + screenshot)
        if isinstance(image, np.ndarray):
            h, w = image.shape[0], image.shape[1]
        else:
            w, h = 1080, 1920
        self.state.messages = append_adb_observation(
            self.state.messages,
            image,
            command,
            command_output,
            "",
            0,
            (w, h),
        )
        self.state.images.append(image)

        _should_add, should_continue = self.training.add_step(
            self.state.messages, response_token_ids
        )
        if not should_continue:
            self.state.is_done = True
            return True, "TRAINING_BUDGET_EXCEEDED", None

        return False, None, None
