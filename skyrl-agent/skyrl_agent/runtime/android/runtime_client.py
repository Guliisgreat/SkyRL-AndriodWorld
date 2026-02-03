"""
RuntimeClient - HTTP client for communicating with container's FastAPI server.

Provides the same interface as AndroidWorldHostEnv (reset, step methods)
to ensure compatibility with agent layer code.

Features step-level retry with fixed delay for transient failures.
"""

import asyncio
import base64
import logging
import numpy as np
import aiohttp
from enum import Enum
from typing import Dict, Any, Tuple, Optional
from .container_manager import ContainerInstance
from .exceptions import ContainerDeadError

logger = logging.getLogger(__name__)


class ErrorLayer(Enum):
    """Classification of error by layer in the system stack."""
    NETWORK = 1      # Connection errors, timeouts, DNS
    SERVER = 2       # HTTP 5xx, server crashes
    ENVIRONMENT = 3  # Env-level errors (screenshot, action)
    EMULATOR = 4     # Emulator crashed/frozen
    UNKNOWN = 5


class ErrorClassifier:
    """
    Classifies errors by layer for appropriate recovery strategy.
    
    Usage:
        layer = ErrorClassifier.classify(exception)
        strategy = ErrorClassifier.get_retry_strategy(layer)
    """
    
    @staticmethod
    def classify(error: Exception, response_body: dict = None) -> ErrorLayer:
        """
        Classify an error into the appropriate layer.
        
        Args:
            error: The exception that occurred
            response_body: Optional response body for additional context
        
        Returns:
            ErrorLayer indicating which layer the error originated from
        """
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        
        # Layer 1: Network errors
        network_indicators = [
            'connection', 'timeout', 'refused', 'reset', 'dns',
            'clientconnectorerror', 'serverdisconnected', 'clienterror'
        ]
        if any(x in error_str or x in error_type for x in network_indicators):
            return ErrorLayer.NETWORK
        
        # Layer 2: Server errors (HTTP 5xx)
        server_indicators = ['500', '502', '503', '504', 'server error', 'internal error']
        if any(x in error_str for x in server_indicators):
            return ErrorLayer.SERVER
        
        # Layer 3: Environment errors (check response body)
        if response_body:
            status = response_body.get('status', '')
            reason = response_body.get('reason', '')
            if status == 'degraded':
                return ErrorLayer.ENVIRONMENT
            if 'blank_screen' in reason or 'slow_response' in reason:
                return ErrorLayer.ENVIRONMENT
        
        # Layer 4: Emulator errors
        emulator_indicators = ['emulator', 'adb', 'grpc', 'screenshot', 'android']
        if any(x in error_str for x in emulator_indicators):
            return ErrorLayer.EMULATOR
        
        return ErrorLayer.UNKNOWN
    
    @staticmethod
    def get_retry_strategy(layer: ErrorLayer) -> dict:
        """
        Get retry parameters based on error layer.
        
        Different layers have different characteristics:
        - Network: Usually transient, quick retries
        - Server: May need time to recover
        - Environment: May need emulator restart (slow)
        - Emulator: Needs container-level intervention
        
        Args:
            layer: The error layer
        
        Returns:
            dict with max_retries, base_delay, max_delay
        """
        strategies = {
            ErrorLayer.NETWORK: {
                "max_retries": 3, 
                "base_delay": 2.0, 
                "max_delay": 10.0,
                "description": "Network transient - quick retries"
            },
            ErrorLayer.SERVER: {
                "max_retries": 3, 
                "base_delay": 5.0, 
                "max_delay": 30.0,
                "description": "Server error - medium retries"
            },
            ErrorLayer.ENVIRONMENT: {
                "max_retries": 2, 
                "base_delay": 10.0, 
                "max_delay": 30.0,
                "description": "Env error - allow internal recovery"
            },
            ErrorLayer.EMULATOR: {
                "max_retries": 2, 
                "base_delay": 30.0, 
                "max_delay": 60.0,
                "description": "Emulator error - needs restart time"
            },
            ErrorLayer.UNKNOWN: {
                "max_retries": 3, 
                "base_delay": 5.0, 
                "max_delay": 20.0,
                "description": "Unknown error - default strategy"
            },
        }
        return strategies.get(layer, strategies[ErrorLayer.UNKNOWN])
    
    @staticmethod
    def is_retryable(layer: ErrorLayer) -> bool:
        """
        Check if errors from this layer are generally retryable.
        
        Args:
            layer: The error layer
        
        Returns:
            True if errors from this layer should be retried
        """
        # All layers are retryable, but with different strategies
        return True
    
    @staticmethod
    def should_switch_container(layer: ErrorLayer, retry_count: int) -> bool:
        """
        Determine if we should switch to a different container.
        
        Args:
            layer: The error layer
            retry_count: Number of retries already attempted
        
        Returns:
            True if container switch is recommended
        """
        # For emulator errors, switch after 2 retries
        if layer == ErrorLayer.EMULATOR and retry_count >= 2:
            return True
        
        # For server errors, switch after 3 retries
        if layer == ErrorLayer.SERVER and retry_count >= 3:
            return True
        
        return False


