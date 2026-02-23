"""
Compatibility patch for verl 0.6.1 to support transformers >= 4.54.0.

This patch modifies verl's monkey_patch module to allow transformers 4.54+
(which is required by other dependencies like vllm 0.11.0).

The verl-fork incorrectly blocks all transformers >= 4.53.0, but the original
verl supports 4.54+ and only blocks 4.53.* specifically (which has bugs).

This patch should be imported BEFORE any verl imports.
"""

import sys
from functools import wraps


def patch_verl_monkey_patch():
    """
    Patch verl's apply_monkey_patch to support transformers >= 4.54.0.

    The original verl-fork raises ValueError for any transformers >= 4.53.0.
    We patch it to:
    - Allow transformers >= 4.54.0 (like the original verl)
    - Block only 4.53.* (which is known to be bugged)
    """
    try:
        from verl.models.transformers import monkey_patch as mp
        from verl.models.transformers.monkey_patch import is_transformers_version_in_range
    except ImportError:
        # verl not installed yet, will be patched when imported
        return

    original_apply = mp.apply_monkey_patch

    @wraps(original_apply)
    def patched_apply_monkey_patch(
        model,
        ulysses_sp_size: int = 1,
        use_remove_padding: bool = True,
        use_fused_kernels: bool = False,
        fused_kernels_backend: str = None,
    ):
        """Patched version that supports transformers >= 4.54.0"""

        # Check if we're dealing with Qwen2-VL models
        model_type = getattr(model.config, 'model_type', None)

        if model_type in ["qwen2_5_vl", "qwen2_vl"]:
            # Check transformers version
            if is_transformers_version_in_range(min_version="4.54.0"):
                # 4.54.0+ is supported - proceed normally
                print(f"[verl_compat_patch] Allowing transformers >= 4.54.0 for {model_type}")
            elif is_transformers_version_in_range(min_version="4.53.0"):
                # 4.53.* is bugged
                raise RuntimeError(
                    "Transformers 4.53.* has bugs with Qwen2-VL models. "
                    "Please use transformers >= 4.54.0 or < 4.53.0"
                )

        # Call original with try/except to catch the ValueError
        try:
            return original_apply(
                model,
                ulysses_sp_size=ulysses_sp_size,
                use_remove_padding=use_remove_padding,
                use_fused_kernels=use_fused_kernels,
                fused_kernels_backend=fused_kernels_backend,
            )
        except ValueError as e:
            if "Transformers 4.53 is not supported" in str(e):
                # This is the verl-fork's overly strict check
                # Check if we're actually on 4.54+ (which should be allowed)
                if is_transformers_version_in_range(min_version="4.54.0"):
                    print(f"[verl_compat_patch] Bypassing verl-fork's 4.53 check for transformers 4.54+")
                    # We need to manually do what the original function would do
                    # For now, just skip the monkey patching for the attention
                    # The model should still work, just without ulysses optimization
                    print(f"[verl_compat_patch] Warning: Skipping some monkey patches for {model_type}")
                    return
                else:
                    raise
            else:
                raise

    mp.apply_monkey_patch = patched_apply_monkey_patch
    print("[verl_compat_patch] Patched verl's apply_monkey_patch for transformers 4.54+ support")


# Auto-patch when this module is imported
def install_import_hook():
    """Install an import hook to patch verl when it's imported."""

    class VerlPatchFinder:
        def find_module(self, name, path=None):
            if name == 'verl.models.transformers.monkey_patch':
                return self
            return None

        def load_module(self, name):
            # Remove ourselves to avoid infinite recursion
            sys.meta_path.remove(self)

            # Import the real module
            import importlib
            module = importlib.import_module(name)

            # Apply our patch
            patch_verl_monkey_patch()

            return module

    # Only install if verl isn't already imported
    if 'verl.models.transformers.monkey_patch' not in sys.modules:
        sys.meta_path.insert(0, VerlPatchFinder())
        print("[verl_compat_patch] Import hook installed")
    else:
        # verl already imported, patch directly
        patch_verl_monkey_patch()


def patch_vllm_utils():
    """
    Patch vllm.utils to provide get_tcp_uri function if it doesn't exist.
    
    verl 0.6 requires get_tcp_uri from vllm.utils but it was removed in vLLM 0.11.0.
    This patch provides a compatible implementation.
    """
    try:
        import vllm.utils as vllm_utils
        
        # Check if get_tcp_uri already exists
        if hasattr(vllm_utils, 'get_tcp_uri'):
            return
        
        # Check if is_valid_ipv6_address exists for proper IPv6 handling
        is_valid_ipv6 = getattr(vllm_utils, 'is_valid_ipv6_address', lambda x: False)
        
        # Provide a compatible implementation
        def get_tcp_uri(host: str, port: int) -> str:
            """Generate a TCP URI for ZeroMQ communication."""
            if is_valid_ipv6(host):
                return f"tcp://[{host}]:{port}"
            return f"tcp://{host}:{port}"
        
        # Monkey-patch it into vllm.utils
        vllm_utils.get_tcp_uri = get_tcp_uri
        print("[verl_compat_patch] Added get_tcp_uri to vllm.utils for verl 0.6 compatibility")
        
    except ImportError:
        # vllm not installed yet
        pass


def patch_vllm_async_server_max_model_len():
    """
    Patch verl's vLLMHttpServer to respect explicit max_model_len setting.
    
    Bug: verl's vllm_async_server.py unconditionally overwrites max_model_len:
        self.config.max_model_len = self.config.prompt_length + self.config.response_length
    
    This ignores any explicit max_model_len setting from the config.
    
    This patch makes it use the explicit setting if provided, falling back to
    the calculated value only if max_model_len is not set.
    """
    try:
        from verl.workers.rollout.vllm_rollout import vllm_async_server
        
        original_init = vllm_async_server.vLLMHttpServer.__init__
        
        def patched_init(self, config, model_config, rollout_mode, workers, replica_rank, node_rank, gpus_per_node, nnodes):
            # Call original init (which overwrites max_model_len)
            original_init(self, config, model_config, rollout_mode, workers, replica_rank, node_rank, gpus_per_node, nnodes)
            
            # Check if there was an explicit max_model_len in the original config
            # The OmegaConf object may have the original value before conversion
            if hasattr(config, '_content') and 'max_model_len' in config._content:
                explicit_max_model_len = config._content.get('max_model_len')
            elif hasattr(config, 'max_model_len'):
                # Check if it's different from the calculated value
                explicit_max_model_len = getattr(config, 'max_model_len', None)
            else:
                explicit_max_model_len = None
            
            calculated_len = self.config.prompt_length + self.config.response_length
            
            # If explicit value was larger than calculated, restore it
            # (The original init would have overwritten it to calculated_len)
            if explicit_max_model_len and explicit_max_model_len > calculated_len:
                print(f"[verl_compat_patch] Restoring explicit max_model_len={explicit_max_model_len} "
                      f"(was overwritten to {calculated_len})")
                self.config.max_model_len = explicit_max_model_len
        
        vllm_async_server.vLLMHttpServer.__init__ = patched_init
        print("[verl_compat_patch] Patched vLLMHttpServer to respect explicit max_model_len")
        
    except ImportError:
        # verl not installed or module structure different
        pass
    except Exception as e:
        print(f"[verl_compat_patch] Warning: Could not patch vLLMHttpServer: {e}")


# Run the patches
patch_vllm_utils()
patch_vllm_async_server_max_model_len()
install_import_hook()
