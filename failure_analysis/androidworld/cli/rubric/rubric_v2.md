# Rubric v2 — Failure-Mode Taxonomy for AndroidWorld CLI Trajectories

**Status:** v2. Same 9 leaves as v1 (and as TB Appendix C), but framings, decision procedures, and exclusion criteria are **rewritten to be Android-native**.

**Source lineage:** Merrill et al., *Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces*, arXiv:2601.11868v1, Appendix C → AndroidWorld-native adaptation grounded in 211 CLI-solvable readable failures across 6 agent×model combos.

## v1 → v2 design change

v1 lifted TB Appendix C *verbatim* and applied only two surgical Android edits (Disobey Spec output-location, Weak Verification authoritative-evaluator). The other seven leaves carried TB-flavored decision procedures and examples that don't fit Android trajectories cleanly — e.g., *Disobey Specification* Step 2 listed "Using a placeholder instead of the required implementation" (a coding pattern), with no Android analog.

v2 takes the opposite approach: **keep all 9 TB leaf names and their high-level intent, but rewrite framing/decision procedure/exclusion criteria with Android-native vocabulary, examples, and decision rules**.

v1's additions of *Data Fabrication*, *Tool-Format Error*, and *Constraint Infeasibility* as separate leaves are **dropped in v2**. They are reabsorbed as Android-native sub-patterns of existing TB leaves — see §C.4 mapping.

**Validation:** every cluster in the bottom-up Docent free-form clustering (Opus 4.7 classification, 211 trajectories, 9 emergent categories) maps cleanly onto v2's 9 TB-derived leaves. No bottom-up cluster requires a new leaf. See `docent_analyses/2026-05-10_android-failure-cluster/android_cli_failure_taxonomy.md` for the methodology.

---

## Top-level structure (unchanged from TB / v1)

Three broad classes:

- **Execution** — *Disobey Specification*, *Step Repetition*, *Unaware of Termination Conditions*
- **Coherence** — *Context Loss*, *Task Derailment*, *Reasoning–Action Mismatch*
- **Verification** — *Premature Termination*, *No or Incorrect Verification*, *Weak Verification*

Single-label primary assignment, optional secondary leaves (multi-label). 9 leaves total.

---

## C.1 Taxonomy summary (Android-native one-line framings)

- **Disobey Specification:** the agent materially contradicts explicit Android-task directives — including using the wrong consumer surface (app DB instead of system provider), the wrong API level (binder hacks instead of intents/role-holders), the wrong output format/protocol (malformed `finish --description`), or fabricating data when the source was named.
- **Step Repetition:** the agent re-executes the same ADB command class against the same content URI / DB path / file path multiple times without strategy change. Common Android forms: re-issuing failed `content insert`, looping on the same `pm`/`cmd` verb after harness rejection, repeated probes of the same blocked surface.
- **Unaware of Termination Conditions:** the agent continues acting past an Android-recognizable stopping signal — confirmed device-state success (the row is now visible via the canonical reader), explicit denial (`run-as: not debuggable`, `Only sync adapters may write`), or futility (≥ 2 consecutive identical errors from the same surface).
- **Reasoning–Action Mismatch:** the agent's stated reasoning is contradicted by its actual command. Android forms: declared method ("use ContentProvider") doesn't match action (used `sqlite3` directly); reasoning admits uncertainty about a mapping then commits to a guessed value; intended command is sound but the emitted shell string is malformed and the agent doesn't notice.
- **Context Loss:** the agent forgets or contradicts established Android device state or task content. Forms: re-discovers a package it already found, re-queries the device timezone after using it earlier, paraphrases the task's exact phone number / event title / file content after having captured it.
- **Task Derailment:** the agent's pursued sub-goal drifts from the task's primary objective. Android forms: over-investigating one app of a multi-app task, reading an unrelated app's DB, deep-diving an unrelated subsystem (clipboard, accessibility, services).
- **Premature Termination:** the agent declares completion (via `finish --status complete`) before satisfying explicit or implicit Android objectives. Two sub-types: **positive PT** (claimed success despite missing objective) and **negative PT** (submitted "None" / empty answer for a retrieval task without exhausting filter alternatives).
- **No or Incorrect Verification:** the agent calls `finish --status complete` without any substantive read against an authoritative Android surface (`dumpsys` / `content query` / `sqlite3` / `settings get`) — only self-assertions.
- **Weak Verification:** the agent verified, but through a surface the consumer doesn't read from (verify-via-same-DB-as-write, or only the app's UI not the system provider). On Android, the canonical authoritative surfaces are `dumpsys <service>`, `content query --uri content://...` against the system provider, or `sqlite3` against system DBs.

