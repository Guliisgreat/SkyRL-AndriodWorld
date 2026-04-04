"""
Integration test: Venus GUI agent against a live AndroidWorld container.

Requires:
- Docker installed and running (or a pre-existing container via AW_CONTAINER_URL)
- KVM support (for Android emulator, only when creating new container)
- Built androidworld:2026 image (only when creating new container)
- A running Venus-compatible LLM endpoint

Run with a pre-existing container (fastest):
    RUN_DOCKER_TESTS=true \\
    AW_CONTAINER_URL=http://localhost:5018 \\
    VENUS_MODEL=/shared/darren/models/Qwen3-VL-8B-Instruct \\
    VENUS_API_URL=http://localhost:8100/v1 \\
    pytest tests/integration/runtime/androidworld/test_venus_agent.py -v -s

Run with auto-created container (slow, ~6min startup):
    RUN_DOCKER_TESTS=true \\
    VENUS_MODEL=ui-venus-7b \\
    VENUS_API_URL=http://localhost:8000/v1 \\
    pytest tests/integration/runtime/androidworld/test_venus_agent.py -v -s

Environment variables:
    RUN_DOCKER_TESTS=true          - Enable Docker tests
    AW_CONTAINER_URL               - URL of a pre-existing healthy AW container (skips Docker)
    ANDROID_DOCKER_IMAGE           - Docker image (default: androidworld:2026)
    DOCKER_TEST_TIMEOUT            - Container startup timeout in seconds (default: 600)
    VENUS_MODEL                    - Model name for the OpenAI-compatible API (required)
    VENUS_API_URL                  - API base URL (required)
    VENUS_API_KEY                  - API key (default: "empty")
"""

import os
import sys
import time

import pytest
import requests

# ---------------------------------------------------------------------------
# Path setup so we can import venus_common from the examples directory
# ---------------------------------------------------------------------------

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, os.pardir, os.pardir, os.pardir, os.pardir))
_GUI_DIR = os.path.join(_REPO_ROOT, "examples", "run_mobileworld_gui")
_CLAUDE_SDK_DIR = os.path.join(_REPO_ROOT, "examples", "run_claude_sdk")

