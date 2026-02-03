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
# Import utilities (pure functions extracted for testability)
from .utils import (
    init_messages,
    select_messages,
    load_content,
    numpy_to_base64,
    parse_uitars_action,
    add_box_token,
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
    Single container for all trajectory data.
    
    Used both during execution AND as final output.
    Replaces scattered self.xxx variables with one cohesive container.
    """
    # Identity
    instance_id: str
    trajectory_id: str
    
    # Core data (source of truth)
    messages: List[Dict] = field(default_factory=list)
    images: List[np.ndarray] = field(default_factory=list)
    
    # Training tensors (accumulated)
    input_ids: Optional[torch.Tensor] = None
    labels: Optional[torch.Tensor] = None
    attention_mask: Optional[torch.Tensor] = None
    pixel_values: Optional[torch.Tensor] = None
    image_grid_thw: Optional[torch.Tensor] = None
    
    # Tracking
    step_count: int = 0
    prompt_token_len: int = 0
    processed_until: int = 0  # For incremental training tensor processing
    
    # Result
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
        self.max_pixels = getattr(traj_config, 'max_pixels', 1003520)
        self.min_pixels = getattr(traj_config, 'min_pixels', 3136)
        
        # Unique agent ID for inference
        self.agent_id = uuid4().hex
        
        # Single state container (replaces scattered self.xxx)
        self.state = TrajectoryState(
            instance_id=traj_config.instance_id,
            trajectory_id=traj_config.trajectory_id,
            input_ids=torch.zeros((0,), dtype=torch.int64),
            labels=torch.full((0,), -100, dtype=torch.int64),
            attention_mask=torch.zeros((0,), dtype=torch.int64),
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
            response: Raw assistant response
            
        Returns:
            New message list with assistant message appended
        """
        formatted_response = add_box_token(response)
        return messages + [{
            "role": "assistant",
            "content": [{"type": "text", "text": formatted_response}]
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
    
    # === TRAINING TENSOR PROCESSING ===
    
    def process_for_training(self, messages: List[Dict]) -> Dict[str, Any]:
        """
        Process messages into training tensors.
        
        Converts OpenAI-format messages into tokenized tensors for VLM training.
        Each message is processed individually, then concatenated. Labels are set
        to -100 for system/user (masked in loss), actual tokens for assistant (learned).
        
        Args:
            messages: Messages to process (already selected by caller via select_messages)
            
        Returns:
            Dict with input_ids, labels, attention_mask, pixel_values, image_grid_thw
        """
        try:
            from qwen_vl_utils import process_vision_info
        except ImportError:
            return {}
        
        if self.processor is None:
            return {}
        
        # === Step 1: Extract images from all messages ===
        # Fail loudly if image processing fails - silent failures produce corrupted training data
        image_inputs, video_inputs, video_kwargs = process_vision_info(
            messages, return_video_kwargs=True
        )
        
        # Per-message accumulators
        input_ids_list = []
        labels_list = []
        attention_mask_list = []
        
        # Image tracking: process_vision_info returns all images flattened,
        # we slice them per-message based on how many <|image_pad|> each has
        image_count = 0
        pixel_values_list = []
        image_grid_thw_list = []
        
        # === Step 2: Process each message individually ===
        for msg in messages:
            role = msg['role']
            # load_content: text → text, image → "<|vision_start|><|image_pad|><|vision_end|>"
            content = load_content(msg['content'])
            # Format as ChatML: <|im_start|>role\ncontent<|im_end|>\n
            prompt = f'<|im_start|>{role}\n' + content + '<|im_end|>\n'
            
            # === Step 2a: Tokenize with VLM processor ===
            # The processor expands <|image_pad|> into actual image token sequences
            cur_image_num = prompt.count("<|image_pad|>")
            if cur_image_num > 0:
                # Pass corresponding images for this message
                result = self.processor(
                    image_inputs[image_count:image_count + cur_image_num],
                    [prompt],
                    add_special_tokens=False,
                    return_tensors="pt"
                )
                image_count += cur_image_num
            else:
                # Text-only message
                result = self.processor(
                    None,
                    [prompt],
                    add_special_tokens=False,
                    return_tensors="pt"
                )
            
            cur_input_ids = result.pop('input_ids')[0]
            cur_attention_mask = result.pop('attention_mask')[0]
            
            # Collect image embeddings if present
            if 'pixel_values' in result:
                pixel_values_list.append(result["pixel_values"])
            if 'image_grid_thw' in result:
                image_grid_thw_list.append(result["image_grid_thw"])
            
            input_ids_list.append(cur_input_ids)
            attention_mask_list.append(cur_attention_mask)
            
            # === Step 2b: Create labels for training ===
            # system/user → -100 (ignored in loss, model doesn't learn these)
            # assistant  → actual tokens (model learns to predict these)
            if role in ["system", "user"]:
                labels_list.append(torch.full_like(cur_input_ids, -100))
            else:
                labels_list.append(cur_input_ids)
        
        # === Step 3: Concatenate all messages into single tensors ===
        result = {}
        if input_ids_list:
            result["input_ids"] = torch.cat(input_ids_list, dim=0)
            result["labels"] = torch.cat(labels_list, dim=0)
            result["attention_mask"] = torch.cat(attention_mask_list, dim=0)
        
        if pixel_values_list:
            result["pixel_values"] = torch.cat(pixel_values_list, dim=0)
        
        if image_grid_thw_list:
            result["image_grid_thw"] = torch.cat(image_grid_thw_list, dim=0)
        
        return result
    
    def accumulate_tensors(self, new_tensors: Dict[str, Any]) -> None:
        """
        Accumulate new tensors into state.
        
        Args:
            new_tensors: Dict from process_for_training()
        """
        if not new_tensors:
            return
        
        if "input_ids" in new_tensors:
            self.state.input_ids = torch.cat([self.state.input_ids, new_tensors["input_ids"]], dim=0)
            self.state.labels = torch.cat([self.state.labels, new_tensors["labels"]], dim=0)
            self.state.attention_mask = torch.cat([self.state.attention_mask, new_tensors["attention_mask"]], dim=0)
        
        if "pixel_values" in new_tensors:
            if self.state.pixel_values is None:
                self.state.pixel_values = new_tensors["pixel_values"]
            else:
                self.state.pixel_values = torch.cat([self.state.pixel_values, new_tensors["pixel_values"]], dim=0)
        
        if "image_grid_thw" in new_tensors:
            if self.state.image_grid_thw is None:
                self.state.image_grid_thw = new_tensors["image_grid_thw"]
            else:
                self.state.image_grid_thw = torch.cat([self.state.image_grid_thw, new_tensors["image_grid_thw"]], dim=0)
    
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
        initial_tensors = self.process_for_training(self.state.messages)
        self.accumulate_tensors(initial_tensors)
        self.state.prompt_token_len = len(self.state.input_ids)
        self.state.processed_until = len(self.state.messages)
        
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
        
        # 1. Select messages for LLM (explicit selection)
        selected_messages = select_messages(self.state.messages, mode="full")
        
        # 2. Prepare input
        input_ids = self.prepare_input_ids(selected_messages)
        
        # 2b. Extract images for VLM inference (required for Qwen2-VL with vLLM V1)
        image_data = self.extract_images_for_inference(selected_messages)
        
        # Check context window
        response_token_len = len(input_ids) - self.state.prompt_token_len
        if response_token_len >= self.max_prompt_length:
            self.state.is_done = True
            return True, "CONTEXT_WINDOW_EXCEEDED", None
        
        # 3. Generate response
        sampling_params = copy.deepcopy(self.sampling_params)
        sampling_params["max_tokens"] = self.max_prompt_length - response_token_len
        
        if DEBUG_TIMING:
            num_images = len(image_data) if image_data else 0
            print(f"[Context] step={self.state.step_count} tokens={len(input_ids)} images={num_images}")
            vllm_start = time.perf_counter()
        
        response_str, stop_reason = await self.infer_engine.async_generate_ids(
            input_ids=input_ids,
            sampling_params=sampling_params,
            request_id=self.agent_id,
            image_data=image_data,
        )
        
        if DEBUG_TIMING:
            vllm_elapsed = time.perf_counter() - vllm_start
        
        # Check for length stop
        if stop_reason == "length":
            print(f"[AndroidAgent] Stopping reason: {stop_reason}. Stopping agent.")
            self.state.messages = self.append_assistant(self.state.messages, response_str)
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
            # Process only new messages for training
            train_messages = select_messages(
                self.state.messages,
                mode="incremental",
                start_idx=self.state.processed_until
            )
            new_tensors = self.process_for_training(train_messages)
            self.accumulate_tensors(new_tensors)
            self.state.processed_until = len(self.state.messages)
            
            finish_reason = "FINISH" if terminated else "TRUNCATED"
            return True, finish_reason, self.state.reward
        
        # 7. Append new observation
        image = output.get("image")
        if image is None:
            self.state.is_done = True
            # Process only new messages for training
            train_messages = select_messages(
                self.state.messages,
                mode="incremental",
                start_idx=self.state.processed_until
            )
            new_tensors = self.process_for_training(train_messages)
            self.accumulate_tensors(new_tensors)
            self.state.processed_until = len(self.state.messages)
            return True, "NO_SCREENSHOT", None
        
        # Update state with observation (EXPLICIT assignment)
        self.state.messages = self.append_observation(self.state.messages, image)
        self.state.images.append(image)
        
        # 8. Process for training (EXPLICIT: select then process)
        train_messages = select_messages(
            self.state.messages,
            mode="incremental",
            start_idx=self.state.processed_until
        )
        new_tensors = self.process_for_training(train_messages)
        self.accumulate_tensors(new_tensors)
        self.state.processed_until = len(self.state.messages)
        
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
        
        Refactored from EnvWorker.get_train_dict() lines 296-325.
        """
        try:
            from verl.models.transformers.qwen2_vl import get_rope_index
            import verl.utils.torch_functional as VF
            
            position_ids = get_rope_index(
                self.processor,
                input_ids=self.state.input_ids,
                image_grid_thw=self.state.image_grid_thw,
                attention_mask=self.state.attention_mask,
            )
            
            # Postprocess input_ids and attention_mask (padding/truncation)
            # VF.postprocess_data expects 2D tensors [batch, seq]
            input_ids_2d = self.state.input_ids.unsqueeze(0) if self.state.input_ids.dim() == 1 else self.state.input_ids
            attention_mask_2d = self.state.attention_mask.unsqueeze(0) if self.state.attention_mask.dim() == 1 else self.state.attention_mask
            
            input_ids_2d, attention_mask_2d = VF.postprocess_data(
                input_ids=input_ids_2d,
                attention_mask=attention_mask_2d,
                max_length=self.max_prompt_length,
                pad_token_id=self.tokenizer.pad_token_id,
                left_pad=True,
                truncation='right',
            )
            
            # Squeeze back to 1D
            input_ids = input_ids_2d.squeeze(0)
            attention_mask = attention_mask_2d.squeeze(0)
            
            # Handle position_ids and labels separately with same padding
            seq_len = input_ids.shape[0]
            orig_len = position_ids.shape[1] if position_ids.dim() > 1 else position_ids.shape[0]
            
            if seq_len > orig_len:
                # Pad position_ids (left pad with 0s)
                pad_len = seq_len - orig_len
                if position_ids.dim() > 1:
                    position_ids = torch.cat([
                        torch.zeros((position_ids.shape[0], pad_len), dtype=position_ids.dtype),
                        position_ids
                    ], dim=1)
                else:
                    position_ids = torch.cat([
                        torch.zeros(pad_len, dtype=position_ids.dtype),
                        position_ids
                    ])
            elif seq_len < orig_len:
                # Truncate from right
                if position_ids.dim() > 1:
                    position_ids = position_ids[:, :seq_len]
                else:
                    position_ids = position_ids[:seq_len]
            
            # Handle labels similarly
            labels = self.state.labels
            if labels is not None:
                orig_label_len = labels.shape[0]
                if seq_len > orig_label_len:
                    pad_len = seq_len - orig_label_len
                    labels = torch.cat([
                        torch.full((pad_len,), -100, dtype=labels.dtype),
                        labels
                    ])
                elif seq_len < orig_label_len:
                    labels = labels[:seq_len]
            
            data = {
                'input_ids': input_ids,
                'labels': labels,
                'position_ids': position_ids,
                'attention_mask': attention_mask,
            }
            
            if self.state.pixel_values is not None:
                data['multi_modal_inputs'] = {
                    'pixel_values': self.state.pixel_values,
                    'image_grid_thw': self.state.image_grid_thw,
                }
            
            return data
            
        except ImportError:
            # Fallback if verl imports not available
            return {
                'input_ids': self.state.input_ids,
                'labels': self.state.labels,
                'attention_mask': self.state.attention_mask,
            }
    
    # === BACKWARD COMPATIBILITY GETTERS ===
    # These delegate to state for code that still uses old API
    
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
