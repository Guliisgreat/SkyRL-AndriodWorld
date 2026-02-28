#!/bin/bash
# launch_4x_inference.sh - Launch 4 parallel inference runs sharing pre-running containers
#
# Architecture:
#   1. Pool broker (FastAPI) adopts existing 64 containers (env0-env63)
#   2. 4 inference scripts connect to broker via HTTP, each using 1 GPU + 16 containers
#
# Prerequisites:
#   - 64 containers (env0-env63) already running
#   - GPUs 1-4 available
#
# Usage: ./launch_4x_inference.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}" || exit 1

# Apply vLLM patch
"${PROJECT_ROOT}/scripts/patch_vllm.sh" 2>/dev/null || true

# === Configuration ===
BROKER_PORT=9200
BROKER_URL="http://localhost:${BROKER_PORT}"
GPUS=(1 2 3 4)
POOL_SIZE=16              # containers per run
TOTAL_CONTAINERS=64       # total containers for broker
MODEL=ByteDance-Seed/UI-TARS-7B-SFT
DATA_DIR="./data/androidworld_generalization/unseen_task_instance"
TEST_DATA="${DATA_DIR}/test_seed7.jsonl"

if [ ! -f "$TEST_DATA" ]; then
    echo "ERROR: Test data not found: $TEST_DATA"
    exit 1
fi
NUM_INSTANCES=$(wc -l < "$TEST_DATA")
echo "Test data: $TEST_DATA ($NUM_INSTANCES instances)"

# === Output setup ===
OUTPUT_BASE=./results/4x_verify_$(date +%Y%m%d_%H%M%S)
mkdir -p "${OUTPUT_BASE}"
echo "Output base: $OUTPUT_BASE"

# === Step 1: Start pool broker (adopt existing containers) ===
echo ""
echo "=============================================="
echo "Step 1: Starting pool broker (adopting ${TOTAL_CONTAINERS} containers)"
echo "=============================================="

BROKER_LOG="${OUTPUT_BASE}/broker.log"
uv run --frozen --extra verl --env-file .env -m skyrl_agent.runtime.android.pool_broker \
    --pool-size ${TOTAL_CONTAINERS} \
    --base-env-id 0 \
    --port ${BROKER_PORT} \
    --docker-image androidworld:full_adb_agent \
    --adopt \
    > "${BROKER_LOG}" 2>&1 &
BROKER_PID=$!
echo "Broker PID=${BROKER_PID}, log=${BROKER_LOG}"

# Wait for broker to be ready
echo -n "Waiting for broker..."
for i in $(seq 1 30); do
    if curl -s "${BROKER_URL}/health" > /dev/null 2>&1; then
        echo " ready!"
        break
    fi
    if ! kill -0 $BROKER_PID 2>/dev/null; then
        echo " FAILED (broker crashed)"
        echo "Last 20 lines of broker log:"
        tail -20 "${BROKER_LOG}"
        exit 1
    fi
    echo -n "."
    sleep 2
done

# Verify broker status
BROKER_STATUS=$(curl -s "${BROKER_URL}/status" 2>/dev/null)
echo "Broker status: $BROKER_STATUS" | python3 -m json.tool 2>/dev/null || echo "$BROKER_STATUS"

# === Step 2: Launch 4 inference runs ===
echo ""
echo "=============================================="
echo "Step 2: Launching 4 inference runs"
echo "=============================================="

PIDS=()
for i in 0 1 2 3; do
    gpu=${GPUS[$i]}
    output_dir="${OUTPUT_BASE}/run${i}"
    results_dir="${output_dir}/results"
    rollouts_dir="${output_dir}/rollouts"
    log_file="${output_dir}/inference.log"

    mkdir -p "${results_dir}" "${rollouts_dir}"

    echo ""
    echo "--- Run ${i}: GPU=${gpu} ---"

    VLLM_USE_V1=1 \
    RAY_ADDRESS=local \
    RAY_TMPDIR="/shared/tmp/ray_run${i}" \
    RAY_object_spilling_threshold=0.99 \
    CUDA_VISIBLE_DEVICES=${gpu} \
    uv run --frozen --extra verl --env-file .env -m skyrl_agent.integrations.verl.verl_main_inference \
       data.train_files="$TEST_DATA" \
       data.val_files="$TEST_DATA" \
       data.custom_cls.path=pkg://skyrl_agent.integrations.verl.android_dataset \
       data.custom_cls.name=AndroidWorldDataset \
       data.dataloader_num_workers=0 \
       data.train_batch_size=$POOL_SIZE \
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
       actor_rollout_ref.actor.ppo_mini_batch_size=$POOL_SIZE \
       actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=False \
       actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1 \
       actor_rollout_ref.actor.ulysses_sequence_parallel_size=1 \
       actor_rollout_ref.rollout.tensor_model_parallel_size=1 \
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
       'trainer.logger=["console"]' \
       trainer.project_name=skyagent-android-4x-verify \
       trainer.experiment_name="inference-run${i}-gpu${gpu}" \
       trainer.n_gpus_per_node=1 \
       trainer.nnodes=1 \
       trainer.total_epochs=0 \
       trainer.rollout_data_dir="$rollouts_dir" \
       trainer.validation_data_dir="$results_dir" \
       +skyrl_agent.task_yaml="${SCRIPT_DIR}/verl_android_inference_broker.yaml" \
       +skyrl_agent.num_trajectories=$POOL_SIZE \
       +skyrl_agent.env_pool_size=$POOL_SIZE \
       > "$log_file" 2>&1 &

    PIDS+=($!)
    echo "  PID=${PIDS[-1]}, log=$log_file"
done

echo ""
echo "=============================================="
echo "All 4 runs launched!"
echo "Broker PID: ${BROKER_PID}"
echo "Run PIDs: ${PIDS[*]}"
echo "=============================================="
echo ""
echo "Monitor:"
echo "  tail -f ${OUTPUT_BASE}/run{0,1,2,3}/inference.log"
echo "  curl -s ${BROKER_URL}/status | python3 -m json.tool"
echo ""

# Wait for all inference runs to finish
echo "Waiting for all inference runs to complete..."
FAILED=0
for i in 0 1 2 3; do
    pid=${PIDS[$i]}
    if wait $pid; then
        echo "Run ${i} (PID=$pid): SUCCESS"
    else
        echo "Run ${i} (PID=$pid): FAILED (exit code $?)"
        FAILED=$((FAILED + 1))
    fi
done

# Stop broker
echo "Stopping broker..."
kill $BROKER_PID 2>/dev/null || true
wait $BROKER_PID 2>/dev/null || true

echo ""
echo "=============================================="
if [ $FAILED -eq 0 ]; then
    echo "All 4 runs completed successfully!"
else
    echo "${FAILED}/4 runs failed."
fi
echo "Logs: ${OUTPUT_BASE}/run*/inference.log"
echo "Broker log: ${BROKER_LOG}"
echo "=============================================="

exit $FAILED
