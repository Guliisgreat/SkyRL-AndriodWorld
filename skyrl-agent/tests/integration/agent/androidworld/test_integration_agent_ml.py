"""
Integration tests for Agent + ML Components (Tokenizer, Processor).

Tests verify that AndroidAgent correctly interacts with real HuggingFace
tokenizer and processor components, catching:
- Tensor shape mismatches
- Tokenization edge cases
- Image processing issues
- Training data quality

These tests require transformers and qwen_vl_utils packages.
"""

import os
import numpy as np
from typing import Dict, Any, List
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import pytest


# ==================== Skip Markers ====================

# Check for optional dependencies
TRANSFORMERS_AVAILABLE = False
try:
    import torch
    from transformers import AutoTokenizer, AutoProcessor
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    pass

QWEN_VL_UTILS_AVAILABLE = False
try:
    from qwen_vl_utils import process_vision_info
    QWEN_VL_UTILS_AVAILABLE = True
except ImportError:
    pass

# Model for integration tests
TEST_MODEL_NAME = os.environ.get("TEST_VLM_MODEL", "Qwen/Qwen2-VL-2B-Instruct")

skipif_no_transformers = pytest.mark.skipif(
    not TRANSFORMERS_AVAILABLE,
    reason="transformers package not available"
)

skipif_no_qwen_vl = pytest.mark.skipif(
    not QWEN_VL_UTILS_AVAILABLE,
    reason="qwen_vl_utils package not available"
)

skipif_no_ml_deps = pytest.mark.skipif(
    not (TRANSFORMERS_AVAILABLE and QWEN_VL_UTILS_AVAILABLE),
    reason="ML dependencies not available (transformers, qwen_vl_utils)"
)

# Mark all tests in this module
pytestmark = pytest.mark.integration


# ==================== Session-Scoped Fixtures ====================
# These are expensive to create, so we reuse them across tests


@pytest.fixture(scope="module")
def real_tokenizer():
    """Load real Qwen2-VL tokenizer (module-scoped for efficiency)."""
    if not TRANSFORMERS_AVAILABLE:
        pytest.skip("transformers not available")
    
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            TEST_MODEL_NAME,
            trust_remote_code=True,
        )
        return tokenizer
    except Exception as e:
        pytest.skip(f"Failed to load tokenizer: {e}")


@pytest.fixture(scope="module")
def real_processor():
    """Load real Qwen2-VL processor (module-scoped for efficiency)."""
    if not TRANSFORMERS_AVAILABLE:
        pytest.skip("transformers not available")
    
    try:
        processor = AutoProcessor.from_pretrained(
            TEST_MODEL_NAME,
            trust_remote_code=True,
        )
        return processor
    except Exception as e:
        pytest.skip(f"Failed to load processor: {e}")


# ==================== Test-Scoped Fixtures ====================


@pytest.fixture
def sample_messages_text_only():
    """Sample messages with text only (no images)."""
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
            "role": "assistant",
            "content": [{"type": "text", "text": "Thought: I need to open Settings.\nAction: open_app(content='Settings')"}]
        },
    ]


@pytest.fixture
def sample_messages_with_image():
    """Sample messages including an image."""
    from skyrl_agent.agents.android.android_utils import numpy_to_base64
    
    image = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
    image_b64 = numpy_to_base64(image)
    
    return [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are a GUI agent."}]
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "Open the Settings app"}]
        },
        {
            "role": "user",
            "content": [{
                "type": "image",
                "image": f"data:image/png;base64,{image_b64}",
                "min_pixels": 3136,
                "max_pixels": 1003520,
            }]
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Thought: I see the home screen.\nAction: open_app(content='Settings')"}]
        },
    ]


@pytest.fixture
def sample_multi_image_messages():
    """Sample messages with multiple images (multi-step trajectory)."""
    from skyrl_agent.agents.android.android_utils import numpy_to_base64
    
    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are a GUI agent."}]
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "Open Settings and navigate to WiFi"}]
        },
    ]
    
    # Add 3 observation-action pairs
    for i in range(3):
        image = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
        image_b64 = numpy_to_base64(image)
        
        messages.append({
            "role": "user",
            "content": [{
                "type": "image",
                "image": f"data:image/png;base64,{image_b64}",
                "min_pixels": 3136,
                "max_pixels": 1003520,
            }]
        })
        messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": f"Thought: Step {i+1}.\nAction: click(start_box='(500,{300+i*100})')"}]
        })
    
    return messages


