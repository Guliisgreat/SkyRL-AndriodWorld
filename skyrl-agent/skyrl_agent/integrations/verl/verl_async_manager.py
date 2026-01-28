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

        if has_vlm_tensors:
            multi_modal_inputs = []
            for pv, igt in zip(inputs["pixel_values"], inputs["image_grid_thw"]):
                if pv is not None and igt is not None:
                    multi_modal_inputs.append({"pixel_values": pv, "image_grid_thw": igt})
                else:
                    multi_modal_inputs.append({})
            non_tensor_batch["multi_modal_inputs"] = np.array(multi_modal_inputs, dtype=object)

            try:
                from verl.models.transformers.qwen2_vl import get_rope_index
                from verl.utils import hf_processor

                if self._vlm_processor is None:
                    local_path = copy_to_local(self.config.actor_rollout_ref.model.path)
                    self._vlm_processor = hf_processor(local_path, trust_remote_code=True, use_fast=True)

                position_ids_list = []
                for i in range(len(input_ids)):
                    sample_ids = input_ids[i:i+1]
                    sample_mask = attention_mask[i:i+1]
                    sample_igt = inputs["image_grid_thw"][i]

                    if sample_igt is not None:
                        if sample_igt.dim() == 2:
                            sample_igt = sample_igt.unsqueeze(0)
                        pos_ids = get_rope_index(
                            self._vlm_processor,
                            input_ids=sample_ids,
                            image_grid_thw=sample_igt,
                            attention_mask=sample_mask,
                        )
                    else:
                        pos_ids = (sample_mask.cumsum(dim=1) - 1) * sample_mask
                    position_ids_list.append(pos_ids)

                if position_ids_list:
                    if position_ids_list[0].dim() == 3:
                        position_ids = torch.cat(position_ids_list, dim=1)
                    else:
                        position_ids = torch.cat(position_ids_list, dim=0)
                else:
                    position_ids = (attention_mask.cumsum(dim=1) - 1) * attention_mask
            except Exception as e:
                print(f"Warning: Error computing VLM position_ids: {e}")
                position_ids = (attention_mask.cumsum(dim=1) - 1) * attention_mask
        else:
            position_ids = (attention_mask.cumsum(dim=1) - 1) * attention_mask

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
            meta_info={"rollout_metrics": inputs["rollout_metrics"], "timing": {}},
        )

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
