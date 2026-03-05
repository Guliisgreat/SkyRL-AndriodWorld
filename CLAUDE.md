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
