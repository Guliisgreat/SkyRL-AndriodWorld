"""
AndroidAgent - GUI agent for AndroidWorld following ReActAgent pattern.

This agent owns all state via TrajectoryState container, handles formatting
internally, and uses AndroidEnvTool for environment interaction.

Design Principles:
- Single source of truth: TrajectoryState holds all trajectory data
- Explicit data flow: Functions return values, assignments visible at call site
- Separate concerns: Message transformation vs memory selection vs tensor processing

Refactored from verl/trainer/mobile_agent.py
"""

import copy
import os
import time
import torch
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
from uuid import uuid4
import numpy as np

# Timing instrumentation toggle (set DEBUG_TIMING=1 to enable)
DEBUG_TIMING = os.environ.get("DEBUG_TIMING", "0") == "1"

from skyrl_agent.config.configuration_utils import TrajectoryConfig
from skyrl_agent.integrations.base import AsyncInferBackend
from skyrl_agent.tools.base import TOOL_REGISTRY
from skyrl_agent.agents.memory import StepMemory, MemoryConfig
from skyrl_agent.agents.vlm_training import (
    TrainingAccumulator,
    TrainingAccumulatorConfig,
)
# Import utilities (pure functions extracted for testability)
from .android_utils import (
    init_messages,
    load_content,
    numpy_to_base64,
    parse_uitars_action,
)


# Refactored from mobile_agent.py lines 20-45
UITARS_USR_PROMPT_THOUGHT = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task. 

## Output Format
```
Thought: ...
Action: ...
```

## Action Space
click(start_box='<|box_start|>(x1,y1)<|box_end|>')
long_press(start_box='<|box_start|>(x1,y1)<|box_end|>', time='')
type(content='') # If you want to submit your input, use "\\n" at the end of `content`.
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x3,y3)<|box_end|>')
press_home()
press_back()
open_app(content='') # Open an app specified by `content`.
finished(content='') # Submit the task regardless of whether it succeeds or fails.
answer(content='') # Answer user's question.

## Note
- Use English in `Thought` and `Action` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.

