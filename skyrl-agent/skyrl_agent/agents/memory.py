"""
Memory module for agent trajectory management.

Two types of memory management:
1. Inference Memory: Sliding window for context during generation
2. Training Memory: Strategy for selecting steps for training data
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple


# =============================================================================
# INFERENCE MEMORY
# =============================================================================

@dataclass
class MemoryConfig:
    """Configuration for inference memory."""
    
    max_steps: int = 10           # Sliding window size for inference
    max_tokens: int = 28672       # Token budget (used by training)
    system_messages: int = 2      # Number of system messages to always keep


class StepMemory:
    """
    Step-based memory manager for inference.
    
    Provides sliding window for inference context (last K steps).
    
    Usage:
        memory = StepMemory(MemoryConfig(max_steps=10))
        
        # For inference - get sliding window context
        context = memory.get_inference_messages(all_messages)
    """
    
    def __init__(self, config: MemoryConfig):
        self.config = config
    
    def get_inference_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Get messages for inference with sliding window.
        
        Keeps:
        - First N messages (system + task)
        - Last K steps (each step = 2 messages: user + assistant)
        
        Args:
            messages: Full message history
            
        Returns:
            Subset of messages for inference context
        """
        # Keep system/task messages
        base = messages[:self.config.system_messages]
        
        # Get step messages (after system)
        step_messages = messages[self.config.system_messages:]
        
        # Each step = 2 messages (user observation + assistant response)
        max_step_messages = self.config.max_steps * 2
        
        if len(step_messages) > max_step_messages:
            step_messages = step_messages[-max_step_messages:]
        
        return base + step_messages


# =============================================================================
# TRAINING MEMORY STRATEGIES
# =============================================================================

@dataclass
class TrainingMemoryConfig:
    """Configuration for training memory strategy."""
    
    max_tokens: int = 32768       # Token budget for training
    system_messages: int = 2      # Number of system messages to always keep
    strategy: str = "early"       # "early", "recent", or "full"


class TrainingMemoryStrategy(ABC):
    """
    Abstract interface for training memory strategies.
    
    Strategies determine:
    1. Whether to add new steps to training data
    2. Whether the trajectory should continue
    3. Which messages to include in final training data
    """
    
    @abstractmethod
    def should_accumulate(
        self,
        accumulated_tokens: int,
        new_step_tokens: int,
        max_tokens: int,
    ) -> Tuple[bool, bool]:
        """
        Decide whether to accumulate new step.
        
        Args:
            accumulated_tokens: Tokens accumulated so far
            new_step_tokens: Tokens in the new step
            max_tokens: Maximum token budget
            
        Returns:
            (should_add, should_continue)
            - should_add: Whether to add this step to training
            - should_continue: Whether agent should continue trajectory
        """
        pass
    
    @abstractmethod
    def select_messages(
        self,
        all_messages: List[Dict],
        system_messages: int,
        step_token_counts: List[int],
        max_tokens: int,
        system_tokens: int,
    ) -> Tuple[int, int]:
        """
        Select range of messages to include in training.
        
        Args:
            all_messages: Full message history
            system_messages: Number of system messages to always keep
            step_token_counts: Token count for each step (after system)
            max_tokens: Maximum token budget
            system_tokens: Tokens used by system messages
            
        Returns:
            (start_idx, end_idx) - slice indices for step messages
        """
        pass


class EarlyStrategy(TrainingMemoryStrategy):
    """
    Keep system + task + early steps.
    Stop trajectory when budget exceeded.
    
    Training: [System][Task][Step1][Step2]...[StepK] (stops at K)
    
    Pros:
    - Captures initial reasoning and early decisions
    - Simple incremental accumulation
    
    Cons:
    - May miss final successful action sequence
    """
    
    def should_accumulate(
        self,
        accumulated_tokens: int,
        new_step_tokens: int,
        max_tokens: int,
    ) -> Tuple[bool, bool]:
        if accumulated_tokens + new_step_tokens > max_tokens:
            return False, False  # Don't add, stop trajectory
        return True, True  # Add, continue
    
    def select_messages(
        self,
        all_messages: List[Dict],
        system_messages: int,
        step_token_counts: List[int],
        max_tokens: int,
        system_tokens: int,
    ) -> Tuple[int, int]:
        # Already accumulated incrementally, include all
        return 0, len(all_messages) - system_messages


class RecentStrategy(TrainingMemoryStrategy):
    """
    Keep system + task + recent steps within budget.
    Trajectory continues even if training is truncated.
    
    Training: [System][Task]...[StepN-K]...[StepN]
    
    Pros:
    - Captures final action sequence (often successful)
    - Aligned with inference (both use sliding window)
    - Better credit assignment (recent actions → reward)
    
    Cons:
    - Loses early context and reasoning
    """
    
    def should_accumulate(
        self,
        accumulated_tokens: int,
        new_step_tokens: int,
        max_tokens: int,
    ) -> Tuple[bool, bool]:
        # Always continue trajectory, selection happens at end
        return True, True
    
    def select_messages(
        self,
        all_messages: List[Dict],
        system_messages: int,
        step_token_counts: List[int],
        max_tokens: int,
        system_tokens: int,
    ) -> Tuple[int, int]:
        # Work backwards to find recent steps that fit
        remaining_budget = max_tokens - system_tokens
        
        if not step_token_counts:
            return 0, 0
        
        # Each step is 2 messages (user + assistant)
        # step_token_counts should correspond to steps
        total_steps = len(step_token_counts)
        
        accumulated = 0
        start_step = total_steps  # Start from end
        
        for i in range(total_steps - 1, -1, -1):
            if accumulated + step_token_counts[i] <= remaining_budget:
                accumulated += step_token_counts[i]
                start_step = i
            else:
                break
        
        # Convert step index to message index
        # Each step = 2 messages
        start_msg_idx = start_step * 2
        end_msg_idx = total_steps * 2
        
        return start_msg_idx, end_msg_idx


class FullStrategy(TrainingMemoryStrategy):
    """
    Include all steps. Raise error if exceeded.
    For debugging or when trajectories are guaranteed short.
    
    Training: [System][Task][Step1]...[StepN] (all or error)
    
    Pros:
    - No data loss
    - Good for debugging
    
    Cons:
    - Fails on long trajectories
    """
    
    def should_accumulate(
        self,
        accumulated_tokens: int,
        new_step_tokens: int,
        max_tokens: int,
    ) -> Tuple[bool, bool]:
        if accumulated_tokens + new_step_tokens > max_tokens:
            raise ValueError(
                f"Training exceeds max_tokens: {accumulated_tokens + new_step_tokens} > {max_tokens}. "
                "Use 'early' or 'recent' strategy for long trajectories."
            )
        return True, True
    
    def select_messages(
        self,
        all_messages: List[Dict],
        system_messages: int,
        step_token_counts: List[int],
        max_tokens: int,
        system_tokens: int,
    ) -> Tuple[int, int]:
        return 0, len(all_messages) - system_messages


def create_training_strategy(strategy_name: str) -> TrainingMemoryStrategy:
    """
    Factory function for training memory strategies.
    
    Args:
        strategy_name: One of "early", "recent", "full"
        
    Returns:
        TrainingMemoryStrategy instance
    """
    strategies = {
        "early": EarlyStrategy,
        "recent": RecentStrategy,
        "full": FullStrategy,
    }
    if strategy_name not in strategies:
        raise ValueError(
            f"Unknown training strategy: '{strategy_name}'. "
            f"Available: {list(strategies.keys())}"
        )
    return strategies[strategy_name]()
