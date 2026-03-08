# Qwen3 Variant Comparison — T3A Agent on AndroidWorld

**Date**: 2026-03-08
**Goal**: Identify best Qwen3 variant for mobile agent tasks before migrating from GPT-5-mini.
**Agent**: `AndroidT3AAgent` (index-based JSON actions via AndroidWorld env)
**Dataset**: `test_seed7.jsonl` — 78 unseen AndroidWorld tasks

## Background

GPT-5-mini on T3A-ADB agent shows high variance (15–31% SR across runs, median ~19%).
We want to migrate to open-source Qwen3 models for fine-tuning. First step: benchmark
which Qwen3 size hits the best quality/cost tradeoff on this task.

## Experiment Matrix

3 models × 2 modes = **6 experiments**, run in 2 rounds of 3 simultaneous runs.

### Models

| Model                | Params         | FP16 VRAM | GPU Assignment | vLLM Port |
|----------------------|----------------|-----------|----------------|-----------|
| Qwen3-14B            | 14B dense      | ~31 GB    | GPU 5 (47 GB free) | 8214   |
| Qwen3-30B-A3B (MoE) | 30B (3B active)| ~66 GB    | GPU 2 (81 GB free) | 8230   |
| Qwen3-32B            | 32B dense      | ~70 GB    | GPU 3 (81 GB free) | 8232   |

### Modes

| Mode      | Think tokens | max_tokens | remove_think_tokens | Notes |
|-----------|-------------|------------|---------------------|-------|
| No-think  | Disabled    | 4096       | false               | Baseline; faster inference |
| Think     | Enabled     | 8192       | true                | Extra budget for reasoning |

Think mode rationale: T3A requires multi-step reasoning (read UI → decide action →
track progress → summarize). Think tokens give the model scratch space. But they also
consume KV cache and max_tokens budget, so we test both.

## Infrastructure

### Broker
- **Stop** current broker (33 containers) and **relaunch with 64 containers**
- Command: `python -m skyrl_agent.runtime.android.pool_broker --pool-size 64 --port 9200 --docker-image androidworld:full_adb_agent --parallel 8`
- Snapshot restore enabled (fixed in this branch) — each container reset between tasks
- 3 experiments × 16 containers = 48 leased, 16 buffer

### vLLM Servers (one per model)

```bash
# GPU 2: Qwen3-30B-A3B
CUDA_VISIBLE_DEVICES=2 vllm serve Qwen/Qwen3-30B-A3B \
    --port 8230 --max-model-len 32768 --gpu-memory-utilization 0.9

# GPU 3: Qwen3-32B
CUDA_VISIBLE_DEVICES=3 vllm serve Qwen/Qwen3-32B \
    --port 8232 --max-model-len 32768 --gpu-memory-utilization 0.9

# GPU 5: Qwen3-14B
CUDA_VISIBLE_DEVICES=5 vllm serve Qwen/Qwen3-14B \
    --port 8214 --max-model-len 32768 --gpu-memory-utilization 0.9
```

For think mode, add `--enable-thinking` flag.
For no-think mode, omit the flag (or prepend system prompt with `/no_think`).

### GPU Availability (as of 2026-03-08)

| GPU | Total | Used | Free | Owner |
|-----|-------|------|------|-------|
| 0   | 81 GB | 77 GB | 4 GB  | vLLM worker (other) |
| 1   | 81 GB | 77 GB | 4 GB  | vLLM worker (other) |
| 2   | 81 GB | 0 GB  | 81 GB | **Available** |
| 3   | 81 GB | 0 GB  | 81 GB | **Available** |
| 4   | 81 GB | 67 GB | 14 GB | python3 (taozhang) |
| 5   | 81 GB | 34 GB | 47 GB | **Available (partial)** |
| 6   | 81 GB | 73 GB | 8 GB  | taozhang |
| 7   | 81 GB | 69 GB | 12 GB | python3 (taozhang) |

## Execution Plan

### Round 1: No-think mode

1. Stop broker, relaunch with 64 containers (wait for initialization)
2. Launch 3 vLLM servers (no `--enable-thinking`)
3. Create 3 YAML configs (T3A agent, temperature 0.6, max_tokens 4096)
4. Launch 3 inference runs simultaneously (16 containers each)
5. Wait for completion, collect results

### Round 2: Think mode

1. Restart 3 vLLM servers with `--enable-thinking`
2. Create 3 YAML configs (max_tokens 8192, remove_think_tokens: true)
3. Launch 3 inference runs simultaneously
4. Wait for completion, collect results

### YAML Config Template

```yaml
agent_cls: skyrl_agent.agents.android.AndroidT3AAgent

task: skyrl_agent.tasks.android.android_task.AndroidTask

tools:
  enable_android_env: true

data:
  instance_key: instance
  instance_id_key: instance.instance_id
  data_source_key: data_source
  max_pixels: 564480
  min_pixels: 78400

env:
  broker_url: "http://localhost:9200"
  pool_size: 16
  buffer_size: 1
  docker_image: androidworld:full_adb_agent
  use_host_network: true
  snapshot: clean
  sample_mode: sequential
  train_task_family: android_world
  val_task_family: android_world
  temp_path: /tmp/androidworld_t3a_{model_short}
  base_env_id: 0

generator:
  infer_backend: openai_server
  backend_config:
    model_name: Qwen/{model_name}
    api_url: http://localhost:{port}
    api_type: chat
    model_max_len: 32768
  num_trajectories: 1
  max_iterations: 30
  max_prompt_length: 32768
  max_history_steps: 10
  training_strategy: early
  sampling_params:
    max_tokens: {4096 or 8192}
    temperature: 0.6
  val_config:
    num_trajectories: 1
    sampling_params:
      max_tokens: {4096 or 8192}
      temperature: 0.6
  remove_think_tokens: {false or true}
  vision_is_active: false
  qwen3_enable_thinking: false
  qwen3_acc_thinking: false
  save_trajectories: true
  trajectory_save_dir: ./results
  trajectory_exp_name: ""
  save_screenshots: true

dispatcher:
  type: async_fix_pool
  max_parallel_agents: 16
  max_eval_parallel_agents: 16
  val_config:
    max_parallel_agents: 16
    max_eval_parallel_agents: 16
```

## Expected Deliverable

| Model | Mode | SR | Finish% | Avg Steps | Avg Tokens | Time |
|-------|------|-----|---------|-----------|------------|------|
| Qwen3-14B | no-think | | | | | |
| Qwen3-14B | think | | | | | |
| Qwen3-30B-A3B | no-think | | | | | |
| Qwen3-30B-A3B | think | | | | | |
| Qwen3-32B | no-think | | | | | |
| Qwen3-32B | think | | | | | |

## Reference: Prior Results (GPT-5-mini, T3A-ADB)

| Run | SR | Notes |
|-----|-----|-------|
| 0304_2009 (outlier) | 30.8% (24/78) | Fresh containers, no broker |
| 0304 median (6 runs) | ~19% | Same code, high variance |
| Snapshot-fix (0306) | 14.1% (11/78) | Broker with snapshot restore |

Note: T3A-ADB results not directly comparable to T3A (different action space).
T3A uses index-based JSON actions; T3A-ADB uses raw ADB shell commands.
