"""
Android environment tool for executing actions in AndroidWorld.

Adapted from verl/trainer/mobile_agent.py step() method.
This tool provides a thin wrapper around env_handle.step() for the AndroidAgent.
"""

import asyncio
from typing import Union, Dict, Any
from .base import BaseTool, register_tool


@register_tool("android_env")
class AndroidEnvTool(BaseTool):
    """
    Tool for executing actions in Android environment.
    
    This tool receives parsed action dicts from AndroidAgent and executes them
    via the environment handle's step() method.
    
    Supported action types:
        - click: Touch at normalized coordinates [x, y]
        - long_press: Long press at coordinates
        - input_text: Enter text
        - scroll: Scroll in direction (up/down/left/right)
        - navigate_home: Press home button
        - navigate_back: Press back button
        - open_app: Open app by name
        - status: Mark task complete/infeasible
        - wait: Wait for a moment
        - answer: Provide an answer
    """
    
    name = "android_env"
    description = "Execute actions in the Android environment"
    parameters = {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "description": "Type of action to execute (click, scroll, type, etc.)"
            },
        },
        "required": ["action_type"],
    }

    async def async_call(self, params: Union[str, dict], **kwargs) -> Dict[str, Any]:
        """
        Execute action via env_handle.step() (async version).
        
        This is the preferred method when calling from an async context.
        Avoids asyncio nesting issues that occur with call() in thread pools.
        
        Args:
            params: Action dict with action_type and action-specific parameters
            **kwargs:
                env_handle: Environment handle with step() method (required)
                thought: Agent's thought string (optional)
        
        Returns:
            Dict with image, reward, terminated, truncated, info
        """
        env_handle = kwargs.get("env_handle")
        thought = kwargs.get("thought", "")
        
        if env_handle is None:
            return {
                "error": "No env_handle provided",
                "image": None,
                "reward": 0.0,
                "terminated": True,
                "truncated": False,
                "info": {"error": "Missing env_handle"},
            }
        
        # Parse params if string
        if isinstance(params, str):
            try:
                params = self._verify_json_format_args(params)
            except ValueError as e:
                return {
                    "error": f"Invalid action parameters: {e}",
                    "image": None,
                    "reward": 0.0,
                    "terminated": True,
                    "truncated": False,
                    "info": {"error": str(e)},
                }
        
        # Build step payload
        payload = {
            "action": params,
            "thought": thought,
        }
        
        # Execute step via environment handle (async)
        try:
            observation, reward, terminated, truncated, info = await env_handle.step(payload)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "error": f"Environment step failed: {e}",
                "image": None,
                "reward": 0.0,
                "terminated": True,
                "truncated": False,
                "info": {"error": str(e)},
            }
        
        # Extract image from observation
        image = None
        if observation is not None:
            image = observation.get("image")
        
        return {
            "image": image,
            "reward": reward,
            "terminated": terminated,
            "truncated": truncated,
            "info": info,
        }
    
    def call(self, params: Union[str, dict], **kwargs) -> Dict[str, Any]:
        """
        Execute action via env_handle.step() (sync wrapper).
        
        WARNING: This method has known issues with asyncio when called from
        thread pool executors. Prefer async_call() when in an async context.
        
        Args:
            params: Action dict with action_type and action-specific parameters
            **kwargs:
                env_handle: Environment handle with step() method (required)
                thought: Agent's thought string (optional)
        
        Returns:
            Dict with image, reward, terminated, truncated, info
        """
        env_handle = kwargs.get("env_handle")
        thought = kwargs.get("thought", "")
        
        if env_handle is None:
            return {
                "error": "No env_handle provided",
                "image": None,
                "reward": 0.0,
                "terminated": True,
                "truncated": False,
                "info": {"error": "Missing env_handle"},
            }
        
        # Parse params if string
        if isinstance(params, str):
            try:
                params = self._verify_json_format_args(params)
            except ValueError as e:
                return {
                    "error": f"Invalid action parameters: {e}",
                    "image": None,
                    "reward": 0.0,
                    "terminated": True,
                    "truncated": False,
                    "info": {"error": str(e)},
                }
        
        # Build step payload
        payload = {
            "action": params,
            "thought": thought,
        }
        
        # Execute step via environment handle
        # Note: This has issues when called from thread pool with running event loop
        try:
            step_coro = env_handle.step(payload)
            if asyncio.iscoroutine(step_coro):
                # Create new event loop for this thread
                observation, reward, terminated, truncated, info = asyncio.run(step_coro)
            else:
                observation, reward, terminated, truncated, info = step_coro
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "error": f"Environment step failed: {e}",
                "image": None,
                "reward": 0.0,
                "terminated": True,
                "truncated": False,
                "info": {"error": str(e)},
            }
        
        # Extract image from observation
        image = None
        if observation is not None:
            image = observation.get("image")
        
        return {
            "image": image,
            "reward": reward,
            "terminated": terminated,
            "truncated": truncated,
            "info": info,
        }
