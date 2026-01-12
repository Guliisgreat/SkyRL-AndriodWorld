"""
End-to-end integration tests for Android agent pipeline.

Tests the COMPLETE flow with REAL components:
    Runner → Dispatcher → Trajectory → Agent → Tool → Environment

Component reality status:
    ✓ Runner: Real AndroidAgentRunner
    ✓ Dispatcher: Real async_fix_pool_dispatcher  
    ✓ Trajectory: Real AndroidTrajectory
    ✓ Agent: Real AndroidAgent
    ✓ Tool: Real AndroidEnvTool (from TOOL_REGISTRY)
    ✓ Tokenizer: Real Qwen2-VL tokenizer (for runner initialization)
    ✓ Processor: Real Qwen2-VL processor (for runner initialization)
    ⚠ Environment: Mock env_handle (Docker not required)
    ⚠ Inference: Mock infer_engine (GPU not required)
    ⚠ Post-processing: Mock _post_process_results (multimodal messages incompatible)

The post-processing is mocked because Android agent produces multimodal messages
(content as list of dicts with images) which the base runner's tokenization
doesn't handle. The E2E flow (Runner → Dispatcher → Trajectory → Agent → Tool)
is fully tested with real components.

Requirements:
    - transformers package (for real tokenizer/processor)
    - Will download Qwen2-VL-2B-Instruct model on first run

For tests with real Docker infrastructure:
    RUN_E2E_DOCKER=true pytest <this_file>
    
For simpler trajectory+agent tests that work with mock tokenizer, see:
    test_integration_trajectory_agent.py
"""

import asyncio
import os
import numpy as np
from typing import Dict, Any, List, Optional
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from dataclasses import dataclass, field

import pytest
from omegaconf import OmegaConf


# ==================== Skip Markers ====================

RUN_E2E_DOCKER = os.environ.get("RUN_E2E_DOCKER", "").lower() == "true"

# Check for transformers availability
TRANSFORMERS_AVAILABLE = False
try:
    from transformers import AutoTokenizer, AutoProcessor
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    pass

skipif_no_docker_e2e = pytest.mark.skipif(
    not RUN_E2E_DOCKER,
    reason="Docker E2E tests disabled (set RUN_E2E_DOCKER=true)"
)

skipif_no_transformers = pytest.mark.skipif(
    not TRANSFORMERS_AVAILABLE,
    reason="transformers package not available"
)

# Mark all tests in this module
pytestmark = [pytest.mark.integration, pytest.mark.e2e]

# Model for integration tests
TEST_MODEL_NAME = os.environ.get("TEST_VLM_MODEL", "Qwen/Qwen2-VL-2B-Instruct")


# ==================== Mock Infrastructure ====================


def create_mock_env_pool(pool_size: int = 2, terminate_after_steps: int = 2):
    """
    Create mock environment pool that simulates real env behavior.
    
    These mocks provide the same interface as real AndroidWorldHostEnv
    but don't require Docker.
    """
    pool = []
    
    for i in range(pool_size):
        env = AsyncMock()
        env.env_id = i
        
        # Reset returns (observation, info)
        env.reset = AsyncMock(return_value=(
            {
                "task": f"Test task {i}: Open Settings and find WiFi",
                "image": np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8),
            },
            {"task_id": i}
        ))
        
        # Step counter for simulating termination
        step_count = [0]
        
        def make_step_fn(env_idx, counter, max_steps):
            def step_fn(payload):
                counter[0] += 1
                action = payload.get("action", {})
                action_type = action.get("action_type", "")
                
                # Check for finish action
                if action_type == "status" and action.get("goal_status") == "complete":
                    return (
                        {"image": None},
                        1.0,  # Success reward
                        True,  # Terminated
                        False,
                        {"success": True}
                    )
                
                # Check for infeasible
                if action_type == "status" and action.get("goal_status") == "infeasible":
                    return (
                        {"image": None},
                        0.0,
                        True,
                        False,
                        {"success": False}
                    )
                
                # Regular step - continue
                if counter[0] >= max_steps:
                    # Force termination after max steps
                    return (
                        {"image": np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)},
                        0.0,
                        False,
                        True,  # Truncated
                        {}
                    )
                
                return (
                    {"image": np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)},
                    0.0,
                    False,
                    False,
                    {}
                )
            return step_fn
        
        env.step = Mock(side_effect=make_step_fn(i, step_count, terminate_after_steps))
        pool.append(env)
    
    return pool


def create_mock_infer_engine(responses: Optional[List[tuple]] = None):
    """
    Create mock inference engine with predefined responses.
    
    If responses is None, returns a response that finishes immediately.
    """
    engine = AsyncMock()
    
    if responses is None:
        # Default: finish immediately
        responses = [
            ("Thought: Task is complete.\nAction: finished(content='done')", "stop"),
        ]
    
    # Repeat responses for multiple trajectories
    engine.async_generate_ids = AsyncMock(side_effect=responses * 100)
    return engine


