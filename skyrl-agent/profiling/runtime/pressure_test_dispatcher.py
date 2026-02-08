#!/usr/bin/env python3
"""
Pressure Test for Dispatcher Error Detection and Recovery

This script simulates many mocked trajectories and uses the dispatcher to send them
to multiple concurrent docker containers (mocked) to test:

1. Error detection and classification
2. Container switching on failure
3. Retry logic with fast-fail for dead containers
4. Context length error handling (deterministic failure)
5. Recovery callback mechanism
6. Backup pool usage
7. Concurrent trajectory execution robustness

Usage:
    # Basic pressure test with 20 trajectories across 4 containers
    uv run python tests/profiling/pressure_test_dispatcher.py

    # Large scale test
    uv run python tests/profiling/pressure_test_dispatcher.py \
        --num-trajectories 100 --num-containers 8 --failure-rate 0.3

    # Test specific failure scenarios
    uv run python tests/profiling/pressure_test_dispatcher.py \
        --failure-rate 0.5 --dead-container-rate 0.2 --context-error-rate 0.1

    # Stress test with high failure rate
    uv run python tests/profiling/pressure_test_dispatcher.py \
        --num-trajectories 50 --failure-rate 0.6 --stress-mode

Options:
    --num-trajectories N     Number of trajectories to simulate (default: 20)
    --num-instances N        Number of task instances (default: 4)
    --num-containers N       Number of mock containers (default: 4)
    --failure-rate F         Base failure rate 0-1 (default: 0.2)
    --dead-container-rate F  Rate of dead container errors (default: 0.1)
    --context-error-rate F   Rate of context length errors (default: 0.05)
    --max-retries N          Max retries per container (default: 3)
    --max-container-switches N   Max container switches (default: 2)
    --stress-mode            Enable stress mode (high concurrency, timing chaos)
    --verbose                Enable verbose logging
    --seed N                 Random seed for reproducibility
"""

import asyncio
import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any, Callable
from loguru import logger

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from skyrl_agent.dispatcher.dispatchers import (
    async_fix_pool_retry_dispatcher,
    is_container_dead_error,
    is_context_length_error,
    TrajectoryContext,
    RetryConfig,
    DEAD_CONTAINER_PATTERNS,
    CONTEXT_LENGTH_PATTERNS,
)


# =============================================================================
# Test Configuration
# =============================================================================

@dataclass
class PressureTestConfig:
    """Configuration for pressure test."""
    num_trajectories: int = 5  # trajectories per instance
    num_instances: int = 4
    num_containers: int = 4
    
    # Failure rates
    failure_rate: float = 0.2  # Base failure rate
    dead_container_rate: float = 0.1  # Rate of dead container errors
    context_error_rate: float = 0.05  # Rate of context length errors
    transient_error_rate: float = 0.15  # Rate of transient errors (recoverable)
    
    # Retry configuration
    max_retries: int = 3
    max_container_switches: int = 2
    retry_base_delay: float = 0.1  # Fast for testing
    container_switch_delay: float = 0.2  # Fast for testing
    
    # Timing simulation
    min_step_time: float = 0.01  # Minimum step execution time
    max_step_time: float = 0.1  # Maximum step execution time
    
    # Stress mode settings
    stress_mode: bool = False
    
    # Reproducibility
    seed: Optional[int] = None
    
    # Verbose output
    verbose: bool = False


@dataclass
class TrajectoryResult:
    """Result of a single trajectory execution."""
    batch_idx: int
    trajectory_id: int
    success: bool
    env_ids_used: List[int]
    container_switches: int
    total_attempts: int
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    failure_history: List[Dict] = field(default_factory=list)
    execution_time: float = 0.0


@dataclass
class ContainerStats:
    """Statistics for a mock container."""
    env_id: int
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    dead_errors: int = 0
    context_errors: int = 0
    transient_errors: int = 0
    is_healthy: bool = True
    restart_count: int = 0