# ==================== Tokenizer Tests ====================


@skipif_no_transformers
class TestRealTokenizerIntegration:
    """Tests using real tokenizer with AndroidAgent."""
    
    def test_tokenizer_special_tokens_available(self, real_tokenizer):
        """Verify required special tokens exist in tokenizer."""
        # Tokens used by AndroidAgent
        required_tokens = ['<|im_start|>', '<|im_end|>']
        
        for token in required_tokens:
            token_id = real_tokenizer.convert_tokens_to_ids(token)
            assert token_id != real_tokenizer.unk_token_id, \
                f"Token '{token}' not found in tokenizer vocabulary"
    
    def test_chat_template_produces_valid_tokens(self, real_tokenizer, sample_messages_text_only):
        """Chat template produces valid token sequences."""
        # Convert to simple format for chat template
        simple_messages = []
        for msg in sample_messages_text_only:
            content = ""
            for item in msg["content"]:
                if item["type"] == "text":
                    content += item["text"]
            simple_messages.append({"role": msg["role"], "content": content})
        
        tokens = real_tokenizer.apply_chat_template(
            simple_messages,
            add_generation_prompt=True,
            tokenize=True,
        )
        
        assert isinstance(tokens, list)
        assert len(tokens) > 0
        assert all(isinstance(t, int) for t in tokens)
        # Use len(tokenizer) to include added/special tokens, not just vocab_size
        assert all(0 <= t < len(real_tokenizer) for t in tokens)
    
    def test_agent_prepare_input_ids(
        self, real_tokenizer, mock_processor, mock_infer_engine, mock_env_handle, mock_traj_config
    ):
        """Agent.prepare_input_ids() works with real tokenizer."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=mock_processor,
                env_handle=mock_env_handle,
            )
        
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "You are helpful."}]},
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
        ]
        
        # Convert to format tokenizer expects
        simple_messages = []
        for msg in messages:
            content = ""
            for item in msg["content"]:
                if item["type"] == "text":
                    content += item["text"]
            simple_messages.append({"role": msg["role"], "content": content})
        
        input_ids = agent.prepare_input_ids(simple_messages)
        
        assert isinstance(input_ids, list)
        assert len(input_ids) > 0


# ==================== Processor Tests ====================


@skipif_no_transformers
class TestRealProcessorIntegration:
    """Tests using real VLM processor with AndroidAgent."""
    
    def test_processor_handles_text_only(self, real_processor):
        """Processor correctly handles text-only input."""
        text = "<|im_start|>user\nHello world<|im_end|>\n"
        
        result = real_processor(
            None,  # No images
            [text],
            add_special_tokens=False,
            return_tensors="pt"
        )
        
        assert 'input_ids' in result
        assert 'attention_mask' in result
        assert result['input_ids'].dim() == 2
        assert result['input_ids'].shape[0] == 1  # Batch size 1
    
    def test_processor_handles_single_image(self, real_processor):
        """Processor correctly handles single image input."""
        from PIL import Image
        
        test_image = Image.new('RGB', (224, 224), color='blue')
        text = "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|><|im_end|>\n"
        
        result = real_processor(
            [test_image],
            [text],
            add_special_tokens=False,
            return_tensors="pt"
        )
        
        assert 'input_ids' in result
        assert 'pixel_values' in result
        assert 'image_grid_thw' in result
    
    def test_processor_handles_multiple_images(self, real_processor):
        """Processor correctly handles multiple images."""
        from PIL import Image
        
        images = [
            Image.new('RGB', (224, 224), color='red'),
            Image.new('RGB', (224, 224), color='green'),
        ]
        text = "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|><|vision_start|><|image_pad|><|vision_end|><|im_end|>\n"
        
        result = real_processor(
            images,
            [text],
            add_special_tokens=False,
            return_tensors="pt"
        )
        
        assert 'pixel_values' in result
        # Should have data for both images
        assert result['image_grid_thw'].shape[0] >= 2


# ==================== Process for Training Tests ====================


@skipif_no_ml_deps
class TestProcessForTrainingIntegration:
    """Integration tests for process_for_training with real ML components."""
    
    def test_process_for_training_text_only(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle, sample_messages_text_only
    ):
        """process_for_training works with text-only messages."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        result = agent.process_for_training(sample_messages_text_only)
        
        # Verify output structure
        assert 'input_ids' in result
        assert 'labels' in result
        assert 'attention_mask' in result
        
        # Verify tensor types
        assert result['input_ids'].dtype == torch.long
        assert result['labels'].dtype == torch.long
        
        # Verify shapes match
        assert result['input_ids'].shape == result['labels'].shape
        assert result['input_ids'].shape == result['attention_mask'].shape
    
    def test_process_for_training_with_image(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle, sample_messages_with_image
    ):
        """process_for_training works with image messages."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        result = agent.process_for_training(sample_messages_with_image)
        
        # Verify image data present
        assert 'pixel_values' in result
        assert 'image_grid_thw' in result
        
        # Verify text tensors
        assert 'input_ids' in result
        assert 'labels' in result
    
    def test_process_for_training_multi_image(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle, sample_multi_image_messages
    ):
        """process_for_training handles multiple images correctly."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        result = agent.process_for_training(sample_multi_image_messages)
        
        # Verify multiple images processed
        assert 'image_grid_thw' in result
        # Should have data for 3 images
        assert result['image_grid_thw'].shape[0] >= 3
    
    def test_labels_masking_correct(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle, sample_messages_text_only
    ):
        """Labels are correctly masked: system/user=-100, assistant=tokens."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        result = agent.process_for_training(sample_messages_text_only)
        
        labels = result['labels']
        
        # Count masked vs unmasked
        masked_count = (labels == -100).sum().item()
        unmasked_count = (labels != -100).sum().item()
        total = labels.numel()
        
        # Should have some masked (system/user) and some unmasked (assistant)
        assert masked_count > 0, "No tokens are masked - system/user should be masked"
        assert unmasked_count > 0, "All tokens masked - assistant should be unmasked"
        assert masked_count + unmasked_count == total


# ==================== Tensor Accumulation Tests ====================


@skipif_no_ml_deps
class TestTrainingAccumulatorIntegration:
    """Tests for TrainingAccumulator with real ML components."""
    
    def test_training_accumulator_grows_correctly(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle
    ):
        """TrainingAccumulator grows tensors correctly."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        # First batch - use add_initial
        messages1 = [
            {"role": "system", "content": [{"type": "text", "text": "System prompt"}]},
            {"role": "user", "content": [{"type": "text", "text": "User input"}]},
        ]
        agent.training.add_initial(messages1)
        len_after_first = agent.training._train_input_ids.shape[0]
        
        # Second batch - add assistant + user messages
        messages_all = messages1 + [
            {"role": "assistant", "content": [{"type": "text", "text": "Assistant response"}]},
            {"role": "user", "content": [{"type": "text", "text": "Follow up"}]},
        ]
        mock_response_token_ids = [1, 2, 3, 4, 5]  # Simulated tokens
        agent.training.add_step(messages_all, mock_response_token_ids)
        len_after_second = agent.training._train_input_ids.shape[0]
        
        # Verify growth
        assert len_after_second > len_after_first
        assert agent.training._train_input_ids.shape == agent.training._train_labels.shape
        assert agent.training._train_input_ids.shape == agent.training._train_attention_mask.shape
    
    def test_accumulate_tensors_with_images(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle
    ):
        """Tensor accumulation handles images correctly."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        from skyrl_agent.agents.android.android_utils import numpy_to_base64
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        # Initial image
        image1 = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
        image1_b64 = numpy_to_base64(image1)
        
        messages1 = [
            {"role": "system", "content": [{"type": "text", "text": "System"}]},
            {"role": "user", "content": [{
                "type": "image",
                "image": f"data:image/png;base64,{image1_b64}",
                "min_pixels": 3136,
                "max_pixels": 1003520,
            }]},
        ]
        tensors1 = agent.process_for_training(messages1)
        agent.accumulate_tensors(tensors1)
        
        assert agent.training._train_pixel_values is not None
        initial_pixel_count = agent.training._train_pixel_values.shape[0]
        
        # Second image
        image2 = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
        image2_b64 = numpy_to_base64(image2)
        
        messages2 = [
            {"role": "assistant", "content": [{"type": "text", "text": "Response"}]},
            {"role": "user", "content": [{
                "type": "image",
                "image": f"data:image/png;base64,{image2_b64}",
                "min_pixels": 3136,
                "max_pixels": 1003520,
            }]},
        ]
        tensors2 = agent.process_for_training(messages2)
        agent.accumulate_tensors(tensors2)
        
        # Verify pixel values accumulated
        assert agent.training._train_pixel_values.shape[0] > initial_pixel_count


# ==================== Edge Cases ====================


@skipif_no_ml_deps
class TestMLEdgeCases:
    """Edge case tests for ML integration."""
    
    def test_empty_messages_raises_error(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle
    ):
        """Empty message list raises an error (qwen_vl_utils doesn't handle empty input)."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        # Empty messages is an invalid input - qwen_vl_utils raises IndexError
        with pytest.raises(IndexError):
            agent.process_for_training([])
    
    def test_unicode_text_handled(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle
    ):
        """Unicode characters in text are handled correctly."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "你好 🌍 café"}]},
            {"role": "user", "content": [{"type": "text", "text": "打开设置 émojis 🔧"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "完成 ✅"}]},
        ]
        
        result = agent.process_for_training(messages)
        
        # Should process without error
        assert 'input_ids' in result
        assert result['input_ids'].numel() > 0
    
    def test_very_long_text_handled(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle
    ):
        """Very long text is handled (may be truncated)."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        # Create very long text
        long_text = "This is a test sentence. " * 500
        
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "System"}]},
            {"role": "user", "content": [{"type": "text", "text": long_text}]},
            {"role": "assistant", "content": [{"type": "text", "text": "OK"}]},
        ]
        
        result = agent.process_for_training(messages)
        
        # Should process without error
        assert 'input_ids' in result
        assert result['input_ids'].numel() > 0


