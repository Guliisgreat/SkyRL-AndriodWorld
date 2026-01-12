"""
Unit and integration tests for AndroidTrajectory.

Tests trajectory lifecycle: initialize, generate, evaluate.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import numpy as np
import pytest

from skyrl_agent.agents.android.android_trajectory import AndroidTrajectory


# ==================== Unit Tests ====================


class TestBuildResetPayload:
    """Test AndroidTrajectory._build_reset_payload() method."""
    
    @pytest.fixture
    def trajectory(self, mock_traj_config, sample_data, mock_infer_engine, 
                   mock_tokenizer, mock_task):
        """Create AndroidTrajectory for testing."""
        return AndroidTrajectory(
            cfg=mock_traj_config,
            data=sample_data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
    
    def test_build_reset_payload(self, trajectory):
        """Verify payload structure with task_id, seed, options."""
        payload = trajectory._build_reset_payload()

        assert "seed" in payload
        # When cfg.seed is None, seed defaults to trajectory_id (0 in mock_traj_config)
        assert payload["seed"] == trajectory.cfg.trajectory_id
        assert "options" in payload
        
        options = payload["options"]
        assert "task_id" in options
        assert "go_home_on_reset" in options
        assert options["go_home_on_reset"] is True
        assert "epoch" in options
        assert "mode" in options
        assert "traj" in options
    
    def test_build_reset_payload_with_instance_data(self, mock_traj_config, 
                                                     mock_infer_engine, mock_tokenizer, mock_task):
        """Verify payload uses instance data correctly."""
        data = {
            "instance_id": 5,
            "instance": {"task_id": 42, "task": "Test task"},
            "epoch": 3,
            "mode": "val",
        }
        
        trajectory = AndroidTrajectory(
            cfg=mock_traj_config,
            data=data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
        
        payload = trajectory._build_reset_payload()
        
        assert payload["options"]["task_id"] == 42
        assert payload["options"]["epoch"] == 3
        assert payload["options"]["mode"] == "val"
    
    def test_build_reset_payload_defaults(self, mock_traj_config, mock_infer_engine,
                                          mock_tokenizer, mock_task):
        """Verify defaults when instance data is minimal."""
        data = {
            "instance_id": 0,
            "instance": {},  # Minimal instance
        }
        
        trajectory = AndroidTrajectory(
            cfg=mock_traj_config,
            data=data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
        
        payload = trajectory._build_reset_payload()
        
        assert payload["options"]["task_id"] == 0  # Default
        assert payload["options"]["epoch"] == 0  # Default
        assert payload["options"]["mode"] == "train"  # Default
    
    def test_build_reset_payload_trajectory_id(self, mock_traj_config, sample_data,
                                                mock_infer_engine, mock_tokenizer, mock_task):
        """Verify trajectory_id is included in payload."""
        mock_traj_config.trajectory_id = 7
        
        trajectory = AndroidTrajectory(
            cfg=mock_traj_config,
            data=sample_data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
        
        payload = trajectory._build_reset_payload()
        
        assert payload["options"]["traj"] == 7


# ==================== Integration Tests ====================


class TestInitializeTrajectory:
    """Integration tests for AndroidTrajectory.initialize_trajectory()."""
    
    @pytest.fixture
    def trajectory_with_env(self, mock_traj_config, sample_data, mock_infer_engine,
                            mock_tokenizer, mock_task, mock_env_handle, sample_observation):
        """Create trajectory with env_handle set."""
        trajectory = AndroidTrajectory(
            cfg=mock_traj_config,
            data=sample_data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
        trajectory.env_handle = mock_env_handle
        trajectory.env_id = 0
        
        return trajectory
    
    @pytest.mark.asyncio
    async def test_initialize_trajectory(self, trajectory_with_env, sample_instruction):
        """Verify env reset and instruction generation."""
        await trajectory_with_env.initialize_trajectory()
        
        # Verify env.reset was called
        trajectory_with_env.env_handle.reset.assert_called_once()
        
        # Verify task.get_instruction was called (for template)
        trajectory_with_env.task.get_instruction.assert_called_once()
        
        # Verify task.format_observation was called (for observation content)
        trajectory_with_env.task.format_observation.assert_called_once()
        
        # Verify initial_instruction is set (combined from both methods)
        assert trajectory_with_env.initial_instruction is not None
        assert trajectory_with_env.initial_observation is not None
        
        # Verify instruction is the combination of template + observation
        assert len(trajectory_with_env.initial_instruction) == len(sample_instruction)
    
    @pytest.mark.asyncio
    async def test_initialize_trajectory_reset_payload(self, trajectory_with_env):
        """Verify reset is called with correct payload."""
        await trajectory_with_env.initialize_trajectory()
        
        call_args = trajectory_with_env.env_handle.reset.call_args[0][0]
        
        assert "seed" in call_args
        assert "options" in call_args


class TestGenerateTrajectory:
    """Integration tests for AndroidTrajectory.generate_trajectory()."""
    
    @pytest.fixture
    def initialized_trajectory(self, mock_traj_config, sample_data, mock_infer_engine,
                               mock_tokenizer, mock_task, mock_env_handle, 
                               sample_observation, sample_instruction, mock_processor):
        """Create trajectory that has been initialized."""
        trajectory = AndroidTrajectory(
            cfg=mock_traj_config,
            data=sample_data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
        trajectory.env_handle = mock_env_handle
        trajectory.env_id = 0
        trajectory.processor = mock_processor
        trajectory.initial_instruction = sample_instruction
        trajectory.initial_observation = sample_observation
        
        return trajectory
    
    @pytest.mark.asyncio
    async def test_generate_trajectory(self, initialized_trajectory, mock_traj_config):
        """Verify agent creation and result retrieval."""
        with patch('skyrl_agent.agents.android.android_trajectory.AndroidAgent') as MockAgent:
            # Create mock state that get_state returns
            mock_state = Mock()
            mock_state.instance_id = mock_traj_config.instance_id
            mock_state.trajectory_id = mock_traj_config.trajectory_id
            mock_state.messages = []
            mock_state.images = []
            mock_state.finish_reason = "FINISH"
            mock_state.reward = 1.0
            mock_state.format_reward = 0.0
            
            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock(return_value=("FINISH", 1.0))
            mock_agent.get_state = Mock(return_value=mock_state)
            mock_agent.get_train_dict = Mock(return_value={})
            MockAgent.return_value = mock_agent
            
            await initialized_trajectory.generate_trajectory()
            
            # Verify agent was created
            MockAgent.assert_called_once()
            
            # Verify agent.run was called with instruction
            mock_agent.run.assert_called_once_with(initialized_trajectory.initial_instruction)
            
            # Verify result was stored
            assert initialized_trajectory.result is not None
            assert initialized_trajectory.result["finish_reason"] == "FINISH"
            assert initialized_trajectory.result["results"] == 1.0
    
    @pytest.mark.asyncio
    async def test_generate_trajectory_retrieves_state(self, initialized_trajectory, mock_traj_config):
        """Verify all state is retrieved from agent via get_state()."""
        with patch('skyrl_agent.agents.android.android_trajectory.AndroidAgent') as MockAgent:
            # Create mock state that get_state returns
            mock_state = Mock()
            mock_state.instance_id = mock_traj_config.instance_id
            mock_state.trajectory_id = mock_traj_config.trajectory_id
            mock_state.messages = [{"role": "user", "content": "test"}]
            mock_state.images = [np.zeros((10, 10, 3))]
            mock_state.finish_reason = "FINISH"
            mock_state.reward = 0.5
            mock_state.format_reward = -0.1
            
            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock(return_value=("FINISH", 1.0))
            mock_agent.get_state = Mock(return_value=mock_state)
            mock_agent.get_train_dict = Mock(return_value={"input_ids": [1, 2, 3]})
            MockAgent.return_value = mock_agent
            
            await initialized_trajectory.generate_trajectory()
            
            # Verify get_state was called
            mock_agent.get_state.assert_called_once()
            mock_agent.get_train_dict.assert_called_once()
            
            # Verify result structure
            result = initialized_trajectory.result
            assert result["messages"] == [{"role": "user", "content": "test"}]
            assert len(result["history_images"]) == 1
            assert result["train_dict"] == {"input_ids": [1, 2, 3]}
            assert result["reward"] == 0.5
            assert result["format_reward"] == -0.1
    
    @pytest.mark.asyncio
    async def test_generate_trajectory_sets_instance_info(self, initialized_trajectory, mock_traj_config):
        """Verify instance_id and trajectory_id in result."""
        with patch('skyrl_agent.agents.android.android_trajectory.AndroidAgent') as MockAgent:
            # Create mock state that get_state returns
            mock_state = Mock()
            mock_state.instance_id = mock_traj_config.instance_id
            mock_state.trajectory_id = mock_traj_config.trajectory_id
            mock_state.messages = []
            mock_state.images = []
            mock_state.finish_reason = "FINISH"
            mock_state.reward = 0.0
            mock_state.format_reward = 0.0
            
            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock(return_value=("FINISH", 1.0))
            mock_agent.get_state = Mock(return_value=mock_state)
            mock_agent.get_train_dict = Mock(return_value={})
            MockAgent.return_value = mock_agent
            
            await initialized_trajectory.generate_trajectory()
            
            assert initialized_trajectory.result["instance_id"] == mock_traj_config.instance_id
            assert initialized_trajectory.result["trajectory_id"] == mock_traj_config.trajectory_id


class TestEvaluateTrajectory:
    """Integration tests for AndroidTrajectory.evaluate_trajectory()."""
    
    @pytest.fixture
    def generated_trajectory(self, mock_traj_config, sample_data, mock_infer_engine,
                             mock_tokenizer, mock_task, mock_env_handle, mock_processor):
        """Create trajectory that has completed generation."""
        trajectory = AndroidTrajectory(
            cfg=mock_traj_config,
            data=sample_data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
        trajectory.env_handle = mock_env_handle
        trajectory.env_id = 0
        trajectory.processor = mock_processor
        
        # Set result as if generate was called
        trajectory.result = {
            "instance_id": 0,
            "trajectory_id": 0,
            "messages": [{"role": "user", "content": "test"}],
            "history_images": [np.zeros((10, 10, 3), dtype=np.uint8)],
            "train_dict": {},
            "results": 0.5,
            "finish_reason": "FINISH",
            "reward": 0.5,
            "format_reward": 0.0,
            "state": {},
        }
        
        return trajectory
    
    @pytest.mark.asyncio
    async def test_evaluate_trajectory(self, generated_trajectory):
        """Verify task evaluation called with agent state."""
        await generated_trajectory.evaluate_trajectory()
        
        # Verify task.evaluate_result was called
        generated_trajectory.task.evaluate_result.assert_called_once()
        
        # Verify result was updated
        assert generated_trajectory.result["reward"] == 1.0  # mock_task returns 1.0
    
    @pytest.mark.asyncio
    async def test_evaluate_trajectory_passes_history(self, generated_trajectory):
        """Verify history is passed to evaluation."""
        await generated_trajectory.evaluate_trajectory()
        
        call_kwargs = generated_trajectory.task.evaluate_result.call_args[1]
        
        assert "result" in call_kwargs
        assert "instance" in call_kwargs
        assert "history_images" in call_kwargs
        assert "history_messages" in call_kwargs
    
    @pytest.mark.asyncio
    async def test_evaluate_trajectory_handles_error(self, generated_trajectory):
        """Verify graceful handling when evaluation fails."""
        generated_trajectory.task.evaluate_result = AsyncMock(
            side_effect=Exception("Evaluation error")
        )
        
        await generated_trajectory.evaluate_trajectory()
        
        # Should set reward to 0.0 on error
        assert generated_trajectory.result["reward"] == 0.0
        assert "eval_error" in generated_trajectory.result


class TestFullTrajectoryLifecycle:
    """Test complete trajectory lifecycle: init -> generate -> evaluate."""
    
    @pytest.mark.asyncio
    async def test_full_trajectory_lifecycle(self, mock_traj_config, sample_data,
                                              mock_infer_engine, mock_tokenizer, 
                                              mock_task, mock_env_handle, 
                                              mock_processor, sample_observation):
        """End-to-end init -> generate -> evaluate."""
        trajectory = AndroidTrajectory(
            cfg=mock_traj_config,
            data=sample_data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
        trajectory.env_handle = mock_env_handle
        trajectory.env_id = 0
        trajectory.processor = mock_processor
        
        # 1. Initialize
        await trajectory.initialize_trajectory()
        
        assert trajectory.initial_instruction is not None
        assert trajectory.initial_observation is not None
        
        # 2. Generate (with mocked agent)
        with patch('skyrl_agent.agents.android.android_trajectory.AndroidAgent') as MockAgent:
            # Create mock state that get_state returns
            mock_state = Mock()
            mock_state.instance_id = mock_traj_config.instance_id
            mock_state.trajectory_id = mock_traj_config.trajectory_id
            mock_state.messages = [{"role": "assistant", "content": "done"}]
            mock_state.images = []
            mock_state.finish_reason = "FINISH"
            mock_state.reward = 1.0
            mock_state.format_reward = 0.0
            
            mock_agent = AsyncMock()
            mock_agent.run = AsyncMock(return_value=("FINISH", 1.0))
            mock_agent.get_state = Mock(return_value=mock_state)
            mock_agent.get_train_dict = Mock(return_value={})
            MockAgent.return_value = mock_agent
            
            await trajectory.generate_trajectory()
        
        assert trajectory.result is not None
        assert trajectory.result["finish_reason"] == "FINISH"
        
        # 3. Evaluate
        await trajectory.evaluate_trajectory()
        
        assert trajectory.result["reward"] == 1.0


class TestTrajectoryAttributes:
    """Test AndroidTrajectory attribute initialization and access."""
    
    def test_initial_attributes(self, mock_traj_config, sample_data, mock_infer_engine,
                                 mock_tokenizer, mock_task):
        """Verify initial attribute values."""
        trajectory = AndroidTrajectory(
            cfg=mock_traj_config,
            data=sample_data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
        
        assert trajectory.env_id is None
        assert trajectory.env_handle is None
        assert trajectory.processor is None
        assert trajectory.agent is None
        assert trajectory.initial_instruction is None
    
    def test_env_assignment(self, mock_traj_config, sample_data, mock_infer_engine,
                            mock_tokenizer, mock_task, mock_env_handle):
        """Verify env_handle can be assigned."""
        trajectory = AndroidTrajectory(
            cfg=mock_traj_config,
            data=sample_data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=mock_task,
        )
        
        trajectory.env_id = 3
        trajectory.env_handle = mock_env_handle
        
        assert trajectory.env_id == 3
        assert trajectory.env_handle is mock_env_handle

