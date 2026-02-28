"""
AndroidTask - Task interface for Android/AndroidWorld tasks.

Provides initial instruction formatting and evaluation.
Does NOT handle per-step formatting (that's Agent's responsibility).
"""

import io
import base64
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from skyrl_agent.runtime.android import ContainerManager
from PIL import Image
from loguru import logger

from skyrl_agent.tasks.base import BaseTask


class AndroidTask(BaseTask):
    """
    Task interface for Android/AndroidWorld tasks.
    
    Provides:
    - initialize_runtime(): Pre-start environment pool
    - get_instruction(): Build initial instruction messages
    - evaluate_result(): Evaluate trajectory result
    """
    
    # Class-level storage for ContainerManager (shared across calls)
    _container_manager: Optional['ContainerManager'] = None

    @classmethod
    async def initialize_runtime(cls, env_config: Dict[str, Any]) -> List:
        """
        Pre-start environment pool.

        Called once by AndroidAgentRunner on first run().
        Creates Docker containers via ContainerManager and wraps them in RuntimeClients.

        When broker_url is set in env_config, uses a remote container pool broker
        instead of creating containers locally. The BrokerContainerManager adapter
        implements the same interface as ContainerManager, so the dispatcher and
        runner work unchanged.

        Args:
            env_config: Environment configuration dict containing:
                - broker_url: URL of container pool broker (optional, activates Mode B)
                - pool_size: Number of environments to create (default: 8)
                - docker_image: Docker image for Android emulator (default: "androidworld:v8")
                - snapshot: Snapshot name (default: "clean")
                - sample_mode: Task sampling mode (default: "sequential")
                - train_task_family: Training task family (default: "android_world")
                - val_task_family: Validation task family (default: "android_world")
                - temp_path: Path for temp files (default: "/tmp")
                - base_env_id: Starting env ID (default: 0)
                - lock_file: Lock file path for port allocation (optional)

        Returns:
            List of RuntimeClient instances for async_fix_pool dispatcher
        """
        # ── Mode B: Broker ────────────────────────────────────────────────
        broker_url = env_config.get("broker_url")
        if broker_url:
            from skyrl_agent.runtime.android.pool_client import (
                PoolClient,
                BrokerContainerManager,
            )

            pool_client = PoolClient(broker_url)
            if not await pool_client.check_broker_health():
                raise RuntimeError(f"Broker not reachable at {broker_url}")
            pool_size = env_config.get("pool_size")
            broker_manager = BrokerContainerManager(pool_client, pool_size=pool_size)
            await broker_manager.initialize()
            cls._container_manager = broker_manager
            logger.info(f"Connected to container pool broker at {broker_url}")
            return []  # No pre-created RuntimeClients; containers acquired per-task

        # ── Mode A: Local (existing code, completely unchanged) ───────────
        from skyrl_agent.runtime.android import ContainerManager, RuntimeClient

        pool_size = env_config.get("pool_size", 8)
        buffer_size = env_config.get("buffer_size", 0)  # Hot standby containers
        base_env_id = env_config.get("base_env_id", 0)
        docker_image = env_config.get("docker_image", "androidworld:v8")
        temp_path = env_config.get("temp_path", "/tmp")
        lock_file = env_config.get("lock_file")

        # Create ContainerManager if not already created
        if cls._container_manager is None:
            cls._container_manager = ContainerManager(
                docker_image=docker_image,
                temp_path=temp_path,
                lock_file=lock_file,
            )

        # Create container pool (parallel for faster initialization)
        # With optional backup buffer for hot standby containers
        containers = await cls._container_manager.create_pool_parallel(
            pool_size=pool_size,
            base_env_id=base_env_id,
            max_concurrent=min(pool_size + buffer_size, 4),  # Bound parallelism
            initial_wait=30.0,  # Reduced wait for parallel
            max_retries=2,
            sample_mode=env_config.get("sample_mode", "sequential"),
            snapshot=env_config.get("snapshot", "clean"),
            train_task_family=env_config.get("train_task_family", "android_world"),
            val_task_family=env_config.get("val_task_family", "android_world"),
            buffer_size=buffer_size,
            use_host_network=env_config.get("use_host_network", False),
            skip_screenshot=env_config.get("skip_screenshot", False),
        )

        # Wrap each container in a RuntimeClient (for backward compatibility)
        # Note: The new async_fix_pool_android dispatcher creates RuntimeClients
        # on-demand from ContainerInstance, so this is only needed for legacy code
        runtime_clients = [RuntimeClient(container) for container in containers]
        
        # Start background health monitor for automatic container recovery
        # Check every 30s (reduced frequency)
        await cls._container_manager.start_health_monitor(interval=30.0)

        return runtime_clients

    @classmethod
    async def cleanup_runtime(cls):
        """
        Cleanup the container pool.

        Should be called when training is complete to stop all Docker containers.
        """
        if cls._container_manager is not None:
            # Stop health monitor before cleanup
            await cls._container_manager.stop_health_monitor()
            await cls._container_manager.cleanup()
            cls._container_manager = None
    
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
    def format_observation(
        cls,
        observation: Dict,
        prompt_formatter=None,
        min_pixels: int = 78400,
        max_pixels: int = 564480,
    ) -> List[Dict]:
        """
        Format observation into messages (task description + image).
        
        Returns RAW observation data. Agent-specific prompt formatting 
        should be applied by the Agent layer via prompt_formatter.
        
        Args:
            observation: Observation from env.reset() containing:
                - task: Task instruction string
                - image: Screenshot as numpy array
            prompt_formatter: Optional callable to format the task instruction
                              with an agent-specific prompt template.
                              If None, returns raw task instruction.
            min_pixels: Minimum pixels for image (agent/model specific, default for Qwen2-VL)
            max_pixels: Maximum pixels for image (agent/model specific, default for Qwen2-VL)
        
        Returns:
            Messages with task instruction and initial screenshot
        """
        task_instruction = observation.get("task", "")
        image = observation.get("image")
        
        # Apply agent-specific prompt formatting if provided
        if prompt_formatter is not None:
            formatted_text = prompt_formatter(task_instruction)
        else:
            formatted_text = task_instruction
        
        messages = [
            {
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": formatted_text
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
                    "min_pixels": min_pixels,
                    "max_pixels": max_pixels,
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
