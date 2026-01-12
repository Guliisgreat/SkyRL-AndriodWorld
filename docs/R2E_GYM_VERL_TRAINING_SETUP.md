# VERL Training Setup for SkyRL Agent

This document describes the setup and configuration for running VERL (Reinforcement Learning) training with the SkyRL agent on the R2E-gym dataset.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Configuration Changes](#configuration-changes)
4. [Files Created](#files-created)
5. [Directory Structure](#directory-structure)
6. [Running Training](#running-training)
7. [GPU Architecture](#gpu-architecture)
8. [Metrics Explained](#metrics-explained)
9. [Troubleshooting](#troubleshooting)

---

## Overview

The VERL training pipeline trains the SkyRL agent to fix bugs using reinforcement learning. The agent interacts with Docker containers running R2E-gym instances and learns from rewards based on whether bugs are successfully fixed.

### Key Components

- **Model**: Qwen/Qwen3-8B
- **Framework**: VERL (PPO-based RL)
- **Inference**: vLLM with tensor parallelism
- **Training**: FSDP with CPU offloading
- **Environment**: OpenHands runtime containers

---

## Prerequisites

### 1. Docker Buildx

Docker buildx is required for building OpenHands runtime images:

```bash
mkdir -p ~/.docker/cli-plugins
curl -SL https://github.com/docker/buildx/releases/download/v0.19.3/buildx-v0.19.3.linux-amd64 \
     -o ~/.docker/cli-plugins/docker-buildx
chmod +x ~/.docker/cli-plugins/docker-buildx
```

### 2. Pre-built Runtime Images

OpenHands wraps base R2E-gym images with additional layers. Pre-build all 109 runtime images before training:

```bash
cd /shared/ligu/projects/SkyRL/skyrl-agent
python prebuild_openhands_runtimes.py
```

This takes ~3-4 hours but only needs to be done once. Images are cached locally.

### 3. Environment File

Ensure the `.env` file exists in the working directory:

```bash
# Create symlink if running from examples/run_verl/
ln -s /shared/ligu/projects/SkyRL/skyrl-agent/.env \
      /shared/ligu/projects/SkyRL/skyrl-agent/examples/run_verl/.env
```

---

## Configuration Changes

### Training Script: `examples/run_verl/verl_oh.sh`

The following paths were updated from `/mnt/local_storage` to `/shared/ligu/data`:

```bash
# Checkpoint directory
trainer.default_local_dir=/shared/ligu/data/ckpts/skyagent-32b-r2e-verl/skyagent-verl-30b-r2e-4500-loop-sep27

# Rollout data directories
trainer.rollout_data_dir=/shared/ligu/data/rollouts/verl_grpo_skyagent/qwen2.5_1.5b_function_rm
trainer.validation_data_dir=/shared/ligu/data/rollouts/verl_grpo_skyagent/qwen2.5_1.5b_function_rm_val
```

### Key Training Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `actor_rollout_ref.model.path` | `Qwen/Qwen3-8B` | Base model |
| `trainer.n_gpus_per_node` | `8` | Number of GPUs |
| `actor_rollout_ref.actor.ulysses_sequence_parallel_size` | `2` | Sequence parallelism |
| `actor_rollout_ref.rollout.tensor_model_parallel_size` | `2` | Tensor parallelism |
| `actor_rollout_ref.rollout.enforce_eager` | `True` | Disable CUDA graphs (fixes OOM) |
| `actor_rollout_ref.actor.fsdp_config.param_offload` | `True` | Offload params to CPU |
| `actor_rollout_ref.actor.fsdp_config.optimizer_offload` | `True` | Offload optimizer to CPU |
| `actor_rollout_ref.rollout.free_cache_engine` | `True` | Free KV cache during training |
| `data.train_batch_size` | `8` | Instances per batch |
| `actor_rollout_ref.rollout.n` | `2` | Trajectories per instance |
| `trainer.total_epochs` | `15` | Total training epochs |

---

## Source Code Changes

### 1. VERL Trainer: `skyrl_agent/integrations/verl/verl_trainer.py`

Added `ResourcePoolManager` to the imports from `verl.trainer.ppo.ray_trainer`:

```diff
-from verl.trainer.ppo.ray_trainer import Role, compute_advantage, RayPPOTrainer
+from verl.trainer.ppo.ray_trainer import Role, compute_advantage, RayPPOTrainer, ResourcePoolManager
```

This import is required for managing GPU resource pools in the co-located worker architecture.

---

## Files Created

### 1. Pre-build Script: `prebuild_openhands_runtimes.py`

```python
#!/usr/bin/env python3
"""
Pre-build OpenHands runtime images for all R2E-gym instances in the filtered dataset.
This avoids the need to build images during training.
"""

import os
import sys

os.environ['OH_RUNTIME_RUNTIME_IMAGE_REPO'] = 'docker.io/xingyaoww/runtime'
sys.path.insert(0, '/shared/ligu/projects/SkyRL-OpenHands')

import docker
import pandas as pd
from openhands.runtime.utils.runtime_build import build_runtime_image, get_hash_for_lock_files
from openhands.runtime.builder.docker import DockerRuntimeBuilder
from openhands import __version__ as oh_version

def get_base_images_from_dataset(data_path: str) -> list[str]:
    df = pd.read_parquet(data_path)
    images = set()
    for idx, row in df.iterrows():
        instance = row['instance']
        if isinstance(instance, dict):
            instance_id = instance['instance_id']
        else:
            instance_id = instance
        images.add(instance_id)
    return sorted(images)

def build_single_image(base_image: str, builder: DockerRuntimeBuilder):
    try:
        result = build_runtime_image(
            base_image=base_image,
            runtime_builder=builder,
            platform=None,
            extra_deps=None,
            force_rebuild=False,
        )
        return (base_image, True, f"Built: {result}")
    except Exception as e:
        return (base_image, False, str(e))

def main():
    data_path = "/shared/ligu/data/swe-data/train_filtered.parquet"
    print(f"Using runtime image repo: {os.environ['OH_RUNTIME_RUNTIME_IMAGE_REPO']}")
    print(f"OpenHands version: {oh_version}")

    base_images = get_base_images_from_dataset(data_path)
    print(f"Found {len(base_images)} unique base images")

    docker_client = docker.from_env()
    builder = DockerRuntimeBuilder(docker_client)

    for i, base_image in enumerate(base_images):
        repo = os.environ['OH_RUNTIME_RUNTIME_IMAGE_REPO']
        lock_tag = f'oh_v{oh_version}_{get_hash_for_lock_files(base_image)}'
        target_image = f'{repo}:{lock_tag}'

        print(f"\n[{i+1}/{len(base_images)}] {base_image}")

        if builder.image_exists(target_image, pull_from_repo=False):
            print(f"  [SKIP] Already exists")
            continue

        image, success, message = build_single_image(base_image, builder)
        print(f"  [{'OK' if success else 'FAIL'}] {message[:200]}")

if __name__ == "__main__":
    main()
```

### 2. Filtered Dataset: `/shared/ligu/data/swe-data/train_filtered.parquet`

Created by filtering the original dataset to only include instances with locally available Docker images:
- Original: 4,578 instances
- Filtered: 109 instances

---

## Directory Structure

```
/shared/ligu/data/
├── swe-data/
│   ├── train_filtered.parquet      # 109 filtered training instances
│   └── validation.parquet          # 500 validation instances
├── ckpts/
│   └── skyagent-32b-r2e-verl/
│       └── skyagent-verl-30b-r2e-4500-loop-sep27/
│           ├── global_step_1/      # Checkpoint after step 1
│           ├── global_step_2/      # Checkpoint after step 2
│           └── ...
└── rollouts/
    └── verl_grpo_skyagent/
        ├── qwen2.5_1.5b_function_rm/      # Training rollout data
        └── qwen2.5_1.5b_function_rm_val/  # Validation rollout data
```

---

## Running Training

### Start Training

```bash
cd /shared/ligu/projects/SkyRL/skyrl-agent
bash examples/run_verl/verl_oh.sh
```

**Important**: Run from the `skyrl-agent` directory, NOT from `examples/run_verl/`.

### Resume from Checkpoint

Training automatically resumes from the latest checkpoint. The checkpoint path is read from:
```
/shared/ligu/data/ckpts/skyagent-32b-r2e-verl/skyagent-verl-30b-r2e-4500-loop-sep27/latest_checkpointed_iteration.txt
```

### Monitor Training

```bash
# Watch logs
tail -f /tmp/claude/.../tasks/<task_id>.output

# Check W&B dashboard
# https://wandb.ai/guliisgreat6868/skyagent-32b-r2e
```

---

## GPU Architecture

### Worker Allocation (8 GPUs, TP=2, SP=2)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            8 GPUs LAYOUT                                │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐               │
│  │  GPU 0    │ │  GPU 1    │ │  GPU 2    │ │  GPU 3    │               │
│  │  ACTOR    │ │  ACTOR    │ │  ACTOR    │ │  ACTOR    │               │
│  │  vLLM 0   │─│  (TP)     │ │  vLLM 1   │─│  (TP)     │               │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘               │
│                                                                         │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐               │
│  │  GPU 4    │ │  GPU 5    │ │  GPU 6    │ │  GPU 7    │               │
│  │  ACTOR    │ │  ACTOR    │ │  ACTOR    │ │  ACTOR    │               │
│  │  vLLM 2   │─│  (TP)     │ │  vLLM 3   │─│  (TP)     │               │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘               │
│                                                                         │
│  Formula: num_vllm_engines = num_gpus / TP_SIZE = 8 / 2 = 4            │
└─────────────────────────────────────────────────────────────────────────┘
```

### Co-located Workers

Training (FSDP) and inference (vLLM) share the same GPUs via time-multiplexing:

1. **Rollout Phase**: vLLM active, KV cache allocated (~50GB), optimizer offloaded to CPU
2. **Training Phase**: FSDP active, KV cache freed, optimizer loaded from CPU
3. **Key Benefit**: No weight transfer needed - same memory used for both

---

## Metrics Explained

### Rollout Metrics

| Metric | Description | Goal |
|--------|-------------|------|
| `raw_reward` | Fraction of trajectories that fixed bugs | Higher |
| `num_all_resolved` | Instances where ALL trajectories succeeded | Higher |
| `finish_tool_ratio` | Fraction of agents that submitted a solution | Higher |
| `stuck_in_a_loop_ratio` | Fraction of agents that got stuck | Lower |
| `context_exceed_ratio` | Fraction of agents that exceeded context | Lower |

### Training Metrics

| Metric | Description |
|--------|-------------|
| `actor/pg_loss` | Policy gradient loss |
| `actor/entropy` | Action entropy (exploration) |
| `actor/grad_norm` | Gradient norm |
| `critic/rewards/mean` | Average reward |
| `perf/throughput` | Tokens per second |

---

## Troubleshooting

### Issue: CUDA Out of Memory

**Solution**: Enable eager mode to disable CUDA graphs:
```bash
actor_rollout_ref.rollout.enforce_eager=True
```

### Issue: Docker Build Fails (Status 125)

**Solution**: Install docker buildx and pre-build images:
```bash
# Install buildx
mkdir -p ~/.docker/cli-plugins
curl -SL https://github.com/docker/buildx/releases/download/v0.19.3/buildx-v0.19.3.linux-amd64 \
     -o ~/.docker/cli-plugins/docker-buildx
chmod +x ~/.docker/cli-plugins/docker-buildx

# Pre-build images
python prebuild_openhands_runtimes.py
```

### Issue: Missing .env File

**Solution**: Create symlink or run from correct directory:
```bash
cd /shared/ligu/projects/SkyRL/skyrl-agent
bash examples/run_verl/verl_oh.sh
```

### Issue: Permission Denied on /mnt/local_storage

**Solution**: Update paths in `verl_oh.sh` to use `/shared/ligu/data/`.

### Issue: Disk Space Low on /tmp/ray

**Solution**: Clean up old Ray sessions:
```bash
rm -rf /tmp/ray/session_*
```

---

## Training Results (Example Run)

| Step | raw_reward | bugs_resolved | finish_ratio | time |
|------|------------|---------------|--------------|------|
| 1 | 0.00 | 0 | 25% | 346s |
| 2 | 0.25 | 0 | 37.5% | 380s |
| 3 | 0.0625 | 0 | 25% | 405s |
| 4 | **0.375** | **3** | 37.5% | 380s |
| 5 | 0.1875 | 1 | 37.5% | 496s |
| 6 | 0.125 | 1 | 50% | 395s |

**Estimated total training time**: ~20 hours for 195 steps (15 epochs).

---

## References

- [VERL Documentation](https://github.com/volcengine/verl)
- [OpenHands Documentation](https://github.com/All-Hands-AI/OpenHands)
- [R2E-gym Dataset](https://github.com/r2e-project/r2e-gym)
- [W&B Project Dashboard](https://wandb.ai/guliisgreat6868/skyagent-32b-r2e)
