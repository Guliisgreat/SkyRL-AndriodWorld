# Copyright 2024 Bytedance Ltd. and/or its affiliates
# Inference-only entry point for AndroidWorld evaluation
"""
Inference-only script that runs evaluation on the test set without training.
Uses vLLM for efficient inference with VLM models.
"""

# IMPORTANT: Import compat patch BEFORE any verl imports
from . import verl_compat_patch  # noqa: F401

# Register the verl_061 backend (overrides old verl backend for 0.6.1 TokenOutput API)
from . import VeRLBackend  # noqa: F401  - triggers registration in __init__.py

import os
import socket
import sys

import hydra
import ray
from omegaconf import OmegaConf
from loguru import logger

from verl.trainer.main_ppo import get_ppo_ray_runtime_env
from verl.utils.device import is_cuda_available

from .verl_trainer import SkyAgentPPOTrainer
import torch
from collections import defaultdict


from verl.workers.reward_manager import register
from verl.protocol import DataProto
from verl.trainer.main_ppo import create_rl_dataset, create_rl_sampler

# Get verl config directory path
import verl
config_dir = os.path.join(os.path.dirname(verl.__file__), "trainer", "config")


def setup_wandb_logging(config):
    """Setup wandb logging for both metrics and loguru logs.
    
    Returns:
        wandb run object if enabled, None otherwise.
    """
    loggers = config.trainer.get("logger", ["console"])
    if isinstance(loggers, str):
        loggers = [loggers]
    
    if "wandb" not in loggers:
        return None
    
    try:
        import wandb
        
        # Initialize wandb if not already done
        if wandb.run is None:
            entity = os.environ.get("WANDB_ENTITY", None)
            wandb.init(
                project=config.trainer.project_name,
                name=config.trainer.experiment_name,
                entity=entity,
                config=OmegaConf.to_container(config, resolve=True),
            )
        
        # Add loguru sink to wandb
        def wandb_sink(message):
            """Send loguru logs to wandb."""
            record = message.record
            level = record["level"].name
            msg = record["message"]
            
            # Log as wandb alert for errors/warnings, otherwise as console output
            if level in ("ERROR", "CRITICAL"):
                wandb.alert(title=f"[{level}]", text=msg[:500], level=wandb.AlertLevel.ERROR)
            elif level == "WARNING":
                wandb.alert(title=f"[{level}]", text=msg[:500], level=wandb.AlertLevel.WARN)
            
            # Also log to wandb console (captured in logs tab)
            print(message, end="")  # wandb captures stdout
        
        # Add wandb sink to loguru (only for INFO and above to avoid spam)
        logger.add(
            wandb_sink, 
            level="INFO",
            format="{time:HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
            filter=lambda record: record["level"].no >= logger.level("INFO").no
        )
        
        print(f"WandB logging enabled: {wandb.run.url}")
        return wandb
        
    except ImportError:
        print("Warning: wandb not installed, skipping wandb logging")
        return None
    except Exception as e:
        print(f"Warning: Failed to setup wandb logging: {e}")
        return None


@register("skyagent")
class SkyAgentInferenceRewardManager:
    """The reward manager for inference mode."""

    def __init__(self, tokenizer, num_examine, compute_score=None, reward_fn_key="data_source") -> None:
        self.tokenizer = tokenizer
        self.num_examine = num_examine
        self.reward_fn_key = reward_fn_key

    def __call__(self, data: DataProto, return_dict=False):
        """Compute rewards from pre-computed values in the batch."""
        if "rm_scores" in data.batch.keys():
            if return_dict:
                return {"reward_tensor": data.batch["rm_scores"]}
            else:
                return data.batch["rm_scores"]

        reward_tensor = torch.zeros_like(data.batch["responses"], dtype=torch.float32)
        reward_extra_info = defaultdict(list)

        print(
            f"In Reward manager: data proto batch keys: {data.batch.keys()}, "
            f"non tensor batch keys: {data.non_tensor_batch.keys()} "
            f"meta info keys: {data.meta_info.keys()}"
        )

        for i in range(len(data)):
            data_item = data[i]
            prompt_ids = data_item.batch["prompts"]
            prompt_length = prompt_ids.shape[-1]
            valid_prompt_length = data_item.batch["attention_mask"][:prompt_length].sum()

            response_ids = data_item.batch["responses"]
            valid_response_length = data_item.batch["attention_mask"][prompt_length:].sum()

            reward_tensor[i, valid_response_length - 1] = float(data_item.non_tensor_batch["rewards"])

        if return_dict:
            return {
                "reward_tensor": reward_tensor,
                "reward_extra_info": reward_extra_info,
            }
        else:
            return reward_tensor


