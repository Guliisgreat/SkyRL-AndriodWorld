"""
verl 0.6.1 integration for skyrl-agent.

This module provides integration between skyrl-agent and verl 0.6.1
with VLM support for AndroidWorld tasks.
"""

from .android_dataset import AndroidWorldDataset, create_android_dataset
from .verl_async_manager import SkyAgentLoopManager
from .verl_trainer import SkyAgentPPOTrainer
from .verl_backend import VeRLBackend, VeRLGeneratorOutput, VeRLGeneratorInput
from ..base import register_backend, BackendSpec

# Register the verl_061 backend (overrides the old "verl" backend)
# This ensures verl 0.6.1's TokenOutput API is used correctly
register_backend(
    "verl",
    BackendSpec(
        infer_backend_cls=VeRLBackend,
        generator_output_cls=VeRLGeneratorOutput,
        generator_input_cls=VeRLGeneratorInput,
    ),
)

__all__ = [
    "AndroidWorldDataset",
    "create_android_dataset",
    "SkyAgentLoopManager",
    "SkyAgentPPOTrainer",
    "VeRLBackend",
    "VeRLGeneratorOutput",
    "VeRLGeneratorInput",
]
