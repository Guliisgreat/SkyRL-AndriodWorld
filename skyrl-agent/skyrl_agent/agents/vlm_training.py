"""
Training utilities for VLM agents.

Shared functions for processing messages into training tensors.
These are model-agnostic where possible, with VLM-specific handling for Qwen2-VL.

Key components:
- TrainingAccumulator: Encapsulates all training tensor management
- process_messages_for_vlm_training: Convert messages to training tensors
- build_vlm_train_dict: Build final training dict with position_ids
"""

import torch
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass

from skyrl_agent.agents.memory import (
    TrainingMemoryConfig,
    TrainingMemoryStrategy,
    create_training_strategy,
)


# =============================================================================
# TrainingAccumulator - Encapsulates all training complexity
# =============================================================================

@dataclass
class TrainingAccumulatorConfig:
    """Configuration for TrainingAccumulator."""
    max_tokens: int = 32768       # Token budget for training sequence
    max_length: int = 32768       # Max length for final padding
    strategy: str = "early"       # Training memory strategy: "early", "recent", "full"
    system_messages: int = 2      # Number of system messages to always keep


class TrainingAccumulator:
    """
    Encapsulates all training tensor management.
    
    Hides from agent:
    - Incremental tokenization indices
    - Response token ID caching  
    - Token budget tracking
    - Tensor accumulation
    - Memory strategy (early/recent/full)
    
    Usage:
        training = TrainingAccumulator(processor, tokenizer, config)
        training.add_initial(messages)  # Process system + first user
        
        # In step loop:
        should_add, should_continue = training.add_step(messages, response_token_ids)
        if not should_continue:
            break  # Stop trajectory
        
        # At end:
        train_dict = training.get_train_dict()
    """
    
    def __init__(
        self,
        processor: Any,
        tokenizer: Any,
        config: TrainingAccumulatorConfig,
        load_content_fn: Optional[Callable] = None,
    ):
        """
        Initialize TrainingAccumulator.
        
        Args:
            processor: VLM processor (e.g., Qwen2VLProcessor)
            tokenizer: Tokenizer for encoding text
            config: Configuration with max_tokens, max_length, strategy
            load_content_fn: Function to convert message content to text
        """
        self.processor = processor
        self.tokenizer = tokenizer
        self.config = config
        self.load_content_fn = load_content_fn
        
        # Create memory strategy
        self._strategy: TrainingMemoryStrategy = create_training_strategy(config.strategy)
        
        # Internal state (hidden from agent)
        self._train_input_ids: Optional[torch.Tensor] = None
        self._train_labels: Optional[torch.Tensor] = None
        self._train_attention_mask: Optional[torch.Tensor] = None
        self._train_pixel_values: Optional[torch.Tensor] = None
        self._train_image_grid_thw: Optional[torch.Tensor] = None
        
        # Cache for vLLM response tokens (avoids retokenization)
        self._response_token_ids_cache: List[List[int]] = []
        
        # Index tracking
        self._last_tokenized_idx: int = 0
        self._accumulated_tokens: int = 0
        
        # Per-step token counts (for "recent" strategy)
        self._step_token_counts: List[int] = []
        self._system_tokens: int = 0
        
        # All messages reference (for "recent" strategy final selection)
        self._all_messages: List[Dict] = []
        
        # Initialize empty tensors
        self._train_input_ids = torch.zeros((0,), dtype=torch.int64)
        self._train_labels = torch.full((0,), -100, dtype=torch.int64)
        self._train_attention_mask = torch.zeros((0,), dtype=torch.int64)
    
    def add_initial(self, messages: List[Dict]) -> None:
        """
        Process initial messages (system + first user).
        
        Args:
            messages: Initial messages to process
        """
        tensors = process_messages_for_vlm_training(
            messages=messages,
            processor=self.processor,
            tokenizer=self.tokenizer,
            response_token_ids_cache=None,  # No cached responses yet
            load_content_fn=self.load_content_fn,
        )
        self._accumulate(tensors)
        self._last_tokenized_idx = len(messages)
        self._accumulated_tokens = len(self._train_input_ids)
        
        # Track system tokens (for "recent" strategy budget calculation)
        self._system_tokens = self._accumulated_tokens
        self._all_messages = list(messages)
    
    def add_step(
        self,
        all_messages: List[Dict],
        response_token_ids: List[int],
    ) -> Tuple[bool, bool]:
        """
        Add one step's worth of messages for training.
        
        Uses the configured strategy to decide whether to accumulate
        and whether to continue the trajectory.
        
        Args:
            all_messages: Full message list (agent's messages)
            response_token_ids: Token IDs from vLLM for latest response
            
        Returns:
            Tuple (should_add, should_continue):
            - should_add: Whether this step was added to training
            - should_continue: Whether agent should continue trajectory
        """
        # Cache response tokens for use during tokenization
        self._response_token_ids_cache.append(response_token_ids)
        
        # Get new messages since last tokenization
        new_messages = all_messages[self._last_tokenized_idx:]
        
        if not new_messages:
            return True, True  # Nothing to add, continue
        
        # Count assistant messages before this batch to determine cache offset
        # The cache offset tells process_messages which cached tokens to use
        num_assistant_before = sum(
            1 for msg in all_messages[:self._last_tokenized_idx]
            if msg.get("role") == "assistant"
        )
        
        # Process new messages with cached tokens
        tensors = process_messages_for_vlm_training(
            messages=new_messages,
            processor=self.processor,
            tokenizer=self.tokenizer,
            response_token_ids_cache=self._response_token_ids_cache,
            cache_offset=num_assistant_before,
            load_content_fn=self.load_content_fn,
        )
        
        step_tokens = len(tensors.get("train_input_ids", []))
        
        # Use strategy to decide
        should_add, should_continue = self._strategy.should_accumulate(
            accumulated_tokens=self._accumulated_tokens,
            new_step_tokens=step_tokens,
            max_tokens=self.config.max_tokens,
        )
        
        # Track step tokens (for "recent" strategy)
        self._step_token_counts.append(step_tokens)
        self._all_messages = list(all_messages)
        
        if should_add:
            self._accumulate(tensors)
            self._accumulated_tokens += step_tokens
        
        self._last_tokenized_idx = len(all_messages)
        return should_add, should_continue
    
    def can_continue(self) -> bool:
        """Check if there's room for more tokens."""
        return self._accumulated_tokens < self.config.max_tokens
    
    def get_train_dict(self) -> Dict[str, Any]:
        """
        Build final training dict with padding and position_ids.
        
        For "recent" strategy, this re-processes selected messages to ensure
        only recent steps within budget are included.
        
        Returns:
            Dict ready for training with input_ids, labels, position_ids,
            attention_mask, and multi_modal_inputs
        """
        # For "recent" strategy, re-process selected messages
        if self.config.strategy == "recent" and self._all_messages:
            return self._build_recent_train_dict()
        
        # For "early" and "full" strategies, use accumulated tensors
        return build_vlm_train_dict(
            train_input_ids=self._train_input_ids,
            train_labels=self._train_labels,
            train_attention_mask=self._train_attention_mask,
            train_pixel_values=self._train_pixel_values,
            train_image_grid_thw=self._train_image_grid_thw,
            processor=self.processor,
            tokenizer=self.tokenizer,
            max_length=self.config.max_length,
        )
    
    def _build_recent_train_dict(self) -> Dict[str, Any]:
        """
        Build training dict for "recent" strategy.
        
        Re-processes messages to include only recent steps within budget.
        """
        # Use strategy to select message range
        start_step_idx, end_step_idx = self._strategy.select_messages(
            all_messages=self._all_messages,
            system_messages=self.config.system_messages,
            step_token_counts=self._step_token_counts,
            max_tokens=self.config.max_tokens,
            system_tokens=self._system_tokens,
        )
        
        # Convert step indices to message indices
        # System messages + selected step messages
        system_msgs = self._all_messages[:self.config.system_messages]
        step_msgs = self._all_messages[self.config.system_messages:]
        
        # Each step = 2 messages (user observation + assistant response)
        start_msg_idx = start_step_idx  # Already in message index form from strategy
        end_msg_idx = end_step_idx
        
        selected_step_msgs = step_msgs[start_msg_idx:end_msg_idx]
        selected_messages = system_msgs + selected_step_msgs
        
        if not selected_messages:
            return build_vlm_train_dict(
                train_input_ids=self._train_input_ids,
                train_labels=self._train_labels,
                train_attention_mask=self._train_attention_mask,
                train_pixel_values=self._train_pixel_values,
                train_image_grid_thw=self._train_image_grid_thw,
                processor=self.processor,
                tokenizer=self.tokenizer,
                max_length=self.config.max_length,
            )
        
        # Build cache offset for selected messages
        # Count how many assistant messages are skipped
        skipped_assistant_count = sum(
            1 for msg in step_msgs[:start_msg_idx]
            if msg.get("role") == "assistant"
        )
        
        # Re-process selected messages with proper cache offset
        tensors = process_messages_for_vlm_training(
            messages=selected_messages,
            processor=self.processor,
            tokenizer=self.tokenizer,
            response_token_ids_cache=self._response_token_ids_cache,
            cache_offset=skipped_assistant_count,
            load_content_fn=self.load_content_fn,
        )
        
        return build_vlm_train_dict(
            train_input_ids=tensors.get("train_input_ids", torch.zeros((0,), dtype=torch.int64)),
            train_labels=tensors.get("train_labels", torch.full((0,), -100, dtype=torch.int64)),
            train_attention_mask=tensors.get("train_attention_mask", torch.zeros((0,), dtype=torch.int64)),
            train_pixel_values=tensors.get("train_pixel_values"),
            train_image_grid_thw=tensors.get("train_image_grid_thw"),
            processor=self.processor,
            tokenizer=self.tokenizer,
            max_length=self.config.max_length,
        )
    
    def get_accumulated_tokens(self) -> int:
        """Return total accumulated tokens so far."""
        return self._accumulated_tokens
    
    def reset(self) -> None:
        """Reset for new trajectory."""
        self._train_input_ids = torch.zeros((0,), dtype=torch.int64)
        self._train_labels = torch.full((0,), -100, dtype=torch.int64)
        self._train_attention_mask = torch.zeros((0,), dtype=torch.int64)
        self._train_pixel_values = None
        self._train_image_grid_thw = None
        self._response_token_ids_cache = []
        self._last_tokenized_idx = 0
        self._accumulated_tokens = 0
        self._step_token_counts = []
        self._system_tokens = 0
        self._all_messages = []
    
    def _accumulate(self, tensors: Dict[str, Any]) -> None:
        """Accumulate new tensors into internal state."""
        if not tensors:
            return
        
        (
            self._train_input_ids,
            self._train_labels,
            self._train_attention_mask,
            self._train_pixel_values,
            self._train_image_grid_thw,
        ) = accumulate_tensors(
            self._train_input_ids,
            self._train_labels,
            self._train_attention_mask,
            self._train_pixel_values,
            self._train_image_grid_thw,
            tensors,
        )


