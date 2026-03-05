"""
ClaudeSDKRunner - Standalone runner for Claude Agent SDK evaluation.

Does NOT inherit from AgentRunner (no infer_engine or VLM backend needed).
Uses AndroidTask, ContainerManager, and the async_fix_pool_android dispatcher
directly.

NOTE: Imports use ``_import_module`` helper to load modules directly, bypassing
``skyrl_agent.agents.__init__`` which pulls in the verl/torch dependency chain.
"""

import importlib
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from loguru import logger
from omegaconf import DictConfig, OmegaConf


import os as _os

_AGENTS_ANDROID_DIR = _os.path.dirname(_os.path.abspath(__file__))


def _load_sibling(module_name: str, filename: str):
    """Load a sibling module from this directory, bypassing __init__.py chains."""
    import importlib.util
    filepath = _os.path.join(_AGENTS_ANDROID_DIR, filename)
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ClaudeSDKRunner:
    """
    Standalone runner for Claude Agent SDK evaluation on AndroidWorld.

    Manages the full lifecycle:
        1. Initialize container pool (via AndroidTask)
        2. Create ClaudeSDKTrajectory per instance
        3. Dispatch via async_fix_pool_android
        4. Collect results and metrics
    """

    def __init__(self, cfg: DictConfig):
        from skyrl_agent.tasks.android.android_task import AndroidTask

        self.cfg = cfg
        self.task = AndroidTask()
        self.env_pool: Optional[List] = None
        self.trajectories: Dict[str, Dict[int, Any]] = {}
        self._trajectory_saver: Optional[Any] = None

    async def run(self, data: List[Dict], val_mode: bool = True) -> Dict[str, Any]:
        """
        Run evaluation on the given data instances.

        Args:
            data: List of instance dicts (from load_jsonl), each with
                  instance_id, instance, data_source, raw_prompt.
            val_mode: Always True for SDK evaluation (no training).

        Returns:
            Dict with rewards, step_counts, rollout_metrics, etc.
        """
        start = time.time()

        # 1. Initialize container pool (first call only)
        if self.env_pool is None:
            env_config = OmegaConf.to_container(self.cfg.env, resolve=True)
            logger.info("Initializing container pool...")
            self.env_pool = await self.task.initialize_runtime(env_config)
            logger.info(f"Container pool initialized")

        # 2. Initialize trajectory saver
        _saver_mod = _load_sibling("trajectory_saver", "trajectory_saver.py")
        TrajectorySaver = _saver_mod.TrajectorySaver

        save_trajectories = self.cfg.get("results", {}).get("save_trajectories", True)
        if save_trajectories:
            save_dir = self.cfg.get("results", {}).get("trajectory_save_dir", "./results")
            save_screenshots = self.cfg.get("results", {}).get("save_screenshots", True)
            self._trajectory_saver = TrajectorySaver(
                save_dir=save_dir,
                exp_name="",  # Auto-generated from agent_cls + task
                save_screenshots=save_screenshots,
                agent_cls=self.cfg.get("agent_cls", "ClaudeAgentSDK"),
                task_name=self.cfg.get("task", "AndroidTask"),
            )

        # 3. Create trajectory instances
        self._initialize_trajectories(data)

        # 4. Set up dispatcher callbacks
        from skyrl_agent.runtime.android import RuntimeClient

        async def init_fn(batch_idx: int, trajectory_id: int, container):
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
            await self.trajectories[instance_id][trajectory_id].evaluate_trajectory()

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
                    "step_count": 0,
                }
                logger.error(f"Trajectory {instance_id}/{trajectory_id} failed: {error}")

            if self._trajectory_saver and traj.result is not None:
                task_text = ""
                if batch_idx < len(data):
                    task_text = data[batch_idx].get("instance", {}).get("task", "")
                try:
                    self._trajectory_saver.save(
                        traj.result,
                        task_text,
                        model_name=self.cfg.get("claude_sdk", {}).get(
                            "model", "claude-sonnet"
                        ),
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to save trajectory {instance_id}/{trajectory_id}: {e}"
                    )

        # 5. Get container manager and dispatch
        from skyrl_agent.dispatcher.dispatchers import DISPATCHER_REGISTRY

        container_manager = getattr(self.task, "_container_manager", None)
        if container_manager is None:
            raise RuntimeError(
                "ContainerManager not initialized. "
                "Call task.initialize_runtime() first."
            )

        dispatcher_cfg = {
            "container_manager": container_manager,
            "num_instances": len(self.trajectories),
            "num_trajectories": 1,
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
            f"Starting dispatch: {len(self.trajectories)} instances "
            f"with {len(container_manager.containers)} containers"
        )
        await dispatcher(dispatcher_cfg, init_fn, run_fn, eval_fn)

        # 6. Post-process results
        output = self._post_process_results()
        elapsed = time.time() - start
        output["elapsed_seconds"] = elapsed

        # Reset trajectories
        self.trajectories = {}

        return output

    def _initialize_trajectories(self, data: List[Dict]) -> None:
        """Create ClaudeSDKTrajectory instances for each data item."""
        _traj_mod = _load_sibling("claude_sdk_trajectory", "trajectory.py")
        ClaudeSDKTrajectory = _traj_mod.ClaudeSDKTrajectory
        from skyrl_agent.config.configuration_utils import TrajectoryConfig

        sdk_cfg = OmegaConf.to_container(
            self.cfg.get("claude_sdk", {}), resolve=True
        )

        for batch_id, item in enumerate(data):
            instance_id = item.get("instance_id", str(batch_id))
            self.trajectories[instance_id] = {}

            traj_cfg = TrajectoryConfig(
                instance_id=instance_id,
                trajectory_id=0,
                max_prompt_length=0,
                sampling_params={},
                vision_is_active=False,
                max_iterations=sdk_cfg.get("max_turns", 30),
                tools=["android_env"],
                agent_cls=self.cfg.get(
                    "agent_cls",
                    "skyrl_agent.agents.android.claude_sdk.trajectory.ClaudeAgentSDK",
                ),
            )
            # Attach SDK config to trajectory config
            traj_cfg.claude_sdk = sdk_cfg

            traj = ClaudeSDKTrajectory(
                cfg=traj_cfg,
                data=item,
                infer_engine=None,
                tokenizer=None,
                task=self.task,
            )
            self.trajectories[instance_id][0] = traj

    def _post_process_results(self) -> Dict[str, Any]:
        """Collect results from all trajectories into output dict."""
        rewards: List[float] = []
        step_counts: List[int] = []
        finish_reasons: List[str] = []

        for instance_id in self.trajectories:
            for traj_id in self.trajectories[instance_id]:
                result = self.trajectories[instance_id][traj_id].result
                if result is None:
                    rewards.append(0.0)
                    step_counts.append(0)
                    finish_reasons.append("error_null_result")
                    continue
                if result.get("error"):
                    rewards.append(0.0)
                    step_counts.append(0)
                    finish_reasons.append("error")
                    continue

                rewards.append(result.get("reward", 0.0))
                step_counts.append(result.get("step_count", 0))
                finish_reasons.append(result.get("finish_reason", ""))

        n = max(len(rewards), 1)
        rollout_metrics = {
            "rollout_metrics/raw_reward": sum(rewards) / n,
            "rollout_metrics/avg_step_count": sum(step_counts) / n,
            "rollout_metrics/finish_tool_ratio": sum(
                1 for r in finish_reasons if r == "FINISH"
            ) / n,
            "rollout_metrics/infeasible_ratio": sum(
                1 for r in finish_reasons if r == "INFEASIBLE"
            ) / n,
            "rollout_metrics/iter_cap_ratio": sum(
                1 for r in finish_reasons if r == "max_iterations_reached"
            ) / n,
            "rollout_metrics/error_ratio": sum(
                1 for r in finish_reasons if r.startswith("error")
            ) / n,
        }

        return {
            "rewards": rewards,
            "step_counts": step_counts,
            "finish_reasons": finish_reasons,
            "rollout_metrics": rollout_metrics,
        }
