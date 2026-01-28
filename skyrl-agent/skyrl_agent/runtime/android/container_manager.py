"""
ContainerManager - Manages pool of Docker containers for AndroidWorld environments.

This module contains all components for container management:
- PortAllocator: Thread-safe port allocation
- ContainerFactory: Container creation and initialization  
- HealthMonitor: Background health monitoring
- ContainerManager: Main facade class

Extracted and adapted from verl/trainer/androidworld_env.py
"""

import os
import time
import platform
import asyncio
from pathlib import Path
from typing import List, Set, Optional, Any, Tuple, Dict, Callable
from dataclasses import dataclass, field

import docker
import psutil
import requests
from filelock import FileLock
from loguru import logger


# =============================================================================
# Constants
# =============================================================================

RETRY_INTERVAL = 10  # seconds between health check retries
SERVER_TIMEOUT = 600  # max seconds to wait for server to be ready


# =============================================================================
# Exceptions
# =============================================================================

class PortAllocationError(Exception):
    """Raised when no available ports can be found."""
    pass


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ContainerConfig:
    """Configuration for container creation."""
    sample_mode: str = "sequential"
    snapshot: str = "clean"
    train_task_family: str = "android_world"
    val_task_family: str = "android_world"
    initial_wait: float = 45.0


# Re-export for backward compatibility
__all__ = ["ContainerManager", "ContainerInstance", "PortAllocationError", "PortAllocator", "ContainerFactory", "HealthMonitor", "ContainerConfig"]


@dataclass
class ContainerInstance:
    """Represents a single Docker container instance."""
    container_id: str
    container: Any  # docker.models.containers.Container
    server_port: int
    emulator_port: int
    grpc_port: int
    env_id: int
    state: str  # "stopped", "starting", "ready", "in_use"
    # Health tracking fields
    last_health_check: float = field(default=0.0)
    is_healthy: bool = field(default=True)
    restart_count: int = field(default=0)
    current_trajectory: Optional[Tuple[int, int]] = field(default=None)  # (batch_idx, traj_id)


# =============================================================================
# PortAllocator
# =============================================================================

class PortAllocator:
    """
    Handles port allocation for Docker containers.
    
    Features:
    - Thread-safe port allocation using file locks
    - Detects used ports from both system and Docker
    - Supports pre-allocation for parallel container creation
    """
    
    def __init__(
        self,
        lock_file: Optional[Path] = None,
        docker_client: Optional[Any] = None,
    ):
        if lock_file is None:
            if platform.system() == 'Windows':
                temp_dir = Path(os.getenv('TEMP', '/tmp'))
            else:
                temp_dir = Path(f"/tmp/docker_ports_{os.getuid()}")
            temp_dir.mkdir(parents=True, exist_ok=True)
            lock_file = temp_dir / "docker_port_allocation.lck"
        
        self.lock_file = lock_file
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._docker_client = docker_client
    
    @property
    def docker_client(self) -> Any:
        if self._docker_client is None:
            self._docker_client = docker.from_env()
        return self._docker_client
    
    def allocate_port(self, start_port: int) -> int:
        used_ports = self.get_used_ports()
        port = start_port
        while port < 65354:
            if port not in used_ports:
                return port
            port += 1
        raise PortAllocationError(f"No available ports found starting from {start_port}")
    
    def get_used_ports(self) -> Set[int]:
        try:
            net_conns = psutil.net_connections()
            system_ports = set(conn.laddr.port for conn in net_conns)
        except Exception:
            system_ports = set()
        
        docker_ports = set()
        for attempt in range(3):
            try:
                containers_list = self.docker_client.containers.list()
                for container in containers_list:
                    ports = container.attrs['NetworkSettings']['Ports']
                    if ports:
                        for port_mappings in ports.values():
                            if port_mappings:
                                docker_ports.update(int(p['HostPort']) for p in port_mappings)
                break
            except docker.errors.NotFound:
                time.sleep(1)
            except Exception:
                break
        
        return system_ports | docker_ports
    
    def preallocate_ports(self, pool_size: int, base_env_id: int = 0) -> List[Tuple[int, int, int]]:
        lock = FileLock(str(self.lock_file))
        port_tuples = []
        allocated_ports: Set[int] = set()
        
        with lock:
            used_ports = self.get_used_ports()
            
            for i in range(pool_size):
                env_id = base_env_id + i
                
                server_port = 5000 + 2 * env_id
                while server_port in used_ports or server_port in allocated_ports:
                    server_port += 1
                allocated_ports.add(server_port)
                
                emulator_port = 5574 + 2 * env_id
                while emulator_port in used_ports or emulator_port in allocated_ports:
                    emulator_port += 1
                allocated_ports.add(emulator_port)
                
                grpc_port = emulator_port + 3000
                while grpc_port in used_ports or grpc_port in allocated_ports:
                    grpc_port += 1
                allocated_ports.add(grpc_port)
                
                port_tuples.append((server_port, emulator_port, grpc_port))
                logger.debug(
                    f"[PortAllocator] Pre-allocated ports for env{env_id}: "
                    f"server={server_port}, emulator={emulator_port}, grpc={grpc_port}"
                )
        
        return port_tuples


