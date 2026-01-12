"""
RuntimeClient - HTTP client for communicating with container's FastAPI server.

Provides the same interface as AndroidWorldHostEnv (reset, step methods)
to ensure compatibility with agent layer code.
"""

import base64
import numpy as np
import aiohttp
from typing import Dict, Any, Tuple, Optional
from .container_manager import ContainerInstance


class RuntimeClient:
    """
    HTTP client that replaces AndroidWorldHostEnv.
    
    Provides SAME interface as AndroidWorldHostEnv:
    - reset(payload) → (observation, info)
    - step(payload) → (observation, reward, terminated, truncated, info)
    
    This ensures agent layer code works without changes.
    """
    
    def __init__(self, container: ContainerInstance):
        """
        Initialize RuntimeClient.
        
        Args:
            container: ContainerInstance to connect to
        """
        self.container = container
        self.base_url = f"http://localhost:{container.server_port}"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self):
        """Ensure HTTP session is created."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
    
    async def reset(self, payload: Dict = None) -> Tuple[Dict, Dict]:
        """
        Reset environment (same interface as AndroidWorldHostEnv.reset).
        
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
        
        try:
            async with self.session.post(
                f"{self.base_url}/reset",
                json=payload
            ) as response:
                if response.status != 200:
                    raise Exception(f"Reset request to {self.base_url}/reset failed with status code {response.status}")
                
                data = await response.json()
        
        except aiohttp.ClientError as e:
            raise Exception(f"Error in sending reset request to {self.base_url}: {e}")
        
        observation = data.get('observation')
        if observation:
            observation = self._deserialize_observation(observation)
        
        info = data.get('info', {})
        return observation, info
    
    async def step(self, payload: Dict) -> Tuple[Dict, float, bool, bool, Dict]:
        """
        Execute action (same interface as AndroidWorldHostEnv.step).
        
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
        
        try:
            async with self.session.post(
                f"{self.base_url}/step",
                json=payload
            ) as response:
                if response.status != 200:
                    raise Exception(f"Step request to {self.base_url}/step failed with status code {response.status}")
                
                data = await response.json()
        
        except aiohttp.ClientError as e:
            raise Exception(f"Error in sending step request to {self.base_url}: {e}")
        
        observation = data.get('observation')
        if observation:
            observation = self._deserialize_observation(observation)
        
        reward = data.get('reward', 0.0)
        terminated = data.get('terminated', False)
        truncated = data.get('truncated', False)
        info = data.get('info', {})
        
        return observation, reward, terminated, truncated, info
    
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

