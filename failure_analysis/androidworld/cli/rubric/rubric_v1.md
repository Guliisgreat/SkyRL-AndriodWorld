# Rubric v1 — Failure-Mode Taxonomy for AndroidWorld CLI Trajectories

**Status:** v1. Iterates on `rubric_v0.md` after empirical evidence from 211 LLM-judge classifications and the `claudecodecli_18_cli_solvable.md` deep dive.

**Source:** Merrill et al., *Terminal-Bench*, arXiv:2601.11868v1, Appendix C (verbatim base) + Android-specific extensions developed in this work.

**Diff from v0** (full rationale in *Iteration log* section at the bottom):

| Change | Type | Reason |
|---|---|---|
| Add `data_fabrication` leaf | NEW | Promoted from sub-flag of WV. 0% leaf-level capture in v0 despite being the dominant pattern in OsmAnd, Pro Expense, geocoding, clipboard guessing failures. |
| Add `constraint_infeasibility` leaf | NEW | Replaces `_no_match_` for tasks structurally incompatible with the agent's no-screen / no-root constraint set. |
| Add `tool_format_error` leaf | NEW | Resolves AMBIG-1 (Step Rep vs RAM on shell-quoting retries). 8.7% of v0 classifications were ambiguous between these two. |
| Replace RAM "JSON-only filter" pre-check | EDIT | TB's pre-check is irrelevant on Android; replaced with Android-equivalent "shell-output-format-only" filter. |
| Add Android examples to Context Loss | EDIT | v0 fired CL only 6 times across 211. Examples clarify when CL applies in CLI domain (re-discovery patterns). |
| Sharpen Task Derailment with Android examples | EDIT | v0 fired TD only 2 times. Concrete multi-app drift scenarios added. |
| Tighten Premature Termination handoff carve-out | EDIT | v0 carve-out exempted SMS-infeasibility cases too easily; requires *evidence of attempting alternative surfaces*. |
| Drop Unaware-P1 sub-type (merged into PT) | EDIT | Removes overlap; P1 was literally PT. |
| Complete Weak Verification Step 6 decision logic | FIX | TB Step 6 was "Decide output" with no actual logic. v1 specifies. |
| Add **C.4 Tie-breaker matrix** | NEW SECTION | 4 overlap pairs (DS↔WV, PT↔Unaware-P1, WV↔NoIV, StepRep↔CL) get explicit resolution rules. |

---

## Top-level structure

Four broad classes (was 3 in v0; added Constraint/Tool):

- **Execution** — *Disobey Specification*, *Step Repetition*, *Unaware of Termination Conditions*
- **Coherence** — *Context Loss*, *Task Derailment*, *Reasoning–Action Mismatch*
- **Verification** — *Premature Termination*, *No or Incorrect Verification*, *Weak Verification*, *Data Fabrication*
- **Constraint / Tool** *(NEW)* — *Constraint Infeasibility*, *Tool-Format Error*

The pilot's primary-leaf assignment is single-label per trajectory; co-occurring failures recorded as `secondary_leaves[]`.

---

## C.1 Taxonomy summary

**Execution leaves**
- **Disobey Specification:** the agent materially contradicts explicit task directives (hard or soft) — required methods, sources of truth, output locations, or prohibitions.
- **Step Repetition:** the agent re-executes the same phase (same sub-goal, tool, target, underlying method) ≥ 2× without strategy change.
- **Unaware of Termination Conditions:** the agent continues acting past a reasonable stopping point (after success or after established futility), excluding the "claimed done before done" case which is now exclusively *Premature Termination*.

**Coherence leaves**
- **Context Loss:** the agent forgets or contradicts established state or context within a recent window.
- **Task Derailment:** the agent's pursued sub-goal drifts from the task's primary objective for ≥ 2 consecutive turns without returning.
- **Reasoning–Action Mismatch:** stated reasoning/claims contradict observable actions, artifacts, or final state.

**Verification leaves**
- **Premature Termination:** the agent declares completion before objectives are met, *without* evidence of having attempted available alternative surfaces.
- **No or Incorrect Verification:** the agent marks completion without performing any substantive check on required properties.
- **Weak Verification:** the agent verifies through a surface the consumer doesn't read from, or covers wrong properties.

**Data-Integrity leaf** *(promoted from WV sub-flag in v0)*
- **Data Fabrication:** the agent generates or alters outputs/source data that should have been recovered/derived from authoritative sources, and treats the result as genuine.

**Constraint / Tool leaves** *(NEW)*
- **Constraint Infeasibility:** the task as specified requires a capability the agent's constraint set forbids (e.g., screen interaction, root, file pull). The agent recognized correctly but had no path forward.
- **Tool-Format Error:** the agent's *intent* was correct but the emitted command was malformed (shell quoting, escape sequence, base64 encoding) and the loop of retries didn't constitute reasoning failure.