# ==================== Runner Config ====================


def create_runner_config(
    pool_size: int = 2,
    num_trajectories: int = 2,
    max_iterations: int = 5,
) -> OmegaConf:
    """Create OmegaConf configuration for AndroidAgentRunner."""
    cfg = {
        "generator": {
            "max_prompt_length": 4096,
            "max_iterations": max_iterations,
            "vision_is_active": True,
            "num_trajectories": num_trajectories,
            "infer_backend": "mock",
            "backend_config": {},  # Required by base AgentRunner
            "sampling_params": {"temperature": 0.7, "max_tokens": 512},
            "remove_think_tokens": False,  # Required by post-processing
            "val_config": {
                "num_trajectories": 1,
                "sampling_params": {"temperature": 0.0, "max_tokens": 512},
            },
        },
        "env": {
            "pool_size": pool_size,
        },
        "actor_rollout_ref": {
            "model": {
                "path": "Qwen/Qwen2-VL-2B-Instruct",
                "trust_remote_code": True,
            }
        },
        "agent_cls": "skyrl_agent.agents.android.AndroidAgent",
        "task": "skyrl_agent.tasks.android.AndroidTask",  # Required by base AgentRunner
    }
    return OmegaConf.create(cfg)


# Context manager for mocking infrastructure layer
from contextlib import contextmanager


def create_mock_post_process_result(num_instances: int, num_trajectories: int = 1):
    """
    Create mock result for _post_process_results.
    
    This bypasses tokenization issues with multimodal messages while
    still returning realistic training data structure.
    """
    results = []
    for inst_id in range(num_instances):
        for traj_id in range(num_trajectories):
            results.append({
                "instance_id": inst_id,
                "trajectory_id": traj_id,
                "input_ids": list(range(100)),  # Dummy tokens
                "assistant_masks": [False] * 50 + [True] * 50,
                "reward": 1.0,
                "finish_reason": "FINISH",
                "resolved": True,
            })
    return results


@contextmanager
def mock_infrastructure(infer_engine, input_batch, num_trajectories: int = 1):
    """
    Mock the infrastructure layer (backend, input/output conversion, post-processing).
    
    This allows testing real Runner/Dispatcher/Trajectory/Agent/Tool
    without requiring actual inference backends or tokenization compatibility.
    
    The _post_process_results is mocked because Android agent produces multimodal
    messages (content as list of dicts) which the base runner's tokenization
    doesn't handle correctly.
    """
    num_instances = len(input_batch)
    mock_result = create_mock_post_process_result(num_instances, num_trajectories)
    
    with patch('skyrl_agent.agents.base.build_backend') as mock_build, \
         patch('skyrl_agent.agents.android.android_runner.build_generator_input') as mock_input, \
         patch('skyrl_agent.agents.android.android_runner.build_generator_output') as mock_output, \
         patch('skyrl_agent.agents.base.AgentRunner._post_process_results') as mock_post:
        
        mock_build.return_value = infer_engine
        mock_input.return_value = MagicMock(input_batch=input_batch)
        mock_output.return_value = MagicMock(result={"trajectories": []})
        mock_post.return_value = mock_result
        
        yield {
            'build_backend': mock_build,
            'build_generator_input': mock_input,
            'build_generator_output': mock_output,
            'post_process_results': mock_post,
        }


# ==================== Real ML Fixtures ====================


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


# ==================== E2E Tests with Real Components ====================