# ==================== Task Format Tests ====================


@skipif_no_ml_deps
class TestTaskFormatIntegration:
    """Tests for Task formatting with ML components."""
    
    def test_task_instruction_format_valid(self, real_tokenizer, sample_observation):
        """Task.get_instruction() produces valid format for tokenizer."""
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        instance = {"task_id": 0, "task": "Test task"}
        
        # Get instruction (system prompt only)
        instruction = AndroidTask.get_instruction(instance)
        
        assert isinstance(instruction, list)
        assert len(instruction) > 0
        assert instruction[0]["role"] == "system"
    
    def test_task_observation_format_valid(self, real_tokenizer, sample_observation):
        """Task.format_observation() produces valid format for tokenizer."""
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        # Format observation
        obs_messages = AndroidTask.format_observation(sample_observation)
        
        assert isinstance(obs_messages, list)
        assert len(obs_messages) >= 1
        
        # Should have user role
        assert any(m["role"] == "user" for m in obs_messages)
    
    def test_full_initial_instruction_processable(
        self, real_tokenizer, real_processor, mock_traj_config,
        mock_infer_engine, mock_env_handle, sample_observation
    ):
        """Full initial instruction can be processed by agent."""
        from skyrl_agent.agents.android.android_agent import AndroidAgent
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        with patch('skyrl_agent.agents.android.android_agent.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=real_tokenizer,
                processor=real_processor,
                env_handle=mock_env_handle,
            )
        
        # Build full instruction like trajectory does
        instance = {"task_id": 0}
        template_messages = AndroidTask.get_instruction(instance)
        observation_messages = AndroidTask.format_observation(sample_observation)
        full_instruction = template_messages + observation_messages
        
        # Process with agent
        result = agent.process_for_training(full_instruction)
        
        # Should produce valid training data
        assert 'input_ids' in result
        assert 'pixel_values' in result  # Should have image data
        assert result['input_ids'].numel() > 0
