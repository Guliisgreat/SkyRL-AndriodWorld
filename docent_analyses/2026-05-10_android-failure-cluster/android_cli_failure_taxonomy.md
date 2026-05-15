# Android CLI Agent Failure Taxonomy — Bottom-Up Discovery via Docent

**Date:** 2026-05-10 (updated after Phase 3 re-classification with Opus 4.7)
**Pool:** 211 CLI-solvable readable failures across 6 CLI agents on AndroidWorld seed 30
**Method:** Docent free-form clustering, no prior taxonomy
**Collection:** [https://docent.transluce.org/dashboard/a59d1430-18bd-4a8f-8c22-63a5aef49caa](https://docent.transluce.org/dashboard/a59d1430-18bd-4a8f-8c22-63a5aef49caa)

This document captures the discovered taxonomy, explains the methodology, compares against the prior `rubric_v1.md` taxonomy lifted-and-edited from Terminal-Bench, and proposes v2 changes.

> ## ⚠ Methodology note — counts come from Opus 4.7, not Mini
>
> The original Phase 3 classification used `openai/gpt-5.4-mini` (Docent skill default). That run produced misleading attributions: it conflated "agent wrote to wrong surface" with "finalization protocol issue" 67 times. Phase 3 was re-run with `anthropic/claude-opus-4-7` (without `reasoning_effort="high"`, which the Docent proxy doesn't accept for Anthropic models). **All counts in this document are from the Opus re-run; the Mini run is preserved in the Docent UI for comparison.**
>
> The lesson: for per-trajectory classification of complex multi-turn CLI traces, Mini is genuinely under-powered — it reaches for surface-level attributions rather than deep root-cause analysis. The 9-cluster *taxonomy itself* (Phase 2 synthesis) was robust between Mini and Opus, but the *trajectory-to-cluster assignment* (Phase 3) needs a stronger model. Both runs are in the Docent UI under reading plans `android_cli_failure_freeform_clustering`.

---

## Table of Contents

1. [Why and How to Use Docent](#1-why-and-how-to-use-docent)
2. [Discovered Taxonomy — 9 Clusters in Detail](#2-discovered-taxonomy--9-clusters-in-detail)
3. [Relation to v1 Taxonomy](#3-relation-to-v1-taxonomy)
4. [Recommendation for v2](#4-recommendation-for-v2)

---

## 1. Why and How to Use Docent

### Why use Docent for failure-mode discovery?

The standard pipeline for failure-mode analysis is to (1) lift a taxonomy from prior work (in our case, Terminal-Bench Appendix C → `rubric_v0.md`), (2) iterate based on evaluator judgment (→ `rubric_v1.md`), (3) classify trajectories at scale. This is **top-down**: the taxonomy comes first, the data is fitted to it.

The risk: a taxonomy lifted from a different domain (TB targets Linux CLI coding tasks) may **shoehorn** Android-specific failure modes into ill-fitting leaves, and may **invent** leaves that don't actually appear in the data. After v1 was built, we observed:

- **`Context Loss` and `Task Derailment` rarely fired** as primary classifications (0/211 and 2/211 respectively). They may not exist as distinct phenomena in Android CLI agents.
- **`Weak Verification` became a catch-all** (64% multi-label firing) — suggesting it absorbs cases that might deserve their own leaves.
- The judge's `_no_match_` rate was only 1%, but that's because the rubric was elastic — *every* failure was *forced* into something.

Docent solves both problems by **letting the data propose the taxonomy**:

1. **LLM summarizes each trajectory** in 3-5 sentences focused on root-cause behavior.
2. **One LLM call sees all 211 summaries** and proposes free-form categories (any number, any names, any granularity).
3. **LLM classifies each trajectory** into a proposed category — the same way the v1 judge worked, but with categories *derived from the data* rather than imposed on it.

The result is a **categorically different** view of the failure landscape — comparable to v1's view as a sanity check, and revealing patterns v1 missed.

Critically: Terminal-Bench itself used Docent to refine its rubric (per Appendix C: *"Docent is used to refine these rubrics, as it enables summarization, search, clustering, and targeted intervention, prompting clarifications and highlighting recurring patterns or ambiguities"*). What we did is the same methodology applied to a different domain (Android CLI vs Linux CLI).

### How the analysis was structured

**Phase 0 — Ingestion** (`docent_analyses/2026-05-10_android-failure-cluster/ingest.py`)
- Loaded `pilot_set.jsonl` filtered to 211 CLI-solvable readable failures
- Converted each trajectory (ATIF or MiniSWE native format) into a Docent `AgentRun`
- Each agent step → `AssistantMessage` with `tool_calls`; observations → `ToolMessage`
- Metadata: `task_id`, `task_name`, `agent_class`, `model`, `step_count`, `reward=0`
- Uploaded to a new collection `android-cli-failures-211`

**Phase 1 — Summarize** (211 LLM calls, ~$5)
- Per-trajectory prompt asked for 3-5 sentence root-cause summary
- **Deliberately avoided** v1-rubric language ("weak verification", "context loss", etc.) so the LLM described behaviors in its own words
- Output: 211 freeform summaries

**Phase 2 — Propose categories** (1 LLM call, ~$2)
- Single prompt with all 211 summaries
- Asked for 5–12 mutually-exclusive, collectively-exhaustive categories
- `reasoning_effort="high"`, `max_new_tokens=12000`
- Required structured output: `{name, description, example_signature}` per category
- Output: 9 proposed clusters

**Phase 3 — Classify** (211 LLM calls, ~$5)
- Per-trajectory prompt with the 9 categories from Phase 2
- LLM picked exactly one category per trajectory + cited transcript evidence
- Output: 211 classifications + per-agent / per-app aggregations

**Total cost:** ~$12 / ~30 min on `openai/gpt-5.4-mini`.

### How to inspect

- **Docent UI:** [https://docent.transluce.org/dashboard/a59d1430-18bd-4a8f-8c22-63a5aef49caa](https://docent.transluce.org/dashboard/a59d1430-18bd-4a8f-8c22-63a5aef49caa) — every per-trajectory summary and classification is browsable; the LLM's rationale cites transcript moments.
- **Local scripts:** `docent_analyses/2026-05-10_android-failure-cluster/ingest.py`, `cluster.py`, `proposed_clusters.md`.
- **Reading plan name** (for re-runs): `android_cli_failure_freeform_clustering`.

### Key design choices that shaped the outcome

| Choice | What we picked | Why |
|---|---|---|
| Summarization framing | Generic "root cause", no Android-app hints | Maximizes bottom-up signal; avoids domain-priors steering the LLM |
| Forbidden vocabulary | Excluded TB rubric names from summarizer prompt | Prevents v1 anchoring |
| Number of categories | LLM picks 5–12 | Wide range lets data drive; we got 9 |
| Reasoning effort | `high` for proposer, default for summarizer/classifier | Proposer needs deeper synthesis; per-item readings are fast |
| Scope | All 211 CLI-solvable readable failures | Full pool, not a subsample |

The **single most important decision** was forbidding v1-rubric language in the summarizer prompt. If the LLM had been told "summarize this in terms of weak verification, step repetition, ...", the proposer would have re-discovered v1. Instead, it described behaviors in fresh terms ("inserted into mmssms.db then verified against the same DB"), letting Phase 2 propose categories grounded in those behaviors.

---

## 2. Discovered Taxonomy — 9 Clusters in Detail

Total: **211 of 211 trajectories classified** (Opus run, 100% coverage).

| # | Cluster | n | % | CCLI | MSWE | T2 |
|---:|---|---:|---:|---:|---:|---:|
| 1 | **wrong_surface_or_storage_path** | 82 | **39%** | 16 | 37 | 29 |
| 2 | **speculative_value_fabrication** | 41 | 19% | 8 | 16 | 17 |
| 3 | **harness_command_interface_mismatch** | 29 | 14% | 0 | 0 | **29** |
| 4 | premature_negative_conclusion | 23 | 11% | 1 | 8 | 14 |
| 5 | schema_mapping_guessing | 14 | 7% | 3 | 7 | 4 |
| 6 | low_level_ipc_guessing | 11 | 5% | 7 | 3 | 1 |
| 7 | permission_or_api_wall_persistence | 6 | 3% | 1 | 3 | 2 |
| 8 | finalization_or_output_contract_violation | 3 | 1% | 0 | 2 | 1 |
| 9 | shell_construction_breakage | 2 | 1% | 1 | 0 | 1 |

### Mini → Opus delta (why we re-ran)

| Cluster | Mini | Opus | Δ | Interpretation |
|---|---:|---:|---:|---|
| wrong_surface_or_storage_path | 15 | **82** | **+67** | Mini under-attributed; this is the dominant pattern |
| finalization_or_output_contract_violation | **82** | 3 | **−79** | Mini hallucinated this category at scale |
| speculative_value_fabrication | 23 | 41 | +18 | Mini under-detected fabrication |
| shell_construction_breakage | 17 | 2 | −15 | Mini over-fired on quoting errors |
| harness_command_interface_mismatch | 31 | 29 | −2 | Stable across models |
| low_level_ipc_guessing | 10 | 11 | +1 | Stable |
| permission_or_api_wall_persistence | 7 | 6 | −1 | Stable |
| premature_negative_conclusion | 16 | 23 | +7 | Mini under-detected |
| schema_mapping_guessing | 9 | 14 | +5 | Mini under-detected |

The Opus distribution is the authoritative one for downstream decisions.

---

### Cluster 1 — `wrong_surface_or_storage_path` (82 / 39%)

**Description (verbatim from Docent LLM proposer):**
> The agent writes to or queries a backend that the app will not actually consume, such as a private database, shared folder, or generic provider, and then assumes that mutation is enough. The core mistake is choosing the wrong persistence/read surface.

**Transcript signature:** It inserts into SQLite or drops a file in shared storage, but verification through the app/provider never reflects the change.

**Per-agent breakdown:** ClaudeCodeCLI 16 / MiniSweAgent 37 / Terminus2 29 — affects all three agent classes, with MiniSweAgent most affected.

**Example trajectories:**
- Tasks 38, 65, 66, 67, 68, 79 (SMS) — agent writes directly to `mmssms.db` or the Simple SMS Messenger's `conversations.db`, while the eval reads via the system `content://sms/` provider, which doesn't reflect the direct DB write.
- Task 33 (MSWE) — Retro Music playlist: writes to MediaStore (`content://media/...`) instead of Retro Music's own internal DB.
- Task 10 (T2, MSWE) — Contacts: agent writes directly to `contacts.db` SQLite instead of going through the system Contacts ContentProvider.
- Tasks 22, 52, 53, 79 — Markor file ops: agent writes file to filesystem but Markor's index/UI doesn't refresh; or writes to wrong subfolder.
- Tasks 72, 73 — VLC: agent writes to `vlc_media.db` directly while the trigger-broken DB silently doesn't persist the write.
- Tasks 74, 88, 89 — OsmAnd: agent writes `.gpx` files when OsmAnd's newer schema uses SQLite for favorites/tracks.

**What distinguishes this from other clusters:**
- **NOT** *speculative_value_fabrication* — the values are correct; just stored in the wrong place.
- **NOT** *low_level_ipc_guessing* — the API choice is plausible (`sqlite3` or shared-storage file write); the *target surface* is the issue, not the API level.
- **NOT** *permission_or_api_wall_persistence* — Android didn't deny the write; the write succeeded *to the wrong place*.

**Why it dominates (39%):** This is the canonical "Android consumer-surface mismatch" pattern. Android apps frequently use Room-generated SQLite, FTS triggers, ContentObservers, or `notifyChange()` to propagate state. Writing to the underlying DB bypasses the change-notification machinery, so the consumer (UI, ContentProvider, MediaStore) doesn't see the update. This corresponds directly to v1's combination of **Disobey Specification (wrong source of truth, Android edit)** + **Weak Verification (verified through same surface as write)**.

---

### Cluster 2 — `speculative_value_fabrication` (41 / 19%)

**Description:**
> The agent invents concrete task data — timestamps, coordinates, note bodies, message text, track waypoints, filenames, or record contents — instead of extracting it from the source material. The core error is grounding-free value creation.

**Transcript signature:** The write contains hard-coded dates, GPS coordinates, or message bodies that were never grounded in the transcript's source data.

**Per-agent breakdown:** ClaudeCodeCLI 8 / MiniSweAgent 16 / Terminus2 17.

**Example trajectories:**
- Task 35 (T2) — Simple Calendar Pro "create a calendar event for tomorrow at 19h" — agent computed "tomorrow" using assumed timezone offset, didn't query device time first.
- Task 36 (MSWE) — Calendar recurring event — agent invented the day-of-week pattern.
- Task 38 (MSWE) — SMS reply — agent paraphrased the message body instead of using exact text.
- OsmAnd tasks — agent invents lat/lon coordinates for "Schaan, Liechtenstein", "Oberplanken, Liechtenstein", etc.

**What distinguishes this from other clusters:**
- **NOT** *schema_mapping_guessing* (cluster 5) — that's about inventing *internal mapping integers*; this is about inventing *task-domain data* (dates, places, message text).
- **NOT** *wrong_surface_or_storage_path* — wrong *where*; this is wrong *what*.

**Validates v1 addition:** This corresponds directly to the **Data Fabrication** leaf I added to v1. Bottom-up + Opus confirm it's a real, distinct, common failure mode. Stronger evidence than Mini (which had only 23 cases).

---

### Cluster 3 — `harness_command_interface_mismatch` (29 / 14%)

**Description:**
> The agent assumes it can use ordinary adb-shell or Unix commands, but the harness rejects the command tokens themselves as invalid verbs. It keeps retrying the same class of commands instead of realizing the execution interface is the blocker.

**Transcript signature:** Every turn is another `pm`/`cmd`/`ls`/`echo` probe that comes back `not a recognized verb`, and the agent never reaches app data.

**Per-agent breakdown:** ClaudeCodeCLI 0 / MiniSweAgent 0 / **Terminus2 29** — *exclusively* a Terminus2 failure mode. **Robust across Mini and Opus runs** (31 → 29).

**Example trajectories:**
- Task 109 (T2) — OpenTracks: "What was the longest distance covered in a mountain biking activity in the OpenTracks app?" — agent's `pm list packages` and `dumpsys` probes rejected.
- Task 110 (T2) — OpenTracks: similar — agent never accesses the OpenTracks DB.
- Task 113 (T2) — Calendar query: "How many attendees in 'Project Status Update'" — same harness-rejection pattern.

**What distinguishes this from other clusters:**
- **NOT** *Constraint Infeasibility* (which I added to v1) — that's about *Android* not supporting an action (e.g., reading the clipboard from shell). This is about the *Terminus2 harness* not recognizing standard command verbs.
- **NOT** *Tool-Format Error* — that's about quoting/escaping in a valid command. Here the *verb itself* is rejected.

**Why this is a major finding:** This pattern is **entirely invisible** in v1 — there's no leaf for harness-interface mismatch. Yet it accounts for **~30% of Terminus2's failures** (29 / 98) — and 0% of any other agent. It explains why Terminus2 has the worst success rate in the dataset (35%): the harness rejects the agent's commands before they can even attempt the task.

This is a **harness configuration issue**, fixable by either (a) loosening the Terminus2 command interface to match what agents expect, or (b) prompting the agent about the harness's restrictions.

---

### Cluster 4 — `premature_negative_conclusion` (23 / 11%)

**Description:**
> The agent treats an empty or partial query result as definitive and stops early, often returning `None` or a raw dump before isolating the requested subset. The failure is concluding from insufficient evidence rather than continuing the extraction path.

**Transcript signature:** A single `No result found` or truncated provider dump leads directly to `None`, even though the requested rows or titles were never fully filtered.

**Per-agent breakdown:** CCLI 1 / MSWE 8 / **T2 14** — Terminus2 most affected; ClaudeCodeCLI almost zero.

**Example trajectories:**
- Task 102 (MSWE) — Tasks app: "Which tasks with high priority are due the Monday after next" — agent's date filter returned empty; agent submitted "None".
- Task 104 (MSWE) — Tasks app: "Which tasks have I completed for October 19" — agent submitted truncated dump.
- Many Terminus2 calendar/tasks queries where the agent's filter returned 0 rows on the first try.

**What distinguishes this from other clusters:**
- **NOT** *Premature Termination* (TB sense) — TB's PT is about declaring *success* without verification. Here the agent declares a *negative* result without sufficient checking.

**Notable agent split:** ClaudeCodeCLI has only 1 of these (out of 37 CCLI failures). Both Claude models persist longer on retrieval tasks than the other 4 agents — they widen queries, try alternative filters, iterate. Terminus2 and MiniSWE models accept the first negative result more readily.

---

### Cluster 5 — `schema_mapping_guessing` (14 / 7%)

**Description:**
> The agent reverse-engineers hidden numeric or textual mappings from sparse database/APK evidence and then invents IDs, labels, or field semantics from pattern matching. The failure is overconfident schema inference, not just a bad write surface.

**Transcript signature:** It infers values like `category 13`, `importance = 3`, or a table-field meaning from a few rows or resource strings and writes them as if they were verified.

**Per-agent breakdown:** CCLI 3 / MSWE 7 / T2 4.

**Example trajectories:**
- Tasks 21, 48, 86 (Pro Expense) — agent invents `category=13` for "Education" by extrapolating from existing rows' integer pattern. The actual category-name → integer mapping isn't recoverable from data; the agent guesses anyway.

**What distinguishes this from other clusters:**
- Twin of `speculative_value_fabrication` (#2) but for *implementation-level integers* rather than *task-domain content data*.
- Together with #2, **total fabrication signal = 55 (26%)** — strongly corresponds to v1's *Data Fabrication* leaf.

**Why split this from #2:** The fabrication mechanism is different. #2 invents real-world content (dates, place names, message bodies). #5 invents *opaque internal mappings* (category enums, importance levels, sync-state codes). These warrant different mitigation strategies: #2 needs "ground answers in observed data"; #5 needs "discover mappings from app metadata before writing".

---

### Cluster 6 — `low_level_ipc_guessing` (11 / 5%)

**Description:**
> The agent drops to binder/service-call hacking and starts guessing transaction codes or shell app-op sequences for clipboard/SMS-style IPC without first confirming the correct API contract. It is not merely blocked; it is probing the wrong low-level protocol shape.

**Transcript signature:** Repeated `service call isms ...` or `service call clipboard ...` attempts end in Parcel/security errors, but the agent keeps varying transaction codes anyway.

**Per-agent breakdown:** **CCLI 7** / MSWE 3 / T2 1 — ClaudeCodeCLI dominant (64% of cluster). **Robust across Mini and Opus** (10 → 11).

**Example trajectories:**
- Task 27 — Clipboard: "Copy the following text to the clipboard: Tracking #: 5K672F4C". All 3 agents fail this with binder hacking.

**What distinguishes this from other clusters:**
- **NOT** *Reasoning–Action Mismatch* — reasoning and action both point at "use binder transactions"; the issue is binder transactions are *the wrong tool*.
- **NOT** *Step Repetition* — the agent varies transaction codes, not the same code.

**Why ClaudeCodeCLI dominates here:** Opus 4.7 has more training data about low-level Android internals (Stack Overflow `service call isms 5` recipes etc.). It "knows" these APIs exist and tries them — but they're internal, not designed for shell use, and the right API for clipboard/SMS is at a higher level.

---

### Cluster 7 — `permission_or_api_wall_persistence` (6 / 3%)

**Description:**
> The agent reaches an explicit permission, debuggability, or API wall and then keeps probing neighboring URIs or methods on the same blocked surface instead of pivoting. The pattern is stubborn persistence after a clear denial like `run-as` failure or unsupported provider writes.

**Transcript signature:** After `package not debuggable`, `UnsupportedOperationException`, or `Only sync adapters may write`, the agent just keeps trying similar URIs or methods on that same surface.

**Per-agent breakdown:** CCLI 1 / MSWE 3 / T2 2. **Stable across Mini and Opus** (7 → 6).

**Example trajectories:**
- Task 11 (MSWE) — Pro Expense delete: agent hits `run-as: not debuggable` and keeps trying `run-as` variants instead of pivoting to `su 0`.
- Task 21 (MSWE) — Pro Expense add: same `run-as` wall.
- Task 31 (T2) — Broccoli recipes: agent hits `Only sync adapters may write` on Calendar provider and keeps trying URIs of the same provider.

**What distinguishes this from other clusters:**
- **NOT** *harness_command_interface_mismatch* (#3) — that's the harness rejecting verbs. This is Android itself denying access at the OS/permission level.
- **NOT** *Step Repetition* — the agent varies the URI/method, but stays on the same blocked surface.

---

### Cluster 8 — `finalization_or_output_contract_violation` (3 / 1%)

**Description:**
> The agent has done the work or nearly done it, but loses at the end by violating the run protocol or output contract: malformed `finish`, combining multiple actions into one turn, or emitting the wrong completion format.

**Transcript signature:** The data change succeeds, but the final turn fails because `finish` is malformed, paired with another command, or sent in the wrong format.

**Per-agent breakdown:** CCLI 0 / MSWE 2 / T2 1. **Major shift from Mini** (was 82, now 3).

**Interpretation:** Mini was incorrectly assigning 79 trajectories here that Opus correctly classifies as *wrong_surface_or_storage_path*. The actual rate of finalization-protocol violations is small (1.4%). **This category is NOT a major v2 leaf candidate.**

---

### Cluster 9 — `shell_construction_breakage` (2 / 1%)

**Description:**
> The agent has a plausible path, but it keeps breaking the actual command string: bad quoting, embedded newlines, unsupported flags, malformed projections, or broken arithmetic/SQL.

**Transcript signature:** The transcript is full of `no closing quote`, `unexpected '('`, `Invalid column`, or `--limit` errors while the agent repeatedly edits one giant shell one-liner.

**Per-agent breakdown:** CCLI 1 / MSWE 0 / T2 1. **Major shift from Mini** (was 17, now 2).

**Interpretation:** Mini over-fired on this category, likely conflating "agent retried with different quoting" with "agent's intent was wrong". When Opus reads carefully, most apparent quoting-retry sequences are actually part of a larger wrong-surface or fabrication failure — the quoting fight is incidental, not the root cause. **The v1 `Tool-Format Error` leaf may be over-specified.**

---

## 3. Relation to v1 Taxonomy

### Direct mapping (Opus-validated)

| Bottom-up cluster | n | v1 leaf | Relationship |
|---|---:|---|---|
| wrong_surface_or_storage_path | **82** | Disobey Specification (Android edit) + Weak Verification | ✅ **VALIDATES v1's biggest leaves** — these cover the dominant failure mode |
| speculative_value_fabrication + schema_mapping_guessing | 55 | **Data Fabrication** (NEW in v1) | ✅ **STRONGLY VALIDATES v1** — 26% of failures, more than Mini suggested |
| permission_or_api_wall_persistence | 6 | Constraint Infeasibility (NEW in v1) + Step Repetition | partial — v1 covers the "wall" concept |
| shell_construction_breakage | 2 | **Tool-Format Error** (NEW in v1) | ⚠ **OVER-SPECIFIED in v1** — only 2 cases; mostly absorbed into other clusters |

**Strongest v1 validation:** the largest cluster (`wrong_surface_or_storage_path`, 39%) maps cleanly to v1's *Disobey Specification (Android-edit, wrong source of truth)* + *Weak Verification (Android-edit, verified through wrong surface)*. The v1 Android edits were exactly right for this dominant pattern.

**Strongest v1 over-specification:** *Tool-Format Error* was added in v1 based on AMBIG-1 noise from earlier heuristic analysis. Opus says only 2 trajectories fit this pattern as the *primary* failure — quoting issues are usually a side-effect of a wrong-surface or fabrication root cause.

### v1 leaves that DIDN'T emerge bottom-up (consistent with v1 evaluation)

- **Context Loss** — no bottom-up category. Validates v1 critique: leaf rarely fires.
- **Task Derailment** — no bottom-up category. Validates v1 critique: rare.
- **Step Repetition** — implicit in `permission_or_api_wall_persistence` and `harness_command_interface_mismatch` as a *modifier*, not a primary leaf.
- **Unaware of Termination Conditions** — no bottom-up category.
- **Reasoning–Action Mismatch** — appears as a *modifier* in several clusters (fabrication despite uncertainty, binder hacking despite knowing it's wrong), but not isolated.

### v1 leaves that were **missed** (the real additions for v2)

| Bottom-up cluster | n | % | v1 status | Strength of evidence |
|---|---:|---:|---|---|
| **harness_command_interface_mismatch** | 29 | 14% | **MISSING in v1** | Robust (Mini 31, Opus 29). 100% Terminus2. |
| **low_level_ipc_guessing** | 11 | 5% | **MISSING in v1** | Robust (Mini 10, Opus 11). 64% ClaudeCodeCLI. |
| **premature_negative_conclusion** | 23 | 11% | **MISSING in v1** | Sub-type of PT but distinct: "agent gives up *negative* answer" not "claims success" |

**Together these 3 missing categories account for 63 / 211 = 30% of failures.** v1's leaves cover the remaining 70% well (especially with the Data Fabrication and Constraint Infeasibility additions).

### Summary comparison (corrected)

| | v1 | Bottom-up (Opus) |
|---|---:|---:|
| Total primary leaves | 12 | 9 |
| Coverage of 211 failures | 99% (3 `_no_match_`) | 100% |
| Largest single leaf | Weak Verification (34%) | wrong_surface_or_storage_path (39%) |
| Best-validated v1 addition | — | Data Fabrication (26% combined, strong) |
| Best-validated bottom-up addition | — | harness_command_interface_mismatch (14%, robust) |
| Over-specified in v1 | Tool-Format Error (Opus: only 2 cases) | — |

**Updated framing:** v1 is largely correct. The Android edits captured the dominant pattern (wrong source of truth + verification through wrong surface), and the Data Fabrication addition was right. The genuine v2 additions are *harness-level* failure modes that TB's Linux-coding domain didn't have analogs for.

---

## 4. Recommendation for v2 (corrected)

### Two genuine v2 additions

#### **Change 1 — Add `Harness Command Interface Mismatch` as a primary leaf** (HIGH priority)

29 failures, 100% Terminus2, robust across Mini and Opus runs. The single biggest finding from this analysis.

Proposed leaf framing:
> The agent's commands are valid `adb shell` syntax, but the harness wrapper rejects them at the verb level ("not a recognized verb"). The agent keeps retrying similar commands instead of pivoting. Distinct from *Constraint Infeasibility* (about Android's capabilities) and *Tool-Format Error* (about argument syntax).

Without this leaf, ~30% of Terminus2's failures silently get attributed to "Terminus2 is worse" — misleading because the root cause is the *harness configuration*, not the agent.

#### **Change 2 — Add `Premature Negative Conclusion` as a primary leaf** (HIGH priority)

23 failures (11%), distinct from v1's *Premature Termination*. PT in v1 is about declaring *success* with unmet objectives; this is the opposite — agent declares a *negative* answer ("None", "no events found") after insufficient checking.

Proposed leaf framing:
> The agent treats an empty or partial query result as definitive and stops early on retrieval tasks, returning "None" or a raw dump before exhausting reasonable filter alternatives. Distinct from *Premature Termination*, which is about false-success claims.

#### **Optional Change 3 — Add `Low-Level IPC Guessing`** (MEDIUM priority — could be sub-flag)

11 failures (5%), 64% ClaudeCodeCLI. Actionable mitigation. Could be a primary leaf, or a `low_level_ipc_guessing` flag on RAM / Step Repetition.

### v1 changes to KEEP (validated by Opus)

| v1 addition | Status |
|---|---|
| **Data Fabrication** | ✅ STRONGLY VALIDATED — 26% combined (content + mapping), should remain a primary leaf. Optionally split into `Data Fabrication — Content` (19%) and `Data Fabrication — Mapping` (7%). |
| **Constraint Infeasibility** | ✅ KEPT — `permission_or_api_wall_persistence` and `harness_command_interface_mismatch` together align with the Android-capability concept |
| Disobey Specification Android edit | ✅ VALIDATED — the wrong-surface pattern dominates (39%) |
| Weak Verification Android edit | ✅ VALIDATED — verify-through-same-surface pattern is core to wrong_surface_or_storage_path |

### v1 changes to DROP or REVISIT

| v1 addition | Status |
|---|---|
| **Tool-Format Error** | ⚠ DROP or DEMOTE — only 2 Opus cases. Quoting retries are usually incidental to a deeper root cause (wrong surface, fabrication). Either remove or demote to a modifier flag. |
| Finalization or Output Contract Violation (proposed in earlier v2 draft) | ❌ DO NOT ADD — Mini artifact. Only 3 cases under Opus. |

### Revised v2 leaf list

**Execution**
1. Disobey Specification *(with Android edit, validated)*
2. Step Repetition
3. Unaware of Termination Conditions

**Coherence**
4. Reasoning–Action Mismatch
5. *(Context Loss → demoted to modifier — no primary firing)*
6. *(Task Derailment → demoted to modifier — rare)*

**Verification**
7. Premature Termination *(positive — false success claim)*
8. **Premature Negative Conclusion** *(NEW in v2 — negative — gave up early)*
9. No or Incorrect Verification
10. Weak Verification *(with Android edit, validated)*

**Data Integrity** *(v1 leaf, refined)*
11. Data Fabrication *(or split into 11a Content / 11b Mapping)*

**Constraint / Tool / Harness**
12. Constraint Infeasibility *(Android capability)*
13. **Harness Command Interface Mismatch** *(NEW in v2 — robust, Terminus2-specific)*
14. Low-Level IPC Guessing *(NEW in v2, optional — could be modifier instead)*

**Total: 12–14 primary leaves + 2 modifiers.** Compare to v1's 12.

Removed from my earlier v2 draft:
- ~~`Finalization or Output Contract Violation`~~ (Mini artifact)
- ~~`Tool-Format Error` as a primary leaf~~ (over-specified; demote)

### Open decision points

1. **Should `Harness Command Interface Mismatch` be a primary leaf or a harness-config flag?** It's 100% Terminus2 — if the harness is fixed, the leaf empties. Recommend: primary leaf for now (it documents the harness issue and is useful for cross-agent analysis), revisit after harness fix.

2. **Should Data Fabrication split into Content + Mapping?** The Opus run shows both sub-types are common (41 + 14). Splitting allows different mitigation strategies; keeping unified preserves a single "fabrication" label. Recommend: keep unified for primary classification, add a `fabrication_type` modifier flag.

3. **Should `Tool-Format Error` be removed entirely or kept as a rare leaf?** Opus says 2 cases. Recommend: drop from primary classification; if quoting analysis is needed, capture as a modifier.

### Validation plan for v2

Before adopting v2:
1. Hand-validate the 5 v2 leaves that changed (Harness Mismatch, Premature Negative, Data Fabrication split, Tool-Format demotion, Finalization removal) on 20 trajectories from the Docent UI.
2. Re-run the v1 LLM judge with v2 leaf definitions on all 211 trajectories.
3. Compare: does Weak Verification's primary rate change (since wrong_surface cases may now go to Disobey Spec instead)? Does Data Fabrication count rise to ~55 (matching Opus bottom-up)?

---

## Appendix — Inspection Links

- **Docent collection:** [https://docent.transluce.org/dashboard/a59d1430-18bd-4a8f-8c22-63a5aef49caa](https://docent.transluce.org/dashboard/a59d1430-18bd-4a8f-8c22-63a5aef49caa)
- **Reading plan:** `android_cli_failure_freeform_clustering` (in the Docent UI)
- **Local files in this session dir:**
  - `ingest.py` — converted 211 trajectories to Docent format
  - `cluster.py` — 3-phase clustering pipeline
  - `proposed_clusters.md` — the 9 categories with descriptions
  - `collection_id.txt` — Docent collection UUID
- **Prior v1 rubric:** `failure_analysis/androidworld/cli/rubric/rubric_v1.md`
- **Prior LLM judge results (v1):** `failure_analysis/androidworld/cli/judge/outputs/judge_results.jsonl`
