"""
Unit tests for AndroidWorldTask.
"""

import pytest
import base64
import numpy as np
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from skyrl_agent.tasks.android.android_task import AndroidTask


class TestInitializeRuntime:
    """Test AndroidTask.initialize_runtime()."""
    
    @pytest.mark.asyncio
    async def test_initialize_runtime(self, tmp_path):
        """Test initialize_runtime creates pool and clients."""
        from unittest.mock import patch, Mock, AsyncMock
        from skyrl_agent.runtime.android.container_manager import ContainerInstance
        
        env_config = {
            "pool_size": 3,
            "docker_image": "androidworld:test",
            "base_env_id": 0,
            "temp_path": str(tmp_path),
            "lock_file": str(tmp_path / "test.lck"),
        }
        
        # Mock ContainerManager and RuntimeClient
        mock_containers = []
        for i in range(3):
            mock_container_obj = Mock()
            container_instance = ContainerInstance(
                container_id=f"test-{i}",
                container=mock_container_obj,
                server_port=5000 + 2 * i,
                emulator_port=5554 + 2 * i,
                grpc_port=8554 + 2 * i,
                env_id=i,
                state="ready"
            )
            mock_containers.append(container_instance)
        
        with patch('skyrl_agent.runtime.androidworld.container_manager.docker') as mock_docker, \
             patch('psutil.net_connections', return_value=[]), \
             patch('requests.get') as mock_get, \
             patch('skyrl_agent.runtime.androidworld.runtime_client.RuntimeClient') as mock_client_cls:
            
            # Setup docker mock
            mock_docker.from_env = Mock(return_value=Mock())
            mock_get.return_value.status_code = 200
            
            # Mock ContainerManager.create_pool
            with patch.object(AndroidTask, 'initialize_runtime', wraps=AndroidTask.initialize_runtime):
                # Actually create containers using the real ContainerManager but with mocked docker
                mock_client_instances = [Mock() for _ in range(3)]
                mock_client_cls.side_effect = mock_client_instances
                
                clients = await AndroidTask.initialize_runtime(env_config)
                
                assert len(clients) == 3
                assert all(c is not None for c in clients)
    
    @pytest.mark.asyncio
    async def test_initialize_runtime_default_config(self, tmp_path):
        """Test initialize_runtime with default config."""
        from unittest.mock import patch, Mock
        from skyrl_agent.runtime.android.container_manager import ContainerInstance
        
        env_config = {
            "docker_image": "androidworld:test",
            "temp_path": str(tmp_path),
            "lock_file": str(tmp_path / "test.lck"),
        }
        
        with patch('skyrl_agent.runtime.android.container_manager.docker') as mock_docker, \
             patch('psutil.net_connections', return_value=[]), \
             patch('requests.get') as mock_get:
            
            mock_docker.from_env = Mock(return_value=Mock())
            mock_get.return_value.status_code = 200
            
            # This will use default pool_size=8
            clients = await AndroidTask.initialize_runtime(env_config)
            
            assert len(clients) == 8  # Default pool_size
    
    @pytest.mark.asyncio
    async def test_initialize_runtime_custom_config(self, tmp_path):
        """Test initialize_runtime with custom config."""
        from unittest.mock import patch, Mock
        
        env_config = {
            "pool_size": 5,
            "docker_image": "androidworld:custom",
            "snapshot": "custom_snapshot",
            "sample_mode": "sequential",
            "train_task_family": "custom_train",
            "val_task_family": "custom_val",
            "temp_path": str(tmp_path),
            "base_env_id": 10,
            "lock_file": str(tmp_path / "test.lck"),
        }
        
        with patch('skyrl_agent.runtime.android.container_manager.docker') as mock_docker, \
             patch('psutil.net_connections', return_value=[]), \
             patch('requests.get') as mock_get:
            
            mock_docker.from_env = Mock(return_value=Mock())
            mock_get.return_value.status_code = 200
            
            clients = await AndroidTask.initialize_runtime(env_config)
            
            assert len(clients) == 5


class TestGetInstruction:
    """Test AndroidTask.get_instruction()."""
    
    def test_get_instruction(self):
        """Test get_instruction returns system prompt only."""
        instance = {"task_id": 0}
        
        messages = AndroidTask.get_instruction(instance)
        
        assert isinstance(messages, list)
        assert len(messages) == 1  # System message only
        
        # Check system message
        assert messages[0]["role"] == "system"
        assert "content" in messages[0]
        assert messages[0]["content"][0]["text"] == "You are a helpful assistant."
    
    def test_get_instruction_ignores_instance_content(self):
        """Test get_instruction returns same template regardless of instance."""
        instance1 = {"task_id": 0}
        instance2 = {"task_id": 99, "extra_field": "value"}
        
        messages1 = AndroidTask.get_instruction(instance1)
        messages2 = AndroidTask.get_instruction(instance2)
        
        # Same template for any instance
        assert messages1 == messages2