class RuntimeClient:
    """
    HTTP client that replaces AndroidWorldHostEnv.
    
    Provides SAME interface as AndroidWorldHostEnv:
    - reset(payload) → (observation, info)
    - step(payload) → (observation, reward, terminated, truncated, info)
    
    This ensures agent layer code works without changes.
    
    Features step-level retry with fixed delay for transient failures.
    """
    
    # Step-level retry configuration
    STEP_MAX_RETRIES = 3  # Retry each request up to 3 times
    STEP_RETRY_BASE_DELAY = 5.0  # Fixed delay between retries (no exponential backoff)
    
    # HTTP timeout - allows for container internal recovery (emulator restart ~30-60s)
    HTTP_TIMEOUT = 120.0  # 2 minutes per request
    
    def __init__(self, container: ContainerInstance):
        """
        Initialize RuntimeClient.
        
        Args:
            container: ContainerInstance to connect to
        """
        self.container = container
        self.session: Optional[aiohttp.ClientSession] = None
    
    @property
    def base_url(self) -> str:
        """
        Get base URL dynamically from container.
        
        This ensures we use the current port after container restarts,
        since the port may change when a container is restarted.
        """
        return f"http://localhost:{self.container.server_port}"
    
    async def _ensure_session(self):
        """Ensure HTTP session is created."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
    
    async def reset(self, payload: Dict = None) -> Tuple[Dict, Dict]:
        """
        Reset environment (same interface as AndroidWorldHostEnv.reset).
        
        Includes step-level retry with fixed delay for transient failures.
        
        Args:
            payload: Dict with seed, options (same format as AndroidWorldHostEnv)
                   {
                       "seed": int,
                       "options": {
                           "task_id": int,
                           "go_home_on_reset": bool,
                           "epoch": int,
                           "mode": str,
                           "traj": int,
                           "total_traj": int
                       }
                   }
        
        Returns:
            (observation, info) - Same format as AndroidWorldHostEnv
        """
        if payload is None:
            payload = {}
        
        await self._ensure_session()
        
        last_error = None
        for attempt in range(self.STEP_MAX_RETRIES + 1):
            try:
                async with self.session.post(
                    f"{self.base_url}/reset",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.HTTP_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        raise Exception(f"Reset request to {self.base_url}/reset failed with status code {response.status}")
                    
                    data = await response.json()
                
                # Success - parse and return
                observation = data.get('observation')
                if observation:
                    observation = self._deserialize_observation(observation)
                
                info = data.get('info', {})
                
                if attempt > 0:
                    logger.info(f"Reset succeeded after {attempt} retries on {self.base_url}")
                
                return observation, info
            
            except (aiohttp.ClientError, Exception) as e:
                last_error = e
                if attempt < self.STEP_MAX_RETRIES:
                    # Fixed delay (no exponential backoff)
                    delay = self.STEP_RETRY_BASE_DELAY
                    logger.warning(
                        f"Reset request to {self.base_url} failed (attempt {attempt+1}/{self.STEP_MAX_RETRIES+1}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Reset request to {self.base_url} failed after {self.STEP_MAX_RETRIES+1} attempts: {e}"
                    )
        
        # All retries exhausted - raise ContainerDeadError to trigger container replacement
        raise ContainerDeadError(
            self.container.env_id,
            f"Reset failed after {self.STEP_MAX_RETRIES+1} attempts: {last_error}"
        )
    
    async def step(self, payload: Dict) -> Tuple[Dict, float, bool, bool, Dict]:
        """
        Execute action (same interface as AndroidWorldHostEnv.step).
        
        Includes step-level retry with fixed delay for transient failures.
        
        Args:
            payload: Dict with action, thought (same format as AndroidWorldHostEnv)
                   {
                       "action": {
                           "action_type": str,
                           "touch_point": [float, float],
                           ...
                       },
                       "thought": str
                   }
        
        Returns:
            (observation, reward, terminated, truncated, info) - Same format
        """
        await self._ensure_session()
        
        last_error = None
        for attempt in range(self.STEP_MAX_RETRIES + 1):
            try:
                async with self.session.post(
                    f"{self.base_url}/step",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.HTTP_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        raise Exception(f"Step request to {self.base_url}/step failed with status code {response.status}")
                    
                    data = await response.json()
                
                # Success - parse and return
                observation = data.get('observation')
                if observation:
                    observation = self._deserialize_observation(observation)
                
                reward = data.get('reward', 0.0)
                terminated = data.get('terminated', False)
                truncated = data.get('truncated', False)
                info = data.get('info', {})
                
                if attempt > 0:
                    logger.info(f"Step succeeded after {attempt} retries on {self.base_url}")
                
                return observation, reward, terminated, truncated, info
            
            except (aiohttp.ClientError, Exception) as e:
                last_error = e
                if attempt < self.STEP_MAX_RETRIES:
                    # Fixed delay (no exponential backoff)
                    delay = self.STEP_RETRY_BASE_DELAY
                    logger.warning(
                        f"Step request to {self.base_url} failed (attempt {attempt+1}/{self.STEP_MAX_RETRIES+1}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Step request to {self.base_url} failed after {self.STEP_MAX_RETRIES+1} attempts: {e}"
                    )
        
        # All retries exhausted - raise ContainerDeadError to trigger container replacement
        raise ContainerDeadError(
            self.container.env_id,
            f"Step failed after {self.STEP_MAX_RETRIES+1} attempts: {last_error}"
        )
    
    def _deserialize_observation(self, obs_dict: Dict) -> Dict:
        """
        Deserialize observation (reuse from androidworld_env.py lines 114-117, 148-151).
        
        Converts base64-encoded image back to numpy array.
        """
        if 'image' in obs_dict and isinstance(obs_dict['image'], str):
            # Image is base64-encoded string
            img_bytes = base64.b64decode(obs_dict['image'])
            shape = tuple(obs_dict['image_shape'])
            dtype = np.dtype(obs_dict['image_dtype'])
            obs_dict['image'] = np.frombuffer(img_bytes, dtype=dtype).reshape(shape)
        
        return obs_dict
    
    async def close(self):
        """Close HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def is_healthy(self, timeout: float = 5.0) -> bool:
        """
        Check if the container is healthy by querying the health endpoint.
        
        Args:
            timeout: Request timeout in seconds
        
        Returns:
            True if container is healthy, False otherwise
        """
        await self._ensure_session()
        
        try:
            async with self.session.get(
                f"{self.base_url}/health",
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                return response.status == 200
        except Exception:
            return False
    
    async def deep_health_check(self, timeout: float = 60.0) -> dict:
        """
        Perform deep health check - tests if emulator is actually responsive.
        
        This is more thorough than is_healthy() as it actually tries to get
        a screenshot from the emulator, detecting frozen or unresponsive states.
        
        Args:
            timeout: Request timeout in seconds (default 60s for screenshot)
        
        Returns:
            dict with:
                - status: "healthy", "degraded", or "unhealthy"
                - reason: (optional) reason for non-healthy status
                - response_time: (optional) time taken for check
        """
        await self._ensure_session()
        
        try:
            async with self.session.get(
                f"{self.base_url}/deep_health",
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status == 200:
                    return await response.json()
                return {"status": "unhealthy", "reason": f"HTTP {response.status}"}
        except asyncio.TimeoutError:
            return {"status": "unhealthy", "reason": "timeout"}
        except Exception as e:
            return {"status": "unhealthy", "reason": str(e)}

