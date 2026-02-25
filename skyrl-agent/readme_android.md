# AndroidWorld Training & Inference Guide

This guide explains how to run **GRPO training** and **inference evaluation** for AndroidWorld tasks using the SkyRL agent framework with verl.

## Prerequisites

1. **Docker** with KVM support running
2. **Android emulator image**: `androidworld:v8` available locally
3. **GPU**: At least 4x A100/H100 80GB GPUs (for training)
4. **Python environment**: Managed via `uv` with verl extras installed
5. **Environment file**: `.env` with required API keys (e.g., Wandb)
6. **Test data**: JSONL files in `data/androidworld_generalization/`

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    verl GRPO Trainer                     │
│  ┌──────────┐   ┌──────────┐   ┌─────────────────────┐ │
│  │  FSDP    │   │  vLLM    │   │   Android Containers│ │
│  │ Training │◄──│ Rollout  │◄──│   (16 emulators)    │ │
│  │ (4 GPUs) │   │ (TP=2)   │   │   via Docker        │ │
│  └──────────┘   └──────────┘   └─────────────────────┘ │
│       ▲              │                    │              │
│       │         mode=async           Agent loop         │
│       │      (time-shared GPUs)    (up to 30 steps)     │
│       └──────────────┘                    │              │
│            Weights updated           Reward: 0/1        │
│            via GRPO loss          (task success)         │
└─────────────────────────────────────────────────────────┘
```

Training and inference share GPUs via **async mode** — vLLM handles generation during rollouts, then frees memory (`free_cache_engine=True`) for FSDP training.

---

## Inference (Evaluation Only)

**Script**: `examples/run_verl/verl_android_inference.sh`

Run inference to evaluate the base model (or a checkpoint) on AndroidWorld tasks without any training.

### Quick Start

```bash
cd skyrl-agent

# Run with default test data
bash examples/run_verl/verl_android_inference.sh

# Run with custom test data
bash examples/run_verl/verl_android_inference.sh ./data/my_test.jsonl
```

### Configuration

The script auto-detects available GPUs (>50GB free). Override with:

```bash
# Use specific GPUs
export CUDA_VISIBLE_DEVICES=0,1,2,3

# Change environment pool size (default: 16)
export ENV_POOL_SIZE=8

bash examples/run_verl/verl_android_inference.sh
```

### Key Parameters

| Parameter | Default | Description |
|---|---|---|
| `ENV_POOL_SIZE` | 16 | Number of Android containers for parallel evaluation |
| `rollout.n` | 1 | Trajectories per instance (1 for deterministic eval) |
| `rollout.gpu_memory_utilization` | 0.6 | vLLM KV cache memory fraction |
| `rollout.tensor_model_parallel_size` | 1 | Tensor parallelism for vLLM |

### Output

Results are saved to:
- **Metrics**: `./results/final_metrics.json`
- **Trajectories**: `./results/0.jsonl`
- **Rollout data**: `./results/rollouts/`

### Config File

The inference YAML config is at `examples/run_verl/verl_android_inference.yaml`. Key differences from training:
- `val_config.num_trajectories: 1` — single trajectory per instance
- `val_config.sampling_params.temperature: 0.7` — lower temperature for more deterministic output

---

## Training (GRPO)

**Script**: `examples/run_verl/verl_android_wandb.sh`

Run GRPO (Group Relative Policy Optimization) training on AndroidWorld tasks with Wandb logging.

### Quick Start

```bash
cd skyrl-agent

# Start training
bash examples/run_verl/verl_android_wandb.sh
```

### Running in Background (Recommended)

```bash
# Run in tmux for long training sessions
tmux new-session -d -s train \
  "cd /path/to/skyrl-agent && bash examples/run_verl/verl_android_wandb.sh 2>&1 | tee train.log"

# Attach to monitor
tmux attach -t train