---

## C.2 Per-leaf rubrics (Android-native)

### Disobey Specification

**Framing.**
Disobey Specification concerns material contradictions to Android-task directives — both hard ("must reply via Simple SMS Messenger", "from `my_expenses.txt`") and soft ("use the standard Android API"). Pure response-format issues that don't affect downstream readers are excluded. Material violations on Android typically take five forms:

1. **Wrong consumer surface** — the task implies a specific consumer (Simple SMS Messenger, Markor, OsmAnd) and the agent writes to a surface the consumer doesn't read from (e.g., writes to `mmssms.db` directly when the system `content://sms/` provider is the path through which Simple SMS reads via ContentObserver).
2. **Wrong API level** — the agent uses raw binder transactions (`service call isms ...`, `service call clipboard ...`) or sqlite directly when a higher-level API (intent broadcast, RoleManager grant, `am start`, content provider) is the correct path.
3. **Wrong output format/protocol** — the agent's `finish --description` is malformed: multi-line answer for a single-line expected, includes reasoning text, combined with another command in the same turn, missing the answer entirely.
4. **Data fabrication when source was named** — task specifies "from `my_expenses.txt`" and agent invents transactions; task names a specific message body and agent paraphrases; task names a place and agent invents lat/lon coordinates instead of using OsmAnd's offline data.
5. **Forbidden operations** — the agent's system prompt explicitly prohibits APK extraction (`unzip`/`xxd`/`strings` on `base.apk`), full `dumpsys package`, recursive `find /`. Agent uses them anyway.

Acceptable substitutions: if the agent uses a different surface but the final state is provably correct (e.g., the canonical consumer surface confirms via `content query`), no match. "Demonstrably equivalent" requires cross-surface verification, not just the agent's own re-read of its write.

**Decision Procedure.**

1. **Locate directives.** Identify hard and soft directives from task text and the agent's system prompt:
   - Consumer apps named (e.g., "in Simple SMS Messenger", "in Markor")
   - Source data named (file paths, exact strings, specific values)
   - Output format specified (single line vs multi-line, exact wording, schema)
   - Forbidden operations in system prompt
   *If none identifiable:* no match.
2. **Check for contradiction.** Determine if the agent violated at least one directive:
   - Wrote to a surface different from what the named consumer reads from
   - Used a lower-level API (binder, raw sqlite) when a higher-level API was implied
   - Submitted via wrong format/channel (`finish --description` malformed)
   - Fabricated data when source was named
   - Used a forbidden operation
3. **Assess materiality.**
   - Whitespace-only / trailing-newline format issues → no match
   - Wrong consumer surface (consumer cannot see the write) → material
   - Fabrication of typed data (dates, coords, message bodies, IDs from observed integer patterns without ground truth) → material
   - Wrong output format that blocks the verifier from reading the answer → material
   - Forbidden operation regardless of outcome → material
4. **Check for correction.** Did the agent fully reverse the violation before completion AND the final state satisfies all directives (verified through an authoritative reader, not just re-reading its own write)? *If yes:* no match.
5. **Decide.** If Steps 2–3 satisfied and Step 4 not → match.

**Android-specific exclusion criteria.**

