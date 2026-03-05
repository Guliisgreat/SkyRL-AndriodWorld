"""
Integration tests for Dispatcher + Agent interaction.

Tests the async_fix_pool dispatcher with AndroidAgent/AndroidTrajectory to verify:
- Environment pool management
- Parallel trajectory execution
- Environment assignment and release
- Error handling across concurrent trajectories

These tests use mocks to avoid requiring Docker/real environments.
"""

import asyncio
import numpy as np
from typing import Dict, Any, List
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from dataclasses import dataclass, field

import pytest


# Mark all tests in this module
pytestmark = [pytest.mark.integration]


# ==================== Fixtures ====================


@pytest.fixture
def mock_env_pool_factory():
    """Factory to create mock environment pools of various sizes."""
    def _factory(pool_size: int = 4, fail_indices: List[int] = None):
        """
        Create mock environment pool.
        
        Args:
            pool_size: Number of environments
            fail_indices: List of env indices that should fail on step
        """
        fail_indices = fail_indices or []
        pool = []
        
        for i in range(pool_size):
            env = AsyncMock()
            env.env_id = i
            
            env.reset = AsyncMock(return_value=(
                {
                    "task": f"Task for env {i}",
                    "image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8),
                },
                {}
            ))
            
            if i in fail_indices:
                env.step = Mock(side_effect=Exception(f"Env {i} failed"))
            else:
                env.step = Mock(return_value=(
                    {"image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)},
                    0.0,
                    False,
                    False,
                    {}
                ))
            
            pool.append(env)
        
        return pool
    
    return _factory


@pytest.fixture
def mock_trajectories_factory(mock_traj_config, mock_tokenizer, mock_processor):
    """Factory to create mock trajectories."""
    def _factory(num_instances: int, num_trajectories: int):
        """Create nested dict of trajectories: {instance_id: {traj_id: traj}}."""
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        trajectories = {}
        
        for inst_id in range(num_instances):
            trajectories[inst_id] = {}
            for traj_id in range(num_trajectories):
                mock_infer_engine = AsyncMock()
                mock_infer_engine.async_generate_ids = AsyncMock(
                    return_value=("Thought: Done.\nAction: finished(content='done')", "stop")
                )
                
                data = {
                    "instance_id": inst_id,
                    "instance": {"task_id": inst_id},
                    "epoch": 0,
                    "mode": "train",
                }
                
                traj = AndroidTrajectory(
                    cfg=mock_traj_config,
                    data=data,
                    infer_engine=mock_infer_engine,
                    tokenizer=mock_tokenizer,
                    task=AndroidTask,
                )
                traj.processor = mock_processor
                
                trajectories[inst_id][traj_id] = traj
        
        return trajectories
    
    return _factory


# ==================== Dispatcher Tests ====================


class TestAsyncFixPoolDispatcher:
    """Tests for async_fix_pool dispatcher with trajectory management."""
    
    @pytest.mark.asyncio
    async def test_dispatcher_assigns_envs_correctly(self, mock_env_pool_factory):
        """Dispatcher correctly assigns environments to trajectories."""
        from skyrl_agent.dispatcher.dispatchers import async_fix_pool_dispatcher
        
        pool_size = 2
        num_instances = 3
        num_trajectories = 2
        total_trajectories = num_instances * num_trajectories
        
        env_pool = mock_env_pool_factory(pool_size=pool_size)
        
        # Track which envs were assigned
        env_assignments = []
        
        async def init_fn(batch_idx, trajectory_id, env_id):
            env_assignments.append((batch_idx, trajectory_id, env_id))
        
        async def run_fn(batch_idx, trajectory_id, env_id):
            await asyncio.sleep(0.01)  # Simulate work
        
        async def eval_fn(batch_idx, trajectory_id, env_id):
            pass
        
        cfg = {
            "envs": env_pool,
            "num_instances": num_instances,
            "num_trajectories": num_trajectories,
        }
        
        await async_fix_pool_dispatcher(cfg, init_fn, run_fn, eval_fn)
        
        # Verify: All trajectories were assigned
        assert len(env_assignments) == total_trajectories
        
        # Verify: All env_ids are valid
        for batch_idx, traj_id, env_id in env_assignments:
            assert 0 <= env_id < pool_size
    
    @pytest.mark.asyncio
    async def test_dispatcher_reuses_envs(self, mock_env_pool_factory):
        """Dispatcher correctly reuses environments when trajectories complete."""
        from skyrl_agent.dispatcher.dispatchers import async_fix_pool_dispatcher
        
        pool_size = 2
        num_instances = 4  # More instances than envs
        num_trajectories = 1
        
        env_pool = mock_env_pool_factory(pool_size=pool_size)
        
        # Track env usage count
        env_usage_count = {i: 0 for i in range(pool_size)}
        
        async def init_fn(batch_idx, trajectory_id, env_id):
            env_usage_count[env_id] += 1
        
        async def run_fn(batch_idx, trajectory_id, env_id):
            await asyncio.sleep(0.01)
        
        async def eval_fn(batch_idx, trajectory_id, env_id):
            pass
        
        cfg = {
            "envs": env_pool,
            "num_instances": num_instances,
            "num_trajectories": num_trajectories,
        }
        
        await async_fix_pool_dispatcher(cfg, init_fn, run_fn, eval_fn)
        
        # Verify: Environments were reused (each used at least once)
        for env_id, count in env_usage_count.items():
            assert count >= 1, f"Env {env_id} was never used"
        
        # Verify: Total usage equals total trajectories
        total_usage = sum(env_usage_count.values())
        assert total_usage == num_instances * num_trajectories
    
    @pytest.mark.asyncio
    async def test_dispatcher_handles_worker_error(self, mock_env_pool_factory):
        """Dispatcher continues when a worker encounters an error."""
        from skyrl_agent.dispatcher.dispatchers import async_fix_pool_dispatcher
        
        pool_size = 2
        num_instances = 3
        num_trajectories = 1
        
        env_pool = mock_env_pool_factory(pool_size=pool_size)
        
        completed_trajectories = []
        
        async def init_fn(batch_idx, trajectory_id, env_id):
            pass
        
        async def run_fn(batch_idx, trajectory_id, env_id):
            if batch_idx == 1:  # Middle trajectory fails
                raise Exception("Simulated failure")
            await asyncio.sleep(0.01)
            completed_trajectories.append((batch_idx, trajectory_id))
        
        async def eval_fn(batch_idx, trajectory_id, env_id):
            pass
        
        cfg = {
            "envs": env_pool,
            "num_instances": num_instances,
            "num_trajectories": num_trajectories,
        }
        
        # Should complete without raising
        await async_fix_pool_dispatcher(cfg, init_fn, run_fn, eval_fn)
        
        # Verify: Other trajectories still completed
        # Note: The failed trajectory won't be in completed_trajectories
        assert len(completed_trajectories) >= 2  # At least 2 of 3 completed
    
    @pytest.mark.asyncio
    async def test_dispatcher_parallel_execution(self, mock_env_pool_factory):
        """Verify dispatcher actually runs trajectories in parallel."""
        from skyrl_agent.dispatcher.dispatchers import async_fix_pool_dispatcher
        import time
        
        pool_size = 4
        num_instances = 4
        num_trajectories = 1
        work_time = 0.1  # Each trajectory takes 100ms
        
        env_pool = mock_env_pool_factory(pool_size=pool_size)
        
        start_time = time.time()
        
        async def init_fn(batch_idx, trajectory_id, env_id):
            pass
        
        async def run_fn(batch_idx, trajectory_id, env_id):
            await asyncio.sleep(work_time)
        
        async def eval_fn(batch_idx, trajectory_id, env_id):
            pass
        
        cfg = {
            "envs": env_pool,
            "num_instances": num_instances,
            "num_trajectories": num_trajectories,
        }
        
        await async_fix_pool_dispatcher(cfg, init_fn, run_fn, eval_fn)
        
        elapsed = time.time() - start_time
        
        # If sequential: 4 * 0.1 = 0.4s
        # If parallel: ~0.1s (plus overhead)
        # Allow some margin for overhead
        assert elapsed < 0.3, f"Took {elapsed}s, should be parallel (~0.1s)"


class TestDispatcherWithTrajectories:
    """Tests for dispatcher integration with real AndroidTrajectory objects."""
    
    @pytest.mark.asyncio
    async def test_dispatcher_runs_full_trajectory_lifecycle(
        self, mock_env_pool_factory, mock_trajectories_factory
    ):
        """Dispatcher correctly executes init → run → eval for each trajectory."""
        from skyrl_agent.dispatcher.dispatchers import async_fix_pool_dispatcher
        
        pool_size = 2
        num_instances = 2
        num_trajectories = 2
        
        env_pool = mock_env_pool_factory(pool_size=pool_size)
        trajectories = mock_trajectories_factory(num_instances, num_trajectories)
        
        # Assign env handles and processor
        for inst_id in trajectories:
            for traj_id in trajectories[inst_id]:
                trajectories[inst_id][traj_id].env_handle = env_pool[0]  # Will be reassigned
        
        lifecycle_events = []
        
        async def init_fn(batch_idx, trajectory_id, env_id):
            traj = trajectories[batch_idx][trajectory_id]
            traj.env_handle = env_pool[env_id]
            
            with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry:
                mock_tool = Mock()
                mock_tool.name = "android_env"
                mock_registry.__contains__ = Mock(return_value=True)
                mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
                
                await traj.initialize_trajectory()
            
            lifecycle_events.append(("init", batch_idx, trajectory_id))
        
        async def run_fn(batch_idx, trajectory_id, env_id):
            traj = trajectories[batch_idx][trajectory_id]
            
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
                
                await traj.generate_trajectory()
            
            lifecycle_events.append(("run", batch_idx, trajectory_id))
        
        async def eval_fn(batch_idx, trajectory_id, env_id):
            traj = trajectories[batch_idx][trajectory_id]
            await traj.evaluate_trajectory()
            lifecycle_events.append(("eval", batch_idx, trajectory_id))
        
        cfg = {
            "envs": env_pool,
            "num_instances": num_instances,
            "num_trajectories": num_trajectories,
        }
        
        await async_fix_pool_dispatcher(cfg, init_fn, run_fn, eval_fn)
        
        # Verify: All lifecycle events occurred
        total_expected = num_instances * num_trajectories * 3  # init + run + eval
        assert len(lifecycle_events) == total_expected
        
        # Verify: Order is correct for each trajectory (init before run before eval)
        for inst_id in range(num_instances):
            for traj_id in range(num_trajectories):
                init_idx = lifecycle_events.index(("init", inst_id, traj_id))
                run_idx = lifecycle_events.index(("run", inst_id, traj_id))
                eval_idx = lifecycle_events.index(("eval", inst_id, traj_id))
                
                assert init_idx < run_idx < eval_idx, \
                    f"Wrong order for ({inst_id}, {traj_id}): init={init_idx}, run={run_idx}, eval={eval_idx}"
    
    @pytest.mark.asyncio
    async def test_dispatcher_collects_results_from_all_trajectories(
        self, mock_env_pool_factory, mock_trajectories_factory
    ):
        """All trajectory results are collected after dispatcher completes."""
        from skyrl_agent.dispatcher.dispatchers import async_fix_pool_dispatcher
        
        pool_size = 2
        num_instances = 2
        num_trajectories = 2
        
        env_pool = mock_env_pool_factory(pool_size=pool_size)
        trajectories = mock_trajectories_factory(num_instances, num_trajectories)
        
        async def init_fn(batch_idx, trajectory_id, env_id):
            traj = trajectories[batch_idx][trajectory_id]
            traj.env_handle = env_pool[env_id]
            await traj.initialize_trajectory()
        
        async def run_fn(batch_idx, trajectory_id, env_id):
            traj = trajectories[batch_idx][trajectory_id]
            
            with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry, \
                 patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
                
                mock_tool = Mock()
                mock_tool.name = "android_env"
                mock_registry.__contains__ = Mock(return_value=True)
                mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
                
                # Return different rewards based on trajectory
                mock_call.return_value = {
                    "image": None,
                    "reward": float(batch_idx + trajectory_id) / 10,
                    "terminated": True,
                    "truncated": False,
                    "info": {},
                }
                
                await traj.generate_trajectory()
        
        async def eval_fn(batch_idx, trajectory_id, env_id):
            traj = trajectories[batch_idx][trajectory_id]
            await traj.evaluate_trajectory()
        
        cfg = {
            "envs": env_pool,
            "num_instances": num_instances,
            "num_trajectories": num_trajectories,
        }
        
        await async_fix_pool_dispatcher(cfg, init_fn, run_fn, eval_fn)
        
        # Verify: All trajectories have results
        for inst_id in range(num_instances):
            for traj_id in range(num_trajectories):
                traj = trajectories[inst_id][traj_id]
                assert traj.result is not None, f"Trajectory ({inst_id}, {traj_id}) has no result"
                assert "reward" in traj.result
                assert "finish_reason" in traj.result


class TestAgentEnvInteraction:
    """Tests for agent-environment interaction patterns."""
    
    @pytest.mark.asyncio
    async def test_agent_receives_correct_env_handle(
        self, mock_traj_config, mock_tokenizer, mock_processor, mock_env_pool_factory
    ):
        """Agent correctly uses the assigned environment handle."""
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        env_pool = mock_env_pool_factory(pool_size=2)
        
        # Track which env handle was used
        used_env_handles = []
        
        mock_infer_engine = AsyncMock()
        mock_infer_engine.async_generate_ids = AsyncMock(
            return_value=("Thought: Done.\nAction: finished(content='done')", "stop")
        )
        
        data = {"instance_id": 0, "instance": {"task_id": 0}, "epoch": 0, "mode": "train"}
        traj = AndroidTrajectory(
            cfg=mock_traj_config,
            data=data,
            infer_engine=mock_infer_engine,
            tokenizer=mock_tokenizer,
            task=AndroidTask,
        )
        
        # Assign specific env
        assigned_env = env_pool[1]
        traj.env_handle = assigned_env
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
        
        # Verify: The assigned env was used for reset
        assigned_env.reset.assert_called()
    
    @pytest.mark.asyncio
    async def test_env_handles_not_shared_between_concurrent_trajectories(
        self, mock_traj_config, mock_tokenizer, mock_processor, mock_env_pool_factory
    ):
        """Concurrent trajectories don't interfere with each other's env handles."""
        from skyrl_agent.agents.android.trajectory import AndroidTrajectory
        from skyrl_agent.tasks.android.android_task import AndroidTask
        
        env_pool = mock_env_pool_factory(pool_size=2)
        
        # Track concurrent env usage
        concurrent_env_usage = {0: [], 1: []}  # env_id -> list of (start_time, end_time)
        
        async def run_trajectory_with_tracking(env_idx: int, traj_id: int):
            import time
            start = time.time()
            
            mock_infer_engine = AsyncMock()
            mock_infer_engine.async_generate_ids = AsyncMock(
                return_value=("Thought: Done.\nAction: finished(content='done')", "stop")
            )
            
            data = {"instance_id": env_idx, "instance": {"task_id": traj_id}, "epoch": 0, "mode": "train"}
            traj = AndroidTrajectory(
                cfg=mock_traj_config,
                data=data,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                task=AndroidTask,
            )
            traj.env_handle = env_pool[env_idx]
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
                await asyncio.sleep(0.05)  # Simulate work
                await traj.generate_trajectory()
            
            end = time.time()
            concurrent_env_usage[env_idx].append((start, end))
            return traj
        
        # Run trajectories on different envs concurrently
        trajectories = await asyncio.gather(
            run_trajectory_with_tracking(0, 0),
            run_trajectory_with_tracking(1, 1),
        )
        
        # Verify: Both trajectories completed
        assert all(t.result is not None for t in trajectories)
        
        # Verify: Both envs were used
        assert len(concurrent_env_usage[0]) == 1
        assert len(concurrent_env_usage[1]) == 1


class TestDispatcherEdgeCases:
    """Edge case tests for dispatcher behavior."""
    
    @pytest.mark.asyncio
    async def test_dispatcher_with_single_env(self, mock_env_pool_factory):
        """Dispatcher works correctly with only one environment."""
        from skyrl_agent.dispatcher.dispatchers import async_fix_pool_dispatcher
        
        env_pool = mock_env_pool_factory(pool_size=1)
        num_instances = 3
        num_trajectories = 2
        
        completed = []
        
        async def init_fn(batch_idx, trajectory_id, env_id):
            assert env_id == 0  # Only one env
        
        async def run_fn(batch_idx, trajectory_id, env_id):
            await asyncio.sleep(0.01)
            completed.append((batch_idx, trajectory_id))
        
        async def eval_fn(batch_idx, trajectory_id, env_id):
            pass
        
        cfg = {
            "envs": env_pool,
            "num_instances": num_instances,
            "num_trajectories": num_trajectories,
        }
        
        await async_fix_pool_dispatcher(cfg, init_fn, run_fn, eval_fn)
        
        # Verify: All trajectories completed sequentially
        assert len(completed) == num_instances * num_trajectories
    
    @pytest.mark.asyncio
    async def test_dispatcher_with_more_envs_than_trajectories(self, mock_env_pool_factory):
        """Dispatcher works when there are more envs than trajectories."""
        from skyrl_agent.dispatcher.dispatchers import async_fix_pool_dispatcher
        
        env_pool = mock_env_pool_factory(pool_size=10)
        num_instances = 2
        num_trajectories = 1
        
        used_env_ids = set()
        
        async def init_fn(batch_idx, trajectory_id, env_id):
            used_env_ids.add(env_id)
        
        async def run_fn(batch_idx, trajectory_id, env_id):
            await asyncio.sleep(0.01)
        
        async def eval_fn(batch_idx, trajectory_id, env_id):
            pass
        
        cfg = {
            "envs": env_pool,
            "num_instances": num_instances,
            "num_trajectories": num_trajectories,
        }
        
        await async_fix_pool_dispatcher(cfg, init_fn, run_fn, eval_fn)
        
        # Verify: Only needed envs were used
        assert len(used_env_ids) <= num_instances * num_trajectories
