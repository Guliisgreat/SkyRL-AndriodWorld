# Docs

Index for the `docs/` tree. See [`../CLAUDE.md`](../CLAUDE.md) for the rules
that govern what goes where (in particular: design docs are append-only and
must be marked superseded rather than deleted).

## Map

```
docs/
├── README.md                          (this file)
│
├── architecture & operations  ──────────────────────────────────────────
├── framework.md                       SkyRL-Agent framework tutorial (3-layer model)
├── androidworld_integration.md        AndroidWorld → SkyRL-Agent integration tutorial
├── error_recovery.md                  4-layer error model (network/server/env/emulator)
├── host_network_debugging.md          host-network parallel container troubleshooting
├── task_prerequisites.md              known-failing AW tasks + workaround
│
├── ref_agent/                         ── read by Claude Code on every task ──
│   ├── code_structure.md              up-to-date repo map (skyrl-agent + eval-runners + docker)
│   ├── container_pool_broker.md       Mode A (local) vs Mode B (broker) usage
│   └── adb_agent_prompt_design.md     prompt anatomy for screen_adb_agent
│
├── design/                            ── technical design docs (human review) ──
│   ├── androidlab/                    7 docs (integration, verifiers, results)
│   ├── mobileworld/                   6 docs (broker compat, Claude CLI agent, harbor usage,
│   │                                  task analysis/lifecycle, vs AndroidWorld)
│   ├── tier4/                         tier4 / CLI-advantage benchmark
│   │   ├── cli_dataset_45_balanced.md      ← canonical 45-task subset
│   │   ├── cli_dataset_new_task_specs.md   specs for 7 new C/D tasks
│   │   ├── 2026plusswipe_integration.md    Docker integration runbook
│   │   ├── cli_vs_gui_quadrant.md          quadrant analysis
│   │   ├── gui_solvable_tasks.md / gui_unsolvable_tasks.md
│   │   ├── paper_paragraphs.md             paper draft text
│   │   ├── task_design_rationale.md        50-task rationale (foundational)
│   │   └── terminal_vs_gui_constraints.md  CLI/GUI constraint enforcement
│   ├── claude_cli_terminus2/          terminus2 designs + Claude vs UI-TARS comparison
│   ├── gui_owl_reproduction_report.md
│   ├── m3a_t3a_parity_review.md
│   ├── mini_swe_agent_integration.md
│   ├── qwen3_variant_comparison.md
│   └── archive/                       ── superseded / implemented (kept for history) ──
│
└── final/                             ── canonical ground-truth references ──
    ├── AndroidWorld2026/
    │   ├── README.md                              workflow + Harbor viewer setup
    │   ├── androidworld_ground_truth_reference_v2.md   ← current GT (use this)
    │   └── archive/androidworld_ground_truth_reference_v1.md   ← superseded
    └── mobileworld/
        └── mobileworld_ground_truth_reference.md  117 GUI-only tasks
```

## Where to add things

Per [`../CLAUDE.md`](../CLAUDE.md):

| New doc kind | Goes in |
|---|---|
| Architecture/usage doc for developers | `docs/*.md` (top-level) |
| Reference Claude Code reads while implementing | `docs/ref_agent/` (keep <500 lines, in sync with code) |
| Technical design / analysis / proposal | `docs/design/<topic>/` |
| Replaces an older design | new file in `docs/design/<topic>/`; **add a banner** to the old one and move it to `docs/design/archive/` |
| Canonical ground-truth reference | `docs/final/<benchmark>/` |

Do **not** create docs in `dev docs/`, `dev_doc/`, `tmp_doc/`, the repo root,
or sibling top-level directories like `cli_dataset/`. Everything goes here.

## Recently moved

The 2026-05 cleanup (`refactor/cc-docs-cleanup`):

- Grouped 13 `androidlab_*` / `mobileworld_*` / `tier4_*` docs into per-topic
  subdirectories under `docs/design/`.
- Archived 21 superseded or implemented design docs into `docs/design/archive/`
  with status banners.
- Replaced the stale `ref_agent/code_structure.md` and `container_pool_broker.md`
  to match the post-`237ab9e0` layout (broker + container code now under
  `eval-runners/common/runtime/`).
- Marked `final/AndroidWorld2026/androidworld_ground_truth_reference.md` (v1)
  as superseded by v2 and moved it to `final/AndroidWorld2026/archive/`.
- Moved `cli_dataset/*.md` (which lived in the repo root) into
  `docs/design/tier4/`.
