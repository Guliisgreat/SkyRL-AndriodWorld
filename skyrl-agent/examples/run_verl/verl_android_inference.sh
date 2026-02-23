#!/bin/bash
# verl_android_inference.sh - Inference-only evaluation for AndroidWorld
#
# Usage: ./verl_android_inference.sh [additional_args]
#
# This script runs inference on the test set without training to verify:
# 1. Docker containers are working
# 2. vLLM engine is functional
# 3. Agent framework executes correctly
# 4. Final success rate is computed
#
# Prerequisites:
# 1. Docker is running with KVM support
# 2. androidworld:v8 Docker image is available
# 3. Test data is available in JSONL format

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
export RAY_TMPDIR=/shared/tmp/ray
mkdir -p ${RAY_TMPDIR}

# Increase Ray disk space threshold
export RAY_object_spilling_threshold=0.99

# === Data Configuration ===
# Default: Use test.jsonl from unseen_task_instance
DATA_DIR="./data/androidworld_generalization/unseen_task_instance"
test_data="${DATA_DIR}/test.jsonl"

# Override with command line argument if provided
if [ -n "$1" ] && [ -f "$1" ]; then
    test_data="$1"
    shift
fi

# Validate test data exists
if [ ! -f "$test_data" ]; then
    echo "ERROR: Test data file not found: $test_data"
    exit 1
fi

NUM_INSTANCES=$(wc -l < "$test_data")
echo "✓ Test data validated: $test_data ($NUM_INSTANCES instances)"

# === Model Configuration ===
MODEL=ByteDance-Seed/UI-TARS-7B-SFT

# === GPU Configuration ===
if [ -z "$CUDA_VISIBLE_DEVICES" ]; then
    # Auto-detect GPUs with >50GB free memory
    AVAILABLE_GPUS=$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits | awk -F', ' '$2 > 50000 {printf "%s,", $1}' | sed 's/,$//')
    if [ -n "$AVAILABLE_GPUS" ]; then
        export CUDA_VISIBLE_DEVICES=$AVAILABLE_GPUS
        NUM_GPUS=$(echo $AVAILABLE_GPUS | tr ',' '\n' | wc -l)
        echo "✓ Auto-detected GPUs: $AVAILABLE_GPUS ($NUM_GPUS GPUs)"
    else
        export CUDA_VISIBLE_DEVICES=0,1,2,3
        NUM_GPUS=4
        echo "⚠ Using default GPUs: 0,1,2,3"
    fi
else
    NUM_GPUS=$(echo $CUDA_VISIBLE_DEVICES | tr ',' '\n' | wc -l)
    echo "✓ Using user-specified GPUs: $CUDA_VISIBLE_DEVICES ($NUM_GPUS GPUs)"
fi

# === Parallel Environment Configuration ===
# Use 16 environments for inference (matches yaml config)
# Can be overridden via ENV_POOL_SIZE environment variable
ENV_POOL_SIZE=${ENV_POOL_SIZE:-16}
NUM_TRAJECTORIES=$ENV_POOL_SIZE

echo "✓ Environment pool size: $ENV_POOL_SIZE"

# === Distributed Configuration ===
NNODES=1
SP_SIZE=1
TP_SIZE=1
N_GPUS_PER_NODE=$NUM_GPUS

# === Output Configuration ===
OUTPUT_DIR=/shared/ligu/projects/SkyRL-AndriodWorld/tmp_inference
RESULTS_DIR=${OUTPUT_DIR}/results
ROLLOUTS_DIR=${OUTPUT_DIR}/rollouts

mkdir -p ${RESULTS_DIR} ${ROLLOUTS_DIR}
echo "✓ Output directories created:"
echo "  - Results: ${RESULTS_DIR}"
echo "  - Rollouts: ${ROLLOUTS_DIR}"