@dataclass
class TestMetrics:
    """Overall test metrics."""
    total_trajectories: int = 0
    successful_trajectories: int = 0
    failed_trajectories: int = 0
    context_error_trajectories: int = 0
    
    total_container_switches: int = 0
    total_retry_attempts: int = 0
    
    # Per-container stats
    container_stats: Dict[int, ContainerStats] = field(default_factory=dict)
    
    # Recovery metrics
    recovered_from_dead_container: int = 0
    recovered_from_transient_error: int = 0
    
    # Timing
    total_execution_time: float = 0.0
    avg_trajectory_time: float = 0.0
    
    # Error breakdown
    error_counts: Dict[str, int] = field(default_factory=dict)
    
    # Trajectory results
    trajectory_results: List[TrajectoryResult] = field(default_factory=list)


# =============================================================================
# Mock Container and Error Simulation
# =============================================================================

class ErrorType(Enum):
    """Types of errors that can be simulated."""
    NONE = "none"
    TRANSIENT = "transient"
    DEAD_CONTAINER = "dead_container"
    CONTEXT_LENGTH = "context_length"


class MockContainer:
    """
    Mock container that simulates various failure scenarios.
    
    Tracks statistics and can be configured to fail in different ways.
    """
    
    def __init__(
        self,
        env_id: int,
        failure_rate: float = 0.2,
        dead_container_rate: float = 0.1,
        context_error_rate: float = 0.05,
        stress_mode: bool = False,
    ):
        self.env_id = env_id
        self.failure_rate = failure_rate
        self.dead_container_rate = dead_container_rate
        self.context_error_rate = context_error_rate
        self.stress_mode = stress_mode
        
        self.stats = ContainerStats(env_id=env_id)
        self._is_dead = False
        self._dead_until: Optional[float] = None
        self._consecutive_failures = 0
        self._max_consecutive_dead_failures = 2  # Reset after 2 dead failures
        self._lock = asyncio.Lock()
    
    def mark_dead(self, duration: float = 0.5):
        """Mark container as dead for specified duration (short for testing)."""
        self._is_dead = True
        self._dead_until = time.time() + duration
        self._consecutive_failures += 1
    
    def mark_healthy(self):
        """Mark container as healthy."""
        self._is_dead = False
        self._dead_until = None
        self.stats.is_healthy = True
        self.stats.restart_count += 1
        self._consecutive_failures = 0  # Reset failure counter
    
    def is_healthy(self) -> bool:
        """Check if container is healthy."""
        # Auto-recover after dead duration expires
        if self._dead_until and time.time() > self._dead_until:
            self.mark_healthy()
        # Also auto-recover after too many consecutive dead failures (simulate restart worker)
        if self._consecutive_failures > self._max_consecutive_dead_failures:
            self.mark_healthy()
        return not self._is_dead
    
    def _decide_error_type(self) -> ErrorType:
        """Decide what type of error to generate (if any)."""
        # Check if we should auto-recover
        if self._is_dead:
            if time.time() > (self._dead_until or 0) or \
               self._consecutive_failures > self._max_consecutive_dead_failures:
                self.mark_healthy()
            else:
                return ErrorType.DEAD_CONTAINER
        
        if random.random() > self.failure_rate:
            return ErrorType.NONE
        
        # Decide which type of error
        r = random.random()
        
        # Context errors are deterministic - once triggered, always fail
        if r < self.context_error_rate:
            return ErrorType.CONTEXT_LENGTH
        
        # Dead container errors - but limit consecutive ones
        if r < self.context_error_rate + self.dead_container_rate:
            if self._consecutive_failures < self._max_consecutive_dead_failures:
                return ErrorType.DEAD_CONTAINER
            # If we've had too many dead failures, make it transient instead
            return ErrorType.TRANSIENT
        
        # Everything else is transient
        return ErrorType.TRANSIENT
    
    def _generate_error(self, error_type: ErrorType) -> Exception:
        """Generate an appropriate exception for the error type."""
        if error_type == ErrorType.DEAD_CONTAINER:
            patterns = [
                "cannot connect to server",
                "connection refused by host",
                "server disconnected unexpectedly",
                "connection reset by peer",
                "no route to host",
                "connection timed out after 30s",
            ]
            msg = random.choice(patterns)
            return ConnectionError(msg)
        
        elif error_type == ErrorType.CONTEXT_LENGTH:
            patterns = [
                "maximum model length exceeded (32768 tokens)",
                "max_model_len is 8192 but prompt has 12000 tokens",
                "context window exceeded: 65536 > 32768",
                "prompt is too long: 50000 tokens",
            ]
            msg = random.choice(patterns)
            return ValueError(msg)
        
        elif error_type == ErrorType.TRANSIENT:
            patterns = [
                "HTTP 500: Internal Server Error",
                "emulator screenshot timeout",
                "action execution failed: tap",
                "server busy, try again later",
                "ADB command failed: timeout",
            ]
            msg = random.choice(patterns)
            return RuntimeError(msg)
        
        return RuntimeError("Unknown error")
    
    async def execute(
        self,
        operation: str,
        batch_idx: int,
        trajectory_id: int,
        min_time: float = 0.01,
        max_time: float = 0.1,
    ):
        """
        Execute an operation with simulated timing and potential failures.
        
        Args:
            operation: Name of operation (init, run, eval)
            batch_idx: Batch index
            trajectory_id: Trajectory ID
            min_time: Minimum execution time
            max_time: Maximum execution time
        """
        async with self._lock:
            self.stats.total_requests += 1
        
        # Simulate execution time
        if self.stress_mode:
            # Add timing chaos in stress mode
            await asyncio.sleep(random.uniform(0, max_time * 3))
        else:
            await asyncio.sleep(random.uniform(min_time, max_time))
        
        # Decide if this request fails
        error_type = self._decide_error_type()
        
        async with self._lock:
            if error_type == ErrorType.NONE:
                self.stats.successful_requests += 1
                return  # Success!
            
            self.stats.failed_requests += 1
            
            if error_type == ErrorType.DEAD_CONTAINER:
                self.stats.dead_errors += 1
                self.mark_dead(duration=random.uniform(2.0, 10.0))
            elif error_type == ErrorType.CONTEXT_LENGTH:
                self.stats.context_errors += 1
            elif error_type == ErrorType.TRANSIENT:
                self.stats.transient_errors += 1
        
        # Raise the error
        error = self._generate_error(error_type)
        logger.debug(
            f"[MockContainer env{self.env_id}] {operation} failed for "
            f"({batch_idx}, {trajectory_id}): {type(error).__name__}: {error}"
        )
        raise error


