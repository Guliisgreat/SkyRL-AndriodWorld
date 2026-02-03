import asyncio
from dataclasses import dataclass, field
from typing import Callable, Any, Dict, List, Optional, Tuple
from loguru import logger

# Dispatcher Registry
DISPATCHER_REGISTRY: Dict[str, "DispatcherType"] = {}

# Type aliases for clarity
DispatcherType = Callable[..., Any]

# === Configuration Constants ===
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_CONTAINER_SWITCHES = 2
DEFAULT_RETRY_BASE_DELAY = 2.0
DEFAULT_CONTAINER_SWITCH_DELAY = 10.0
QUEUE_DRAIN_TIMEOUT = 1.0


# === Error Classification for Fast-Fail ===

# Patterns that DEFINITELY indicate the container is dead (fast-fail immediately)
# These are unambiguous - no point retrying on same container
DEFINITELY_DEAD_PATTERNS: List[str] = [
    "connection refused",          # Server process not running
    "no route to host",            # Network configuration broken
    "network is unreachable",      # Interface down
]

# Patterns that POSSIBLY indicate container is dead (need confirmation)
# These can be transient - require 2+ consecutive failures before switching
POSSIBLY_DEAD_PATTERNS: List[str] = [
    "cannot connect",
    "server disconnected",
    "connection reset by peer",
    "connection timed out",        # Could be slow, not dead
    "failed to establish a new connection",
]

# Combined for backward compatibility
DEAD_CONTAINER_PATTERNS: List[str] = DEFINITELY_DEAD_PATTERNS + POSSIBLY_DEAD_PATTERNS

# Patterns that indicate context length exceeded (not recoverable by retry or switch)
CONTEXT_LENGTH_PATTERNS: List[str] = [
    "maximum model length",
    "max_model_len",
    "context window exceeded",
    "context_window_exceeded",
    "prompt is too long",
    "exceeds the maximum",
]


def is_container_dead_error(error: Exception, consecutive_failures: int = 1) -> bool:
    """
    Check if an error indicates the container is dead/unreachable.
    
    Uses a two-tier approach to balance reliability vs responsiveness:
    - DEFINITELY_DEAD patterns: Fast-fail immediately (no retries will help)
    - POSSIBLY_DEAD patterns: Require 2+ consecutive failures before declaring dead
    
    This prevents unnecessary container switches from transient issues like:
    - Momentary network hiccups
    - Container under heavy load (slow response)
    - Brief connection timeouts
    
    Trade-off: 1-2 extra seconds of retry << 45-120 seconds of container restart
    
    Args:
        error: The exception that was raised
        consecutive_failures: Number of consecutive failures on this container (default: 1)
    
    Returns:
        True if this is a dead container error, False otherwise
    """
    error_str = str(error).lower()
    
    # Definitely dead - no second chances, these are unambiguous
    if any(pattern in error_str for pattern in DEFINITELY_DEAD_PATTERNS):
        return True
    
    # Possibly dead - require confirmation via consecutive failures
    # This prevents false positives from transient issues
    if consecutive_failures >= 2:
        if any(pattern in error_str for pattern in POSSIBLY_DEAD_PATTERNS):
            return True
    
    return False


def is_context_length_error(error: Exception) -> bool:
    """
    Check if an error indicates context length exceeded.
    
    These errors are DETERMINISTIC - the same conversation will always exceed
    the context limit. Retrying or switching containers won't help.
    Fail fast and mark as context error.
    
    Args:
        error: The exception that was raised
    
    Returns:
        True if this is a context length error, False otherwise
    """
    error_str = str(error).lower()
    return any(pattern in error_str for pattern in CONTEXT_LENGTH_PATTERNS)


# === Helper Classes for Retry Dispatcher ===


