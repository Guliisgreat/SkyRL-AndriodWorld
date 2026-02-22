# Debug ADB Docker container

Use the ADB Docker image (`androidworld-adb:v8`) to test that the environment starts and passes health checks.

## 1. Run the debug script (pool of 1 container)

```bash
cd skyrl-agent
ANDROID_DOCKER_IMAGE=androidworld-adb:v8 python scripts/debug_adb_container.py --pool-size 1 --timeout 420
```

If health checks keep failing, see step 2 to inspect container logs.

## 2. Run one container and stream logs (when health fails)

```bash
docker run --rm -p 5000:5000 -p 5574:5574 -p 8574:8574 \
  -e SERVER_PORT=5000 -e EMULATOR_PORT=5574 -e GRPC_PORT=8574 -e ENV_ID=0 \
  -e ENV_SAMPLE_MODE=sequential -e ENV_SAVE_IMAGES=False -e ENV_SNAPSHOT=clean \
  -e ENV_TASK_FAMILY=android_world --device /dev/kvm \
  androidworld-adb:v8
```

In another terminal after ~2 min: `curl -s http://localhost:5000/health`.  
Check the first terminal for Python/uvicorn errors (e.g. import or env init).

## 3. Run integration tests with ADB image

```bash
cd skyrl-agent
RUN_DOCKER_TESTS=true ANDROID_DOCKER_IMAGE=androidworld-adb:v8 \
  pytest tests/integration/runtime/androidworld/test_error_recovery.py \
  -v -s -k "TestHealthEndpoints" --timeout=600
```

Uses the same container pool as inference; requires Docker and KVM.
