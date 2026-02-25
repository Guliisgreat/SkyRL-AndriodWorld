"""
AndroidADBAgentRunner - Runner for ADB agent using AndroidADBTrajectory.

Subclass of AndroidAgentRunner; overrides _initialize_trajectories to create
AndroidADBTrajectory and run() init_fn to wrap containers with RuntimeClient
(unified client that supports both step and step_adb).
"""

from omegaconf import OmegaConf

from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
from skyrl_agent.agents.android.android_adb_trajectory import AndroidADBTrajectory
from skyrl_agent.agents.android.trajectory_saver import TrajectorySaver
from skyrl_agent.config.configuration_utils import TrajectoryConfig
from loguru import logger


class AndroidADBAgentRunner(AndroidAgentRunner):
    """
    Runner for ADB agent. Same flow as AndroidAgentRunner but uses
    AndroidADBTrajectory and RuntimeClient (which supports step_adb).
    """

    def _initialize_trajectories(self, val_mode: bool = False):
        """
        Initialize trajectory instances with AndroidADBTrajectory.
        """
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

                traj = AndroidADBTrajectory(
                    cfg=traj_cfg,
                    data=data,
                    tokenizer=self.tokenizer,
                    infer_engine=self.infer_engine,
                    task=self.task,
                )

                traj.processor = self.processor
                if self.processor is None:
                    logger.warning(
                        f"[AndroidADBAgentRunner] Setting None processor on trajectory {instance_id}/{traj_id}"
                    )
                else:
                    logger.debug(
                        f"[AndroidADBAgentRunner] Setting processor on trajectory {instance_id}/{traj_id}"
                    )

                self.trajectories[instance_id][traj_id] = traj

    async def run(self, input_batch, val_mode: bool = False):
        """
        Same as base run() but init_fn uses RuntimeClient(container).
        """
        from skyrl_agent.integrations.base import (
            build_generator_input,
            build_generator_output,
        )
        from skyrl_agent.dispatcher.dispatchers import DISPATCHER_REGISTRY
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient

        self.batch = build_generator_input(
            self.cfg.generator.infer_backend, input_batch
        ).input_batch

        if self.env_pool is None:
            logger.info("Initializing environment pool...")
            env_config = OmegaConf.to_container(self.cfg.env, resolve=True)
            self.env_pool = await self.task.initialize_runtime(env_config)
            logger.info(
                f"Environment pool initialized with {len(self.env_pool)} environments"
            )

        # Initialize trajectory saver if configured
        save_trajectories = getattr(self.cfg.generator, "save_trajectories", False)
        if save_trajectories:
            save_dir = getattr(self.cfg.generator, "trajectory_save_dir", "/tmp/trajectories")
            exp_name = getattr(self.cfg.generator, "trajectory_exp_name", "")
            save_screenshots = getattr(self.cfg.generator, "save_screenshots", True)
            agent_cls = getattr(self.cfg, "agent_cls", "")
            task_name = getattr(self.cfg, "task", "")
            self._trajectory_saver = TrajectorySaver(
                save_dir=save_dir,
                exp_name=exp_name,
                save_screenshots=save_screenshots,
                agent_cls=agent_cls,
                task_name=task_name,
            )
            logger.info(f"Trajectory saving enabled: {self._trajectory_saver.base_dir} (screenshots={save_screenshots})")
        else:
            self._trajectory_saver = None

        self._initialize_trajectories(val_mode=val_mode)

        if val_mode:
            num_trajectories = self.cfg.generator.val_config.num_trajectories
        else:
            num_trajectories = self.cfg.generator.num_trajectories

        async def init_fn(batch_idx: int, trajectory_id: int, container):
            """Use RuntimeClient (unified: supports both step and step_adb)."""
            instance_ids = list(self.trajectories.keys())
            instance_id = instance_ids[batch_idx]
            traj = self.trajectories[instance_id][trajectory_id]
            traj.env_id = container.env_id
            traj.env_handle = RuntimeClient(container)
            await traj.initialize_trajectory()

        async def run_fn(batch_idx: int, trajectory_id: int, container):
            instance_ids = list(self.trajectories.keys())
            instance_id = instance_ids[batch_idx]
            await self.trajectories[instance_id][trajectory_id].generate_trajectory()

        async def eval_fn(batch_idx: int, trajectory_id: int, container):
            instance_ids = list(self.trajectories.keys())
            instance_id = instance_ids[batch_idx]
            await self.trajectories[instance_id][
                trajectory_id
            ].evaluate_trajectory()

        container_manager = getattr(self.task, "_container_manager", None)
        if container_manager is None:
            raise RuntimeError(
                "ContainerManager not initialized. Call task.initialize_runtime() first."
            )

        async def on_trajectory_complete(
            batch_idx: int, trajectory_id: int, success: bool, error: str
        ):
            instance_ids = list(self.trajectories.keys())
            instance_id = instance_ids[batch_idx]
            traj = self.trajectories[instance_id][trajectory_id]
            if not success and traj.result is None:
                traj.result = {
                    "instance_id": instance_id,
                    "trajectory_id": trajectory_id,
                    "error": True,
                    "error_message": error or "Unknown error",
                    "messages": [],
                    "reward": 0.0,
                    "format_reward": 0.0,
                }
                logger.error(
                    f"Trajectory {instance_id}/{trajectory_id} failed: {error}"
                )

            # Save trajectory to disk if configured
            if self._trajectory_saver and traj.result is not None:
                task_text = ""
                if batch_idx < len(self.batch):
                    raw_prompt = self.batch[batch_idx].get("raw_prompt", [])
                    if raw_prompt:
                        task_text = raw_prompt[0].get("content", "")
                model_name = getattr(
                    self.cfg.generator.backend_config, "model_name", ""
                )
                try:
                    self._trajectory_saver.save(traj.result, task_text, model_name)
                except Exception as e:
                    logger.warning(f"Failed to save trajectory {instance_id}/{trajectory_id}: {e}")

        dispatcher_cfg = {
            "container_manager": container_manager,
            "num_instances": len(self.trajectories),
            "num_trajectories": num_trajectories,
            "num_workers": len(container_manager.containers),
            "on_trajectory_complete": on_trajectory_complete,
            "val_mode": val_mode,
        }

        dispatcher = DISPATCHER_REGISTRY.get("async_fix_pool_android")
        if dispatcher is None:
            raise ValueError(
                "async_fix_pool_android dispatcher not found in registry"
            )

        logger.info(
            f"Starting async_fix_pool_android dispatch (ADB): "
            f"{len(self.trajectories)} instances x {num_trajectories} trajectories "
            f"with {len(container_manager.containers)} containers"
        )
        await dispatcher(dispatcher_cfg, init_fn, run_fn, eval_fn)

        output = self._post_process_results(val_mode=val_mode)
        self.trajectories = {}
        return build_generator_output(
            self.cfg.generator.infer_backend, output
        ).result