@dataclass
class TrajectoryContext:
    """Context for tracking a trajectory's execution state."""
    batch_idx: int
    trajectory_id: int
    current_env_id: int
    containers_tried: List[int] = field(default_factory=list)
    failure_history: List[Dict[str, Any]] = field(default_factory=list)
    container_switches: int = 0
    success: bool = False
    
    def __post_init__(self):
        if self.current_env_id not in self.containers_tried:
            self.containers_tried.append(self.current_env_id)
    
    def record_failure(
        self, 
        attempt: int, 
        error: Exception, 
        is_dead: bool, 
        is_context_error: bool
    ) -> Dict[str, Any]:
        """Record a failure in the history and return the error info."""
        error_info = {
            "attempt": attempt,
            "container_switch": self.container_switches,
            "env_id": self.current_env_id,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "is_dead_container": is_dead,
            "is_context_error": is_context_error,
        }
        self.failure_history.append(error_info)
        return error_info
    
    def switch_to_container(self, new_env_id: int) -> None:
        """Switch to a new container."""
        self.container_switches += 1
        self.current_env_id = new_env_id
        if new_env_id not in self.containers_tried:
            self.containers_tried.append(new_env_id)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = DEFAULT_MAX_RETRIES
    max_container_switches: int = DEFAULT_MAX_CONTAINER_SWITCHES
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY
    container_switch_delay: float = DEFAULT_CONTAINER_SWITCH_DELAY
    num_envs: int = 0
    
    # Callbacks
    on_retry_success: Optional[Callable] = None
    on_retry_failure: Optional[Callable] = None
    mark_container_unhealthy: Optional[Callable] = None
    quick_ping: Optional[Callable] = None
    get_backup_container: Optional[Callable] = None

    @classmethod
    def from_cfg(cls, cfg: Dict[str, Any], num_envs: int) -> "RetryConfig":
        """Create RetryConfig from a configuration dictionary."""
        return cls(
            max_retries=cfg.get("max_retries", DEFAULT_MAX_RETRIES),
            max_container_switches=cfg.get("max_container_switches", DEFAULT_MAX_CONTAINER_SWITCHES),
            retry_base_delay=cfg.get("retry_base_delay", DEFAULT_RETRY_BASE_DELAY),
            container_switch_delay=cfg.get("container_switch_delay", DEFAULT_CONTAINER_SWITCH_DELAY),
            num_envs=num_envs,
            on_retry_success=cfg.get("on_retry_success"),
            on_retry_failure=cfg.get("on_retry_failure"),
            mark_container_unhealthy=cfg.get("mark_container_unhealthy"),
            quick_ping=cfg.get("quick_ping"),
            get_backup_container=cfg.get("get_backup_container"),
        )


# === Helper Functions for Retry Dispatcher ===


async def _pre_check_container(
    ctx: TrajectoryContext,
    retry_cfg: RetryConfig,
    env_queue: asyncio.Queue,
) -> int:
    """
    Ensure we get a healthy container before starting trajectory execution.
    
    Performs quick health checks and switches containers if unhealthy.
    
    Args:
        ctx: The trajectory context
        retry_cfg: Retry configuration with callbacks
        env_queue: Queue of available environment IDs
    
    Returns:
        The healthy env_id to use
    """
    if not retry_cfg.quick_ping:
        return ctx.current_env_id
    
    max_pre_check_attempts = retry_cfg.num_envs
    
    for _ in range(max_pre_check_attempts):
        # Try quick health check
        try:
            is_healthy = await retry_cfg.quick_ping(ctx.current_env_id)
        except Exception as e:
            logger.debug(
                f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) pre-check exception "
                f"for env{ctx.current_env_id}: {e}"
            )
            is_healthy = False
        
        if is_healthy:
            return ctx.current_env_id
        
        # Container is unhealthy - mark it and get another
        logger.warning(
            f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) pre-check failed "
            f"for env{ctx.current_env_id}, trying another container"
        )
        if retry_cfg.mark_container_unhealthy:
            await retry_cfg.mark_container_unhealthy(ctx.current_env_id)
        
        # DON'T put unhealthy container back in queue!
        # Try backup pool first (instant), then fall back to regular queue with timeout
        backup_env_id = None
        if retry_cfg.get_backup_container:
            backup_env_id = await retry_cfg.get_backup_container()
        
        if backup_env_id is not None:
            ctx.switch_to_container(backup_env_id)
            logger.info(
                f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) using backup env{backup_env_id}"
            )
        else:
            # Use timeout to prevent deadlock - if no container available, 
            # break out and let main execution loop handle the failure
            try:
                new_env_id = await asyncio.wait_for(env_queue.get(), timeout=30.0)
                ctx.switch_to_container(new_env_id)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) timed out waiting "
                    f"for container in pre-check, proceeding with current env{ctx.current_env_id}"
                )
                break  # Exit pre-check loop, let main loop handle
    
    # If we exhausted all pre-check attempts, log a warning but proceed
    # The main execution loop will handle failures
    logger.warning(
        f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) exhausted {max_pre_check_attempts} "
        f"pre-check attempts, proceeding with env{ctx.current_env_id}"
    )
    return ctx.current_env_id


