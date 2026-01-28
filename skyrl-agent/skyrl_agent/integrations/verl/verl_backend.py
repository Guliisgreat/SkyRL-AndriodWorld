"""
VeRL 0.6.1 Backend for skyrl-agent.

This module adapts verl 0.6.1's TokenOutput to skyrl-agent's expected interface.
Key changes from verl 0.5.x:
- generate() now returns TokenOutput instead of Tuple[str, str]
- Tokenizer is required to decode token_ids to text
"""

from skyrl_agent.integrations.base import AsyncInferBackend, GeneratorOutput, GeneratorInput
from typing import Any, List, Dict, Tuple
from loguru import logger

# Import TokenOutput from verl 0.6.1
try:
    from verl.workers.rollout.replica import TokenOutput
except ImportError:
    # Fallback for type hints if verl is not installed
    TokenOutput = Any


class VeRLBackend(AsyncInferBackend):
    """
    AsyncInferBackend implementation for verl 0.6.1.
    
    Handles the TokenOutput return type from verl 0.6.1's generate() method
    and decodes token_ids to text using the provided tokenizer.
    """

    def __init__(self, infer_engine, tokenizer=None, cfg: Dict[str, Any] = None):
        """
        Initialize VeRLBackend.
        
        Args:
            infer_engine: The inference engine (AsyncLLMServerManager or similar)
            tokenizer: HuggingFace tokenizer for decoding token_ids to text.
                       Required for verl 0.6.1 compatibility.
            cfg: Optional configuration dictionary
        """
        self.infer_engine = infer_engine
        self.tokenizer = tokenizer
        self.cfg = cfg or {}

    async def async_generate_ids(
        self,
        input_ids: List[int],
        sampling_params: Dict[str, Any],
        request_id: str,
        image_data: List[Any] = None,
        **kwargs,
    ) -> Tuple[str, str]:
        """
        Generate text from input token IDs.
        
        Args:
            input_ids: List of input token IDs
            sampling_params: Sampling parameters for generation
            request_id: Unique request identifier for sticky sessions
            image_data: List of PIL images or numpy arrays for VLM models
            **kwargs: Additional arguments
            
        Returns:
            Tuple of (response_text, finish_reason)
        """
        # verl 0.6.1 returns TokenOutput from generate()
        token_output: TokenOutput = await self.infer_engine.generate(
            request_id=request_id,
            prompt_ids=input_ids,
            sampling_params=sampling_params,
            image_data=image_data,
        )
        
        # Decode token_ids to text string
        token_ids = token_output.token_ids
        if self.tokenizer is not None:
            response_str = self.tokenizer.decode(
                token_ids, 
                skip_special_tokens=True
            )
        else:
            # Fallback: join token IDs as string (not recommended)
            logger.warning("Tokenizer not provided, returning raw token_ids as string")
            response_str = str(token_ids)
        
        # Infer finish_reason from token_ids
        # verl 0.6.1 TokenOutput only has token_ids and log_probs, no stop_reason
        finish_reason = "stop"  # Default
        if self.tokenizer is not None and len(token_ids) > 0:
            # Check if last token is EOS
            if token_ids[-1] == self.tokenizer.eos_token_id:
                finish_reason = "stop"
            else:
                # Likely hit max_tokens limit
                finish_reason = "length"
        
        return response_str, finish_reason

    async def async_generate_prompts(self, prompts: Any, sampling_params: Any) -> List[str]:
        """Generate outputs for a list of prompts. Not implemented for verl backend."""
        raise NotImplementedError("async_generate_prompts is not supported for VeRL backend")


class VeRLGeneratorOutput(GeneratorOutput):
    """Generator output wrapper for verl backend."""
    
    def __init__(self, result: Dict[str, Any]):
        self.result = result


class VeRLGeneratorInput(GeneratorInput):
    """
    Generator input wrapper for verl backend.
    
    Converts verl's DataProto format to a list of dictionaries.
    """
    
    def __init__(self, input_batch: Any):
        self.input_batch: List[Dict[str, Any]] = []
        non_tensor_batch = input_batch.non_tensor_batch
        first_key = next(iter(non_tensor_batch.keys()))
        num_entries = len(non_tensor_batch[first_key])
        for i in range(num_entries):
            data_item: dict = {key: non_tensor_batch[key][i] for key in non_tensor_batch.keys()}
            self.input_batch.append(data_item)
        logger.info(f"input batch of size: {len(self.input_batch)}")
        logger.info(f"keys: {self.input_batch[0].keys()}")
