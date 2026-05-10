# SkyRL-AndroidWorld Code Structure Reference

Up-to-date map of the repository for Claude Code. Read this **before** making
changes to agents, runners, brokers, or benchmark glue. Update this file in
the same PR whenever you move or rename a major component.

> Last sync: post-`237ab9e0` (`refactor: move runtime/brokers and utils to eval-runners/common/`).

---

## 1. Top-level layout

```
SkyRL-AndroidWorld/
├── skyrl-agent/        Training-time agent framework (verl / SkyRL-Train / Tinker)
├── skyrl-train/        RL trainer (FSDP + vLLM async)
├── skyrl-tx/           Tinker-style REST backend (experimental)
├── eval-runners/       Inference-time evaluation harness — broker + per-benchmark runners
├── docker/             Dockerfiles + emulator server image
├── tier4/              ADB-exclusive task definitions injected into androidworld:2026plusswipe_tier4
├── data/               Training/test JSONL datasets
├── docs/               Architecture, design, and reference docs (this file lives here)
└── verify_tier4_on_emulator.py   one-off tier4 verifier check
```

There are **two execution paths**:

| Path | Entry point | When to use |
|---|---|---|
| **Training** | `skyrl-agent/examples/run_verl/verl_android*.sh` | RL training (PPO/GRPO) of Android agents |
| **Eval / Inference** | `eval-runners/benchmarks/*/run_*.py` | Benchmark evaluation, ground-truth replay, model comparison |

They share the broker (`eval-runners/common/runtime/pool_broker.py`) and the
Docker image (`androidworld:2026plusswipe` family).

---

## 2. `skyrl-agent/skyrl_agent/` (training-time package)

```
skyrl_agent/
├── auto.py                      AutoAgentRunner factory
├── config/
│   └── configuration_utils.py   TrajectoryConfig, OmegaConf helpers
│
├── agents/
│   ├── base.py                  AgentRunner base class
│   ├── mapping.py               Agent class registry
│   ├── memory.py                Conversation memory primitives
│   ├── records.py               Trajectory record dataclasses
│   ├── vlm_training.py          VLM-specific trainer hooks
│   ├── react/                   ReAct agent (general-purpose)
│   ├── oh_codeact/              OpenHands CodeAct agent
│   └── android/                 ── Android agent family ──
│       ├── base.py                  AndroidAgent base + TrajectoryState
│       ├── runner.py                AndroidAgentRunner (uses async_fix_pool dispatcher)
│       ├── m3a_agent.py             M3A: multimodal screenshot+a11y agent
│       ├── t3a_agent.py             T3A: text-only a11y agent (index actions)
│       ├── t3a_adb_agent.py         T3A variant emitting raw ADB shell commands
│       ├── tree_adb_agent.py        a11y-tree + ADB hybrid
│       ├── screen_agent.py          screenshot-only GUI agent
│       ├── screen_adb_agent.py      screenshot + ADB shell agent (the "ADB agent")
│       ├── combo_agent.py           orchestrator combining multiple agents
│       ├── mobileuse/               MobileUse-style agent (subdir)
│       ├── prompts.py               shared prompt templates
│       └── utils.py                 parsing, image, action helpers
│
├── tasks/
│   ├── base.py                  BaseTask
│   ├── android/android_task.py  AndroidTask — owns ContainerManager / runtime client
│   ├── general_react/           ReAct-task glue
│   ├── swebench/                SWE-Bench tasks
│   ├── web_research_task.py     web research
│   └── verifiers/               correctness graders (math, QA, coder1, etc.)
│
├── tools/
│   ├── base.py                  BaseTool, ToolRegistry
│   ├── android_env.py           AndroidEnvTool (wraps AndroidEnv actions)
│   ├── search.py / search_engine.py / local_search.py / web_browser.py
│   ├── sandbox_fusion.py        SandboxFusion code-exec tool
│   ├── finish.py / em_finish.py / next_memagent.py
│   └── prompt.py / cache.py
│
├── runtime/
│   └── android/
│       └── androidlab_docker/   AndroidLab compat shim (skyrl_compat_server.py)
│       (NOTE: container_manager / pool_broker / runtime_client moved to
│        eval-runners/common/runtime/ in commit 237ab9e0.)
│
├── dispatcher/
│   ├── async_utils.py
│   └── dispatchers.py           DISPATCHER_REGISTRY (incl. async_fix_pool_android)
│
├── functional/                  chat templates, function-calling, history utils
│
└── integrations/
    ├── base.py                  GeneratorInput / GeneratorOutput, AsyncInferBackend
    ├── openai.py                OpenAI-compatible inference (LiteLLM)
    ├── verl/                    primary RL backend
    │   ├── verl_main_ppo.py / verl_main_inference.py
    │   ├── verl_async_manager.py / verl_backend.py / verl_trainer.py
    │   ├── verl_compat_patch.py
    │   ├── android_dataset.py    AndroidWorld JSONL → verl batches
    │   └── upload_utils.py
    ├── skyrl_train/             SkyRL-Train backend
    └── tinker/                  Tinker backend
```

