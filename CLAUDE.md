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