# =============================================================================
# ContainerFactory
# =============================================================================

class ContainerFactory:
    """Creates and initializes Docker containers for AndroidWorld environments."""
    
    def __init__(self, docker_image: str, temp_path: str, docker_client: Optional[Any] = None):
        self.docker_image = docker_image
        self.temp_path = temp_path
        self._docker_client = docker_client
        os.makedirs(temp_path, exist_ok=True)
    
    @property
    def docker_client(self) -> Any:
        if self._docker_client is None:
            self._docker_client = docker.from_env()
        return self._docker_client
    
    async def create(
        self, env_id: int, ports: Tuple[int, int, int], config: ContainerConfig, use_host_network: bool = False
    ) -> ContainerInstance:
        server_port, emulator_port, grpc_port = ports
        
        environment = {
            "ENV_SAMPLE_MODE": config.sample_mode, "ENV_SAVE_IMAGES": "False",
            "ENV_ID": str(env_id), "ENV_SNAPSHOT": config.snapshot,
            "ENV_TASK_FAMILY": config.train_task_family,
            "SERVER_PORT": str(server_port), "EMULATOR_PORT": str(emulator_port), "GRPC_PORT": str(grpc_port),
        }
        
        logger.info(f"[ContainerFactory] env{env_id}: Starting Docker container (server={server_port})")
        
        container_name = f"env{env_id}"
        self._remove_existing_container(container_name)
        
        try:
            if use_host_network:
                container = self._create_with_host_network(env_id, environment)
            else:
                container = self._create_with_port_mapping(env_id, ports, environment)
            
            logger.info(f"[ContainerFactory] env{env_id}: Container started, waiting for server...")
            await asyncio.sleep(config.initial_wait)
            await self.wait_for_ready(server_port, env_id)
            
            return ContainerInstance(
                container_id=container.id, container=container, server_port=server_port,
                emulator_port=emulator_port, grpc_port=grpc_port, env_id=env_id,
                state="ready", last_health_check=time.time(), is_healthy=True,
            )
        except Exception as e:
            if 'container' in locals():
                try: container.stop()
                except: pass
            raise Exception(f"Failed to create container for env_id={env_id}: {e}")
    
    def _create_with_host_network(self, env_id: int, environment: dict) -> Any:
        return self.docker_client.containers.run(
            self.docker_image, environment=environment,
            devices=["/dev/kvm"] if os.path.exists("/dev/kvm") else None,
            volumes={os.path.join(self.temp_path, "log"): {"bind": "/data/log", "mode": "rw"}},
            detach=True, auto_remove=True, name=f"env{env_id}", network_mode="host",
        )
    
    def _create_with_port_mapping(self, env_id: int, ports: Tuple[int, int, int], environment: dict) -> Any:
        server_port, emulator_port, grpc_port = ports
        log_dir = Path(self.temp_path) / f"env{env_id}"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        return self.docker_client.containers.run(
            self.docker_image, name=f"env{env_id}", detach=True, remove=True, privileged=True,
            environment=environment,
            ports={f"{server_port}/tcp": server_port, f"{emulator_port}/tcp": emulator_port, f"{grpc_port}/tcp": grpc_port},
            volumes={str(log_dir): {"bind": "/tmp/android_logs", "mode": "rw"}},
            devices=["/dev/kvm"] if os.path.exists("/dev/kvm") else None,
        )
    
    def _remove_existing_container(self, container_name: str) -> None:
        try:
            existing = self.docker_client.containers.get(container_name)
            logger.warning(f"[ContainerFactory] Removing existing container: {container_name}")
            existing.remove(force=True)
        except docker.errors.NotFound:
            pass
        except Exception as e:
            logger.warning(f"[ContainerFactory] Error removing container {container_name}: {e}")
    
    async def wait_for_ready(self, server_port: int, env_id: int, timeout: float = SERVER_TIMEOUT) -> bool:
        logger.info(f"[ContainerFactory] env{env_id}: Waiting 45s for emulator to boot...")
        await asyncio.sleep(45)
        
        start_time = time.time()
        attempt = 0
        
        while time.time() - start_time < timeout:
            attempt += 1
            if self._check_server_health(server_port):
                elapsed = time.time() - start_time
                logger.info(f"[ContainerFactory] env{env_id}: Health check passed after {elapsed:.1f}s")
                return True
            if attempt % 3 == 0:
                logger.debug(f"[ContainerFactory] env{env_id}: Health check attempt {attempt} failed")
            await asyncio.sleep(RETRY_INTERVAL)
        
        raise TimeoutError(f"Container with server port {server_port} failed to become ready within {timeout}s")
    
    def _check_server_health(self, server_port: int) -> bool:
        try:
            response = requests.get(f"http://localhost:{server_port}/health", timeout=(10, 10))
            return response.status_code == 200
        except Exception:
            return False


