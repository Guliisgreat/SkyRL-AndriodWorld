#!/bin/bash
# Full training run with Wandb logging

set -x

./scripts/patch_vllm.sh 2>/dev/null || true

export VLLM_USE_V1=1
export RAY_TMPDIR=/shared/tmp/ray
mkdir -p ${RAY_TMPDIR}
export RAY_object_spilling_threshold=0.99

export CUDA_VISIBLE_DEVICES=0,1,2,3

# Wandb configuration
export WANDB_DIR=/shared/ligu/projects/SkyRL-AndriodWorld/skyrl-agent/wandb
export WANDB_MODE=online
mkdir -p ${WANDB_DIR}

MODEL=ByteDance-Seed/UI-TARS-7B-SFT
DATA_DIR="./data/androidworld_generalization/unseen_task_instance"

OUTPUT_BASE=/shared/ligu/projects/SkyRL-AndriodWorld/tmp_training
CKPT_DIR="${OUTPUT_BASE}/ckpts/skyagent-android-50step-mb1"
ROLLOUT_DIR="${OUTPUT_BASE}/rollouts/skyagent-android-50step-mb1"
VAL_DIR="${OUTPUT_BASE}/rollouts/skyagent-android-50step-mb1-val"
mkdir -p "${CKPT_DIR}" "${ROLLOUT_DIR}" "${VAL_DIR}"

echo "Training with Wandb logging"
echo "Wandb dir: ${WANDB_DIR}"

uv run --frozen --extra verl --env-file .env -m skyrl_agent.integrations.verl.verl_main_ppo \
   data.train_files=${DATA_DIR}/train.jsonl \
   data.val_files=${DATA_DIR}/test.jsonl \
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
   actor_rollout_ref.actor.ppo_mini_batch_size=1 \
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
   actor_rollout_ref.actor.ulysses_sequence_parallel_size=1 \
   actor_rollout_ref.rollout.tensor_model_parallel_size=2 \
   actor_rollout_ref.rollout.enforce_eager=False \
   actor_rollout_ref.rollout.free_cache_engine=True \
   actor_rollout_ref.rollout.enable_chunked_prefill=False \
   actor_rollout_ref.rollout.name=vllm \
   actor_rollout_ref.rollout.mode=async \
   actor_rollout_ref.rollout.gpu_memory_utilization=0.4 \
   actor_rollout_ref.rollout.n=8 \
   actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1 \
   actor_rollout_ref.ref.fsdp_config.param_offload=True \
   algorithm.adv_estimator=grpo \
   algorithm.use_kl_in_reward=False \
   algorithm.kl_ctrl.kl_coef=0.05 \
   algorithm.norm_adv_by_std_in_grpo=False \
   trainer.val_before_train=False \
   trainer.critic_warmup=0 \
   trainer.logger='["console","wandb"]' \
   trainer.project_name='skyagent-android' \
   trainer.experiment_name='skyagent-android-50step-mb1' \
   trainer.n_gpus_per_node=4 \
   trainer.nnodes=1 \
   trainer.max_actor_ckpt_to_keep=5 \
   trainer.save_freq=5 \
   trainer.default_local_dir=${CKPT_DIR} \
   trainer.test_freq=0 \
   trainer.total_training_steps=15 \
   trainer.resume_mode=auto \
   trainer.rollout_data_dir=${ROLLOUT_DIR} \
   trainer.validation_data_dir=${VAL_DIR} \
   +skyrl_agent.task_yaml=/shared/ligu/projects/SkyRL-AndriodWorld/skyrl-agent/examples/run_verl/verl_android.yaml \
   +skyrl_agent.num_trajectories=8 \
   +skyrl_agent.env_pool_size=16

echo "Training exit code: $?"
