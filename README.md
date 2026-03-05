<div align="center">

# SkyRL-AndroidWorld

Training and evaluating Android GUI agents with reinforcement learning.

</div>

---

## What is this?

This repo uses the [SkyRL](https://github.com/NovaSky-AI/SkyRL) framework to train and evaluate LLM agents on [AndroidWorld](https://github.com/google-research/android_world) tasks — real Android device automation through GUI interaction and ADB commands.

## Quick Navigation

| I want to... | Go to |
|---|---|
| **Run inference** with an existing model | [`skyrl-agent/examples/README.md`](./skyrl-agent/examples/README.md) |
| **Set up Docker containers** for Android emulators | [`docker/android/README.md`](./docker/android/README.md) |
| **Understand the agent framework** | [`skyrl-agent/README.md`](./skyrl-agent/README.md) |
| **Train a model** with RL | [`skyrl-agent/examples/README.md`](./skyrl-agent/examples/README.md) |
| **Read design docs** | [`docs/`](./docs/) |

## Repository Structure

```
SkyRL-AndroidWorld/
├── skyrl-agent/          Agent framework, inference & training scripts
│   ├── skyrl_agent/      Core Python package
│   ├── examples/         Shell scripts + YAML configs to run everything
│   ├── data/             Test/train data (JSONL)
│   └── tests/            Unit and integration tests
│
├── skyrl-train/          RL training framework (FSDP, PPO, async)
├── docker/android/       Dockerfiles + server code for Android emulators
├── docs/                 Architecture docs, design specs, agent references
│   ├── design/           Technical design docs (human review)
│   └── ref_agent/        Implementation references (Claude Code reads these)
│
└── CLAUDE.md             Rules for Claude Code
```

## Typical Workflow

```
1. Build Docker image          docker/android/README.md
2. Start broker (optional)     docker/android/README.md
3. Run inference or training   skyrl-agent/examples/README.md
```

## Packages

- [`skyrl-agent`](./skyrl-agent) — Agent layer: agents, tasks, tools, runtime, dispatchers
- [`skyrl-train`](./skyrl-train) — Training framework: FSDP + vLLM async RL
- [`skyrl-tx`](./skyrl-tx) — Tinker REST API backend (experimental)

## Citation

```bibtex
@article{cao2025skyrl,
  title={SkyRL-Agent: Efficient RL Training for Multi-turn LLM Agent},
  author={Cao, Shiyi and Li, Dacheng and Zhao, Fangzhou and Yuan, Shuo and Hegde, Sumanth R and Chen, Connor and Ruan, Charlie and Griggs, Tyler and Liu, Shu and Tang, Eric and others},
  journal={arXiv preprint arXiv:2511.16108},
  year={2025}
}
```
