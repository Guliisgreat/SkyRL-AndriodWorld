# Autoresearch-Style Prompt Optimization for Terminus_2 Agent

**Status**: Draft — awaiting review
**Date**: 2026-03-18
**Author**: Claude Code

---

## 1. Context & Goal

We want to maximize the **oracle upper-bound success rate** of the Terminus_2 agent on AndroidWorld terminal tasks. The Terminus_2 agent uses Harbor's LiteLLM + Chat class (not Claude CLI directly), responds in structured JSON, and executes commands via subprocess. Its system prompt lives in a `.txt` template file (`android-json.txt`).

The Claude SDK agent already achieved **92% SR (80/87)** via 4 rounds of autoresearch prompt optimization. We want to replicate this approach for Terminus_2.

### Key Differences from Claude SDK Autoresearch

| Dimension | Claude SDK | Terminus_2 |
|---|---|---|
| Prompt format | Python module (`build_system_prompt()`) | `.txt` template with `%PLACEHOLDER%` |
| LLM interface | Claude CLI (subprocess) | Harbor LiteLLM (async Python) |
| Response format | Free-form Bash tool use | Structured JSON: `{analysis, plan, commands, task_complete}` |
| Runner | `claude_code_cli_oracle.py` | `run_terminus2_oracle.py` |
| Template loading | `load_prompt_module()` → registry | `_load_harbor_template()` → hardcoded mapping |
| Current baseline SR | 69% (before optimization) | Unknown — needs baseline run |
| Existing template content | Minimal (4 principles, 3 rules) | Substantial (DB paths, exploration strategy, shell escaping) |

### Notable: Existing Template Has App-Specific Content

The current `android-json.txt` already contains **common app database paths** (calendar.db, contacts2.db, etc.) and package-specific paths. This is borderline leakage but provides utility. The autoresearch process should decide whether to keep, generalize, or remove these.

## 2. Architecture Changes Required

### 2.1 Template Variant System

Currently, `AndroidTerminus2Agent` loads templates by parser name only — there's no way to select a prompt variant. We need:

**Change 1**: Add `template_override` parameter to `AndroidTerminus2Agent.__init__()`:

```python
def __init__(
    self,
    ...
    template_override: str | None = None,  # NEW: path to custom template file
):
    self.template_override = template_override
```

**Change 2**: Use override in `run()`:

```python
if self.template_override:
    template = Path(self.template_override).read_text()
else:
    template = _load_harbor_template(self.parser_name)
```

**Change 3**: Add `--template` CLI flag to `run_terminus2_oracle.py` and `run_terminus2_agent.py`:

```bash
python run_terminus2_oracle.py \
  --data val_data_seed7_terminal.jsonl \
  --template ../../skyrl_agent/agents/android/terminus2/templates/optimized-v1.txt \
  --model gpt53codex \
  --broker-url http://localhost:9200 --pool-size 16 --max-attempts 4
```

### 2.2 Optimized Template File

Create `templates/optimized-v1.txt` as a copy of `android-json.txt`. This is the optimization target — the researcher edits only this file.

### 2.3 File Layout

```
skyrl-agent/examples/run_terminus2/autoresearch/
├── DESIGN.md          → This design doc (symlink or copy)
├── program.md         → Instructions for the AI researcher agent
└── results.tsv        → Experiment log (append-only)

skyrl-agent/skyrl_agent/agents/android/terminus2/templates/
├── android-json.txt           → Original baseline (preserved)
└── optimized-v1.txt           → Optimization target (researcher edits)
```

## 3. Evaluation Protocol

### 3.1 Two-Phase Evaluation (Cost Control)

Same pattern as Claude SDK autoresearch, adapted for Terminus_2:

**Phase A — Diagnostic Subset (16 tasks)**

We reuse the same 16-task subset from the Claude SDK autoresearch. This allows direct comparison and ensures the same failure categories are tested.

```bash
cd /shared/ligu/projects/SkyRL-AndriodWorld-integrate-terminus2/skyrl-agent/examples/run_terminus2
python run_terminus2_oracle.py \
  --data ../../data/androidworld_original/val_data_seed7_terminal.jsonl \
  --tasks 4,11,26,51,56,61,79,87,92,95,97,98,99,100,101,104 \
  --template ../../skyrl_agent/agents/android/terminus2/templates/optimized-v1.txt \
  --model gpt53codex \
  --parser android-json \
  --broker-url http://localhost:9200 --pool-size 16 --max-attempts 4
```

**Phase B — Full Eval (87 tasks)**

Only triggered if Phase A attempt-1 SR meets acceptance threshold:

```bash
python run_terminus2_oracle.py \
  --data ../../data/androidworld_original/val_data_seed7_terminal.jsonl \
  --template ../../skyrl_agent/agents/android/terminus2/templates/optimized-v1.txt \
  --model gpt53codex \
  --parser android-json \
  --broker-url http://localhost:9200 --pool-size 16 --max-attempts 4
```

### 3.2 Metrics — Hybrid Approach

Same as Claude SDK:

- **Attempt-1 SR** (primary, used for accept/reject): tasks passing on first attempt
- **Total SR** (secondary, reported only): tasks passing across all retry attempts

### 3.3 Baseline

Before optimization begins, we need a baseline run on the 16-task diagnostic subset using the unmodified `android-json.txt` template. This establishes the starting numbers.

**Model**: `gpt53codex` via LiteLLM. This is the target deployment model for Terminus_2.

