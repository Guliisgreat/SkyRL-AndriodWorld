"""
Shared pytest fixtures for all tests (unit and integration).

This conftest.py is at the tests root level so fixtures are available
to both unit/ and integration/ test directories.
"""

import asyncio
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from unittest.mock import AsyncMock, Mock, MagicMock

import pytest


# ==================== Configuration Fixtures ====================


@dataclass
class MockTrajectoryConfig:
    """Mock TrajectoryConfig for testing."""
    instance_id: int = 0
    trajectory_id: int = 0
    max_prompt_length: int = 4096
    max_iterations: int = 10
    sampling_params: Dict[str, Any] = field(default_factory=lambda: {
        "temperature": 0.7,
        "max_tokens": 512,
    })
    vision_is_active: bool = True
    qwen3_enable_thinking: bool = False
    qwen3_acc_thinking: bool = False
    tools: List[str] = field(default_factory=lambda: ["android_env"])
    agent_cls: str = "skyrl_agent.agents.android.AndroidAgent"
    max_pixels: int = 1003520
    min_pixels: int = 3136
    profile_tools: bool = False
    debug_log: bool = False
    early_step_threshold: int = 0
    enable_turn_reminder: bool = False
    seed: Optional[int] = None


@pytest.fixture
def mock_traj_config():
    """TrajectoryConfig with test values."""
    return MockTrajectoryConfig()


@pytest.fixture
def mock_traj_config_factory():
    """Factory for creating TrajectoryConfig with custom values."""
    def _factory(**kwargs):
        return MockTrajectoryConfig(**kwargs)
    return _factory


# ==================== Inference Engine Fixtures ====================


@pytest.fixture
def mock_infer_engine():
    """AsyncMock inference engine that returns predefined responses."""
    engine = AsyncMock()
    
    # Default response for click action
    default_response = (
        "Thought: I need to click on the button to proceed.\n"
        "Action: click(start_box='(500,300)')"
    )
    
    engine.async_generate_ids = AsyncMock(return_value=(default_response, "stop"))
    return engine


@pytest.fixture
def mock_infer_engine_factory():
    """Factory for creating mock inference engine with custom responses."""
    def _factory(responses: List[tuple]):
        """
        Create mock engine that returns responses in sequence.
        
        Args:
            responses: List of (response_str, stop_reason) tuples
        """
        engine = AsyncMock()
        engine.async_generate_ids = AsyncMock(side_effect=responses)
        return engine
    return _factory


# ==================== Tokenizer Fixtures ====================


@pytest.fixture
def mock_tokenizer():
    """Mock tokenizer with apply_chat_template method."""
    import torch
    tokenizer = Mock()
    
    def apply_chat_template_fn(*args, **kwargs):
        """Mock apply_chat_template that handles both list and dict returns."""
        token_ids = list(range(100))
        
        # If return_dict is True, return a dict with all required keys
        if kwargs.get('return_dict', False):
            return {
                'input_ids': torch.tensor([token_ids]),
                'attention_mask': torch.ones(len(token_ids)),
                'assistant_masks': torch.ones(len(token_ids)),  # Required by post-processing
            }
        
        # Otherwise return list of token IDs
        return token_ids
    
    tokenizer.apply_chat_template = Mock(side_effect=apply_chat_template_fn)
    tokenizer.pad_token_id = 0
    tokenizer.eos_token_id = 1
    tokenizer.vocab_size = 32000
    
    # Mock decode for any string output needs
    tokenizer.decode = Mock(return_value="decoded text")
    
    # Mock convert_tokens_to_ids for get_rope_index (vision token IDs)
    # These token IDs are used by Qwen2-VL for vision processing
    def convert_tokens_to_ids_fn(token):
        token_map = {
            "<|vision_start|>": 151652,
            "<|vision_end|>": 151653,
            "<|vision_pad|>": 151654,
            "<|image_pad|>": 151655,
        }
        return token_map.get(token, 0)
    
    tokenizer.convert_tokens_to_ids = Mock(side_effect=convert_tokens_to_ids_fn)
    
    return tokenizer


# ==================== Processor Fixtures ====================