# Or check log directly
tail -f train.log
```

### Key Training Parameters

#### Data & Batching

| Parameter | Value | Description |
|---|---|---|
| `data.train_batch_size` | 2 | Task instances sampled per step |
| `data.max_prompt_length` | 28672 | Max prompt tokens |
| `data.max_response_length` | 4096 | Max response tokens per generation |

#### Model & Training

| Parameter | Value | Description |
|---|---|---|
| `actor.ppo_mini_batch_size` | 1 | Samples per optimizer step (1 avoids cross-sample padding OOM) |
| `actor.ppo_micro_batch_size_per_gpu` | 1 | Samples per GPU per forward pass |
| `actor.ppo_epochs` | 1 | PPO epochs per training step |
| `actor.optim.lr` | 1e-6 | Learning rate |
| `actor.fsdp_config.param_offload` | True | Offload params to CPU |
| `actor.fsdp_config.optimizer_offload` | True | Offload optimizer states to CPU |
| `model.enable_gradient_checkpointing` | True | Recompute activations to save memory |

#### Rollout (vLLM Inference)

| Parameter | Value | Description |
|---|---|---|
| `rollout.n` | 8 | Trajectories per task instance |
| `rollout.gpu_memory_utilization` | 0.4 | vLLM KV cache fraction (freed before training) |
| `rollout.tensor_model_parallel_size` | 2 | Tensor parallelism across GPUs |
| `rollout.mode` | async | Time-share GPUs between rollout and training |

#### Environment

| Parameter | Value | Description |
|---|---|---|
| `env_pool_size` | 16 | Android Docker containers |
| `num_trajectories` | 8 | Parallel trajectories per instance |

#### Trainer

| Parameter | Value | Description |
|---|---|---|
| `trainer.total_training_steps` | 15 | Total training iterations |
| `trainer.save_freq` | 5 | Checkpoint save frequency |
| `trainer.n_gpus_per_node` | 4 | GPUs to use |
| `trainer.resume_mode` | auto | Auto-resume from last checkpoint |

### Customizing the Run

Edit `verl_android_wandb.sh` to change parameters. Common adjustments:

```bash
# Change number of GPUs
export CUDA_VISIBLE_DEVICES=0,1      # Use 2 GPUs
trainer.n_gpus_per_node=2

# Change training duration
trainer.total_training_steps=50

# Change batch size and trajectories
data.train_batch_size=4              # More instances per step
actor_rollout_ref.rollout.n=4        # Fewer trajectories per instance
+skyrl_agent.num_trajectories=4
+skyrl_agent.env_pool_size=8         # Should be >= batch_size * num_trajectories

# Change experiment name (creates fresh wandb run)
trainer.experiment_name='my-experiment'

# Change checkpoint directory
CKPT_DIR="${OUTPUT_BASE}/ckpts/my-experiment"
```

### Agent & Environment Config

The YAML config at `examples/run_verl/verl_android.yaml` controls agent behavior:

| Section | Key Parameters |
|---|---|
| `data.max_pixels` | 564480 — image resolution for screenshots |
| `env.pool_size` | 16 — Docker container pool |
| `env.docker_image` | androidworld:v8 |
| `generator.max_iterations` | 30 — max agent steps per trajectory |
| `generator.max_history_steps` | 10 — sliding window for context |
| `generator.training_strategy` | early — stop when token budget reached |
| `dispatcher.max_parallel_agents` | 16 — concurrent agents |

### Memory & OOM Considerations

The biggest factor in GPU memory is the **padded sequence length** during training. Key settings to prevent OOM:

1. **`ppo_mini_batch_size=1`**: Process one sample at a time to avoid cross-sample padding
2. **`max_pixels=564480`**: Lower image resolution reduces tokens per screenshot (~1.78x fewer than high-res)
3. **`param_offload=True` + `optimizer_offload=True`**: Offload model weights and optimizer states to CPU
4. **`enable_gradient_checkpointing=True`**: Trade compute for memory during backward pass
5. **`free_cache_engine=True`**: Release vLLM KV cache before training phase

If OOM persists, try:
- Reduce `generator.max_iterations` (fewer agent steps = shorter sequences)
- Reduce `data.max_pixels` further
- Enable `ulysses_sequence_parallel_size=2` (splits sequences across GPUs, but requires even sequence lengths)

### Monitoring

```bash
# Check training progress
grep "Training Progress" train.log | tail -1

# Check rewards per step
grep "raw_reward" train.log

# Check GPU memory
grep "max_memory_allocated_gb" train.log

# Check sequence lengths
grep "position_ids.*shape" train.log

# Monitor via wandb
# Visit https://wandb.ai and look for project "skyagent-android"
```

### Checkpoints

Checkpoints are saved every `save_freq` steps to the configured `CKPT_DIR`:

```
tmp_training/ckpts/skyagent-android-50step-mb1/
├── global_step_5/
├── global_step_10/
└── global_step_15/
```

To resume from a checkpoint, set `trainer.resume_mode=auto` (default) — the trainer automatically finds the latest checkpoint in `CKPT_DIR`.

---

## Per-Step Pipeline

Each training step follows this pipeline:

```
1. Sample batch_size=2 task instances from training data
2. For each instance, launch 8 trajectories across 16 containers
3. Each trajectory: agent interacts with Android emulator (up to 30 steps)
4. Collect rewards (0 or 1 per trajectory based on task success)
5. Compute advantages using GRPO (group relative)
6. Update model weights via PPO loss (mini_batch=1, 16 optimizer steps)
7. Log metrics to wandb and console
```

Typical timing per step: **5-10 minutes** (rollout ~4-5 min, training ~1 min).