class MockContainerPool:
    """
    Pool of mock containers for testing.
    
    Provides similar interface to ContainerManager but without actual Docker.
    Includes a simulated RestartWorker that recovers unhealthy containers.
    """
    
    def __init__(
        self,
        num_containers: int,
        config: PressureTestConfig,
    ):
        self.config = config
        self.containers: Dict[int, MockContainer] = {}
        
        for i in range(num_containers):
            self.containers[i] = MockContainer(
                env_id=i,
                failure_rate=config.failure_rate,
                dead_container_rate=config.dead_container_rate,
                context_error_rate=config.context_error_rate,
                stress_mode=config.stress_mode,
            )
        
        self._unhealthy_containers: Set[int] = set()
        self._backup_pool: asyncio.Queue = asyncio.Queue()
        self._recovery_callback: Optional[Callable] = None
        self._restart_worker_task: Optional[asyncio.Task] = None
        self._running = False
    
    def get_container(self, env_id: int) -> MockContainer:
        """Get container by env_id."""
        return self.containers[env_id]
    
    async def mark_unhealthy(self, env_id: int):
        """Mark a container as unhealthy."""
        if env_id in self.containers:
            self._unhealthy_containers.add(env_id)
            self.containers[env_id].mark_dead(duration=0.3)  # Short duration for testing
            logger.debug(f"[MockPool] env{env_id} marked UNHEALTHY")
    
    async def quick_ping(self, env_id: int) -> bool:
        """Quick health check for a container."""
        if env_id in self._unhealthy_containers:
            # Check if container has auto-recovered
            if env_id in self.containers and self.containers[env_id].is_healthy():
                self._unhealthy_containers.remove(env_id)
                return True
            return False
        if env_id in self.containers:
            return self.containers[env_id].is_healthy()
        return False
    
    async def get_backup_container(self) -> Optional[int]:
        """Get a backup container if available."""
        try:
            return self._backup_pool.get_nowait()
        except asyncio.QueueEmpty:
            return None
    
    async def add_to_backup_pool(self, env_id: int):
        """Add recovered container to backup pool."""
        if env_id in self._unhealthy_containers:
            self._unhealthy_containers.remove(env_id)
        if env_id in self.containers:
            self.containers[env_id].mark_healthy()
            await self._backup_pool.put(env_id)
            logger.debug(f"[MockPool] env{env_id} added to backup pool")
    
    def set_recovery_callback(self, callback: Callable):
        """Set callback for when a container is recovered."""
        self._recovery_callback = callback
    
    async def start_restart_worker(self, interval: float = 0.2):
        """Start the simulated restart worker."""
        self._running = True
        self._restart_worker_task = asyncio.create_task(
            self._restart_worker_loop(interval)
        )
        logger.debug("[MockPool] RestartWorker started")
    
    async def stop_restart_worker(self):
        """Stop the restart worker."""
        self._running = False
        if self._restart_worker_task:
            self._restart_worker_task.cancel()
            try:
                await self._restart_worker_task
            except asyncio.CancelledError:
                pass
        logger.debug("[MockPool] RestartWorker stopped")
    
    async def _restart_worker_loop(self, interval: float):
        """Background loop that recovers unhealthy containers."""
        while self._running:
            await asyncio.sleep(interval)
            
            # Find containers to recover
            to_recover = []
            for env_id in list(self._unhealthy_containers):
                container = self.containers.get(env_id)
                if container and container.is_healthy():
                    to_recover.append(env_id)
            
            # Recover them
            for env_id in to_recover:
                self._unhealthy_containers.discard(env_id)
                await self._backup_pool.put(env_id)
                logger.debug(f"[MockPool] RestartWorker recovered env{env_id}")
                
                if self._recovery_callback:
                    try:
                        await self._recovery_callback(env_id)
                    except Exception as e:
                        logger.warning(f"[MockPool] Recovery callback failed: {e}")
    
    def get_all_stats(self) -> Dict[int, ContainerStats]:
        """Get stats for all containers."""
        return {env_id: c.stats for env_id, c in self.containers.items()}