---

## C.2 Per-leaf rubrics

### Disobey Task Specification

**Framing.** *(verbatim from TB C.2)*
Disobey task specification concerns material contradictions to explicit directives in the task, including both hard directives ("must," "required," "shall," explicit prohibitions) and soft directives ("should," "recommended," "aim to"). Pure response-format/schema violations are excluded. Violations include ignoring or replacing required methods, constraints, sources of truth, or required output locations. Using the wrong source of truth counts even if the result appears plausible. Transient violations fully reversed before completion are ignored. Acceptable substitutions due to environment constraints are allowed if demonstrably equivalent via strong proof (tool-native introspection, passing the eval/check script, checksum/bytewise equality, or independent cross-check). Soft-guidance departures only count when they clearly undermine the task's stated intent or expected behavior.

**Decision Procedure.** *(verbatim from TB C.2)*

1. **Locate directives.** Identify hard or soft directives from task/system instructions: required methods/sources, success criteria, required output paths, or prohibitions/recommendations. *If none present:* no match.
2. **Check for contradiction.** Determine if the agent ignored or replaced at least one directive (placeholder instead of required impl; forbidden operation; wrong source of truth/metric; altering/fabricating data instead of recovering it; failing to measure mandated numeric constraint; missing required artifact; using Tool Y when "use exactly Tool X").
   *Exceptions:* Extra copies elsewhere are acceptable if correct artifact exists at required path; "use X if available; otherwise Y" permits Y unless explicitly forbidden.
3. **Assess materiality.**
   - Response-format/schema issues only → no match
   - Shortfalls (numeric) despite attempting mandated method → no match
   - Wrong source of truth or missing required output → material
   - Soft-guidance violation that undermines task intent → material
4. **Check for correction.** If the agent fully corrected/reversed the violation before completion such that final outcome satisfies all directives → no match.
5. **Decide.** If Steps 2–3 satisfied and Step 4 not satisfied → match.

> **ANDROID EDIT — required output locations.** On Android, "required output locations" map to:
> - Content-provider URIs (e.g. `content://com.android.contacts/...`, `content://sms/`, `content://media/external/audio/playlists`)
> - Settings keys (`settings get global ...`, `settings put secure ...`)
> - System DB paths (`/data/data/com.android.providers.calendar/databases/calendar.db`, `/data/data/com.android.providers.telephony/databases/mmssms.db`)
> - Specific package/activity targets (`com.android.deskclock/.AlarmsMainActivity`)
> - Filesystem paths under `/sdcard/`, `/storage/emulated/0/` when explicitly named.

> **ANDROID EDIT — fabrication carve-out.** v0 listed "altering/fabricating data" as a Step 2 example. v1 promotes this to its own leaf (*Data Fabrication*). When fabrication is the primary failure mode, prefer *Data Fabrication* over Disobey Specification. Use DS for fabrication only when the task *explicitly* prohibits fabricating (e.g., "use the values from this CSV exactly").

---

### Step Repetition

**Framing.** *(verbatim from TB C.2)*
Step Repetition occurs when the agent re-executes the same phase (same sub-goal, same tool/effect, same target) with semantically or conceptually identical actions. A material change meaningfully alters strategy, algorithm, mode, or information state; superficial edits (formatting, parameter tweaks that do not change mode, refactors preserving the same method) are not material. Regenerating artifacts implementing the same underlying method counts as repetition. Switching tools, changing algorithms, or introducing meaningfully different inputs counts as progress. Repeated initiations of the same phase that never complete (abort-loops) are an explicit subtype.

**Decision Procedure.** *(verbatim from TB C.2)*

1. **Verify preconditions.** Confirm phases/sub-goals are identifiable and multiple distinct agent blocks/turns exist. *If either missing:* no match.
2. **Collect signals.** Extract: phase grouping, distinct tool-call blocks (with block-level deduplication), outcome classification, parameters/flags/code identity, intent statements.
3. **Apply block-level deduplication.** Each tool-call block counts as at most one attempt per unique action.
4. **Trigger check.** Within a single phase, do two or more semantically/conceptually identical actions occur across distinct blocks? *If no:* no match.
5. **Assess identity.**
   - **Semantic identity:** Same tool, same effective operation, same target inputs/paths, same effective flags/arguments
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
   - **(NEW)** Shell-quoting variations to fix encoding errors → not Step Repetition; assign to *Tool-Format Error* instead.
8. **Decide.** Repetition count ≥ 2 within any single phase → match; otherwise → no match.

