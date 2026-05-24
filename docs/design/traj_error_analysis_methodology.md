# Trajectory-Level Error Analysis Methodology

**Goal of this doc.** Give the team and Claude Code a reproducible recipe
for analyzing why an agent fails on Android (or any CLI-agent) tasks at
the trajectory level. The recommended approach is **bottom-up free-form
clustering with Docent** (so we discover the actual Android-native
failure patterns), with **Terminal-Bench Appendix C's 9-leaf taxonomy as
the reference cross-walk** (so emergent clusters can be reported in a
vocabulary that matches the broader CLI-agent literature).

This methodology was used to produce
`failure_analysis/androidworld/cli/rubric/rubric_v2.md` and
`docent_analyses/2026-05-10_android-failure-cluster/android_cli_failure_taxonomy.md`
on the prior 211-trajectory pilot. It supersedes any pure top-down
rubric-only flow.

---

## 1. When to use this

Run a trajectory-level error analysis when **you have ≥ ~50 failed
trajectories from one or more agents and you need to answer *why* they
fail in a form a paper or design doc can cite.**

| signal you should run this | example |
|---|---|
| Headline SR is known but the *failure mix* isn't | "Opus is 31/45 on Tier-4 — what are the 14 fails doing wrong?" |
| A new agent / model lands and you want to know if it fails like the others | "GUI-Owl just shipped — does it share MAI's failure profile?" |
| A taxonomy from prior work (TB, OpenMobile, etc.) doesn't obviously fit your domain | TB is Linux-CLI; you're on Android |
| Reviewers ask "are these failures stochastic noise or systematic?" | bottom-up cluster sizes answer this |

If you have < 50 failures, run a hand-read instead — the LLM clustering
won't give stable categories below that.

---

## 2. The recipe at a glance

```
                ┌────────── raw eval results ──────────┐
                │  eval-runners/results/.../results.jsonl  │
                └─────────────────┬──────────────────────┘
                                  ▼
       Step 1.  Filter failures to "agent-solvable, readable, reward=0"
                                  ▼
       Step 2.  Convert each trajectory into Docent's AgentRun format
                                  ▼
       Step 3.  Ingest into a fresh Docent collection
                                  ▼
       Step 4.  Phase 1 — per-trajectory root-cause summary
                  (no rubric-vocabulary priors — let the LLM describe
                   behavior in its own words)
                                  ▼
       Step 5.  Phase 2 — synthesis call sees all summaries → proposes
                          ≈ 5-15 free-form clusters
                                  ▼
       Step 6.  Phase 3 — classify every trajectory into one of the
                          proposed clusters (one primary + optional
                          secondaries)
                                  ▼
       Step 7.  Cross-walk each cluster onto TB Appendix C's 9-leaf
                taxonomy (Execution / Coherence / Verification × leaves)
                                  ▼
       Step 8.  Human spot-check ~10 % of trajectories; refine
                                  ▼
       Step 9.  Aggregate & report:
                  - cluster sizes (Android-native names)
                  - TB-leaf rollup
                  - per-agent / per-task-category breakdowns
                  - illustrative trajectory IDs per cluster
```

---

## 3. Prerequisites

| item | source / location |
|---|---|
| Docent account + API access | `https://docent.transluce.org`. Set `DOCENT_API_KEY` and `DOCENT_DOMAIN`. See `docent.env` for the template. |
| LLM judge (Opus 4.7 — **do not use Mini**) | Anthropic or Docent proxy. See pitfalls §11. |
| Eval results | `eval-runners/results/<AgentClass>_<model>_<yymmdd>_<HHMM>/results.jsonl` + the matching `atif_trajectories/<task_id>.json` |
| Ground-truth reference (for solvability filter) | `docs/final/cli_advantage/tier4_ground_truth_reference_v2.md` (Tier-4) or whichever doc gates which tasks are CLI-solvable |
| TB Appendix C taxonomy | the 9 leaves listed in §7 below, also encoded in `failure_analysis/androidworld/cli/rubric/rubric_v2.md` |
| Python deps | `docent-python` (the SDK), `openai` or `anthropic` for LLM calls |

