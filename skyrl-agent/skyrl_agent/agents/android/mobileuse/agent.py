"""
AndroidMobileUseAgent — MobileUse hierarchical multi-agent in skyrl-agent.

Reimplements MobileUse's orchestration logic (Planner → Operator → Reflector →
TrajectoryReflector → Progressor → GlobalReflector → AnswerAgent) within the
skyrl-agent ``AndroidAgent`` interface.

Key design decisions:
  - Operator is the **trainable** generation; all other sub-agents are
    auxiliary LLM calls (not recorded for RL training).
  - MobileUse rebuilds the operator prompt **from scratch each step**
    (unlike M3A/T3A which accumulate multi-turn conversations).
    ``self.state.messages`` is used for training accumulation only.
  - Auxiliary sub-agents share the same ``infer_engine`` as the operator.
"""

import copy
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from skyrl_agent.agents.android.base import AndroidAgent, TrajectoryState
from skyrl_agent.config.configuration_utils import TrajectoryConfig
from skyrl_agent.integrations.base import AsyncInferBackend
from ..utils import init_messages, load_content, numpy_to_base64

from .parsers import (
    parse_answer_response,
    parse_global_reflector_response,
    parse_operator_response,
    parse_planner_response,
    parse_progressor_response,
    parse_reflector_response,
    parse_trajectory_reflector_response,
)
from .prompts import (
    build_answer_messages,
    build_global_reflector_messages,
    build_operator_messages,
    build_planner_messages,
    build_progressor_messages,
    build_reflector_messages,
    build_trajectory_reflector_messages,
    format_history,
)
from .utils import (
    is_same_image,
    mobileuse_action_to_skyrl,
    smart_resize,
)

DEBUG_TIMING = os.environ.get("DEBUG_TIMING", "0") == "1"

# ADB keycode map for the `key` action
_ADB_KEY_MAP = {
    "home": 3,
    "back": 4,
    "enter": 66,
    "delete": 67,
    "del": 67,
    "backspace": 67,
    "clear": 28,
    "volume_up": 24,
    "volume_down": 25,
    "power": 26,
    "tab": 61,
    "escape": 111,
    "esc": 111,
    "space": 62,
    "menu": 82,
    "search": 84,
    "camera": 27,
    "page_up": 92,
    "page_down": 93,
}

# Minimum number of steps before allowing answer/terminate (Q&A guard)
_MIN_STEPS_BEFORE_FINISH = 5

# Default MobileUse configuration values
_DEFAULT_MOBILEUSE_CONFIG = {
    # Sub-agent enable flags
    "enable_planner": False,
    "enable_reflector": True,
    "enable_trajectory_reflector": True,
    "enable_global_reflector": True,
    "enable_progressor": True,
    "enable_answer_agent": True,
    # Reflector parameters
    "reflect_on_demand": False,
    "logprob_threshold": -0.01,
    "max_action_retry": 3,
    # Trajectory reflector parameters
    "traj_reflector_evoke_every": 5,
    "traj_reflector_cold_steps": 3,
    "max_repeat_action": 3,
    "max_repeat_screen": 3,
    "max_fail_count": 3,
    # Global reflector
    "max_finish_count": 3,
    # Image sizing for Qwen2.5-VL
    "min_pixels": 3136,          # 4 * 28 * 28
    "max_pixels": 12845056,      # 16384 * 28 * 28
    # History
    "num_histories": None,       # None = all
    # Pre-reflection optimization
    "enable_pre_reflection": True,
}


