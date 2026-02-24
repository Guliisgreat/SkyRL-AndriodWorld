"""
Structured output records for agent trajectories.

Provides dataclasses for tracking step and trajectory metadata,
including token counts for debugging and analysis.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
import json


@dataclass
class StepRecord:
    """Record of a single agent step."""
    
    step_idx: int
    thought: str
    action_type: str
    action_params: Dict[str, Any]
    raw_response: str = ""
    
    # Observation context
    a11y_tree: Optional[str] = None
    screenshot_path: Optional[str] = None
    command_output: Optional[str] = None
    
    # Token counts (this step only)
    input_tokens: int = 0       # Prompt tokens for this step
    output_tokens: int = 0      # Generated tokens for this step
    image_tokens: int = 0       # Image tokens in observation
    
    # Outcome
    success: bool = True
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class TrajectoryRecord:
    """Complete trajectory record with token tracking."""
    
    # Identity
    instance_id: str
    trajectory_id: str
    task_instruction: str
    
    # Steps
    steps: List[StepRecord] = field(default_factory=list)
    num_steps: int = 0
    
    # Outcome
    finish_reason: str = ""     # "FINISH", "CONTEXT_WINDOW_EXCEEDED", etc.
    reward: float = 0.0
    success: bool = False
    
    # Token counts (aggregated)
    total_prompt_tokens: int = 0
    total_response_tokens: int = 0
    total_image_tokens: int = 0
    total_tokens: int = 0       # prompt + response (image tokens included in prompt)
    
    def add_step(self, step: StepRecord) -> None:
        """Add a step record and update counts."""
        self.steps.append(step)
        self.num_steps = len(self.steps)
        self.total_prompt_tokens += step.input_tokens
        self.total_response_tokens += step.output_tokens
        self.total_image_tokens += step.image_tokens
        self.total_tokens = self.total_prompt_tokens + self.total_response_tokens
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = asdict(self)
        d["steps"] = [s.to_dict() for s in self.steps]
        return d
    
    def save(self, path: str) -> None:
        """Save trajectory to JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, path: str) -> "TrajectoryRecord":
        """Load trajectory from JSON file."""
        with open(path) as f:
            data = json.load(f)
        steps_data = data.pop("steps", [])
        steps = [StepRecord(**s) for s in steps_data]
        record = cls(**data)
        record.steps = steps
        return record
