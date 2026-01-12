"""
AndroidTask - Task interface for Android/AndroidWorld tasks.

Provides initial instruction formatting and evaluation.
Does NOT handle per-step formatting (that's Agent's responsibility).
"""

import io
import base64
from typing import List, Dict, Any, Optional
from PIL import Image

from skyrl_agent.tasks.base import BaseTask
from skyrl_agent.agents.android.android_agent import UITARS_USR_PROMPT_THOUGHT


class AndroidTask(BaseTask):
    """
    Task interface for Android/AndroidWorld tasks.
    
    Provides:
    - initialize_runtime(): Pre-start environment pool
    - get_instruction(): Build initial instruction messages
    - evaluate_result(): Evaluate trajectory result
    """
    
    @classmethod
    async def initialize_runtime(cls, env_config: Dict[str, Any]) -> List:
        """
        Pre-start environment pool.
        
        Called once by AndroidAgentRunner on first run().
        Delegates actual environment creation to Environment Layer.
        
        Args:
            env_config: Environment configuration dict containing:
                - pool_size: Number of environments to create
                - docker_image: Docker image for Android emulator
                - snapshot: Snapshot name
                - Other env-specific config
        
        Returns:
            List of env handles for async_fix_pool dispatcher
        """
        # Import here to avoid circular dependency
        # The actual AndroidWorldHostEnv is in Environment Layer
        try:
            from verl.trainer.androidworld_env import AndroidWorldHostEnv
        except ImportError:
            raise ImportError(
                "AndroidWorldHostEnv not found. Please ensure the environment layer is available."
            )
        
        pool_size = env_config.get("pool_size", 8)
        base_env_id = env_config.get("base_env_id", 0)
        
        env_pool = []
        for i in range(pool_size):
            env = AndroidWorldHostEnv(
                docker_image=env_config.get("docker_image", "androidworld:v8"),
                sample_mode=env_config.get("sample_mode", "random"),
                save_images=env_config.get("save_images", False),
                env_id=base_env_id + i,
                snapshot=env_config.get("snapshot", "default"),
                train_task_family=env_config.get("train_task_family", None),
                val_task_family=env_config.get("val_task_family", None),
                temp_path=env_config.get("temp_path", "/tmp"),
            )
            env_pool.append(env)
        
        return env_pool
    
    @classmethod
    def get_instruction(cls, instance: Dict) -> List[Dict]:
        """
        Build template instruction messages (system prompt only).
        
        Called once per trajectory during initialize_trajectory().
        Returns base messages without task-specific content.
        Task description and image are added via format_observation().
        
        Args:
            instance: Task instance data (contains task_id, seed, etc.)
        
        Returns:
            Messages in OpenAI format with system prompt only
        """
        return [
            {
                "role": "system",
                "content": [{"type": "text", "text": "You are a helpful assistant."}]
            },
        ]
    
    @classmethod
    def format_observation(cls, observation: Dict) -> List[Dict]:
        """
        Format observation into messages (task description + image).
        
        Called by trajectory after env.reset() to add task-specific content.
        
        Args:
            observation: Observation from env.reset() containing:
                - task: Task instruction string
                - image: Screenshot as numpy array
        
        Returns:
            Messages with task instruction and initial screenshot
        """
        task_instruction = observation.get("task", "")
        image = observation.get("image")
        
        messages = [
            {
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": UITARS_USR_PROMPT_THOUGHT.format(instruction=task_instruction)
                }]
            },
        ]
        
        # Add initial screenshot if available
        if image is not None:
            image_base64 = cls._numpy_to_base64(image)
            messages.append({
                "role": "user",
                "content": [{
                    "type": "image",
                    "image": f"data:image/png;base64,{image_base64}",
                    "min_pixels": 3136,
                    "max_pixels": 1003520,
                }]
            })
        
        return messages
    
    @classmethod
    def complete_runtime(cls, env_handle: Any) -> Dict[str, Any]:
        """
        Optional cleanup after trajectory.
        
        Args:
            env_handle: Environment handle to clean up
        
        Returns:
            Dict with any extracted state
        """
        return {}
    
    @classmethod
    async def evaluate_result(
        cls,
        result: Any,
        instance: Dict,
        history_images: Optional[List] = None,
        history_messages: Optional[List] = None,
        reward_provider: str = "ground_truth",
        **kwargs,
    ) -> float:
        """
        Evaluate trajectory result.
        
        Supports multiple evaluation methods:
        - ground_truth: Use reward from environment
        - gemini: Use LLM-based evaluation
        
        Args:
            result: Result from agent run (usually reward from last step)
            instance: Task instance data
            history_images: List of screenshots from trajectory
            history_messages: List of conversation messages
            reward_provider: Evaluation method ("ground_truth" or "gemini")
            **kwargs: Additional arguments for specific evaluators
        
        Returns:
            Float reward value
        """
        if reward_provider == "ground_truth":
            # Use reward passed from environment
            if isinstance(result, (int, float)):
                return float(result)
            return 0.0
        
        # elif reward_provider == "gemini":
        #     # Use LLM-based evaluation
        #     try:
        #         from verl.trainer.gemini_evaluator import GeminiEvaluator
                
        #         evaluator = GeminiEvaluator(model_name="gemini-2.5-pro")
        #         task_instruction = instance.get("task", "") if isinstance(instance, dict) else ""
                
        #         reward = evaluator.evaluate(
        #             task_instruction,
        #             history_images or [],
        #             history_messages or [],
        #         )
        #         return float(reward)
        #     except Exception as e:
        #         print(f"[AndroidTask] Gemini evaluation failed: {e}")
        #         return 0.0
        
        else:
            print(f"[AndroidTask] Unknown reward_provider: {reward_provider}")
            return 0.0
    
    @staticmethod
    def _numpy_to_base64(nparray) -> str:
        """
        Convert numpy array to base64 string.
        
        Args:
            nparray: Numpy array representing an image
        
        Returns:
            Base64-encoded PNG string
        """
        image = Image.fromarray(nparray)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