### 3.4 Acceptance Rules

- **Phase A → Phase B gate**: attempt-1 SR on diagnostic improves by >=2 tasks over current best
- **Accept prompt change**: Phase B attempt-1 SR improves over previous best
- **Reject**: roll back (`git reset --hard <last accepted commit>`)

## 4. Failure Analysis & Hypotheses

The Terminus_2 agent's failure modes may differ from Claude SDK because:
1. **Structured JSON response** — the agent must output valid JSON, which constrains its reasoning style
2. **No free-form Bash** — commands are strings in an array, not arbitrary tool calls
3. **Harbor LiteLLM** — different token counting, cost tracking, and model compatibility
4. **Template-based prompt** — the entire system prompt is in the first message, not a system prompt field

### Expected Failure Categories (to validate with baseline)

| Category | Expected Impact | Prompt-Addressable? |
|---|---|---|
| Temporal reasoning | High (same as SDK) | Yes — add date/time guidelines |
| DB schema discovery | Medium | Partially — template already has exploration guidance |
| Shell escaping | Medium | Partially — template already has base64 guidance |
| JSON parse errors | Low-Medium | Yes — clarify format constraints |
| Output truncation | Low | Maybe — tune MAX_OUTPUT_CHARS guidance |
| App state sync | Medium | Yes — add force-stop/restart guidance |

### Transfer from Claude SDK Optimization

The Claude SDK's `optimized_terminal_v1.py` contains proven prompt sections that can be adapted:
- **Date & Time** section (temporal reasoning)
- **Database Operations** section (schema-first approach)
- **File Operations** section (media scan, content providers)
- **Messaging & Communication** section (SMS via service call)
- **App State Sync** section (force-stop/restart pattern)

These are all **app-agnostic** and directly transferable. The question is whether to start from scratch or seed the optimized template with these proven sections.

**Recommendation**: Start the optimized template as a copy of `android-json.txt`, then selectively incorporate proven sections from `optimized_terminal_v1.py` in early rounds. This gives the researcher a head start while still validating each change empirically.

## 5. Experiment Loop (up to 6 Rounds, or until 90%+ SR)

Same loop structure as Claude SDK autoresearch, with an **early-stop condition**:

```
┌─────────────────────────────────────────────────────────────┐
│  AI Researcher Agent (Claude Code)                          │
│                                                             │
│  1. Read results.tsv — what's been tried                    │
│  2. Read failure analysis from last run's results.jsonl     │
│  3. Hypothesize a prompt change                             │
│  4. Edit optimized-v1.txt                                   │
│  5. Leakage check — no app names, task-specific hints       │
│  6. Git commit the change                                   │
│  7. Run Phase A — 16-task diagnostic subset                 │
│  8. If attempt-1 SR < best + 2 → reject, git reset         │
│  9. If improvement → run Phase B (full 87)                  │
│  10. Accept if full SR improves; reject otherwise           │
│  11. Log result to results.tsv                              │
│  12. If total SR >= 90% (79/87) → STOP (target reached)    │
│  13. If round 6 → STOP (budget exhausted)                   │
│  14. Analyze new failures → loop to step 1                  │
└─────────────────────────────────────────────────────────────┘
```

**Budget**: Up to 6 rounds × (Phase A + Phase B). Stop early if total SR reaches **90%+** on full eval.

**Stopping criteria** (whichever comes first):
1. Total SR on full 87-task eval >= 90% (79/87)
2. 6 rounds completed

## 6. Leakage Guard

Same hard constraint as Claude SDK. The template must not contain:
- App names (Broccoli, Markor, Joplin, Pro Expense, etc.)
- Package names (`com.xxx.yyy`) — **Note**: the current `android-json.txt` baseline already has these. The optimized version should evaluate whether to keep or remove them.
- Database-specific table/column names
- Task-specific answers or values

**Exception**: System-level database paths (calendar.db, contacts2.db, mmssms.db) may be acceptable as they are Android system components, not benchmark-specific apps. The researcher should make a deliberate decision on this.

## 7. Implementation Plan

### Phase 0: Setup

- [ ] Add `--template` flag to `run_terminus2_oracle.py` and `run_terminus2_agent.py`
- [ ] Add `template_override` parameter to `AndroidTerminus2Agent`
- [ ] Pass `template_override` through `terminus2_common.py` bridge
- [ ] Create `templates/optimized-v1.txt` (copy of `android-json.txt`)
- [ ] Create `autoresearch/program.md` with researcher instructions
- [ ] Initialize `autoresearch/results.tsv` with header row
- [ ] Run baseline eval (Phase A: 16 tasks) to establish current numbers

### Phase 1–6: Autonomous Optimization Rounds

AI researcher runs up to 6 rounds following `program.md`, stopping early if total SR reaches 90%+.

### Final Report

- [ ] Document all experiments and outcomes
- [ ] Report final SR vs baseline
- [ ] Compare with Claude SDK results (92% target)

## 8. Decisions (Resolved)

| Question | Decision |
|---|---|
| Model | `gpt53codex` (target deployment model) |
| Seed optimized template from SDK prompt? | Pre-seed with proven SDK sections |
| Keep app DB paths in template? | Keep system-level (calendar.db, contacts2.db, mmssms.db), remove app-specific (com.broccoli.app, etc.) |
| Parser | android-json (simplest, purpose-built) |
| Diagnostic subset | Same 16 tasks as SDK (enables comparison) |
| Rounds | Up to 6, or until total SR >= 90% |