---

## 4. Step 1 — Filter the failure pool

The bottom-up methodology is only meaningful on **failures the agent
*could* have solved**. Environment bugs, unsupported tasks, and
unreadable trajectories are noise that pollutes the cluster signal.

Apply three filters in order, dropping until you have your pool.

### 4.1 reward = 0

```python
[r for r in results if r['reward'] == 0]
```

### 4.2 solvable

A task is *solvable* iff there is an oracle command sequence that earns
reward = 1 on this image. For Tier-4 this is encoded in
`docker/androidworld_2026plusswipe_tier4/test_integration.py` —
`GOLDEN_PATHS` contains every solvable task. Drop tasks marked
`skip_reason=...` (e.g. the `text_emulator` SMS fixture path).

For other benchmarks, use whatever solvability marker exists. If no such
marker exists, document the exclusion as "no oracle verified" and treat
the pool as best-effort.

### 4.3 readable

A trajectory is *readable* iff it has ≥ 1 substantive turn and the JSON
parses to either ATIF schema or the runner's native format. Drop
trajectories that died inside the harness (no agent steps at all,
container-crash exit, hook rejection on step 0).

Keep an `excluded_set.jsonl` with one row per dropped trajectory and the
reason. This is the audit trail.

**Target size**: 50-500 trajectories. The 2026-05 pilot used 211.

Output: `pilot_set.jsonl` (one row per trajectory, with `task_id`,
`task_name`, `agent_class`, `model`, `trajectory_path`).

---

## 5. Step 2-3 — Ingest into Docent

### 5.1 Convert each trajectory to Docent's `AgentRun`

The conversion is mechanical — one assistant message per agent step,
one tool message per observation, system message at the top.

Reference implementation:
`docent_analyses/2026-05-10_android-failure-cluster/ingest.py`. Adapt
the `trajectory_to_messages()` function for your trajectory schema (ATIF
vs MiniSWE vs Terminus2 native all look slightly different).

Required metadata on each `AgentRun`:

| key | use |
|---|---|
| `task_id` | for joining back to results.jsonl |
| `task_name` | human-readable |
| `agent_class` | drives per-agent breakdowns later |
| `model` | drives per-model breakdowns |
| `step_count` | sanity-check (high step counts often correlate with timeout failures) |
| `reward` | always 0 in this pool, but encode anyway |

### 5.2 Create a fresh collection

Use a new collection per analysis — don't reuse old ones. Naming:
`<benchmark>-<failure-kind>-<n>`, e.g. `android-cli-failures-211`.

Persist the `collection_id` in `collection_id.txt` next to your ingest
script. **The collection ID is the single source of truth for the
analysis** — every later phase references it.

---

## 6. Phase 1-3 — Summarize, synthesize, classify

These three phases are the heart of the bottom-up flow.

### 6.1 Phase 1 — per-trajectory summarization (no taxonomy priors)

**Goal**: each trajectory gets a 3-5 sentence root-cause summary written
in *whatever vocabulary the LLM chooses*. The single most important
methodological choice here:

> **Do not inject TB or rubric vocabulary into the Phase-1 prompt.**
> No words like "weak verification", "context loss", "premature
> termination", "task derailment". You want the LLM to *describe what
> happened*, not classify it.

Prompt skeleton (adapt):

```
You are reading a single failure trajectory of an Android CLI agent.
The agent was asked to perform task: <task description>.
The agent did not earn reward.

Write a 3-5 sentence root-cause summary covering:
  - What the agent was trying to do (its strategy in plain language).
  - What blocked success (what did the system reject, return empty,
    or fail to verify).
  - The specific behavior that's the proximate cause of the failure
    (which step or which kind of step).

Do NOT use general taxonomic labels (e.g., "weak verification",
"premature termination"). Describe the behavior in concrete Android
terms (which app, which surface, which command).
```

Run per trajectory. Save outputs to `discovery/summaries.jsonl` with
fields `{trajectory_id, task_id, agent_class, root_cause,
agent_behavior_pattern, what_blocked_success, elapsed_sec}`.

