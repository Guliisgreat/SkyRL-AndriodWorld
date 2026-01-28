#!/usr/bin/env python3
"""
Container Pool Profiling Script

This script profiles Docker container interactions with different pool sizes
to measure performance characteristics:

- Container creation time (sequential or parallel startup)
- Container allocation/release latency
- Reset operation latency
- Step operation latency (all action types: click, scroll, type, etc.)
- Concurrent throughput (parallel operations)

Usage:
    # Profile with default pool sizes (1, 2, 4)
    RUN_DOCKER_TESTS=true uv run python tests/profiling/profile_container_pool.py

    # Profile specific pool sizes
    RUN_DOCKER_TESTS=true uv run python tests/profiling/profile_container_pool.py --pool-sizes 1 2 4 8

    # Quick test with single container
    RUN_DOCKER_TESTS=true uv run python tests/profiling/profile_container_pool.py --pool-sizes 1 --skip-concurrent

    # Use parallel pool creation (faster for large pools)
    RUN_DOCKER_TESTS=true uv run python tests/profiling/profile_container_pool.py \\
        --pool-sizes 4 8 16 --parallel-creation --max-concurrent 4 --initial-wait 30

    # Compare sequential vs parallel creation
    RUN_DOCKER_TESTS=true uv run python tests/profiling/profile_container_pool.py \\
        --pool-sizes 8 --parallel-creation --initial-wait 30

Options:
    --pool-sizes N [N ...]     Pool sizes to test (default: 1 2 4)
    --parallel-creation        Use bounded parallel pool creation
    --max-concurrent N         Max concurrent container creations (default: 4)
    --initial-wait SECONDS     Initial emulator boot wait (default: 45, try 30 for faster)
    --skip-concurrent          Skip concurrent throughput test (faster)
    --concurrent-duration S    Duration for concurrent test (default: 30)
    --skip-cleanup             Skip cleanup of stale containers before profiling

Environment Variables:
    RUN_DOCKER_TESTS=true     - Required to run the profiling
    ANDROID_DOCKER_IMAGE      - Docker image name (default: androidworld:v8)
    PROFILE_TEMP_DIR          - Temp directory for logs (default: /tmp/profile_containers)
"""

import asyncio
import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from contextlib import asynccontextmanager

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def cleanup_stale_containers(pattern: str = "env*") -> int:
    """
    Remove stale Docker containers matching the pattern before profiling.
    
    This prevents port conflicts and resource issues from leftover containers.
    
    Args:
        pattern: Container name pattern to match (default: "env*")
    
    Returns:
        Number of containers removed
    """
    import docker
    
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True, filters={"name": pattern})
        
        removed_count = 0
        for container in containers:
            try:
                container_name = container.name
                print(f"  Removing stale container: {container_name}")
                container.remove(force=True)
                removed_count += 1
            except Exception as e:
                print(f"  Warning: Failed to remove {container.name}: {e}")
        
        return removed_count
    except Exception as e:
        print(f"  Warning: Failed to cleanup containers: {e}")
        return 0


# All action types to test for realistic profiling (7 unique types)
# Each action type is tested once to keep profiling time reasonable (~28s vs ~72s)
PROFILING_ACTIONS = [
    {"action_type": "wait"},
    {"action_type": "click", "touch_point": [0.5, 0.5]},
    {"action_type": "scroll", "direction": "down"},
    {"action_type": "navigate_home"},
    {"action_type": "navigate_back"},
    {"action_type": "input_text", "text": "test"},
    {"action_type": "long_press", "touch_point": [0.5, 0.5]},
]


@dataclass
class TimingResult:
    """Single timing measurement."""
    operation: str
    duration_seconds: float
    success: bool
    error: Optional[str] = None