@pytest.fixture
def mock_processor():
    """Mock VLM processor for image processing."""
    processor = Mock()
    
    def process_fn(images, texts, add_special_tokens=False, return_tensors="pt"):
        import torch
        batch_size = 1
        seq_len = 50
        
        result = {
            'input_ids': torch.zeros((batch_size, seq_len), dtype=torch.long),
            'attention_mask': torch.ones((batch_size, seq_len), dtype=torch.long),
        }
        
        if images is not None and len(images) > 0:
            result['pixel_values'] = torch.zeros((len(images), 3, 224, 224))
            result['image_grid_thw'] = torch.tensor([[1, 14, 14]] * len(images))
        
        return result
    
    processor.side_effect = process_fn
    processor.return_value = process_fn(None, ["test"], return_tensors="pt")
    
    # Mock processor.tokenizer for get_rope_index (Qwen2-VL vision tokens)
    def convert_tokens_to_ids_fn(token):
        token_map = {
            "<|vision_start|>": 151652,
            "<|vision_end|>": 151653,
            "<|vision_pad|>": 151654,
            "<|image_pad|>": 151655,
            "<|video_pad|>": 151656,
        }
        return token_map.get(token, 0)
    
    processor.tokenizer = Mock()
    processor.tokenizer.convert_tokens_to_ids = Mock(side_effect=convert_tokens_to_ids_fn)
    
    # Mock processor.image_processor for merge_size
    processor.image_processor = Mock()
    processor.image_processor.merge_size = 2
    
    return processor


# ==================== Environment Handle Fixtures ====================


@pytest.fixture
def sample_observation():
    """Sample observation dict with image array."""
    return {
        "task": "Open the Settings app and navigate to Wi-Fi settings",
        "image": np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8),
    }


@pytest.fixture
def sample_observation_no_image():
    """Sample observation dict without image."""
    return {
        "task": "Open the Settings app",
        "image": None,
    }


@pytest.fixture
def mock_env_handle(sample_observation):
    """Mock environment handle with step/reset methods."""
    env = AsyncMock()
    
    # Reset returns initial observation
    env.reset = AsyncMock(return_value=(sample_observation, {}))
    
    # Step returns (obs, reward, terminated, truncated, info)
    step_obs = {
        "image": np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8),
    }
    env.step = Mock(return_value=(step_obs, 0.0, False, False, {}))
    
    return env


@pytest.fixture
def mock_env_handle_terminated(sample_observation):
    """Mock environment handle that terminates after one step."""
    env = AsyncMock()
    env.reset = AsyncMock(return_value=(sample_observation, {}))
    
    step_obs = {"image": None}
    env.step = Mock(return_value=(step_obs, 1.0, True, False, {"success": True}))
    
    return env


@pytest.fixture
def mock_env_handle_factory(sample_observation):
    """Factory for creating mock environment handles with custom behavior."""
    def _factory(
        step_returns: Optional[List[tuple]] = None,
        reset_obs: Optional[Dict] = None,
    ):
        env = AsyncMock()
        
        obs = reset_obs if reset_obs is not None else sample_observation
        env.reset = AsyncMock(return_value=(obs, {}))
        
        if step_returns is not None:
            env.step = Mock(side_effect=step_returns)
        else:
            step_obs = {"image": np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8)}
            env.step = Mock(return_value=(step_obs, 0.0, False, False, {}))
        
        return env
    return _factory


# ==================== Instruction Fixtures ====================


@pytest.fixture
def sample_instruction():
    """Sample formatted instruction messages in OpenAI format."""
    return [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are a helpful assistant."}]
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "Open the Settings app"}]
        },
        {
            "role": "user",
            "content": [{
                "type": "image",
                "image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "min_pixels": 3136,
                "max_pixels": 1003520,
            }]
        },
    ]


# ==================== Task and Data Fixtures ====================


@pytest.fixture
def sample_instance():
    """Sample task instance data."""
    return {
        "task_id": 1,
        "task": "Open Settings app",
        "app_name": "Settings",
    }


@pytest.fixture
def sample_data(sample_instance):
    """Sample trajectory data dict."""
    return {
        "instance_id": 0,
        "instance": sample_instance,
        "epoch": 0,
        "mode": "train",
    }


# ==================== Mock Task Fixtures ====================


