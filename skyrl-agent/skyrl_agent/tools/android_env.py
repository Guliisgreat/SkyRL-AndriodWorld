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

    def call(self, params: Union[str, dict], **kwargs) -> Dict[str, Any]:
        """
        Execute action via env_handle.step().
        
        Reused from mobile_agent.py lines 446-447:
            payload = {'action': action, 'thought': thought}
            observation, reward, terminated, truncated, info = self.env.step(payload)
        
        Args:
            params: Action dict with action_type and action-specific parameters
                - click: {"action_type": "click", "touch_point": [x, y]}
                - long_press: {"action_type": "long_press", "touch_point": [x, y]}
                - input_text: {"action_type": "input_text", "text": "..."}
                - scroll: {"action_type": "scroll", "direction": "up|down|left|right"}
                - navigate_home: {"action_type": "navigate_home"}
                - navigate_back: {"action_type": "navigate_back"}
                - open_app: {"action_type": "open_app", "app_name": "..."}
                - status: {"action_type": "status", "goal_status": "complete|infeasible"}
                - wait: {"action_type": "wait"}
                - answer: {"action_type": "answer", "text": "..."}
            **kwargs:
                env_handle: Environment handle with step() method (required)
                thought: Agent's thought string (optional)
        
        Returns:
            Dict with:
                - image: Screenshot as numpy array (or None if unavailable)
                - reward: Reward from environment
                - terminated: Whether episode terminated
                - truncated: Whether episode was truncated
                - info: Additional info from environment
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
        
        # Build step payload (same structure as mobile_agent.py)
        payload = {
            "action": params,
            "thought": thought,
        }
        
        # Execute step via environment handle
        # Note: env_handle.step() is async, so we need to run it properly
        try:
            step_coro = env_handle.step(payload)
            # Check if step returns a coroutine (async method)
            if asyncio.iscoroutine(step_coro):
                # Run async step in a new event loop (we're in a thread pool)
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # We're in an async context, use run_coroutine_threadsafe
                        import concurrent.futures
                        future = asyncio.run_coroutine_threadsafe(step_coro, loop)
                        observation, reward, terminated, truncated, info = future.result(timeout=300)
                    else:
                        observation, reward, terminated, truncated, info = loop.run_until_complete(step_coro)
                except RuntimeError:
                    # No event loop exists, create a new one
                    observation, reward, terminated, truncated, info = asyncio.run(step_coro)
            else:
                # Sync method (step_coro is already the result tuple)
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