### Key contracts

- `AndroidAgentRunner` (`agents/android/runner.py`) drives a batch of trajectories
  through `DISPATCHER_REGISTRY["async_fix_pool_android"]`
  (`dispatcher/dispatchers.py`), which acquires/releases containers via a
  `container_manager` object. In production that object is the
  `BrokerContainerManager` from `eval-runners/common/runtime/pool_client.py` —
  duck-typed to match the legacy `ContainerManager` interface.
- `AndroidTask` (`tasks/android/android_task.py`) owns the container lifecycle
  per trajectory and exposes the Gym-like reset/step API to the agent.
- All agents implement the same `step(observation) → action` protocol; pick the
  variant by class name in the verl YAML (`agent.cls: AndroidT3AADBAgent` etc.).

---

## 3. `eval-runners/` (evaluation harness)

```
eval-runners/
├── README.md                    runbook (start here for any eval workflow)
├── results/                     auto-named per-run output dirs (ATIF trajectories)
├── data/
│   ├── tier4/all_tasks_seed7.jsonl    tier4 source pool (50 + 27 extras = 77 tasks)
│   └── mobileworld/gui_only_tasks.jsonl
│
├── common/
│   ├── runtime/                 ── shared broker + container layer ──
│   │   ├── pool_broker.py           AndroidWorld broker (FastAPI; creates containers)
│   │   ├── mw_pool_broker.py        MobileWorld broker (adopts running containers)
│   │   ├── androidlab_broker.py     AndroidLab broker
│   │   ├── pool_client.py           PoolClient + BrokerContainerManager
│   │   ├── container_manager.py     Local-mode container pool (PortAllocator,
│   │   │                            ContainerFactory, HealthMonitor, ContainerManager)
│   │   ├── runtime_client.py        async HTTP client for /reset, /step, /step_adb
│   │   ├── runtime_client_adb.py    ADB-only fast-path client
│   │   └── exceptions.py            ContainerDeadError + friends
│   └── utils/
│       ├── trajectory.py            TrajectoryRecord
│       └── trajectory_saver.py      ATIF-v1.6 export (Harbor-compatible)
│
├── agents/
│   ├── cli/                     ── ADB-shell / no-screenshot agents ──
│   │   ├── claude_sdk/              Claude Code CLI agent
│   │   │   ├── runner.py / android_env.py / tools.py / mcp_server.py
│   │   │   ├── prompts/                 (adb_baseline, mw_adb_oracle, …)
│   │   │   ├── trajectory.py / wrappers/
│   │   ├── terminus2/               Terminus2 agent
│   │   │   ├── agent.py / environment.py / prompts.py / templates/
│   │   └── mini_swe/                Mini-SWE agent
│   │       └── environment.py / templates/
│   └── gui/                     ── screenshot + tap/swipe/type agents ──
│       ├── gui_agent_broker.py      shared runner with retry/throttling
│       ├── general_e2e_common.py    Gemini / generic E2E
│       ├── gui_owl_ref_common.py    GUI-Owl-1.5
│       ├── mai_common.py            MAI-UI-8B
│       ├── qwen3vl_common.py        Qwen3-VL
│       ├── qwen35_dashscope_common.py
│       └── venus_common.py          UI-Venus-1.5-30B-A3B
│
├── benchmarks/
│   ├── androidworld/
│   │   ├── run_claude_cli.py / run_claude_cli_oracle.py
│   │   ├── run_terminus2.py / run_terminus2_oracle.py
│   │   ├── run_mini_swe.py / run_mini_swe_oracle.py
│   │   ├── run_general_e2e.py / test_vllm_oh_demo.py
│   │   ├── claude_cli_common.py / mini_swe_common.py / terminus2_common.py
│   │   └── ground_truth/
│   │       ├── run_ground_truth.py        ATIF v1 GT replay
│   │       └── verify_v2_edits.py         v2 edit verifier
│   ├── mobileworld/
│   │   ├── run_claude_cli.py / run_terminus2.py / run_mini_swe.py
│   │   ├── run_qwen3vl.py / run_qwen35_dashscope.py
│   │   ├── run_mai.py / run_venus.py
│   │   ├── run_gui_agent_broker.py / run_gui_owl_ref.py
│   │   ├── mw_cli_common.py / mw_tools.py
│   │   ├── mobileworld_tier1a.yaml
│   │   └── ground_truth/                   GT generators + replay
│   └── androidlab/
│       ├── run_claude_cli.py / run_claude_cli_oracle.py
│       ├── run_terminus2.py / run_mini_swe.py / run_gui_agent.py
│       ├── run_original_eval_with_broker.py
│       ├── posthoc_original_xml_eval.py / posthoc_refactored_xml_eval.py
│       ├── cross_validate_dual.py / cross_validate_verifiers.py
│       ├── convert_tasks.py / convert_traces_to_androidlab.py
│       ├── start_broker.sh / run_bash_only.sh
│       ├── androidlab_common.py / androidlab_tasks*.jsonl
│       ├── ground_truth/
│       └── verifiers/
│
└── skyrl_agent/                 (legacy stub kept on PYTHONPATH for back-compat)
```

