#!/bin/bash
# T3A-ADB agent inference with verl vLLM backend.
# Uses Qwen3.5-27B (text-only) with broker-managed container pool.
#
# Usage:
#   CUDA_VISIBLE_DEVICES=4,5 ./verl_android_t3a_adb_inference.sh
#
# Overrides:
#   MODEL=Qwen/Qwen3.5-9B ./verl_android_t3a_adb_inference.sh
#   ENV_POOL_SIZE=8 ./verl_android_t3a_adb_inference.sh

set -x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}" || exit 1

# Apply vLLM patch if needed
"${PROJECT_ROOT}/scripts/patch_vllm.sh" 2>/dev/null || true

export VLLM_USE_V1=1
export RAY_TMPDIR=/shared/tmp/ray
mkdir -p ${RAY_TMPDIR}
export RAY_object_spilling_threshold=0.99

# === Data ===
DATA_DIR="./data/androidworld_generalization/unseen_task_instance"
test_data="${DATA_DIR}/test_seed7.jsonl"

if [ -n "$1" ] && [ -f "$1" ]; then
    test_data="$1"
    shift
fi

if [ ! -f "$test_data" ]; then
    echo "ERROR: Test data file not found: $test_data"
    exit 1
fi

NUM_INSTANCES=$(wc -l < "$test_data")
echo "Test data: $test_data ($NUM_INSTANCES instances)"

# === Model ===
MODEL=${MODEL:-Qwen/Qwen3.5-27B}

# === GPUs ===
if [ -z "$CUDA_VISIBLE_DEVICES" ]; then
    AVAILABLE_GPUS=$(nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits | awk -F', ' '$2 > 50000 {printf "%s,", $1}' | sed 's/,$//')
    if [ -n "$AVAILABLE_GPUS" ]; then
        export CUDA_VISIBLE_DEVICES=$AVAILABLE_GPUS
        NUM_GPUS=$(echo $AVAILABLE_GPUS | tr ',' '\n' | wc -l)
    else
        echo "ERROR: No GPUs with >50GB free memory found"
        exit 1
    fi
else
    NUM_GPUS=$(echo $CUDA_VISIBLE_DEVICES | tr ',' '\n' | wc -l)
fi
echo "GPUs: $CUDA_VISIBLE_DEVICES ($NUM_GPUS GPUs)"

# === Pool ===
ENV_POOL_SIZE=${ENV_POOL_SIZE:-16}
NUM_TRAJECTORIES=$ENV_POOL_SIZE
echo "Pool size: $ENV_POOL_SIZE"

# === Distributed ===
NNODES=1
SP_SIZE=1
TP_SIZE=1
N_GPUS_PER_NODE=$NUM_GPUS

# === Output ===
# Convention: {AgentClass}_{Model}_{yymmdd}_{HHMM}
MODEL_SHORT=$(basename "$MODEL" | tr -d '.-')
EXP_NAME="AndroidT3AADBAgent_${MODEL_SHORT}_$(date +%y%m%d_%H%M)"
OUTPUT_DIR=./results/${EXP_NAME}
RESULTS_DIR=${OUTPUT_DIR}
ROLLOUTS_DIR=${OUTPUT_DIR}/rollouts
mkdir -p ${RESULTS_DIR} ${ROLLOUTS_DIR}

echo "=============================================="
echo "T3A-ADB Inference (verl vLLM)"
echo "  Model: $MODEL"
echo "  Data: $test_data ($NUM_INSTANCES instances)"
echo "  GPUs: $CUDA_VISIBLE_DEVICES ($NUM_GPUS)"
echo "  Pool: $ENV_POOL_SIZE containers"
echo "=============================================="

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
   actor_rollout_ref.rollout.gpu_memory_utilization=0.85 \
   actor_rollout_ref.rollout.n=1 \
   actor_rollout_ref.model.enable_gradient_checkpointing=False \
   actor_rollout_ref.ref.fsdp_config.param_offload=True \
   algorithm.adv_estimator=grpo \
   algorithm.use_kl_in_reward=False \
   trainer.val_before_train=True \
   trainer.balance_batch=False \
   'trainer.logger=["console", "wandb"]' \
   trainer.project_name=skyagent-android-t3a-adb \
   trainer.experiment_name=$EXP_NAME \
   trainer.n_gpus_per_node=$N_GPUS_PER_NODE \
   trainer.nnodes=$NNODES \
   trainer.total_epochs=0 \
   trainer.rollout_data_dir=$ROLLOUTS_DIR \
   trainer.validation_data_dir=$RESULTS_DIR \
   +skyrl_agent.task_yaml="${PROJECT_ROOT}/examples/run_verl/verl_android_t3a_adb_inference.yaml" \
   +skyrl_agent.num_trajectories=$NUM_TRAJECTORIES \
   +skyrl_agent.env_pool_size=$ENV_POOL_SIZE \
   "$@"

exit $?
