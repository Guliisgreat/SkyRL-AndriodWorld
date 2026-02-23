"""
AndroidFullADBTrajectory - Trajectory for the text-only ADB agent.

Subclass of AndroidTrajectory; overrides generate_trajectory to instantiate
AndroidFullADBAgent. env_handle must be RuntimeClient (set by the runner).
"""

from typing import Optional

from skyrl_agent.agents.android.android_trajectory import AndroidTrajectory
from skyrl_agent.agents.android.android_full_adb_agent import AndroidFullADBAgent


class AndroidFullADBTrajectory(AndroidTrajectory):
    """
    Trajectory for the full-ADB (text-only) agent. Same lifecycle as
    AndroidTrajectory; uses AndroidFullADBAgent and expects env_handle
    to support step_adb().
    """

    agent: Optional[AndroidFullADBAgent] = None

    async def generate_trajectory(self):
        """Create AndroidFullADBAgent, run trajectory, retrieve state."""
        if self.processor is None:
            print(
                f"[AndroidFullADBTrajectory] processor is None for "
                f"instance={self.cfg.instance_id} traj={self.cfg.trajectory_id}"
            )
        else:
            print(
                f"[AndroidFullADBTrajectory] processor loaded: "
                f"{type(self.processor).__name__} for "
                f"instance={self.cfg.instance_id} traj={self.cfg.trajectory_id}"
            )

        self.agent = AndroidFullADBAgent(
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
            "state": {},
        }