async def _get_different_container(
    ctx: TrajectoryContext,
    env_queue: asyncio.Queue,
    num_envs: int,
    retry_cfg: Optional["RetryConfig"] = None,
) -> int:
    """
    Get a container we haven't tried yet, or fall back to any available.
    
    Drains the queue temporarily to find an untried container.
    Uses backup pool as fallback to prevent deadlock.
    
    Args:
        ctx: The trajectory context with containers_tried list
        env_queue: Queue of available environment IDs
        num_envs: Total number of environments
        retry_cfg: Retry config with backup pool access
    
    Returns:
        The new env_id to use
    """
    candidates = []
    new_env_id = None
    max_drain_attempts = num_envs * 2  # Avoid infinite loop
    
    for _ in range(max_drain_attempts):
        try:
            candidate = await asyncio.wait_for(env_queue.get(), timeout=QUEUE_DRAIN_TIMEOUT)
            
            if candidate not in ctx.containers_tried:
                # Found a container we haven't tried - use it
                new_env_id = candidate
                break
            else:
                # Already tried this one - save for later
                candidates.append(candidate)
        except asyncio.TimeoutError:
            # Queue is empty
            break
    
    # Put back all candidates we collected but didn't use
    for candidate in candidates:
        await env_queue.put(candidate)
    
    # If we couldn't find a new container, use any available
    if new_env_id is None:
        if candidates:
            # Fall back to a previously tried container
            new_env_id = candidates[0]
            logger.warning(
                f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) no untried containers available, "
                f"reusing env{new_env_id}"
            )
        else:
            # Try backup pool first to prevent deadlock
            if retry_cfg and retry_cfg.get_backup_container:
                backup_id = await retry_cfg.get_backup_container()
                if backup_id is not None:
                    logger.info(
                        f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) got backup container env{backup_id}"
                    )
                    return backup_id
            
            # Wait for any container with timeout to prevent permanent deadlock
            max_wait_time = 60.0  # Maximum wait before giving up
            wait_interval = 5.0
            total_waited = 0.0
            
            while total_waited < max_wait_time:
                try:
                    new_env_id = await asyncio.wait_for(env_queue.get(), timeout=wait_interval)
                    logger.warning(
                        f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) waited {total_waited:.0f}s for container, "
                        f"got env{new_env_id}"
                    )
                    break
                except asyncio.TimeoutError:
                    total_waited += wait_interval
                    # Check backup pool again
                    if retry_cfg and retry_cfg.get_backup_container:
                        backup_id = await retry_cfg.get_backup_container()
                        if backup_id is not None:
                            logger.info(
                                f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) got backup env{backup_id} after waiting {total_waited:.0f}s"
                            )
                            return backup_id
                    logger.debug(
                        f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) still waiting for container ({total_waited:.0f}s)..."
                    )
            
            if new_env_id is None:
                # Last resort - use any container from our tried list
                if ctx.containers_tried:
                    new_env_id = ctx.containers_tried[0]
                    logger.warning(
                        f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) timeout waiting for container, "
                        f"reusing env{new_env_id}"
                    )
                else:
                    # This shouldn't happen, but just in case
                    new_env_id = 0
                    logger.error(
                        f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) no container available, using env0 as fallback"
                    )
    
    return new_env_id


async def _execute_with_retries(
    ctx: TrajectoryContext,
    retry_cfg: RetryConfig,
    init_fn: Callable,
    run_fn: Callable,
    eval_fn: Callable,
) -> Tuple[bool, bool, bool]:
    """
    Execute trajectory with retries on the current container.
    
    Uses robust error detection to avoid unnecessary container switches:
    - DEFINITELY_DEAD patterns: Fast-fail immediately
    - POSSIBLY_DEAD patterns: Require 2+ consecutive failures
    - Other errors: Retry up to max_retries times
    
    Trade-off: A few extra seconds of retry is much cheaper than
    container switch (5-10s) + restart trajectory from beginning.
    
    Args:
        ctx: The trajectory context
        retry_cfg: Retry configuration
        init_fn: Initialization function
        run_fn: Run function
        eval_fn: Evaluation function
    
    Returns:
        Tuple of (success, container_dead, context_error)
    """
    container_dead = False
    context_error = False
    consecutive_connection_failures = 0  # Track for robust dead detection
    
    for attempt in range(retry_cfg.max_retries + 1):
        try:
            await init_fn(ctx.batch_idx, ctx.trajectory_id, ctx.current_env_id)
            await run_fn(ctx.batch_idx, ctx.trajectory_id, ctx.current_env_id)
            await eval_fn(ctx.batch_idx, ctx.trajectory_id, ctx.current_env_id)
            ctx.success = True
            return True, False, False
            
        except Exception as e:
            # Track consecutive connection-related failures for robust detection
            error_str = str(e).lower()
            if any(p in error_str for p in DEAD_CONTAINER_PATTERNS):
                consecutive_connection_failures += 1
            else:
                consecutive_connection_failures = 0  # Reset on different error type
            
            # Use consecutive failures for robust dead container detection
            # This prevents false positives from transient network issues
            is_dead = is_container_dead_error(e, consecutive_connection_failures)
            is_context = is_context_length_error(e)
            ctx.record_failure(attempt + 1, e, is_dead, is_context)
            
            # FAST-FAIL: Context length errors are DETERMINISTIC
            if is_context:
                logger.warning(
                    f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) hit context length limit "
                    f"on env{ctx.current_env_id}: {e}. This is deterministic - failing fast."
                )
                return False, False, True
            
            # FAST-FAIL: If container is confirmed dead (unambiguous or 2+ consecutive failures)
            if is_dead:
                logger.warning(
                    f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) detected dead container "
                    f"env{ctx.current_env_id} after {consecutive_connection_failures} consecutive "
                    f"connection failures: {e}. Switching container..."
                )
                return False, True, False
            
            if attempt < retry_cfg.max_retries:
                logger.warning(
                    f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) failed on env{ctx.current_env_id} "
                    f"(attempt {attempt+1}/{retry_cfg.max_retries+1}): {e}. "
                    f"Retrying in {retry_cfg.retry_base_delay}s..."
                )
                await asyncio.sleep(retry_cfg.retry_base_delay)
            else:
                logger.warning(
                    f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) exhausted retries "
                    f"on env{ctx.current_env_id} after {retry_cfg.max_retries+1} attempts"
                )
    
    return False, container_dead, context_error