> **ANDROID EDIT — quoting/encoding retries.** On Android, agents frequently emit `adb shell '...'` commands with embedded quotes that fail with shell-syntax errors. The agent then retries with slightly different quoting until the encoding works. This is **not Step Repetition** (the *intent* was right; only the encoding was wrong). Assign these to *Tool-Format Error*. Step Repetition applies when the *intent* itself is the same and unchanged across the failed retries (e.g., agent runs the same `INSERT INTO sms` 5× when the underlying issue is the SmsProvider permission, not quoting).

---

### Unaware of Termination Conditions

**Framing.**
Failure-to-stop occurs when an agent continues acting beyond a reasonable stopping point — after success has been achieved, or after futility is established. *(v1 narrowing: P1 "Premature Completion" sub-type is removed and assigned exclusively to* Premature Termination *— see C.4.)*

**Decision Procedure.**

1. **Verify preconditions.** A stopping point must be identifiable:
   - Explicit success criteria, OR
   - Strong implicit success evidence (verifier pass, validated artifact), OR
   - Futility (two consecutive identical failures with no progress)
   *If none present:* no match.
2. **Identify triggering condition.** Either: success condition satisfied, OR futility established.
3. **Classify violation type.**
   - **C1 (After Success):** Agent continues the completed subgoal for ≥ 2 additional turns (1 verification turn allowed)
   - **C2 (After Futility):** After two consecutive identical failures, agent continues same failing approach
4. **Apply exclusions.**
   - One verification turn after success → allowed
   - Hygiene-only turns (renaming, formatting) → not counted
   - Meaningful strategy change → resets futility counter
   - Tool-call echoes within single turn → not counted
5. **Decide.** C1 with ≥ 2 redo turns after success → match; C2 with ≥ 1 further attempt without strategy change → match; otherwise → no match.

> **ANDROID NOTE — `step_count == max_turns`.** Hitting max_turns is **not** automatically Unaware. Hitting max_turns while still pursuing different approaches each turn is an *environmental cap*, not a termination-awareness failure. Apply Unaware only when there's identifiable futility *and* the agent kept emitting the same failing approach (C2).

---

### Context Loss

**Framing.** *(verbatim from TB C.2)*
History loss occurs when the agent forgets or contradicts relevant recent context. Two major forms exist: (1) **state-memory loss** — forgetting concrete state (files created, errors resolved, configs applied); (2) **context-memory loss** — forgetting semantic commitments (instructions, constraints, plans, prior reasoning). A match occurs when later actions/claims are incompatible with previously established state or context within the same window.

**Decision Procedure.**

1. **Verify preconditions.** Identify a recent contiguous window without major resets containing at least one established State or Context. *If neither:* no match.
2. **Identify contradiction.** Look for later behavior that:
   - Acts as if earlier state/context never occurred
   - Reverts to older assumptions
   - Re-asks answered questions or redoes completed steps
   - Ignores earlier constraints, instructions, or reasoning
3. **Classify violation type.**
   - **State Contradiction:** Agent behaves as if state updates never happened
   - **Context Contradiction:** Agent forgets semantic context
4. **Apply exclusions.**
   - Acknowledged uncertainty or legitimate recovery attempts
   - Harmless re-checks
   - Explicit environment resets
   - Pure formatting issues with no context reliance
   - Contradictions within same tool block
5. **Decide.** Contradiction present AND no exclusion applies → match.

> **ANDROID EDIT — concrete examples.** v0 fired Context Loss only 6 times across 211 trajectories. To enable better detection, recognize these Android-specific patterns as Context Loss:
> - Agent re-runs `pm list packages | grep <X>` after the package was already discovered in an earlier turn.
> - Agent re-issues `.schema <table>` after schema was already inspected and used.
> - Agent re-discovers a file path it already used in an earlier write.
> - Agent re-checks the device's date/timezone after already querying it.
>
> **Tiebreaker against Step Repetition (see C.4):** prefer Context Loss when the re-execution is a *discovery* operation (read-only inspection that produces information). Prefer Step Repetition when the re-execution is a *write* operation (the agent retried the same INSERT/UPDATE).

---

### Task Derailment

**Framing.**
The agent's pursued sub-goal deviates from the task's primary objective for ≥ 2 consecutive turns. Distinct from Context Loss (which is about *forgetting*) and from Reasoning–Action Mismatch (which is about *misalignment*). Task Derailment is about *intent drift*.

**Decision Procedure.**

