# verl 0.6 vs 0.7 Migration Guide

## Summary: Code Changes Required

**Estimated effort: Medium (3-5 files, ~200-300 lines)**

## Key Differences

### 1. **Rollout Mode** ⚠️ BREAKING
- **verl 0.6**: Supports both `sync` and `async` modes
- **verl 0.7**: Only supports `async` mode (sync removed)
- **Impact**: If verl 0.6 worked with sync mode, no change needed. If async was used, minimal change.

### 2. **AgentLoopManager Interface** ⚠️ BREAKING
- **verl 0.6**: May have different initialization pattern
- **verl 0.7**: Uses `RolloutReplica` classes with `init_hybrid(worker_group)`
- **Impact**: `SkyAgentLoopManager` inheritance may need adjustment

### 3. **postprocess_data() Signature** ⚠️ BREAKING
- **verl 0.6**: Likely accepts `position_ids` and `labels` as parameters
- **verl 0.7**: Only accepts `input_ids`, `attention_mask`, `max_length`, `pad_token_id`, `left_pad`, `truncation`
- **Impact**: `android_agent.py` - need to revert the workaround we added

### 4. **AsyncServerBase** ⚠️ BREAKING
- **verl 0.6**: Has `AsyncServerBase` class
- **verl 0.7**: Removed `AsyncServerBase` (we use `Any` as workaround)
- **Impact**: `verl_async_manager.py` - can use proper type hints

### 5. **Config Access** ⚠️ MINOR
- **verl 0.6**: May allow direct access to optional config keys
- **verl 0.7**: Requires `OmegaConf.select()` for optional keys
- **Impact**: `verl_trainer.py` - may simplify config access

## Files That Need Changes

### 1. `pyproject.toml` (1 line)
```toml
# Change from:
verl = { git = "https://github.com/volcengine/verl", rev = "v0.7.0" }
# To:
verl = { git = "https://github.com/volcengine/verl", rev = "v0.6.0" }
```

### 2. `skyrl_agent/integrations/verl/verl_async_manager.py` (~50-100 lines)
- **Current (0.7)**: Inherits from `AgentLoopManager`, uses `RolloutReplica`
- **0.6**: May need different initialization pattern
- **Action**: Check if verl 0.6 has `AgentLoopManager` or uses different class
- **Revert**: The `AsyncServerBase = Any` workaround (line 19) can use proper type

### 3. `skyrl_agent/agents/android/android_agent.py` (~30-50 lines)
- **Current (0.7)**: Manual padding of `position_ids` and `labels` after `postprocess_data()`
- **0.6**: Can pass `position_ids` and `labels` directly to `postprocess_data()`
- **Action**: Revert to simpler version that passes all params to `VF.postprocess_data()`

### 4. `skyrl_agent/integrations/verl/verl_trainer.py` (~10-20 lines)
- **Current (0.7)**: Uses `OmegaConf.select()` for optional `profile_steps`
- **0.6**: May allow direct access `self.config.trainer.profile_steps`
- **Action**: Simplify config access if 0.6 allows it

### 5. `examples/run_verl/verl_android_test.sh` (1 line)
- **Current (0.7)**: `actor_rollout_ref.rollout.mode=async` (only option)
- **0.6**: Can use `sync` or `async`
- **Action**: Can optionally try `sync` mode if async has issues

## Potential Benefits of verl 0.6

1. ✅ **May not have the flash attention CUDA bug** - The `cu_seqlens_q must be on CUDA` error might be fixed
2. ✅ **Simpler API** - `postprocess_data()` accepts more parameters
3. ✅ **Sync mode available** - Can use sync mode if async has issues
4. ✅ **More stable** - 0.6 is older, may have fewer breaking changes

## Potential Risks of verl 0.6

1. ⚠️ **Missing features** - verl 0.7 may have bug fixes or features we need
2. ⚠️ **vLLM compatibility** - verl 0.6 may not support newer vLLM versions
3. ⚠️ **Different bugs** - May have different issues than 0.7

## Recommendation

**Try verl 0.6 if:**
- The flash attention bug is blocking
- You want to test if the issue is version-specific
- You're willing to revert some of our 0.7 compatibility work

**Stay on verl 0.7 if:**
- You want latest features
- You can wait for verl to fix the flash attention bug
- You want to file a bug report with verl team

## Testing Checklist

After downgrading to verl 0.6:
1. ✅ Update `pyproject.toml` version
2. ✅ Run `uv sync` to update dependencies
3. ✅ Check if `AgentLoopManager` exists and has same interface
4. ✅ Test `postprocess_data()` signature
5. ✅ Run training and check if flash attention error is gone
6. ✅ Verify AndroidWorld training works end-to-end
