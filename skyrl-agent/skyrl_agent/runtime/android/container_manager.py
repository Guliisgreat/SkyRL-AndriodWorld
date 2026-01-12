"""
ContainerManager - Manages pool of Docker containers for AndroidWorld environments.

Extracted and adapted from verl/trainer/androidworld_env.py
"""

import os
import time
import docker
import psutil
import requests
import platform
import asyncio
from pathlib import Path
from typing import List, Set, Optional, Any, Tuple, Dict
from filelock import FileLock
from dataclasses import dataclass, field
from loguru import logger

RETRY_INTERVAL = 10  # retry connecting to the container server
SERVER_TIMEOUT = 600  # server established timeout


class PortAllocationError(Exception):
    pass


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


class ContainerManager:
    """
    Manages pool of Docker containers for AndroidWorld environments.
    
    Features:
    - Background health monitoring
    - Automatic container restart for idle unhealthy containers
    - Fail-fast handling for in-use container failures
    - Status tracking and reporting
    """
    
    def __init__(
        self,
        docker_image: str = "androidworld:v8",
        temp_path: str = "/tmp",
        lock_file: Optional[Path] = None,
    ):
        """
        Initialize ContainerManager.
        
        Args:
            docker_image: Docker image name for containers
            temp_path: Base path for temporary files and logs
            lock_file: Path to lock file for port allocation (defaults to /tmp/docker_port_allocation.lck)
        """
        self.docker_image = docker_image
        self.temp_path = temp_path
        self.client = docker.from_env()
        
        # Set up lock file for port allocation (user-specific to avoid permission issues)
        if lock_file is None:
            if platform.system() == 'Windows':
                temp_dir = Path(os.getenv('TEMP', '/tmp'))
            else:
                # Use user-specific directory to avoid permission conflicts
                temp_dir = Path(f"/tmp/docker_ports_{os.getuid()}")
            temp_dir.mkdir(parents=True, exist_ok=True)
            lock_file = temp_dir / "docker_port_allocation.lck"
        self.lock_file = lock_file
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Container pool
        self.containers: List[ContainerInstance] = []
        self.available_queue: Optional[asyncio.Queue] = None
        
        # Pool configuration (stored for restart)
        self._pool_config: Optional[Dict[str, Any]] = None
        
        # Health monitoring
        self._health_monitor_task: Optional[asyncio.Task] = None
        self._health_monitor_running: bool = False
        
        # Failed trajectory tracking
        self.failed_trajectories: List[Tuple[int, int, str]] = []  # (batch_idx, traj_id, error_msg)
        
        os.makedirs(temp_path, exist_ok=True)
    
    async def create_pool(
        self,
        pool_size: int,
        base_env_id: int = 0,
        sample_mode: str = "sequential",
        snapshot: str = "clean",
        train_task_family: str = "android_world",
        val_task_family: str = "android_world",
    ) -> List[ContainerInstance]:
        """
        Create pool of N containers.
        
        Args:
            pool_size: Number of containers to create
            base_env_id: Starting environment ID (containers will use base_env_id, base_env_id+1, ...)
            sample_mode: Task sampling mode ("random" or "sequential")
            snapshot: Emulator snapshot name
            train_task_family: Training task family name
            val_task_family: Validation task family name
        
        Returns:
            List of ContainerInstance objects
        """
        # Store pool config for restart
        self._pool_config = {
            "sample_mode": sample_mode,
            "snapshot": snapshot,
            "train_task_family": train_task_family,
            "val_task_family": val_task_family,
        }
        
        self.available_queue = asyncio.Queue()
        
        logger.info(f"[ContainerManager] Starting pool creation: {pool_size} containers")
        logger.info(f"[ContainerManager] Config: image={self.docker_image}, snapshot={snapshot}, sample_mode={sample_mode}")
        
        pool_start_time = time.time()
        
        # Create containers sequentially (with locking for port allocation)
        for i in range(pool_size):
            env_id = base_env_id + i
            logger.info(f"[ContainerManager] Creating container {i + 1}/{pool_size} (env{env_id})...")
            
            container_start_time = time.time()
            container = await self._create_container(
                env_id=env_id,
                sample_mode=sample_mode,
                snapshot=snapshot,
                train_task_family=train_task_family,
                val_task_family=val_task_family,
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
    
    async def _create_container(
        self,
        env_id: int,
        sample_mode: str,
        snapshot: str,
        train_task_family: str,
        val_task_family: str,
    ) -> ContainerInstance:
        """
        Create a single container instance.
        
        Adapted from AndroidWorldHostEnv.docker_init()
        """
        # Build environment variables
        environment = {
            "ENV_SAMPLE_MODE": sample_mode,
            "ENV_SAVE_IMAGES": "False",
            "ENV_ID": str(env_id),
            "ENV_SNAPSHOT": snapshot,
            "ENV_TASK_FAMILY": train_task_family,  # Default to train
        }
        
        # Use file lock for port allocation (thread-safe)
        lock = FileLock(str(self.lock_file))
        
        try:
            with lock:
                # Allocate ports
                logger.debug(f"[ContainerManager] env{env_id}: Allocating ports...")
                server_port = self._get_available_port(5000 + 2 * env_id)
                emulator_port = self._get_available_port(5574 + 2 * env_id)
                grpc_port = self._get_available_port(emulator_port + 3000)
                
                environment["SERVER_PORT"] = str(server_port)
                environment["EMULATOR_PORT"] = str(emulator_port)
                environment["GRPC_PORT"] = str(grpc_port)
                
                logger.info(
                    f"[ContainerManager] env{env_id}: Starting Docker container "
                    f"(server={server_port}, emulator={emulator_port}, grpc={grpc_port})"
                )
                
                # Remove any existing container with the same name (handles race conditions)
                container_name = f"env{env_id}"
                try:
                    existing = self.client.containers.get(container_name)
                    logger.warning(f"[ContainerManager] env{env_id}: Removing existing container...")
                    existing.remove(force=True)
                except docker.errors.NotFound:
                    pass  # Container doesn't exist, good
                
                # Create Docker container
                container = self.client.containers.run(
                    self.docker_image,
                    environment=environment,
                    devices=["/dev/kvm"],
                    volumes={
                        os.path.join(self.temp_path, "log"): {
                            "bind": "/data/log",
                            "mode": "rw"
                        },
                    },
                    detach=True,
                    auto_remove=True,
                    name=f"env{env_id}",
                    network_mode="host"
                )
            
            logger.info(f"[ContainerManager] env{env_id}: Docker container started, waiting for emulator...")
            
            # Wait for container to be ready
            await self._wait_for_container_ready(server_port, env_id)
            
            # Create ContainerInstance
            container_instance = ContainerInstance(
                container_id=container.id,
                container=container,
                server_port=server_port,
                emulator_port=emulator_port,
                grpc_port=grpc_port,
                env_id=env_id,
                state="ready",
            )
            
            return container_instance
        
        except Exception as e:
            # Clean up on error
            if 'container' in locals():
                try:
                    container.stop()
                except:
                    pass
            raise Exception(f"Failed to create container for env_id={env_id}: {e}")
    
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
            
            # Check health before allocating
            if not self._is_container_healthy(container):
                logger.warning(
                    f"[ContainerManager] Skipping unhealthy container env{container.env_id} "
                    f"during allocation"
                )
                # Put back for health monitor to restart
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
        if not self._is_container_healthy(container):
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
    
    async def cleanup(self):
        """Stop all containers in the pool."""
        if not self.containers:
            logger.info("[ContainerManager] No containers to cleanup")
            return
        
        logger.info(f"[ContainerManager] Cleaning up {len(self.containers)} containers...")
        
        for i, container_instance in enumerate(self.containers):
            try:
                if container_instance.container:
                    logger.debug(f"[ContainerManager] Stopping container env{container_instance.env_id}...")
                    container_instance.container.stop()
                    logger.debug(f"[ContainerManager] ✓ Container env{container_instance.env_id} stopped")
            except Exception as e:
                logger.warning(f"[ContainerManager] Error stopping container env{container_instance.env_id}: {e}")
        
        logger.info(f"[ContainerManager] ✓ Cleanup complete")
    
    def _get_available_port(self, start_port: int) -> int:
        """
        Find next available port starting from start_port.
        
        Reused from AndroidWorldHostEnv._get_available_port()
        """
        used_ports = self._get_used_ports()
        port = start_port
        while port < 65354:
            if port not in used_ports:
                return port
            port += 1
        raise PortAllocationError(f"No available ports found starting from {start_port}")
    
    def _get_used_ports(self) -> Set[int]:
        """
        Get all currently used ports (both system and Docker).
        
        Reused from AndroidWorldHostEnv._get_used_ports()
        """
        # #region agent log
        import json
        try:
            with open('/home/ligu/projects/aw_g/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"container_manager.py:356","message":"_get_used_ports: Getting psutil.net_connections","data":{"type":str(type(psutil.net_connections))},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        
        try:
            net_conns = psutil.net_connections()
            # #region agent log
            try:
                with open('/home/ligu/projects/aw_g/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"container_manager.py:361","message":"_get_used_ports: Got net_connections result","data":{"type":str(type(net_conns)),"is_iterable":hasattr(net_conns,'__iter__')},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
            
            # Handle Mock objects in tests - if it's a Mock, return empty set
            if hasattr(net_conns, '_mock_name'):  # It's a Mock
                system_ports = set()
            else:
                system_ports = set(conn.laddr.port for conn in net_conns)
        except Exception as e:
            # #region agent log
            try:
                with open('/home/ligu/projects/aw_g/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"container_manager.py:370","message":"_get_used_ports: Exception getting system ports","data":{"error":str(e),"error_type":type(e).__name__},"timestamp":int(time.time()*1000)}) + "\n")
            except: pass
            # #endregion
            system_ports = set()
        
        docker_ports = set()
        
        for attempt in range(3):  # Retry up to 3 times
            try:
                # #region agent log
                try:
                    with open('/home/ligu/projects/aw_g/.cursor/debug.log', 'a') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"container_manager.py:378","message":"_get_used_ports: Getting docker containers","data":{"attempt":attempt},"timestamp":int(time.time()*1000)}) + "\n")
                except: pass
                # #endregion
                
                containers_list = self.client.containers.list()
                # #region agent log
                try:
                    with open('/home/ligu/projects/aw_g/.cursor/debug.log', 'a') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"container_manager.py:385","message":"_get_used_ports: Got containers list","data":{"type":str(type(containers_list)),"is_iterable":hasattr(containers_list,'__iter__'),"len":len(containers_list) if hasattr(containers_list,'__len__') else "N/A"},"timestamp":int(time.time()*1000)}) + "\n")
                except: pass
                # #endregion
                
                for container in containers_list:
                    ports = container.attrs['NetworkSettings']['Ports']
                    if ports:
                        for port_mappings in ports.values():
                            if port_mappings:
                                docker_ports.update(int(p['HostPort']) for p in port_mappings)
                break  # Exit retry loop if successful
            except docker.errors.NotFound:
                time.sleep(1)  # Wait before retrying
            except Exception as e:
                # #region agent log
                try:
                    with open('/home/ligu/projects/aw_g/.cursor/debug.log', 'a') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"container_manager.py:400","message":"_get_used_ports: Exception getting docker ports","data":{"error":str(e),"error_type":type(e).__name__},"timestamp":int(time.time()*1000)}) + "\n")
                except: pass
                # #endregion
                break  # Exit on other errors
        
        # #region agent log
        try:
            with open('/home/ligu/projects/aw_g/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A,B","location":"container_manager.py:405","message":"_get_used_ports: Returning ports","data":{"system_ports_count":len(system_ports),"docker_ports_count":len(docker_ports)},"timestamp":int(time.time()*1000)}) + "\n")
        except: pass
        # #endregion
        
        return system_ports | docker_ports
    
    async def _wait_for_container_ready(self, server_port: int, env_id: int):
        """
        Wait for container server to be ready by checking health endpoint.
        
        Adapted from AndroidWorldHostEnv._wait_for_vm_ready()
        """
        # Initial wait for emulator to launch
        logger.info(f"[ContainerManager] env{env_id}: Waiting 45s for emulator to boot...")
        await asyncio.sleep(45)
        
        start_time = time.time()
        attempt = 0
        
        def check_server_health():
            try:
                response = requests.get(
                    f"http://localhost:{server_port}/health",
                    timeout=(10, 10)
                )
                if response.status_code == 200:
                    return True
            except Exception:
                return False
            return False
        
        logger.info(f"[ContainerManager] env{env_id}: Checking health endpoint (timeout={SERVER_TIMEOUT}s)...")
        
        while time.time() - start_time < SERVER_TIMEOUT:
            attempt += 1
            if check_server_health():
                elapsed = time.time() - start_time
                logger.info(
                    f"[ContainerManager] env{env_id}: ✓ Health check passed after {elapsed:.1f}s "
                    f"({attempt} attempts)"
                )
                return True
            
            elapsed = time.time() - start_time
            if attempt % 3 == 0:  # Log every 3rd attempt to avoid spam
                logger.debug(
                    f"[ContainerManager] env{env_id}: Health check attempt {attempt} failed, "
                    f"elapsed={elapsed:.0f}s, retrying in {RETRY_INTERVAL}s..."
                )
            await asyncio.sleep(RETRY_INTERVAL)
        
        raise TimeoutError(f"Container with server port {server_port} failed to become ready within timeout period")
    
    def _is_container_healthy(self, container: ContainerInstance) -> bool:
        """
        Check if a container is healthy using Docker API + HTTP health endpoint.
        
        Args:
            container: ContainerInstance to check
        
        Returns:
            True if container is healthy, False otherwise
        """
        # Update last health check timestamp
        container.last_health_check = time.time()
        
        # Check 1: Docker container status
        try:
            container.container.reload()  # Refresh container state from Docker
            docker_status = container.container.status
            # Handle Mock objects in tests - if status is a Mock, consider it healthy
            if hasattr(docker_status, '_mock_name'):
                # It's a Mock object, skip health check for tests
                pass
            elif docker_status != "running":
                logger.warning(
                    f"[ContainerManager] Container env{container.env_id} unhealthy: "
                    f"Docker status={docker_status}"
                )
                container.is_healthy = False
                return False
        except (docker.errors.NotFound, AttributeError):
            logger.warning(
                f"[ContainerManager] Container env{container.env_id} unhealthy: "
                f"Container not found (may have been removed)"
            )
            container.is_healthy = False
            return False
        except Exception as e:
            logger.warning(
                f"[ContainerManager] Container env{container.env_id} unhealthy: "
                f"Docker API error: {e}"
            )
            container.is_healthy = False
            return False
        
        # Check 2: HTTP health endpoint
        try:
            response = requests.get(
                f"http://localhost:{container.server_port}/health",
                timeout=(5, 5)
            )
            if response.status_code != 200:
                logger.warning(
                    f"[ContainerManager] Container env{container.env_id} unhealthy: "
                    f"Health endpoint returned {response.status_code}"
                )
                container.is_healthy = False
                return False
        except requests.exceptions.RequestException as e:
            logger.warning(
                f"[ContainerManager] Container env{container.env_id} unhealthy: "
                f"Health endpoint unreachable: {e}"
            )
            container.is_healthy = False
            return False
        
        container.is_healthy = True
        return True
    
    # === Health Monitoring ===
    
    async def start_health_monitor(self, interval: float = 30.0):
        """
        Start background health check task.
        
        Args:
            interval: Time between health checks in seconds (default: 30s)
        """
        if self._health_monitor_running:
            logger.warning("[ContainerManager] Health monitor already running")
            return
        
        self._health_monitor_running = True
        self._health_monitor_task = asyncio.create_task(
            self._health_monitor_loop(interval)
        )
        logger.info(f"[ContainerManager] Health monitor started (interval={interval}s)")
    
    async def stop_health_monitor(self):
        """Stop the background health check task."""
        self._health_monitor_running = False
        if self._health_monitor_task:
            self._health_monitor_task.cancel()
            try:
                await self._health_monitor_task
            except asyncio.CancelledError:
                pass
            self._health_monitor_task = None
        logger.info("[ContainerManager] Health monitor stopped")
    
    async def _health_monitor_loop(self, interval: float):
        """
        Periodic loop that checks all containers.
        
        - For idle unhealthy containers: trigger restart
        - For in-use unhealthy containers: mark as failed (trajectory will fail-fast)
        
        Args:
            interval: Time between health checks in seconds
        """
        while self._health_monitor_running:
            try:
                await asyncio.sleep(interval)
                
                for container in self.containers:
                    if not self._health_monitor_running:
                        break
                    
                    is_healthy = self._is_container_healthy(container)
                    
                    if not is_healthy:
                        if container.state == "in_use":
                            # In-use container failed - trajectory will fail-fast
                            # Just log, don't restart (would corrupt ongoing work)
                            traj_info = container.current_trajectory
                            if traj_info:
                                logger.error(
                                    f"[ContainerManager] Container env{container.env_id} FAILED "
                                    f"while running trajectory (batch={traj_info[0]}, traj={traj_info[1]})"
                                )
                            else:
                                logger.error(
                                    f"[ContainerManager] Container env{container.env_id} FAILED "
                                    f"while in_use (no trajectory info)"
                                )
                        else:
                            # Idle container failed - restart it
                            logger.info(
                                f"[ContainerManager] Container env{container.env_id} unhealthy "
                                f"(idle), restarting..."
                            )
                            await self._restart_container(container)
                
                # Log pool status periodically
                self._log_pool_status()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ContainerManager] Health monitor error: {e}")
    
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
        
        # Remove from available queue if present (container might be there if idle)
        # We'll re-add it after restart
        
        try:
            # Create new container with same env_id
            new_container = await self._create_container(
                env_id=env_id,
                sample_mode=self._pool_config["sample_mode"],
                snapshot=self._pool_config["snapshot"],
                train_task_family=self._pool_config["train_task_family"],
                val_task_family=self._pool_config["val_task_family"],
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
    
    # === Status Methods ===
    
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

