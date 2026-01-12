"""
AndroidTrajectory - Trajectory management for Android agent.

Follows ReActTrajectory pattern: orchestrates lifecycle and retrieves
all state from Agent via getters.
"""

from typing import Dict, Any, Optional

from skyrl_agent.agents.base import BaseTrajectory
from skyrl_agent.agents.android.android_agent import AndroidAgent


class AndroidTrajectory(BaseTrajectory):
    """
    Trajectory for Android agent. Follows ReActTrajectory pattern.
    
    Orchestrates the trajectory lifecycle (init, generate, evaluate) and
    retrieves all state from Agent via getters.
    """
    
    def __init__(self, cfg, data, infer_engine, tokenizer, task):
        """
        Initialize AndroidTrajectory.
        
        Args:
            cfg: Trajectory configuration
            data: Instance data for this trajectory
            infer_engine: Async inference backend
            tokenizer: Tokenizer for chat template
            task: Task instance (AndroidTask)
        """
        super().__init__(cfg, data, infer_engine, tokenizer, task)
        
        # Set by runner before initialize_trajectory
        self.env_id: Optional[int] = None
        self.env_handle: Optional[Any] = None
        self.processor: Optional[Any] = None
        
        # Agent instance created during generate
        self.agent: Optional[AndroidAgent] = None
        
        # Stored during initialize for generate
        self.initial_instruction = None
        self.initial_observation = None
    
    async def initialize_trajectory(self):
        """
        Reset environment and get initial observation.
        
        Builds initial instruction by combining:
        1. Template messages from Task.get_instruction(instance)
        2. Observation messages from Task.format_observation(observation)
        """
        # 1. Get template from task (no observation needed)
        template_messages = self.task.get_instruction(self.data["instance"])
        
        # 2. Reset environment and get observation
        payload = self._build_reset_payload()
        observation, info = await self.env_handle.reset(payload)
        self.initial_observation = observation
        
        # 3. Format observation via task
        observation_messages = self.task.format_observation(observation)
        
        # 4. Combine: template + observation
        self.initial_instruction = template_messages + observation_messages
        
        # Store initial image in history if available
        if observation and observation.get("image") is not None:
            # Will be properly tracked by agent
            pass
    
    async def generate_trajectory(self):
        """
        Create agent, run trajectory, and retrieve state via getters.
        """
        # Create agent (agent will own all state)
        self.agent = AndroidAgent(
            traj_config=self.cfg,
            infer_engine=self.infer_engine,
            tokenizer=self.tokenizer,
            processor=self.processor,
            env_handle=self.env_handle,
        )
        
        # Run agent with formatted instruction
        finish_reason, result = await self.agent.run(self.initial_instruction)
        
        # Retrieve state from agent (single get_state() call)
        state = self.agent.get_state()
        
        self.result = {
            "instance_id": state.instance_id,
            "trajectory_id": state.trajectory_id,
            "messages": state.messages,
            "history_images": state.images,
            "train_dict": self.agent.get_train_dict(),  # Needs position_ids computation
            "results": result,
            "finish_reason": state.finish_reason,
            "reward": state.reward,
            "format_reward": state.format_reward,
            "state": {},
        }
    
    async def evaluate_trajectory(self):
        """
        Evaluate trajectory using Task with agent's history.
        """
        try:
            reward = await self.task.evaluate_result(
                result=self.result.get("results"),
                instance=self.data["instance"],
                history_images=self.result.get("history_images"),
                history_messages=self.result.get("messages"),
            )
            self.result["reward"] = reward
        except Exception as e:
            print(f"[AndroidTrajectory] Evaluation error: {e}")
            self.result["reward"] = 0.0
            self.result["eval_error"] = str(e)
    
    def _build_reset_payload(self) -> dict:
        """
        Build payload for environment reset.

        Returns:
            Dict with seed and options for env.reset()
        """
        instance = self.data.get("instance", {})

        # Use config seed if provided, otherwise derive from trajectory_id
        seed = self.cfg.seed if self.cfg.seed is not None else self.cfg.trajectory_id

        return {
            "seed": seed,
            "options": {
                "task_id": instance.get("task_id", 0) if isinstance(instance, dict) else 0,
                "go_home_on_reset": True,
                "epoch": self.data.get("epoch", 0),
                "mode": self.data.get("mode", "train"),
                "traj": self.cfg.trajectory_id,
                "total_traj": 1,
            }
        }
