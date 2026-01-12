"""
Unit tests for RuntimeClient.
"""

import pytest
import base64
import numpy as np
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import aiohttp

from skyrl_agent.runtime.android.runtime_client import RuntimeClient
from skyrl_agent.runtime.android.container_manager import ContainerInstance


class TestRuntimeClientInit:
    """Test RuntimeClient initialization."""
    
    def test_runtime_client_init(self, mock_container_instance):
        """Test RuntimeClient initialization."""
        client = RuntimeClient(mock_container_instance)
        
        assert client.container == mock_container_instance
        assert client.base_url == f"http://localhost:{mock_container_instance.server_port}"
        assert client.session is None
    
    def test_runtime_client_base_url(self):
        """Test base_url uses container server_port."""
        container = ContainerInstance(
            container_id="test-id",
            container=Mock(),
            server_port=5575,
            emulator_port=5574,
            grpc_port=8574,
            env_id=0,
            state="ready"
        )
        
        client = RuntimeClient(container)
        assert client.base_url == "http://localhost:5575"


class TestRuntimeClientReset:
    """Test RuntimeClient.reset() method."""
    
    @pytest.mark.asyncio
    async def test_reset_success(self, mock_container_instance, sample_observation_base64):
        """Test successful reset call."""
        client = RuntimeClient(mock_container_instance)
        
        # Mock aiohttp session context manager
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "observation": sample_observation_base64,
            "info": {}
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = Mock(return_value=mock_response)
        
        client.session = mock_session
        
        observation, info = await client.reset({
            "seed": 42,
            "options": {"task_id": 0}
        })
        
        assert isinstance(observation, dict)
        assert "image" in observation
        assert isinstance(observation["image"], np.ndarray)
        assert isinstance(info, dict)
        
        # Verify HTTP request was made
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert "/reset" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_reset_with_payload(self, mock_container_instance):
        """Test reset with custom payload."""
        client = RuntimeClient(mock_container_instance)
        
        payload = {
            "seed": 42,
            "options": {
                "task_id": 0,
                "go_home_on_reset": True
            }
        }
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"observation": {}, "info": {}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = Mock(return_value=mock_response)
        
        client.session = mock_session
        
        await client.reset(payload)
        
        # Verify payload was sent
        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs["json"] == payload
    
    @pytest.mark.asyncio
    async def test_reset_no_payload(self, mock_container_instance):
        """Test reset with None payload."""
        client = RuntimeClient(mock_container_instance)
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"observation": {}, "info": {}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = Mock(return_value=mock_response)
        
        client.session = mock_session
        
        await client.reset(None)
        
        # Verify empty dict was sent
        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs["json"] == {}
    
    @pytest.mark.asyncio
    async def test_reset_http_error(self, mock_container_instance):
        """Test reset handles HTTP errors."""
        client = RuntimeClient(mock_container_instance)
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = Mock(return_value=mock_response)
        
        client.session = mock_session
        
        with pytest.raises(Exception, match="failed with status code 500"):
            await client.reset({})
    
    @pytest.mark.asyncio
    async def test_reset_connection_error(self, mock_container_instance):
        """Test reset handles connection errors."""
        client = RuntimeClient(mock_container_instance)
        
        mock_session = AsyncMock()
        mock_session.post = Mock(side_effect=aiohttp.ClientError("Connection failed"))
        
        client.session = mock_session
        
        with pytest.raises(Exception, match="Connection failed"):
            await client.reset({})