@dataclass
class PoolMetrics:
    """Metrics for a single pool size test."""
    pool_size: int
    
    # Creation metrics
    total_creation_time: float
    per_container_creation_times: List[float]
    avg_creation_time_per_container: float
    
    # Creation mode info
    creation_mode: str  # "sequential" or "parallel"
    max_concurrent: int  # For parallel mode
    initial_wait: float  # Initial wait time used
    
    # Allocation metrics
    allocation_latencies: List[float]
    avg_allocation_latency: float
    
    # Release metrics
    release_latencies: List[float]
    avg_release_latency: float
    
    # Reset metrics
    reset_latencies: List[float]
    avg_reset_latency: float
    
    # Step metrics - per action type breakdown
    step_latencies_by_type: Dict[str, List[float]]
    avg_step_latency_by_type: Dict[str, float]
    avg_step_latency: float  # Overall average for backward compatibility
    
    # Concurrent metrics
    concurrent_ops_per_second: float
    concurrent_total_ops: int
    concurrent_duration: float
    
    # Errors
    errors: List[str]
    
    def to_dict(self) -> Dict:
        return asdict(self)


class ContainerPoolProfiler:
    """Profiler for container pool operations."""
    
    def __init__(
        self,
        docker_image: str = "androidworld:v8",
        temp_path: str = "/tmp/profile_containers",
        base_env_id: int = 100,
    ):
        self.docker_image = docker_image
        self.temp_path = temp_path
        self.base_env_id = base_env_id
        self.manager = None
        
        os.makedirs(temp_path, exist_ok=True)
    
    @asynccontextmanager
    async def create_manager(self, pool_size: int):
        """Context manager for ContainerManager with cleanup."""
        from skyrl_agent.runtime.android.container_manager import ContainerManager
        
        manager = ContainerManager(
            docker_image=self.docker_image,
            temp_path=os.path.join(self.temp_path, f"pool_{pool_size}"),
        )
        
        try:
            yield manager
        finally:
            await manager.cleanup()
    
    async def profile_pool_creation(
        self,
        manager,
        pool_size: int,
        env_id_offset: int = 0,
        use_parallel: bool = False,
        max_concurrent: int = 4,
        initial_wait: float = 45.0,
    ) -> Tuple[float, List[float], List]:
        """
        Profile pool creation time.
        
        Args:
            manager: ContainerManager instance
            pool_size: Number of containers to create
            env_id_offset: Offset for environment IDs
            use_parallel: Use parallel pool creation
            max_concurrent: Max concurrent container creations (for parallel mode)
            initial_wait: Initial emulator boot wait time in seconds
        
        Returns:
            Tuple of (total_time, per_container_times, containers)
        """
        from skyrl_agent.runtime.android.container_manager import ContainerManager
        
        per_container_times = []
        mode_str = f"parallel, max_concurrent={max_concurrent}" if use_parallel else "sequential"
        
        print(f"\n  [1/5] Creating container pool (size={pool_size}, mode={mode_str}, initial_wait={initial_wait}s)...")
        
        total_start = time.time()
        
        if use_parallel:
            # Use parallel pool creation with bounded concurrency
            containers = await manager.create_pool_parallel(
                pool_size=pool_size,
                base_env_id=self.base_env_id + env_id_offset,
                max_concurrent=max_concurrent,
                initial_wait=initial_wait,
                sample_mode="sequential",
                snapshot="clean",
            )
        else:
            # Use sequential pool creation (original behavior)
            containers = await manager.create_pool(
                pool_size=pool_size,
                base_env_id=self.base_env_id + env_id_offset,
                sample_mode="sequential",
                snapshot="clean",
                initial_wait=initial_wait,
            )
        
        total_time = time.time() - total_start
        
        # Estimate per-container time (roughly equal distribution)
        avg_per_container = total_time / pool_size
        per_container_times = [avg_per_container] * pool_size
        
        print(f"       Done: {total_time:.1f}s total, ~{avg_per_container:.1f}s per container")
        
        return total_time, per_container_times, containers
    
    async def profile_allocation_release(
        self,
        manager,
        num_iterations: int = 10,
    ) -> Tuple[List[float], List[float]]:
        """
        Profile container allocation and release latency.
        
        Returns:
            Tuple of (allocation_latencies, release_latencies)
        """
        print(f"\n  [2/5] Profiling allocation/release ({num_iterations} iterations)...")
        
        allocation_latencies = []
        release_latencies = []
        
        for i in range(num_iterations):
            # Allocation
            start = time.time()
            container = await manager.allocate_container(batch_idx=0, trajectory_id=i)
            alloc_time = time.time() - start
            allocation_latencies.append(alloc_time)
            
            # Small delay to simulate work
            await asyncio.sleep(0.01)
            
            # Release
            start = time.time()
            await manager.release_container(container, success=True)
            release_time = time.time() - start
            release_latencies.append(release_time)
        
        avg_alloc = sum(allocation_latencies) / len(allocation_latencies) * 1000
        avg_release = sum(release_latencies) / len(release_latencies) * 1000
        
        print(f"       Allocation: {avg_alloc:.2f}ms avg")
        print(f"       Release: {avg_release:.2f}ms avg")
        
        return allocation_latencies, release_latencies
    
    async def profile_reset_operations(
        self,
        manager,
        containers,
        num_resets_per_container: int = 2,
    ) -> List[float]:
        """
        Profile reset operation latency.
        
        Returns:
            List of reset latencies in seconds
        """
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient
        
        print(f"\n  [3/5] Profiling reset operations...")
        
        reset_latencies = []
        
        # Test on first few containers to save time
        test_containers = containers[:min(len(containers), 4)]
        
        for idx, container in enumerate(test_containers):
            client = RuntimeClient(container)
            
            try:
                for i in range(num_resets_per_container):
                    start = time.time()
                    obs, info = await client.reset({
                        "seed": 42 + i,
                        "options": {"task_id": idx % 10}
                    })
                    reset_time = time.time() - start
                    reset_latencies.append(reset_time)
                    
                    if obs is None:
                        print(f"       WARNING: Reset returned None for container {container.env_id}")
            finally:
                await client.close()
        
        if reset_latencies:
            avg_reset = sum(reset_latencies) / len(reset_latencies)
            print(f"       Reset: {avg_reset:.2f}s avg ({len(reset_latencies)} measurements)")
        else:
            print(f"       Reset: No measurements (error)")
        
        return reset_latencies
    
    async def profile_step_operations(
        self,
        manager,
        containers,
        num_cycles: int = 2,
    ) -> Dict[str, List[float]]:
        """
        Profile step operation latency for all action types.
        
        Args:
            manager: ContainerManager instance
            containers: List of containers to test on
            num_cycles: Number of times to cycle through all action types
        
        Returns:
            Dict mapping action_type -> list of latencies in seconds
        """
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient
        
        print(f"\n  [4/5] Profiling step operations (all action types, {num_cycles} cycles)...")
        
        # Initialize latency tracking per action type
        step_latencies_by_type: Dict[str, List[float]] = {}
        for action in PROFILING_ACTIONS:
            action_type = action["action_type"]
            if action_type not in step_latencies_by_type:
                step_latencies_by_type[action_type] = []
        
        # Test on first few containers
        test_containers = containers[:min(len(containers), 4)]
        
        for idx, container in enumerate(test_containers):
            client = RuntimeClient(container)
            
            try:
                # Reset first
                await client.reset({
                    "seed": 42,
                    "options": {"task_id": idx % 10}
                })
                
                # Cycle through all action types
                for cycle in range(num_cycles):
                    for action in PROFILING_ACTIONS:
                        action_type = action["action_type"]
                        
                        start = time.time()
                        obs, reward, terminated, truncated, info = await client.step({
                            "action": action.copy(),
                            "thought": f"Profiling {action_type} (cycle {cycle})"
                        })
                        step_time = time.time() - start
                        step_latencies_by_type[action_type].append(step_time)
                        
                        if terminated:
                            # Reset and continue if terminated early
                            await client.reset({
                                "seed": 42 + cycle,
                                "options": {"task_id": idx % 10}
                            })
            finally:
                await client.close()
        
        # Print summary per action type
        total_measurements = sum(len(v) for v in step_latencies_by_type.values())
        if total_measurements > 0:
            print(f"       Step latencies by action type ({total_measurements} total measurements):")
            for action_type, latencies in step_latencies_by_type.items():
                if latencies:
                    avg = sum(latencies) / len(latencies)
                    print(f"         {action_type:15s}: {avg:.3f}s avg ({len(latencies)} samples)")
        else:
            print(f"       Step: No measurements (error)")
        
        return step_latencies_by_type
    
    async def profile_concurrent_operations(
        self,
        manager,
        containers,
        duration_seconds: float = 30.0,
    ) -> Tuple[float, int, float]:
        """
        Profile concurrent throughput with parallel operations.
        
        Returns:
            Tuple of (ops_per_second, total_ops, actual_duration)
        """
        from skyrl_agent.runtime.android.runtime_client import RuntimeClient
        
        print(f"\n  [5/5] Profiling concurrent operations ({duration_seconds}s)...")
        
        if len(containers) < 2:
            print(f"       Skipping: Need at least 2 containers for concurrent test")
            return 0.0, 0, 0.0
        
        # Track operations
        ops_completed = 0
        ops_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        
        async def worker(container, worker_id: int):
            nonlocal ops_completed
            
            client = RuntimeClient(container)
            
            try:
                # Initial reset
                await client.reset({
                    "seed": worker_id,
                    "options": {"task_id": worker_id % 10}
                })
                
                while not stop_event.is_set():
                    # Perform step
                    await client.step({
                        "action": {"action_type": "wait"},
                        "thought": f"Worker {worker_id} step"
                    })
                    
                    async with ops_lock:
                        ops_completed += 1
                    
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"       Worker {worker_id} error: {e}")
            finally:
                await client.close()
        
        # Start workers
        start_time = time.time()
        tasks = []
        
        for i, container in enumerate(containers):
            task = asyncio.create_task(worker(container, i))
            tasks.append(task)
        
        # Run for specified duration
        await asyncio.sleep(duration_seconds)
        stop_event.set()
        
        # Wait for workers to finish (with timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            print(f"       WARNING: Some workers timed out")
            for task in tasks:
                task.cancel()
        
        actual_duration = time.time() - start_time
        ops_per_second = ops_completed / actual_duration if actual_duration > 0 else 0
        
        print(f"       Concurrent: {ops_per_second:.2f} ops/s "
              f"({ops_completed} ops in {actual_duration:.1f}s)")
        
        return ops_per_second, ops_completed, actual_duration
    
    async def profile_pool_size(
        self,
        pool_size: int,
        env_id_offset: int = 0,
        skip_concurrent: bool = False,
        concurrent_duration: float = 30.0,
        use_parallel: bool = False,
        max_concurrent: int = 4,
        initial_wait: float = 45.0,
    ) -> PoolMetrics:
        """
        Run full profiling for a specific pool size.
        
        Args:
            pool_size: Number of containers in the pool
            env_id_offset: Offset for environment IDs (to avoid conflicts)
            skip_concurrent: Skip concurrent profiling (faster)
            concurrent_duration: Duration for concurrent test in seconds
            use_parallel: Use parallel pool creation
            max_concurrent: Max concurrent container creations (for parallel mode)
            initial_wait: Initial emulator boot wait time in seconds
        
        Returns:
            PoolMetrics with all measurements
        """
        errors = []
        creation_mode = "parallel" if use_parallel else "sequential"
        
        print(f"\n{'='*60}")
        print(f"PROFILING POOL SIZE: {pool_size} (mode={creation_mode})")
        print(f"{'='*60}")
        
        async with self.create_manager(pool_size) as manager:
            # 1. Profile pool creation
            try:
                creation_time, per_container_times, containers = await self.profile_pool_creation(
                    manager, pool_size, env_id_offset,
                    use_parallel=use_parallel,
                    max_concurrent=max_concurrent,
                    initial_wait=initial_wait,
                )
            except Exception as e:
                errors.append(f"Pool creation failed: {e}")
                raise
            
            # 2. Profile allocation/release
            try:
                alloc_latencies, release_latencies = await self.profile_allocation_release(
                    manager, num_iterations=min(pool_size * 3, 20)
                )
            except Exception as e:
                errors.append(f"Allocation profiling failed: {e}")
                alloc_latencies, release_latencies = [], []
            
            # 3. Profile reset operations
            try:
                reset_latencies = await self.profile_reset_operations(
                    manager, containers, num_resets_per_container=2
                )
            except Exception as e:
                errors.append(f"Reset profiling failed: {e}")
                reset_latencies = []
            
            # 4. Profile step operations (returns Dict[str, List[float]])
            try:
                step_latencies_by_type = await self.profile_step_operations(
                    manager, containers, num_cycles=1
                )
            except Exception as e:
                errors.append(f"Step profiling failed: {e}")
                step_latencies_by_type = {}
            
            # 5. Profile concurrent operations
            if skip_concurrent or pool_size < 2:
                concurrent_ops_per_sec = 0.0
                concurrent_total_ops = 0
                concurrent_dur = 0.0
            else:
                try:
                    concurrent_ops_per_sec, concurrent_total_ops, concurrent_dur = \
                        await self.profile_concurrent_operations(
                            manager, containers, duration_seconds=concurrent_duration
                        )
                except Exception as e:
                    errors.append(f"Concurrent profiling failed: {e}")
                    concurrent_ops_per_sec = 0.0
                    concurrent_total_ops = 0
                    concurrent_dur = 0.0
        
        # Calculate averages
        avg_alloc = sum(alloc_latencies) / len(alloc_latencies) if alloc_latencies else 0
        avg_release = sum(release_latencies) / len(release_latencies) if release_latencies else 0
        avg_reset = sum(reset_latencies) / len(reset_latencies) if reset_latencies else 0
        
        # Calculate per-action-type averages
        avg_step_latency_by_type = {}
        all_step_latencies = []
        for action_type, latencies in step_latencies_by_type.items():
            if latencies:
                avg_step_latency_by_type[action_type] = sum(latencies) / len(latencies)
                all_step_latencies.extend(latencies)
            else:
                avg_step_latency_by_type[action_type] = 0.0
        
        avg_step = sum(all_step_latencies) / len(all_step_latencies) if all_step_latencies else 0
        
        return PoolMetrics(
            pool_size=pool_size,
            total_creation_time=creation_time,
            per_container_creation_times=per_container_times,
            avg_creation_time_per_container=creation_time / pool_size,
            creation_mode=creation_mode,
            max_concurrent=max_concurrent if use_parallel else 1,
            initial_wait=initial_wait,
            allocation_latencies=alloc_latencies,
            avg_allocation_latency=avg_alloc,
            release_latencies=release_latencies,
            avg_release_latency=avg_release,
            reset_latencies=reset_latencies,
            avg_reset_latency=avg_reset,
            step_latencies_by_type=step_latencies_by_type,
            avg_step_latency_by_type=avg_step_latency_by_type,
            avg_step_latency=avg_step,
            concurrent_ops_per_second=concurrent_ops_per_sec,
            concurrent_total_ops=concurrent_total_ops,
            concurrent_duration=concurrent_dur,
            errors=errors,
        )


