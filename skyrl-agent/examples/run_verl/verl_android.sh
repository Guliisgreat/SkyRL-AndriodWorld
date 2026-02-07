#!/bin/bash
# verl_android.sh - Launch script for Android/AndroidWorld training with verl
#
# Usage: ./verl_android.sh [additional_args]
#
# Prerequisites:
# 1. Docker is running with KVM support
# 2. androidworld:v8 Docker image is available
# 3. Training data is available in JSONL format (one JSON object per line)

set -x

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Change to project root directory (required for relative paths in config)
cd "${PROJECT_ROOT}" || exit 1

# Apply vLLM patch for qwen2_vl.py CUDA device bug (vLLM 0.11.0)
"${PROJECT_ROOT}/scripts/patch_vllm.sh" 2>/dev/null || true

# Enable vLLM V1 engine (required for verl async mode)
export VLLM_USE_V1=1

# Set Ray temp directory to /shared to avoid /tmp disk space issues
# Use short path to avoid AF_UNIX socket path length limit (107 bytes)
export RAY_TMPDIR=/shared/tmp/ray
mkdir -p ${RAY_TMPDIR}

# Increase Ray disk space threshold to avoid "over 95% full" warnings
export RAY_object_spilling_threshold=0.99

# === Data Configuration ===
# Dataset stored in repo: data/androidworld_generalization/unseen_task_instance/
# Note: AndroidWorldDataset expects JSONL format (one JSON object per line)
DATA_DIR="./data/androidworld_generalization/unseen_task_instance"
train_data="${DATA_DIR}/train.jsonl"
test_data="${DATA_DIR}/test.jsonl"

# Validate data files exist
if [ ! -f "$train_data" ]; then
    echo "ERROR: Training data file not found: $train_data"
    exit 1
fi
if [ ! -f "$test_data" ]; then
    echo "ERROR: Test data file not found: $test_data"
    exit 1
fi
echo "✓ Data files validated:"
echo "  - Train: $train_data ($(wc -l < "$train_data") lines)"
echo "  - Test: $test_data ($(wc -l < "$test_data") lines)"

# === Model Configuration ===
# Use UI-TARS for vision-language UI automation tasks (same as inference)
MODEL=ByteDance-Seed/UI-TARS-7B-SFT
# MODEL=Qwen/Qwen2-VL-7B-Instruct  # Alternative: general VLM
# MODEL=Qwen/Qwen2-VL-2B-Instruct  # Smaller model for testing

# === Distributed Training Configuration ===
NNODES=1
SP_SIZE=1
TP_SIZE=1
# For larger clusters:
# NNODES=4
# SP_SIZE=2
# TP_SIZE=4

# === Environment Pool Configuration ===
# Number of Docker containers in the pool
# Will be adjusted based on available GPUs below
ENV_POOL_SIZE=8

# === Context Length Configuration ===
# IMPORTANT: verl calculates max_model_len = max_prompt_length + max_response_length
# To get 32768 tokens total: 28672 + 4096 = 32768
# This is required for long AndroidWorld trajectories with many screenshots

# === Storage Configuration ===
# Create output directories if they don't exist
OUTPUT_BASE=/shared/ligu/projects/SkyRL-AndriodWorld/tmp_training
CKPT_DIR="${OUTPUT_BASE}/ckpts/skyagent-android"
ROLLOUT_DIR="${OUTPUT_BASE}/rollouts/skyagent-android"
VAL_DIR="${OUTPUT_BASE}/rollouts/skyagent-android-val"

mkdir -p "${CKPT_DIR}" "${ROLLOUT_DIR}" "${VAL_DIR}"
echo "✓ Output directories created:"
echo "  - Checkpoints: ${CKPT_DIR}"
echo "  - Rollouts: ${ROLLOUT_DIR}"
echo "  - Validation: ${VAL_DIR}"

# === GPU Configuration ===
# Set CUDA_VISIBLE_DEVICES to use only available GPUs
# Check GPU availability and set accordingly
# Default: Use GPUs 0-3 (4 GPUs) if not set
if [ -z "$CUDA_VISIBLE_DEVICES" ]; then
    # Check which GPUs are available (free memory > 50GB)
    AVAILABLE_GPUS=$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits | awk -F', ' '$2 > 50000 {printf "%s,", $1}' | sed 's/,$//')
    if [ -n "$AVAILABLE_GPUS" ]; then
        export CUDA_VISIBLE_DEVICES=$AVAILABLE_GPUS
        NUM_GPUS=$(echo $AVAILABLE_GPUS | tr ',' '\n' | wc -l)
        echo "✓ Auto-detected available GPUs: $AVAILABLE_GPUS ($NUM_GPUS GPUs)"
    else
        # Fallback: Use GPUs 0-3
        export CUDA_VISIBLE_DEVICES=0,1,2,3
        NUM_GPUS=4
        echo "⚠ No GPUs with >50GB free found, using default: 0,1,2,3 (4 GPUs)"
    fi
else
    NUM_GPUS=$(echo $CUDA_VISIBLE_DEVICES | tr ',' '\n' | wc -l)
    echo "✓ Using user-specified GPUs: $CUDA_VISIBLE_DEVICES ($NUM_GPUS GPUs)"
fi

# Update n_gpus_per_node based on available GPUs
N_GPUS_PER_NODE=$NUM_GPUS