class TestRuntimeClientStep:
    """Test RuntimeClient.step() method."""
    
    @pytest.mark.asyncio
    async def test_step_success(self, mock_container_instance, sample_observation_base64):
        """Test successful step call."""
        client = RuntimeClient(mock_container_instance)
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "observation": sample_observation_base64,
            "reward": 1.0,
            "terminated": False,
            "truncated": False,
            "info": {}
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = Mock(return_value=mock_response)
        
        client.session = mock_session
        
        obs, reward, terminated, truncated, info = await client.step({
            "action": {"action_type": "click"},
            "thought": "test"
        })
        
        assert isinstance(obs, dict)
        assert isinstance(obs["image"], np.ndarray)
        assert reward == 1.0
        assert terminated is False
        assert truncated is False
        assert isinstance(info, dict)
    
    @pytest.mark.asyncio
    async def test_step_with_action(self, mock_container_instance):
        """Test step with action payload."""
        client = RuntimeClient(mock_container_instance)
        
        payload = {
            "action": {"action_type": "click", "touch_point": [0.5, 0.5]},
            "thought": "Clicking center"
        }
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "observation": {},
            "reward": 0.0,
            "terminated": False,
            "truncated": False,
            "info": {}
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = Mock(return_value=mock_response)
        
        client.session = mock_session
        
        await client.step(payload)
        
        # Verify payload was sent
        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs["json"] == payload
    
    @pytest.mark.asyncio
    async def test_step_http_error(self, mock_container_instance):
        """Test step handles HTTP errors."""
        client = RuntimeClient(mock_container_instance)
        
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = Mock(return_value=mock_response)
        
        client.session = mock_session
        
        with pytest.raises(Exception, match="failed with status code 500"):
            await client.step({"action": {}})


class TestObservationDeserialization:
    """Test observation deserialization."""
    
    def test_deserialize_observation(self):
        """Test observation deserialization."""
        # Create base64-encoded image
        image = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
        image_bytes = base64.b64encode(image.tobytes()).decode("utf-8")
        
        obs_dict = {
            "image": image_bytes,
            "image_shape": [1080, 1920, 3],
            "image_dtype": "uint8",
            "task": "test"
        }
        
        container = ContainerInstance(
            container_id="test",
            container=Mock(),
            server_port=5555,
            emulator_port=5574,
            grpc_port=8554,
            env_id=0,
            state="ready"
        )
        client = RuntimeClient(container)
        
        deserialized = client._deserialize_observation(obs_dict)
        
        assert isinstance(deserialized["image"], np.ndarray)
        assert deserialized["image"].shape == (1080, 1920, 3)
        assert deserialized["image"].dtype == np.uint8
        assert deserialized["task"] == "test"
    
    def test_deserialize_observation_no_image(self):
        """Test deserialization when no image present."""
        obs_dict = {
            "task": "test"
        }
        
        container = ContainerInstance(
            container_id="test",
            container=Mock(),
            server_port=5555,
            emulator_port=5574,
            grpc_port=8554,
            env_id=0,
            state="ready"
        )
        client = RuntimeClient(container)
        
        deserialized = client._deserialize_observation(obs_dict)
        assert deserialized == obs_dict
    
    def test_deserialize_observation_already_numpy(self):
        """Test deserialization when image already numpy."""
        image = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
        obs_dict = {
            "image": image,  # Already numpy array
            "task": "test"
        }
        
        container = ContainerInstance(
            container_id="test",
            container=Mock(),
            server_port=5555,
            emulator_port=5574,
            grpc_port=8554,
            env_id=0,
            state="ready"
        )
        client = RuntimeClient(container)
        
        deserialized = client._deserialize_observation(obs_dict)
        # Should not change if already numpy
        assert isinstance(deserialized["image"], np.ndarray)


class TestSessionManagement:
    """Test session management."""
    
    @pytest.mark.asyncio
    async def test_ensure_session(self, mock_container_instance):
        """Test session creation on first use."""
        client = RuntimeClient(mock_container_instance)
        
        assert client.session is None
        
        # Mock aiohttp.ClientSession and response
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"observation": {}, "info": {}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_session.post = Mock(return_value=mock_response)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            await client.reset({})
            
            # Verify session was created
            assert client.session is not None
    
    @pytest.mark.asyncio
    async def test_close(self, mock_container_instance):
        """Test closing session."""
        client = RuntimeClient(mock_container_instance)
        
        # Create mock session
        mock_session = AsyncMock()
        mock_session.close = AsyncMock()
        client.session = mock_session
        
        await client.close()
        
        # Verify session closed
        mock_session.close.assert_called_once()
        assert client.session is None
        
        # Verify can be called multiple times
        await client.close()  # Should not raise error