- **Source data unnamed** — if the task doesn't name a source file or exact values, the agent inserting plausible test values isn't fabrication (it's just under-specification of the task). E.g., "create a calendar event for tomorrow" with no body text given.
- **Consumer-equivalent surfaces** — if the named consumer happens to read from the same underlying DB the agent wrote to (some apps use MediaStore directly), then writing via that DB is not "wrong consumer surface".
- **Force-stop sync** — agents that write to an app's DB, then `am force-stop` the app, then verify, get partial credit on consumer-surface — but the eval may still fail if there's no notify path. Apply with caution.

---

### Step Repetition

**Framing.**
Step Repetition occurs when the agent re-executes the same ADB command class against the same target without a meaningful change. On Android, "command class" = the verb + the target surface (content URI / DB path / settings key / activity name). Differences in quoting, escaping, whitespace, or trailing redirection do *not* count as material change.

Common Android patterns:
- Re-issuing the same `content insert content://...` after a silent drop (no error visible, but the row didn't appear in subsequent query)
- Re-running `sqlite3 INSERT INTO <table> ...` after the previous one returned `(no output)` (which on Android is ambiguous — could be success or silent failure)
- Looping on the same `pm`/`cmd`/`ls`/`echo` verb class after a Terminus2 harness rejection (`not a recognized verb`)
- Repeated `run-as <pkg>` attempts after `package not debuggable` denial

**Decision Procedure.**

1. **Verify preconditions.** Multiple distinct agent turns exist, identifiable phases/sub-goals can be grouped. *If either missing:* no match.
2. **Collect signals.** For each agent turn, extract:
   - Command verb (`content insert`, `sqlite3`, `pm`, `cmd`, `service call`, `am`, `dumpsys`, `settings`, `run-as`)
   - Target (URI / DB path / package name / setting key / service name)
   - Argument identity (`--bind` payload, SQL statement, intent action)
   - Outcome (success / silent drop / error / pending)
3. **Apply block-level deduplication.** Each agent turn = one attempt. Multi-part commands in one turn count once.
4. **Trigger check.** Within a single phase, do ≥ 2 turns share the same (verb, target, argument identity) ignoring whitespace/quoting? *If no:* no match.
5. **Assess identity.**
   - **Semantic identity:** same verb + same target + same argument payload. Whitespace / quoting differences ignored. `content insert --uri content://sms --bind body:s:"X"` and `content insert --uri content://sms --bind body:s:'X'` are semantically identical.
   - **Conceptual identity:** different verb but same intended effect on same target. `content insert content://sms ...` then `sqlite3 mmssms.db "INSERT INTO sms ..."` are conceptually the same (both attempt to write a sent SMS row). Retrying one after the other failed *is* repetition.
   - **Not identical:** changing target surface (e.g., `content insert content://sms` → `am start -a SENDTO`), changing API level (sqlite → role-manager grant), changing tool flags that alter mode (`--user` flag added).
6. **Classify category.**
   - Post-error-blind-retry (Terminus2 harness rejection of `pm` verb, then re-issuing same `pm` command)
   - Post-silent-drop retry (content insert appeared to succeed but the row didn't surface, then retried identically)
   - Post-denial retry (`run-as: not debuggable` then more `run-as`)
   - Verification-loop (re-running same `SELECT` on same DB after write, > 2 times)
7. **Apply Android-specific exclusions.**
   - **Quoting / escaping variants** to fix shell syntax errors → not Step Repetition. The intent is fixed, the encoding is being repaired. These are sub-patterns of *Reasoning–Action Mismatch* (intent right, encoding wrong).
   - **First retry after `am force-stop`** → not counted. Force-stop is a meaningful state change.
   - **Schema-discovery re-runs** (`.schema <table>` repeated) → diagnostic, not repetition.
   - **Diagnostic-only changes** (adding `2>&1`, adding `--verbose` flag) → don't break identity.
   - **Up to 2 identical performance probes** (`time <command>`) → allowed.
8. **Decide.** ≥ 2 semantically or conceptually identical actions within one phase → match.

---

### Unaware of Termination Conditions

**Framing.**
Failure-to-stop occurs when an agent continues acting past an Android-recognizable stopping signal. On Android these signals are:

- **Confirmed device-state success** — the agent's authoritative reader (`content query`, `dumpsys`, `sqlite3`) returned a row that matches the goal.
- **Established futility** — ≥ 2 consecutive identical denials from the same surface (`Only sync adapters may write`, `package not debuggable`, harness "not a recognized verb").
- **Explicit completion** — the agent calls `finish --status complete`.

**Decision Procedure.**

1. **Verify preconditions.** A stopping point must be identifiable from one of:
   - Success criteria explicit in the task ("Turn bluetooth off" + agent reads `settings get global bluetooth_on` = 0)
   - Strong implicit success (canonical reader confirms goal state)
   - Futility (≥ 2 consecutive identical denials, no successful alternative tried)
   - Agent's own completion signal (`finish --status complete`)
   *If none identifiable:* no match.
2. **Identify triggering condition.** Exactly one of:
   - Success condition observably satisfied
   - Futility established (denial + denial + same approach)
   - Completion signaled
3. **Classify violation type.**
   - **C1 (After Success):** Agent has confirmed device-state matches goal, but continues acting for ≥ 2 additional turns (1 verification turn allowed).
   - **C2 (After Futility):** After 2 consecutive identical denials/errors from the same surface, agent continued same approach (same content URI, same `run-as`, same harness-rejected verb class).
4. **Apply Android-specific exclusions.**
   - **One canonical verification turn after success** → allowed.
   - **Force-stop + re-verify** counts as one strategy change, resets futility counter.
   - **Hygiene-only turns** (renaming files, formatting output) → not counted.
   - **Hitting `max_turns`** (e.g., 50/50) is not automatically C1 or C2. It's only Unaware if there's identifiable futility *and* the agent kept emitting the same failing approach. Pure max-turns hits without a clear futility signal are an environmental cap, not termination-awareness failure.
5. **Decide.** C1 with ≥ 2 redo turns after success → match. C2 with ≥ 1 further attempt without strategy change → match.

> **Note on relation to Premature Termination.** TB's original Unaware decision procedure included a "P1: Premature Completion" sub-type — agent claims completion before success conditions are met. **v2 removes P1 from Unaware**; that case is *Premature Termination*. Unaware in v2 covers only C1 (kept going after success) and C2 (kept going after futility).

---

### Context Loss

**Framing.**
Context Loss occurs when the agent forgets or contradicts established Android device state or task content within a recent window. Two forms:

1. **State Loss** — agent re-discovers something it already established (package, schema, device timezone, default-SMS-app, agent's own writes).
2. **Context Loss** — agent paraphrases or invents task content after having recorded the exact form earlier (e.g., task says "Reply to +18490934066 with 'The library book is due back on the 15th.'" — agent reads this, then later writes "library book due 15th").

**Decision Procedure.**

1. **Verify preconditions.** Identify a recent contiguous window (no major resets) containing at least one of:
   - State: a successful discovery (package found, schema queried, timezone read, sms_default_application checked)
   - Context: exact task-string captured (the message body, the event title, the file content, the phone number)
   *If neither exists:* no match.
2. **Identify contradiction.** Look for later behavior that:
   - Re-discovers something that's already known (re-running `pm list packages | grep <X>` after the package was found earlier)
   - Paraphrases task content (writes shortened/altered version of exact text)
   - Reverts to default assumptions about state (e.g., timezone, after `getprop` returned UTC earlier)
   - Re-asks an answered question (re-reads the same source file)
3. **Classify violation type.**
   - **State Contradiction:** behaves as if a prior discovery never happened
   - **Context Contradiction:** alters exact task-content after having captured it
4. **Apply Android-specific exclusions.**
   - **Re-discovery is not always Context Loss.** Most "re-running the same probe" on Android is actually *Step Repetition* (same verb, same target, retried identically). Context Loss applies specifically when the agent acts as if the *result* of the prior discovery doesn't exist (e.g., re-running `pm list packages | grep markor` not because of an error but because the agent's reasoning suggests it doesn't know the package).
   - **Force-stop resets** are explicit and don't count as forgetting.
   - **Schema re-inspections** when the agent is switching tables → not Context Loss (active exploration).
5. **Decide.** Contradiction present AND no exclusion applies → match.

> **Note on rarity.** Empirically (v1 LLM-judge run over 211 trajectories), Context Loss fires very rarely as primary classification (0/211) and infrequently as secondary (6/211). On CLI agents specifically, what looks like Context Loss is usually Step Repetition (re-running a probe) or Reasoning–Action Mismatch (paraphrasing task content). Apply Context Loss only when the agent observably *forgets* prior context, not merely *re-checks* it.

---

### Task Derailment

**Framing.**
Task Derailment occurs when the agent's pursued sub-goal drifts from the task's primary objective for ≥ 2 consecutive turns. Distinct from Context Loss (forgetting) and Reasoning–Action Mismatch (misaligned action). Task Derailment is about *intent drift*.

**Android forms:**

- **Multi-app over-investment:** Task like "Create a note in Markor, then SMS its contents to X". Agent over-investigates Markor's storage for many turns without starting the SMS subtask.
- **Wrong-app exploration:** Task is about Calendar; agent reads Tasks app's DB for ≥ 2 turns.
- **Tangential subsystem dive:** Task is straightforward (e.g., turn WiFi off). Agent dives deep into clipboard service, accessibility, or low-level binder transactions.
- **Forbidden time-sink:** Agent attempts APK extraction or recursive `find /` against system prompt prohibitions for ≥ 2 turns. (Also matches *Disobey Specification*; prefer DS unless the agent's reasoning explicitly identifies the time-sink as the goal.)

**Decision Procedure.**

1. **Identify task objective.** From the task prompt, extract:
   - Primary goal (the artifact / answer / state change required)
   - Implicit prerequisites (what device state must change for the eval to pass)
   *If no clear objective:* no match.
2. **Look for sustained deviation.** Within ≥ 2 consecutive agent turns, does the agent pursue a sub-goal that does not advance the primary objective or its prerequisites?
3. **Distinguish from sibling leaves.**
   - Deviation traces to *forgetting* what the task was → prefer *Context Loss*.
   - Agent's reasoning correctly identifies the goal but actions go elsewhere → prefer *Reasoning–Action Mismatch*.
   - Agent pursues a sub-task it incorrectly thinks is required → Task Derailment.
4. **Decide.** Sustained deviation (≥ 2 turns) with no later return to the original objective and no reset event → match.

> **Empirical note.** v1 LLM-judge fired Task Derailment only 2/211 times as primary. Bottom-up clustering did not surface it as a distinct cluster. Apply this leaf only when the agent's behavior is clearly "wrong app/subsystem/depth"; default to Disobey Spec or Step Repetition when in doubt.

---

### Reasoning–Action Mismatch

**Framing.**
RAM evaluates whether the agent's stated reasoning/conclusions align with its observable actions and outputs. Decision principle: if reasoning says X but the action/output is not-X, mismatch.

**Android-specific RAM patterns** (commonly observed):

1. **Declared method vs actual method:** Agent reasons "I'll use the system content provider for SMS" then uses `sqlite3` directly against `mmssms.db`.
2. **Verification claim without verification:** Agent says "I verified the message was sent" but the only evidence is a re-read of the DB it wrote to, not an authoritative `content query content://sms/`.
3. **Uncertainty acknowledged then ignored:** Agent reasons "I don't know what category=4 represents in this enum" then writes `category=13` for Education as if certain. (This pattern, observed across many Pro Expense failures, was the source of v1's *Data Fabrication* leaf — v2 reabsorbs it into RAM.)
4. **Intent vs encoded command:** Agent's reasoning describes correct SQL with proper escaping, but the emitted shell string has nested-quote breakage. The agent doesn't notice the encoding broke its intent. (Source of v1's *Tool-Format Error* leaf — v2 reabsorbs into RAM.)
5. **Success claim ignoring last observation:** Agent's last `content query` returned `No result found` but submission says the row was inserted.

**Decision Procedure.**

1. **Identify commitments/claims.** From transcript:
   - Stated method/surface ("I'll use the content provider", "I'll set sms_default_application first")
   - Success/verification assertions ("the row was created", "verified")
   - Required output format/protocol declared in reasoning
   - Acknowledgments of uncertainty ("I don't know X")
   *If none present:* no match.
2. **Pre-check: shell-format-only filter.** If all observable contradictions are output-format issues (whitespace, trailing newlines, casing of fields in `dumpsys`) and none blocked the core deliverable → no match. *(Android analog of TB's JSON-only filter.)*
3. **Collect behavioral evidence.** Examine actions, generated state, log output, error messages, final response.
4. **Compare commitments to evidence. Apply materiality rule** — count only if:
   - **Repeated:** ≥ 2 independent instances of same contradiction class
   - **Blocking:** Violates required spec/contract or prevents completion
5. **Apply Android-specific clarifications.**
   - Judge claims against evidence available when claim was made (don't penalize the agent for not knowing later results).
   - **Uncertainty-then-commit pattern:** if agent's reasoning admits "I don't know mapping/value/etc." and then commits to a guessed value, this counts as RAM regardless of repetition.
   - **Encoding-error pattern:** if agent's intent was right but the emitted shell string was wrong AND the agent doesn't recognize the broken encoding, this counts as RAM (intent vs action mismatch). Distinct from Step Repetition: the agent isn't retrying — it's failing to notice.
   - Ignore benign deviations (trailing newline, harmless comments).
6. **Decide.** Clear contradiction that is repeated, blocking, or uncertainty-then-commit → match.

---

### Premature Termination

**Framing.**
The agent declares completion (`finish --status complete`) before meeting explicit or implicit Android-task objectives, and without a concrete actionable handoff. Two sub-types:

1. **Positive PT** *(TB-standard)* — agent claimed success despite an unmet objective (e.g., submitted "added the expense" without checking if it surfaces via consumer reader).
2. **Negative PT** *(Android-native)* — for information-retrieval tasks ("What tasks are due Monday?"), the agent submitted `None` / empty answer / raw dump without exhausting reasonable filter alternatives (different date ranges, different importance thresholds, different table joins).

The concrete-handoff carve-out applies only if the agent listed ≥ 2 alternative surfaces attempted with documented failure modes (not vague "could not complete").

**Decision Procedure.**

1. **Identify objectives.** Extract explicit objectives and implicit ones:
   - Explicit: stated in task ("Send an SMS to X with body Y", "Add expense Z")
   - Implicit on Android: for write tasks, the consumer must be able to read the change via canonical surface. For retrieval tasks, the agent must have queried *all* reasonable filters before submitting empty.
   *If none identifiable:* no match.
2. **Confirm agent-declared ending.** Did the agent explicitly call `finish --status complete` or present final outputs as if done? Exclude involuntary endings (timeouts, environment crashes). *If no:* no match.
3. **Check for unmet necessities.** For each objective:
   - Write task: did the agent verify through an authoritative reader that the consumer sees the change? If only re-reads its own write → unmet.
   - Retrieval task: did the agent try ≥ 2 distinct filter/query variants before submitting empty? If only 1 → unmet.
   *If all met:* no match.
4. **Evaluate handoff (v2 — tighter than TB).** The carve-out applies only if:
   - (a) Submission lists ≥ 2 distinct surfaces/approaches attempted, AND
   - (b) Submission documents the failure mode of each (e.g., "tried `cmd role add-role-holder` — got 'Unknown command'; tried `cmd phone send` — no SMS verb available").
   - Vague "could not complete" or single-mention does **not** qualify.
   *If qualifying handoff:* no match.
5. **Decide.** Agent ended with unmet necessities AND no qualifying handoff AND claimed success or submitted final answer → match.

   Classify the sub-type:
   - **Positive PT:** claimed success
   - **Negative PT:** submitted "None"/empty after insufficient filter exploration

---

### No or Incorrect Verification

**Framing.**
The agent calls `finish --status complete` without performing any substantive read against an authoritative Android surface. Distinct from *Weak Verification* (which is verification that hit the wrong surface) — NoIV is the case where *no* verification at all happened, or only self-assertions ("looks good", "should work") are present.

**Decision Procedure.**

1. **Identify required properties.** Classify the task's verifiable properties:
   - Core functional: correctness of the device state change (row exists, file written, setting changed)
   - Peripheral structural: format, filename, ordering, mere existence
   *If no required properties:* no match.
2. **Check completion status.** Did agent call `finish --status complete`? *If no:* go to Step 5.
3. **Check for explicit admission.** Does agent explicitly acknowledge "I could not verify" or "the operation may have failed"? *If yes:* no match (this is honesty, not NoIV).
4. **Assess core verification at completion.** Considering only checks on the required final deliverable:
   - **Zero substantive verification commands** (only `echo "looks good"`, self-assertions, no SELECT/`dumpsys`/`content query`/`settings get`) → match
   - **Failing core verification ignored** at completion (agent's last `content query` returned no row, yet `finish` claimed success) → match
   - **Some verification happened** (even if through wrong surface) → not NoIV; assign *Weak Verification* instead
5. **No completion: check for designated verifier bypass.** Rare on Android. If a designated runtime verifier was available and the agent ignored it → match.

**Android-specific exclusion:** if the agent's verification was through a surface the consumer doesn't read from (e.g., agent verified via the same DB it wrote to), that's *Weak Verification*, not NoIV.

---

### Weak Verification

**Framing.**
The agent did verify, but the verification doesn't establish that the consumer can see the change. Two major sub-patterns:

1. **Same-surface verification:** Agent wrote via X, verified via X (where the consumer reads via Y). Canonical Android example: write to `mmssms.db`, SELECT from `mmssms.db`. Consumer (Simple SMS Messenger via ContentResolver listening on `content://sms`) doesn't see the change due to missing notify path.
2. **Wrong-property verification:** Agent's verification checked existence/format but not correctness. E.g., agent inserted an expense with `category=13` (fabricated); verification SELECT confirmed the row exists but didn't check whether `13` is actually the Education category (which it isn't).
3. **Provider-notification gap:** Agent wrote to a DB that *should* be the right surface but didn't trigger the required `ContentResolver.notifyChange()` / broadcast. Consumer's read returns stale state.

Authoritative Android surfaces (treat these as the consumer's read path):
- `adb shell dumpsys <service>` (e.g., `dumpsys alarm`, `dumpsys notification`, `dumpsys wifi`)
- `adb shell content query --uri content://...` against the consumer's read URI
- `adb shell sqlite3 /data/data/<package>/databases/<db>.db "SELECT ..."` *only when* the consumer reads the same DB without provider-layer caching
- `adb shell settings get <namespace> <key>`

**Decision Procedure.**

1. **Identify verification actions.** Does transcript show the agent using checks to judge progress (SELECT/`content query`/`dumpsys`/`settings get`)? *If none:* `weak_verification = false` — assign to *No or Incorrect Verification* instead.
2. **Extract essentials.**
   - **Explicit requirements:** properties for correctness from the task.
   - **Authoritative reader:** the consumer's actual read path. On Android, default to the canonical surface (system content provider when one exists; `dumpsys` for services; `settings get` for system settings).
   - **Implied prerequisites:** state that must be true for the consumer to function.
3. **Compare coverage to essentials.**
   - Was at least one core essential verified through the authoritative reader? (e.g., write to mmssms.db verified via `content query content://sms`)
   - Did the verification catch correctness, not just existence? (e.g., did the agent check that `category=13` actually means Education?)
4. **Apply Android-specific tie-breakers.**
   - **Same-surface read after write** → match (Weak Verification).
   - **Cross-surface read after write** (different surface for verify than write) → no match if the cross-surface confirms.
   - **Provider-notification gap** (wrote to underlying DB but no `notifyChange` / broadcast) → match if the consumer reads via Provider and the agent verified via same DB only.
   - **Strong coverage** (write via X, read via authoritative Y) → no match.
5. **Decide.**
   - Verification covered all core essentials via authoritative reader → no match.
   - Verification missed an essential OR only used same-surface OR data-fabrication-based verification → match.

---

## C.3 Tie-breaker matrix

When multiple leaves match, apply these v2 rules:

| Overlap | Tie-breaker |
|---|---|
| Disobey Spec ↔ Weak Verification (wrong surface + same-surface verify) | If task **named** the consumer → Disobey Spec primary, WV secondary. If consumer was implicit → WV primary, DS secondary. |
| Disobey Spec ↔ RAM (fabrication) | If task **named** the source data → Disobey Spec primary. If source not named, fabrication came after uncertainty in reasoning → RAM primary. |
| Disobey Spec ↔ Step Repetition (low-level IPC guessing) | Disobey Spec primary (wrong API level). Step Repetition secondary if same `service call` retried. |
| Premature Termination ↔ Unaware (P1 conflict) | v2 eliminates this — P1 was removed from Unaware and assigned to PT. |
| Weak Verification ↔ No/Incorrect Verification | Did **any** check happen? If yes → WV. If no → NoIV. |
| Step Repetition ↔ Context Loss | Read/discovery op repeated → Context Loss. Write op repeated → Step Repetition. |
| Step Repetition ↔ RAM (quoting retries) | Encoding errors in observations → RAM (intent right, action wrong). No encoding errors, same intent retried → Step Repetition. |
| Premature Termination ↔ Step Repetition (harness mismatch) | If agent stopped early in despair → PT. If agent kept looping on same blocked verb class → Step Repetition. |

---

## C.4 Mapping — Bottom-up clusters → v2 TB leaves

Validates that v2's 9 leaves cover all empirical failure patterns observed in 211 trajectories (Opus 4.7 classification, May 2026):

| Bottom-up cluster | n | % | v2 primary leaf | v2 secondary |
|---|---:|---:|---|---|
| wrong_surface_or_storage_path | 82 | 39% | **Disobey Specification** (wrong consumer surface) | Weak Verification |
| speculative_value_fabrication | 41 | 19% | **Disobey Specification** (fabrication when source named) | Reasoning–Action Mismatch |
| harness_command_interface_mismatch | 29 | 14% | **Step Repetition** (looping on rejected verb class) | Unaware of Termination |
| premature_negative_conclusion | 23 | 11% | **Premature Termination** (negative PT) | — |
| schema_mapping_guessing | 14 | 7% | **Reasoning–Action Mismatch** (uncertainty-then-commit) | Disobey Spec |
| low_level_ipc_guessing | 11 | 5% | **Disobey Specification** (wrong API level) | Step Repetition |
| permission_or_api_wall_persistence | 6 | 3% | **Unaware of Termination Conditions** (C2: after futility) | Step Repetition |
| finalization_or_output_contract_violation | 3 | 1% | **Disobey Specification** (wrong output format) | — |
| shell_construction_breakage | 2 | 1% | **Reasoning–Action Mismatch** (intent right, encoding wrong) | — |

**Total coverage:** 211/211 (100%) via 9 TB leaves. No new leaves needed.

---

## C.5 Multi-label assignment

Each trajectory MUST receive exactly one `primary_leaf` from the 9 in C.2, plus a (possibly empty) `secondary_leaves` list.

1. Walk each leaf's decision procedure → collect all leaves that match.
2. Apply C.3 tie-breaker matrix to resolve overlaps and pick the single most-specific match as `primary_leaf`.
3. List all other matching leaves as `secondary_leaves`.
4. `_no_match_` is reserved for true rubric gaps; rationale must describe the observed pattern. In v2, `_no_match_` should fire <1% on Android trajectories given the comprehensive coverage proven in C.4.

---

## C.6 What changed from v1 to v2

**Structural changes:**
- v1's leaves: *Data Fabrication*, *Tool-Format Error*, *Constraint Infeasibility* → **dropped as separate leaves**. Reabsorbed:
  - Data Fabrication (content) → *Disobey Specification* (fabrication when source named) + *Reasoning–Action Mismatch* (uncertainty-then-commit)
  - Data Fabrication (mapping) → *Reasoning–Action Mismatch* (uncertainty-then-commit)
  - Tool-Format Error → *Reasoning–Action Mismatch* (intent right, encoding wrong)
  - Constraint Infeasibility → *Premature Termination* (exhausted alternatives with handoff) or *Unaware of Termination* (kept going on infeasible)
- v1 retained TB's "P1 Premature Completion" sub-type inside Unaware → v2 fully moves P1 to *Premature Termination*. PT in v2 has two clean sub-types: positive (false success) and negative (gave up empty).

**Framing changes:**
- All 9 leaves' framings rewritten with Android-native examples (content URIs, system DBs, ADB verbs, harness interface) instead of TB's coding-task examples.
- Decision procedures' Step 2/3 example lists replaced with Android equivalents.
- Exclusion criteria sections expanded with Android-specific cases (quoting variants, force-stop refreshes, schema-discovery re-runs, max-turns-not-Unaware).

**Procedural changes:**
- Reasoning-Action Mismatch: TB's "JSON-only filter" pre-check (Step 2) replaced with "shell-format-only filter".
- Premature Termination: handoff carve-out tightened (≥ 2 distinct alternative surfaces with failure modes, vs v1's permissive "concrete handoff").
- Weak Verification: complete Step 5 decision logic (TB had "Decide output" stub; v2 specifies same-surface vs cross-surface vs notification-gap rules).
- Unaware of Termination: max-turns-only is *not* automatically Unaware (clarified to prevent over-firing).

**New section:**
- C.3 Tie-breaker matrix (8 specific overlap rules).
- C.4 Bottom-up validation table (proves 9 leaves cover all observed patterns).

---

## Iteration log

- **v0** (2026-05-07) — TB Appendix C lifted verbatim. 2 Android edits applied to *Disobey Specification* (output-location framing) and *Weak Verification* (authoritative-evaluator framing). Task Derailment given a placeholder rubric since TB C.2 omits it.
- **v1** (2026-05-10) — Empirical iteration after running v0 across 211 failures with Opus 4.7 judge. Added *Data Fabrication*, *Tool-Format Error*, *Constraint Infeasibility* as new primary leaves. Tightened Premature Termination, added tie-breakers. (Bumped to 12 leaves.)
- **v2** (2026-05-10, same day) — After bottom-up Docent free-form clustering on the same 211 failures rediscovered 9 categories that all map onto TB's 9 leaves, **reverted to TB's 9-leaf taxonomy** but **rewrote every leaf's framing/decision procedure/exclusion criteria to be Android-native** instead of TB-coding-native. v1's leaf additions reabsorbed as sub-patterns. Tie-breaker matrix added.
- **v3 onwards** — Re-validate v2 with LLM judge on 211 trajectories. Compare `_no_match_` rate, primary-leaf distribution against v1 and bottom-up.