@hydra.main(config_path=config_dir, config_name="ppo_trainer", version_base=None)
def main(config):
    """Main entry point for inference-only evaluation."""
    run_inference(config)


def run_inference(config) -> None:
    """Initialize Ray cluster and run inference-only evaluation.

    Args:
        config: Configuration object containing all necessary parameters.
    """
    if not ray.is_initialized():
        default_runtime_env = get_ppo_ray_runtime_env()
        ray_init_kwargs = config.ray_kwargs.get("ray_init", {})
        runtime_env_kwargs = ray_init_kwargs.get("runtime_env", {})

        runtime_env_vars = runtime_env_kwargs.get("env_vars", {})
        runtime_env_vars["VLLM_USE_V1"] = os.environ.get("VLLM_USE_V1", "0")

        if os.environ.get("CUDA_VISIBLE_DEVICES", None):
            print(f"Exporting `CUDA_VISIBLE_DEVICES={os.environ['CUDA_VISIBLE_DEVICES']}` to Ray workers")
            runtime_env_vars["CUDA_VISIBLE_DEVICES"] = os.environ["CUDA_VISIBLE_DEVICES"]

        if os.environ.get("LD_LIBRARY_PATH", None):
            print("Exporting `LD_LIBRARY_PATH` from driver")
            runtime_env_vars["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH"]

        runtime_env_kwargs["env_vars"] = runtime_env_vars
        runtime_env = OmegaConf.merge(default_runtime_env, runtime_env_kwargs)
        ray_init_kwargs = OmegaConf.create({**ray_init_kwargs, "runtime_env": runtime_env})
        print(f"ray init kwargs: {ray_init_kwargs}")
        ray.init(**OmegaConf.to_container(ray_init_kwargs))

    # Store CUDA_VISIBLE_DEVICES in config
    if os.environ.get("CUDA_VISIBLE_DEVICES", None):
        OmegaConf.set_struct(config.skyrl_agent, False)
        config.skyrl_agent.cuda_visible_devices = os.environ["CUDA_VISIBLE_DEVICES"]
        OmegaConf.set_struct(config.skyrl_agent, True)
        print(f"Added CUDA_VISIBLE_DEVICES={os.environ['CUDA_VISIBLE_DEVICES']} to config")

    task_runner_runtime_env = {}
    if os.environ.get("CUDA_VISIBLE_DEVICES", None):
        task_runner_runtime_env["env_vars"] = {"CUDA_VISIBLE_DEVICES": os.environ["CUDA_VISIBLE_DEVICES"]}
        print(f"TaskRunner will use CUDA_VISIBLE_DEVICES={os.environ['CUDA_VISIBLE_DEVICES']}")

    runner = InferenceRunner.options(runtime_env=task_runner_runtime_env).remote() if task_runner_runtime_env else InferenceRunner.remote()

    task = runner.run.remote(config)
    try:
        ray.get(task)
    except KeyboardInterrupt:
        print("KeyboardInterrupt received, shutting down...")
        ray.cancel(task)
        raise