class TestFormatObservation:
    """Test AndroidTask.format_observation()."""
    
    def test_format_observation(self, sample_observation):
        """Test format_observation formats messages correctly."""
        messages = AndroidTask.format_observation(sample_observation)
        
        assert isinstance(messages, list)
        assert len(messages) == 2  # User text + image
        
        # Check user message with instruction
        assert messages[0]["role"] == "user"
        assert "Open calculator app" in messages[0]["content"][0]["text"]
        
        # Check image message
        assert messages[1]["role"] == "user"
        assert "image" in messages[1]["content"][0]
    
    def test_format_observation_with_image(self, sample_observation):
        """Test format_observation includes image."""
        messages = AndroidTask.format_observation(sample_observation)
        
        # Find image message
        image_message = None
        for msg in messages:
            if msg["role"] == "user" and "content" in msg:
                for content in msg["content"]:
                    if isinstance(content, dict) and "image" in content:
                        image_message = content
                        break
        
        assert image_message is not None
        assert image_message["type"] == "image"
        assert image_message["image"].startswith("data:image/png;base64,")
        assert "min_pixels" in image_message
        assert "max_pixels" in image_message
    
    def test_format_observation_no_image(self):
        """Test format_observation without image."""
        observation = {
            "task": "Test task",
            # No image
        }
        
        messages = AndroidTask.format_observation(observation)
        
        # Should have only text message, no image
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Test task" in messages[0]["content"][0]["text"]
        
        # Should not have image message
        has_image = False
        for msg in messages:
            if "content" in msg:
                for content in msg["content"]:
                    if isinstance(content, dict) and content.get("type") == "image":
                        has_image = True
                        break
        
        assert not has_image
    
    def test_format_observation_empty_task(self):
        """Test format_observation with empty task."""
        observation = {
            "task": "",  # Empty task
            "image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        }
        
        messages = AndroidTask.format_observation(observation)
        
        # Should still create messages (text + image)
        assert len(messages) == 2


class TestCompleteRuntime:
    """Test AndroidTask.complete_runtime()."""
    
    def test_complete_runtime(self):
        """Test complete_runtime returns empty dict."""
        mock_runtime_client = Mock()
        
        result = AndroidTask.complete_runtime(mock_runtime_client)
        
        assert result == {}


class TestEvaluateResult:
    """Test AndroidTask.evaluate_result()."""
    
    @pytest.mark.asyncio
    async def test_evaluate_result_ground_truth(self):
        """Test evaluate_result with ground_truth provider."""
        instance = {"task_id": 0}
        
        # Test with float reward
        reward = await AndroidTask.evaluate_result(1.5, instance)
        assert reward == 1.5
        
        # Test with int reward
        reward = await AndroidTask.evaluate_result(1, instance)
        assert reward == 1.0
        
        # Test with None
        reward = await AndroidTask.evaluate_result(None, instance)
        assert reward == 0.0
    
    @pytest.mark.asyncio
    async def test_evaluate_result_gemini(self):
        """Test evaluate_result with gemini provider."""
        instance = {"task": "Test task"}
        history_images = [np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)]
        history_messages = [{"role": "user", "content": "test"}]
        
        with patch('verl.trainer.gemini_evaluator.GeminiEvaluator') as mock_eval_cls:
            mock_evaluator = Mock()
            mock_evaluator.evaluate = Mock(return_value=1.0)
            mock_eval_cls.return_value = mock_evaluator
            
            reward = await AndroidTask.evaluate_result(
                None,
                instance,
                history_images=history_images,
                history_messages=history_messages,
                reward_provider="gemini"
            )
            
            assert reward == 1.0
            mock_evaluator.evaluate.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_evaluate_result_gemini_exception(self):
        """Test evaluate_result with gemini provider handles exceptions."""
        instance = {"task": "Test task"}
        
        with patch('verl.trainer.gemini_evaluator.GeminiEvaluator') as mock_eval_cls:
            mock_eval_cls.side_effect = ImportError("Gemini not available")
            
            reward = await AndroidTask.evaluate_result(
                None,
                instance,
                reward_provider="gemini"
            )
            
            assert reward == 0.0
    
    @pytest.mark.asyncio
    async def test_evaluate_result_unknown_provider(self):
        """Test evaluate_result with unknown provider."""
        instance = {"task_id": 0}
        
        reward = await AndroidTask.evaluate_result(
            0,
            instance,
            reward_provider="unknown"
        )
        
        assert reward == 0.0


class TestNumpyToBase64:
    """Test AndroidTask._numpy_to_base64()."""
    
    def test_numpy_to_base64(self):
        """Test numpy array to base64 conversion."""
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        
        base64_str = AndroidTask._numpy_to_base64(image)
        
        assert isinstance(base64_str, str)
        
        # Verify can decode back
        decoded = base64.b64decode(base64_str)
        assert len(decoded) > 0
        
        # Verify PNG format (PNG files start with specific bytes)
        import struct
        # PNG signature: 89 50 4E 47 0D 0A 1A 0A
        png_signature = b'\x89PNG\r\n\x1a\n'
        assert decoded[:8] == png_signature