async def _handle_container_switch(
    ctx: TrajectoryContext,
    retry_cfg: RetryConfig,
    env_queue: asyncio.Queue,
    container_dead: bool,
) -> bool:
    """
    Handle switching to a different container after failures.
    
    When max_container_switches is exceeded, instead of failing immediately,
    wait for a healthy container to become available (from RestartWorker).
    This ensures zero infrastructure failures.
    
    Args:
        ctx: The trajectory context
        retry_cfg: Retry configuration
        env_queue: Queue of available environment IDs
        container_dead: Whether the current container is dead
    
    Returns:
        True if switch was successful (always True - never gives up)
    """
    switches_exhausted = ctx.container_switches >= retry_cfg.max_container_switches
    
    # Mark dead container as unhealthy if callback provided
    if container_dead and retry_cfg.mark_container_unhealthy:
        try:
            await retry_cfg.mark_container_unhealthy(ctx.current_env_id)
            logger.info(
                f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) marked container "
                f"env{ctx.current_env_id} as UNHEALTHY"
            )
        except Exception as e:
            logger.warning(
                f"Failed to mark container env{ctx.current_env_id} as unhealthy: {e}"
            )
    
    # Release current container back to pool
    await env_queue.put(ctx.current_env_id)
    
    if switches_exhausted:
        # All switches exhausted - wait for a healthy container instead of failing
        logger.warning(
            f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) exhausted all {retry_cfg.max_container_switches} "
            f"container switches. Waiting for a healthy container from RestartWorker..."
        )
        # Wait longer to give RestartWorker time to recover containers
        await asyncio.sleep(retry_cfg.container_switch_delay * 2)
    elif not container_dead:
        logger.info(
            f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) switching container "
            f"(switch {ctx.container_switches + 1}/{retry_cfg.max_container_switches}). "
            f"Waiting {retry_cfg.container_switch_delay}s..."
        )
        await asyncio.sleep(retry_cfg.container_switch_delay)
    else:
        logger.info(
            f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) fast-switching container "
            f"(switch {ctx.container_switches + 1}/{retry_cfg.max_container_switches}, dead container)"
        )
    
    # Get a different container (will block until one is available)
    # Pass retry_cfg so backup pool can be used if queue is empty
    new_env_id = await _get_different_container(ctx, env_queue, retry_cfg.num_envs, retry_cfg)
    ctx.switch_to_container(new_env_id)
    
    if switches_exhausted:
        logger.info(
            f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) recovered! Now trying env{ctx.current_env_id} "
            f"(after waiting for healthy container)"
        )
    else:
        logger.info(
            f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) now trying env{ctx.current_env_id} "
            f"(fresh restart from beginning)"
        )
    
    return True


async def _record_trajectory_result(
    ctx: TrajectoryContext,
    retry_cfg: RetryConfig,
    env_queue: asyncio.Queue,
    work_queue: asyncio.Queue,
) -> None:
    """
    Record the final result of a trajectory execution.
    
    Args:
        ctx: The trajectory context
        retry_cfg: Retry configuration with callbacks
        env_queue: Queue to return the container to
        work_queue: Work queue to mark task as done
    """
    if ctx.success:
        if ctx.failure_history and retry_cfg.on_retry_success:
            await retry_cfg.on_retry_success(
                ctx.batch_idx, ctx.trajectory_id, len(ctx.failure_history), ctx.failure_history
            )
        if ctx.container_switches > 0:
            logger.info(
                f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) succeeded after "
                f"{ctx.container_switches} container switch(es) and {len(ctx.failure_history)} total attempts"
            )
    else:
        logger.error(
            f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) FAILED after "
            f"{ctx.container_switches} container switches and {len(ctx.failure_history)} total attempts. "
            f"Containers tried: {ctx.containers_tried}"
        )
        
        if retry_cfg.on_retry_failure:
            await retry_cfg.on_retry_failure(
                ctx.batch_idx, ctx.trajectory_id, len(ctx.failure_history),
                ctx.failure_history, ctx.failure_history[-1] if ctx.failure_history else None
            )
        # Note: Critical failure handling is done in the worker, not here
    
    work_queue.task_done()
    await env_queue.put(ctx.current_env_id)


