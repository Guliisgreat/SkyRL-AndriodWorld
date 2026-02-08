"""
Test fixtures for ContainerManager and RuntimeClient tests.
"""

import numpy as np
from unittest.mock import Mock, MagicMock
from pathlib import Path
import pytest

from skyrl_agent.runtime.android.container_manager import ContainerInstance


@pytest.fixture
def mock_container_instance():
    """Create mock ContainerInstance."""
    mock_container = Mock()
    mock_container.id = "test-container-id"
    mock_container.stop = Mock()
    
    return ContainerInstance(
        container_id="test-container-id",
        container=mock_container,
        server_port=5555,
        emulator_port=5574,
        grpc_port=8554,
        env_id=0,
        state="ready"
    )


@pytest.fixture
def sample_observation():
    """Create sample observation dict."""
    return {
        "task": "Open calculator app",
        "image": np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8),
        "image_shape": [1080, 1920, 3],
        "image_dtype": "uint8"
    }


@pytest.fixture
def sample_observation_base64():
    """Create sample observation with base64-encoded image."""
    import base64
    image = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
    
    return {
        "task": "Open calculator app",
        "image": base64.b64encode(image.tobytes()).decode("utf-8"),
        "image_shape": [1080, 1920, 3],
        "image_dtype": "uint8"
    }


# Note: mock_docker_client is defined in test_container_manager.py
# This fixture is kept for backward compatibility with other test files
@pytest.fixture
def mock_docker_client_legacy():
    """Mock docker client (legacy - use injection instead)."""
    from unittest.mock import patch
    
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.id = "test-id"
    mock_container.stop = Mock()
    mock_container.status = "running"
    mock_container.attrs = {
        'NetworkSettings': {
            'Ports': {}
        }
    }
    
    mock_client.containers.list.return_value = []
    mock_client.containers.run.return_value = mock_container
    mock_client.containers.get.side_effect = Exception("Not found")
    
    # Patch docker.from_env at the point where it's called
    with patch('skyrl_agent.runtime.android.container_manager.docker') as mock_docker_module:
        mock_docker_module.from_env = Mock(return_value=mock_client)
        yield mock_client


@pytest.fixture
def reset_payload():
    """Sample reset payload."""
    return {
        "seed": 42,
        "options": {
            "task_id": 0,
            "go_home_on_reset": True,
            "epoch": 0,
            "mode": "train",
            "traj": 0,
            "total_traj": 1
        }
    }


@pytest.fixture
def step_payload():
    """Sample step payload."""
    return {
        "action": {
            "action_type": "click",
            "touch_point": [0.5, 0.5]
        },
        "thought": "Clicking on the center of the screen"
    }


@pytest.fixture
def reset_response(sample_observation_base64):
    """Sample reset response from container server."""
    return {
        "status": "success",
        "observation": sample_observation_base64,
        "info": {}
    }


@pytest.fixture
def step_response(sample_observation_base64):
    """Sample step response from container server."""
    return {
        "status": "success",
        "observation": sample_observation_base64,
        "reward": 1.0,
        "terminated": False,
        "truncated": False,
        "info": {}
    }