class AndroidMobileUseAgent(AndroidAgent):
    """MobileUse hierarchical multi-agent for AndroidWorld.

    Subclass of ``AndroidAgent``. Overrides ``format_initial_instruction``
    and ``step`` to implement the full MobileUse pipeline.
    """

    def __init__(
        self,
        traj_config: TrajectoryConfig,
        infer_engine: AsyncInferBackend,
        tokenizer: Any,
        processor: Any,
        env_handle: Any,
    ) -> None:
        super().__init__(traj_config, infer_engine, tokenizer, processor, env_handle)

        # Parse MobileUse-specific config from traj_config
        mu_cfg = getattr(traj_config, "mobileuse", None) or {}
        self.mu_cfg: Dict[str, Any] = {**_DEFAULT_MOBILEUSE_CONFIG, **mu_cfg}

        # MobileUse state (rebuilt each step, not accumulated)
        self._goal: str = ""
        self._step_history: List[Dict] = []
        self._current_plan: Optional[str] = None
        self._current_subgoal: Optional[str] = None
        self._memory: str = ""
        self._last_reflection: Optional[Dict] = None
        self._last_traj_reflection: Optional[Dict] = None
        self._global_reflection_error: Optional[str] = None
        self._progress: str = ""
        self._current_screenshot: Optional[np.ndarray] = None
        self._before_screenshot: Optional[np.ndarray] = None
        self._finish_count: int = 0

        # Trajectory reflector timing
        self._last_traj_reflect_step: int = 0

        # Screen dimensions (updated from first screenshot)
        self._screen_w: int = 1080
        self._screen_h: int = 2400

        # Resized dimensions for Qwen2.5-VL
        self._resized_w: int = 0
        self._resized_h: int = 0

        # Auxiliary LLM call tracking
        self._aux_input_tokens: int = 0
        self._aux_output_tokens: int = 0

    # ------------------------------------------------------------------
    # ADB-based action execution
    # ------------------------------------------------------------------

    @staticmethod
    def _escape_adb_text(text: str) -> str:
        """Escape text for `adb shell input text`."""
        # adb input text treats spaces as separators; use %s
        # Also escape shell-special characters
        result = text.replace("\\", "\\\\")
        result = result.replace('"', '\\"')
        result = result.replace("'", "\\'")
        result = result.replace(" ", "%s")
        result = result.replace("&", "\\&")
        result = result.replace("<", "\\<")
        result = result.replace(">", "\\>")
        result = result.replace("|", "\\|")
        result = result.replace(";", "\\;")
        result = result.replace("(", "\\(")
        result = result.replace(")", "\\)")
        result = result.replace("$", "\\$")
        result = result.replace("`", "\\`")
        result = result.replace("!", "\\!")
        result = result.replace("~", "\\~")
        result = result.replace("{", "\\{")
        result = result.replace("}", "\\}")
        return result

    async def _execute_action(
        self,
        action_dict: Dict,
        thought: str,
    ) -> Tuple[Dict, float, bool, bool, Dict]:
        """Execute an action, routing type/clear_text/swipe/key through ADB.

        Returns (output_dict, reward, terminated, truncated, info) where
        output_dict has 'image', 'reward', 'terminated', 'truncated' keys
        matching what the /step tool returns.
        """
        action_name = action_dict.get("action", "")

        # --- type: ADB text input WITHOUT auto-enter ---
        if action_name == "type":
            text = action_dict.get("text", "")
            if not text:
                # Empty type → wait
                skyrl_action = {"action_type": "wait"}
                tool = self.tools["android_env"]
                return await tool.async_call(
                    skyrl_action, env_handle=self.env_handle, thought=thought,
                )
            escaped = self._escape_adb_text(text)
            cmd = f'adb shell input text "{escaped}"'
            obs, cmd_out, reward, term, trunc, info = await self.env_handle.step_adb(
                {"command": cmd, "thought": thought}
            )
            image = obs.get("image") if obs else None
            return {
                "image": image,
                "reward": reward,
                "terminated": term,
                "truncated": trunc,
                **info,
            }

        # --- clear_text: ADB select-all + delete ---
        if action_name == "clear_text":
            # Ctrl+A (select all) = KEYCODE_A (29) with --longpress for modifier
            # then KEYCODE_DEL (67) to delete selected
            cmd = "adb shell input keyevent 29 --longpress && adb shell input keyevent 67"
            obs, cmd_out, reward, term, trunc, info = await self.env_handle.step_adb(
                {"command": cmd, "thought": thought}
            )
            image = obs.get("image") if obs else None
            return {
                "image": image,
                "reward": reward,
                "terminated": term,
                "truncated": trunc,
                **info,
            }

        # --- swipe: ADB coordinate-based swipe ---
        if action_name == "swipe":
            coord1 = action_dict.get("coordinate", [0, 0])
            coord2 = action_dict.get("coordinate2", [0, 0])
            x1, y1 = int(coord1[0]), int(coord1[1])
            x2, y2 = int(coord2[0]), int(coord2[1])
            cmd = f"adb shell input swipe {x1} {y1} {x2} {y2} 500"
            obs, cmd_out, reward, term, trunc, info = await self.env_handle.step_adb(
                {"command": cmd, "thought": thought}
            )
            image = obs.get("image") if obs else None
            return {
                "image": image,
                "reward": reward,
                "terminated": term,
                "truncated": trunc,
                **info,
            }

        # --- key: ADB keyevent with proper keycodes ---
        if action_name == "key":
            key_text = action_dict.get("text", "").lower()
            keycode = _ADB_KEY_MAP.get(key_text)
            if keycode is not None:
                cmd = f"adb shell input keyevent {keycode}"
                obs, cmd_out, reward, term, trunc, info = await self.env_handle.step_adb(
                    {"command": cmd, "thought": thought}
                )
                image = obs.get("image") if obs else None
                return {
                    "image": image,
                    "reward": reward,
                    "terminated": term,
                    "truncated": trunc,
                    **info,
                }
            # Fall through to existing path for unmapped keys

        # --- Default: existing JSON action via /step ---
        skyrl_action = mobileuse_action_to_skyrl(
            action_dict, self._screen_w, self._screen_h,
        )
        tool = self.tools["android_env"]
        return await tool.async_call(
            skyrl_action, env_handle=self.env_handle, thought=thought,
        )

    # ------------------------------------------------------------------
    # Initial instruction
    # ------------------------------------------------------------------

    def format_initial_instruction(
        self,
        template_messages: List[Dict],
        observation: Dict,
        task,
    ) -> List[Dict]:
        """Format initial instruction and optionally run planner.

        Extracts the goal, captures the initial screenshot, computes
        resized dimensions, and builds the first operator prompt.
        """
        self._goal = (observation or {}).get("task", "")
        image = (observation or {}).get("image")

        if image is not None and isinstance(image, np.ndarray) and image.ndim >= 2:
            self._screen_h, self._screen_w = image.shape[:2]
        else:
            image = np.zeros((self._screen_h, self._screen_w, 3), dtype=np.uint8)

        self._current_screenshot = image

        # Compute resized dimensions
        self._resized_h, self._resized_w = smart_resize(
            self._screen_h, self._screen_w,
            min_pixels=self.mu_cfg["min_pixels"],
            max_pixels=self.mu_cfg["max_pixels"],
        )

        # Build a minimal initial message for training accumulation.
        # The actual operator prompt is built dynamically each step.
        system_msg = {
            "role": "system",
            "content": [{"type": "text", "text": "You are a helpful assistant."}],
        }
        image_b64 = numpy_to_base64(image)
        user_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Task: {self._goal}"},
                {
                    "type": "image",
                    "image": f"data:image/png;base64,{image_b64}",
                    "min_pixels": self.min_pixels,
                    "max_pixels": self.max_pixels,
                },
            ],
        }

        return [system_msg, user_msg]

    # ------------------------------------------------------------------
    # Main step
    # ------------------------------------------------------------------

    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """Execute one full MobileUse cycle.

        Pipeline per step:
          1. PLANNER (auxiliary) → update plan + subgoal
          2. OPERATOR (trainable) → predict action
          3. Handle special actions (terminate, answer, take_note)
          4. EXECUTE via android_env tool
          5. REFLECTOR (auxiliary) → validate action outcome
          6. TRAJECTORY REFLECTOR (auxiliary) → detect stuck/repeat patterns
          7. PROGRESSOR (auxiliary) → summarize progress
          8. Record training step
        """
        self.state.step_count += 1
        step_idx = self.state.step_count
        print(f"[MobileUse Step {step_idx}] instance={self.state.instance_id} traj={self.state.trajectory_id}")

        if DEBUG_TIMING:
            step_start = time.perf_counter()

        # Snapshot the pre-action screenshot
        self._before_screenshot = self._current_screenshot

        # -----------------------------------------------------------
        # 1. PLANNER (auxiliary, not trained)
        # -----------------------------------------------------------
        if self.mu_cfg["enable_planner"]:
            await self._run_planner()

        # -----------------------------------------------------------
        # 2. OPERATOR (trainable LLM call)
        # -----------------------------------------------------------
        operator_messages, resized_size, raw_size = build_operator_messages(
            goal=self._goal,
            plan=self._current_plan or "",
            subgoal=self._current_subgoal or "",
            step_history=self._step_history,
            memory=self._memory,
            reflection=self._last_reflection,
            traj_reflection=self._last_traj_reflection,
            global_reflection=self._global_reflection_error,
            progress=self._progress,
            screenshot_np=self._current_screenshot,
            resized_w=self._resized_w,
            resized_h=self._resized_h,
            min_pixels=self.mu_cfg["min_pixels"],
            max_pixels=self.mu_cfg["max_pixels"],
            enable_planner=self.mu_cfg["enable_planner"],
        )

        # Clear one-shot feedback signals after they've been included
        self._last_reflection = None
        self._last_traj_reflection = None
        self._global_reflection_error = None

        # Tokenize and generate
        inference_input_ids = self.prepare_input_ids(operator_messages)
        image_data = self.extract_images_for_inference(operator_messages)

        sampling_params = copy.deepcopy(self.sampling_params)
        sampling_params.pop("max_tokens", None)

        if DEBUG_TIMING:
            vllm_start = time.perf_counter()

        result = await self.infer_engine.async_generate_ids(
            input_ids=inference_input_ids,
            sampling_params=sampling_params,
            request_id=self.agent_id,
            image_data=image_data,
            return_token_ids=True,
            messages=operator_messages,
        )

        response_str, stop_reason, _prompt_token_ids, response_token_ids = result

        self.state.total_input_tokens += len(_prompt_token_ids)
        self.state.total_output_tokens += len(response_token_ids)

        if DEBUG_TIMING:
            vllm_elapsed = time.perf_counter() - vllm_start

        # Check for length stop
        if stop_reason == "length":
            print(f"[MobileUse] Context window exceeded at step {step_idx}")
            self.state.messages = self.append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None

        # -----------------------------------------------------------
        # Parse operator response (with multi-turn retry matching original)
        # -----------------------------------------------------------
        thought, action_dict, action_str, action_desc = "", {}, "", ""
        parse_ok = False
        retry_messages = list(operator_messages)  # copy for multi-turn retry
        for retry in range(self.mu_cfg["max_action_retry"]):
            try:
                thought, action_dict, action_str, action_desc = parse_operator_response(
                    response_str, resized_size, raw_size,
                )
                self.state.format_reward = 0.0
                parse_ok = True
                break
            except (ValueError, Exception) as e:
                if retry < self.mu_cfg["max_action_retry"] - 1:
                    print(f"[MobileUse] Parse retry {retry+1}: {e}")
                    # Append error feedback (matching original multi-turn retry)
                    error_prompt = (
                        f"Failed to parse the action. Error is {e.args}\n"
                        "Please follow the output format to provide a valid action:"
                    )
                    retry_messages.append({"role": "assistant", "content": [{"type": "text", "text": response_str}]})
                    retry_messages.append({"role": "user", "content": [{"type": "text", "text": error_prompt}]})
                    # Re-generate with error context
                    retry_input_ids = self.prepare_input_ids(retry_messages)
                    retry_image_data = self.extract_images_for_inference(retry_messages)
                    result = await self.infer_engine.async_generate_ids(
                        input_ids=retry_input_ids,
                        sampling_params=sampling_params,
                        request_id=self.agent_id,
                        image_data=retry_image_data,
                        return_token_ids=True,
                        messages=retry_messages,
                    )
                    response_str, stop_reason, _prompt_token_ids, response_token_ids = result
                    self.state.total_input_tokens += len(_prompt_token_ids)
                    self.state.total_output_tokens += len(response_token_ids)
                else:
                    print(f"[MobileUse] Parse failed after {self.mu_cfg['max_action_retry']} retries: {e}")

        if not parse_ok:
            self.state.format_reward = -1.0
            action_dict = {"action": "terminate", "status": "failure"}
            action_str = json.dumps(action_dict)
            action_desc = "Parse error fallback: terminate"
            thought = f"Parse error: {response_str[:200]}"

        action_name = action_dict.get("action", "wait")

        # -----------------------------------------------------------
        # 3. Handle special actions before env execution
        # -----------------------------------------------------------

        # Q&A guard: prevent premature answer/terminate before min steps
        if action_name in ("answer", "terminate") and step_idx < _MIN_STEPS_BEFORE_FINISH:
            print(f"[MobileUse] Blocked early {action_name} at step {step_idx} (min={_MIN_STEPS_BEFORE_FINISH})")
            # Convert to wait and inject reflection guidance
            action_dict = {"action": "wait"}
            action_name = "wait"
            action_str = '{"action": "wait"}'
            action_desc = "wait (blocked early finish)"
            self._last_reflection = {
                "outcome": "C",
                "error": (
                    "You must navigate to the relevant app and verify the "
                    "information before answering. Do not answer prematurely."
                ),
                "action_desc": action_desc,
                "action_str": action_str,
            }

        # take_note: update memory, skip env execution
        if action_name == "take_note":
            note_text = action_dict.get("text", "")
            if note_text:
                self._memory = (self._memory + "\n" + note_text).strip() if self._memory else note_text
            # Record step
            self._record_step_history(step_idx, thought, action_dict, action_str, action_desc)
            self.state.messages = self.append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            return False, None, None

        # answer: use operator's answer directly (DON'T run answer_agent here —
        # original MobileUse only runs answer_agent on "terminate", not "answer")
        if action_name == "answer":
            answer_text = action_dict.get("text", "")

            # Run global reflector to validate
            should_finish = await self._handle_finish(
                answer_text=answer_text,
                response_str=response_str,
                response_token_ids=response_token_ids,
                step_idx=step_idx,
                thought=thought,
                action_dict=action_dict,
                action_str=action_str,
                action_desc=action_desc,
            )
            if should_finish:
                return True, "FINISH", self.state.reward

            # Not actually finished — continue
            return False, None, None

        # terminate: run answer_agent first (if enabled), then global reflector
        if action_name == "terminate":
            # Original MobileUse runs answer_agent on terminate to generate
            # an answer when the operator hasn't provided one
            answer_text = None
            if self.mu_cfg["enable_answer_agent"]:
                answer_text = await self._run_answer_agent()

            should_finish = await self._handle_finish(
                answer_text=answer_text,
                response_str=response_str,
                response_token_ids=response_token_ids,
                step_idx=step_idx,
                thought=thought,
                action_dict=action_dict,
                action_str=action_str,
                action_desc=action_desc,
            )
            if should_finish:
                status = action_dict.get("status", "failure")
                goal_status = "complete" if status == "success" else "infeasible"
                skyrl_action = {"action_type": "status", "goal_status": goal_status}
                tool = self.tools["android_env"]
                output = await tool.async_call(
                    skyrl_action, env_handle=self.env_handle, thought=thought,
                )
                self.state.reward = output.get("reward", 0.0)
                self.state.messages = self.append_assistant(self.state.messages, response_str)
                self.training.add_step(self.state.messages, response_token_ids)
                self.state.is_done = True
                return True, "FINISH", self.state.reward

            # Not actually finished — continue
            return False, None, None

        # -----------------------------------------------------------
        # 4. EXECUTE via android_env tool
        # -----------------------------------------------------------

        # Pre-reflection: consecutive type without click
        skip_reflector = False
        if (self.mu_cfg["enable_pre_reflection"]
                and action_name == "type"
                and len(self._step_history) > 0
                and self._step_history[-1].get("action_name") == "type"
                and "coordinate" not in action_dict):
            skip_reflector = True
            self._last_reflection = {
                "outcome": "C",
                "error": "Action executed failed. You should first click the corresponding text field before typing in text.",
                "action_desc": action_desc,
                "action_str": action_str,
            }

        if DEBUG_TIMING:
            container_start = time.perf_counter()

        # Execute via ADB-routed or standard /step path
        output = await self._execute_action(action_dict, thought)

        if DEBUG_TIMING:
            container_elapsed = time.perf_counter() - container_start
            print(f"[Timing] step={step_idx} vLLM={vllm_elapsed:.2f}s container={container_elapsed:.2f}s")

        self.state.reward = output.get("reward", 0.0)
        terminated = output.get("terminated", False)
        truncated = output.get("truncated", False)

        # Record step metadata
        self.state.step_records.append({
            "step_idx": step_idx,
            "thought": thought,
            "raw_response": response_str,
            "action_type": action_name,
            "action_params": {k: v for k, v in action_dict.items() if k != "action"},
            "mobileuse_action": action_dict,
            "command_output": None,
            "a11y_tree": None,
            "screenshot_idx": len(self.state.images),
            "input_tokens": len(_prompt_token_ids),
            "output_tokens": len(response_token_ids),
        })

        # Update training messages
        self.state.messages = self.append_assistant(self.state.messages, response_str)

        if terminated or truncated:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            finish_reason = "FINISH" if terminated else "TRUNCATED"
            return True, finish_reason, self.state.reward

        # Get post-action screenshot
        image = output.get("image")
        if image is None:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)
            return True, "NO_SCREENSHOT", None

        self._current_screenshot = image
        self.state.messages = self.append_observation(self.state.messages, image)
        self.state.images.append(image)

        # -----------------------------------------------------------
        # 5. REFLECTOR (auxiliary)
        # -----------------------------------------------------------
        if self.mu_cfg["enable_reflector"] and not skip_reflector:
            await self._run_reflector(action_str, action_desc)

        # -----------------------------------------------------------
        # 6. TRAJECTORY REFLECTOR (auxiliary)
        # -----------------------------------------------------------
        if self.mu_cfg["enable_trajectory_reflector"]:
            await self._maybe_run_trajectory_reflector(step_idx)

        # -----------------------------------------------------------
        # 7. PROGRESSOR (auxiliary)
        # -----------------------------------------------------------
        if self.mu_cfg["enable_progressor"]:
            await self._run_progressor(thought, action_desc, action_str)

        # Record step in history
        self._record_step_history(step_idx, thought, action_dict, action_str, action_desc)

        # -----------------------------------------------------------
        # 8. Training recording
        # -----------------------------------------------------------
        _should_add, should_continue = self.training.add_step(
            self.state.messages, response_token_ids,
        )
        if not should_continue:
            self.state.is_done = True
            return True, "TRAINING_BUDGET_EXCEEDED", None

        return False, None, None

    # ==================================================================
    # Auxiliary sub-agent runners
    # ==================================================================

    async def _auxiliary_generate(self, messages: List[Dict]) -> str:
        """Run a non-trainable LLM call through the same infer_engine.

        Token counts are tracked separately for monitoring.
        """
        input_ids = self.prepare_input_ids(messages)
        image_data = self.extract_images_for_inference(messages)

        sampling_params = copy.deepcopy(self.sampling_params)
        sampling_params.pop("max_tokens", None)

        result = await self.infer_engine.async_generate_ids(
            input_ids=input_ids,
            sampling_params=sampling_params,
            request_id=self.agent_id + "_aux",
            image_data=image_data,
            return_token_ids=True,
            messages=messages,
        )
        response_str, _stop_reason, prompt_ids, resp_ids = result
        self._aux_input_tokens += len(prompt_ids)
        self._aux_output_tokens += len(resp_ids)
        return response_str

    # ------------------------------------------------------------------
    # Planner
    # ------------------------------------------------------------------

    async def _run_planner(self) -> None:
        """Run planner to get/update plan and subgoal."""
        messages = build_planner_messages(
            goal=self._goal,
            screenshot_np=self._current_screenshot,
            resized_w=self._resized_w,
            resized_h=self._resized_h,
            current_plan=self._current_plan,
            previous_subgoal=self._current_subgoal,
            min_pixels=self.mu_cfg["min_pixels"],
            max_pixels=self.mu_cfg["max_pixels"],
        )
        try:
            response = await self._auxiliary_generate(messages)
            _thought, plan, subgoal = parse_planner_response(response)
            if plan:
                self._current_plan = plan
            if subgoal:
                self._current_subgoal = subgoal
        except Exception as e:
            print(f"[MobileUse Planner] Error: {e}")

    # ------------------------------------------------------------------
    # Reflector
    # ------------------------------------------------------------------

    async def _run_reflector(self, action_str: str, action_desc: str) -> None:
        """Run reflector to validate the last action."""
        if self._before_screenshot is None or self._current_screenshot is None:
            return

        same = is_same_image(self._before_screenshot, self._current_screenshot)

        messages = build_reflector_messages(
            goal=self._goal,
            subgoal=self._current_subgoal or "",
            before_screenshot_np=self._before_screenshot,
            after_screenshot_np=self._current_screenshot,
            action_str=action_str,
            action_desc=action_desc,
            resized_w=self._resized_w,
            resized_h=self._resized_h,
            same_image=same,
            min_pixels=self.mu_cfg["min_pixels"],
            max_pixels=self.mu_cfg["max_pixels"],
        )
        try:
            response = await self._auxiliary_generate(messages)
            outcome, error_desc = parse_reflector_response(response)
            self._last_reflection = {
                "outcome": outcome,
                "error": error_desc,
                "action_desc": action_desc,
                "action_str": action_str,
            }
        except Exception as e:
            print(f"[MobileUse Reflector] Error: {e}")

    # ------------------------------------------------------------------
    # Trajectory reflector
    # ------------------------------------------------------------------

    async def _maybe_run_trajectory_reflector(self, step_idx: int) -> None:
        """Run trajectory reflector if due (every N steps or on error)."""
        evoke_every = self.mu_cfg["traj_reflector_evoke_every"]
        cold_steps = self.mu_cfg["traj_reflector_cold_steps"]

        # Check if enough steps have elapsed since last invocation
        steps_since = step_idx - self._last_traj_reflect_step
        error_detected = self._detect_trajectory_errors()

        should_run = (
            (steps_since >= evoke_every)
            or (error_detected and steps_since >= cold_steps)
        )
        if not should_run:
            return

        # Collect recent screenshots (last 3)
        recent_screenshots = []
        for img in self.state.images[-3:]:
            recent_screenshots.append(img)
        if self._current_screenshot is not None and (
            not recent_screenshots
            or not np.array_equal(recent_screenshots[-1], self._current_screenshot)
        ):
            recent_screenshots.append(self._current_screenshot)

        if not recent_screenshots:
            return

        error_info = self._get_trajectory_error_info() if error_detected else None

        messages = build_trajectory_reflector_messages(
            goal=self._goal,
            plan=self._current_plan or "",
            step_history=self._step_history,
            progress=self._progress,
            recent_screenshots=recent_screenshots,
            resized_w=self._resized_w,
            resized_h=self._resized_h,
            error_info=error_info,
            min_pixels=self.mu_cfg["min_pixels"],
            max_pixels=self.mu_cfg["max_pixels"],
        )
        try:
            response = await self._auxiliary_generate(messages)
            outcome, error_desc = parse_trajectory_reflector_response(response)
            self._last_traj_reflection = {
                "outcome": outcome,
                "error": error_desc,
            }
            self._last_traj_reflect_step = step_idx
        except Exception as e:
            print(f"[MobileUse TrajReflector] Error: {e}")

    def _detect_trajectory_errors(self) -> bool:
        """Detect repeated actions, repeated screens, or consecutive failures."""
        history = self._step_history
        if len(history) < 2:
            return False

        max_repeat = self.mu_cfg["max_repeat_action"]
        max_fail = self.mu_cfg["max_fail_count"]

        # Check repeated single action
        if len(history) >= max_repeat:
            last_actions = [h.get("action_str", "") for h in history[-max_repeat:]]
            if len(set(last_actions)) == 1:
                return True

        # Check consecutive reflection failures
        if len(history) >= max_fail:
            last_outcomes = [h.get("reflection_outcome", "A") for h in history[-max_fail:]]
            if all(o in ("B", "C") for o in last_outcomes):
                return True

        # Check repeated screenshots
        max_screen = self.mu_cfg["max_repeat_screen"]
        if len(self.state.images) >= max_screen:
            recent = self.state.images[-max_screen:]
            all_same = all(is_same_image(recent[0], img) for img in recent[1:])
            if all_same:
                return True

        return False

    def _get_trajectory_error_info(self) -> str:
        """Generate error info string for trajectory reflector."""
        history = self._step_history
        if not history:
            return ""

        max_repeat = self.mu_cfg["max_repeat_action"]
        if len(history) >= max_repeat:
            last_actions = [h.get("action_str", "") for h in history[-max_repeat:]]
            if len(set(last_actions)) == 1:
                return f"Repeated the same action {max_repeat} times: {last_actions[0]}"

        max_screen = self.mu_cfg["max_repeat_screen"]
        if len(self.state.images) >= max_screen:
            recent = self.state.images[-max_screen:]
            all_same = all(is_same_image(recent[0], img) for img in recent[1:])
            if all_same:
                return f"Screen unchanged for {max_screen} consecutive steps."

        max_fail = self.mu_cfg["max_fail_count"]
        if len(history) >= max_fail:
            last_outcomes = [h.get("reflection_outcome", "A") for h in history[-max_fail:]]
            if all(o in ("B", "C") for o in last_outcomes):
                return f"Last {max_fail} actions all failed."

        return ""

    # ------------------------------------------------------------------
    # Progressor
    # ------------------------------------------------------------------

    async def _run_progressor(self, thought: str, action_desc: str, action_str: str) -> None:
        """Run progressor to update progress summary."""
        reflection_error = None
        if self._last_reflection and self._last_reflection.get("outcome") in ("B", "C"):
            reflection_error = self._last_reflection.get("error")

        messages = build_progressor_messages(
            goal=self._goal,
            step_history=self._step_history,
            progress=self._progress,
            thought=thought,
            action_desc=action_desc,
            action_str=action_str,
            reflection_error=reflection_error,
        )
        try:
            response = await self._auxiliary_generate(messages)
            progress = parse_progressor_response(response)
            if progress:
                self._progress = progress
        except Exception as e:
            print(f"[MobileUse Progressor] Error: {e}")

    # ------------------------------------------------------------------
    # Answer agent
    # ------------------------------------------------------------------

    async def _run_answer_agent(self) -> str:
        """Run answer agent to generate a refined answer."""
        messages = build_answer_messages(
            goal=self._goal,
            plan=self._current_plan or "",
            subgoal=self._current_subgoal or "",
            step_history=self._step_history,
            memory=self._memory,
            progress=self._progress,
            screenshot_np=self._current_screenshot,
            resized_w=self._resized_w,
            resized_h=self._resized_h,
            min_pixels=self.mu_cfg["min_pixels"],
            max_pixels=self.mu_cfg["max_pixels"],
        )
        try:
            response = await self._auxiliary_generate(messages)
            return parse_answer_response(response)
        except Exception as e:
            print(f"[MobileUse AnswerAgent] Error: {e}")
            return ""

    # ------------------------------------------------------------------
    # Global reflector + finish handling
    # ------------------------------------------------------------------

    async def _handle_finish(
        self,
        answer_text: Optional[str],
        response_str: str,
        response_token_ids: List[int],
        step_idx: int,
        thought: str,
        action_dict: Dict,
        action_str: str,
        action_desc: str,
    ) -> bool:
        """Handle terminate/answer: run global reflector, decide if done.

        Returns True if the episode should actually finish.
        """
        self._finish_count += 1

        # Record step
        self._record_step_history(step_idx, thought, action_dict, action_str, action_desc)

        # If answer, execute it via env
        if answer_text:
            skyrl_action = {"action_type": "answer", "text": answer_text}
            tool = self.tools["android_env"]
            output = await tool.async_call(
                skyrl_action, env_handle=self.env_handle, thought=thought,
            )
            self.state.reward = output.get("reward", 0.0)
            terminated = output.get("terminated", False)
            if terminated:
                self.state.messages = self.append_assistant(self.state.messages, response_str)
                self.training.add_step(self.state.messages, response_token_ids)
                self.state.is_done = True
                return True

        # Run global reflector (only on first finish attempt)
        if self.mu_cfg["enable_global_reflector"] and self._finish_count == 1:
            result = await self._run_global_reflector()
            if result in ("Failed", "Uncertain"):
                # Revert: give second chance (treat Uncertain same as Failed)
                if result == "Uncertain":
                    print(f"[MobileUse] Global reflector returned 'Uncertain' — continuing execution")
                self._global_reflection_error = self._last_global_reason
                self.state.messages = self.append_assistant(self.state.messages, response_str)
                # Re-capture screenshot for continued execution
                if self._current_screenshot is not None:
                    self.state.messages = self.append_observation(
                        self.state.messages, self._current_screenshot,
                    )
                self.training.add_step(self.state.messages, response_token_ids)
                return False

        # Exceeded finish_count or reflector says Success → actually finish
        if self._finish_count >= self.mu_cfg["max_finish_count"]:
            self.state.messages = self.append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)
            self.state.is_done = True
            return True

        # Global reflector said Success → finish
        self.state.messages = self.append_assistant(self.state.messages, response_str)
        self.training.add_step(self.state.messages, response_token_ids)
        self.state.is_done = True
        return True

    async def _run_global_reflector(self) -> str:
        """Run global reflector. Returns 'Success', 'Failed', or 'Uncertain'."""
        recent_screenshots = []
        for img in self.state.images[-3:]:
            recent_screenshots.append(img)
        if self._current_screenshot is not None:
            recent_screenshots.append(self._current_screenshot)
        if not recent_screenshots:
            recent_screenshots = [self._current_screenshot or np.zeros(
                (self._screen_h, self._screen_w, 3), dtype=np.uint8,
            )]

        messages = build_global_reflector_messages(
            goal=self._goal,
            plan=self._current_plan or "",
            step_history=self._step_history,
            progress=self._progress,
            recent_screenshots=recent_screenshots,
            resized_w=self._resized_w,
            resized_h=self._resized_h,
            min_pixels=self.mu_cfg["min_pixels"],
            max_pixels=self.mu_cfg["max_pixels"],
        )
        try:
            response = await self._auxiliary_generate(messages)
            result, reason = parse_global_reflector_response(response)
            self._last_global_reason = reason
            return result
        except Exception as e:
            print(f"[MobileUse GlobalReflector] Error: {e}")
            self._last_global_reason = str(e)
            return "Uncertain"

    # ------------------------------------------------------------------
    # Step history management
    # ------------------------------------------------------------------

    def _record_step_history(
        self,
        step_idx: int,
        thought: str,
        action_dict: Dict,
        action_str: str,
        action_desc: str,
    ) -> None:
        """Record a step in the MobileUse-specific history."""
        entry = {
            "step_idx": step_idx,
            "thought": thought,
            "action_name": action_dict.get("action", ""),
            "action_dict": action_dict,
            "action_str": action_str,
            "action_desc": action_desc,
            "reflection_outcome": (
                self._last_reflection.get("outcome") if self._last_reflection else None
            ),
            "reflection_error": (
                self._last_reflection.get("error") if self._last_reflection else None
            ),
            "traj_reflection_outcome": (
                self._last_traj_reflection.get("outcome") if self._last_traj_reflection else None
            ),
            "traj_reflection_error": (
                self._last_traj_reflection.get("error") if self._last_traj_reflection else None
            ),
        }
        self._step_history.append(entry)