# Adjust environment pool size if we have fewer GPUs
# With fewer GPUs, we need fewer parallel environments
if [ $N_GPUS_PER_NODE -lt 8 ]; then
    ENV_POOL_SIZE=$((N_GPUS_PER_NODE * 2))  # 2 envs per GPU
    echo "⚠ Reduced environment pool size to $ENV_POOL_SIZE (based on $N_GPUS_PER_NODE GPUs)"
fi

echo ""
echo "=============================================="
echo "Starting VERL Android Training"
echo "=============================================="
echo "Model: $MODEL"
echo "Train data: $train_data"
echo "Test data: $test_data"
echo "Environment pool size: $ENV_POOL_SIZE"
echo "GPUs per node: $N_GPUS_PER_NODE"
echo "CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
echo "=============================================="
echo ""

# Use verl integration
uv run --frozen --extra verl --env-file .env -m skyrl_agent.integrations.verl.verl_main_ppo \
   data.train_files=$train_data \
   data.val_files=$test_data \
   data.custom_cls.path=pkg://skyrl_agent.integrations.verl.android_dataset \
   data.custom_cls.name=AndroidWorldDataset \
   data.dataloader_num_workers=0 \
   data.train_batch_size=2 \
   data.max_prompt_length=28672 \
   data.max_response_length=4096 \
   data.filter_overlong_prompts=False \
   data.truncation=error \
   data.return_raw_chat=true \
   actor_rollout_ref.model.path=$MODEL \
   actor_rollout_ref.model.trust_remote_code=True \
   actor_rollout_ref.model.use_remove_padding=False \
   actor_rollout_ref.model.use_fused_kernels=True \
   actor_rollout_ref.actor.strategy=fsdp \
   actor_rollout_ref.actor.loss_agg_mode=seq-mean-token-sum \
   actor_rollout_ref.actor.optim.lr=1e-6 \
   actor_rollout_ref.actor.optim.lr_warmup_steps_ratio=0.05 \
   actor_rollout_ref.actor.ppo_epochs=1 \
   actor_rollout_ref.actor.ppo_mini_batch_size=8 \
   actor_rollout_ref.actor.use_dynamic_bsz=False \
   actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1 \
   actor_rollout_ref.actor.use_kl_loss=True \
   actor_rollout_ref.actor.kl_loss_coef=0.01 \
   actor_rollout_ref.actor.kl_loss_type=low_var_kl \
   actor_rollout_ref.actor.entropy_coeff=0 \
   actor_rollout_ref.actor.clip_ratio_low=0.2 \
   actor_rollout_ref.actor.clip_ratio_high=0.3 \
   actor_rollout_ref.model.enable_gradient_checkpointing=True \
   actor_rollout_ref.actor.fsdp_config.param_offload=True \
   actor_rollout_ref.actor.fsdp_config.optimizer_offload=True \
   actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=False \
   actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1 \
   actor_rollout_ref.actor.ulysses_sequence_parallel_size=$SP_SIZE \
   actor_rollout_ref.rollout.tensor_model_parallel_size=$TP_SIZE \
   actor_rollout_ref.rollout.enforce_eager=False \
   actor_rollout_ref.rollout.free_cache_engine=True \
   actor_rollout_ref.rollout.enable_chunked_prefill=False \
   actor_rollout_ref.rollout.name=vllm \
   actor_rollout_ref.rollout.mode=async \
   actor_rollout_ref.rollout.gpu_memory_utilization=0.6 \
   actor_rollout_ref.rollout.n=4 \
   actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1 \
   actor_rollout_ref.ref.fsdp_config.param_offload=True \
   algorithm.adv_estimator=grpo \
   algorithm.use_kl_in_reward=False \
   algorithm.kl_ctrl.kl_coef=0.05 \
   algorithm.norm_adv_by_std_in_grpo=False \
   trainer.val_before_train=False \
   trainer.critic_warmup=0 \
   trainer.logger='["console"]' \
   trainer.project_name='skyagent-android' \
   trainer.experiment_name='skyagent-android-qwen2vl-7b' \
   trainer.n_gpus_per_node=$N_GPUS_PER_NODE \
   trainer.nnodes=$NNODES \
   trainer.max_actor_ckpt_to_keep=5 \
   trainer.save_freq=1 \
   trainer.default_local_dir=${CKPT_DIR} \
   trainer.test_freq=0 \
   trainer.total_training_steps=2 \
   trainer.resume_mode=auto \
   trainer.rollout_data_dir=${ROLLOUT_DIR} \
   trainer.validation_data_dir=${VAL_DIR} \
   +skyrl_agent.task_yaml="${PROJECT_ROOT}/examples/run_verl/verl_android.yaml" \
   +skyrl_agent.num_trajectories=4 \
   +skyrl_agent.env_pool_size=8 \
   "$@"

TRAIN_EXIT_CODE=$?

echo ""
echo "=============================================="
if [ $TRAIN_EXIT_CODE -eq 0 ]; then
    echo "Training completed successfully!"
else
    echo "Training failed with exit code: $TRAIN_EXIT_CODE"
fi
echo "=============================================="
echo "Output directories:"
echo "  - Checkpoints: ${CKPT_DIR}"
echo "  - Rollouts: ${ROLLOUT_DIR}"
echo "  - Validation: ${VAL_DIR}"
echo "=============================================="

exit $TRAIN_EXIT_CODE