1. **Identify task objective.** From the task prompt, extract the primary goal and the artifact/result it requires. *If no clear objective:* no match.
2. **Look for sustained deviation.** Within ≥ 2 consecutive agent turns, does the agent pursue a sub-goal that does not advance the primary objective?
3. **Distinguish from sibling leaves.**
   - If the deviation traces to *forgetting* what the task was → prefer Context Loss.
   - If the agent's reasoning correctly identifies the goal but actions go elsewhere → prefer Reasoning–Action Mismatch.
   - If the deviation is the agent pursuing a sub-task it incorrectly thinks is required → Task Derailment.
4. **Decide.** Sustained deviation (≥ 2 turns) with no later return to the original objective and no reset event → match.

> **ANDROID EDIT — concrete examples.** Task Derailment in CLI agents typically looks like:
> - Multi-app task (e.g., "create note in Markor, then send SMS"): agent over-investigates the first app for many turns, never starts the second.
> - Information-retrieval task: agent explores database schemas of unrelated apps for ≥ 2 turns.
> - Task asks about Calendar; agent reads the Tasks app DB.
> - Agent enters a "deep diagnostic" of a tangentially-related subsystem (clipboard, accessibility, services) when the task is straightforward.

---

### Reasoning–Action Mismatch

**Framing.** *(verbatim from TB C.2)*
Reasoning–action mismatch evaluates whether an agent's stated reasoning/conclusions and binding commitments from the task/interface contract align with observable actions and outputs. Decision principle: if a claim/requirement says X but behavior/artifacts show not-X, that's a mismatch. Environment/tool failures only count when the agent proceeds as if success occurred or asserts outcomes contrary to evidence.

**Decision Procedure.**

1. **Identify commitments/claims.** From transcript and task instructions, identify: required output format/protocol, declared method/provenance, success/verification assertions. *If none present:* no match.
2. **Pre-check (v1 — replaces TB's JSON-only filter): Shell-format-only filter.** If all observable contradictions are shell-output-format issues (whitespace, trailing newlines, casing of keys in `dumpsys` output) and none blocked the core deliverable → no match. *(TB's JSON-only filter is irrelevant on Android.)*
3. **Collect behavioral evidence.** Examine: executed commands/tool calls, generated artifacts/files, logs/errors, timestamps/order, final responses.
4. **Compare commitments to evidence. Apply materiality rule** — count only if:
   - **Repeated:** 2+ independent instances of same contradiction class, OR
   - **Blocking:** Violates required spec/contract or prevents completion/tooling
5. **Apply clarifications.**
   - Judge claims against evidence available when claim was made
   - Later failures create mismatch only if agent repeats success claim
   - Core requirements: items affecting acceptance/grading
   - Ignore benign deviations (trailing newline, harmless comments)
6. **Decide.** Clear contradiction that is repeated or blocking → match.

> **ANDROID EDIT — common RAM patterns.** Recognize these as RAM:
> - Agent says "I will use the system content provider" then uses `sqlite3` directly.
> - Agent says "verified the message was sent" but only re-queried the same DB it wrote to (no cross-surface verification).
> - Agent says "calendar event created" but the agent's own `content query content://com.android.calendar/events` after the write returned no row.
> - Agent's reasoning admits uncertainty ("I don't know what category=4 means") then proceeds *as if certain*.

---

### Premature Termination

**Framing.**
The agent declares completion before satisfying explicit task objectives or providing required verifications/data. The handoff carve-out applies *only* when the agent demonstrably attempted alternative surfaces and exhausted reasonable options.

**Decision Procedure.**

1. **Identify objectives.** Extract explicit objectives and required verifications/data. *If none identifiable:* no match.
2. **Confirm agent-declared ending.** Did the agent explicitly declare completion (`finish --status complete`) or present final outputs as if done? Exclude involuntary endings (timeouts, crashes). *If no:* no match.
3. **Check for unmet necessities.** Are any explicit objectives, required verifications, or critical data missing from required output channel(s)? *If no:* no match.
4. **Evaluate handoff (v1 — tightened).** The handoff carve-out applies *only* if:
   - (a) Submission lists at least 2 distinct alternative surfaces the agent attempted, AND
   - (b) Submission documents the failure mode of each (e.g., "tried `cmd role add-role-holder` — got 'Unknown command'; tried `cmd phone send` — no SMS verb available").
   - Mere statements like "could not complete the task" or vague handoffs ("you may need additional permissions") do **not** qualify.

   *If yes (handoff requirements met):* no match.
5. **Decide.** Agent ended with explicit necessities missing, no qualifying handoff, AND claimed success or presented proxies as final → match.

> **ANDROID EDIT — implicit objectives.** Many Android tasks have implicit verifications (e.g., "Send SMS" implies the message must be visible via `content://sms`). Treat these as implicit objectives if the eval would check them. The "If none identifiable: no match" exit should *not* fire just because the prompt didn't enumerate verification checks.

---

### No or Incorrect Verification