# =============================================================================
# HealthMonitor
# =============================================================================

class HealthMonitor:
    """Background health monitoring for Docker containers."""
    
    def __init__(
        self, containers: List[ContainerInstance],
        on_restart_needed: Optional[Callable[[ContainerInstance], Any]] = None,
        on_status_log: Optional[Callable[[], None]] = None,
    ):
        self.containers = containers
        self.on_restart_needed = on_restart_needed
        self.on_status_log = on_status_log
        self._monitor_task: Optional[asyncio.Task] = None
        self._running: bool = False
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    async def start(self, interval: float = 30.0) -> None:
        if self._running:
            logger.warning("[HealthMonitor] Already running")
            return
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))
        logger.info(f"[HealthMonitor] Started (interval={interval}s)")
    
    async def stop(self) -> None:
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try: await self._monitor_task
            except asyncio.CancelledError: pass
            self._monitor_task = None
        logger.info("[HealthMonitor] Stopped")
    
    def check_health(self, container: ContainerInstance) -> bool:
        container.last_health_check = time.time()
        if not self._check_docker_status(container):
            return False
        if not self._check_http_health(container):
            return False
        container.is_healthy = True
        return True
    
    def _check_docker_status(self, container: ContainerInstance) -> bool:
        try:
            container.container.reload()
            if container.container.status != "running":
                logger.warning(f"[HealthMonitor] Container env{container.env_id} unhealthy: Docker status={container.container.status}")
                container.is_healthy = False
                return False
        except docker.errors.NotFound:
            logger.warning(f"[HealthMonitor] Container env{container.env_id} unhealthy: Container not found")
            container.is_healthy = False
            return False
        except Exception as e:
            logger.warning(f"[HealthMonitor] Container env{container.env_id} unhealthy: {e}")
            container.is_healthy = False
            return False
        return True
    
    def _check_http_health(self, container: ContainerInstance) -> bool:
        try:
            response = requests.get(f"http://localhost:{container.server_port}/health", timeout=(5, 5))
            if response.status_code != 200:
                logger.warning(f"[HealthMonitor] Container env{container.env_id} unhealthy: HTTP {response.status_code}")
                container.is_healthy = False
                return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"[HealthMonitor] Container env{container.env_id} unhealthy: {e}")
            container.is_healthy = False
            return False
        return True
    
    async def _monitor_loop(self, interval: float) -> None:
        while self._running:
            try:
                await asyncio.sleep(interval)
                for container in self.containers:
                    if not self._running: break
                    is_healthy = self.check_health(container)
                    if not is_healthy:
                        await self._handle_unhealthy_container(container)
                if self.on_status_log: self.on_status_log()
            except asyncio.CancelledError: break
            except Exception as e: logger.error(f"[HealthMonitor] Error in monitor loop: {e}")
    
    async def _handle_unhealthy_container(self, container: ContainerInstance) -> None:
        if container.state == "in_use":
            traj_info = container.current_trajectory
            if traj_info:
                logger.error(f"[HealthMonitor] Container env{container.env_id} FAILED while running trajectory")
            else:
                logger.error(f"[HealthMonitor] Container env{container.env_id} FAILED while in_use")
        else:
            logger.info(f"[HealthMonitor] Container env{container.env_id} unhealthy (idle), requesting restart...")
            if self.on_restart_needed:
                try:
                    result = self.on_restart_needed(container)
                    if asyncio.iscoroutine(result): await result
                except Exception as e:
                    logger.error(f"[HealthMonitor] Restart callback failed for env{container.env_id}: {e}")


# =============================================================================
# ContainerManager (Main Facade)
# =============================================================================

