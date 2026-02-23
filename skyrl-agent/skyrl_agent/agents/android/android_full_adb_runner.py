"""
AndroidFullADBAgentRunner - Runner for the text-only ADB agent.

Subclass of AndroidADBAgentRunner; reuses run() (which already uses
RuntimeClient for step_adb). Only overrides _initialize_trajectories to create
AndroidFullADBTrajectory instead of AndroidADBTrajectory.
"""

from omegaconf import OmegaConf
from loguru import logger

from skyrl_agent.agents.android.android_adb_runner import AndroidADBAgentRunner
from skyrl_agent.agents.android.android_full_adb_trajectory import AndroidFullADBTrajectory
from skyrl_agent.config.configuration_utils import TrajectoryConfig


class AndroidFullADBAgentRunner(AndroidADBAgentRunner):
    """
    Runner for the full-ADB (text-only) agent. Identical to
    AndroidADBAgentRunner except it creates AndroidFullADBTrajectory.
    """

    def _initialize_trajectories(self, val_mode: bool = False):
        for batch_id, content in enumerate(self.batch):
            data = self._get_data(content)
            instance_id = data["instance_id"] if data["instance_id"] else batch_id
            self.trajectories[instance_id] = {}

            sampling_params = (
                self.cfg.generator.val_config.sampling_params
                if val_mode
                else self.cfg.generator.sampling_params
            )
            sampling_params = OmegaConf.to_container(sampling_params, resolve=True)
            num_trajectories = (
                self.cfg.generator.val_config.num_trajectories
                if val_mode
                else self.cfg.generator.num_trajectories
            )

            for traj_id in range(num_trajectories):
                traj_cfg = TrajectoryConfig(
                    instance_id=instance_id,
                    trajectory_id=traj_id,
                    max_prompt_length=self.cfg.generator.max_prompt_length,
                    sampling_params=sampling_params,
                    vision_is_active=self.cfg.generator.vision_is_active,
                    qwen3_enable_thinking=self.cfg.generator.get(
                        "qwen3_enable_thinking", False
                    ),
                    qwen3_acc_thinking=self.cfg.generator.get(
                        "qwen3_acc_thinking", False
                    ),
                    max_iterations=self.cfg.generator.max_iterations,
                    tools=["android_env"],
                    agent_cls=self.cfg.agent_cls,
                    max_model_len=self.cfg.generator.get("max_model_len", 32768),
                    context_buffer=self.cfg.generator.get("context_buffer", 4096),
                )

                if hasattr(self.cfg, "data"):
                    traj_cfg.max_pixels = getattr(
                        self.cfg.data, "max_pixels", 564480
                    )
                    traj_cfg.min_pixels = getattr(self.cfg.data, "min_pixels", 78400)

                if hasattr(self.cfg, "generator"):
                    traj_cfg.max_history_steps = getattr(
                        self.cfg.generator, "max_history_steps", 10
                    )

                traj = AndroidFullADBTrajectory(
                    cfg=traj_cfg,
                    data=data,
                    tokenizer=self.tokenizer,
                    infer_engine=self.infer_engine,
                    task=self.task,
                )

                traj.processor = self.processor
                if self.processor is None:
                    logger.warning(
                        f"[AndroidFullADBAgentRunner] Setting None processor on trajectory {instance_id}/{traj_id}"
                    )
                else:
                    logger.debug(
                        f"[AndroidFullADBAgentRunner] Setting processor on trajectory {instance_id}/{traj_id}"
                    )

                self.trajectories[instance_id][traj_id] = traj