**Framing.** *(verbatim from TB C.2 with Android note)*
This rubric flags missing or irrelevant verification of required properties, with completion defined as calling `finish --status complete` (Android) or `mark_task_complete()` (TB). It distinguishes core functional properties from peripheral structural properties. When core properties exist, the agent must verify at least one with an observed, substantive result before completion. Self-assertions ("looks good") are insufficient.

**Decision Procedure.**

1. **Identify required properties.** Classify properties:
   - Core functional: Correctness, required metrics, minimality when central
   - Peripheral structural: Format, filenames, ordering, mere existence
   *If no required properties:* no match.
2. **Check completion status.** Did agent call `finish --status complete`? *If no:* go to Step 5.
3. **Check for explicit admission.** Does agent acknowledge inability or that required properties are not met? *If yes:* no match.
4. **Assess core verification at completion.** Consider only checks on the required final deliverable.
   - **No substantive check at all** (only self-assertions, no SELECT/dumpsys/content query at all) → match
   - Failing core result ignored → match
   - Core property verified with observed result → no match (note: surface validity is judged by *Weak Verification*, not here)
5. **No completion: check for verifier bypass.** If a designated authoritative verifier was available and the agent ignored it → match; otherwise → no match.

> **ANDROID EDIT — distinction from Weak Verification (v1 tiebreaker, also in C.4).**
> - **No or Incorrect Verification:** the agent did **not** check at all, OR the agent's "verification" was self-assertion only (a `cat` of its own write, plus a `# looks good` comment).
> - **Weak Verification:** the agent *did* check, but the check was through a surface the consumer doesn't read from, or covered the wrong properties.
>
> Empirically: most Android failures fall under WV (the agent did some verification, just the wrong kind). NoIV is rare on Android because most agents instinctively re-query their own writes.

---

### Weak Verification

**Framing.** *(v0 + Android edit + v1 completion of decision logic)*
Verification is weak when checks do not cover properties that must hold for true correctness. Common Android pattern: agent writes via one surface (e.g., direct `sqlite3 INSERT` into app DB) and verifies via the same surface (`SELECT FROM` same DB). The eval reads via a different surface (e.g., `content://...` provider) and sees stale state.

**Decision Procedure.**

1. **Identify verification actions.** Does transcript show agent using checks to judge progress/completion (tests, assertions, comparisons, metrics, end-to-end trials)? *If none:* `weak_verification = false` → assign to *No or Incorrect Verification* instead.
2. **Extract essentials.**
   - **Explicit requirements:** Critical properties for correctness from task/instructions
   - **Authoritative evaluator:** On Android — `dumpsys`, `content query` against the relevant provider, `sqlite3` against system DBs, `settings get`. Treat these as essentials.
   - **Implied prerequisites:** Prerequisites whose failure makes explicit requirements impossible (e.g., for SMS: the row must be visible through the system telephony content provider, not just present in `mmssms.db`).
3. **Compare coverage to essentials.**
4. **Check decisiveness and mitigation.**
5. **Apply tie-breakers and exclusions** (also see C.4):
   - Authoritative evaluator with passing result → no match (sufficient verification)
   - **Same-surface verification** (write via X, read via X, where the eval reads via Y) → match
   - Brittle / non-deterministic checks not evidence of correctness → match
   - Inconclusive-only checks ("output had some text") → match
   - Verified constraints all hold under the authoritative surface → no match
   - **Strong coverage** = wrote via X, read via authoritative Y → no match