# =============================================================================
# Tensor Processing Functions
# =============================================================================


def process_messages_for_vlm_training(
    messages: List[Dict],
    processor: Any,
    tokenizer: Any,
    response_token_ids_cache: Optional[List[List[int]]] = None,
    cache_offset: int = 0,
    load_content_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Process messages into training tensors for VLM models.
    
    Converts OpenAI-format messages into tokenized tensors for training.
    Each message is processed individually, then concatenated. Labels are set
    to -100 for system/user (masked in loss), actual tokens for assistant (learned).
    
    For assistant messages, uses cached token IDs if available to avoid
    retokenization drift.
    
    Args:
        messages: Messages to process (OpenAI format)
        processor: VLM processor (e.g., Qwen2VLProcessor)
        tokenizer: Tokenizer for encoding text
        response_token_ids_cache: Cached token IDs from vLLM for assistant responses
        cache_offset: Starting index in cache for this batch of messages
        load_content_fn: Function to convert message content to text with image placeholders
        
    Returns:
        Dict with train_input_ids, train_labels, train_attention_mask,
        train_pixel_values, train_image_grid_thw
    """
    try:
        from qwen_vl_utils import process_vision_info
    except ImportError:
        return {}
    
    if processor is None:
        return {}
    
    # Default load_content if not provided
    if load_content_fn is None:
        from skyrl_agent.agents.android.android_utils import load_content
        load_content_fn = load_content
    
    # === Step 1: Extract images from all messages ===
    image_inputs, video_inputs, video_kwargs = process_vision_info(
        messages, return_video_kwargs=True
    )
    
    # Per-message accumulators
    input_ids_list = []
    labels_list = []
    attention_mask_list = []
    
    # Image tracking
    image_count = 0
    pixel_values_list = []
    image_grid_thw_list = []
    
    # Track assistant messages for cache lookup
    # cache_offset tells us where in the cache this batch's assistant messages start
    assistant_idx = 0
    num_cached = len(response_token_ids_cache) if response_token_ids_cache else 0
    
    # Pre-compute ChatML framing tokens for assistant messages
    chatml_start = None
    chatml_end = None
    if num_cached > 0 and tokenizer is not None:
        chatml_start = tokenizer.encode("<|im_start|>assistant\n", add_special_tokens=False)
        chatml_end = tokenizer.encode("<|im_end|>\n", add_special_tokens=False)
    
    # === Step 2: Process each message ===
    for msg in messages:
        role = msg['role']
        
        # For assistant messages, use cached tokens if available
        cache_idx = cache_offset + assistant_idx
        if role == "assistant" and cache_idx < num_cached:
            response_tokens = response_token_ids_cache[cache_idx]
            full_tokens = chatml_start + list(response_tokens) + chatml_end
            cur_input_ids = torch.tensor(full_tokens, dtype=torch.long)
            cur_attention_mask = torch.ones_like(cur_input_ids)
            assistant_idx += 1
            
            input_ids_list.append(cur_input_ids)
            attention_mask_list.append(cur_attention_mask)
            labels_list.append(cur_input_ids.clone())
            continue
        
        # For system/user messages (or uncached assistant), tokenize with VLM processor
        content = load_content_fn(msg['content'])
        prompt = f'<|im_start|>{role}\n' + content + '<|im_end|>\n'
        
        cur_image_num = prompt.count("<|image_pad|>")
        if cur_image_num > 0:
            result = processor(
                image_inputs[image_count:image_count + cur_image_num],
                [prompt],
                add_special_tokens=False,
                return_tensors="pt"
            )
            image_count += cur_image_num
        else:
            result = processor(
                None,
                [prompt],
                add_special_tokens=False,
                return_tensors="pt"
            )
        
        cur_input_ids = result.pop('input_ids')[0]
        cur_attention_mask = result.pop('attention_mask')[0]
        
        if 'pixel_values' in result:
            pixel_values_list.append(result["pixel_values"])
        if 'image_grid_thw' in result:
            image_grid_thw_list.append(result["image_grid_thw"])
        
        input_ids_list.append(cur_input_ids)
        attention_mask_list.append(cur_attention_mask)
        
        # Labels: system/user → -100, assistant → actual tokens
        if role in ["system", "user"]:
            labels_list.append(torch.full_like(cur_input_ids, -100))
        else:
            labels_list.append(cur_input_ids)
            # If this was an uncached assistant message, increment counter
            if role == "assistant":
                assistant_idx += 1
    
    # === Step 3: Concatenate with train_ prefix ===
    result = {}
    if input_ids_list:
        result["train_input_ids"] = torch.cat(input_ids_list, dim=0)
        result["train_labels"] = torch.cat(labels_list, dim=0)
        result["train_attention_mask"] = torch.cat(attention_mask_list, dim=0)
    
    if pixel_values_list:
        result["train_pixel_values"] = torch.cat(pixel_values_list, dim=0)
    
    if image_grid_thw_list:
        result["train_image_grid_thw"] = torch.cat(image_grid_thw_list, dim=0)
    
    return result


def accumulate_tensors(
    state_train_input_ids: torch.Tensor,
    state_train_labels: torch.Tensor,
    state_train_attention_mask: torch.Tensor,
    state_train_pixel_values: Optional[torch.Tensor],
    state_train_image_grid_thw: Optional[torch.Tensor],
    new_tensors: Dict[str, Any],
) -> tuple:
    """
    Accumulate new tensors into existing state tensors.
    
    Args:
        state_train_*: Current state tensors
        new_tensors: Dict from process_messages_for_vlm_training() with train_* keys
        
    Returns:
        Tuple of (train_input_ids, train_labels, train_attention_mask,
                  train_pixel_values, train_image_grid_thw)
    """
    if not new_tensors:
        return (state_train_input_ids, state_train_labels, state_train_attention_mask,
                state_train_pixel_values, state_train_image_grid_thw)
    
    train_input_ids = state_train_input_ids
    train_labels = state_train_labels
    train_attention_mask = state_train_attention_mask
    train_pixel_values = state_train_pixel_values
    train_image_grid_thw = state_train_image_grid_thw
    
    if "train_input_ids" in new_tensors:
        train_input_ids = torch.cat([state_train_input_ids, new_tensors["train_input_ids"]], dim=0)
        train_labels = torch.cat([state_train_labels, new_tensors["train_labels"]], dim=0)
        train_attention_mask = torch.cat([state_train_attention_mask, new_tensors["train_attention_mask"]], dim=0)
    
    if "train_pixel_values" in new_tensors:
        if state_train_pixel_values is None:
            train_pixel_values = new_tensors["train_pixel_values"]
        else:
            train_pixel_values = torch.cat([state_train_pixel_values, new_tensors["train_pixel_values"]], dim=0)
    
    if "train_image_grid_thw" in new_tensors:
        if state_train_image_grid_thw is None:
            train_image_grid_thw = new_tensors["train_image_grid_thw"]
        else:
            train_image_grid_thw = torch.cat([state_train_image_grid_thw, new_tensors["train_image_grid_thw"]], dim=0)
    
    return train_input_ids, train_labels, train_attention_mask, train_pixel_values, train_image_grid_thw


def build_vlm_train_dict(
    train_input_ids: torch.Tensor,
    train_labels: torch.Tensor,
    train_attention_mask: torch.Tensor,
    train_pixel_values: Optional[torch.Tensor],
    train_image_grid_thw: Optional[torch.Tensor],
    processor: Any,
    tokenizer: Any,
    max_length: int,
) -> Dict[str, Any]:
    """
    Build final training dict with position_ids and proper padding.
    
    Args:
        train_input_ids, train_labels, train_attention_mask: Token tensors
        train_pixel_values, train_image_grid_thw: Image tensors
        processor: VLM processor for position_ids computation
        tokenizer: Tokenizer for pad_token_id
        max_length: Maximum sequence length
        
    Returns:
        Dict ready for training with input_ids, labels, position_ids,
        attention_mask, multi_modal_inputs
    """
    if processor is None:
        data = {
            'input_ids': train_input_ids,
            'labels': train_labels,
            'attention_mask': train_attention_mask,
        }
        if train_pixel_values is not None:
            data['multi_modal_inputs'] = {
                'pixel_values': train_pixel_values,
                'image_grid_thw': train_image_grid_thw,
            }
        return data

    try:
        from verl.models.transformers.qwen2_vl import get_rope_index
        import verl.utils.torch_functional as VF
        
        position_ids = get_rope_index(
            processor,
            input_ids=train_input_ids,
            image_grid_thw=train_image_grid_thw,
            attention_mask=train_attention_mask,
        )
        
        # Postprocess (padding/truncation)
        input_ids_2d = train_input_ids.unsqueeze(0) if train_input_ids.dim() == 1 else train_input_ids
        attention_mask_2d = train_attention_mask.unsqueeze(0) if train_attention_mask.dim() == 1 else train_attention_mask
        
        input_ids_2d, attention_mask_2d = VF.postprocess_data(
            input_ids=input_ids_2d,
            attention_mask=attention_mask_2d,
            max_length=max_length,
            pad_token_id=tokenizer.pad_token_id,
            left_pad=True,
            truncation='error',
        )
        
        final_input_ids = input_ids_2d.squeeze(0)
        final_attention_mask = attention_mask_2d.squeeze(0)
        
        # Align position_ids and labels with padded sequence
        seq_len = final_input_ids.shape[0]
        orig_len = position_ids.shape[1] if position_ids.dim() > 1 else position_ids.shape[0]
        
        if seq_len > orig_len:
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
            if position_ids.dim() > 1:
                position_ids = position_ids[:, :seq_len]
            else:
                position_ids = position_ids[:seq_len]
        
        # Handle labels
        final_labels = train_labels
        if train_labels is not None:
            orig_label_len = train_labels.shape[0]
            if seq_len > orig_label_len:
                pad_len = seq_len - orig_label_len
                final_labels = torch.cat([
                    torch.full((pad_len,), -100, dtype=train_labels.dtype),
                    train_labels
                ])
            elif seq_len < orig_label_len:
                final_labels = train_labels[:seq_len]
        
        data = {
            'input_ids': final_input_ids,
            'labels': final_labels,
            'position_ids': position_ids,
            'attention_mask': final_attention_mask,
        }
        
        if train_pixel_values is not None:
            data['multi_modal_inputs'] = {
                'pixel_values': train_pixel_values,
                'image_grid_thw': train_image_grid_thw,
            }
        
        return data
        
    except ImportError:
        return {
            'input_ids': train_input_ids,
            'labels': train_labels,
            'attention_mask': train_attention_mask,
        }