**Cost**: with Opus 4.7 max-effort, ~$0.02 / trajectory. 200
trajectories ≈ $4.

### 6.2 Phase 2 — synthesize free-form clusters

One LLM call sees **all N summaries** concatenated and proposes
clusters.

Prompt skeleton:

```
You are reading N short root-cause summaries of Android CLI agent
failures. Each summary describes what one agent tried to do and what
blocked success.

Propose a clustering of these failures by failure mode. Aim for 5-15
clusters. For each cluster:

  - Cluster name (snake_case, behavior-focused — e.g.
    `wrote_to_wrong_app_data_store`, not `verification_failure`)
  - 1-2 sentence description in Android-native vocabulary
  - Transcript signature (a 1-sentence pattern a reader could spot in
    a trajectory to recognize this cluster)
  - Estimated fraction of the pool that fits

You may propose any number of clusters. Do not anchor on Terminal-
Bench or generic failure taxonomies — describe what the data shows.

After listing clusters, write a one-paragraph "overarching observation"
section about cross-cluster patterns.
```

Cost: 1 call, but the input is long (all summaries). Budget ~$2-5 on
Opus 4.7. Save output to `discovery/failure_modes.md`.

**Sanity check**: do the cluster names actually use Android vocabulary
(app names, content URIs, surface names) rather than generic terms? If
not, the prompt let too much TB leak in — re-write and re-run.

### 6.3 Phase 3 — classify every trajectory

Now use the Docent reading-plan / reading-skill mechanism (or your own
per-trajectory LLM call) to assign each trajectory to **one primary
cluster** + **0-2 secondary clusters**.

The Phase-3 LLM call should receive:
- The trajectory (full).
- The list of clusters (names + descriptions + transcript signatures
  from Phase 2).
- Instructions to pick one primary + optional secondaries, with
  evidence step IDs and a confidence value.

Schema for outputs (mirrors the existing `judge_labels.jsonl`):

```json
{
  "trajectory_id": "ClaudeCodeCLI_claudeopus47_seed30_t086",
  "primary_cluster": "fabricated_values_after_failed_or_truncated_read",
  "secondary_clusters": ["raw_sqlite_write_bypassed_app_pipeline"],
  "confidence": "high",
  "rationale": "...",
  "evidence_step_ids": [5, 11, 12]
}
```

Output: `cluster_labels.jsonl`. ~$0.02 / trajectory on Opus 4.7.

**Reproducibility note**: do not skip per-trajectory rationale +
evidence step IDs. They are what makes the analysis auditable.

---

## 7. Step 7 — Cross-walk emergent clusters to TB's 9 leaves

This is the step that makes the analysis comparable to the broader
literature. TB's 9 leaves (Merrill et al., *Terminal-Bench*, arXiv
2601.11868, Appendix C):

### Execution

- **Disobey Specification** — agent materially contradicts task directives (wrong consumer surface, wrong API level, wrong output protocol, data fabrication).
- **Step Repetition** — agent re-executes the same command class against the same surface without strategy change.
- **Unaware of Termination Conditions** — agent keeps acting past a clear stop signal (success confirmed, explicit denial, ≥ 2 identical errors).

### Coherence

- **Context Loss** — agent forgets / contradicts established device or task state.
- **Task Derailment** — sub-goal drifts from the task's primary objective.
- **Reasoning–Action Mismatch** — stated reasoning contradicts the actual command issued.

### Verification

- **Premature Termination** — agent declares completion before satisfying the objective.
- **No or Incorrect Verification** — agent finishes without any read against an authoritative surface.
- **Weak Verification** — agent verifies through a surface the consumer doesn't read from (verify-via-same-DB-as-write, app UI vs system provider).

### How to do the cross-walk

For each Phase-2 cluster, name **the single TB leaf it most cleanly
maps to**, plus optional secondary leaves it commonly co-occurs with.
This is a *human* judgement on a small set (5-15 clusters) — don't
automate it. Document the mapping as a small table in your report:

