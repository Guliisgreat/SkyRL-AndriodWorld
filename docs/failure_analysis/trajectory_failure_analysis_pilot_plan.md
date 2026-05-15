# Trajectory Failure Analysis — Pilot Plan (Single-Seed)

> **Goal:** validate the end-to-end pipeline and tune the rubric. Not the final §4.X analysis.
> **Scope:** N CLI agent results, single seed, AndroidWorld
> **Outcome:** working pipeline + frozen rubric ready for the full multi-seed run later

---

## What this plan is, and isn't

**Is:** a fast loop to confirm the pipeline works end-to-end and to iterate the rubric until it fits Android trajectories. The output of this plan is *infrastructure and a frozen rubric*, not the final paper figure.

**Isn't:** the full §4.X analysis. No GUI agents yet, no statistical claims, no chi-squared test, no figure for the paper. Those come later, on the full multi-seed run, using the rubric this plan produces.

Think of this as the rehearsal. The full performance comes after.

---

## Scope

- N CLI agent configs (whatever you have ready, single seed each)
- AndroidWorld
- ~100–150 failed trajectories total, depending on N and per-config success rates
- 1–2 days of work

No GUI agents in this pilot. They get added later when the rubric is frozen and the pipeline is known to work.

---

## Repository layout

```
analysis/failure_modes/
├── data/
│   ├── sample_index.jsonl
│   └── pilot_set.jsonl              # all sampled failures, ~100-150
├── rubric/
│   ├── rubric_v0.md                 # initial draft (TB lift + Android edits)
│   ├── rubric_v1.md, v2.md, ...     # iterations during this pilot
│   └── rubric_pilot_frozen.md       # output of this plan
├── annotations/
│   ├── pilot_human.jsonl            # ~30 trajectories you label by hand
│   └── notes.md                     # what you saw, what didn't fit
├── judge/
│   ├── prompt_v0.md, v1.md, ...
│   └── outputs/
│       └── pilot_judge.jsonl
└── stats/
    └── pilot_distribution.csv       # per-config failure-mode distribution
```

---

## Phase 1 — Sample failed trajectories

### 1.1 Verify logs

Inspect logs for all N configs. Confirm each contains: agent reasoning text, action emitted, observation/output, final state. If reasoning is missing for any config, drop that config from the pilot.

### 1.2 Sample