def register_dispatcher(name):
    def decorator(fn):
        DISPATCHER_REGISTRY[name] = fn
        return fn

    return decorator


# Async Pipeline Dispatcher (Producer-Consumer Pipelining)
@register_dispatcher("async_pipeline")
async def async_pipeline_dispatcher(
    cfg, trajectories: Dict[str, Dict[str, Any]], init_fn: str, run_fn: str, eval_fn: str
):
    async def pipeline():
        """Pipeline dispatcher for async processing of init, run, and eval functions."""
        # Initialize queues
        init_queue = asyncio.Queue()
        run_queue = asyncio.Queue()
        eval_queue = asyncio.Queue()

        # Get the generator instance from the init function
        max_parallel_agents = cfg["max_parallel_agents"]
        max_eval_parallel_agents = cfg.get("max_eval_parallel_agents", max_parallel_agents)

        num_instances = cfg["num_instances"]
        num_trajectories = cfg["num_trajectories"]
        total_instances = num_instances

        max_eval_parallel_agents = min(total_instances * num_trajectories, max_eval_parallel_agents)
        max_parallel_agents = min(total_instances * num_trajectories, max_parallel_agents)

        logger.info(
            f"Using max_parallel_agents of {max_parallel_agents} for {total_instances} instances with {num_trajectories} trajectories each"
        )
        logger.info(
            f"Using max_eval_parallel_agents of {max_eval_parallel_agents} for {total_instances} instances with {num_trajectories} trajectories each"
        )

        # Fill the init queue with tasks
        for trajectory_id in range(num_trajectories):
            for instance_id in trajectories.keys():
                await init_queue.put((instance_id, trajectory_id))

        async def initialize_one():
            while True:
                instance_id, trajectory_id = await init_queue.get()
                await getattr(trajectories[instance_id][trajectory_id], init_fn)()
                await run_queue.put((instance_id, trajectory_id))
                init_queue.task_done()

        async def run_one():
            while True:
                instance_id, trajectory_id = await run_queue.get()
                await getattr(trajectories[instance_id][trajectory_id], run_fn)()
                await eval_queue.put((instance_id, trajectory_id))
                run_queue.task_done()

        async def eval_one():
            while True:
                instance_id, trajectory_id = await eval_queue.get()
                await getattr(trajectories[instance_id][trajectory_id], eval_fn)()
                eval_queue.task_done()

        # Create tasks for initialization, running and evaluation
        init_tasks = [asyncio.create_task(initialize_one()) for _ in range(max_parallel_agents)]
        run_tasks = [asyncio.create_task(run_one()) for _ in range(max_parallel_agents)]
        eval_tasks = [asyncio.create_task(eval_one()) for _ in range(max_eval_parallel_agents)]

        # Wait until all initialization tasks are done
        logger.info("Waiting for initialization tasks to complete...")
        await init_queue.join()
        for task in init_tasks:
            task.cancel()

        logger.info("Initialization tasks completed. Waiting for run tasks to complete...")
        # Wait until all running tasks are done
        await run_queue.join()
        for task in run_tasks:
            task.cancel()

        logger.info("Run tasks completed. Waiting for evaluation tasks to complete...")
        # Wait until all evaluation tasks are done
        await eval_queue.join()
        for task in eval_tasks:
            task.cancel()

    await pipeline()


# Async Batch Dispatcher
@register_dispatcher("async_batch")
async def async_batch_dispatcher(cfg, trajectories: Dict[int, Dict[int, Any]], init_fn: str, run_fn: str, eval_fn: str):
    async def run_all():
        tasks = []
        total_instances = cfg["num_instances"]
        num_trajectories = cfg["num_trajectories"]

        async def one_traj(instance_id, trajectory_id):
            traj = trajectories[instance_id][trajectory_id]
            if init_fn is not None:
                await getattr(traj, init_fn)()
            await getattr(traj, run_fn)()
            await getattr(traj, eval_fn)()

        for instance_id in trajectories.keys():
            for trajectory_id in range(num_trajectories):
                tasks.append(asyncio.create_task(one_traj(instance_id, trajectory_id)))

        await asyncio.gather(*tasks)

    await run_all()


