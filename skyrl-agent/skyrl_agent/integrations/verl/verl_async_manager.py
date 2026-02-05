"""
SkyAgent Loop Manager for verl 0.6.1.

This module provides the integration between skyrl-agent and verl 0.6.1's
new replica-based architecture. Key changes from verl 0.5.x:
- Uses vLLMReplica/SGLangReplica for server lifecycle management
- No longer uses AsyncvLLMServerRegular (removed in 0.6.1)
- Keeps asyncio-based parallelism (does NOT use AgentLoopWorker)
- VLM-aware postprocessing for Qwen2-VL models (pixel_values, image_grid_thw)
"""

import asyncio
from importlib import import_module
from typing import Any, Dict, List, Optional, Type

import numpy as np
import ray
import torch
from omegaconf import DictConfig, OmegaConf
from tensordict import TensorDict

from verl.protocol import DataProto
from verl.single_controller.ray.base import RayWorkerGroup
from verl.utils import hf_tokenizer
from verl.utils.fs import copy_to_local
from verl.experimental.agent_loop.agent_loop import AsyncLLMServerManager
from verl.workers.rollout.replica import get_rollout_replica_class, RolloutReplica



def _import_object(path: str):
    """Import a class or function from a module path."""
    module_path, class_name = path.rsplit(".", 1)
    return getattr(import_module(module_path), class_name)


