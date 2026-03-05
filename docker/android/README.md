# Android Emulator Containers

Docker containers running Android emulators for AndroidWorld evaluation and training.

## Quick Start

Build the recommended image and run inference:

```bash
# 1. Build (requires base image androidworld:v8)
docker build -f docker/android/Dockerfile.full_adb_agent \
    -t androidworld:full_adb_agent docker/android

# 2. Run inference (containers are created automatically)
cd skyrl-agent
OPENAI_API_KEY=sk-... ./examples/run_openai/openai_android_inference.sh
```

## Docker Images

```
ubuntu:22.04
  └── androidworld:v8              (base image — must be built first)
        ├── androidworld:v9         (ADB port fix only)
        ├── androidworld-adb:v8     (/step_adb only)
        └── androidworld:full_adb_agent  ← RECOMMENDED
```

**Use `androidworld:full_adb_agent`** unless you have a specific reason not to. It supports all agent types.

| Feature | v8 (base) | v9 | adb:v8 | full_adb_agent |
|---|---|---|---|---|
| GUI agents (`/step`) | Yes | Yes | Yes | Yes |
| ADB agents (`/step_adb`) | — | — | Yes | Yes |
| A11y tree in observations | — | — | — | Yes |
| 16+ parallel containers | — | Yes | — | Yes |

### Build Commands

```bash
# Base image (required first)
cd docker/android && docker build -t androidworld:v8 .

# Recommended: full-featured image
docker build -f docker/android/Dockerfile.full_adb_agent \
    -t androidworld:full_adb_agent docker/android

# Other variants (only if needed)
docker build -f docker/android/Dockerfile.v9 -t androidworld:v9 docker/android
docker build -f docker/android/Dockerfile.adb -t androidworld-adb:v8 docker/android
```

## Container Management: Mode A vs Mode B

### Mode A — Local (default)

Scripts create and destroy containers automatically. Simple but slow to start (~5 min for 16 containers).

```yaml
# In your YAML config — no broker_url means Mode A
env:
  docker_image: androidworld:full_adb_agent
  pool_size: 16
```

### Mode B — Broker (recommended for iterating)

A persistent broker process owns a shared container pool. Scripts acquire/return containers via HTTP. Fast startup, survives script restarts.

**Step 1: Start the broker**

```bash
cd skyrl-agent
python -m skyrl_agent.runtime.android.pool_broker \
    --pool-size 16 \
    --docker-image androidworld:full_adb_agent \
    --port 9200 \
    --base-env-id 0
```

**Step 2: Point scripts to the broker**

```yaml
# In your YAML config
env:
  broker_url: "http://localhost:9200"
  docker_image: androidworld:full_adb_agent
  pool_size: 16
```

The broker keeps containers running between experiments. To stop it, kill the process — it cleans up containers on exit.

**Broker API:**

| Endpoint | Method | Description |
|---|---|---|
| `/status` | GET | Pool status (available, in-use, total) |
| `/acquire` | POST | Get a container for a task |
| `/return` | POST | Return a container to the pool |
| `/health` | GET | Broker health check |

## How Containers Work

Each container runs:
- Android emulator (AOSP)
- ADB daemon (unique port per container)
- FastAPI server exposing `/health`, `/reset`, `/step`, `/step_adb`

With host networking, each container binds to a unique server port (`5001 + env_id`). The agent talks only to the server port via HTTP.

```
Host machine
├── localhost:5001 → container 0 (env_id=0)
├── localhost:5002 → container 1 (env_id=1)
├── localhost:5004 → container 2 (env_id=2)
└── ...
```

## Troubleshooting

- **KVM required**: The Android emulator needs `/dev/kvm`. Check: `ls /dev/kvm`
- **Slow first start**: Emulator boot takes ~2-3 min per container. Use the broker to avoid re-creating.
- **Port conflicts**: If containers fail to start, check for leftover containers: `docker ps -a | grep androidworld`
- **Health check**: `curl http://localhost:5001/health` should return `{"status": "ok"}`

## Further Reading

- [`DOCKERFILE_COMPARISON.md`](./DOCKERFILE_COMPARISON.md) — detailed feature comparison of all images
- [`PORTS_AND_HOST_CONNECTIVITY.md`](./PORTS_AND_HOST_CONNECTIVITY.md) — deep dive on port allocation and networking
- [`docs/ref_agent/container_pool_broker.md`](../../docs/ref_agent/container_pool_broker.md) — broker architecture details
