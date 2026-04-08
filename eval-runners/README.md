# Eval Runners

Evaluation and inference runners for Android agent benchmarks. Supports multiple agents × multiple benchmarks via a shared broker pool.

## Agent × Benchmark Matrix

✓ = evaluated, results in [`results/table.md`](results/table.md).

### CLI Agents (ADB shell, no screenshots)

| Agent | AndroidWorld | MobileWorld |
|-------|-------------|-------------|
| **Claude Code CLI** | ✓ | — |
| **Terminus2** | ✓ | — |
| **Mini-SWE** | — | — |
| **Ground Truth Oracle** | — | — |

### GUI Agents (screenshots + tap/swipe/type)

| Agent | AndroidWorld | MobileWorld |
|-------|-------------|-------------|
| **Qwen3-VL** | ✓ | — |
| **UI-Venus-1.5-30B-A3B** | ✓ | ✓ |
| **MAI-UI-8B** | ✓ | — |
| **Qwen3.5 (DashScope)** | — | — |
| **GeneralE2E (Gemini 2.5 Pro)** | ✓ | — |
| **GeneralE2E (Kimi K2.5)** | — | ✓ |

## Quick Start

### 1. Start broker + containers

```bash
# AndroidWorld (16 containers)
PYTHONPATH=eval-runners/common/runtime:. \
python eval-runners/common/runtime/pool_broker.py \
  --pool-size 16 --docker-image androidworld:2026 --port 9400 \
  --base-env-id 700 --parallel 4

# MobileWorld (pre-existing containers, scan port range)
PYTHONPATH=eval-runners/common/runtime:. \
python eval-runners/common/runtime/mw_pool_broker.py \
  --scan-range 6804-6819 --port 9400
```

### 2. Source API keys

```bash
source .env  # OPENAI_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY, DASHSCOPE_API_KEY
```

### 3. Run evaluation

```bash
# --- AndroidWorld ---

# Claude Code CLI (ADB agent) on AndroidWorld
PYTHONPATH=eval-runners/benchmarks/androidworld:. \
python eval-runners/benchmarks/androidworld/run_claude_cli.py \
  --data data/androidworld_original/val_data_seed7.jsonl \
  --broker-url http://localhost:9400 --pool-size 16 \
  --model claude-opus-4-6 --prompt clean_optimized --max-turns 30

# Qwen3-VL GUI agent on AndroidWorld (via OpenRouter)
PYTHONPATH=eval-runners/benchmarks/androidworld:eval-runners/agents/gui:. \
python eval-runners/benchmarks/mobileworld/run_qwen3vl.py \
  --data data/androidworld_original/val_data_seed7.jsonl \
  --model qwen/qwen3-vl-30b-a3b-instruct \
  --api-url https://openrouter.ai/api/v1 \
  --api-key $OPENROUTER_API_KEY \
  --broker-url http://localhost:9400 --pool-size 16 --max-steps 30

# UI-Venus-1.5 GUI agent on AndroidWorld (local vLLM)
PYTHONPATH=eval-runners/benchmarks/androidworld:eval-runners/agents/gui:. \
python eval-runners/benchmarks/mobileworld/run_venus.py \
  --data data/androidworld_original/val_data_seed7.jsonl \
  --model /path/to/UI-Venus-1.5-30B-A3B \
  --api-url http://localhost:8300/v1 \
  --broker-url http://localhost:9400 --pool-size 12 --max-steps 30

# --- MobileWorld ---

# Claude CLI on MobileWorld
python eval-runners/benchmarks/mobileworld/run_claude_cli.py \
  --data eval-runners/data/mobileworld/gui_only_tasks.jsonl \
  --broker-url http://localhost:9400 --pool-size 8 \
  --model claude-sonnet-4-6 --max-turns 30 --prompt mw_adb_oracle

# Qwen3-VL GUI agent on MobileWorld (via OpenRouter)
python eval-runners/benchmarks/mobileworld/run_gui_agent_broker.py \
  --data eval-runners/data/mobileworld/gui_only_tasks.jsonl \
  --agent-type qwen3vl \
  --model qwen/qwen3-vl-30b-a3b-instruct \
  --api-url https://openrouter.ai/api/v1 \
  --api-key $OPENROUTER_API_KEY \
  --broker-url http://localhost:9400 --pool-size 16 --max-steps 50

# Gemini on MobileWorld (via OpenRouter)
python eval-runners/benchmarks/mobileworld/run_gui_agent_broker.py \
  --data eval-runners/data/mobileworld/gui_only_tasks.jsonl \
  --agent-type general_e2e \
  --model google/gemini-3.1-pro-preview \
  --api-url https://openrouter.ai/api/v1 \
  --api-key $OPENROUTER_API_KEY \
  --broker-url http://localhost:9400 --pool-size 8 --max-steps 50

# UI-Venus on MobileWorld (local vLLM)
CUDA_VISIBLE_DEVICES=3 python -m vllm.entrypoints.openai.api_server \
  --model /path/to/UI-Venus-1.5-30B-A3B --port 8300 \
  --trust-remote-code --max-model-len 8192 &
python eval-runners/benchmarks/mobileworld/run_venus.py \
  --data eval-runners/data/mobileworld/gui_only_tasks.jsonl \
  --broker-url http://localhost:9400 --pool-size 8 \
  --model /path/to/UI-Venus-1.5-30B-A3B \
  --api-url http://localhost:8300/v1 --max-steps 50

# Ground truth replay (MobileWorld)
python eval-runners/benchmarks/mobileworld/ground_truth/run_gt_mwenv_broker.py \
  --broker-url http://localhost:9400 --pool-size 8
```