class ContainerManager:
    """
    Manages pool of Docker containers for AndroidWorld environments.
    
    Features:
    - Background health monitoring
    - Automatic container restart for idle unhealthy containers
    - Fail-fast handling for in-use container failures
    - Status tracking and reporting
    
    Uses composition with:
    - PortAllocator: Thread-safe port allocation
    - ContainerFactory: Container creation and initialization
    - HealthMonitor: Background health checks
    """
    
    def __init__(
        self,
        docker_image: str = "androidworld:v8",
        temp_path: str = "/tmp",
        lock_file: Optional[Path] = None,
        # Optional DI for testing (underscore prefix signals internal use)
        _port_allocator: Optional[PortAllocator] = None,
        _container_factory: Optional[ContainerFactory] = None,
        _docker_client: Optional[Any] = None,
    ):
        """
        Initialize ContainerManager.
        
        Args:
            docker_image: Docker image name for containers
            temp_path: Base path for temporary files and logs
            lock_file: Path to lock file for port allocation (defaults to /tmp/docker_port_allocation.lck)
            _port_allocator: Optional PortAllocator for testing
            _container_factory: Optional ContainerFactory for testing
            _docker_client: Optional Docker client for testing
        """
        self.docker_image = docker_image
        self.temp_path = temp_path
        
        # Docker client (shared with components)
        self._docker_client = _docker_client
        
        # Set up lock file path
        if lock_file is None:
            import platform
            if platform.system() == 'Windows':
                temp_dir = Path(os.getenv('TEMP', '/tmp'))
            else:
                temp_dir = Path(f"/tmp/docker_ports_{os.getuid()}")
            temp_dir.mkdir(parents=True, exist_ok=True)
            lock_file = temp_dir / "docker_port_allocation.lck"
        self.lock_file = lock_file
        
        # Initialize components (allow DI for testing)
        self._port_allocator = _port_allocator or PortAllocator(
            lock_file=lock_file,
            docker_client=self.client,
        )
        self._factory = _container_factory or ContainerFactory(
            docker_image=docker_image,
            temp_path=temp_path,
            docker_client=self.client,
        )
        
        # Container pool
        self.containers: List[ContainerInstance] = []
        self._backup_containers: List[ContainerInstance] = []
        self.available_queue: Optional[asyncio.Queue] = None
        
        # Pool configuration (stored for restart)
        self._pool_config: Optional[Dict[str, Any]] = None
        
        # Health monitoring (created lazily after containers exist)
        self._health_monitor: Optional[HealthMonitor] = None
        self._health_monitor_task: Optional[asyncio.Task] = None
        self._health_monitor_running: bool = False
        
        # Recovery callback
        self._recovery_callback = None
        
        # Failed trajectory tracking
        self.failed_trajectories: List[Tuple[int, int, str]] = []  # (batch_idx, traj_id, error_msg)
        
        os.makedirs(temp_path, exist_ok=True)
    
    @property
    def client(self) -> Any:
        """Lazy initialization of Docker client."""
        if self._docker_client is None:
            self._docker_client = docker.from_env()
        return self._docker_client
    
    # =========================================================================
    # Pool Creation
    # =========================================================================
    
    async def create_pool(
        self,
        pool_size: int,
        base_env_id: int = 0,
        sample_mode: str = "sequential",
        snapshot: str = "clean",
        train_task_family: str = "android_world",
        val_task_family: str = "android_world",
        initial_wait: float = 45.0,
    ) -> List[ContainerInstance]:
        """
        Create pool of N containers sequentially.
        
        Args:
            pool_size: Number of containers to create
            base_env_id: Starting environment ID (containers will use base_env_id, base_env_id+1, ...)
            sample_mode: Task sampling mode ("random" or "sequential")
            snapshot: Emulator snapshot name
            train_task_family: Training task family name
            val_task_family: Validation task family name
            initial_wait: Initial wait time for emulator boot (seconds)
        
        Returns:
            List of ContainerInstance objects
        """
        # Store pool config for restart
        self._pool_config = {
            "sample_mode": sample_mode,
            "snapshot": snapshot,
            "train_task_family": train_task_family,
            "val_task_family": val_task_family,
            "initial_wait": initial_wait,
        }
        
        self.available_queue = asyncio.Queue()
        
        logger.info(f"[ContainerManager] Starting pool creation: {pool_size} containers")
        logger.info(f"[ContainerManager] Config: image={self.docker_image}, snapshot={snapshot}, sample_mode={sample_mode}")
        
        pool_start_time = time.time()
        config = ContainerConfig(
            sample_mode=sample_mode,
            snapshot=snapshot,
            train_task_family=train_task_family,
            val_task_family=val_task_family,
            initial_wait=initial_wait,
        )
        
        # Create containers sequentially
        for i in range(pool_size):
            env_id = base_env_id + i
            logger.info(f"[ContainerManager] Creating container {i + 1}/{pool_size} (env{env_id})...")
            
            container_start_time = time.time()
            
            # Allocate ports with lock
            ports = self._port_allocator.preallocate_ports(pool_size=1, base_env_id=env_id)[0]
            
            # Create container
            factory_instance = await self._factory.create(
                env_id=env_id,
                ports=ports,
                config=config,
                use_host_network=True,
            )
            
            # Convert to ContainerInstance (our dataclass)
            container = ContainerInstance(
                container_id=factory_instance.container_id,
                container=factory_instance.container,
                server_port=factory_instance.server_port,
                emulator_port=factory_instance.emulator_port,
                grpc_port=factory_instance.grpc_port,
                env_id=factory_instance.env_id,
                state=factory_instance.state,
                last_health_check=factory_instance.last_health_check,
                is_healthy=factory_instance.is_healthy,
            )
            
            container_elapsed = time.time() - container_start_time
            
            self.containers.append(container)
            await self.available_queue.put(container)
            
            logger.info(
                f"[ContainerManager] ✓ Container {i + 1}/{pool_size} ready "
                f"(env{env_id}, port={container.server_port}, took {container_elapsed:.1f}s)"
            )
        
        pool_elapsed = time.time() - pool_start_time
        logger.info(
            f"[ContainerManager] ✓ Pool creation complete: {pool_size} containers in {pool_elapsed:.1f}s"
        )
        return self.containers

    async def create_pool_parallel(
        self,
        pool_size: int,
        base_env_id: int = 0,
        max_concurrent: int = 4,
        initial_wait: float = 30.0,
        max_retries: int = 2,
        sample_mode: str = "sequential",
        snapshot: str = "clean",
        train_task_family: str = "android_world",
        val_task_family: str = "android_world",
        buffer_size: int = 0,
    ) -> List[ContainerInstance]:
        """
        Create pool of N containers with bounded parallel creation.
        
        This is faster than sequential creation for large pools.
        Uses semaphore to limit concurrent container creations.
        
        Args:
            pool_size: Number of containers to create
            base_env_id: Starting environment ID
            max_concurrent: Maximum concurrent container creations
            initial_wait: Initial wait time for emulator boot (seconds)
            max_retries: Max retries per container creation
            sample_mode: Task sampling mode ("random" or "sequential")
            snapshot: Emulator snapshot name
            train_task_family: Training task family name
            val_task_family: Validation task family name
            buffer_size: Number of additional buffer containers (hot standby)
        
        Returns:
            List of ContainerInstance objects (pool_size main + buffer_size backup)
        """
        # Store pool config for restart
        self._pool_config = {
            "sample_mode": sample_mode,
            "snapshot": snapshot,
            "train_task_family": train_task_family,
            "val_task_family": val_task_family,
            "initial_wait": initial_wait,
        }
        
        self.available_queue = asyncio.Queue()
        
        total_containers = pool_size + buffer_size
        logger.info(f"[ContainerManager] Starting parallel pool creation: {pool_size} main + {buffer_size} buffer containers")
        logger.info(f"[ContainerManager] Config: max_concurrent={max_concurrent}, initial_wait={initial_wait}s")
        
        pool_start_time = time.time()
        
        # Pre-allocate all ports atomically (with lock)
        port_tuples = self._port_allocator.preallocate_ports(
            pool_size=total_containers,
            base_env_id=base_env_id,
        )
        
        config = ContainerConfig(
            sample_mode=sample_mode,
            snapshot=snapshot,
            train_task_family=train_task_family,
            val_task_family=val_task_family,
            initial_wait=initial_wait,
        )
        
        # Create semaphore for bounded concurrency
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def create_with_semaphore(idx: int, env_id: int, ports: Tuple[int, int, int]) -> ContainerInstance:
            async with semaphore:
                for attempt in range(max_retries + 1):
                    try:
                        factory_instance = await self._factory.create(
                            env_id=env_id,
                            ports=ports,
                            config=config,
                            use_host_network=False,
                        )
                        
                        # Convert to ContainerInstance
                        container = ContainerInstance(
                            container_id=factory_instance.container_id,
                            container=factory_instance.container,
                            server_port=factory_instance.server_port,
                            emulator_port=factory_instance.emulator_port,
                            grpc_port=factory_instance.grpc_port,
                            env_id=factory_instance.env_id,
                            state=factory_instance.state,
                            last_health_check=factory_instance.last_health_check,
                            is_healthy=factory_instance.is_healthy,
                        )
                        
                        logger.info(
                            f"[ContainerManager] ✓ Container {idx + 1}/{total_containers} ready "
                            f"(env{env_id}, port={ports[0]})"
                        )
                        return container
                    except Exception as e:
                        if attempt < max_retries:
                            logger.warning(
                                f"[ContainerManager] Container {idx + 1} creation failed (attempt {attempt + 1}): {e}"
                            )
                            await asyncio.sleep(2.0)
                        else:
                            raise
        
        # Create all containers in parallel (bounded by semaphore)
        tasks = []
        for i in range(total_containers):
            env_id = base_env_id + i
            ports = port_tuples[i]
            tasks.append(create_with_semaphore(i, env_id, ports))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Separate successful containers and handle failures
        main_containers = []
        backup_containers = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[ContainerManager] Container {i} failed: {result}")
            else:
                if i < pool_size:
                    main_containers.append(result)
                    await self.available_queue.put(result)
                else:
                    backup_containers.append(result)
        
        self.containers = main_containers
        self._backup_containers = backup_containers
        
        pool_elapsed = time.time() - pool_start_time
        logger.info(
            f"[ContainerManager] ✓ Parallel pool creation complete: "
            f"{len(main_containers)} main + {len(backup_containers)} backup in {pool_elapsed:.1f}s"
        )
        return main_containers

    # =========================================================================
    # Container Allocation
    # =========================================================================
    
    async def allocate_container(
        self,
        batch_idx: Optional[int] = None,
        trajectory_id: Optional[int] = None,
    ) -> ContainerInstance:
        """
        Allocate an available container from the pool.
        
        Skips unhealthy containers and puts them back in the queue for restart.
        
        Args:
            batch_idx: Batch index for the trajectory (optional, for tracking)
            trajectory_id: Trajectory ID (optional, for tracking)
        
        Returns:
            ContainerInstance from available pool
        
        Raises:
            RuntimeError: If pool not initialized or no healthy containers available
        """
        if self.available_queue is None:
            raise RuntimeError("Container pool not initialized. Call create_pool() first.")
        
        max_attempts = len(self.containers)
        attempts = 0
        
        while attempts < max_attempts:
            container = await self.available_queue.get()
            attempts += 1
            
            # Check health before allocating (works with or without health monitor)
            if self._health_monitor:
                is_healthy = self._health_monitor.check_health(container)
            else:
                is_healthy = self._check_container_health(container)
            
            if not is_healthy:
                logger.warning(
                    f"[ContainerManager] Skipping unhealthy container env{container.env_id} "
                    f"during allocation"
                )
                # Put back in queue - will be skipped until healthy or restarted
                await self.available_queue.put(container)
                continue
            
            # Healthy container found
            container.state = "in_use"
            container.current_trajectory = (batch_idx, trajectory_id) if batch_idx is not None else None
            
            logger.debug(
                f"[ContainerManager] Allocated container env{container.env_id} "
                f"for trajectory (batch={batch_idx}, traj={trajectory_id})"
            )
            return container
        
        raise RuntimeError(
            f"No healthy containers available after {max_attempts} attempts"
        )
    
    async def release_container(
        self,
        container: ContainerInstance,
        success: bool = True,
        error: Optional[str] = None,
    ):
        """
        Release container back to pool (after resetting it).
        
        Args:
            container: ContainerInstance to release
            success: Whether the trajectory completed successfully
            error: Error message if trajectory failed
        """
        traj_info = container.current_trajectory
        
        # Track failed trajectories
        if not success and traj_info:
            error_msg = error or "Unknown error"
            self.failed_trajectories.append((traj_info[0], traj_info[1], error_msg))
            logger.error(
                f"[ContainerManager] Trajectory (batch={traj_info[0]}, traj={traj_info[1]}) "
                f"FAILED on env{container.env_id}: {error_msg}"
            )
        elif success and traj_info:
            logger.debug(
                f"[ContainerManager] Trajectory (batch={traj_info[0]}, traj={traj_info[1]}) "
                f"completed successfully on env{container.env_id}"
            )
        
        # Clear trajectory association
        container.current_trajectory = None
        
        # Check health before returning to pool
        if self._health_monitor and not self._health_monitor.check_health(container):
            logger.warning(
                f"[ContainerManager] Container env{container.env_id} unhealthy after release, "
                f"triggering restart"
            )
            container.state = "stopped"
            # Restart in background (don't block release)
            asyncio.create_task(self._restart_container(container))
            # Put back in queue - it will be skipped until healthy
            await self.available_queue.put(container)
        else:
            # Healthy - return to pool
            container.state = "ready"
            await self.available_queue.put(container)
    
    async def get_backup_container(self) -> Optional[int]:
        """
        Get a backup container from the hot standby pool.
        
        Returns:
            env_id of the backup container, or None if no backup available
        """
        if not self._backup_containers:
            return None
        
        backup = self._backup_containers.pop(0)
        self.containers.append(backup)
        await self.available_queue.put(backup)
        
        logger.info(f"[ContainerManager] Activated backup container env{backup.env_id}")
        return backup.env_id

    # =========================================================================
    # Health Monitoring
    # =========================================================================
    
    def _check_container_health(self, container: ContainerInstance) -> bool:
        """
        Check if a container is healthy using Docker status + HTTP health endpoint.
        
        This is a standalone check that works whether or not the health monitor is running.
        Used as a fallback when health monitor is not active.
        
        Note: This is a single-shot check. Retry logic is handled by quick_ping().
        
        Args:
            container: ContainerInstance to check
        
        Returns:
            True if container is healthy, False otherwise
        """
        container.last_health_check = time.time()
        
        # Check 1: Docker container status
        try:
            container.container.reload()
            if container.container.status != "running":
                logger.warning(
                    f"[ContainerManager] Container env{container.env_id} unhealthy: "
                    f"Docker status={container.container.status}"
                )
                container.is_healthy = False
                return False
        except docker.errors.NotFound:
            logger.warning(
                f"[ContainerManager] Container env{container.env_id} unhealthy: "
                f"Container not found"
            )
            container.is_healthy = False
            return False
        except Exception as e:
            # Docker API can have transient errors - log at debug level
            # Let quick_ping's retry logic handle this
            logger.debug(
                f"[ContainerManager] Container env{container.env_id} Docker API error: {e}"
            )
            # Don't immediately mark unhealthy - could be transient
            # Return False to trigger retry in quick_ping
            return False
        
        # Check 2: HTTP health endpoint with improved timeout handling
        # Use longer read timeout (10s) because emulator can be slow under load
        # The cost of a false positive (container switch: 45-120s) far exceeds
        # the cost of waiting a few extra seconds for a slow health check
        try:
            response = requests.get(
                f"http://localhost:{container.server_port}/health",
                timeout=(3, 10)  # 3s connect, 10s read (was 5s, 5s)
            )
            if response.status_code == 200:
                container.is_healthy = True
                return True
            elif response.status_code == 503:
                # Server temporarily unavailable - likely busy, not dead
                # Return False to trigger retry, but don't mark unhealthy
                logger.debug(
                    f"[ContainerManager] Container env{container.env_id} busy (503)"
                )
                return False
            else:
                # Other error codes - likely real problem
                logger.warning(
                    f"[ContainerManager] Container env{container.env_id} unhealthy: "
                    f"HTTP health returned {response.status_code}"
                )
                container.is_healthy = False
                return False
                
        except requests.exceptions.ConnectTimeout:
            # Can't even establish connection - likely dead
            logger.warning(
                f"[ContainerManager] Container env{container.env_id} connect timeout - likely dead"
            )
            container.is_healthy = False
            return False
            
        except requests.exceptions.ReadTimeout:
            # Connected but slow response - may just be busy
            # Return False to trigger retry, but don't mark unhealthy immediately
            logger.debug(
                f"[ContainerManager] Container env{container.env_id} read timeout - may be busy"
            )
            return False
            
        except requests.exceptions.ConnectionError as e:
            # Connection refused/reset - container not responding
            logger.warning(
                f"[ContainerManager] Container env{container.env_id} connection error: {e}"
            )
            container.is_healthy = False
            return False
            
        except Exception as e:
            # Unexpected error - log but don't fail hard
            logger.warning(
                f"[ContainerManager] Container env{container.env_id} unexpected error: {e}"
            )
            return False
    
    async def quick_ping(
        self, 
        env_id: int, 
        max_retries: int = 2, 
        retry_delay: float = 1.0
    ) -> bool:
        """
        Quick health check for a container with retry for transient failures.
        
        Uses retry logic because the cost of a false positive (unnecessary
        container switch: 45-120s) far exceeds the cost of extra retries (1-2s).
        
        Args:
            env_id: Container environment ID
            max_retries: Number of retries before declaring unhealthy (default: 2)
            retry_delay: Delay between retries in seconds (default: 1.0)
        
        Returns:
            True if container is healthy, False otherwise
        """
        container = next((c for c in self.containers if c.env_id == env_id), None)
        if container is None:
            logger.warning(f"[ContainerManager] quick_ping: env{env_id} not found")
            return False
        
        for attempt in range(max_retries + 1):
            if self._health_monitor:
                is_healthy = self._health_monitor.check_health(container)
            else:
                is_healthy = self._check_container_health(container)
            
            if is_healthy:
                if attempt > 0:
                    logger.info(
                        f"[ContainerManager] quick_ping env{env_id} recovered after "
                        f"{attempt} retry(s) - avoided unnecessary switch"
                    )
                return True
            
            if attempt < max_retries:
                logger.debug(
                    f"[ContainerManager] quick_ping env{env_id} failed "
                    f"(attempt {attempt+1}/{max_retries+1}), retrying in {retry_delay}s..."
                )
                await asyncio.sleep(retry_delay)
        
        logger.warning(
            f"[ContainerManager] quick_ping env{env_id} failed after "
            f"{max_retries+1} attempts - container likely dead"
        )
        return False

    async def mark_container_unhealthy_async(self, env_id: int) -> None:
        """
        Mark a container as unhealthy for background restart.
        
        Args:
            env_id: Environment ID of the container to mark
        """
        container = next((c for c in self.containers if c.env_id == env_id), None)
        if container:
            container.is_healthy = False
            logger.warning(f"[ContainerManager] Container env{env_id} marked as unhealthy")

    def set_recovery_callback(self, callback) -> None:
        """
        Set callback to be called when a container is recovered.
        
        Args:
            callback: Async function to call with (env_id) when container is recovered
        """
        self._recovery_callback = callback
    
    async def start_health_monitor(self, interval: float = 30.0):
        """
        Start background health check task.
        
        Args:
            interval: Time between health checks in seconds (default: 30s)
        """
        if self._health_monitor_running:
            logger.warning("[ContainerManager] Health monitor already running")
            return
        
        # Create health monitor with callbacks
        self._health_monitor = HealthMonitor(
            containers=self.containers,
            on_restart_needed=self._restart_container,
            on_status_log=self._log_pool_status,
        )
        
        self._health_monitor_running = True
        await self._health_monitor.start(interval)
        logger.info(f"[ContainerManager] Health monitor started (interval={interval}s)")
    
    async def stop_health_monitor(self):
        """Stop the background health check task."""
        self._health_monitor_running = False
        if self._health_monitor:
            await self._health_monitor.stop()
            self._health_monitor = None
        logger.info("[ContainerManager] Health monitor stopped")
    
    async def _restart_container(self, container: ContainerInstance):
        """
        Restart a failed container, preserving env_id and config.
        
        Args:
            container: ContainerInstance to restart
        """
        if self._pool_config is None:
            logger.error(
                f"[ContainerManager] Cannot restart container env{container.env_id}: "
                f"pool config not available"
            )
            return
        
        env_id = container.env_id
        old_restart_count = container.restart_count
        
        # Try to stop the old container if it still exists
        try:
            container.container.stop()
        except docker.errors.NotFound:
            pass  # Already removed
        except Exception as e:
            logger.warning(
                f"[ContainerManager] Error stopping old container env{env_id}: {e}"
            )
        
        try:
            config = ContainerConfig(
                sample_mode=self._pool_config["sample_mode"],
                snapshot=self._pool_config["snapshot"],
                train_task_family=self._pool_config["train_task_family"],
                val_task_family=self._pool_config["val_task_family"],
                initial_wait=self._pool_config.get("initial_wait", 45.0),
            )
            
            # Allocate new ports
            ports = self._port_allocator.preallocate_ports(pool_size=1, base_env_id=env_id)[0]
            
            # Create new container with same env_id
            new_container = await self._factory.create(
                env_id=env_id,
                ports=ports,
                config=config,
                use_host_network=True,
            )
            
            # Update the existing ContainerInstance in place
            container.container_id = new_container.container_id
            container.container = new_container.container
            container.server_port = new_container.server_port
            container.emulator_port = new_container.emulator_port
            container.grpc_port = new_container.grpc_port
            container.state = "ready"
            container.is_healthy = True
            container.restart_count = old_restart_count + 1
            container.current_trajectory = None
            container.last_health_check = time.time()
            
            logger.info(
                f"[ContainerManager] Container env{env_id} restarted successfully "
                f"(restart_count={container.restart_count})"
            )
            
        except Exception as e:
            logger.error(
                f"[ContainerManager] Failed to restart container env{env_id}: {e}"
            )
            container.is_healthy = False
            container.state = "stopped"
    
    # =========================================================================
    # Cleanup
    # =========================================================================
    
    async def cleanup(self):
        """Stop all containers in the pool."""
        if not self.containers:
            logger.info("[ContainerManager] No containers to cleanup")
            return
        
        logger.info(f"[ContainerManager] Cleaning up {len(self.containers)} containers...")
        
        for container_instance in self.containers:
            try:
                if container_instance.container:
                    logger.debug(f"[ContainerManager] Stopping container env{container_instance.env_id}...")
                    container_instance.container.stop()
                    logger.debug(f"[ContainerManager] ✓ Container env{container_instance.env_id} stopped")
            except Exception as e:
                logger.warning(f"[ContainerManager] Error stopping container env{container_instance.env_id}: {e}")
        
        logger.info(f"[ContainerManager] ✓ Cleanup complete")
    
    # =========================================================================
    # Status Methods
    # =========================================================================
    
    def get_pool_status(self) -> Dict[str, Any]:
        """
        Return health status of all containers.
        
        Returns:
            Dict with pool statistics and per-container details
        """
        healthy_count = sum(1 for c in self.containers if c.is_healthy)
        unhealthy_count = len(self.containers) - healthy_count
        in_use_count = sum(1 for c in self.containers if c.state == "in_use")
        idle_count = sum(1 for c in self.containers if c.state == "ready")
        
        container_details = []
        for c in self.containers:
            container_details.append({
                "env_id": c.env_id,
                "state": c.state,
                "is_healthy": c.is_healthy,
                "restart_count": c.restart_count,
                "current_trajectory": c.current_trajectory,
                "last_health_check": c.last_health_check,
                "server_port": c.server_port,
            })
        
        return {
            "total": len(self.containers),
            "healthy": healthy_count,
            "unhealthy": unhealthy_count,
            "in_use": in_use_count,
            "idle": idle_count,
            "failed_trajectories": len(self.failed_trajectories),
            "containers": container_details,
        }
    
    def _log_pool_status(self):
        """Log pool status summary."""
        status = self.get_pool_status()
        logger.info(
            f"[ContainerManager] Pool Status: "
            f"{status['healthy']} healthy, {status['unhealthy']} unhealthy, "
            f"{status['idle']} idle, {status['in_use']} in_use"
        )
    
    def get_failed_trajectories(self) -> List[Tuple[int, int, str]]:
        """
        Get list of failed trajectories.
        
        Returns:
            List of (batch_idx, traj_id, error_msg) tuples
        """
        return self.failed_trajectories.copy()
    
    def clear_failed_trajectories(self):
        """Clear the list of failed trajectories (e.g., after batch completion)."""
        self.failed_trajectories.clear()
    
    def print_batch_summary(self, total_trajectories: int):
        """
        Print summary at batch completion.
        
        Args:
            total_trajectories: Total number of trajectories in the batch
        """
        succeeded = total_trajectories - len(self.failed_trajectories)
        failed = len(self.failed_trajectories)
        
        logger.info(
            f"[ContainerManager] Batch complete: "
            f"{succeeded}/{total_trajectories} succeeded, {failed} failed"
        )
        
        if self.failed_trajectories:
            logger.info("[ContainerManager] Failed trajectories:")
            for batch_idx, traj_id, error_msg in self.failed_trajectories:
                logger.info(
                    f"  - (batch={batch_idx}, traj={traj_id}): {error_msg[:100]}"
                )
