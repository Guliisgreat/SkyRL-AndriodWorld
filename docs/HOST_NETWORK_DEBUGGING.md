# Host network debugging (AndroidWorld containers)

When `use_host_network: true` is set in the task YAML, containers use `network_mode: "host"` and each gets a dedicated ADB server port (`5037 + env_id`). This allows parallel container creation. Failed containers are **not** auto-removed so you can inspect them.

## 0. Verify parallel host-network creation (before vLLM/agent integration)

To confirm that **parallel creation of multiple containers with host network** works before integrating with the vLLM engine or agent:

```bash
cd skyrl-agent
RUN_DOCKER_TESTS=true ./scripts/verify_host_network_parallel.sh
```

- **Exit 0** → Parallel host-network creation is working; safe to integrate with vLLM/agent.
- **Exit 1** → Verification failed; fix container/image or reduce concurrency before integrating.

The script runs `verify_container_pool.py` with `--host-network`, pool size 4, `--max-concurrent 2` (bounded parallelism so all containers pass health), and `--skip-allocate`. You can override via env: `VERIFY_POOL_SIZE=6 VERIFY_MAX_CONCURRENT=3 ./scripts/verify_host_network_parallel.sh`.

## 1. Run inference with host network (parallel)

```bash
cd skyrl-agent
ENV_POOL_SIZE=8 ./examples/run_verl/verl_android_inference.sh 2>&1 | tee /tmp/verl_host.log
```

Ensure `use_host_network: true` in `examples/run_verl/verl_android_inference.yaml` under `env:`.

## 2. Inspect failed or exited env containers

Containers are named `env0`, `env1`, … With host network, `auto_remove=False`, so exited/failed containers remain.

- List env containers (running and exited):
  ```bash
  docker ps -a --format "{{.Names}}\t{{.Status}}" | grep -E '^env[0-9]' | sort -V
  ```

- Logs for a specific env (e.g. env1):
  ```bash
  docker logs env1 2>&1
  ```

- Collect logs for **all** env* containers into a directory (run from repo root):
  ```bash
  ./skyrl-agent/scripts/collect_env_logs.sh -o /tmp/env_logs
  ```

## 3. Check what is listening on host ports

With host network, each container’s server listens on the host. If only env0 is ready, only that port will be in use:

```bash
# Expected: 5000, 5002, 5004, ... (one per env when all healthy)
ss -tlnp | grep -E '5000|5002|5004|5006|5008|5010|5012|5014'
```

Confirm which env uses which port from the inference log (e.g. `[ContainerFactory] envN: ... server=PORT`).

## 4. Manually run one env with host network (e.g. env1)

Use the same env vars the manager passes so you can reproduce failures:

```bash
docker run --rm -it --name env1_debug \
  -e ENV_ID=1 \
  -e SERVER_PORT=5002 \
  -e EMULATOR_PORT=5587 \
  -e GRPC_PORT=8587 \
  -e ADB_SERVER_PORT=5038 \
  -e ENV_SAMPLE_MODE=sequential \
  -e ENV_SAVE_IMAGES=False \
  -e ENV_SNAPSHOT=clean \
  -e ENV_TASK_FAMILY=android_world \
  --network=host \
  --device /dev/kvm \
  androidworld:v9
```

Watch for emulator startup, ADB, or Python/server errors. In another terminal, after the server is up: `curl -s http://localhost:5002/health`.

## 5. Clean up before a fresh run

Remove leftover env containers so the next run doesn’t hit name/port conflicts:

```bash
for i in $(seq 0 15); do docker rm -f env$i 2>/dev/null; done
```

## Why might only one container pass health with parallel + host network?

- The server inside the container only starts listening (and thus responds to `/health`) **after** the lifespan runs: it starts the emulator, waits, then calls `get_raw_observation()`. If the emulator never becomes ready or that call hangs, the HTTP server never starts.
- All containers previously shared a single host log volume (`temp_path/log` → `/data/log`). That can cause races or locks when many start in parallel. The code now uses a **per-env log dir** for host network (`temp_path/env{id}/log` → `/data/log`) so each container has its own log directory.
- If only one (or a few) still pass after that, likely causes are **resource contention** (e.g. 10 emulators competing for KVM/CPU so only some boot in time). In that case try serial creation (e.g. lower `max_concurrent` or run `verify_container_pool.py` with `--pool-size 1`) or inspect `docker logs envN` for the failing envs.

## Requirements for host network

- Docker image must support per-container ADB port (e.g. **androidworld:v9**): entrypoint uses `adb -P ${ADB_SERVER_PORT:-5037} devices`, and `server/env.py` uses `ADB_SERVER_PORT` / `-P` in all adb calls.
- Task YAML: `env.use_host_network: true` and `env.docker_image: androidworld:v9` (or a similarly updated image).