def print_summary_table(results: List[PoolMetrics]):
    """Print a summary table of all results."""
    print("\n")
    print("=" * 120)
    print("PROFILING SUMMARY")
    print("=" * 120)
    
    # Header
    headers = [
        "Pool Size",
        "Mode",
        "Creation (s)",
        "Per Container (s)",
        "Alloc (ms)",
        "Release (ms)",
        "Reset (s)",
        "Step (s)",
        "Throughput (ops/s)",
    ]
    
    col_widths = [10, 12, 14, 18, 12, 12, 10, 10, 18]
    
    header_line = " | ".join(h.center(w) for h, w in zip(headers, col_widths))
    print(header_line)
    print("-" * len(header_line))
    
    # Data rows
    for m in results:
        mode_str = f"{m.creation_mode[:3]}({m.max_concurrent})" if m.creation_mode == "parallel" else "seq"
        row = [
            str(m.pool_size),
            mode_str,
            f"{m.total_creation_time:.1f}",
            f"{m.avg_creation_time_per_container:.1f}",
            f"{m.avg_allocation_latency * 1000:.2f}",
            f"{m.avg_release_latency * 1000:.2f}",
            f"{m.avg_reset_latency:.2f}" if m.avg_reset_latency > 0 else "N/A",
            f"{m.avg_step_latency:.2f}" if m.avg_step_latency > 0 else "N/A",
            f"{m.concurrent_ops_per_second:.2f}" if m.concurrent_ops_per_second > 0 else "N/A",
        ]
        
        row_line = " | ".join(v.center(w) for v, w in zip(row, col_widths))
        print(row_line)
    
    print("=" * 120)
    
    # Per-action-type step latency breakdown
    print("\nStep Latency by Action Type (seconds):")
    print("-" * 80)
    
    # Collect all action types across all results
    all_action_types = set()
    for m in results:
        all_action_types.update(m.avg_step_latency_by_type.keys())
    
    if all_action_types:
        # Header for action types
        action_header = f"{'Action Type':20s}"
        for m in results:
            action_header += f" | Pool {m.pool_size:3d}"
        print(action_header)
        print("-" * len(action_header))
        
        # Rows for each action type
        for action_type in sorted(all_action_types):
            row = f"{action_type:20s}"
            for m in results:
                avg = m.avg_step_latency_by_type.get(action_type, 0.0)
                row += f" | {avg:8.3f}" if avg > 0 else " |      N/A"
            print(row)
    
    print("-" * 80)
    
    # Additional insights
    if len(results) >= 2:
        print("\nScaling Analysis:")
        base = results[0]
        for m in results[1:]:
            creation_scale = m.total_creation_time / base.total_creation_time
            size_scale = m.pool_size / base.pool_size
            efficiency = size_scale / creation_scale * 100
            
            print(f"  Pool {base.pool_size} -> {m.pool_size}: "
                  f"Creation scales {creation_scale:.1f}x (vs {size_scale:.1f}x linear), "
                  f"Efficiency: {efficiency:.0f}%")
            
            if m.concurrent_ops_per_second > 0 and base.concurrent_ops_per_second > 0:
                throughput_scale = m.concurrent_ops_per_second / base.concurrent_ops_per_second
                print(f"    Throughput scales {throughput_scale:.2f}x")


