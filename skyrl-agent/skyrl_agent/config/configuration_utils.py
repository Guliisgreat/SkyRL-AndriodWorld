from dataclasses import dataclass
from typing import Any, Optional


# TODO(csy): a smarter way?
def get_field_from_config(key_path, context):
    parts = key_path.split(".")
    value = context
    try:
        for part in parts:
            value = value[part]
    except (KeyError, TypeError):
        raise ValueError(f"Path '{key_path}' not found in context.")
    return value


@dataclass
class TrajectoryConfig:
    instance_id: int
    trajectory_id: int
    max_prompt_length: int = 1024
    sampling_params: Optional[Any] = None
    vision_is_active: bool = False
    qwen3_enable_thinking: bool = True
    qwen3_acc_thinking: bool = True
    max_iterations: int = 5
    tools: Optional[list] = None
    agent_cls: str = "skyrl_agent.agents.react.ReActAgent"
    profile_tools: bool = False
    debug_log: bool = False
    early_step_threshold: int = 0  # Step count threshold for early reminder
    enable_turn_reminder: bool = False
    seed: Optional[int] = None  # Environment seed. None = derive from trajectory_id
    # vLLM's max_model_len - the absolute limit for context
    # Must match actor_rollout_ref.rollout.max_model_len in shell script
    max_model_len: int = 32768
    # Buffer to leave below max_model_len for response generation
    # Larger to account for image tokens (~1300 per image)
    context_buffer: int = 4096
    # Sliding window size for inference context (number of steps)
    max_history_steps: int = 10
    # Training memory strategy: "early" (stop on budget), "recent" (sliding window), "full" (error on budget)
    training_strategy: str = "early"
    
    @property
    def context_limit_threshold(self) -> int:
        """Early stop threshold = max_model_len - buffer."""
        return self.max_model_len - self.context_buffer


# DEPR
@dataclass
class AgentConfig:
    max_iterations: int = 5
    tools: Optional[list] = None


TASK_CONFIG_REGISTRY = {"swe_bench": "swe_bench.yaml"}
