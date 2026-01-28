"""
AndroidAgentRunner - Runner for Android agents using async_fix_pool_retry dispatcher.

Same interface as AgentRunner, with persistent env_pool created via
Task.initialize_runtime() on first run().
"""

from typing import Any, Dict, List, Optional
from collections import defaultdict
from omegaconf import OmegaConf
import torch

from skyrl_agent.agents.base import AgentRunner
from skyrl_agent.dispatcher.dispatchers import DISPATCHER_REGISTRY
from skyrl_agent.integrations.base import build_generator_input, build_generator_output
from skyrl_agent.config.configuration_utils import TrajectoryConfig
from loguru import logger


class AndroidAgentRunner(AgentRunner):
    """
    Runner for Android agents using async_fix_pool_retry dispatcher.
    
    Same interface as AgentRunner, persistent env_pool.
    Uses async_fix_pool_retry dispatcher with built-in retry logic for robust execution.
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
            from verl.utils import hf_processor
            model_path = self.cfg.actor_rollout_ref.model.path
            trust_remote_code = self.cfg.actor_rollout_ref.model.trust_remote_code

            self.processor = hf_processor(
                model_path,
                trust_remote_code=trust_remote_code,
                use_fast=True,
            )
            logger.info(f"Loaded VLM processor from {model_path}")
        except Exception as e:
            logger.warning(f"Could not load processor: {e}")
            import traceback
            traceback.print_exc()
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
                    # Context limit: derived from max_model_len - context_buffer
                    # Must match actor_rollout_ref.rollout.max_model_len in shell script
                    max_model_len=self.cfg.generator.get("max_model_len", 32768),
                    context_buffer=self.cfg.generator.get("context_buffer", 4096),
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
                if self.processor is None:
                    logger.warning(f"[AndroidAgentRunner] Setting None processor on trajectory {instance_id}/{traj_id}")
                else:
                    logger.debug(f"[AndroidAgentRunner] Setting processor on trajectory {instance_id}/{traj_id}")
                
                self.trajectories[instance_id][traj_id] = traj
    
    async def run(self, input_batch: Any, val_mode: bool = False) -> Any:
        """
        Generate trajectories for the given input batch.
        
        Uses async_fix_pool_retry dispatcher with persistent env_pool and retry logic.
        
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
        
        # 3. Create wrapper functions for async_fix_pool_retry
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
        
        async def on_retry_success(batch_idx: int, trajectory_id: int, retry_count: int, failure_history: list):
            """Called when a trajectory succeeds after retries. Store retry info on trajectory."""
            instance_ids = list(self.trajectories.keys())
            instance_id = instance_ids[batch_idx]
            traj = self.trajectories[instance_id][trajectory_id]
            # Store retry metadata on trajectory result
            if traj.result is not None:
                traj.result["retry_count"] = retry_count
                traj.result["failure_history"] = failure_history
                logger.info(
                    f"Trajectory {instance_id}/{trajectory_id} succeeded after {retry_count} retries"
                )
        
        async def on_retry_failure(batch_idx: int, trajectory_id: int, retry_count: int, 
                                   failure_history: list, final_error: dict):
            """Called when all retries are exhausted. Store error info on trajectory."""
            instance_ids = list(self.trajectories.keys())
            instance_id = instance_ids[batch_idx]
            traj = self.trajectories[instance_id][trajectory_id]
            # Set trajectory result to error object
            traj.result = {
                "instance_id": instance_id,
                "trajectory_id": trajectory_id,
                "error": True,
                "retry_count": retry_count,
                "failure_history": failure_history,
                "final_error": final_error,
                "messages": [],
                "reward": 0.0,
                "format_reward": 0.0,
            }
            logger.error(
                f"Trajectory {instance_id}/{trajectory_id} failed after {retry_count} attempts: "
                f"{final_error['error_message'] if final_error else 'Unknown'}"
            )
        
        # 4. Dispatch with async_fix_pool_retry
        # Use len(self.trajectories) instead of len(self.batch) because
        # batch items may share the same instance_id and get deduplicated
        # 
        # Two-level recovery strategy:
        # - Level 1: Retry on same container (max_retries times)
        # - Level 2: Switch to different container and restart from beginning
        
        # Get container manager for health callbacks
        container_manager = getattr(self.task, '_container_manager', None)
        
        # Create quick_ping callback for pre-check
        async def quick_ping(env_id: int) -> bool:
            """Quick health check before assigning container."""
            if container_manager is None:
                return True  # No container manager, assume healthy
            return await container_manager.quick_ping(env_id)
        
        # Create mark_container_unhealthy callback
        async def mark_unhealthy(env_id: int) -> None:
            """Mark container as unhealthy for background restart."""
            if container_manager is not None:
                await container_manager.mark_container_unhealthy_async(env_id)
        
        # Create recovery callback registration function
        # This is called by the dispatcher to register the add_to_queue callback
        def on_container_recovered(add_to_queue_callback):
            """Register the add_to_queue callback with the container manager."""
            if container_manager is not None:
                container_manager.set_recovery_callback(add_to_queue_callback)
        
        # Create backup container callback (instant failover)
        async def get_backup_container() -> int:
            """Get a hot standby container from backup pool."""
            if container_manager is None:
                return None
            return await container_manager.get_backup_container()
        
        # Get dispatcher retry config from yaml (with sensible defaults)
        disp_cfg = getattr(self.cfg, 'dispatcher', None) or {}
        if hasattr(disp_cfg, '__iter__') and not isinstance(disp_cfg, dict):
            disp_cfg = dict(disp_cfg) if hasattr(disp_cfg, 'items') else {}
        
        dispatcher_cfg = {
            "envs": self.env_pool,
            "num_instances": len(self.trajectories),
            "num_trajectories": num_trajectories,
            # Level 1: Retries per container (read from yaml config)
            "max_retries": getattr(disp_cfg, 'max_retries', None) or disp_cfg.get('max_retries', 5),
            "retry_base_delay": getattr(disp_cfg, 'retry_base_delay', None) or disp_cfg.get('retry_base_delay', 2.0),
            # Level 2: Container switching (read from yaml config)
            "max_container_switches": getattr(disp_cfg, 'max_container_switches', None) or disp_cfg.get('max_container_switches', 10),
            "container_switch_delay": getattr(disp_cfg, 'container_switch_delay', None) or disp_cfg.get('container_switch_delay', 5.0),
            # Callbacks
            "on_retry_success": on_retry_success,
            "on_retry_failure": on_retry_failure,
            "quick_ping": quick_ping,  # Pre-check before using container
            "mark_container_unhealthy": mark_unhealthy,  # Mark dead containers
            "on_container_recovered": on_container_recovered,  # Add recovered containers back to queue
            "get_backup_container": get_backup_container,  # Instant failover to backup
        }
        
        dispatcher = DISPATCHER_REGISTRY.get("async_fix_pool_retry")
        if dispatcher is None:
            raise ValueError("async_fix_pool_retry dispatcher not found in registry")
        
        logger.info(
            f"Starting async_fix_pool_retry dispatch: "
            f"{len(self.batch)} instances x {num_trajectories} trajectories "
            f"with {len(self.env_pool)} envs, "
            f"max_retries={dispatcher_cfg['max_retries']}, "
            f"max_container_switches={dispatcher_cfg['max_container_switches']}, "
            f"pre_check={'enabled' if container_manager else 'disabled'}"
        )
        await dispatcher(dispatcher_cfg, init_fn, run_fn, eval_fn)
        
        # 5. Post-process results
        output = self._post_process_results(val_mode=val_mode)

        # Reset trajectories after run
        self.trajectories = {}

        return build_generator_output(self.cfg.generator.infer_backend, output).result

    def _post_process_results(self, return_tensors=False, val_mode: bool = False) -> Dict[str, Any]:
        """
        Post-process results for VLM training.

        Overrides base to extract VLM tensors (pixel_values, image_grid_thw) from
        AndroidAgent.get_train_dict() instead of re-tokenizing messages.

        Returns:
            Dict with prompt_token_ids, response_ids, loss_masks, rewards,
            and VLM-specific: pixel_values, image_grid_thw, position_ids
        """
        num_trajectories = (
            self.cfg.generator.val_config.num_trajectories if val_mode
            else self.cfg.generator.num_trajectories
        )

        # Collect results from all trajectories
        all_results = {}
        for instance_id in self.trajectories:
            for trajectory_id in self.trajectories[instance_id]:
                result = self.trajectories[instance_id][trajectory_id].result
                all_results.setdefault(instance_id, {})[trajectory_id] = result

        # Match results to unique trajectories (not batch order, since batch may have duplicates)
        matched_results = []
        for instance_id in self.trajectories:
            trajectories = all_results.get(instance_id, {})
            matched_results.extend(trajectories.values())

        # When batch items share the same instance_id, results are deduplicated
        expected_results = num_trajectories * len(self.trajectories)
        assert len(matched_results) == expected_results, \
            f"Expected {expected_results} results, got {len(matched_results)}"

        # Extract VLM tensors from train_dict
        prompt_token_ids = []
        response_ids = []
        loss_masks = []
        rewards = []
        pixel_values_list = []
        image_grid_thw_list = []
        position_ids_list = []
        finish_reason_list = []

        # Reasons to mask out loss
        mask_out_reason = [
            "CONTEXT_WINDOW_EXCEEDED",
            "error_runtime",
            "error_evaluation",
            "max_iterations_reached",
            "BAD_LLM_RESPONSE",
            "stuck_in_a_loop",
            "cmd_timeout",
        ]

        for result in matched_results:
            # Handle None result (trajectory completely failed)
            if result is None:
                logger.warning("Got None result from trajectory, using empty tensors")
                prompt_token_ids.append([])
                response_ids.append([])
                loss_masks.append([])
                pixel_values_list.append(None)
                image_grid_thw_list.append(None)
                position_ids_list.append(None)
                finish_reason_list.append("error_null_result")
                rewards.append(0.0)
                continue
            
            # Handle error result (trajectory failed after all retries)
            if result.get("error"):
                instance_id = result.get("instance_id", "unknown")
                retry_count = result.get("retry_count", 0)
                final_error = result.get("final_error", {})
                error_msg = final_error.get("error_message", "Unknown error") if final_error else "Unknown error"
                logger.warning(
                    f"Trajectory {instance_id} failed after {retry_count} retries: {error_msg}"
                )
                prompt_token_ids.append([])
                response_ids.append([])
                loss_masks.append([])
                pixel_values_list.append(None)
                image_grid_thw_list.append(None)
                position_ids_list.append(None)
                finish_reason_list.append(f"error_max_retries_{retry_count}")
                rewards.append(0.0)
                continue
            
            # Log retry info if trajectory succeeded after retries
            if result.get("retry_count", 0) > 0:
                logger.info(
                    f"Trajectory {result.get('instance_id')} succeeded after "
                    f"{result.get('retry_count')} retries"
                )
                
            train_dict = result.get("train_dict", {})
            finish_reason = result.get("finish_reason", "")
            reward = result.get("reward", 0.0)

            finish_reason_list.append(finish_reason)
            rewards.append(reward)

            if not train_dict or "input_ids" not in train_dict:
                # Fallback: use empty tensors if train_dict missing
                logger.warning(f"Missing train_dict for result, using empty tensors")
                prompt_token_ids.append([])
                response_ids.append([])
                loss_masks.append([])
                pixel_values_list.append(None)
                image_grid_thw_list.append(None)
                position_ids_list.append(None)
                continue

            input_ids = train_dict["input_ids"]
            labels = train_dict.get("labels", input_ids)
            attention_mask = train_dict.get("attention_mask")
            position_ids = train_dict.get("position_ids")

            # Get multi_modal_inputs
            multi_modal = train_dict.get("multi_modal_inputs", {})
            pixel_values = multi_modal.get("pixel_values")
            image_grid_thw = multi_modal.get("image_grid_thw")

            # Split into prompt and response based on labels
            # labels == -100 means prompt (not trained on), labels != -100 means response
            if labels is not None and len(labels) > 0:
                # Find first non-(-100) label as start of response
                labels_list = labels.tolist() if torch.is_tensor(labels) else labels
                response_start = 0
                for i, label in enumerate(labels_list):
                    if label != -100:
                        response_start = i
                        break

                input_ids_list = input_ids.tolist() if torch.is_tensor(input_ids) else input_ids
                prompt_ids = input_ids_list[:response_start]
                resp_ids = input_ids_list[response_start:]

                # Create loss mask: 1 where labels != -100, 0 where labels == -100
                # Only for response portion
                resp_labels = labels_list[response_start:]
                loss_mask = [0 if l == -100 else 1 for l in resp_labels]

                # Mask out entire trajectory if finish_reason indicates error
                if finish_reason in mask_out_reason:
                    loss_mask = [0] * len(loss_mask)
            else:
                # Fallback if no labels
                input_ids_list = input_ids.tolist() if torch.is_tensor(input_ids) else input_ids
                prompt_ids = input_ids_list
                resp_ids = []
                loss_mask = []

            prompt_token_ids.append(prompt_ids)
            response_ids.append(resp_ids)
            loss_masks.append(loss_mask)
            pixel_values_list.append(pixel_values)
            image_grid_thw_list.append(image_grid_thw)
            position_ids_list.append(position_ids)

        # Compute rollout metrics
        rollout_metrics = {}
        num_turns = []
        for result in matched_results:
            messages = result.get("messages", [])
            num_turns.append(sum(1 for m in messages if m.get("role") == "assistant"))

        avg_turn_assistant = sum(num_turns) / len(num_turns) if num_turns else 0.0
        rollout_metrics["rollout_metrics/avg_turn_assistant"] = avg_turn_assistant

        # Finish reason metrics
        rollout_metrics["rollout_metrics/finish_tool_ratio"] = sum(
            1 for r in finish_reason_list if r == "FINISH"
        ) / max(len(finish_reason_list), 1)
        rollout_metrics["rollout_metrics/context_exceed_ratio"] = sum(
            1 for r in finish_reason_list if r == "CONTEXT_WINDOW_EXCEEDED"
        ) / max(len(finish_reason_list), 1)
        rollout_metrics["rollout_metrics/iter_cap_ratio"] = sum(
            1 for r in finish_reason_list if r == "max_iterations_reached"
        ) / max(len(finish_reason_list), 1)
        rollout_metrics["rollout_metrics/error_runtime"] = sum(
            1 for r in finish_reason_list if r == "error_runtime"
        ) / max(len(finish_reason_list), 1)

        # Resolution metrics
        total_per_instance = defaultdict(int)
        resolved_per_instance = defaultdict(int)
        for batch_idx, content in enumerate(self.batch):
            data = self._get_data(content)
            instance_id = data["instance_id"] if data["instance_id"] else batch_idx
            for traj_idx in range(num_trajectories):
                result_idx = batch_idx * num_trajectories + traj_idx
                if result_idx < len(rewards):
                    total_per_instance[instance_id] += 1
                    if rewards[result_idx] > 0:
                        resolved_per_instance[instance_id] += 1

        num_resolved_0 = sum(1 for iid in total_per_instance if resolved_per_instance[iid] == 0)
        num_resolved_1 = sum(1 for iid in total_per_instance
                           if resolved_per_instance[iid] == total_per_instance[iid])
        rollout_metrics["rollout_metrics/num_all_resolved"] = num_resolved_1
        rollout_metrics["rollout_metrics/num_none_resolved"] = num_resolved_0
        rollout_metrics["rollout_metrics/raw_reward"] = sum(rewards) / max(len(rewards), 1)

        logger.info(f"Rollout metrics: {rollout_metrics}")
        logger.info(f"Finish reasons: {finish_reason_list}")

        output = {
            "prompt_token_ids": prompt_token_ids,
            "response_ids": response_ids,
            "rewards": rewards,
            "loss_masks": loss_masks,
            "rollout_metrics": rollout_metrics,
            # VLM-specific tensors
            "pixel_values": pixel_values_list,
            "image_grid_thw": image_grid_thw_list,
            "position_ids": position_ids_list,
        }

        return output