Take **all failed trajectories** from each config (no per-task sampling — at single seed there's only 1 trial per task). Tag each with `config`, `task_id`, `task_category`.

Output: `data/pilot_set.jsonl` with one row per failed trajectory, ~100–150 total.

---

## Phase 2 — Rubric v0

### 2.1 Lift TB taxonomy

Copy TB Appendix C verbatim into `rubric/rubric_v0.md`:

**Execution:** Disobey Specification, Step Repetition, Unaware of Termination Conditions
**Coherence:** Reasoning–Action Mismatch, Context Loss, Task Derailment
**Verification:** Premature Termination, No or Incorrect Verification, Weak Verification

For each leaf: framing, 5-step decision procedure, exclusion criteria.

### 2.2 Light Android edits

- *Disobey Specification:* exclusion criteria reference content provider URIs / settings keys / package names instead of filesystem paths.
- *Weak Verification:* "authoritative evaluator" framing references `dumpsys` / `content query` / `sqlite3` reads against the system source of truth, not pytest.

### 2.3 Read 10 trajectories

Pick 10 random failures from `pilot_set.jsonl`. Read end-to-end without classifying. Note in `annotations/notes.md`: what failure types did you see, and did anything not fit any leaf cleanly?

If something genuinely doesn't fit, draft a candidate Android-specific leaf (most likely "Surface Mismatch" — wrong app/activity/provider). Add only if Step 2.3 surfaces ≥2 trajectories that clearly don't fit existing leaves.

---

## Phase 3 — Hand-label a small set

### 3.1 Label 30 trajectories

You alone (no annotation partner needed for the pilot) label 30 trajectories drawn from `pilot_set.jsonl`. Mix across configs.

For each: `{trajectory_id, primary_leaf, rationale}`. Output: `annotations/pilot_human.jsonl`.

### 3.2 Notice what's hard

Track in `annotations/notes.md`:

- Which trajectories were ambiguous between two leaves
- Which exclusion criteria felt wrong
- Whether any leaf seems to never fire (might be merge-able)
- Whether any cluster of trajectories is forced into a bad-fit leaf (might need a new leaf)

This is the rubric-tuning input. **Do not iterate the rubric yet.** Just take notes.

### 3.3 Decide on rubric edits

Based on Step 3.2 notes, edit the rubric:
- Sharpen exclusion criteria for any leaf-pair that was ambiguous
- Merge leaves that never fired
- Add a leaf only if a cluster of trajectories systematically didn't fit

Save as `rubric/rubric_v1.md`. If you make further edits later, version as `v2.md`, etc.

---

## Phase 4 — Build and test the judge

### 4.1 Judge prompt v0

Write `judge/prompt_v0.md`:

```
SYSTEM:
You classify failure modes in agent trajectories on AndroidWorld. Read the trajectory and assign exactly one primary failure leaf from the taxonomy.

[Full content of rubric_v1.md]

Output JSON:
{
  "primary_leaf": "<leaf_name>",
  "rationale": "<2-3 sentences citing specific steps>",
  "confidence": "<high|medium|low>"
}

USER:
Trajectory ID: {trajectory_id}
Config: {config}
Task: {task_id} ({task_description})

Steps:
{formatted_step_log}

Final outcome: {success_or_failure_with_details}
```

Format each step as `Step N: [reasoning] → [action] → [observation]`. Truncate observations at 2000 chars; always include the final 5 steps in full.

### 4.2 Run judge on the 30 hand-labeled trajectories

Use Opus 4.6 high-reasoning. Output: `judge/outputs/pilot_judge.jsonl`.

### 4.3 Compare

Compute agreement between judge and your hand labels on the 30 trajectories.

- **≥85% agreement:** judge is reasonable. Proceed.
- **70–85%:** look at disagreements. Often the issue is rubric, not judge — go back to Phase 3.3, edit rubric, regenerate judge prompt, re-run.
- **<70%:** something is wrong. Either the prompt format is bad (judge isn't reading trajectories properly), the rubric is too ambiguous, or the model is wrong. Diagnose before iterating.

Per-leaf check: any leaf where judge disagrees on >30% of cases needs the rubric tightened for that specific leaf.

---

## Phase 5 — Run judge on full pilot set

### 5.1 Run

Run the validated judge prompt on all ~100–150 trajectories in `pilot_set.jsonl`. Cost: ~$50–100. Output: `judge/outputs/pilot_judge.jsonl` (overwrites the 30-row version).

### 5.2 Build distribution

Per-config failure-mode distribution: rows = configs, columns = leaves, cells = counts.

Output: `stats/pilot_distribution.csv`.

### 5.3 Sanity-check the result

Look at the distribution. Three things to check:

- **Does any leaf get >70% of all failures across all configs?** If yes, the rubric is too coarse — that leaf likely contains hidden sub-distinctions.
- **Does any leaf get <2% across all configs?** If yes, it might be merge-able with a sibling.
- **Do the configs look meaningfully different from each other?** If all CLI configs have nearly-identical distributions, that's good (within-paradigm consistency). If they look wildly different, the rubric may be picking up on noise rather than the failure mode.

Write findings to `annotations/notes.md`.

### 5.4 Decide if rubric is ready

Two outcomes:

- **Pipeline works, rubric stable, distribution sensible:** freeze the rubric. Copy `rubric_v1.md` (or whichever version is current) to `rubric_pilot_frozen.md`. **Pilot done.**
- **Distribution reveals a problem:** iterate the rubric one more time, re-run the judge on the full pilot set. Maximum 2 iterations after the initial v0→v1 step. If still not stable, the taxonomy needs structural rework — escalate before committing to the multi-seed run.

---

## Definition of done

- [ ] Pipeline runs end-to-end without manual fixups
- [ ] Rubric is frozen (`rubric_pilot_frozen.md`)
- [ ] Judge agreement with your hand labels ≥85% on 30-trajectory check
- [ ] Per-config distribution exists and looks sensible
- [ ] `annotations/notes.md` documents what was hard and how the rubric evolved

---

## What you carry forward to the full run

When you later run the full multi-seed analysis (per ALE-216):

1. **`rubric_pilot_frozen.md` becomes `rubric_frozen.md`.** No more rubric changes.
2. **Judge prompt is reusable as-is.** Same model, same format.
3. **Repository layout is reusable.** Just expand to multi-seed sampling.
4. **Add the GUI agents.** Re-run calibration with annotation partner on a 20-trajectory mixed CLI/GUI set. Validation set jumps to 120. Sample size jumps to ~380.

The pilot's job is to make sure all of that runs smoothly and the rubric is right. Saves you from discovering rubric problems on day 4 of the full run.

---

## Time budget

- Phase 1: 1–2 hours (data prep)
- Phase 2: 2–3 hours (rubric v0)
- Phase 3: 3–4 hours (hand-labeling 30 + notes + edits)
- Phase 4: 2–3 hours (judge build + 30-trajectory check)
- Phase 5: 2–3 hours (full pilot run + sanity check + freeze)

**Total: 1–2 days.** Single owner, no annotation partner needed for the pilot.

---

## Critical guardrails

1. **Don't iterate the rubric on the full pilot result.** Iterate during Phase 3 (on the 30 hand-labeled set) and at most once after Phase 5.3. Beyond that, you're rubric-shopping.

2. **Don't promote pilot findings into paper claims.** The pilot's distribution is on a small sample, single seed, CLI-only. It's not publishable — it's diagnostic.

3. **Document what didn't work.** If a leaf was ambiguous, write that down. The full run will hit the same ambiguity if you don't.

4. **Stop and escalate** if rubric won't stabilize after 2 iterations or judge agreement won't reach 85%. The taxonomy probably needs structural rework, not more rubric tweaks.
