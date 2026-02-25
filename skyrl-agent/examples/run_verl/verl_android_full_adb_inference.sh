#!/bin/bash
# verl_android_full_adb_inference.sh - Inference with text-only ADB agent (a11y tree input)
#
# Uses AndroidAPITreeADBAgent which takes only the accessibility tree as input
# (no screenshots) and generates ADB commands as output. Suitable for text-only LLMs.
# vision_is_active is set to false.
#
# Usage:
#   ./verl_android_full_adb_inference.sh [test_data_file] [additional_args]
#   ENV_POOL_SIZE=4 CUDA_VISIBLE_DEVICES=4,5 ./verl_android_full_adb_inference.sh

set -x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${PROJECT_ROOT}" || exit 1

"${PROJECT_ROOT}/scripts/patch_vllm.sh" 2>/dev/null || true

export VLLM_USE_V1=1
export RAY_TMPDIR=/shared/tmp/ray
mkdir -p ${RAY_TMPDIR}
export RAY_object_spilling_threshold=0.99

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
echo "Test data validated: $test_data ($NUM_INSTANCES instances)"

MODEL=ByteDance-Seed/UI-TARS-7B-SFT

if [ -z "$CUDA_VISIBLE_DEVICES" ]; then
    export CUDA_VISIBLE_DEVICES=4,5,7
    NUM_GPUS=3
    echo "Using default GPUs: 4,5,7 ($NUM_GPUS GPUs)"
else
    NUM_GPUS=$(echo $CUDA_VISIBLE_DEVICES | tr ',' '\n' | wc -l)
    echo "Using user-specified GPUs: $CUDA_VISIBLE_DEVICES ($NUM_GPUS GPUs)"
fi

ENV_POOL_SIZE=${ENV_POOL_SIZE:-4}
NUM_TRAJECTORIES=$ENV_POOL_SIZE
echo "Environment pool size: $ENV_POOL_SIZE"

NNODES=1
SP_SIZE=1
TP_SIZE=1
N_GPUS_PER_NODE=$NUM_GPUS

OUTPUT_DIR=./results
RESULTS_DIR=${OUTPUT_DIR}/results
ROLLOUTS_DIR=${OUTPUT_DIR}/rollouts
mkdir -p ${RESULTS_DIR} ${ROLLOUTS_DIR}
echo "Output directories created: ${RESULTS_DIR} ${ROLLOUTS_DIR}"

echo ""
echo "=============================================="
echo "Starting AndroidWorld Full-ADB Agent Inference"
echo "  (text-only: a11y tree input, ADB output)"
echo "=============================================="
echo "Model: $MODEL"
echo "Test data: $test_data ($NUM_INSTANCES instances)"
echo "Agent: AndroidAPITreeADBAgent (a11y tree + step_adb)"
echo "vision_is_active: false"
echo "=============================================="
echo ""

uv run --frozen --extra verl --env-file .env -m skyrl_agent.integrations.verl.verl_android_full_adb_inference \
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
   actor_rollout_ref.rollout.gpu_memory_utilization=0.6 \
   actor_rollout_ref.rollout.n=1 \
   actor_rollout_ref.model.enable_gradient_checkpointing=False \
   actor_rollout_ref.ref.fsdp_config.param_offload=True \
   algorithm.adv_estimator=grpo \
   algorithm.use_kl_in_reward=False \
   trainer.val_before_train=True \
   trainer.balance_batch=False \
   'trainer.logger=["console", "wandb"]' \
   trainer.project_name=skyagent-android-full-adb-inference \
   trainer.experiment_name=android-full-adb-inference-test \
   trainer.n_gpus_per_node=$N_GPUS_PER_NODE \
   trainer.nnodes=$NNODES \
   trainer.total_epochs=0 \
   trainer.rollout_data_dir=$ROLLOUTS_DIR \
   trainer.validation_data_dir=$RESULTS_DIR \
   +skyrl_agent.task_yaml="${PROJECT_ROOT}/examples/run_verl/verl_android_full_adb_inference.yaml" \
   +skyrl_agent.num_trajectories=$NUM_TRAJECTORIES \
   +skyrl_agent.env_pool_size=$ENV_POOL_SIZE \
   "$@"

INFERENCE_EXIT_CODE=$?

echo ""
echo "=============================================="
if [ $INFERENCE_EXIT_CODE -eq 0 ]; then
    echo "Full-ADB inference completed successfully!"
    if [ -f "${RESULTS_DIR}/final_metrics.json" ]; then
        echo ""
        echo "Final Metrics:"
        cat "${RESULTS_DIR}/final_metrics.json"
    fi
else
    echo "Full-ADB inference failed with exit code: $INFERENCE_EXIT_CODE"
fi
echo "=============================================="
echo "Output: ${RESULTS_DIR}/final_metrics.json, ${RESULTS_DIR}/0.jsonl"
echo "=============================================="

exit $INFERENCE_EXIT_CODE