@pytest.fixture
def mock_task(sample_instruction):
    """Mock AndroidTask for testing."""
    task = Mock()
    # get_instruction now only returns system prompt (first message)
    task.get_instruction = Mock(return_value=[sample_instruction[0]])
    # format_observation returns the rest (user text + image)
    task.format_observation = Mock(return_value=sample_instruction[1:])
    task.evaluate_result = AsyncMock(return_value=1.0)
    task.initialize_runtime = AsyncMock(return_value=[Mock() for _ in range(4)])
    task.complete_runtime = Mock(return_value={})
    return task


# ==================== Raw Output Test Data ====================


@pytest.fixture
def raw_output_click():
    """Sample raw output for click action."""
    return (
        "Thought: I need to click on the Settings icon to open the app.\n"
        "Action: click(start_box='(500,300)')"
    )


@pytest.fixture
def raw_output_scroll():
    """Sample raw output for scroll action."""
    return (
        "Thought: I need to scroll down to see more options.\n"
        "Action: scroll(start_box='(500,800)', end_box='(500,200)')"
    )


@pytest.fixture
def raw_output_type():
    """Sample raw output for type action."""
    return (
        "Thought: I need to enter the search query.\n"
        "Action: type(content='WiFi settings')"
    )


@pytest.fixture
def raw_output_open_app():
    """Sample raw output for open_app action."""
    return (
        "Thought: I need to open the Settings app.\n"
        "Action: open_app(content='Settings')"
    )


@pytest.fixture
def raw_output_finished():
    """Sample raw output for finished action."""
    return (
        "Thought: The task is complete.\n"
        "Action: finished(content='Task completed successfully')"
    )


@pytest.fixture
def raw_output_invalid():
    """Sample raw output with invalid action."""
    return (
        "Thought: I'm not sure what to do.\n"
        "Action: unknown_action(param='value')"
    )


# ==================== Small Image Fixture ====================


@pytest.fixture
def small_test_image():
    """Small test image as numpy array (10x10 RGB)."""
    return np.random.randint(0, 255, (10, 10, 3), dtype=np.uint8)


# ==================== Integration Test Support ====================


# Check for optional dependencies
TRANSFORMERS_AVAILABLE = False
try:
    from transformers import AutoTokenizer, AutoProcessor
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    pass

QWEN_VL_UTILS_AVAILABLE = False
try:
    from qwen_vl_utils import process_vision_info  # noqa: F401
    QWEN_VL_UTILS_AVAILABLE = True
except ImportError:
    pass


@pytest.fixture(scope="session")
def integration_model_name():
    """Model name for integration tests (can be overridden via env var)."""
    import os
    return os.environ.get("TEST_VLM_MODEL", "Qwen/Qwen2-VL-2B-Instruct")


@pytest.fixture(scope="session")
def real_tokenizer_session(integration_model_name):
    """
    Session-scoped real tokenizer for integration tests.
    
    Returns None if transformers not available (tests using this should skip).
    """
    if not TRANSFORMERS_AVAILABLE:
        return None
    
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            integration_model_name,
            trust_remote_code=True,
        )
        return tokenizer
    except Exception:
        return None


@pytest.fixture(scope="session")
def real_processor_session(integration_model_name):
    """
    Session-scoped real processor for integration tests.
    
    Returns None if transformers not available (tests using this should skip).
    """
    if not TRANSFORMERS_AVAILABLE:
        return None
    
    try:
        processor = AutoProcessor.from_pretrained(
            integration_model_name,
            trust_remote_code=True,
        )
        return processor
    except Exception:
        return None


@pytest.fixture
def real_traj_config():
    """Real TrajectoryConfig for integration tests."""
    from skyrl_agent.config.configuration_utils import TrajectoryConfig
    
    return TrajectoryConfig(
        instance_id=0,
        trajectory_id=0,
        max_prompt_length=4096,
        max_iterations=5,
        sampling_params={"temperature": 0.7, "max_tokens": 512},
        vision_is_active=True,
        tools=["android_env"],
        agent_cls="skyrl_agent.agents.android.AndroidAgent",
    )


# ==================== Pytest Configuration ====================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (may require external deps)"
    )
    config.addinivalue_line(
        "markers", "e2e: mark test as end-to-end test (requires full environment)"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow (longer than 1s)"
    )