class SkyAgentLoopManager:
    """
    Agent loop manager that manages LLM servers and skyrl-agent trajectories.
    
    This implementation:
    - Uses verl 0.6.1's RolloutReplica abstraction for server lifecycle
    - Maintains asyncio-based parallelism via skyrl-agent's dispatchers
    - Does NOT use verl's AgentLoopWorker (which uses Ray-based parallelism)
    - VLM-aware postprocessing for Qwen2-VL models
    """

    def __init__(
        self, 
        config: DictConfig, 
        worker_group: RayWorkerGroup,
        rollout_resource_pool=None,
    ):
        """Initialize agent loop manager."""
        self.config = config
        self.worker_group = worker_group
        self.rollout_resource_pool = rollout_resource_pool

        # Get the replica class based on backend (vllm or sglang)
        self.rollout_replica_class = get_rollout_replica_class(
            self.config.actor_rollout_ref.rollout.name
        )

        # Initialize tokenizer
        model_path = config.actor_rollout_ref.model.path
        self.model_name = "/".join(model_path.split("/")[-2:])
        local_path = copy_to_local(config.actor_rollout_ref.model.path)
        self.tokenizer = hf_tokenizer(local_path, trust_remote_code=True)

        # VLM processor for position_ids computation (lazy-loaded)
        self._vlm_processor = None

        # Initialize LLM servers using replica abstraction
        self._initialize_llm_servers()

        # Initialize AsyncLLMServerManager for load balancing
        self.server_manager = AsyncLLMServerManager(config, self.server_handles)

        # Initialize skyrl-agent generator using registry-based creation
        self.skyagent_generator = self._create_agent_runner(config)

        # Initially we're in sleep mode if configured
        if self.config.actor_rollout_ref.rollout.free_cache_engine:
            self.sleep()

    def _create_agent_runner(self, config: DictConfig):
        """Create agent runner with merged config for vision model support."""
        # Lazy imports to avoid circular dependency
        from skyrl_agent.agents import AgentRunner
        from skyrl_agent.agents.mapping import AGENT_GENERATOR_REGISTRY
        
        task_yaml = config.skyrl_agent.task_yaml
        task_cfg = OmegaConf.load(task_yaml)

        runner_path = AGENT_GENERATOR_REGISTRY.get(task_cfg.agent_cls, None)
        if not runner_path:
            raise ValueError(
                f"AgentRunner class for agent {task_cfg.agent_cls} is not specified. "
                f"Please ensure that the agent is present in the registry"
            )
        runner_cls: Type[AgentRunner] = _import_object(runner_path)

        merged_cfg = OmegaConf.merge(
            task_cfg,
            {"actor_rollout_ref": config.actor_rollout_ref}
        )
        return runner_cls(merged_cfg, self.server_manager, self.tokenizer)

    def _initialize_llm_servers(self):
        """Initialize LLM servers using verl 0.6.1's RolloutReplica abstraction."""
        rollout_config = self.config.actor_rollout_ref.rollout
        model_config = self.config.actor_rollout_ref.model

        rollout_world_size = (
            rollout_config.tensor_model_parallel_size
            * rollout_config.get("data_parallel_size", 1)
            * rollout_config.get("pipeline_model_parallel_size", 1)
        )
        world_size = (
            self.worker_group.world_size
            if self.worker_group
            else self.config.trainer.n_gpus_per_node * self.config.trainer.nnodes
        )
        num_replicas = world_size // rollout_world_size

        self.rollout_replicas: List[RolloutReplica] = []
        for replica_rank in range(num_replicas):
            replica = self.rollout_replica_class(
                replica_rank=replica_rank,
                config=rollout_config,
                model_config=model_config,
                gpus_per_node=self.config.trainer.n_gpus_per_node,
            )
            self.rollout_replicas.append(replica)

        if self.worker_group:
            self._run_all([
                replica.init_hybrid(self.worker_group) 
                for replica in self.rollout_replicas
            ])
        else:
            self._run_all([
                replica.init_standalone() 
                for replica in self.rollout_replicas
            ])

        self.server_handles = [replica._server_handle for replica in self.rollout_replicas]
        self.server_addresses = [replica._server_address for replica in self.rollout_replicas]

        print(f"SkyAgentLoopManager: Initialized {len(self.rollout_replicas)} replicas")
        print(f"SkyAgentLoopManager: Server addresses: {self.server_addresses}")

    def _run_all(self, tasks: List[asyncio.Task]):
        """Run all async tasks and wait for completion."""
        async def run_all():
            await asyncio.gather(*tasks)
        asyncio.run(run_all())

    def _postprocess(self, inputs: Dict[str, List[Any]]) -> DataProto:
        """Postprocess skyrl-agent outputs to verl's DataProto format."""
        has_vlm_tensors = (
            "pixel_values" in inputs
            and inputs["pixel_values"]
            and any(pv is not None for pv in inputs["pixel_values"])
        )

        self.tokenizer.padding_side = "left"
        max_prompt_length = max(
            max([len(ids) for ids in inputs["prompt_token_ids"]]),
            self.config.actor_rollout_ref.rollout.prompt_length,
        )
        outputs = self.tokenizer.pad(
            [{"input_ids": ids} for ids in inputs["prompt_token_ids"]],
            padding="max_length",
            max_length=max_prompt_length,
            return_tensors="pt",
            return_attention_mask=True,
        )
        prompt_ids, prompt_attention_mask = outputs["input_ids"], outputs["attention_mask"]

        self.tokenizer.padding_side = "right"
        max_response_length = max(
            max([len(r) for r in inputs["response_ids"]]),
            self.config.actor_rollout_ref.rollout.response_length,
        )
        outputs = self.tokenizer.pad(
            [{"input_ids": ids} for ids in inputs["response_ids"]],
            padding="max_length",
            max_length=max_response_length,
            return_tensors="pt",
            return_attention_mask=True,
        )
        response_ids, response_attention_mask = outputs["input_ids"], outputs["attention_mask"]

        response_length = response_ids.shape[1]
        loss_masks = [m + [0] * (response_length - len(m)) for m in inputs["loss_masks"]]
        response_mask = torch.tensor(loss_masks, dtype=torch.long) * response_attention_mask

        input_ids = torch.cat([prompt_ids, response_ids], dim=1)
        attention_mask = torch.cat([prompt_attention_mask, response_attention_mask], dim=1)

        non_tensor_batch = {"rewards": np.array(inputs["rewards"])}
        
        # Track position_ids computation for metrics
        position_ids_metrics = {
            "vlm_samples_total": 0,
            "vlm_samples_computed": 0,
            "vlm_samples_fallback": 0,
            "used_text_only_fallback": False,
        }

        if has_vlm_tensors:
            multi_modal_inputs = []
            for pv, igt in zip(inputs["pixel_values"], inputs["image_grid_thw"]):
                if pv is not None and igt is not None:
                    multi_modal_inputs.append({"pixel_values": pv, "image_grid_thw": igt})
                else:
                    multi_modal_inputs.append({})
            
            non_tensor_batch["multi_modal_inputs"] = np.array(multi_modal_inputs, dtype=object)

            position_ids, position_ids_metrics = self._compute_vlm_position_ids(
                input_ids=input_ids,
                attention_mask=attention_mask,
                image_grid_thw_list=inputs["image_grid_thw"],
            )
            
            # FAIL-FAST: If VLM position_ids computation completely failed,
            # training would use incorrect 1D position_ids instead of 3D M-RoPE.
            # This would cause the model to lose image spatial information.
            # Better to fail loudly than train a broken model silently.
            if position_ids_metrics["used_text_only_fallback"]:
                raise RuntimeError(
                    "CRITICAL: VLM position_ids computation failed for entire batch.\n"
                    f"  - Batch size: {len(input_ids)}\n"
                    f"  - Samples with images: {sum(1 for igt in inputs['image_grid_thw'] if igt is not None)}\n"
                    f"  - Fallback count: {position_ids_metrics['vlm_samples_fallback']}\n"
                    "\n"
                    "Training with 1D position_ids would cause incorrect VLM behavior:\n"
                    "  - Model cannot understand image spatial layout\n"
                    "  - Cross-attention between text and image will be wrong\n"
                    "  - Training would produce a broken model\n"
                    "\n"
                    "To fix this issue:\n"
                    "  1. Check if verl.models.transformers.qwen2_vl is importable\n"
                    "  2. Verify the model path has a valid processor\n"
                    "  3. Check image_grid_thw tensors are correctly formatted\n"
                    "  4. See logs above for specific error details"
                )
        else:
            position_ids = (attention_mask.cumsum(dim=1) - 1) * attention_mask
        
        # Add position_ids metrics to rollout_metrics
        rollout_metrics = inputs.get("rollout_metrics", {})
        for key, value in position_ids_metrics.items():
            rollout_metrics[f"position_ids/{key}"] = value

        batch = TensorDict({
            "prompts": prompt_ids,
            "responses": response_ids,
            "response_mask": response_mask,
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "position_ids": position_ids,
        }, batch_size=len(input_ids))

        return DataProto(
            batch=batch,
            non_tensor_batch=non_tensor_batch,
            meta_info={"rollout_metrics": rollout_metrics, "timing": {}},
        )

    def _compute_vlm_position_ids(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        image_grid_thw_list: List[Any],
    ) -> tuple:
        """
        Compute VLM-aware position_ids for Qwen2-VL models.
        
        For VLM models, position_ids have 3D structure [batch, 3, seq_len]:
        - Dimension 0: text position
        - Dimension 1: height position for image tokens
        - Dimension 2: width position for image tokens
        
        This function tracks success/failure metrics and provides detailed
        error logging to help diagnose issues.
        
        Args:
            input_ids: Padded input token IDs [batch, seq_len]
            attention_mask: Attention mask [batch, seq_len]
            image_grid_thw_list: List of image_grid_thw tensors per sample
        
        Returns:
            Tuple of (position_ids tensor, metrics dict)
        """
        import traceback
        
        metrics = {
            "vlm_samples_total": len(input_ids),
            "vlm_samples_computed": 0,
            "vlm_samples_fallback": 0,
            "used_text_only_fallback": False,
        }
        
        # Try to import VLM utilities
        try:
            from verl.models.transformers.qwen2_vl import get_rope_index
            from verl.utils import hf_processor
        except ImportError as e:
            print(
                f"[position_ids] ERROR: Cannot import VLM utilities: {e}\n"
                f"This will cause incorrect training for Qwen2-VL models.\n"
                f"Falling back to text-only position_ids."
            )
            metrics["used_text_only_fallback"] = True
            metrics["vlm_samples_fallback"] = len(input_ids)
            return (attention_mask.cumsum(dim=1) - 1) * attention_mask, metrics
        
        # Initialize processor if needed
        if self._vlm_processor is None:
            try:
                local_path = copy_to_local(self.config.actor_rollout_ref.model.path)
                self._vlm_processor = hf_processor(local_path, trust_remote_code=True, use_fast=True)
                print(f"[position_ids] Loaded VLM processor from {local_path}")
            except Exception as e:
                print(
                    f"[position_ids] ERROR: Cannot load VLM processor: {e}\n"
                    f"Falling back to text-only position_ids."
                )
                metrics["used_text_only_fallback"] = True
                metrics["vlm_samples_fallback"] = len(input_ids)
                return (attention_mask.cumsum(dim=1) - 1) * attention_mask, metrics
        
        # Compute position_ids for each sample
        position_ids_list = []
        per_sample_errors = []
        
        for i in range(len(input_ids)):
            # get_rope_index expects UNBATCHED tensors (1D for input_ids, 2D for image_grid_thw)
            # See: verl/models/transformers/qwen2_vl.py line 74:
            #   "The batch dim has been removed and input_ids should be a 1D tensor"
            sample_ids = input_ids[i]  # [seq_len] - squeeze out batch dim
            sample_mask = attention_mask[i]  # [seq_len] - squeeze out batch dim
            sample_igt = image_grid_thw_list[i]  # [num_images, 3] - already correct
            
            try:
                if sample_igt is not None:
                    # Ensure image_grid_thw is 2D: [num_images, 3]
                    # Do NOT add batch dimension - get_rope_index expects unbatched
                    if sample_igt.dim() == 3:
                        # Remove spurious batch dim if present
                        sample_igt = sample_igt.squeeze(0)
                    
                    pos_ids = get_rope_index(
                        self._vlm_processor,
                        input_ids=sample_ids,
                        image_grid_thw=sample_igt,
                        attention_mask=sample_mask,
                    )
                    metrics["vlm_samples_computed"] += 1
                else:
                    # No image for this sample - use text-only position_ids (1D)
                    pos_ids = (sample_mask.cumsum(dim=0) - 1) * sample_mask
                    metrics["vlm_samples_fallback"] += 1
                
                position_ids_list.append(pos_ids)
                
            except Exception as e:
                # Log per-sample error with context
                error_info = {
                    "sample_idx": i,
                    "error": str(e),
                    "image_grid_thw_shape": sample_igt.shape if sample_igt is not None else None,
                    "input_ids_shape": sample_ids.shape,
                }
                per_sample_errors.append(error_info)
                
                # Use text-only fallback for this sample (1D)
                pos_ids = (sample_mask.cumsum(dim=0) - 1) * sample_mask
                position_ids_list.append(pos_ids)
                metrics["vlm_samples_fallback"] += 1
        
        # Log errors if any occurred
        if per_sample_errors:
            print(
                f"[position_ids] WARNING: {len(per_sample_errors)}/{len(input_ids)} samples "
                f"failed VLM position_ids computation. Using text-only fallback for these.\n"
                f"First error: {per_sample_errors[0]}"
            )
            if len(per_sample_errors) > 1:
                print(f"[position_ids] Additional errors: {per_sample_errors[1:3]}...")
        
        # Concatenate position_ids
        if not position_ids_list:
            print("[position_ids] WARNING: No position_ids computed, using text-only fallback")
            metrics["used_text_only_fallback"] = True
            return (attention_mask.cumsum(dim=1) - 1) * attention_mask, metrics
        
        # Handle mixed dimensionality:
        # - VLM position_ids from get_rope_index: [3, seq_len] (2D)
        # - Text-only fallback: [seq_len] (1D)
        # We need to normalize all to [3, seq_len] for VLM compatibility
        try:
            dims = [p.dim() for p in position_ids_list]
            if len(set(dims)) > 1 or 1 in dims:
                # Mixed dimensions or have 1D - expand 1D to 2D for VLM
                print(
                    f"[position_ids] INFO: Mixed dimensions detected: {dims}. "
                    f"Expanding 1D tensors to 2D (3, seq_len) for VLM compatibility."
                )
                expanded_list = []
                for pos_ids in position_ids_list:
                    if pos_ids.dim() == 1:
                        # Expand [seq_len] to [3, seq_len] for VLM compatibility
                        # Use same position for all 3 dimensions (text-only behavior)
                        pos_ids = pos_ids.unsqueeze(0).expand(3, -1)
                    expanded_list.append(pos_ids)
                position_ids_list = expanded_list
            
            # Stack into batch: each is [3, seq_len] -> [batch, 3, seq_len]
            # verl's dp_actor.py expects (batch, num_dims, seq_length) and transposes internally
            # See dp_actor.py line 115-116: position_ids.transpose(0, 1) for qwen2vl mrope
            if position_ids_list[0].dim() == 2:
                # VLM format: [3, seq_len] -> stack to [batch, 3, seq_len]
                position_ids = torch.stack(position_ids_list, dim=0)
            else:
                # Unexpected - should not happen after normalization
                position_ids = torch.stack(position_ids_list, dim=0)
            
            # For transformers >= 4.54.0, position_ids needs 4 dimensions:
            # (text_pos, temporal_pos, height_pos, width_pos)
            # See: https://github.com/huggingface/transformers/pull/39447
            # Store as (batch, 4, seq) - dp_actor.py will transpose to (4, batch, seq)
            if position_ids.shape[1] == 3:
                # Prepend text position (same as first dim for M-RoPE)
                # Text position is cumulative position based on attention mask
                text_position = (attention_mask.cumsum(dim=1) - 1) * attention_mask  # [batch, seq]
                text_position = text_position.unsqueeze(1)  # [batch, 1, seq]
                position_ids = torch.cat([text_position, position_ids], dim=1)  # [batch, 4, seq]
            
            # Validate shape
            expected_batch = len(input_ids)
            actual_batch = position_ids.shape[0]  # batch is dim 0
            if actual_batch != expected_batch:
                print(
                    f"[position_ids] ERROR: Shape mismatch after concat. "
                    f"Expected batch={expected_batch}, got {actual_batch}. "
                    f"Input shapes: {[p.shape for p in position_ids_list[:3]]}"
                )
                # This is a critical error - raise to prevent silent training issues
                raise ValueError(
                    f"position_ids batch size mismatch: {actual_batch} vs {expected_batch}"
                )
            
            print(
                f"[position_ids] Computed successfully: shape={position_ids.shape}, "
                f"vlm_computed={metrics['vlm_samples_computed']}, "
                f"fallback={metrics['vlm_samples_fallback']}"
            )
            
        except Exception as e:
            print(
                f"[position_ids] ERROR: Failed to concatenate position_ids: {e}\n"
                f"Traceback: {traceback.format_exc()}\n"
                f"Falling back to text-only position_ids for entire batch."
            )
            metrics["used_text_only_fallback"] = True
            metrics["vlm_samples_fallback"] = len(input_ids)
            metrics["vlm_samples_computed"] = 0
            return (attention_mask.cumsum(dim=1) - 1) * attention_mask, metrics
        
        return position_ids, metrics

    def generate_sequences(self, prompts: DataProto) -> DataProto:
        """Generate sequences using skyrl-agent's asyncio-based dispatcher."""
        if self.config.actor_rollout_ref.rollout.free_cache_engine:
            self.wake_up()

        skyagent_output = asyncio.run(
            self.skyagent_generator.run(
                prompts, 
                val_mode=prompts.meta_info.get("val_mode", False)
            )
        )
        output = self._postprocess(skyagent_output)

        if self.config.actor_rollout_ref.rollout.free_cache_engine:
            self.sleep()

        return output

    def wake_up(self):
        """Wake up all rollout replica instances."""
        self._run_all([replica.wake_up() for replica in self.rollout_replicas])

    def sleep(self):
        """Sleep all rollout replica instances."""
        self._run_all([replica.sleep() for replica in self.rollout_replicas])

    def clear_kv_cache(self):
        """Clear all rollout KV cache without sleeping."""
        self._run_all([replica.clear_kv_cache() for replica in self.rollout_replicas])