for p in (_GUI_DIR, _CLAUDE_SDK_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

DOCKER_AVAILABLE = os.path.exists("/var/run/docker.sock") or os.environ.get("DOCKER_HOST")
RUN_DOCKER_TESTS = os.environ.get("RUN_DOCKER_TESTS", "").lower() == "true"
KVM_AVAILABLE = os.path.exists("/dev/kvm")

VENUS_MODEL = os.environ.get("VENUS_MODEL", "")
VENUS_API_URL = os.environ.get("VENUS_API_URL", "")
VENUS_API_KEY = os.environ.get("VENUS_API_KEY", "empty")
AW_CONTAINER_URL = os.environ.get("AW_CONTAINER_URL", "")

skip_without_docker = pytest.mark.skipif(
    not (DOCKER_AVAILABLE and RUN_DOCKER_TESTS) and not AW_CONTAINER_URL,
    reason="Docker tests disabled (set RUN_DOCKER_TESTS=true or AW_CONTAINER_URL)",
)
skip_without_kvm = pytest.mark.skipif(
    not KVM_AVAILABLE and not AW_CONTAINER_URL,
    reason="KVM not available and no pre-existing container (set AW_CONTAINER_URL)",
)
skip_without_venus = pytest.mark.skipif(
    not (VENUS_MODEL and VENUS_API_URL),
    reason="Venus LLM not configured (set VENUS_MODEL and VENUS_API_URL)",
)

# AndroidWorld uses numeric task IDs
SAMPLE_TASK = {
    "task_id": 12,
    "seed": 7,
    "task": "Delete all my notes in Markor.",
    "difficulty": "android_easy",
    "category": "random_init",
}

VALID_AW_ACTION_TYPES = {
    "click", "long_press", "input_text", "scroll", "status",
    "answer", "navigate_home", "navigate_back", "keyboard_enter",
    "open_app", "wait",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_health(url: str, timeout: int = 600, interval: int = 10) -> None:
    """Poll health endpoint until 200 or timeout."""
    start = time.time()
    last_err = None
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{url}/health", timeout=10)
            if resp.status_code == 200:
                return
        except Exception as e:
            last_err = e
        time.sleep(interval)
    raise TimeoutError(
        f"Container at {url} not healthy after {timeout}s: {last_err}"
    )


def cleanup_container(container) -> None:
    """Stop and remove a container, ignoring errors."""
    try:
        container.stop(timeout=10)
    except Exception:
        pass
    try:
        container.remove(force=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def docker_image():
    return os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:2026")


@pytest.fixture(scope="module")
def container_timeout():
    return int(os.environ.get("DOCKER_TEST_TIMEOUT", "600"))


@pytest.fixture(scope="module")
def docker_client():
    if AW_CONTAINER_URL:
        return None
    try:
        import docker
        return docker.from_env()
    except ImportError:
        pytest.skip("docker-py not installed")
    except Exception as e:
        pytest.skip(f"Cannot connect to Docker: {e}")


@pytest.fixture(scope="module")
def aw_container(docker_client, docker_image, container_timeout):
    """Yield an AndroidWorld container URL.

    If AW_CONTAINER_URL is set, uses that pre-existing container (no Docker
    management). Otherwise starts a new container and cleans up after.
    """
    if AW_CONTAINER_URL:
        wait_for_health(AW_CONTAINER_URL, timeout=30)
        yield AW_CONTAINER_URL
        return

    port = 5900
    container = None
    try:
        container = docker_client.containers.run(
            docker_image,
            environment={
                "SERVER_PORT": str(port),
                "EMULATOR_PORT": "5594",
                "GRPC_PORT": "8594",
                "ENV_ID": "0",
                "ENV_SAMPLE_MODE": "sequential",
                "ENV_SNAPSHOT": "clean",
            },
            devices=["/dev/kvm"],
            network_mode="host",
            detach=True,
            auto_remove=False,
            name="test_venus_aw",
        )
        base_url = f"http://localhost:{port}"
        wait_for_health(base_url, timeout=container_timeout)
        yield base_url
    finally:
        if container:
            cleanup_container(container)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@skip_without_docker
@skip_without_kvm
@skip_without_venus
class TestVenusAgentOnAndroidWorld:
    """Run Venus agent against a live AndroidWorld container."""

    def test_single_task_completes(self, aw_container):
        """Reset container, run one task, verify result dict structure."""
        from venus_common import run_venus_task_sync

        result = run_venus_task_sync(
            SAMPLE_TASK,
            aw_container,
            model=VENUS_MODEL,
            api_url=VENUS_API_URL,
            api_key=VENUS_API_KEY,
            max_steps=5,
            task_timeout=300,
            history_length=3,
        )

        assert isinstance(result, dict)
        for key in ("task_id", "seed", "task", "reward", "step_count",
                     "finished", "commands", "last_error"):
            assert key in result, f"Missing key: {key}"

        assert result["task_id"] == SAMPLE_TASK["task_id"]
        assert not result["last_error"], (
            f"Task runner returned error: {result['last_error']}"
        )
        assert result["step_count"] > 0, "Agent took zero steps"
        assert isinstance(result["commands"], list)
        assert len(result["commands"]) > 0

    def test_action_mapping_valid(self, aw_container):
        """Verify all emitted actions have valid AndroidWorld action_type."""
        from venus_common import run_venus_task_sync

        result = run_venus_task_sync(
            SAMPLE_TASK,
            aw_container,
            model=VENUS_MODEL,
            api_url=VENUS_API_URL,
            api_key=VENUS_API_KEY,
            max_steps=3,
            task_timeout=300,
            history_length=3,
        )

        commands = result.get("commands", [])
        assert len(commands) > 0, (
            f"No commands produced; last_error={result.get('last_error')}"
        )
        for entry in commands:
            aw_action = entry.get("aw_action", {})
            at = aw_action.get("action_type")
            assert at in VALID_AW_ACTION_TYPES, (
                f"Unexpected action_type={at!r} at step {entry.get('step_idx')}"
            )

    def test_timeout_respected(self, aw_container):
        """Run with a very short timeout and verify it aborts promptly."""
        from venus_common import run_venus_task_sync

        start = time.time()
        result = run_venus_task_sync(
            SAMPLE_TASK,
            aw_container,
            model=VENUS_MODEL,
            api_url=VENUS_API_URL,
            api_key=VENUS_API_KEY,
            max_steps=100,
            task_timeout=5,
            history_length=0,
        )
        elapsed = time.time() - start

        # Should finish well before the default 1800s timeout.
        # Allow generous headroom for reset + one LLM call.
        assert elapsed < 120, f"Took {elapsed:.0f}s despite 5s task_timeout"
        assert result["last_error"] == "task_timeout" or result["step_count"] <= 2
