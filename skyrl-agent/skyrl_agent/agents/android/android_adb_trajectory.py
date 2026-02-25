"""
AndroidADBTrajectory - Trajectory for ADB agent using AndroidAPIScreenADBAgent and step_adb.

Subclass of AndroidTrajectory; overrides generate_trajectory to instantiate
AndroidAPIScreenADBAgent. env_handle must be RuntimeClient (set by AndroidAgentRunner).
"""

from typing import Any, Optional

from skyrl_agent.agents.android.android_trajectory import AndroidTrajectory
from skyrl_agent.agents.android.android_adb_agent import AndroidAPIScreenADBAgent


class AndroidADBTrajectory(AndroidTrajectory):
    """
    Trajectory for ADB agent. Same lifecycle as AndroidTrajectory;
    uses AndroidAPIScreenADBAgent and expects env_handle to support step_adb().
    """

    # Agent type for type hints
    agent: Optional[AndroidAPIScreenADBAgent] = None

    async def generate_trajectory(self):
        """
        Create AndroidAPIScreenADBAgent (not AndroidAgent), run trajectory, retrieve state.
        """
        if self.processor is None:
            print(
                f"[AndroidADBTrajectory WARNING] processor is None for instance={self.cfg.instance_id} traj={self.cfg.trajectory_id}"
            )
        else:
            print(
                f"[AndroidADBTrajectory] processor loaded: {type(self.processor).__name__} for instance={self.cfg.instance_id} traj={self.cfg.trajectory_id}"
            )

        self.agent = AndroidAPIScreenADBAgent(
            traj_config=self.cfg,
            infer_engine=self.infer_engine,
            tokenizer=self.tokenizer,
            processor=self.processor,
            env_handle=self.env_handle,
        )

        initial_instruction = self.agent.format_initial_instruction(
            template_messages=self.template_messages,
            observation=self.initial_observation,
            task=self.task,
        )

        finish_reason, result = await self.agent.run(initial_instruction)

        state = self.agent.get_state()

        self.result = {
            "instance_id": state.instance_id,
            "trajectory_id": state.trajectory_id,
            "messages": state.messages,
            "history_images": state.images,
            "train_dict": self.agent.get_train_dict(),
            "results": result,
            "finish_reason": state.finish_reason,
            "reward": state.reward,
            "format_reward": state.format_reward,
            "step_count": state.step_count,
            "total_input_tokens": state.total_input_tokens,
            "total_output_tokens": state.total_output_tokens,
            "step_records": state.step_records,
            "state": {},
        }