### Broker protocol (one API across all three benchmarks)

| Endpoint | Body / Response |
|---|---|
| `POST /acquire` | `{pid, timeout}` → `{env_id, server_url}` |
| `POST /return`  | `{env_id, healthy}` (broker calls `/reset` internally) |
| `GET  /status`  | `{total, idle, leased, pool_initializing}` |
| `GET  /health`  | `{status, uptime, pool_ready, pool_target}` |

`BrokerContainerManager` wraps these endpoints behind the same
`allocate_container / release_container / get_pool_status` interface used by
the dispatcher, so training and eval code paths are interchangeable.

---

## 4. `docker/`

```
docker/
├── android/                                 emulator server image (ADB + grpc + FastAPI)
│   ├── Dockerfile / Dockerfile.2026 / Dockerfile.adb / Dockerfile.full_adb_agent
│   ├── Dockerfile.tier4 / Dockerfile.v9
│   ├── entrypoint*.sh
│   ├── server/                              FastAPI server (env.py, etc.)
│   └── skyrl_server/
├── androidworld_2026plusswipe/              upgraded 2026 task suite + swipe gesture
├── androidworld_2026plusswipe_tier4/        + 50 ADB-exclusive tier4 tasks (env.py, test_integration.py)
├── Dockerfile / Dockerfile.megatron / Dockerfile.ray244   training images
```

Build the eval image with `docker/android/`. Build the tier4 task image with
`docker/androidworld_2026plusswipe_tier4/`.

---

## 5. Where to put new code

| Adding… | Goes in |
|---|---|
| New CLI agent (Claude/Terminus-style) | `eval-runners/agents/cli/<agent_name>/` |
| New GUI agent (vision model) | `eval-runners/agents/gui/<agent_name>_common.py` |
| New benchmark wiring | `eval-runners/benchmarks/<bench>/run_<agent>.py` |
| New training agent (used by verl) | `skyrl-agent/skyrl_agent/agents/android/<name>.py` + register in `__init__.py` |
| New broker / pool feature | `eval-runners/common/runtime/pool_broker.py` |
| New container lifecycle change | `eval-runners/common/runtime/container_manager.py` |
| New tier4 task | `tier4/<category>.py` and rebuild `androidworld:2026plusswipe_tier4` |
| New ground-truth ref | edit `docs/final/AndroidWorld2026/androidworld_ground_truth_reference_v2.md` |

---

## 6. Cross-references

- Broker mode A (local) vs mode B (broker): [`container_pool_broker.md`](./container_pool_broker.md)
- ADB agent prompt anatomy: [`adb_agent_prompt_design.md`](./adb_agent_prompt_design.md)
- Error-recovery model (4 layers): [`../error_recovery.md`](../error_recovery.md)
- Eval runbook: [`../../eval-runners/README.md`](../../eval-runners/README.md)
- Training runbook: [`../../skyrl-agent/examples/README.md`](../../skyrl-agent/examples/README.md)