## User Instruction
{instruction}
"""


# === STATE CONTAINER ===

@dataclass
class TrajectoryState:
    """
    Single container for trajectory data.
    
    Used both during execution AND as final output.
    Training tensors are now managed by TrainingAccumulator.
    """
    # === Identity ===
    instance_id: str
    trajectory_id: str
    
    # === Conversation (for inference) ===
    messages: List[Dict] = field(default_factory=list)  # Full message history
    images: List[np.ndarray] = field(default_factory=list)  # Screenshot history
    
    # === Tracking ===
    step_count: int = 0
    
    # === Result ===
    is_done: bool = False
    finish_reason: str = ""
    reward: float = 0.0
    format_reward: float = 0.0


class AndroidAgent:
    """
    Android GUI agent following ReActAgent pattern.
    
    Design:
    - Owns all state via self.state: TrajectoryState
    - Message functions return new values (explicit data flow)
    - Memory selection is explicit via select_messages()
    - Single get_state() getter for trajectory to retrieve results
    """
    
    def __init__(
        self,
        traj_config: TrajectoryConfig,
        infer_engine: AsyncInferBackend,
        tokenizer: Any,
        processor: Any,
        env_handle: Any,
    ) -> None:
        """
        Initialize AndroidAgent.
        
        Args:
            traj_config: Trajectory configuration
            infer_engine: Async inference backend
            tokenizer: Tokenizer for chat template
            processor: VLM processor for image processing
            env_handle: Environment handle for action execution
        """
        self.infer_engine = infer_engine
        self.tokenizer = tokenizer
        self.processor = processor
        self.env_handle = env_handle
        
        # Config from traj_config
        self.sampling_params = traj_config.sampling_params
        self.max_prompt_length = traj_config.max_prompt_length
        self.max_iterations = traj_config.max_iterations
        self.max_pixels = getattr(traj_config, 'max_pixels', 564480)
        self.min_pixels = getattr(traj_config, 'min_pixels', 78400)
        
        # Unique agent ID for inference
        self.agent_id = uuid4().hex
        
        # Single state container (replaces scattered self.xxx)
        self.state = TrajectoryState(
            instance_id=traj_config.instance_id,
            trajectory_id=traj_config.trajectory_id,
        )
        
        # Memory module for sliding window (inference context)
        max_history_steps = getattr(traj_config, 'max_history_steps', 10)
        self.memory = StepMemory(MemoryConfig(
            max_steps=max_history_steps,
            max_tokens=self.max_prompt_length,
            system_messages=2,  # System + task
        ))
        
        # Training accumulator (encapsulates all training tensor management)
        training_strategy = getattr(traj_config, 'training_strategy', 'early')
        self.training = TrainingAccumulator(
            processor=self.processor,
            tokenizer=self.tokenizer,
            config=TrainingAccumulatorConfig(
                max_tokens=self.max_prompt_length,
                max_length=self.max_prompt_length,
                strategy=training_strategy,
                system_messages=2,  # System + task
            ),
            load_content_fn=load_content,
        )
        
        # Register tool
        self.tools = {}
        self._register_tools(["android_env"])
    
    def _register_tools(self, tools: List[str]) -> None:
        """Register tools (same pattern as ReActAgent)."""
        for name in tools:
            if name not in TOOL_REGISTRY:
                raise ValueError(f"Unknown tool '{name}'. Available: {list(TOOL_REGISTRY.keys())}")
            tool = TOOL_REGISTRY[name]()
            self.tools[tool.name] = tool
    
    # === AGENT-SPECIFIC PROMPT FORMATTING ===
    
    def format_initial_instruction(
        self,
        template_messages: List[Dict],
        observation: Dict,
        task,
    ) -> List[Dict]:
        """
        Format initial instruction with agent-specific prompt template.
        
        This method allows each agent type to apply its own prompt formatting.
        AndroidAgent uses UITARS_USR_PROMPT_THOUGHT template.
        
        Args:
            template_messages: System prompt from Task.get_instruction()
            observation: Raw observation from env.reset()
            task: Task instance for format_observation helper
        
        Returns:
            Complete initial instruction messages
        """
        def prompt_formatter(task_instruction: str) -> str:
            return UITARS_USR_PROMPT_THOUGHT.format(instruction=task_instruction)
        
        observation_messages = task.format_observation(
            observation,
            prompt_formatter=prompt_formatter,
            min_pixels=self.min_pixels,
            max_pixels=self.max_pixels,
        )
        
        return template_messages + observation_messages
    
    # === MESSAGE TRANSFORMATION (explicit returns) ===
    
    def append_assistant(self, messages: List[Dict], response: str) -> List[Dict]:
        """
        Append assistant message to messages.
        
        Args:
            messages: Current message list
            response: Assistant response (with box tokens preserved from vLLM)
            
        Returns:
            New message list with assistant message appended
        """
        # Response already has box tokens (skip_special_tokens=False), no add_box_token needed
        return messages + [{
            "role": "assistant",
            "content": [{"type": "text", "text": response}]
        }]
    
    def append_observation(self, messages: List[Dict], image: np.ndarray) -> List[Dict]:
        """
        Append observation (screenshot) to messages.
        
        Args:
            messages: Current message list
            image: Screenshot as numpy array
            
        Returns:
            New message list with observation appended
        """
        image_base64 = numpy_to_base64(image)
        return messages + [{
            "role": "user",
            "content": [{
                "type": "image",
                "image": f"data:image/png;base64,{image_base64}",
                "min_pixels": self.min_pixels,
                "max_pixels": self.max_pixels,
            }]
        }]
    
    # === TOKENIZATION (explicit input/output) ===
    
    def prepare_input_ids(self, messages: List[Dict]) -> List[int]:
        """
        Tokenize messages for LLM input.
        
        Args:
            messages: Messages to tokenize
            
        Returns:
            Token IDs ready for generation
        """
        return self.tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
        )
    
    def extract_images_for_inference(self, messages: List[Dict]) -> Optional[List[Any]]:
        """
        Extract images from messages for vLLM inference.
        
        Delegates to the agnostic utility function in skyrl_agent.functional.utils.
        For VLM models like Qwen2-VL, images must be passed separately to vLLM.
        
        Args:
            messages: Messages containing image content
            
        Returns:
            List of PIL images, or None if no images found
        """
        from skyrl_agent.functional.utils import extract_images_from_messages
        return extract_images_from_messages(messages)
    
    # === MAIN LOOP (explicit data flow) ===
    
    async def run(self, instruction: List[Dict]) -> Tuple[str, Any]:
        """
        Run agent from initial instruction until done.
        
        Args:
            instruction: Initial messages in OpenAI format (from Task.get_instruction)
        
        Returns:
            (finish_reason, result)
        """
        # Initialize state (explicit assignment)
        self.state.messages = init_messages(instruction)
        self.state.images = []
        
        # Process initial messages for training
        self.training.add_initial(self.state.messages)
        
        result = None
        
        while self.state.step_count < self.max_iterations and not self.state.is_done:
            try:
                done, finish_reason, result = await self.step()
                if done:
                    self.state.finish_reason = finish_reason
                    break
            except Exception as e:
                # Import here to avoid circular dependency
                from skyrl_agent.runtime.android.exceptions import ContainerDeadError
                
                # Re-raise ContainerDeadError - dispatcher needs to handle container replacement
                if isinstance(e, ContainerDeadError):
                    print(f"[AndroidAgent] Container dead for instance={self.state.instance_id} traj={self.state.trajectory_id}: {e}")
                    raise
                
                # Application errors (deterministic) - fail gracefully, don't retry
                if isinstance(e, (IndexError, ValueError, KeyError)):
                    self.state.finish_reason = f"error_application: {type(e).__name__}: {str(e)}"
                    print(f"[AndroidAgent] Application error (non-retryable): {e}")
                    import traceback
                    traceback.print_exc()
                    break
                
                # Other runtime errors - log and break
                self.state.finish_reason = f"error_runtime: {str(e)}"
                print(f"[AndroidAgent Error] instance={self.state.instance_id} traj={self.state.trajectory_id}: {e}")
                import traceback
                traceback.print_exc()
                break
        else:
            # Exited loop without break - max iterations reached
            self.state.finish_reason = "max_iterations_reached"
        
        return self.state.finish_reason, result
    
    async def step(self) -> Tuple[bool, Optional[str], Any]:
        """
        Single step: generate -> parse -> execute via tool -> update state.
        
        Returns:
            (done, finish_reason, result)
        """
        self.state.step_count += 1
        print(f"[AndroidAgent Step {self.state.step_count}] instance={self.state.instance_id} traj={self.state.trajectory_id}")
        
        # 1. Select messages for LLM (sliding window via memory module)
        selected_messages = self.memory.get_inference_messages(self.state.messages)
        
        # 2. Prepare inference input_ids (tokenized prompt for vLLM)
        inference_input_ids = self.prepare_input_ids(selected_messages)
        
        # 2b. Extract images for VLM inference (required for Qwen2-VL with vLLM V1)
        image_data = self.extract_images_for_inference(selected_messages)
        
        # 3. Generate response
        sampling_params = copy.deepcopy(self.sampling_params)
        # Pop max_tokens to avoid duplicate keyword in vLLM SamplingParams(max_tokens=..., **sampling_params).
        # Server sets max_tokens from config; do not pass it in the dict.
        sampling_params.pop("max_tokens", None)
        
        if DEBUG_TIMING:
            num_images = len(image_data) if image_data else 0
            print(f"[Context] step={self.state.step_count} tokens={len(inference_input_ids)} images={num_images}")
            vllm_start = time.perf_counter()
        
        # Generate response from vLLM with token IDs for training
        # With skip_special_tokens=False, box tokens are preserved in response_str
        # We use the actual token IDs for training to avoid retokenization drift
        result = await self.infer_engine.async_generate_ids(
            input_ids=inference_input_ids,
            sampling_params=sampling_params,
            request_id=self.agent_id,
            image_data=image_data,
            return_token_ids=True,
        )
        
        response_str, stop_reason, _prompt_token_ids, response_token_ids = result
        
        if DEBUG_TIMING:
            vllm_elapsed = time.perf_counter() - vllm_start
        
        # Check for length stop
        if stop_reason == "length":
            print(f"[AndroidAgent] Stopping reason: {stop_reason}. Stopping agent.")
            self.state.messages = self.append_assistant(self.state.messages, response_str)
            self.training.add_step(self.state.messages, response_token_ids)  # Best effort, ignore return
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None
        
        # 4. Parse action
        try:
            action_dict, thought = parse_uitars_action(response_str)
            self.state.format_reward = 0.0
        except Exception as e:
            print(f"[AndroidAgent] Parse error: {e}")
            print(f"[AndroidAgent] Raw response: {response_str[:500]}")
            self.state.format_reward = -1.0
            action_dict = {"action_type": "status", "goal_status": "infeasible"}
            thought = f"Parse error: {response_str[:200]}"
        
        # 5. Execute via AndroidEnvTool (use async_call to avoid asyncio nesting issues)
        tool = self.tools["android_env"]
        
        if DEBUG_TIMING:
            container_start = time.perf_counter()
        
        output = await tool.async_call(
            action_dict,
            env_handle=self.env_handle,
            thought=thought,
        )
        
        if DEBUG_TIMING:
            container_elapsed = time.perf_counter() - container_start
            print(f"[Timing] step={self.state.step_count} vLLM={vllm_elapsed:.2f}s container={container_elapsed:.2f}s total={vllm_elapsed+container_elapsed:.2f}s")
        
        self.state.reward = output.get("reward", 0.0)
        terminated = output.get("terminated", False)
        truncated = output.get("truncated", False)
        
        # 6. Update messages (EXPLICIT assignment)
        self.state.messages = self.append_assistant(self.state.messages, response_str)
        
        if terminated or truncated:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)  # Best effort, ignore return
            finish_reason = "FINISH" if terminated else "TRUNCATED"
            return True, finish_reason, self.state.reward
        
        # 7. Append new observation
        image = output.get("image")
        if image is None:
            self.state.is_done = True
            self.training.add_step(self.state.messages, response_token_ids)  # Best effort, ignore return
            return True, "NO_SCREENSHOT", None
        
        # Update state with observation
        self.state.messages = self.append_observation(self.state.messages, image)
        self.state.images.append(image)
        
        # 8. Add step to training accumulator - stop if strategy says to stop
        _should_add, should_continue = self.training.add_step(self.state.messages, response_token_ids)
        if not should_continue:
            self.state.is_done = True
            return True, "TRAINING_BUDGET_EXCEEDED", None
        
        return False, None, None
    
    # === SINGLE GETTER (for Trajectory to retrieve) ===
    
    def get_state(self) -> TrajectoryState:
        """
        Return complete trajectory state.
        
        Single method to retrieve all state - replaces multiple getters.
        """
        return self.state
    
    def get_train_dict(self) -> Dict[str, torch.Tensor]:
        """
        Return training tensors with position_ids computed.
        
        Delegates to TrainingAccumulator for VLM training dict construction.
        """
        return self.training.get_train_dict()
    
    # === BACKWARD COMPATIBILITY METHODS ===
    # These delegate to training/state for code that still uses old API
    
    def process_for_training(self, messages: List[Dict]) -> Dict[str, Any]:
        """
        Process messages into training tensors (backward compatible).
        
        Delegates to training_utils.process_messages_for_vlm_training().
        Returns dict with legacy key names for compatibility.
        
        Args:
            messages: Messages to process
            
        Returns:
            Dict with input_ids, labels, attention_mask, pixel_values, image_grid_thw
        """
        from skyrl_agent.agents.vlm_training import process_messages_for_vlm_training
        result = process_messages_for_vlm_training(
            messages=messages,
            processor=self.processor,
            tokenizer=self.tokenizer,
            response_token_ids_cache=self.training._response_token_ids_cache,
            load_content_fn=load_content,
        )
        # Remap keys for backward compatibility
        return {
            "input_ids": result.get("train_input_ids"),
            "labels": result.get("train_labels"),
            "attention_mask": result.get("train_attention_mask"),
            "pixel_values": result.get("train_pixel_values"),
            "image_grid_thw": result.get("train_image_grid_thw"),
        }
    
    def accumulate_tensors(self, new_tensors: Dict[str, Any]) -> None:
        """
        Accumulate tensors (backward compatible).
        
        Delegates to training._accumulate(). Accepts legacy key names.
        
        Args:
            new_tensors: Dict from process_for_training() with legacy or new keys
        """
        # Remap legacy keys to new keys if needed
        remapped = {}
        for old_key, new_key in [
            ("input_ids", "train_input_ids"),
            ("labels", "train_labels"),
            ("attention_mask", "train_attention_mask"),
            ("pixel_values", "train_pixel_values"),
            ("image_grid_thw", "train_image_grid_thw"),
        ]:
            if old_key in new_tensors:
                remapped[new_key] = new_tensors[old_key]
            elif new_key in new_tensors:
                remapped[new_key] = new_tensors[new_key]
        self.training._accumulate(remapped)
    
    def get_messages(self) -> List[Dict]:
        """Return conversation history (backward compatible)."""
        return self.state.messages
    
    def get_history_images(self) -> List[Any]:
        """Return screenshot history (backward compatible)."""
        return self.state.images
    
    def get_reward(self) -> float:
        """Return reward (backward compatible)."""
        return self.state.reward
    
    def get_format_reward(self) -> float:
        """Return format reward (backward compatible)."""
        return self.state.format_reward