def save_results(results: List[PoolMetrics], output_path: str):
    """Save results to JSON file."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "results": [m.to_dict() for m in results],
    }
    
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")


async def main():
    parser = argparse.ArgumentParser(
        description="Profile Docker container pool performance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--pool-sizes",
        type=int,
        nargs="+",
        default=[1, 2, 4],
        help="Pool sizes to test (default: 1 2 4)"
    )
    
    parser.add_argument(
        "--docker-image",
        type=str,
        default=os.environ.get("ANDROID_DOCKER_IMAGE", "androidworld:v8"),
        help="Docker image name"
    )
    
    parser.add_argument(
        "--temp-dir",
        type=str,
        default=os.environ.get("PROFILE_TEMP_DIR", "/tmp/profile_containers"),
        help="Temporary directory for logs"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path (optional)"
    )
    
    parser.add_argument(
        "--skip-concurrent",
        action="store_true",
        help="Skip concurrent throughput test (faster)"
    )
    
    parser.add_argument(
        "--concurrent-duration",
        type=float,
        default=30.0,
        help="Duration for concurrent test in seconds (default: 30)"
    )
    
    parser.add_argument(
        "--parallel-creation",
        action="store_true",
        help="Use bounded parallel pool creation (faster for large pools)"
    )
    
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=4,
        help="Max concurrent container creations for parallel mode (default: 4)"
    )
    
    parser.add_argument(
        "--initial-wait",
        type=float,
        default=45.0,
        help="Initial emulator boot wait in seconds (default: 45, try 30 for faster startup)"
    )
    
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Skip cleanup of stale containers before profiling"
    )
    
    args = parser.parse_args()
    
    # Check prerequisites
    if os.environ.get("RUN_DOCKER_TESTS", "").lower() != "true":
        print("ERROR: Set RUN_DOCKER_TESTS=true to run profiling")
        print("Example: RUN_DOCKER_TESTS=true uv run python tests/profiling/profile_container_pool.py")
        sys.exit(1)
    
    if not os.path.exists("/var/run/docker.sock") and not os.environ.get("DOCKER_HOST"):
        print("ERROR: Docker not available")
        sys.exit(1)
    
    if not os.path.exists("/dev/kvm"):
        print("WARNING: KVM not available - emulator performance may be degraded")
    
    print("=" * 60)
    print("CONTAINER POOL PROFILING")
    print("=" * 60)
    print(f"Docker image: {args.docker_image}")
    print(f"Pool sizes: {args.pool_sizes}")
    print(f"Temp directory: {args.temp_dir}")
    print(f"Skip concurrent: {args.skip_concurrent}")
    print(f"Concurrent duration: {args.concurrent_duration}s")
    print(f"Parallel creation: {args.parallel_creation}")
    if args.parallel_creation:
        print(f"Max concurrent: {args.max_concurrent}")
    print(f"Initial wait: {args.initial_wait}s")
    print("=" * 60)
    
    # Cleanup stale containers before profiling
    if not args.skip_cleanup:
        print("\nCleaning up stale containers...")
        removed = cleanup_stale_containers("env")
        if removed > 0:
            print(f"  Removed {removed} stale container(s)")
        else:
            print("  No stale containers found")
        print()
    else:
        print("\nSkipping container cleanup (--skip-cleanup)")
        print()
    
    profiler = ContainerPoolProfiler(
        docker_image=args.docker_image,
        temp_path=args.temp_dir,
    )
    
    results: List[PoolMetrics] = []
    
    for i, pool_size in enumerate(args.pool_sizes):
        try:
            metrics = await profiler.profile_pool_size(
                pool_size=pool_size,
                env_id_offset=i * 50,  # Avoid port conflicts between runs
                skip_concurrent=args.skip_concurrent,
                concurrent_duration=args.concurrent_duration,
                use_parallel=args.parallel_creation,
                max_concurrent=args.max_concurrent,
                initial_wait=args.initial_wait,
            )
            results.append(metrics)
            
            if metrics.errors:
                print(f"\n  Errors during profiling:")
                for err in metrics.errors:
                    print(f"    - {err}")
        
        except Exception as e:
            print(f"\nFATAL ERROR profiling pool_size={pool_size}: {e}")
            import traceback
            traceback.print_exc()
    
    # Print summary
    if results:
        print_summary_table(results)
        
        # Save results if output path specified
        if args.output:
            save_results(results, args.output)
        else:
            # Default output path
            output_path = os.path.join(
                args.temp_dir,
                f"profile_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            save_results(results, output_path)
    else:
        print("\nNo results collected - all tests failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
