# Claude Code Rules

## Branch Naming

Use a prefix system for all branches:

- `feat/` — new features
- `fix/` — bug fixes
- `refactor/` — code restructuring without behavior change
- `test/` — adding or updating tests

When Claude Code authors the branch, append `/cc-` after the prefix for easy identification during review:

- `feat/cc-add-api-tests`
- `fix/cc-port-allocator-even-check`
- `refactor/cc-consolidate-runners`

Human-authored branches omit the `/cc-` marker (e.g., `feat/add-api-tests`).

## Documentation

Docs live in `docs/` with two subdirectories:

- **`docs/design/`** — Technical design docs for human review. When Claude Code generates a design spec, analysis, or architecture proposal, save it here. These are append-only records — mark as superseded rather than deleting.
- **`docs/ref_agent/`** — Reference docs read by Claude Code during implementation. These must stay in sync with the code. Keep files small and focused (one topic, <500 lines) so they fit in context. Read relevant files from here before implementing related features.
- **`docs/*.md`** (top-level) — Usage and architecture docs for developers.

Do NOT create docs in other locations (`dev docs/`, `dev_doc/`, `tmp_doc/`, etc.).

## Experiment Results

All experiment results go under `skyrl-agent/results/`. Each run gets its own subfolder.

### Naming convention

```
{AgentClass}_{ModelShort}_{yymmdd}_{HHMM}
```

- **AgentClass** — the agent class name, e.g. `AndroidT3AADBAgent`, `ClaudeAgentSDK`
- **ModelShort** — model name with `/`, `-`, `.` stripped, e.g. `gpt5mini`, `UITARS7BSFT`, `Qwen3527B`
- **yymmdd\_HHMM** — run start time (2-digit year), e.g. `260305_1422`

Examples:
```
results/AndroidAgent_gpt5mini_260305_1422/
results/AndroidT3AADBAgent_UITARS7BSFT_260305_1507/
results/ClaudeAgentSDK_claudesonnet420250514_260305_1633/
```

### Rules

- Shell scripts and Python entry points must auto-generate the subfolder name — never dump results into `results/` flat.
- The OpenAI backend (`run_openai_android_inference.py`) builds the name in `_default_experiment_name()`.
- VERL shell scripts build `EXP_NAME` and pass it as `trainer.experiment_name`.
- `TrajectorySaver` follows the same convention via its `exp_name` parameter.
- Users can override with `OUTPUT_DIR=custom/path` or `--output-dir`, but the default must follow this convention.