@ray.remote(num_cpus=1)
class InferenceRunner:
    """Ray remote class for inference-only evaluation."""

    def run(self, config):
        """Execute inference-only evaluation workflow."""
        from pprint import pprint
        from omegaconf import OmegaConf
        from verl.utils.fs import copy_to_local

        print(f"SkyAgent InferenceRunner hostname: {socket.gethostname()}, PID: {os.getpid()}")
        pprint(OmegaConf.to_container(config, resolve=True))
        OmegaConf.resolve(config)
        
        # Setup wandb logging (also captures loguru logs)
        self.wandb = setup_wandb_logging(config)

        # Validate skyagent config
        if getattr(config, "skyrl_agent", None) is not None:
            task_yaml = getattr(config.skyrl_agent, "task_yaml")
            import yaml
            with open(task_yaml, "r") as f:
                print("Using Skyrl-agent inference mode")
                skyagent_config = OmegaConf.create(yaml.safe_load(f))
                assert (
                    config.skyrl_agent.num_trajectories == skyagent_config.generator.num_trajectories
                ), f"Trajectory mismatch: config={config.skyrl_agent.num_trajectories}, yaml={skyagent_config.generator.num_trajectories}"

        # Download model
        print(f"[{socket.gethostname()}] Loading model from: {config.actor_rollout_ref.model.path}")
        import time
        start_time = time.time()
        local_path = copy_to_local(
            config.actor_rollout_ref.model.path,
            use_shm=config.actor_rollout_ref.model.get("use_shm", False),
            verbose=True,
        )
        print(f"[{socket.gethostname()}] Model loaded in {time.time() - start_time:.2f} seconds")

        # Initialize tokenizer and processor
        from verl.utils import hf_processor, hf_tokenizer
        trust_remote_code = config.data.get("trust_remote_code", False)
        tokenizer = hf_tokenizer(local_path, trust_remote_code=trust_remote_code)
        processor = hf_processor(local_path, trust_remote_code=trust_remote_code, use_fast=True)

        # Setup worker classes for inference (minimal setup)
        if config.actor_rollout_ref.actor.strategy in {"fsdp", "fsdp2"}:
            from verl.single_controller.ray import RayWorkerGroup
            from verl.workers.fsdp_workers import ActorRolloutRefWorker, AsyncActorRolloutRefWorker, CriticWorker

            actor_rollout_cls = (
                AsyncActorRolloutRefWorker
                if config.actor_rollout_ref.rollout.mode == "async"
                else ActorRolloutRefWorker
            )
            ray_worker_group_cls = RayWorkerGroup
        else:
            raise NotImplementedError(f"Strategy {config.actor_rollout_ref.actor.strategy} not supported")

        from .verl_trainer import ResourcePoolManager, Role

        role_worker_mapping = {
            Role.ActorRollout: ray.remote(actor_rollout_cls),
            Role.Critic: ray.remote(CriticWorker),  # Required by verl, but won't be used
        }

        global_pool_id = "global_pool"
        resource_pool_spec = {
            global_pool_id: [config.trainer.n_gpus_per_node] * config.trainer.nnodes,
        }
        mapping = {
            Role.ActorRollout: global_pool_id,
            Role.Critic: global_pool_id,
        }

        # Reward manager
        reward_fn = SkyAgentInferenceRewardManager(tokenizer, num_examine=0)
        val_reward_fn = SkyAgentInferenceRewardManager(tokenizer, num_examine=1)
        resource_pool_manager = ResourcePoolManager(resource_pool_spec=resource_pool_spec, mapping=mapping)

        from verl.utils.dataset.rl_dataset import collate_fn

        # Create validation dataset only (test set)
        train_dataset = create_rl_dataset(config.data.train_files, config.data, tokenizer, processor, is_train=True)
        val_dataset = create_rl_dataset(config.data.val_files, config.data, tokenizer, processor, is_train=False)
        train_sampler = create_rl_sampler(config.data, train_dataset)

        # Initialize trainer in inference mode
        trainer = SkyAgentPPOTrainer(
            config=config,
            tokenizer=tokenizer,
            processor=processor,
            role_worker_mapping=role_worker_mapping,
            resource_pool_manager=resource_pool_manager,
            ray_worker_group_cls=ray_worker_group_cls,
            reward_fn=reward_fn,
            val_reward_fn=val_reward_fn,
            train_dataset=train_dataset,
            val_dataset=val_dataset,
            collate_fn=collate_fn,
            train_sampler=train_sampler,
            device_name=config.trainer.device,
        )

        # Initialize workers (loads model for inference)
        trainer.init_workers()

        # Run validation only
        print("\n" + "="*60)
        print("STARTING INFERENCE-ONLY EVALUATION")
        print("="*60 + "\n")

        val_metrics = trainer._validate()

        print("\n" + "="*60)
        print("INFERENCE COMPLETE")
        print("="*60)
        pprint(f"Validation metrics: {val_metrics}")

        # Save final metrics
        import json
        output_dir = config.trainer.get("validation_data_dir", "/tmp/inference_results")
        os.makedirs(output_dir, exist_ok=True)
        metrics_file = os.path.join(output_dir, "final_metrics.json")
        with open(metrics_file, "w") as f:
            json.dump(val_metrics, f, indent=2)
        print(f"Metrics saved to: {metrics_file}")
        
        # Log final metrics to wandb
        if self.wandb is not None:
            # Log metrics
            self.wandb.log(val_metrics, step=0)
            
            # Save the metrics file as artifact
            artifact = self.wandb.Artifact(
                name=f"inference-results-{config.trainer.experiment_name}",
                type="results"
            )
            artifact.add_file(metrics_file)
            self.wandb.log_artifact(artifact)
            
            # Also save the JSONL if it exists
            jsonl_file = os.path.join(output_dir, "0.jsonl")
            if os.path.exists(jsonl_file):
                artifact_jsonl = self.wandb.Artifact(
                    name=f"generations-{config.trainer.experiment_name}",
                    type="generations"
                )
                artifact_jsonl.add_file(jsonl_file)
                self.wandb.log_artifact(artifact_jsonl)
            
            # Finish wandb run (capture URL before finish() since wandb.run is None afterward)
            run = getattr(self.wandb, "run", None)
            run_url = run.url if run is not None else "N/A"
            self.wandb.finish()
            print(f"WandB run finished: {run_url}")


if __name__ == "__main__":
    main()