# =============================================================================
# Pressure Test Runner
# =============================================================================

class PressureTestRunner:
    """
    Runs pressure tests using the dispatcher with mocked containers.
    """
    
    def __init__(self, config: PressureTestConfig):
        self.config = config
        self.pool: Optional[MockContainerPool] = None
        self.metrics = TestMetrics()
        
        # Set up logging
        if config.verbose:
            logger.remove()
            logger.add(sys.stderr, level="DEBUG")
        else:
            logger.remove()
            logger.add(sys.stderr, level="INFO")
        
        # Set random seed
        if config.seed is not None:
            random.seed(config.seed)
    
    async def run_test(self) -> TestMetrics:
        """
        Run the full pressure test.
        
        Returns:
            TestMetrics with all collected metrics
        """
        start_time = time.time()
        
        logger.info("=" * 60)
        logger.info("PRESSURE TEST: Dispatcher Error Detection & Recovery")
        logger.info("=" * 60)
        logger.info(f"Configuration:")
        logger.info(f"  Trajectories: {self.config.num_instances} instances x {self.config.num_trajectories} trajectories")
        logger.info(f"  Containers: {self.config.num_containers}")
        logger.info(f"  Failure rate: {self.config.failure_rate}")
        logger.info(f"  Dead container rate: {self.config.dead_container_rate}")
        logger.info(f"  Context error rate: {self.config.context_error_rate}")
        logger.info(f"  Max retries: {self.config.max_retries}")
        logger.info(f"  Max container switches: {self.config.max_container_switches}")
        logger.info(f"  Stress mode: {self.config.stress_mode}")
        logger.info("=" * 60)
        
        # Initialize mock container pool
        self.pool = MockContainerPool(self.config.num_containers, self.config)
        
        # Start the simulated restart worker
        await self.pool.start_restart_worker(interval=0.1)
        
        # Track trajectory results
        trajectory_results: Dict[Tuple[int, int], TrajectoryResult] = {}
        trajectory_lock = asyncio.Lock()
        
        # Retry success/failure callbacks
        async def on_retry_success(batch_idx, trajectory_id, retry_count, failure_history):
            async with trajectory_lock:
                key = (batch_idx, trajectory_id)
                if key in trajectory_results:
                    trajectory_results[key].failure_history = failure_history
                    
                    # Check if recovered from dead container
                    for failure in failure_history:
                        if failure.get("is_dead_container"):
                            self.metrics.recovered_from_dead_container += 1
                        else:
                            self.metrics.recovered_from_transient_error += 1
        
        async def on_retry_failure(batch_idx, trajectory_id, retry_count, failure_history, final_error):
            async with trajectory_lock:
                key = (batch_idx, trajectory_id)
                if key in trajectory_results:
                    trajectory_results[key].failure_history = failure_history
                    if final_error:
                        trajectory_results[key].error_type = final_error.get("error_type")
                        trajectory_results[key].error_message = final_error.get("error_message")
        
        # Create trajectory execution functions
        async def init_fn(batch_idx: int, trajectory_id: int, env_id: int):
            """Initialize trajectory on container."""
            container = self.pool.get_container(env_id)
            await container.execute(
                "init", batch_idx, trajectory_id,
                self.config.min_step_time, self.config.max_step_time
            )
            
            async with trajectory_lock:
                key = (batch_idx, trajectory_id)
                if key not in trajectory_results:
                    trajectory_results[key] = TrajectoryResult(
                        batch_idx=batch_idx,
                        trajectory_id=trajectory_id,
                        success=False,
                        env_ids_used=[env_id],
                        container_switches=0,
                        total_attempts=1,
                    )
                else:
                    if env_id not in trajectory_results[key].env_ids_used:
                        trajectory_results[key].env_ids_used.append(env_id)
                        trajectory_results[key].container_switches += 1
                    trajectory_results[key].total_attempts += 1
        
        async def run_fn(batch_idx: int, trajectory_id: int, env_id: int):
            """Run trajectory on container."""
            container = self.pool.get_container(env_id)
            # Run phase takes longer
            await container.execute(
                "run", batch_idx, trajectory_id,
                self.config.min_step_time * 2, self.config.max_step_time * 3
            )
        
        async def eval_fn(batch_idx: int, trajectory_id: int, env_id: int):
            """Evaluate trajectory on container."""
            container = self.pool.get_container(env_id)
            await container.execute(
                "eval", batch_idx, trajectory_id,
                self.config.min_step_time, self.config.max_step_time
            )
            
            # Mark success
            async with trajectory_lock:
                key = (batch_idx, trajectory_id)
                if key in trajectory_results:
                    trajectory_results[key].success = True
        
        # Build dispatcher config
        dispatcher_cfg = {
            "envs": list(range(self.config.num_containers)),
            "num_instances": self.config.num_instances,
            "num_trajectories": self.config.num_trajectories,
            "max_retries": self.config.max_retries,
            "max_container_switches": self.config.max_container_switches,
            "retry_base_delay": self.config.retry_base_delay,
            "container_switch_delay": self.config.container_switch_delay,
            "on_retry_success": on_retry_success,
            "on_retry_failure": on_retry_failure,
            "mark_container_unhealthy": self.pool.mark_unhealthy,
            "quick_ping": self.pool.quick_ping,
            "get_backup_container": self.pool.get_backup_container,
        }
        
        # Run the dispatcher
        try:
            logger.info("\nStarting dispatcher...")
            await async_fix_pool_retry_dispatcher(
                dispatcher_cfg, init_fn, run_fn, eval_fn
            )
            logger.info("Dispatcher completed successfully!")
        except RuntimeError as e:
            logger.error(f"Dispatcher failed with critical error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Stop the restart worker
            await self.pool.stop_restart_worker()
        
        # Collect metrics
        execution_time = time.time() - start_time
        
        self.metrics.total_execution_time = execution_time
        self.metrics.total_trajectories = len(trajectory_results)
        
        for result in trajectory_results.values():
            self.metrics.trajectory_results.append(result)
            
            if result.success:
                self.metrics.successful_trajectories += 1
            else:
                self.metrics.failed_trajectories += 1
                
                # Check if it was a context error
                for failure in result.failure_history:
                    if failure.get("is_context_error"):
                        self.metrics.context_error_trajectories += 1
                        break
            
            self.metrics.total_container_switches += result.container_switches
            self.metrics.total_retry_attempts += result.total_attempts
            
            if result.error_type:
                self.metrics.error_counts[result.error_type] = \
                    self.metrics.error_counts.get(result.error_type, 0) + 1
        
        if self.metrics.total_trajectories > 0:
            self.metrics.avg_trajectory_time = execution_time / self.metrics.total_trajectories
        
        # Collect container stats
        self.metrics.container_stats = self.pool.get_all_stats()
        
        return self.metrics
    
    def print_report(self):
        """Print a detailed report of the test results."""
        m = self.metrics
        
        print("\n")
        print("=" * 70)
        print("PRESSURE TEST RESULTS")
        print("=" * 70)
        
        # Overall Summary
        print("\n[1] Overall Summary")
        print("-" * 50)
        total = m.total_trajectories
        success_rate = (m.successful_trajectories / total * 100) if total > 0 else 0
        
        print(f"  Total Trajectories:      {total}")
        print(f"  Successful:              {m.successful_trajectories} ({success_rate:.1f}%)")
        print(f"  Failed:                  {m.failed_trajectories}")
        print(f"  Context Errors:          {m.context_error_trajectories}")
        print(f"  Execution Time:          {m.total_execution_time:.2f}s")
        print(f"  Avg Trajectory Time:     {m.avg_trajectory_time * 1000:.1f}ms")
        
        # Recovery Metrics
        print("\n[2] Recovery Metrics")
        print("-" * 50)
        print(f"  Total Container Switches:    {m.total_container_switches}")
        print(f"  Total Retry Attempts:        {m.total_retry_attempts}")
        print(f"  Recovered from Dead:         {m.recovered_from_dead_container}")
        print(f"  Recovered from Transient:    {m.recovered_from_transient_error}")
        
        # Container Stats
        print("\n[3] Container Statistics")
        print("-" * 50)
        header = f"{'Env ID':8} {'Total':10} {'Success':10} {'Failed':10} {'Dead':8} {'Context':10} {'Transient':10} {'Restarts':10}"
        print(header)
        print("-" * len(header))
        
        for env_id in sorted(m.container_stats.keys()):
            stats = m.container_stats[env_id]
            print(
                f"{env_id:8} {stats.total_requests:10} {stats.successful_requests:10} "
                f"{stats.failed_requests:10} {stats.dead_errors:8} {stats.context_errors:10} "
                f"{stats.transient_errors:10} {stats.restart_count:10}"
            )
        
        # Error Distribution
        if m.error_counts:
            print("\n[4] Error Type Distribution")
            print("-" * 50)
            for error_type, count in sorted(m.error_counts.items(), key=lambda x: -x[1]):
                print(f"  {error_type:30} {count:5}")
        
        # Trajectory Details (sample)
        print("\n[5] Sample Trajectory Details (first 10)")
        print("-" * 50)
        for result in m.trajectory_results[:10]:
            status = "SUCCESS" if result.success else "FAILED"
            envs = ",".join(str(e) for e in result.env_ids_used)
            print(
                f"  ({result.batch_idx:2}, {result.trajectory_id:2}): {status:7} | "
                f"Envs: [{envs}] | Switches: {result.container_switches} | "
                f"Attempts: {result.total_attempts}"
            )
        
        if len(m.trajectory_results) > 10:
            print(f"  ... and {len(m.trajectory_results) - 10} more trajectories")
        
        # Error Classification Verification
        print("\n[6] Error Classification Verification")
        print("-" * 50)
        
        # Test error classification functions
        dead_test_errors = [
            ConnectionError("connection refused"),
            ConnectionError("cannot connect to server"),
            TimeoutError("connection timed out"),
        ]
        context_test_errors = [
            ValueError("maximum model length exceeded"),
            ValueError("prompt is too long"),
            ValueError("context window exceeded"),
        ]
        
        all_dead_correct = all(is_container_dead_error(e) for e in dead_test_errors)
        all_context_correct = all(is_context_length_error(e) for e in context_test_errors)
        
        print(f"  Dead container errors classified correctly: {all_dead_correct}")
        print(f"  Context length errors classified correctly: {all_context_correct}")
        
        # Final Assessment
        print("\n" + "=" * 70)
        if success_rate > 90:
            print("RESULT: EXCELLENT - High success rate with good recovery")
        elif success_rate > 70:
            print("RESULT: GOOD - Acceptable success rate, some recovery needed")
        elif success_rate > 50:
            print("RESULT: WARNING - Many failures, review error handling")
        else:
            print("RESULT: CRITICAL - Too many failures, system needs attention")
        print("=" * 70)


# =============================================================================
# Unit Tests for Error Classification
# =============================================================================

def test_error_classification():
    """Test that error classification works correctly."""
    print("\n[TEST] Error Classification Unit Tests")
    print("-" * 50)
    
    # Test dead container patterns
    dead_errors = [
        ConnectionError("cannot connect to host"),
        ConnectionError("connection refused"),
        Exception("server disconnected"),
        TimeoutError("connection reset by peer"),
        Exception("no route to host"),
        Exception("network is unreachable"),
        Exception("connection timed out"),
        Exception("failed to establish a new connection"),
    ]
    
    dead_results = [(str(e), is_container_dead_error(e)) for e in dead_errors]
    dead_pass = all(r[1] for r in dead_results)
    
    print(f"  Dead container errors: {'PASS' if dead_pass else 'FAIL'}")
    if not dead_pass:
        for msg, result in dead_results:
            if not result:
                print(f"    FAILED: '{msg[:50]}...'")
    
    # Test context length patterns
    context_errors = [
        ValueError("maximum model length exceeded"),
        ValueError("max_model_len is 8192"),
        Exception("context window exceeded"),
        Exception("context_window_exceeded error"),
        Exception("prompt is too long"),
        Exception("exceeds the maximum token limit"),
    ]
    
    context_results = [(str(e), is_context_length_error(e)) for e in context_errors]
    context_pass = all(r[1] for r in context_results)
    
    print(f"  Context length errors: {'PASS' if context_pass else 'FAIL'}")
    if not context_pass:
        for msg, result in context_results:
            if not result:
                print(f"    FAILED: '{msg[:50]}...'")
    
    # Test non-matching errors
    other_errors = [
        RuntimeError("generic error"),
        ValueError("invalid argument"),
        Exception("task failed"),
    ]
    
    other_dead = [is_container_dead_error(e) for e in other_errors]
    other_context = [is_context_length_error(e) for e in other_errors]
    
    other_pass = not any(other_dead) and not any(other_context)
    print(f"  Other errors not misclassified: {'PASS' if other_pass else 'FAIL'}")
    
    overall = dead_pass and context_pass and other_pass
    print(f"\n  Overall: {'ALL TESTS PASSED' if overall else 'SOME TESTS FAILED'}")
    
    return overall


# =============================================================================
# Main Entry Point
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Pressure test for dispatcher error detection and recovery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--num-trajectories",
        type=int,
        default=5,
        help="Number of trajectories per instance (default: 5)"
    )
    
    parser.add_argument(
        "--num-instances",
        type=int,
        default=4,
        help="Number of task instances (default: 4)"
    )
    
    parser.add_argument(
        "--num-containers",
        type=int,
        default=4,
        help="Number of mock containers (default: 4)"
    )
    
    parser.add_argument(
        "--failure-rate",
        type=float,
        default=0.2,
        help="Base failure rate 0-1 (default: 0.2)"
    )
    
    parser.add_argument(
        "--dead-container-rate",
        type=float,
        default=0.1,
        help="Rate of dead container errors (default: 0.1)"
    )
    
    parser.add_argument(
        "--context-error-rate",
        type=float,
        default=0.05,
        help="Rate of context length errors (default: 0.05)"
    )
    
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries per container (default: 3)"
    )
    
    parser.add_argument(
        "--max-container-switches",
        type=int,
        default=2,
        help="Max container switches (default: 2)"
    )
    
    parser.add_argument(
        "--stress-mode",
        action="store_true",
        help="Enable stress mode (high concurrency, timing chaos)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility"
    )
    
    parser.add_argument(
        "--run-unit-tests",
        action="store_true",
        help="Run unit tests for error classification only"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path for results (optional)"
    )
    
    args = parser.parse_args()
    
    # Run unit tests if requested
    if args.run_unit_tests:
        success = test_error_classification()
        sys.exit(0 if success else 1)
    
    # Build configuration
    config = PressureTestConfig(
        num_trajectories=args.num_trajectories,
        num_instances=args.num_instances,
        num_containers=args.num_containers,
        failure_rate=args.failure_rate,
        dead_container_rate=args.dead_container_rate,
        context_error_rate=args.context_error_rate,
        max_retries=args.max_retries,
        max_container_switches=args.max_container_switches,
        stress_mode=args.stress_mode,
        seed=args.seed,
        verbose=args.verbose,
    )
    
    # Run the test
    runner = PressureTestRunner(config)
    metrics = await runner.run_test()
    
    # Print report
    runner.print_report()
    
    # Save results if output path specified
    if args.output:
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "config": asdict(config),
            "metrics": {
                "total_trajectories": metrics.total_trajectories,
                "successful_trajectories": metrics.successful_trajectories,
                "failed_trajectories": metrics.failed_trajectories,
                "context_error_trajectories": metrics.context_error_trajectories,
                "total_container_switches": metrics.total_container_switches,
                "total_retry_attempts": metrics.total_retry_attempts,
                "recovered_from_dead_container": metrics.recovered_from_dead_container,
                "recovered_from_transient_error": metrics.recovered_from_transient_error,
                "total_execution_time": metrics.total_execution_time,
                "avg_trajectory_time": metrics.avg_trajectory_time,
                "error_counts": metrics.error_counts,
                "container_stats": {
                    str(k): asdict(v) for k, v in metrics.container_stats.items()
                },
            },
            "trajectory_results": [asdict(r) for r in metrics.trajectory_results],
        }
        
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to: {args.output}")
    
    # Return exit code based on success rate
    success_rate = (metrics.successful_trajectories / metrics.total_trajectories * 100) \
        if metrics.total_trajectories > 0 else 0
    
    # Context errors are expected/acceptable, so don't count them as failures
    actual_failures = metrics.failed_trajectories - metrics.context_error_trajectories
    if actual_failures == 0:
        sys.exit(0)
    else:
        # Only exit with error if we have unexpected failures
        sys.exit(1 if success_rate < 50 else 0)


if __name__ == "__main__":
    asyncio.run(main())