# Async FixedEnv Pool Dispatcher (Env Pool Reuse)
@register_dispatcher("async_fix_pool")
async def async_fix_pool_dispatcher(cfg, init_fn, run_fn, eval_fn):
    """
    Dispatcher for pre-initialized environments. Each trajectory is assigned
    to a free env. When finished, the env is returned to the pool.
    """

    async def dispatcher():
        envs = cfg["envs"]  # List of pre-initialized environments
        num_envs = len(envs)
        num_instances = cfg["num_instances"]
        num_trajectories = cfg["num_trajectories"]
        total_trajectories = num_instances * num_trajectories

        # Queue to keep track of available env_ids
        env_queue = asyncio.Queue()
        for env_id in range(num_envs):
            await env_queue.put(env_id)

        # Queue of all pending (batch_idx, trajectory_id)
        work_queue = asyncio.Queue()
        for trajectory_id in range(num_trajectories):
            for batch_idx in range(num_instances):
                await work_queue.put((batch_idx, trajectory_id))

        logger.info(f"FixedEnv dispatcher with {num_envs} envs for {total_trajectories} total trajectories.")

        async def worker():
            while True:
                try:
                    batch_idx, trajectory_id = await work_queue.get()
                    env_id = await env_queue.get()

                    # Reset and assign env
                    await init_fn(batch_idx, trajectory_id, env_id)

                    # Run and eval
                    await run_fn(batch_idx, trajectory_id, env_id)
                    await eval_fn(batch_idx, trajectory_id, env_id)

                    # Mark trajectory and env as done
                    work_queue.task_done()
                    await env_queue.put(env_id)
                except Exception as e:
                    logger.exception(f"Worker failed for ({batch_idx}, {trajectory_id}): {e}")
                    work_queue.task_done()
                    await env_queue.put(env_id)

        # Launch one worker per environment
        workers = [asyncio.create_task(worker()) for _ in range(num_envs)]

        logger.info("Waiting for all work to complete...")
        await work_queue.join()

        # Cancel all workers
        for worker_task in workers:
            worker_task.cancel()

    await dispatcher()


# Async FixedEnv Pool Dispatcher with Retry Logic and Container Switching
@register_dispatcher("async_fix_pool_retry")
async def async_fix_pool_retry_dispatcher(cfg, init_fn, run_fn, eval_fn):
    """
    Dispatcher with retry logic and container switching for pre-initialized environments.
    
    Two-level retry strategy:
    1. Retry on same container up to max_retries times
    2. If still failing, switch to a different container and restart from beginning
    3. Repeat up to max_container_switches times
    
    Config options:
    - max_retries: Retries per container (default: 3)
    - max_container_switches: Number of container switches allowed (default: 2)
    - retry_base_delay: Fixed delay between retries (default: 2.0s)
    - container_switch_delay: Delay before switching container (default: 10.0s)
    
    Callbacks:
    - on_retry_success(batch_idx, trajectory_id, retry_count, failure_history)
    - on_retry_failure(batch_idx, trajectory_id, retry_count, failure_history, final_error)
    - mark_container_unhealthy(env_id): Mark a container as unhealthy for background restart
    - quick_ping(env_id) -> bool: Quick health check before starting trajectory
    
    Fast-Fail Behavior:
    - Dead container errors (connection refused, etc.) skip remaining retries
    - Immediately switches to a different container
    - Marks dead container as UNHEALTHY via callback
    
    Pre-Check Behavior:
    - If quick_ping callback is provided, check container health before starting
    - Unhealthy containers are marked and skipped
    - Gets a different container and retries pre-check
    """

    async def dispatcher():
        envs = cfg["envs"]
        num_envs = len(envs)
        num_instances = cfg["num_instances"]
        num_trajectories = cfg["num_trajectories"]
        total_trajectories = num_instances * num_trajectories
        
        # Build retry configuration from cfg dict
        retry_cfg = RetryConfig.from_cfg(cfg, num_envs)

        # Initialize environment queue
        env_queue = asyncio.Queue()
        for env_id in range(num_envs):
            await env_queue.put(env_id)

        # Initialize work queue
        work_queue = asyncio.Queue()
        for trajectory_id in range(num_trajectories):
            for batch_idx in range(num_instances):
                await work_queue.put((batch_idx, trajectory_id))

        # Set up container recovery callback if provided
        on_container_recovered = cfg.get("on_container_recovered")
        if on_container_recovered:
            async def add_to_queue(env_id: int):
                await env_queue.put(env_id)
                logger.info(f"Container env{env_id} recovered, added back to work queue")
            on_container_recovered(add_to_queue)
        
        logger.info(
            f"FixedEnv dispatcher (retry+switch) with {num_envs} envs, "
            f"{total_trajectories} trajectories, max_retries={retry_cfg.max_retries}, "
            f"max_container_switches={retry_cfg.max_container_switches}, "
            f"retry_base_delay={retry_cfg.retry_base_delay}s"
        )

        # Track critical failures - any failure should stop the entire process
        critical_failure: List[str] = []
        failure_event = asyncio.Event()

        async def worker():
            while True:
                # Check if another worker had a critical failure
                if failure_event.is_set():
                    return
                
                batch_idx, trajectory_id = await work_queue.get()
                
                # Check again after getting work
                if failure_event.is_set():
                    work_queue.task_done()
                    return
                
                env_id = await env_queue.get()
                
                # Create trajectory context to track state
                ctx = TrajectoryContext(
                    batch_idx=batch_idx,
                    trajectory_id=trajectory_id,
                    current_env_id=env_id,
                )
                
                # Pre-check: ensure we get a healthy container before starting
                await _pre_check_container(ctx, retry_cfg, env_queue)

                # Main execution loop with container switching
                # Loop continues until success or non-recoverable error (context length)
                # Has a maximum iteration limit to prevent infinite loops
                MAX_TOTAL_ATTEMPTS = retry_cfg.num_envs * 3  # Try each container up to 3 times
                total_attempts = 0
                
                while not ctx.success and total_attempts < MAX_TOTAL_ATTEMPTS:
                    total_attempts += 1
                    
                    # Execute with retries on current container
                    success, container_dead, context_error = await _execute_with_retries(
                        ctx, retry_cfg, init_fn, run_fn, eval_fn
                    )
                    
                    if success:
                        break
                    
                    # Context errors are deterministic - no point switching containers
                    if context_error:
                        break
                    
                    # Check if we've exhausted all attempts
                    if total_attempts >= MAX_TOTAL_ATTEMPTS:
                        logger.error(
                            f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) exhausted "
                            f"all {MAX_TOTAL_ATTEMPTS} attempts across all containers"
                        )
                        break
                    
                    # Switch to another container (will wait for healthy one if all exhausted)
                    await _handle_container_switch(
                        ctx, retry_cfg, env_queue, container_dead
                    )
                
                # Record final result and check for critical failure
                # Context errors are acceptable (trajectory result exists with reward=0)
                # Infrastructure failures are NOT acceptable (no result, must kill process)
                is_context_error = (
                    ctx.failure_history and 
                    ctx.failure_history[-1].get('is_context_error', False)
                )
                
                if not ctx.success and not is_context_error:
                    # Infrastructure failure - signal to stop all workers
                    last_error = ctx.failure_history[-1]['error_message'] if ctx.failure_history else 'Unknown'
                    error_msg = (
                        f"Trajectory ({ctx.batch_idx}, {ctx.trajectory_id}) FAILED after "
                        f"{ctx.container_switches} switches, {len(ctx.failure_history)} attempts. "
                        f"Error: {last_error}"
                    )
                    critical_failure.append(error_msg)
                    failure_event.set()
                    logger.error(f"CRITICAL INFRASTRUCTURE FAILURE: {error_msg}")
                
                await _record_trajectory_result(ctx, retry_cfg, env_queue, work_queue)

        workers = [asyncio.create_task(worker()) for _ in range(num_envs)]
        await work_queue.join()
        for worker_task in workers:
            worker_task.cancel()
        
        # Check for critical failures after all work is done
        if critical_failure:
            error_summary = "\n".join(critical_failure)
            raise RuntimeError(
                f"CRITICAL: {len(critical_failure)} trajectory(s) failed. "
                f"All test instances must have results.\n{error_summary}"
            )

    await dispatcher()