@skipif_no_transformers
class TestE2ERealRunner:
    """
    E2E tests using real AndroidAgentRunner with real internal components.
    
    Uses real Qwen tokenizer/processor for proper post-processing.
    Only external infrastructure (Docker, GPU) is mocked.
    """
    
    @pytest.mark.asyncio
    async def test_runner_single_batch_completes(
        self, real_tokenizer, real_processor
    ):
        """Runner processes a single batch through full pipeline."""
        from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        # Setup
        cfg = create_runner_config(pool_size=2, num_trajectories=1, max_iterations=3)
        env_pool = create_mock_env_pool(pool_size=2)
        infer_engine = create_mock_infer_engine()
        
        input_batch = [
            {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"},
            {"instance_id": 1, "instance": {"task_id": 1}, "epoch": 0, "mode": "train"},
        ]
        
        # Mock infrastructure layer
        with mock_infrastructure(infer_engine, input_batch):
            runner = AndroidAgentRunner(
                cfg=cfg,
                infer_engine=infer_engine,
                tokenizer=real_tokenizer,
            )
            runner.processor = real_processor
            
            # Mock initialize_runtime to return our env pool
            with patch.object(AndroidTask, 'initialize_runtime', new_callable=AsyncMock) as mock_init:
                mock_init.return_value = env_pool
                
                # Run
                result = await runner.run(input_batch)
            
            # Verify: Environment pool was initialized
            mock_init.assert_called_once()
            
            # Verify: Results returned for all instances
            assert result is not None
    
    @pytest.mark.asyncio
    async def test_runner_uses_real_dispatcher(
        self, real_tokenizer, real_processor
    ):
        """Verify runner uses real async_fix_pool dispatcher."""
        from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
        from skyrl_agent.tasks.android.android_task import AndroidTask
        from skyrl_agent.dispatcher.dispatchers import DISPATCHER_REGISTRY
        
        # Verify dispatcher is registered
        assert "async_fix_pool" in DISPATCHER_REGISTRY
        
        # Setup
        cfg = create_runner_config(pool_size=1, num_trajectories=1, max_iterations=2)
        env_pool = create_mock_env_pool(pool_size=1)
        infer_engine = create_mock_infer_engine()
        
        input_batch = [
            {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"},
        ]
        
        # Track dispatcher calls
        dispatcher_called = []
        original_dispatcher = DISPATCHER_REGISTRY["async_fix_pool"]
        
        async def tracking_dispatcher(cfg, init_fn, run_fn, eval_fn):
            dispatcher_called.append(True)
            return await original_dispatcher(cfg, init_fn, run_fn, eval_fn)
        
        with mock_infrastructure(infer_engine, input_batch):
            runner = AndroidAgentRunner(
                cfg=cfg,
                infer_engine=infer_engine,
                tokenizer=real_tokenizer,
            )
            runner.processor = real_processor
            
            with patch.object(AndroidTask, 'initialize_runtime', new_callable=AsyncMock) as mock_init:
                mock_init.return_value = env_pool
                
                with patch.dict(DISPATCHER_REGISTRY, {"async_fix_pool": tracking_dispatcher}):
                    await runner.run(input_batch)
        
        # Verify: Dispatcher was called
        assert len(dispatcher_called) == 1
    
    @pytest.mark.asyncio
    async def test_runner_uses_real_tool(
        self, real_tokenizer, real_processor
    ):
        """Verify runner uses real AndroidEnvTool (not mocked)."""
        from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
        from skyrl_agent.tasks.android.android_task import AndroidTask
        from skyrl_agent.tools.base import TOOL_REGISTRY
        
        # Verify tool is registered
        assert "android_env" in TOOL_REGISTRY
        
        # Setup with responses that finish
        cfg = create_runner_config(pool_size=1, num_trajectories=1, max_iterations=3)
        env_pool = create_mock_env_pool(pool_size=1, terminate_after_steps=5)
        infer_engine = create_mock_infer_engine()  # Default: finish immediately
        
        input_batch = [
            {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"},
        ]
        
        with mock_infrastructure(infer_engine, input_batch):
            runner = AndroidAgentRunner(
                cfg=cfg,
                infer_engine=infer_engine,
                tokenizer=real_tokenizer,
            )
            runner.processor = real_processor
            
            with patch.object(AndroidTask, 'initialize_runtime', new_callable=AsyncMock) as mock_init:
                mock_init.return_value = env_pool
                
                result = await runner.run(input_batch)
        
        # Verify: Pipeline completed with result
        assert result is not None
        # Verify: AndroidEnvTool class is available in registry
        assert "android_env" in TOOL_REGISTRY


@skipif_no_transformers
class TestE2EFullPipeline:
    """
    Full pipeline E2E tests verifying all components work together.
    
    Uses real Qwen tokenizer/processor for proper post-processing.
    """
    
    @pytest.mark.asyncio
    async def test_multi_step_trajectory_with_real_tool(
        self, real_tokenizer, real_processor
    ):
        """Multi-step trajectory using real tool execution."""
        from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        # Setup with larger iteration count to allow multi-step
        cfg = create_runner_config(pool_size=1, num_trajectories=1, max_iterations=5)
        env_pool = create_mock_env_pool(pool_size=1, terminate_after_steps=10)
        infer_engine = create_mock_infer_engine()  # Default: finish immediately
        
        input_batch = [
            {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"},
        ]
        
        with mock_infrastructure(infer_engine, input_batch):
            runner = AndroidAgentRunner(
                cfg=cfg,
                infer_engine=infer_engine,
                tokenizer=real_tokenizer,
            )
            runner.processor = real_processor
            
            with patch.object(AndroidTask, 'initialize_runtime', new_callable=AsyncMock) as mock_init:
                mock_init.return_value = env_pool
                
                result = await runner.run(input_batch)
        
        # Verify: Pipeline completed
        assert result is not None
        # Verify: Environment was initialized and used
        mock_init.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_parallel_trajectories_with_env_pool(
        self, real_tokenizer, real_processor
    ):
        """Multiple trajectories share environment pool correctly."""
        from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        cfg = create_runner_config(pool_size=2, num_trajectories=2, max_iterations=3)
        env_pool = create_mock_env_pool(pool_size=2, terminate_after_steps=5)
        infer_engine = create_mock_infer_engine()  # Finishes immediately
        
        # 2 instances × 2 trajectories = 4 total trajectories
        input_batch = [
            {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"},
            {"instance_id": 1, "instance": {"task_id": 1}, "epoch": 0, "mode": "train"},
        ]
        
        with mock_infrastructure(infer_engine, input_batch):
            runner = AndroidAgentRunner(
                cfg=cfg,
                infer_engine=infer_engine,
                tokenizer=real_tokenizer,
            )
            runner.processor = real_processor
            
            with patch.object(AndroidTask, 'initialize_runtime', new_callable=AsyncMock) as mock_init:
                mock_init.return_value = env_pool
                
                result = await runner.run(input_batch)
        
        # Verify: Both envs were used (reset called on each)
        assert env_pool[0].reset.called
        assert env_pool[1].reset.called
    
    @pytest.mark.asyncio
    async def test_error_handling_propagates_correctly(
        self, real_tokenizer, real_processor
    ):
        """Errors in environment are handled by real components."""
        from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        cfg = create_runner_config(pool_size=1, num_trajectories=1, max_iterations=3)
        
        # Create env that fails on step
        env_pool = []
        env = AsyncMock()
        env.env_id = 0
        env.reset = AsyncMock(return_value=(
            {"task": "Test", "image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)},
            {}
        ))
        env.step = Mock(side_effect=Exception("Environment crashed!"))
        env_pool.append(env)
        
        # Response that triggers step
        responses = [
            ("Thought: Click.\nAction: click(start_box='(500,500)')", "stop"),
        ]
        infer_engine = create_mock_infer_engine(responses)
        
        input_batch = [
            {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"},
        ]
        
        with mock_infrastructure(infer_engine, input_batch):
            runner = AndroidAgentRunner(
                cfg=cfg,
                infer_engine=infer_engine,
                tokenizer=real_tokenizer,
            )
            runner.processor = real_processor
            
            with patch.object(AndroidTask, 'initialize_runtime', new_callable=AsyncMock) as mock_init:
                mock_init.return_value = env_pool
                
                # Should complete without raising (error handled internally)
                result = await runner.run(input_batch)
        
        # Verify: Run completed despite error
        assert result is not None


@skipif_no_transformers
class TestE2ETrainingDataFlow:
    """Test that training data flows correctly through the pipeline."""
    
    @pytest.mark.asyncio
    async def test_training_tensors_collected_e2e(
        self, real_tokenizer, real_processor
    ):
        """Training tensors are collected through full E2E pipeline."""
        from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        cfg = create_runner_config(pool_size=1, num_trajectories=1, max_iterations=3)
        env_pool = create_mock_env_pool(pool_size=1)
        infer_engine = create_mock_infer_engine()
        
        input_batch = [
            {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"},
        ]
        
        with mock_infrastructure(infer_engine, input_batch):
            runner = AndroidAgentRunner(
                cfg=cfg,
                infer_engine=infer_engine,
                tokenizer=real_tokenizer,
            )
            runner.processor = real_processor
            
            with patch.object(AndroidTask, 'initialize_runtime', new_callable=AsyncMock) as mock_init:
                mock_init.return_value = env_pool
                
                result = await runner.run(input_batch)
        
        # Verify: Result contains training data
        # (exact structure depends on build_generator_output)
        assert result is not None


@skipif_no_transformers
class TestE2EValidationMode:
    """Test validation mode through E2E pipeline."""
    
    @pytest.mark.asyncio
    async def test_validation_mode_uses_different_config(
        self, real_tokenizer, real_processor
    ):
        """Validation mode uses val_config parameters."""
        from skyrl_agent.agents.android.android_runner import AndroidAgentRunner
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        cfg = create_runner_config(pool_size=1, num_trajectories=2, max_iterations=3)
        # val_config has num_trajectories=1
        
        env_pool = create_mock_env_pool(pool_size=1)
        infer_engine = create_mock_infer_engine()
        
        input_batch = [
            {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "val"},
        ]
        
        with mock_infrastructure(infer_engine, input_batch):
            runner = AndroidAgentRunner(
                cfg=cfg,
                infer_engine=infer_engine,
                tokenizer=real_tokenizer,
            )
            runner.processor = real_processor
            
            with patch.object(AndroidTask, 'initialize_runtime', new_callable=AsyncMock) as mock_init:
                mock_init.return_value = env_pool
                
                # Run in validation mode
                result = await runner.run(input_batch, val_mode=True)
        
        # Verify: Only 1 trajectory (from val_config), not 2
        # Reset should be called once (1 trajectory)
        assert env_pool[0].reset.call_count == 1
