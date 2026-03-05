"""
Integration tests for Trajectory + Agent interaction.

Tests AndroidTrajectory and AndroidAgent working together:
- Single trajectory lifecycle (init → generate → eval)
- Multi-step trajectories
- Error handling within trajectory
- Training data collection

Note: These tests mock Tool and Environment to focus on Trajectory/Agent logic.
For full E2E tests with real Tool execution, see test_integration_e2e.py
"""

import asyncio
import os
import numpy as np
from typing import Dict, Any, List
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from dataclasses import dataclass, field

import pytest


# ==================== Skip Markers ====================

# Check for optional dependencies
DOCKER_AVAILABLE = os.path.exists("/var/run/docker.sock") or os.environ.get("DOCKER_HOST")
RUN_E2E_TESTS = os.environ.get("RUN_E2E_TESTS", "").lower() == "true"

skipif_no_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker not available"
)

skipif_e2e_disabled = pytest.mark.skipif(
    not RUN_E2E_TESTS,
    reason="E2E tests disabled (set RUN_E2E_TESTS=true)"
)

# Mark all tests in this module
pytestmark = [pytest.mark.integration, pytest.mark.e2e]


# ==================== Mock Configurations ====================


@dataclass
class MockRunnerConfig:
    """Mock configuration for AndroidAgentRunner."""
    
    @dataclass
    class GeneratorConfig:
        max_prompt_length: int = 4096
        max_iterations: int = 5
        vision_is_active: bool = True
        num_trajectories: int = 2
        infer_backend: str = "mock"
        sampling_params: Dict = field(default_factory=lambda: {"temperature": 0.7, "max_tokens": 512})
        
        @dataclass
        class ValConfig:
            num_trajectories: int = 1
            sampling_params: Dict = field(default_factory=lambda: {"temperature": 0.0, "max_tokens": 512})
        
        val_config: ValConfig = field(default_factory=ValConfig)
    
    @dataclass
    class EnvConfig:
        pool_size: int = 2
        docker_image: str = "androidworld:test"
        snapshot: str = "default"
        sample_mode: str = "sequential"
        save_images: bool = False
        temp_path: str = "/tmp/android_tests"
    
    @dataclass
    class ActorRolloutRefConfig:
        @dataclass
        class ModelConfig:
            path: str = "Qwen/Qwen2-VL-2B-Instruct"
            trust_remote_code: bool = True
        model: ModelConfig = field(default_factory=ModelConfig)
    
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)
    env: EnvConfig = field(default_factory=EnvConfig)
    actor_rollout_ref: ActorRolloutRefConfig = field(default_factory=ActorRolloutRefConfig)
    agent_cls: str = "skyrl_agent.agents.android.AndroidAgent"


# ==================== Fixtures ====================


@pytest.fixture
def mock_runner_config():
    """Configuration for AndroidAgentRunner."""
    return MockRunnerConfig()


@pytest.fixture
def mock_env_pool():
    """Mock environment pool (simulates AndroidWorldHostEnv instances)."""
    pool = []
    for i in range(2):
        env = AsyncMock()
        env.env_id = i
        
        # Reset returns observation
        env.reset = AsyncMock(return_value=(
            {
                "task": f"Test task {i}: Open Settings app",
                "image": np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8),
            },
            {"info_key": "value"}
        ))
        
        # Step returns (obs, reward, terminated, truncated, info)
        env.step = Mock(return_value=(
            {"image": np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8)},
            0.0,
            False,
            False,
            {}
        ))
        
        pool.append(env)
    
    return pool


@pytest.fixture
def mock_infer_engine_with_responses():
    """Mock inference engine that returns a sequence of responses."""
    engine = AsyncMock()
    
    # Responses that lead to task completion
    responses = [
        ("Thought: I need to open the Settings app.\nAction: open_app(content='Settings')", "stop"),
        ("Thought: Settings is open. Task complete.\nAction: finished(content='done')", "stop"),
    ]
    
    engine.async_generate_ids = AsyncMock(side_effect=responses * 10)  # Repeat for multiple trajectories
    return engine


@pytest.fixture
def sample_input_batch():
    """Sample input batch for runner."""
    return [
        {"instance_id": 0, "instance": {"task_id": 0, "task": "Open Settings"}, "epoch": 0, "mode": "train"},
        {"instance_id": 1, "instance": {"task_id": 1, "task": "Open WiFi"}, "epoch": 0, "mode": "train"},
    ]


# ==================== E2E Tests with Mocks ====================