6. **Decide (v1 — replaces TB's "Decide output" stub).**
   - If agent's verification matches the authoritative surface AND covers core essentials → no match.
   - If agent's verification missed an essential, OR was conducted only against the same surface as the write → match.
   - If agent's verification was substantive but covered the wrong properties → match.

> **ANDROID EDIT — provider-notification gap.** A specific Android failure: the agent writes to a DB correctly, but doesn't trigger the required broadcast/notify (`am broadcast android.intent.action.MEDIA_SCANNER_SCAN_FILE`, `ContentResolver.notifyChange`). Apps reading via ContentResolver don't see the change. Treat this as Weak Verification when the agent verified via the underlying DB but didn't verify via the consumer-facing query.

---

### Data Fabrication *(v1 — promoted from WV sub-flag)*

**Framing.**
The agent generates or alters output/source data that should have been recovered, measured, or derived from authoritative sources, and treats the fabricated result as genuine. Different from *Disobey Specification* (which is about violating directives — fabrication may incidentally violate but isn't always directive-driven). Different from *Weak Verification* (which is about insufficient checks of real data — fabrication is about manufacturing data).

**Decision Procedure.**

1. **Identify candidate fabrications.** Does the trajectory contain values, IDs, mappings, or content that:
   - Are not present in any of the agent's observation outputs?
   - Were neither read from a file/DB nor computed deterministically from observed data?
   - The agent treats as authentic (uses for INSERT, includes in submission, claims as fact)?
2. **Check reliance.** The fabrication must drive task progress: the fabricated value is used to satisfy a requirement, pass a check, or appear in the deliverable. Idle speculation that's not acted on → no match.
3. **Distinguish from extrapolation.** Acceptable extrapolations (count as evidence-grounded):
   - Continuing an observed sequence (existing IDs 1, 3, 5, 7 → next likely 9 or 11 — *if the agent labels this as a guess*)
   - Calculating from observed timestamps with documented arithmetic
   - Inferring from the agent's prior output
   *Not acceptable* (fabrication):
   - Choosing an integer category from outside the observed set without explicit reasoning
   - Generating coordinates, dates, or strings from prior knowledge instead of querying live state
   - Making up `address`/`thread_id`/`canonical_addresses` values when canonical_addresses table is queryable
4. **Decide.** Fabrication exists AND it is used in a deliverable/check AND not labeled as a guess → match.

**Common Android fabrication patterns (recognize as match):**
- **Geocoding:** OsmAnd "Add favorite for Schaan, Liechtenstein" → agent writes lat/lon=47.1857/9.5392 from prior knowledge instead of using OsmAnd's `.obf` data.
- **Category mapping:** Pro Expense `category=integer` — agent picks 13 or 15 for "Education"/"Income" without recovering the mapping from APK resources.
- **Clipboard guessing:** Markor paste tasks — agent writes `yN9C99pej0` (a guess from system metadata) when actual clipboard text is unavailable.
- **Date arithmetic:** Calendar tasks — agent computes "Monday after next" using assumed timezone/week-start instead of querying device timezone.
- **Recipe/Music mappings:** Broccoli/Retro Music — agent invents data for unrecoverable mappings.

**Tiebreaker (also in C.4):**
- If fabrication is the **primary failure mode** (the trajectory would have succeeded with correct data) → *Data Fabrication* primary.
- If fabrication is incidental to a wrong-write-surface failure → *Weak Verification* primary, *Data Fabrication* secondary.
- If fabrication is the agent ignoring a directive ("use exact values from this CSV") → *Disobey Specification* primary.

---

### Constraint Infeasibility *(NEW in v1)*

**Framing.**
The task as specified requires a capability that the agent's constraint set forbids. The agent didn't fail at reasoning or execution — the task is structurally incompatible with the no-screen / no-root / no-clipboard-read / no-pull/push constraints. This leaf separates "agent failure" from "task design failure" so the failure-mode distribution doesn't conflate the two.

**Decision Procedure.**

1. **Identify required capability.** Does the task explicitly require:
   - UI interaction (tap, click, swipe, type, scroll)?
   - Screen observation (a11y tree, screenshots, OCR)?
   - Root access (`adb root`, root-only filesystem writes)?
   - File transfer to/from host (`adb pull`, `adb push`)?
   - System service that's not exposed via shell command (e.g., reading the live Android clipboard)?
2. **Check agent constraint set.** From the agent's system prompt, identify forbidden capabilities. *If the required capability is on the forbidden list:* candidate match.
3. **Verify the agent recognized the constraint.** The agent's reasoning should reflect awareness of the constraint (e.g., "I cannot read the clipboard from shell on Android 13+"). If the agent attempted a workaround in good faith and *correctly identified* that no workaround exists → match.
4. **Distinguish from Premature Termination.** PT applies when the agent gave up too early on a workaround that DOES exist. Constraint Infeasibility applies when *no in-environment workaround exists*.
5. **Distinguish from Disobey Specification.** DS applies when the agent ignores a known workaround. Constraint Infeasibility applies when no workaround was reasonably discoverable.
6. **Decide.** Required capability is in the agent's forbidden-list AND no in-environment workaround exists AND the agent identified this correctly → match.

**Common Android Constraint Infeasibility patterns:**
- "Watch this video and transcribe text on each frame" with no-screen constraint.
- "Click the 'Done' button after completing the entry" with no-tap constraint.
- "Read the clipboard content and send it via SMS" — clipboard is unreadable from shell on Android 13+ with no companion app.
- "Take one photo" / "Take one video" — Camera capture requires UI.

> **NOTE.** This leaf overlaps with the AndroidWorld benchmark's `GUI-only` task classification. Tasks classified as GUI-only by the v2 ground-truth doc should be excluded from the analysis pool (not classified) — they're "infeasible by benchmark design", not failures. Constraint Infeasibility applies when the task is *categorically* CLI-solvable but a *specific* trajectory hit an unforeseen capability gap.

---

### Tool-Format Error *(NEW in v1)*

**Framing.**
The agent's intent is correct but the emitted command is malformed at the CLI tool layer (shell quoting, escape sequences, base64 encoding, content-bind syntax). The retries are about *fixing the encoding*, not about reasoning. This is a CLI-environment-specific failure mode that doesn't exist in TB's web/code domains.

**Decision Procedure.**

1. **Identify candidate retry sequence.** ≥ 2 consecutive turns where the *intent* (target operation, target data) is identical and the only differences are:
   - Quoting style (single vs double quotes, escape sequences)
   - HEREDOC vs inline arguments
   - Embedded literal vs base64-encoded payload
   - `2>&1` redirection added
2. **Confirm encoding-error symptoms.** The observation contains shell-syntax error messages: `no closing quote`, `syntax error near unexpected token`, `command not found` (because of mis-tokenization), `usage:` banner from a tool that didn't get its arguments.
3. **Distinguish from sibling leaves.**
   - If the *intent* changes across retries (different SQL, different table, different approach) → *Step Repetition* if same conceptual approach, otherwise normal exploration.
   - If the agent's reasoning misidentifies the bug ("I'll change the date format" when the real issue is quoting) → *Reasoning–Action Mismatch*.
   - If the agent gives up after the encoding errors without trying alternative encodings → still *Tool-Format Error* (the encoding bug was the root cause).
4. **Decide.** ≥ 2 consecutive turns with identical intent, encoding errors in observations, and agent retrying with encoding variants → match.

**Common Android Tool-Format Error patterns:**
- `adb shell 'sqlite3 ... "SELECT ... WHERE x = '\''Y'\''"'` style nested-quote retries.
- `content insert --bind body:s:'...with spaces...'` failing because `content insert` tokenizes spaces.
- `cat <<EOF` HEREDOC retries when the document body contains backticks.
- Base64-encoded payload writes (`echo BASE64 | base64 -d > file`) failing because of shell escaping in the base64 string.

> **NOTE.** This leaf resolves AMBIG-1 from `notes.md` (Step Repetition vs RAM on quoting retries). Heuristic data showed 8.7% of v0 classifications were ambiguous between these two; v1 routes them here cleanly.

---

## C.4 Tie-breaker matrix *(NEW in v1)*

When multiple leaves' decision procedures match the same trajectory, apply the following priority and tie-breakers:

### Pair: Disobey Specification vs Weak Verification (wrong-write-surface)

When agent wrote to non-canonical surface AND verified through same non-canonical surface:
- If task **explicitly** named the canonical surface (e.g., "send via Simple SMS Messenger") → **Disobey Specification** primary, WV secondary.
- If task did NOT explicitly name the surface and the agent had no way to know which surface the eval reads → **Weak Verification** primary, DS secondary.
- **Default:** **Weak Verification** primary (more common pattern; the verification gap is what made the failure visible).

### Pair: Premature Termination vs Unaware-of-Termination (P1)

v1 **eliminates this overlap by removing P1 from Unaware**. All "agent claimed completion before objectives met" cases are now **Premature Termination**. Unaware is reserved for "agent kept going past success or futility" (C1, C2 only).

### Pair: Weak Verification vs No or Incorrect Verification

- Agent emitted **at least one** SELECT/dumpsys/content-query against any surface AFTER its writes → **Weak Verification** primary.
- Agent emitted **zero** verification queries OR only self-assertions like "looks good" → **No or Incorrect Verification** primary.
- The boundary is *whether any check happened*, not whether the check was correct.

### Pair: Step Repetition vs Context Loss

- Re-execution is a **read/discovery** operation (e.g., re-running `pm list packages`, re-listing a directory, re-querying a schema) → **Context Loss** primary.
- Re-execution is a **write** operation (e.g., re-running same INSERT, same `content insert`) → **Step Repetition** primary.
- Re-execution is a **read with new arguments** (re-running SQL with widened WHERE clause) → neither — that's *active exploration*.

### Pair: Step Repetition vs Tool-Format Error

- Encoding/quoting errors in observations → **Tool-Format Error** primary.
- Same well-formed command run multiple times with no encoding errors (the command worked but the action didn't have the desired effect) → **Step Repetition** primary.

### Pair: Disobey Specification vs Data Fabrication

- Task explicitly says "use exact values from X" and agent fabricates → **Disobey Specification** primary.
- Task implicitly requires correct data and agent fabricates → **Data Fabrication** primary.

### Pair: Reasoning-Action Mismatch vs Data Fabrication

- Agent's reasoning admits uncertainty AND action proceeds with a fabricated value → **Data Fabrication** primary, RAM secondary.
- Agent's reasoning claims certainty AND action contradicts that certainty → **Reasoning-Action Mismatch** primary.

### Pair: Premature Termination vs Constraint Infeasibility

- Agent gave up but in-environment workarounds existed and were not attempted → **Premature Termination** primary.
- Agent gave up after demonstrably exhausting all in-environment workarounds → **Constraint Infeasibility** primary.

---

## C.5 Multi-label assignment

Each trajectory MUST receive exactly one `primary_leaf` and a (possibly empty) list of `secondary_leaves`. The judge:

1. Walks each leaf's decision procedure → collects all leaves that match.
2. Applies C.4 tie-breakers to resolve overlaps and pick the single most-specific match as `primary_leaf`.
3. Lists all OTHER matching leaves as `secondary_leaves`.
4. If no leaf matches after all decision procedures → `primary_leaf = "_no_match_"` and `rationale` describes the observed failure pattern (candidate for v2 rubric extension).

---

## C.6 Mapping — MAST → TB → AndroidWorld v1

| MAST | TB | AndroidWorld v0 | AndroidWorld v1 |
|---|---|---|---|
| 1.1 Disobey task spec | Disobey Specification | Disobey Specification | Disobey Specification |
| 1.2 Disobey role spec | merged | merged | merged |
| 1.3 Step repetition | Step Repetition | Step Repetition | Step Repetition |
| 1.5 Unaware of termination | Unaware of Termination | Unaware of Termination | Unaware of Termination *(P1 removed)* |
| 1.4 Loss of conversation history | Context Loss | Context Loss | Context Loss *(Android examples)* |
| 2.3 Task derailment | Task Derailment | Task Derailment *(placeholder)* | Task Derailment *(Android examples)* |
| 2.6 Reasoning–action mismatch | Reasoning–Action Mismatch | Reasoning–Action Mismatch | Reasoning–Action Mismatch *(shell-format pre-check)* |
| 2.1, 2.2, 2.4, 2.5 | dropped | dropped | dropped |
| 3.1 Premature termination | Premature Termination | Premature Termination | Premature Termination *(tightened handoff)* |
| 3.2 Weak verification | Weak Verification | Weak Verification | Weak Verification *(complete decision logic)* |
| 3.3 No or incorrect verification | No or Incorrect Verification | No or Incorrect Verification | No or Incorrect Verification |
| — *(new)* | — | — | **Data Fabrication** *(NEW)* |
| — *(new)* | — | — | **Constraint Infeasibility** *(NEW)* |
| — *(new)* | — | — | **Tool-Format Error** *(NEW)* |

---

## Iteration log

- **v0** (2026-05-07) — TB Appendix C lifted verbatim. 2 Android edits applied. Task Derailment given a placeholder rubric since TB C.2 omits it. 9 leaves total.
- **v1** (2026-05-10) — Empirical iteration after running the v0 rubric across 211 CLI-solvable readable failures with Opus 4.7 max-effort judge. Specific changes:
  - **Promoted Data Fabrication from sub-flag of WV to primary leaf.** Rationale: 5 of 18 ClaudeCodeCLI failures involved fabrication as the *primary* failure (OsmAnd coords, Pro Expense category, clipboard guess, Markor merge separator, geocoding) but were forced under WV or DS.
  - **Added Constraint Infeasibility leaf.** Rationale: 3 `_no_match_` cases in v0 + ~6 cases in deep dive that were forced into DS or _no_match_ when the actual issue was task structurally infeasible under no-screen constraint.
  - **Added Tool-Format Error leaf.** Rationale: AMBIG-1 from `notes.md` validated at scale — 8.7% of v0 classifications had Step Repetition + quoting error pattern. Resolves the ambiguity.
  - **Replaced TB's JSON-only filter in RAM** with an Android-equivalent shell-format-only filter.
  - **Added Android examples to Context Loss** to address its near-zero firing rate in v0 (0/211 primary, 6/211 secondary).
  - **Sharpened Task Derailment** with concrete Android examples (multi-app drift, wrong-app exploration). Removed the suggestion to "merge into Context Loss"; the leaves are now distinguishable.
  - **Tightened Premature Termination handoff carve-out** to require evidence of attempting alternative surfaces, not just listing them.
  - **Removed Unaware-P1 sub-type** (it was literally Premature Termination).
  - **Completed Weak Verification Step 6** with explicit decision logic (TB's "Decide output" was a stub).
  - **Added C.4 Tie-breaker matrix** for the 7 most-common overlap pairs.
- **v2 onwards** — Re-run the LLM judge on all 211 trajectories with v1, compare label deltas, and decide whether further iteration is needed before the full multi-seed run.
