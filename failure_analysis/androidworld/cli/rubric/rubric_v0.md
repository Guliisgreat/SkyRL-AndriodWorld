# Rubric v0 — Failure-Mode Taxonomy for AndroidWorld CLI Trajectories

**Status:** v0. Lifted verbatim from Terminal-Bench Appendix C, with light Android-domain edits (clearly marked) to two leaves.

**Source:** Merrill et al., *Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces*, arXiv:2601.11868v1, Appendix C ([html](https://arxiv.org/html/2601.11868v1#A3)).

**Construction:** TB Appendix C is itself a refinement of MAST (Pan et al., 2025). TB simplified MAST for single-agent CLI use: dropped multi-agent-only modes (conversation reset, information withholding, ignored other-agent input) and merged "disobey task spec" + "disobey role spec" since CLI doesn't enforce roles. Per-leaf rubrics were refined using the Docent platform.

**Coverage gap to flag:** TB C.1 lists **9 leaves** (including *Task Derailment*) but TB C.2 provides detailed LLM-judge rubrics for only **8 of them**. Task Derailment has only a one-sentence framing in C.1 and no decision procedure or exclusion criteria. This rubric retains all 9 leaves; the Task Derailment entry below is annotated as needing rubric work, likely during Phase 3.3 after hand-labeling.

---

## Top-level structure (verbatim from TB)

Three broad classes:

- **Execution** — *Disobey Specification*, *Step Repetition*, *Unaware of Termination Conditions*
- **Coherence** — *Context Loss*, *Task Derailment*, *Reasoning–Action Mismatch*
- **Verification** — *Premature Termination*, *No or Incorrect Verification*, *Weak Verification*

The pilot's primary-leaf assignment is single-label: each trajectory gets exactly one leaf. Co-occurring failures are noted in `notes.md` but not assigned.

---

## C.1 Taxonomy summary (verbatim from TB)

- **Disobey Specification:** the agent materially contradicts explicit task directives (hard or soft), such as required methods, sources of truth, constraints, or required output locations.
- **Step Repetition:** the agent re-executes the same phase (same sub-goal, tool, target, and underlying method) multiple times without a meaningful strategy change, including abort-loops and redundant verification runs.
- **Unaware of Termination Conditions:** the agent continues acting past a reasonable stopping point, i.e. after clear success, after established futility, or after declaring completion, without justification or need.
- **Reasoning–Action Mismatch:** the agent's stated reasoning or claims (e.g., "tests passed," "requirements satisfied") are contradicted by its observable actions, logs, or artifacts.
- **Context Loss:** the agent forgets or contradicts relevant recent context, either about environment state (files, configs, errors) or semantic commitments (plans, instructions, clarified goals).
- **Task Derailment:** the agent deviates from the intended objective or focus of a given task, potentially resulting in irrelevant or unproductive actions.
- **Premature Termination:** the agent declares the task complete or presents a final answer before satisfying explicit objectives or before delivering required artifacts/verification, without providing a concrete, actionable handoff acknowledging the remaining gaps.
- **No or Incorrect Verification:** the agent marks the task completed or bypasses a designated verifier without performing a substantive check of required properties on the actual final deliverable (or ignores failing core checks).
- **Weak Verification:** the agent relies on verification that fails to cover task-critical properties, including fabricating data that should have been recovered or derived from specified sources, while still using those checks to justify progress.

---

## C.2 Per-leaf rubrics

### Disobey Task Specification

**Framing.**
Disobey task specification concerns material contradictions to explicit directives in the task, including both hard directives ("must," "required," "shall," explicit prohibitions) and soft directives ("should," "recommended," "aim to"). Pure response-format/schema violations are excluded. Violations include ignoring or replacing required methods, constraints, sources of truth, or required output locations. Using the wrong source of truth counts even if the result appears plausible. Transient violations fully reversed before completion are ignored. Acceptable substitutions due to environment constraints are allowed if demonstrably equivalent via strong proof (tool-native introspection, passing the eval/check script, checksum/bytewise equality, or independent cross-check). Soft-guidance departures only count when they clearly undermine the task's stated intent or expected behavior.

**Decision Procedure.**

1. **Locate directives.** Identify hard or soft directives from task/system instructions: required methods/sources, success criteria, required output paths, or prohibitions/recommendations. *If none present:* no match.
2. **Check for contradiction.** Determine if the agent ignored or replaced at least one directive, for example:
   - Using a placeholder instead of the required implementation
   - Performing a forbidden operation
   - Using the wrong source of truth/metric
   - Altering/fabricating data instead of recovering it
   - Failing to measure/verify a mandated numeric constraint
   - Failing to produce required artifact at the specified path
   - Using Tool Y when "use exactly Tool X" and X is available

   *Exceptions:* Extra copies elsewhere are acceptable if correct artifact exists at required path; "use X if available; otherwise Y" permits Y unless explicitly forbidden.
3. **Assess materiality.**
   - Response-format/schema issues only → no match
   - Shortfalls (i.e. numeric) despite attempting mandated method → no match
   - Wrong source of truth or missing required output → material
   - Soft-guidance violation that undermines task intent → material
4. **Check for correction.** If the agent fully corrected/reversed the violation before completion such that final outcome satisfies all directives → no match.
5. **Decide.** If Steps 2–3 satisfied and Step 4 not satisfied → match; otherwise → no match.

> **ANDROID EDIT — exclusion criteria.** Where TB anchors directives on filesystem paths, on Android the analogous "required output locations" are content-provider URIs (e.g. `content://com.android.contacts/...`), settings keys (`settings get global ...`), system DB paths (`/data/data/com.android.providers.calendar/databases/calendar.db`), or specific package/activity targets (`com.android.deskclock/.AlarmsMainActivity`). When evaluating directive contradiction in Android trajectories, treat these as the equivalents of TB's "required output paths". Filesystem paths under `/sdcard/`, `/storage/emulated/0/` are also valid when the task explicitly references them.

---

### Step Repetition

**Framing.**
Step Repetition occurs when the agent re-executes the same phase (same sub-goal, same tool/effect, same target) with semantically or conceptually identical actions. A material change meaningfully alters strategy, algorithm, mode, or information state; superficial edits (formatting, parameter tweaks that do not change mode, refactors preserving the same method) are not material. Regenerating artifacts implementing the same underlying method counts as repetition. Switching tools, changing algorithms, or introducing meaningfully different inputs counts as progress. Repeated initiations of the same phase that never complete (abort-loops) are an explicit subtype.

**Decision Procedure.**

1. **Verify preconditions.** Confirm phases/sub-goals are identifiable and multiple distinct agent blocks/turns exist. *If either missing:* no match.
2. **Collect signals.** Extract: phase grouping, distinct tool-call blocks (with block-level deduplication), outcome classification (success/error/interrupted), parameters/flags/code identity, intent statements.
3. **Apply block-level deduplication.** Each tool-call block counts as at most one attempt per unique action. Do not count multiple lines, echoed commands, or parallel outputs within the same block as separate attempts.
4. **Trigger check.** Within a single phase, do two or more semantically/conceptually identical actions occur across distinct blocks? *If no:* no match.
5. **Assess identity.**
   - **Semantic identity:** Same tool, same effective operation, same target inputs/paths, same effective flags/arguments (ignoring whitespace/verbosity tweaks)
   - **Conceptual identity:** Same underlying method/algorithm and inputs, even if code/scripts differ
   - **Not identical:** Different I/O routing, different targets, parameters altering operation mode
6. **Classify category.**
   - Post-error-blind-retry
   - Post-success repetition
   - Verification repetition (exceeds N=2 for simple read-only probes)
   - Abort-loop repetition (repeated initiations without outcomes)
7. **Apply exclusions.**
   - Material changes (different algorithm/mode, different inputs/targets, switching tools) → not repetition
   - Diagnostic-only changes (logging flags, `2>&1`) → do not break identity
   - Up to 2 identical performance-tuning re-runs → allowed
   - First retry after incomplete/interrupted attempt → not counted
8. **Decide.** Repetition count ≥ 2 within any single phase → match; otherwise → no match.

---

### Unaware of Termination Conditions

**Framing.**
Failure-to-stop occurs when an agent continues acting beyond a reasonable stopping point — after success has been achieved, after futility is established, or when the agent prematurely declares completion before success conditions are met. It captures unnecessary continuation, lack of halting after confirmed futility, and premature finalization.

**Decision Procedure.**

1. **Verify preconditions.** A stopping point must be identifiable:
   - Explicit success criteria, OR
   - Strong implicit success evidence (verifier pass, validated artifact), OR
   - Futility (two consecutive identical failures with no progress), OR
   - Explicit finalization instructions

   *If none present:* no match.
2. **Identify triggering condition.** One of the following must occur:
   - Success condition satisfied
   - Futility established
   - Agent explicitly claims/signals completion
3. **Classify violation type.**
   - **C1 (After Success):** Agent continues the completed subgoal for ≥ 2 additional turns (1 verification turn allowed)
   - **C2 (After Futility):** After two consecutive identical failures, agent continues same failing approach
   - **P1 (Premature Completion):** Agent claims completion before success conditions are met
4. **Apply exclusions.**
   - One verification turn after success → allowed
   - Hygiene-only turns (renaming, formatting) → not counted
   - Meaningful strategy change → resets futility counter
   - Tool-call echoes within single turn → not counted
5. **Decide.**
   - C1 with ≥ 2 redo turns after success → match
   - C2 with ≥ 1 further attempt without strategy change → match
   - P1 with explicit completion before required criteria → match
   - Otherwise → no match

---

### Context Loss

**Framing.**
History loss occurs when the agent forgets or contradicts relevant recent context. Two major forms exist: (1) **state-memory loss** — forgetting concrete state (files created, errors resolved, configs applied); (2) **context-memory loss** — forgetting semantic commitments (instructions, constraints, plans, prior reasoning). A match occurs when later actions/claims are incompatible with previously established state or context within the same window.

**Decision Procedure.**

1. **Verify preconditions.** Identify a recent contiguous window without major resets containing at least one established:
   - State (environmental fact: file created, dependency installed, error fixed), OR
   - Context (semantic commitment, plan, instruction, constraint, prior reasoning)

   *If neither exists:* no match.
2. **Identify contradiction.** Look for later behavior that:
   - Acts as if earlier state/context never occurred
   - Reverts to older assumptions
   - Re-asks answered questions or redoes completed steps
   - Ignores earlier constraints, instructions, or reasoning
3. **Classify violation type.**
   - **State Contradiction:** Agent behaves as if state updates never happened (recreating resources, using stale outputs)
   - **Context Contradiction:** Agent forgets semantic context (ignoring constraints, switching tasks after clarification, contradicting own reasoning)
4. **Apply exclusions.**
   - Acknowledged uncertainty or legitimate recovery attempts
   - Harmless re-checks
   - Explicit environment resets
   - Pure formatting issues with no context reliance
   - Contradictions within same tool block
5. **Decide.** Contradiction present AND no exclusion applies → match; otherwise → no match.

---

### Task Derailment

**Framing (verbatim from TB C.1; not detailed in C.2).**
The agent deviates from the intended objective or focus of a given task, potentially resulting in irrelevant or unproductive actions.

**Decision Procedure (TB does NOT provide a detailed rubric for this leaf — placeholder, to be sharpened in Phase 3.3).**

1. **Identify task objective.** From the task prompt, extract the primary goal and the artifact/result it requires. *If no clear objective:* no match.
2. **Look for sustained deviation.** Within ≥ 2 consecutive agent turns, does the agent pursue a sub-goal that does not advance the primary objective? Examples on Android: exploring an unrelated app, reading the contacts DB when the task is about Calendar, configuring system settings unrelated to the task.
3. **Distinguish from Context Loss.** If the deviation traces to *forgetting* what the task was, prefer Context Loss. Task Derailment applies when the agent's stated intent itself drifts from the task.
4. **Distinguish from Reasoning–Action Mismatch.** If the agent's reasoning correctly identifies the goal but actions go elsewhere, prefer Reasoning–Action Mismatch.
5. **Decide.** Sustained deviation (≥ 2 turns) with no later return to the original objective and no reset event → match; otherwise → no match.

> **NOTE:** This rubric is a Phase-2 placeholder. If hand-labeling in Phase 3 surfaces ≥ 3 trajectories that "feel like derailment" but the placeholder doesn't capture cleanly, sharpen here in v1. If hand-labeling never invokes this leaf, the v1 rubric should consider merging it into Context Loss.

---

### Reasoning–Action Mismatch

**Framing.**
Reasoning–action mismatch evaluates whether an agent's stated reasoning/conclusions and binding commitments from the task/interface contract align with observable actions and outputs. Decision principle: if a claim/requirement says X but behavior/artifacts show not-X, that's a mismatch. Environment/tool failures only count when the agent proceeds as if success occurred or asserts outcomes contrary to evidence.

**Decision Procedure.**

1. **Identify commitments/claims.** From transcript and task instructions, identify: required output format/protocol, declared method/provenance, success/verification assertions. *If none present:* no match.
2. **Pre-check: JSON-only filter.** If all contradictions are JSON format/structure issues and none blocked core deliverables/validations → no match.
3. **Collect behavioral evidence.** Examine: executed commands/tool calls, generated artifacts/files, logs/errors, timestamps/order, final responses/formatting.
4. **Compare commitments to evidence. Apply materiality rule** — count only if:
   - **Repeated:** 2+ independent instances of same contradiction class, OR
   - **Blocking:** Violates required spec/contract or prevents completion/tooling
5. **Apply clarifications.**
   - Judge claims against evidence available when claim was made
   - Later failures create mismatch only if agent repeats success claim, proceeds as if successful, or relies on earlier claim without reconciliation
   - Core requirements: items affecting acceptance/grading (required files/paths, metrics, verification artifacts, mandatory methods)
   - Ignore benign deviations (trailing newline, harmless comments)
6. **Decide.** Clear contradiction that is repeated or blocking → match; otherwise → no match.

---

### Premature Termination

**Framing.**
Premature termination occurs when an agent declares completion or presents a final answer before meeting explicit task objectives or providing required verifications/critical data that were obtainable or already obtained but not delivered via required output channels. The focus is on whether necessary, explicitly specified information for task success was exchanged or verified. Involuntary endings (timeouts, crashes) are excluded. A concrete, actionable handoff that enables continuation avoids a match.

**Decision Procedure.**

1. **Identify objectives.** Extract explicit objectives and required verifications/data from task prompt, success criteria, or built-in checks. Do not infer implicit checks. *If none identifiable:* no match.
2. **Confirm agent-declared ending.** Did the agent explicitly declare completion or present final outputs as if done? Exclude involuntary endings. *If no:* no match.
3. **Check for unmet necessities.** Are any explicit objectives, required verifications, or critical data missing from required output channel(s)? Include items obtained but not delivered via required channels. *If no:* no match.
4. **Evaluate handoff.** Did the agent:
   - (a) Clearly flag infeasibility/incompleteness with concrete, actionable handoff (exact commands, file paths, parameters), OR
   - (b) Provide sufficient instructions enabling continuation?

   *If yes:* no match.
5. **Decide.** Agent ended with explicit necessities missing AND claimed success or presented proxies as final → match; otherwise → no match.

---

### No or Incorrect Verification

**Framing.**
This rubric flags missing or irrelevant verification of required properties, with completion defined as calling `mark_task_complete()`. It distinguishes core functional properties (correctness of behavior/edits, success metrics, minimality when central) from peripheral structural properties (format, filenames, ordering, mere existence). When core properties exist, the agent must verify at least one with an observed, substantive result before completion. Self-assertions ("looks good") are insufficient. Verification of non-conforming artifacts cannot satisfy core verification. Failing core results ignored at completion are a match.

**Decision Procedure.**

1. **Identify required properties.** From task/evaluator, classify properties:
   - Core functional: Correctness, required metrics, minimality when central
   - Peripheral structural: Format, filenames, ordering, mere existence

   *If no required properties:* no match.
2. **Check completion status.** Did agent call `mark_task_complete()`? *If no:* go to Step 5.
3. **Check for explicit admission.** Does agent explicitly acknowledge inability or that required properties are not met? *If yes:* no match.
4. **Assess core verification at completion.** Consider only checks on the required final deliverable under method constraints. Self-assertions do not count.
   - No substantive result for any core property → match
   - Failing core result ignored → match
   - Core property verified with observed compliant result → no match
   - Only peripheral properties exist: any observed relevant result → no match; none/self-assertion only → match
5. **No completion: check for verifier bypass.** Was a designated verifier for core properties provided/available? If so, and no substantive authoritative result ever appears → match; otherwise → no match.

> **ANDROID NOTE.** Android CLI agents call `python android_env.py finish --status complete` rather than `mark_task_complete()`. Treat that as the equivalent completion call. Android tasks rarely have a designated runtime verifier exposed to the agent — most success conditions are evaluated post-hoc against system state. The "core verification" the agent should attempt is reading authoritative system state via `dumpsys`, `content query`, or `sqlite3` against the relevant provider/database.

---

### Weak Verification

**Framing.**
Weak verification and data fabrication are distinct but related failure modes. Verification is weak when checks do not cover properties that must hold for true correctness. Fabrication occurs when the agent creates or alters data that should have been measured, recovered, or derived from specified sources, and treats it as authentic. Relying solely on an authoritative official evaluator is sufficient unless additional explicit essentials are stated. Declared limitations can mitigate narrower verification if claims are correspondingly narrowed.

**Decision Procedure.**

1. **Identify data fabrication.** Did the agent generate or alter outputs/source data that should have been recovered/derived from existing artifacts, and treat result as genuine? Include modifying evaluation target/environment to make checks pass. **Require reliance:** Count only if fabricated artifact is used to satisfy requirement, pass check, or serve as deliverable. *Set `data_fabrication` flag.*
2. **Identify verification actions.** Does transcript show agent using checks to judge progress/completion (tests, assertions, comparisons, metrics, end-to-end trials)? *If none:* `weak_verification = false`.
3. **Extract essentials.**
   - **Explicit requirements:** Critical properties for correctness from task/instructions
   - **Authoritative evaluator:** If designated, treat its checks as essentials
   - **Implied prerequisites:** Prerequisites whose failure makes explicit requirements impossible
4. **Compare coverage to essentials.**
5. **Check decisiveness and mitigation.**
6. **Decide output.**

**Tie-breakers and exclusions:** authoritative evaluator rules; absence of verification; brittleness exceptions; inconclusive-only exceptions; verified constraints; strong coverage.

> **ANDROID EDIT — authoritative evaluator framing.** TB anchors "authoritative evaluator" in pytest/eval-script style runtime checks. On Android there is rarely a runtime evaluator exposed to the CLI agent. The closest equivalents — to be treated as the authoritative source of truth in Android trajectories — are direct reads of system state:
> - `adb shell dumpsys <service>` (e.g. `dumpsys alarm`, `dumpsys notification`, `dumpsys wifi`)
> - `adb shell content query --uri content://...` against the relevant provider
> - `adb shell sqlite3 /data/data/<package>/databases/<db>.db "SELECT ..."` against system / app DBs
> - `adb shell settings get <namespace> <key>`
>
> Verification that confirms a UI element or app's *internal* state without cross-checking against the system source of truth (e.g. confirming an event was created by re-opening the calendar UI but never reading `com.android.providers.calendar/calendar.db`) is **weak verification**. Verification that fabricates the result (e.g. agent answers from prior knowledge instead of querying the live device state) triggers the `data_fabrication` flag.

---

## MAST → TB → AndroidWorld mapping (verbatim from TB Table 4)

| MAST label | TB refined label | High-level category |
|---|---|---|
| 1.1 Disobey task specification | Disobey Specification | Execution |
| 1.2 Disobey role specification | — (merged into 1.1) | — |
| 1.3 Step repetition | Step Repetition | Execution |
| 1.5 Unaware of termination conditions | Unaware of Termination Conditions | Execution |
| 1.4 Loss of conversation history | Context Loss | Coherence |
| 2.3 Task derailment | Task Derailment | Coherence |
| 2.6 Reasoning–action mismatch | Reasoning–Action Mismatch | Coherence |
| 2.1 Conversation reset | — (multi-agent only) | — |
| 2.2 Fail to ask for clarification | — (env doesn't support) | — |
| 2.4 Information withholding | — (multi-agent only) | — |
| 2.5 Ignored other agent's input | — (multi-agent only) | — |
| 3.1 Premature termination | Premature Termination | Verification |
| 3.2 Weak verification | Weak Verification | Verification |
| 3.3 No or incorrect verification | No or Incorrect Verification | Verification |

---

## Iteration log

- **v0 (this file)** — TB Appendix C lifted verbatim. 2 Android edits applied to *Disobey Specification* (output-location framing) and *Weak Verification* (authoritative-evaluator framing). Task Derailment given a placeholder rubric since TB C.2 omits it.
- v1 onwards — populate after Phase 3 hand-labeling of 30 trajectories surfaces specific ambiguities.