class TestE2EFullPipelineMock:
    """
    E2E tests using mocks for all external dependencies.
    
    Tests the complete flow without requiring Docker or real inference.
    """
    
    @pytest.mark.asyncio
    async def test_single_trajectory_completes(
        self, mock_traj_config, mock_infer_engine, mock_tokenizer,
        mock_processor, mock_env_handle_terminated, sample_observation
    ):
        """Single trajectory completes successfully from start to finish."""
        from skyrl_agent.agents.android.base import AndroidAgent
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        # Setup: Response that finishes immediately
        mock_infer_engine.async_generate_ids = AsyncMock(
            return_value=("Thought: Done.\nAction: finished(content='complete')", "stop")
        )
        
        # Create trajectory
        data = {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"}
        traj = AndroidTrajectory(
            cfg=mock_traj_config,
            data=data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=AndroidTask,
        )
        traj.env_handle = mock_env_handle_terminated
        traj.processor = mock_processor
        
        # Mock the tool
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry, \
             patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            mock_call.return_value = {
                "image": None,
                "reward": 1.0,
                "terminated": True,
                "truncated": False,
                "info": {},
            }
            
            # Execute: Full trajectory lifecycle
            await traj.initialize_trajectory()
            await traj.generate_trajectory()
            await traj.evaluate_trajectory()
        
        # Verify: Trajectory completed with expected results
        assert traj.result is not None
        assert traj.result["finish_reason"] == "FINISH"
        assert traj.result["reward"] == 1.0
        assert "messages" in traj.result
        assert "train_dict" in traj.result
    
    @pytest.mark.asyncio
    async def test_trajectory_max_iterations(
        self, mock_traj_config, mock_tokenizer, mock_processor, mock_env_handle
    ):
        """Trajectory stops at max iterations when task not completed."""
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        # Setup: Low max iterations, never-ending response
        mock_traj_config.max_iterations = 2
        
        mock_infer_engine = AsyncMock()
        mock_infer_engine.async_generate_ids = AsyncMock(
            return_value=("Thought: Keep trying.\nAction: click(start_box='(500,500)')", "stop")
        )
        
        data = {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"}
        traj = AndroidTrajectory(
            cfg=mock_traj_config,
            data=data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=AndroidTask,
        )
        traj.env_handle = mock_env_handle
        traj.processor = mock_processor
        
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry, \
             patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            mock_call.return_value = {
                "image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8),
                "reward": 0.0,
                "terminated": False,
                "truncated": False,
                "info": {},
            }
            
            await traj.initialize_trajectory()
            await traj.generate_trajectory()
        
        # Verify: Stopped at max iterations
        assert traj.result["finish_reason"] == "max_iterations_reached"
        assert traj.agent.state.step_count == 2
    
    @pytest.mark.asyncio
    async def test_multi_step_trajectory(
        self, mock_traj_config, mock_tokenizer, mock_processor, sample_observation
    ):
        """Multi-step trajectory executes correct sequence of actions."""
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        # Setup: Sequence of responses
        responses = [
            ("Thought: Open Settings.\nAction: open_app(content='Settings')", "stop"),
            ("Thought: Click WiFi.\nAction: click(start_box='(500,300)')", "stop"),
            ("Thought: Done.\nAction: finished(content='complete')", "stop"),
        ]
        
        mock_infer_engine = AsyncMock()
        mock_infer_engine.async_generate_ids = AsyncMock(side_effect=responses)
        
        mock_env_handle = AsyncMock()
        mock_env_handle.reset = AsyncMock(return_value=(sample_observation, {}))
        
        # Step results: continue, continue, terminate
        step_results = [
            ({"image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)},
             0.0, False, False, {}),
            ({"image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)},
             0.0, False, False, {}),
            ({"image": None}, 1.0, True, False, {}),
        ]
        
        data = {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"}
        traj = AndroidTrajectory(
            cfg=mock_traj_config,
            data=data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=AndroidTask,
        )
        traj.env_handle = mock_env_handle
        traj.processor = mock_processor
        
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry, \
             patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            mock_call.side_effect = [
                {"image": r[0]["image"], "reward": r[1], "terminated": r[2], "truncated": r[3], "info": r[4]}
                for r in step_results
            ]
            
            await traj.initialize_trajectory()
            await traj.generate_trajectory()
        
        # Verify: 3 steps executed
        assert traj.result["finish_reason"] == "FINISH"
        assert traj.agent.state.step_count == 3
        assert traj.result["reward"] == 1.0


class TestE2EMultipleTrajectories:
    """Test multiple trajectories running in parallel."""
    
    @pytest.mark.asyncio
    async def test_parallel_trajectories_complete(
        self, mock_traj_config, mock_tokenizer, mock_processor, sample_observation
    ):
        """Multiple trajectories run and complete independently."""
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        num_trajectories = 3
        trajectories = []
        
        for i in range(num_trajectories):
            mock_infer_engine = AsyncMock()
            mock_infer_engine.async_generate_ids = AsyncMock(
                return_value=(f"Thought: Task {i} done.\nAction: finished(content='done')", "stop")
            )
            
            mock_env_handle = AsyncMock()
            mock_env_handle.reset = AsyncMock(return_value=(sample_observation, {}))
            
            data = {"instance_id": i, "instance": {"task_id": i}, "epoch": 0, "mode": "train"}
            traj = AndroidTrajectory(
                cfg=mock_traj_config,
                data=data,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                task=AndroidTask,
            )
            traj.env_handle = mock_env_handle
            traj.processor = mock_processor
            trajectories.append(traj)
        
        # Run all trajectories in parallel
        async def run_trajectory(traj):
            with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry, \
                 patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
                
                mock_tool = Mock()
                mock_tool.name = "android_env"
                mock_registry.__contains__ = Mock(return_value=True)
                mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
                
                mock_call.return_value = {
                    "image": None,
                    "reward": 1.0,
                    "terminated": True,
                    "truncated": False,
                    "info": {},
                }
                
                await traj.initialize_trajectory()
                await traj.generate_trajectory()
                await traj.evaluate_trajectory()
        
        await asyncio.gather(*[run_trajectory(t) for t in trajectories])
        
        # Verify: All trajectories completed
        for i, traj in enumerate(trajectories):
            assert traj.result is not None, f"Trajectory {i} has no result"
            assert traj.result["finish_reason"] == "FINISH", f"Trajectory {i} did not finish"
            assert traj.result["reward"] == 1.0, f"Trajectory {i} reward mismatch"


class TestE2EErrorHandling:
    """Test error handling in E2E scenarios."""
    
    @pytest.mark.asyncio
    async def test_trajectory_handles_env_error(
        self, mock_traj_config, mock_tokenizer, mock_processor
    ):
        """Trajectory handles environment errors gracefully."""
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        mock_infer_engine = AsyncMock()
        mock_infer_engine.async_generate_ids = AsyncMock(
            return_value=("Thought: Try action.\nAction: click(start_box='(500,500)')", "stop")
        )
        
        # Environment that fails on step
        mock_env_handle = AsyncMock()
        mock_env_handle.reset = AsyncMock(return_value=(
            {"task": "Test", "image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)},
            {}
        ))
        
        data = {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"}
        traj = AndroidTrajectory(
            cfg=mock_traj_config,
            data=data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=AndroidTask,
        )
        traj.env_handle = mock_env_handle
        traj.processor = mock_processor
        
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry, \
             patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            # Simulate environment error
            mock_call.side_effect = Exception("Environment crashed")
            
            await traj.initialize_trajectory()
            await traj.generate_trajectory()
        
        # Verify: Error was caught and recorded
        assert traj.result is not None
        assert "error_runtime" in traj.result["finish_reason"]
    
    @pytest.mark.asyncio
    async def test_trajectory_handles_parse_error(
        self, mock_traj_config, mock_tokenizer, mock_processor, mock_env_handle
    ):
        """Trajectory handles action parse errors gracefully."""
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        # Malformed response that can't be parsed
        mock_infer_engine = AsyncMock()
        mock_infer_engine.async_generate_ids = AsyncMock(
            return_value=("This is not a valid action format at all!", "stop")
        )
        
        data = {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"}
        traj = AndroidTrajectory(
            cfg=mock_traj_config,
            data=data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=AndroidTask,
        )
        traj.env_handle = mock_env_handle
        traj.processor = mock_processor
        
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry, \
             patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            # Will be called with fallback action (infeasible)
            mock_call.return_value = {
                "image": None,
                "reward": 0.0,
                "terminated": True,
                "truncated": False,
                "info": {},
            }
            
            await traj.initialize_trajectory()
            await traj.generate_trajectory()
        
        # Verify: Trajectory completed despite parse error
        assert traj.result is not None
        assert traj.agent.state.format_reward == -1.0  # Penalty for bad format


class TestE2ETrainingDataCollection:
    """Test that E2E pipeline collects correct training data."""
    
    @pytest.mark.asyncio
    async def test_training_tensors_collected(
        self, mock_traj_config, mock_tokenizer, mock_processor, sample_observation
    ):
        """Verify training tensors are collected during trajectory."""
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        mock_infer_engine = AsyncMock()
        mock_infer_engine.async_generate_ids = AsyncMock(
            return_value=("Thought: Complete.\nAction: finished(content='done')", "stop")
        )
        
        mock_env_handle = AsyncMock()
        mock_env_handle.reset = AsyncMock(return_value=(sample_observation, {}))
        
        data = {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"}
        traj = AndroidTrajectory(
            cfg=mock_traj_config,
            data=data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=AndroidTask,
        )
        traj.env_handle = mock_env_handle
        traj.processor = mock_processor
        
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry, \
             patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            mock_call.return_value = {
                "image": None,
                "reward": 1.0,
                "terminated": True,
                "truncated": False,
                "info": {},
            }
            
            await traj.initialize_trajectory()
            await traj.generate_trajectory()
        
        # Verify: Training data collected
        train_dict = traj.result.get("train_dict", {})
        assert "input_ids" in train_dict
        assert "labels" in train_dict
        assert "attention_mask" in train_dict
        
        # Verify tensors have content
        assert train_dict["input_ids"].numel() > 0
        assert train_dict["labels"].numel() > 0