# =============================================================================
# Async FixedEnv Pool Dispatcher for AndroidWorld (using ContainerManager)
# =============================================================================

@register_dispatcher("async_fix_pool_android")
async def async_fix_pool_android_dispatcher(cfg, init_fn, run_fn, eval_fn):
    """
    AndroidWorld dispatcher using ContainerManager's allocate/release pattern.
    
    This dispatcher delegates all container health management, failover, and
    replacement to ContainerManager. It does NOT implement retry logic itself -
    ContainerManager handles:
    - Health checks before allocation
    - Unhealthy container detection on release
    - Automatic container replacement via backup pool
    - Background health monitoring
    
    Config parameters:
        container_manager: ContainerManager instance (required)
        num_instances: Number of task instances
        num_trajectories: Number of trajectories per instance
        num_workers: Number of parallel workers (default: pool size)
        on_trajectory_complete: Optional callback(batch_idx, traj_id, success, error)
        val_mode: Boolean indicating evaluation mode (default: False)
        max_container_retries: Max retries per trajectory on container failure (default: 3)
    
    Note: This dispatcher passes ContainerInstance directly to init_fn/run_fn/eval_fn
    instead of just env_id. This simplifies the design by avoiding mappings.
    
    Error handling:
        - ContainerDeadError: 
            - Evaluation mode: Re-queue trajectory for retry (up to max_container_retries)
            - Training mode: Mark as failed, continue (throughput > completeness)
        - Other exceptions: Release with success=False, error logged (no retry)
    """
    from skyrl_agent.runtime.android.exceptions import ContainerDeadError
    from collections import defaultdict
    
    async def dispatcher():
        container_manager = cfg["container_manager"]
        num_instances = cfg["num_instances"]
        num_trajectories = cfg["num_trajectories"]
        num_workers = cfg.get("num_workers", len(container_manager.containers))
        on_trajectory_complete = cfg.get("on_trajectory_complete")
        
        # Mode detection: evaluation vs training
        # In evaluation mode, we retry failed trajectories to ensure complete metrics
        # In training mode, we skip failed trajectories to maximize throughput
        val_mode = cfg.get("val_mode", False)
        max_container_retries = cfg.get("max_container_retries", 3)
        
        total_trajectories = num_instances * num_trajectories
        
        # Track retry counts per trajectory (only used in val_mode)
        trajectory_retries: dict[tuple[int, int], int] = defaultdict(int)
        
        # Queue of all pending (batch_idx, trajectory_id)
        work_queue = asyncio.Queue()
        for trajectory_id in range(num_trajectories):
            for batch_idx in range(num_instances):
                await work_queue.put((batch_idx, trajectory_id))
        
        mode_str = "EVALUATION (retry on container failure)" if val_mode else "TRAINING (skip on container failure)"
        logger.info(
            f"[async_fix_pool_android] Starting dispatch: "
            f"{num_instances} instances x {num_trajectories} trajectories = {total_trajectories} total, "
            f"{num_workers} workers, {len(container_manager.containers)} containers, "
            f"mode={mode_str}"
        )
        
        async def worker():
            while True:
                batch_idx, trajectory_id = await work_queue.get()
                container = None
                success = False
                error_msg = None
                should_requeue = False
                
                try:
                    # Acquire container (blocks until healthy container available)
                    container = await container_manager.allocate_container(batch_idx, trajectory_id)
                    
                    # Pass container directly to trajectory functions
                    # Runner creates RuntimeClient from container in init_fn
                    await init_fn(batch_idx, trajectory_id, container)
                    await run_fn(batch_idx, trajectory_id, container)
                    await eval_fn(batch_idx, trajectory_id, container)
                    
                    success = True
                    # Clear retry count on success
                    if (batch_idx, trajectory_id) in trajectory_retries:
                        del trajectory_retries[(batch_idx, trajectory_id)]
                    
                except ContainerDeadError as e:
                    # Container is dead - this is an INFRA error, not task error
                    error_msg = f"container_dead: {e}"
                    retry_count = trajectory_retries[(batch_idx, trajectory_id)]
                    
                    if val_mode:
                        # EVALUATION MODE: Re-queue for retry (completeness matters)
                        if retry_count < max_container_retries:
                            trajectory_retries[(batch_idx, trajectory_id)] += 1
                            should_requeue = True
                            logger.warning(
                                f"[async_fix_pool_android] Container dead for trajectory "
                                f"({batch_idx}, {trajectory_id}), retry {retry_count + 1}/{max_container_retries}: {e}"
                            )
                        else:
                            logger.error(
                                f"[async_fix_pool_android] Trajectory ({batch_idx}, {trajectory_id}) "
                                f"FAILED after {max_container_retries} container retries: {e}"
                            )
                    else:
                        # TRAINING MODE: Skip and continue (throughput matters)
                        logger.warning(
                            f"[async_fix_pool_android] Container dead for trajectory "
                            f"({batch_idx}, {trajectory_id}), skipping (training mode): {e}"
                        )
                    
                except Exception as e:
                    # APPLICATION ERROR - don't retry, this is a task-level bug
                    error_msg = str(e)
                    logger.exception(
                        f"[async_fix_pool_android] Application error in trajectory "
                        f"({batch_idx}, {trajectory_id}): {e}"
                    )
                    
                finally:
                    # Release container first (if we acquired one)
                    if container is not None:
                        await container_manager.release_container(
                            container, 
                            success=success, 
                            error=error_msg
                        )
                    
                    # Re-queue BEFORE task_done() if needed (val_mode retry)
                    if should_requeue:
                        await work_queue.put((batch_idx, trajectory_id))
                    
                    # Notify completion callback (only if not re-queuing)
                    if not should_requeue and on_trajectory_complete:
                        try:
                            result = on_trajectory_complete(batch_idx, trajectory_id, success, error_msg)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as cb_error:
                            logger.warning(f"on_trajectory_complete callback error: {cb_error}")
                    
                    work_queue.task_done()
        
        # Launch workers
        workers = [asyncio.create_task(worker()) for _ in range(num_workers)]
        
        logger.info("[async_fix_pool_android] Waiting for all work to complete...")
        await work_queue.join()
        
        # Cancel all workers
        for worker_task in workers:
            worker_task.cancel()
        
        # Log final status with retry info
        status = container_manager.get_pool_status()
        total_retries = sum(trajectory_retries.values())
        logger.info(
            f"[async_fix_pool_android] Dispatch complete. "
            f"Pool status: {status['healthy']} healthy, {status['unhealthy']} unhealthy, "
            f"{status['failed_trajectories']} failed trajectories, "
            f"container retries: {total_retries}"
        )
    
    await dispatcher()