## Directory Structure

```
eval-runners/
├── common/
│   ├── runtime/              # Broker + container management
│   │   ├── pool_broker.py        # AndroidWorld broker
│   │   ├── mw_pool_broker.py     # MobileWorld broker (with /reset)
│   │   ├── androidlab_broker.py  # AndroidLab broker
│   │   ├── container_manager.py  # Docker container lifecycle
│   │   ├── runtime_client.py     # HTTP client to containers
│   │   └── pool_client.py        # Broker client (acquire/return)
│   └── utils/
│       ├── trajectory.py         # Trajectory data structures
│       └── trajectory_saver.py   # ATIF trajectory export
│
├── agents/
│   ├── cli/                  # CLI-based agents (ADB commands, no screenshots)
│   │   ├── claude_sdk/           # Claude Code CLI agent
│   │   │   ├── android_env.py        # Environment wrapper
│   │   │   ├── runner.py             # Agent runner
│   │   │   ├── tools.py              # Tool definitions
│   │   │   └── prompts/              # All prompts (AW + MW)
│   │   │       ├── adb_baseline.py
│   │   │       ├── mw_adb_oracle.py
│   │   │       └── ...
│   │   ├── terminus2/            # Terminus2 agent
│   │   │   ├── agent.py
│   │   │   ├── prompts.py
│   │   │   └── templates/
│   │   └── mini_swe/             # Mini-SWE agent
│   │       └── environment.py
│   └── gui/                  # GUI-based agents (screenshots + actions)
│       ├── gui_agent_broker.py   # Shared runner with retry logic
│       ├── venus_common.py       # UI-Venus agent wrapper
│       ├── qwen3vl_common.py     # Qwen3-VL agent wrapper
│       └── qwen35_dashscope_common.py
│
├── benchmarks/
│   ├── androidworld/         # AndroidWorld (116 tasks)
│   │   ├── run_claude_cli.py
│   │   ├── run_claude_cli_oracle.py
│   │   ├── run_openai.py
│   │   ├── run_terminus2.py
│   │   ├── run_mini_swe.py
│   │   ├── claude_cli_common.py
│   │   ├── configs/              # OpenAI yaml configs
│   │   └── ground_truth/
│   │       └── run_ground_truth.py
│   │
│   ├── mobileworld/          # MobileWorld (117 GUI-only tasks)
│   │   ├── run_claude_cli.py
│   │   ├── run_venus.py
│   │   ├── run_qwen3vl.py
│   │   ├── run_qwen35_dashscope.py
│   │   ├── run_gui_agent_broker.py   # Generic GUI agent (Gemini, etc.)
│   │   ├── mw_cli_common.py
│   │   └── ground_truth/
│   │       ├── run_gt_mwenv_broker.py
│   │       ├── gt_commands_mwenv.json    # 111 CLI GT trajectories
│   │       └── run_discovery_gt_live.py
```

## Architecture

Every evaluation follows the same pattern:

```
Runner Script  →  Broker (acquire container)  →  Agent  →  Container (emulator)  →  Eval  →  Broker (return)
```

1. **Runner** loads task list, spawns N parallel workers
2. Each worker **acquires** a container from the broker
3. Worker creates an **agent** (CLI or GUI) and runs it on the task
4. Agent interacts with the **container** (ADB commands or screenshots+actions)
5. Worker calls **eval** (verifier checks device state)
6. Worker **returns** container to broker (with `/reset` for clean state)

### CLI vs GUI Agents

| | CLI Agent | GUI Agent |
|---|---|---|
| Input | ADB shell output, file contents | Screenshots (PIL images) |
| Output | ADB commands, SQL queries | Tap/swipe/type coordinates |
| Example | Claude Code, Terminus2 | Venus, Qwen3VL, Gemini |
| Speed | Fast (text only) | Slow (vision model per step) |
| Benchmark | Both AW + MW | Primarily MW |

### Broker Protocol

All brokers expose the same HTTP API:

| Endpoint | Purpose |
|----------|---------|
| `POST /acquire` | Get a container `{pid, timeout}` → `{env_id, server_url}` |
| `POST /return` | Return a container `{env_id, healthy}` (triggers `/reset`) |
| `GET /status` | Pool status `{total, idle, leased}` |
| `GET /health` | Broker health check |

### Default Parameters

| Parameter | AndroidWorld | MobileWorld |
|-----------|-------------|-------------|
| Max steps | 30 | **50** |
| Pool size | 16 | 8-16 |
| Broker port | 9300 | 9400 |
| Container image | `androidworld:2026` | `mobile_world:reset` |

## Results

Results are saved to `eval-runners/results/` with auto-generated names:

```
eval-runners/results/{AgentClass}_{ModelShort}_{yymmdd}_{HHMM}/
├── results.jsonl        # Per-task results
├── summary.json         # Aggregate stats
└── atif_trajectories/   # ATIF-v1.6 trajectory files
```

See [`results/table.md`](results/table.md) for the latest benchmark numbers.
