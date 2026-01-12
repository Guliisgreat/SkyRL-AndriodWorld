"""
AndroidAgentRunner - Runner for Android agents using async_fix_pool dispatcher.

Same interface as AgentRunner, with persistent env_pool created via
Task.initialize_runtime() on first run().
"""

from typing import Any, Dict, Optional
from omegaconf import OmegaConf

from skyrl_agent.agents.base import AgentRunner
from skyrl_agent.dispatcher.dispatchers import DISPATCHER_REGISTRY
from skyrl_agent.integrations.base import build_generator_input, build_generator_output
from skyrl_agent.config.configuration_utils import TrajectoryConfig
from loguru import logger


class AndroidAgentRunner(AgentRunner):
    """
    Runner for Android agents using async_fix_pool dispatcher.
    
    Same interface as AgentRunner, persistent env_pool.
    Uses async_fix_pool dispatcher for pre-initialized environment pool management.
    """
    
    def __init__(self, cfg: Dict[str, Any], infer_engine: Any, tokenizer: Any) -> None:
        """
        Initialize AndroidAgentRunner.
        
        Same signature as base AgentRunner.
        
        Args:
            cfg: Configuration dictionary
            infer_engine: Inference engine instance
            tokenizer: Tokenizer instance
        """
        super().__init__(cfg, infer_engine, tokenizer)
        self.env_pool = None  # Persistent, created on first run()
        self.processor = None  # VLM processor for image handling
        
        # Try to load processor if path is available
        self._load_processor()
    
    def _load_processor(self) -> None:
        """Load VLM processor for image processing."""
        try:
            from verl.utils.tokenizer import hf_processor
            model_path = self.cfg.actor_rollout_ref.model.path
            trust_remote_code = self.cfg.actor_rollout_ref.model.trust_remote_code
            
            self.processor = hf_processor(
                model_path,
                trust_remote_code=trust_remote_code,
                use_fast=True,
            )
        except Exception as e:
            logger.warning(f"Could not load processor: {e}")
            self.processor = None
    
    def _initialize_trajectories(self, val_mode: bool = False):
        """
        Initialize trajectory instances.
        
        Overrides base to use AndroidTrajectory and set processor.
        """
        # Import here to avoid circular dependency
        from skyrl_agent.agents.android.android_trajectory import AndroidTrajectory
        
        for batch_id, content in enumerate(self.batch):
            data = self._get_data(content)
            instance_id = data["instance_id"] if data["instance_id"] else batch_id
            self.trajectories[instance_id] = {}
            
            sampling_params = (
                self.cfg.generator.val_config.sampling_params if val_mode 
                else self.cfg.generator.sampling_params
            )
            sampling_params = OmegaConf.to_container(sampling_params, resolve=True)
            num_trajectories = (
                self.cfg.generator.val_config.num_trajectories if val_mode 
                else self.cfg.generator.num_trajectories
            )
            
            for traj_id in range(num_trajectories):
                traj_cfg = TrajectoryConfig(
                    instance_id=instance_id,
                    trajectory_id=traj_id,
                    max_prompt_length=self.cfg.generator.max_prompt_length,
                    sampling_params=sampling_params,
                    vision_is_active=self.cfg.generator.vision_is_active,
                    qwen3_enable_thinking=self.cfg.generator.get("qwen3_enable_thinking", False),
                    qwen3_acc_thinking=self.cfg.generator.get("qwen3_acc_thinking", False),
                    max_iterations=self.cfg.generator.max_iterations,
                    tools=["android_env"],  # Use unified Android env tool
                    agent_cls=self.cfg.agent_cls,
                )
                
                # Add Android-specific config
                if hasattr(self.cfg, 'data'):
                    traj_cfg.max_pixels = getattr(self.cfg.data, 'max_pixels', 1003520)
                    traj_cfg.min_pixels = getattr(self.cfg.data, 'min_pixels', 3136)
                
                traj = AndroidTrajectory(
                    cfg=traj_cfg,
                    data=data,
                    tokenizer=self.tokenizer,
                    infer_engine=self.infer_engine,
                    task=self.task,
                )
                
                # Set processor on trajectory
                traj.processor = self.processor
                
                self.trajectories[instance_id][traj_id] = traj
    
    async def run(self, input_batch: Any, val_mode: bool = False) -> Any:
        """
        Generate trajectories for the given input batch.
        
        Uses async_fix_pool dispatcher with persistent env_pool.
        
        Args:
            input_batch: Input batch from training loop
            val_mode: Whether running in validation mode
        
        Returns:
            Results converted to the appropriate output format
        """
        self.batch = build_generator_input(
            self.cfg.generator.infer_backend, input_batch
        ).input_batch
        
        # 1. Create persistent env_pool on first call
        if self.env_pool is None:
            logger.info("Initializing environment pool...")
            env_config = OmegaConf.to_container(self.cfg.env, resolve=True)
            self.env_pool = await self.task.initialize_runtime(env_config)
            logger.info(f"Environment pool initialized with {len(self.env_pool)} environments")
        
        # 2. Initialize trajectories
        self._initialize_trajectories(val_mode=val_mode)
        
        if val_mode:
            num_trajectories = self.cfg.generator.val_config.num_trajectories
        else:
            num_trajectories = self.cfg.generator.num_trajectories
        
        # 3. Create wrapper functions for async_fix_pool
        async def init_fn(batch_idx: int, trajectory_id: int, env_id: int):
            """Wrapper for trajectory initialization with env assignment."""
            instance_ids = list(self.trajectories.keys())
            instance_id = instance_ids[batch_idx]
            traj = self.trajectories[instance_id][trajectory_id]
            traj.env_id = env_id
            traj.env_handle = self.env_pool[env_id]
            await traj.initialize_trajectory()
        
        async def run_fn(batch_idx: int, trajectory_id: int, env_id: int):
            """Wrapper for trajectory generation."""
            instance_ids = list(self.trajectories.keys())
            instance_id = instance_ids[batch_idx]
            await self.trajectories[instance_id][trajectory_id].generate_trajectory()
        
        async def eval_fn(batch_idx: int, trajectory_id: int, env_id: int):
            """Wrapper for trajectory evaluation."""
            instance_ids = list(self.trajectories.keys())
            instance_id = instance_ids[batch_idx]
            await self.trajectories[instance_id][trajectory_id].evaluate_trajectory()
        
        # 4. Dispatch with async_fix_pool
        dispatcher_cfg = {
            "envs": self.env_pool,
            "num_instances": len(self.batch),
            "num_trajectories": num_trajectories,
        }
        
        dispatcher = DISPATCHER_REGISTRY.get("async_fix_pool")
        if dispatcher is None:
            raise ValueError("async_fix_pool dispatcher not found in registry")
        
        logger.info(
            f"Starting async_fix_pool dispatch: "
            f"{len(self.batch)} instances x {num_trajectories} trajectories "
            f"with {len(self.env_pool)} envs"
        )
        await dispatcher(dispatcher_cfg, init_fn, run_fn, eval_fn)
        
        # 5. Post-process results
        output = self._post_process_results(val_mode=val_mode)
        
        # Reset trajectories after run
        self.trajectories = {}
        
        return build_generator_output(self.cfg.generator.infer_backend, output).result