echo ""
echo "=============================================="
echo "Starting AndroidWorld Inference Evaluation"
echo "=============================================="
echo "Model: $MODEL"
echo "Test data: $test_data ($NUM_INSTANCES instances)"
echo "GPUs: $CUDA_VISIBLE_DEVICES ($NUM_GPUS GPUs)"
echo "Environment pool: $ENV_POOL_SIZE containers"
echo "=============================================="
echo ""

# Run inference using verl integration
# Note: Using async mode with V1 engine, CUDA graphs enabled
uv run --frozen --extra verl --env-file .env -m skyrl_agent.integrations.verl.verl_main_inference \
   data.train_files="$test_data" \
   data.val_files="$test_data" \
   data.custom_cls.path=pkg://skyrl_agent.integrations.verl.android_dataset \
   data.custom_cls.name=AndroidWorldDataset \
   data.dataloader_num_workers=0 \
   data.train_batch_size=$ENV_POOL_SIZE \
   data.max_prompt_length=28672 \
   data.max_response_length=4096 \
   data.filter_overlong_prompts=False \
   data.truncation=error \
   data.return_raw_chat=true \
   actor_rollout_ref.model.path="$MODEL" \
   actor_rollout_ref.model.trust_remote_code=True \
   actor_rollout_ref.model.use_remove_padding=True \
   actor_rollout_ref.actor.strategy=fsdp \
   actor_rollout_ref.actor.fsdp_config.param_offload=True \
   actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1 \
   actor_rollout_ref.actor.ppo_mini_batch_size=$ENV_POOL_SIZE \
   actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=False \
   actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1 \
   actor_rollout_ref.actor.ulysses_sequence_parallel_size=$SP_SIZE \
   actor_rollout_ref.rollout.tensor_model_parallel_size=$TP_SIZE \
   actor_rollout_ref.rollout.enforce_eager=False \
   actor_rollout_ref.rollout.free_cache_engine=True \
   actor_rollout_ref.rollout.name=vllm \
   actor_rollout_ref.rollout.mode=async \
   actor_rollout_ref.rollout.gpu_memory_utilization=0.5 \
   actor_rollout_ref.rollout.n=1 \
   actor_rollout_ref.model.enable_gradient_checkpointing=False \
   actor_rollout_ref.ref.fsdp_config.param_offload=True \
   algorithm.adv_estimator=grpo \
   algorithm.use_kl_in_reward=False \
   trainer.val_before_train=True \
   trainer.balance_batch=False \
   'trainer.logger=["console", "wandb"]' \
   trainer.project_name=skyagent-android-inference \
   trainer.experiment_name=android-inference-test \
   trainer.n_gpus_per_node=$N_GPUS_PER_NODE \
   trainer.nnodes=$NNODES \
   trainer.total_epochs=0 \
   trainer.rollout_data_dir=$ROLLOUTS_DIR \
   trainer.validation_data_dir=$RESULTS_DIR \
   +skyrl_agent.task_yaml="${PROJECT_ROOT}/examples/run_verl/verl_android_inference.yaml" \
   +skyrl_agent.num_trajectories=$NUM_TRAJECTORIES \
   +skyrl_agent.env_pool_size=$ENV_POOL_SIZE \
   "$@"

INFERENCE_EXIT_CODE=$?

echo ""
echo "=============================================="
if [ $INFERENCE_EXIT_CODE -eq 0 ]; then
    echo "Inference completed successfully!"
    
    # Display results if available
    if [ -f "${RESULTS_DIR}/final_metrics.json" ]; then
        echo ""
        echo "Final Metrics:"
        cat "${RESULTS_DIR}/final_metrics.json"
    fi
else
    echo "Inference failed with exit code: $INFERENCE_EXIT_CODE"
fi
echo "=============================================="
echo "Output files:"
echo "  - Metrics: ${RESULTS_DIR}/final_metrics.json"
echo "  - Trajectories: ${RESULTS_DIR}/0.jsonl"
echo "=============================================="

exit $INFERENCE_EXIT_CODE