| emergent cluster | TB primary leaf | TB secondary leaves |
|---|---|---|
| `wrote_to_wrong_app_data_store` | Disobey Specification | Weak Verification |
| `raw_sqlite_write_bypassed_app_pipeline` | Disobey Specification | Weak Verification |
| `fabricated_values_after_failed_read` | Disobey Specification | Reasoning-Action Mismatch |
| `reconnaissance_burnout_no_mutation` | Step Repetition | Unaware of Termination |
| ... | ... | ... |

**Mapping rule of thumb**: every cluster should map cleanly onto
exactly one primary TB leaf. If a cluster genuinely doesn't fit, that's
evidence the TB taxonomy is missing a leaf for this domain — report it
explicitly rather than forcing the fit. (In practice, on the 2026-05
pilot, all 11 emergent Android clusters mapped onto 6 of TB's 9 leaves
— *Context Loss* and *Task Derailment* never showed up, suggesting
they're rare or absent in Android CLI agents.)

### Report both views

Final paper / design doc should show:

- **Emergent clusters** — the domain-specific Android-native names with
  their actual data-driven counts. This is the *honest reading* of the
  data.
- **TB-leaf rollup** — totals after summing the emergent clusters under
  each parent TB leaf. This is the *comparable view* for cross-paper
  referencing.

---

## 8. Step 8 — Human spot-check

Pick ~10 % of trajectories (stratified by primary cluster — e.g. 2-3
from each cluster) and **manually verify** that the LLM's assigned
cluster + rationale match what the trajectory actually does.

Spot-check artifacts:

```
annotations/
  v<N>_validation_picks.jsonl    # which trajectory IDs were picked
  v<N>_validation_sample.md      # human-written notes per trajectory
  v<N>_validation_results.csv    # agree / disagree / re-label decisions
```

Use the disagree set to:
1. Refine the Phase-3 prompt (e.g. tighten cluster descriptions).
2. Catch systematic biases (e.g. one cluster absorbing too many
   borderline cases).
3. Decide if the taxonomy needs another iteration.

Target: ≥ 85 % agreement after one iteration. If you're below that,
re-run Phase 3 with the refined prompts.

---

## 9. Output artifacts

A complete trajectory-level error analysis ships with the following
files, organized in a date-stamped directory:

```
docent_analyses/<yyyy-mm-dd>_<benchmark>-<failure-kind>/
  ├── ingest.py                # repeatable Docent ingestion
  ├── collection_id.txt        # Docent collection ID (single SoT)
  ├── pilot_set.jsonl          # the trajectory pool used
  ├── excluded_set.jsonl       # what was filtered out, with reasons
  ├── discovery/
  │     ├── summaries.jsonl    # Phase-1 per-trajectory summaries
  │     └── failure_modes.md   # Phase-2 proposed clusters
  ├── classification/
  │     └── cluster_labels.jsonl   # Phase-3 per-trajectory labels
  ├── annotations/
  │     ├── validation_picks.jsonl
  │     ├── validation_sample.md
  │     └── validation_results.csv
  ├── crosswalk_to_tb.md       # emergent cluster → TB leaf mapping
  └── <analysis_name>.md       # the report doc (paper-ready)
```

The final report (the last file) is the deliverable. Structure:

1. **Setup** — pool, filter criteria, agent × model × seed coverage
2. **Methodology** — Phase 0-3 + cross-walk
3. **Cluster catalog** — one section per emergent cluster: description, transcript signature, count, % of pool, TB-leaf parent, 2-3 example trajectory IDs
4. **TB-leaf rollup** — totals per TB leaf (the comparable view)
5. **Per-agent / per-task-category breakdowns** — which clusters dominate for each agent
6. **Headline observations** — 1-3 cross-cluster patterns
7. **Validation** — spot-check agreement %, any taxonomy refinements
8. **Appendix** — list of trajectory IDs per cluster, full validation table

---

## 10. How the results feed downstream work

| stakeholder | what they use the analysis for |
|---|---|
| **Paper writers** | headline failure-mode distribution + TB cross-walk; per-agent breakdowns; example transcripts as appendix |
| **Agent / prompt designers** | which clusters to target with prompt edits (e.g. *"add a 'do not write to AOSP providers when third-party app is named' instruction"*) |
| **Benchmark designers** | which tasks systematically trip a failure mode → candidates for inclusion / exclusion in future tiers |
| **Reviewers / replicators** | the artifact set is reproducible — given the Docent collection ID, all per-trajectory labels can be re-generated |

---

## 11. Pitfalls (we already hit these)

| pitfall | how to avoid |
|---|---|
| **Mini-class LLM (e.g. `gpt-5.4-mini`) for Phase 3** | It conflates surface-level with root-cause attributions. The 2026-05 pilot saw 67 trajectories misclassified before re-running with Opus 4.7. **Use Opus 4.7 or equivalent for Phase 3**, not Mini. The Phase-2 cluster *names* survived Mini→Opus (synthesis is easier), but per-trajectory assignment didn't. |
| **TB / rubric vocabulary leaking into Phase 1** | Re-write the Phase-1 prompt to forbid generic terms. Symptom: every cluster name ends in "_failure" or "_error". |
| **Phase 2 producing too few clusters (≤ 3) or too many (> 20)** | Re-run with explicit "aim for 5-15" constraint and a temperature ~0.3 (not 0.0 — slight diversity helps cluster proposal). |
| **Cluster definitions too abstract** | If you can't write a one-sentence "transcript signature" for a cluster, it's not actionable. Re-prompt Phase 2 to require one per cluster. |
| **Skipping the human spot-check** | Without it, you have no idea if the LLM labels are right. 10 % minimum, stratified across clusters. |
| **Reusing an old Docent collection** | Always ingest into a fresh collection per analysis. Old collections accumulate stale annotations / reading plans. |
| **No `_no_match_` escape in Phase 3** | The judge will force every trajectory into *some* cluster. Add an explicit `_no_match_` option in the Phase-3 prompt and review any trajectories that land there — they often reveal a missing cluster. |
| **Not separating CLI-solvable vs CLI-unsolvable failures** | The same task on the same agent can fail for completely different reasons (real reasoning failure vs environment-side issue). Filter before clustering. |
| **Cross-walk forced 1-to-1** | If a Phase-2 cluster genuinely splits across two TB leaves with no clear primary, allow it and report it (e.g., `intent_launch_treated_as_persistence` straddles *Premature Termination* and *No Verification*). Forcing a single leaf hides real structure. |

---

## 12. Concrete starting points

When you start a new traj-error analysis from this branch:

1. Copy the directory layout from `docent_analyses/2026-05-10_android-failure-cluster/` — most of the scripts (ingest, probe, cluster) are adaptable.
2. Reuse `failure_analysis/androidworld/cli/scripts/condense_trajectory.py` if your trajectories are too long for the LLM context (it does a deterministic step-merge).
3. Reuse the v2 rubric's framings (`failure_analysis/androidworld/cli/rubric/rubric_v2.md` §C.1-C.2) for the TB-leaf descriptions in your cross-walk table.
4. Use the prior 211-trajectory analysis as a **sanity check**: if your new analysis re-discovers `wrote_to_wrong_app_data_store` and `raw_sqlite_write_bypassed_app_pipeline` as the top-2 clusters, the methodology is working.

---

## 13. References

- **Methodology** — `docent_analyses/2026-05-10_android-failure-cluster/android_cli_failure_taxonomy.md` (the original write-up of this approach).
- **TB taxonomy source** — Merrill et al., *Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces*, arXiv:2601.11868v1, Appendix C.
- **TB taxonomy adapted to Android** — `failure_analysis/androidworld/cli/rubric/rubric_v2.md`.
- **Docent platform** — Transluce. The platform supports both the ingestion API and reading-plan / reading-skill primitives used in Phases 2-3. Set credentials in `docent.env`.
- **Prior bottom-up analysis on Terminal-Bench itself** — `docent_analyses/2026-05-06_gpt51-failures/gpt51_codex_failure_modes.md` (good example of the same methodology applied to GPT-5.1-Codex on TB).
