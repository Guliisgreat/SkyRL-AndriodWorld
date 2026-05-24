# Two-Level Failure Taxonomy

This document catalogs the full 2-level failure taxonomy:

- **Top level (paradigm-agnostic):** Terminal-Bench 9-leaf taxonomy + 1 Out-of-Scope category (paper extension)
- **Bottom level (paradigm-specific):** Docent-discovered sub-leaves (clusters) from bottom-up clustering

**Methodology:**

1. Phase 1: per-trajectory failure summary (Claude Opus 4.7)
2. Phase 2: Docent bottom-up clustering on all summaries → emergent clusters
3. Phase 3 cross-walk: 3 cross-family LLM judges (Claude Opus 4.7 + GPT-5.5 Pro + Gemini 2.5 Pro) map each cluster → TB leaf, using `rubric_v2.md` + `rubric_v2_clarifications.md` (16 tie-breakers). Fleiss κ targets ≥ 0.90.
4. Phase 3 classification: per-trajectory cluster labels (Sonnet 4.6 for CLI; Opus 4.7 for GUI)
5. **Fair-comparison filter (applied throughout this doc).** All counts and percentages reported below are restricted to the 103 CLI-solvable AndroidWorld tasks per the ground-truth reference; 13 GUI-only tasks (canvas/maze/camera/transcribe/multi-from-image) are excluded from both paradigms so the CLI and GUI distributions are directly comparable.

## Cross-paradigm summary (fair view)

| paradigm | trajectories | sub-leaves | TB leaves activated |
|---|---|---|---|
| CLI | 1,508 | 15 (after merging 5 clusters) | 4 of 9 |
| GUI | 194 | 15 (after merging 3 clusters) | 3 of 9 |

---

## TB 9-Leaf Definitions

Android-native one-line framings from `rubric_v2.md` §C.1. These are the **paradigm-agnostic top-level labels**; the bottom-level sub-leaves (clusters) under each are paradigm-specific and listed in the per-paradigm sections below.


### Execution group

*the agent's action *itself* deviates from the spec (wrong method, looping, ignoring stop)*

**Disobey Specification.** The agent materially contradicts explicit Android-task directives — including using the **wrong consumer surface** (app DB instead of system provider), the **wrong API level** (binder hacks instead of intents/role-holders), the **wrong output format/protocol** (malformed `finish --description`), or **fabricating data** when the source was named. Also covers the agent disobeying the wrapper's expected input format (per TB11 rev: malformed JSON / un-prefixed verbs / shell-meta-broken commands).

**Step Repetition.** The agent re-executes the same ADB command class against the same content URI / DB path / file path multiple times without strategy change. On Android, *command class* = verb + target surface. Differences in quoting / whitespace / redirection do not count as change.

**Unaware of Termination.** The agent continues acting past an Android-recognizable stopping signal — **confirmed device-state success** (the row is now visible via the canonical reader), **explicit denial** (`run-as: not debuggable`, `Only sync adapters may write`), or **futility** (≥ 2 consecutive identical errors from the same surface).


### Coherence group

*the agent's *reasoning* drifts from observation or task state*

**Reasoning-Action Mismatch.** The agent's stated reasoning is contradicted by its actual command. Android forms: declared method ("use ContentProvider") doesn't match action (used `sqlite3` directly); reasoning admits uncertainty about a mapping then commits to a guessed value; intended command is sound but the emitted shell string is malformed and the agent doesn't notice.

**Context Loss.** The agent forgets or contradicts established Android device state or task content. Forms: re-discovers a package it already found, re-queries the device timezone after using it earlier, paraphrases the task's exact phone number / event title / file content after having captured it.

**Task Derailment.** The agent's pursued sub-goal drifts from the task's primary objective. Android forms: over-investigating one app of a multi-app task, reading an unrelated app's DB, deep-diving an unrelated subsystem (clipboard, accessibility, services).


### Verification group

*the agent's *check* before declaring done is missing, wrong, or weak*

**Premature Termination.** The agent declares completion (via `finish --status complete`) before satisfying explicit or implicit Android objectives. Two sub-types: **positive PT** (claimed success despite missing objective) and **negative PT** (submitted "None" / empty answer for a retrieval task without exhausting filter alternatives).

**Weak Verification.** The agent verified, but through a surface the consumer doesn't read from (verify-via-same-DB-as-write, or only the app's UI not the system provider). On Android, the canonical authoritative surfaces are `dumpsys <service>`, `content query --uri content://...`, or `sqlite3` against system DBs.

**No or Incorrect Verification.** The agent calls `finish --status complete` without any substantive read against an authoritative Android surface (`dumpsys` / `content query` / `sqlite3` / `settings get`) — only self-assertions.

---

# CLI Paradigm

- **Failure trajectories (fair view):** 1,508 — Sonnet 4.6 reasoning=high per-trajectory classification
- **Sub-leaves discovered (Phase 2 Docent):** 15 (after presentation-layer merges)


## Execution

### Disobey Specification

> **Definition.** The agent materially contradicts explicit Android-task directives — including using the **wrong consumer surface** (app DB instead of system provider), the **wrong API level** (binder hacks instead of intents/role-holders), the **wrong output format/protocol** (malformed `finish --description`), or **fabricating data** when the source was named. Also covers the agent disobeying the wrapper's expected input format (per TB11 rev: malformed JSON / un-prefixed verbs / shell-meta-broken commands).

- TB top-level: **Execution**
- Sub-leaves under this TB leaf: **11**
- Phase 2 estimated mass: **78.5%**
- Phase 3 actual share: **74.4%** (1122 of 1508)

#### `wrote_to_wrong_database_surface`

- Description: Agent persisted state to a SQLite file or content provider that the target app does not consume â most often writing SMS rows into /data/data/com.android.providers.telephony/databases/mmssms.db when Simple SMS Messenger reads its own /data/data/com.simplemobiletools.smsmessenger/databases/conversations.db (or vice versa), writing calendar events to content://com.android.calendar instead of Simple Calendar Pro's events.db, or writing Retro Music playlists to MediaStore instead of its private Room DB.
- Transcript signature: Agent's sqlite3/content insert lands in one store (mmssms.db, content://com.android.calendar, content://media/external/audio/playlists, map_markers_db) and verifier reads from a parallel app-private store (smsmessenger/conversations.db, com.simplemobiletools.calendar.pro/events.db, code.name.monkey.retromusic Room DB, favourites.gpx).
- Phase 2 est_fraction: **16.0%**
- Phase 3 actual count: **357** (23.7% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: Per rubric_v2.md §C.2 Disobey Specification form 1 (wrong consumer surface), writing to mmssms.db when the named consumer reads from a different provider/DB is the canonical example. C.3 tie-breaker: when task names the consumer, DS primary, WV secondary.
  - **judge3_v3** → primary=Disobey Specification; rationale: The agent wrote to a database surface that the target application does not read from, which is a "Wrong consumer surface" violation per rubric_v2.md §C.2. This is often paired with verifying on the same incorrect surface, making Weak Verification a suitable secondary.

#### `wrong_output_value_at_correct_surface`

- **Display-merged from 3 bottom-up clusters:**
  - `time_or_timezone_misinterpretation` (Phase 3 count: 80)
  - `recurrence_or_filter_predicate_omission` (Phase 3 count: 76)
  - `byte_exact_file_content_mismatch` (Phase 3 count: 70)
- Description: Agent reaches the correct surface (right DB, right file path, right query target) but emits a wrong value or wrong query semantics: timezone/epoch offset (TB7), missing SQL recurrence/filter predicate (TB10), wrong byte separator or trailing-newline pattern (file content). The agent's reasoning is consistent with the action at each step; the failure is in the *semantic interpretation* of what the spec wanted (which timezone, which recurrence rule, which newline pattern). Per TB3/7/10, this is the canonical 'right surface, wrong value' family of Disobey Specification.
- Transcript signature: Final write hits the verifier's surface (correct sqlite DB / file / content URI) but a specific field — start_ts, dueDate, completed filter, separator, recurrence expansion — fails the per-field check. The agent's prior reasoning explains the wrong interpretation as if it were correct; no observable plan-vs-action divergence.
- Phase 2 est_fraction: **13.0%**
- Phase 3 actual count: **226** (15.0% of classified)
- Skew: balanced
- Per-variant skew: time_or_timezone_misinterpretation (80): semantic time/wall-clock errors; recurrence_or_filter_predicate_omission (76): missing SQL recurrence/filter expansion; byte_exact_file_content_mismatch (70): wrong separator/newline pattern.
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: [time_or_timezone_misinterpretation] Tie-breaker 7 (clarifications) explicitly covers wrong time/timezone interpretation: right surface, wrong value → Disobey Specification (wrong output protocol), with optional RAM secondary when uncertainty was acknowledged.
  - **judge3_v3** → primary=Disobey Specification; rationale: [time_or_timezone_misinterpretation] Per Tie-breaker 7 in rubric_v2_clarifications.md, writing a numerically incorrect time or timezone value to the correct surface is a "wrong output protocol" violation classified as Disobey Specification.
  - **judge1_v3** → primary=Disobey Specification; rationale: [recurrence_or_filter_predicate_omission] Tie-breaker 10 (clarifications) explicitly covers predicate/SQL-semantics omission at correct query target: wrong filter semantics on the right surface → Disobey Specification (wrong output protocol), RAM optional secondary.
  - **judge3_v3** → primary=Disobey Specification; rationale: [recurrence_or_filter_predicate_omission] Per Tie-breaker 10 of rubric_v2_clarifications.md, querying the correct data source with incorrect filter semantics is a "wrong output protocol" violation classified as Disobey Specification.
  - **judge1_v3** → primary=Disobey Specification; rationale: [byte_exact_file_content_mismatch] Tie-breaker 3 (clarifications): right surface (correct file path) but wrong value (byte-level mismatch) maps to Disobey Specification (wrong output format/protocol). Cat-based self-verification is a WV secondary.
  - **judge3_v3** → primary=Disobey Specification; rationale: [byte_exact_file_content_mismatch] The agent wrote a file to the correct path but with incorrect byte-level content, which is a "wrong output format / protocol" violation per Tie-breaker 3 of rubric_v2_clarifications.md. The use of `cat` for verification instead of a byte-level check is a form of We

#### `permission_or_role_blocked_clipboard_or_sms`

- Description: Agent looped on `service call clipboard`/`cmd clipboard`/`content insert content://sms[/sent]`/`service call isms` after each hit Android 13's AppOps focus-foreground gate or default-SMS-role restriction, often misreading a SecurityException Parcel as 'clipboard empty' (writing 'No items' or 0-byte files), or cycling isms transaction codes for 20+ steps to brute force a parcel layout that requires PendingIntent.
- Transcript signature: Repeated `service call clipboard 1/2/4/6 s16 com.android.shell` or `service call isms 5/6/7/9` returning Parcel(fffffffe)/SecurityException stack-trace bytes; agent never pivots to launching a foreground app to read the clip or invoking SmsManager via the default-SMS-app role.
- Phase 2 est_fraction: **6.0%**
- Phase 3 actual count: **127** (8.4% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: Tie-breaker 8 (clarifications) explicitly covers clipboard/SMS read blocked at shell uid: wrong API level → Disobey Specification primary, RAM secondary when SecurityException is misread as empty.
  - **judge3_v3** → primary=Disobey Specification; rationale: Per Tie-breaker 8 in rubric_v2_clarifications.md, attempting to access protected resources from the shell UID is a "wrong API level" violation. Misinterpreting the resulting security error and looping on the failing command shows both Reasoning-Action Mismatch and being Unaware of Termination.

#### `fabricated_artifact_instead_of_invoking_app_pipeline`

- Description: Agent synthesized the artifact (JPEG via base64, MP4 via screenrecord, M4A via tinycap+rename, GPX with invented coords, contact via raw contacts2.db INSERT) and dropped it into the expected path, instead of driving the responsible app (Camera2/.CaptureActivity shutter tap, AudioRecorder MediaRecorder, OsmAnd favorite-add flow, Contacts editor) to produce real provenance bytes/rows.
- Transcript signature: Hand-crafted base64 JPEG/empty-ftyp M4A/screenrecord MP4/`<wpt>`-only GPX is written then 'verified' via ls or MEDIA_SCANNER_SCAN_FILE without ever issuing the canonical capture/record/save intent.
- Phase 2 est_fraction: **9.0%**
- Phase 3 actual count: **108** (7.2% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: Per rubric_v2.md §C.2 DS form 4 (data fabrication when source was named) and form 2 (wrong API level — bypassing the canonical capture pipeline). Hand-crafted bytes substituting for app-produced provenance is a material spec violation.
  - **judge3_v3** → primary=Disobey Specification; rationale: The agent fabricated an artifact instead of using the correct high-level app pipeline (e.g., an intent to the Camera app), which constitutes a "Wrong API level" violation under rubric_v2.md §C.2.

#### `wrapper_input_format_violation`

- **Display-merged from 2 bottom-up clusters:**
  - `shell_quoting_or_harness_parse_blocked_action` (Phase 3 count: 83)
  - `harness_verb_or_command_prefix_violation` (Phase 3 count: 3)
- Description: Agent's emitted shell command / JSON tool-call payload violates the wrapper / harness expected input protocol — apostrophe/quote bugs in SQL strings, multi-line commands rejected by Terminus2's parser, max_tokens truncation that leaves the parser with partial JSON, tool-call prefix violations (bare `<verb>` when the wrapper expects `adb shell <verb>`). The agent's reasoning typically describes a sound command at the abstract level; the failure surfaces at the byte/character level the wrapper enforces. Per TB11 (rev 2026-05-22), this maps to Disobey Specification (wrong output protocol).
- Transcript signature: Wrapper rejects an action before it reaches the device — `<llm-error>` from token-limit truncation, `Extra data: line N column M` from JSON parse failure, `not a recognized verb` from missing `adb shell` prefix, or sqlite syntax error from apostrophe-broken quoting. The agent's reasoning was typically the abstract intent (correct), but the emitted bytes carry the bug.
- Phase 2 est_fraction: **4.5%**
- Phase 3 actual count: **86** (5.7% of classified)
- Skew: bash_tool-skewed
- Per-variant skew: shell_quoting (83): bash_tool-skewed (wrappers enforce strict JSON parsing); harness_verb (3): bash_tool-only (mini-swe-agent enforces `adb shell` prefix).
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: [shell_quoting_or_harness_parse_blocked_action] Tie-breaker 11 (clarifications) explicitly maps harness/wrapper-layer command-syntax failures (quoting, max_tokens truncation, multi-JSON parse errors) to Disobey Specification (wrong output protocol).
  - **judge3_v3** → primary=Disobey Specification; rationale: [shell_quoting_or_harness_parse_blocked_action] Per Tie-breaker 11 in rubric_v2_clarifications.md, a command that violates the wrapper's expected input syntax is a "wrong output protocol" failure classified as Disobey Specification.
  - **judge1_v3** → primary=Disobey Specification; rationale: [harness_verb_or_command_prefix_violation] Tie-breaker 11 (clarifications) explicitly maps harness verb/command prefix violations to Disobey Specification (wrong output protocol — wrapper syntax violation).
  - **judge3_v3** → primary=Disobey Specification; rationale: [harness_verb_or_command_prefix_violation] Per Tie-breaker 11 in rubric_v2_clarifications.md, violating the wrapper's command syntax by omitting a required prefix is a "wrong output protocol" failure. Persisting in this error for many steps also demonstrates being Unaware of Termination conditions.

#### `truncated_input_treated_as_complete`

- Description: Agent read a source file (my_expenses.txt, recipes.txt, task.html, content query dumps of org.tasks/tasks, sqlite .dump output) where the harness cut output mid-line/mid-row, then synthesized fabricated rows or LCG seeds from the visible prefix rather than paginating with sed/tail/wc -l or re-issuing the query with --projection.
- Transcript signature: Observation ends mid-token (e.g. 'Theater Show|$243.1|Entertainment|I may ', 'Side Business|$50.47|Incom', `read_o`) and the next agent action commits INSERTs/finish answers built from invented names ('Dinner Party', 'Tuition Fees', 'Fundraising Events') absent from the visible window.
- Phase 2 est_fraction: **4.0%**
- Phase 3 actual count: **58** (3.8% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: Per rubric_v2.md §C.2 DS form 4 (fabrication when source was named): task named the source file, agent invented rows beyond the visible prefix. RAM secondary because agent committed to fabricated content despite truncation signal.
  - **judge3_v3** → primary=Disobey Specification; rationale: The agent fabricated data based on a truncated input source, which is a "Data fabrication when source was named" violation under Disobey Specification (rubric_v2.md §C.2). This also represents a Reasoning-Action Mismatch, as the agent acts on the incorrect assumption that the partial data is complet

#### `wrong_notebook_root_for_markor`

- Description: Agent inferred Markor's notebook directory from the presence of seeded .md files (typically /sdcard/Documents/Markor/) instead of reading net.gsantner.markor's shared_prefs `pref_key__notebook_directory`, then created folders/notes one directory level too deep (or, conversely, in /sdcard/Markor/ when the verifier expects /sdcard/Documents/).
- Transcript signature: mkdir/write-file targets /sdcard/Documents/Markor/<name> while verifier checks /sdcard/Documents/<name> (or vice versa /sdcard/Markor/<name>); agent never cats the markor shared_prefs XML to confirm the configured notebook root.
- Phase 2 est_fraction: **4.0%**
- Phase 3 actual count: **57** (3.8% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: Per rubric_v2.md §C.2 DS form 1 (wrong consumer surface) — writing to a path Markor's configured notebook root doesn't include means the named consumer can't see it. RAM secondary when agent guessed the path without reading shared_prefs.
  - **judge3_v3** → primary=Disobey Specification; rationale: The agent wrote files to a directory that the Markor app was not configured to use, which is a "Wrong consumer surface" violation per rubric_v2.md §C.2.

#### `apk_static_analysis_loop_without_db_write`

- Description: Pro Expense (and a few Retro Music) tasks where agent locked into 30â50 turns of `strings`/`unzip -p`/`xxd`/`grep -boa`/`dexdump` against base.apk, resources.arsc, classes.dex, base.vdex, and base.odex trying to recover a category-nameâinteger enum or playlist column ordinals, and never executed a single `sqlite3 ... INSERT INTO expense/PlaylistEntity` despite identifying the writable DB path early.
- Transcript signature: Dozens of consecutive observations are APK byte-grep output; the target SQLite file is mapped early but `MAX(expense_id)` stays at its baseline through finish; agent never pivots to `am start` of the app's add-expense fragment.
- Phase 2 est_fraction: **4.0%**
- Phase 3 actual count: **56** (3.7% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: Tie-breaker 6 (clarifications) explicitly covers recon-only budget exhaustion: choosing static-analysis recon over the required mutation is Disobey Specification primary, with Step Repetition secondary only if the same command class repeats.
  - **judge3_v3** → primary=Disobey Specification; rationale: Per Tie-breaker 6 in rubric_v2_clarifications.md, spending the entire budget on reconnaissance instead of performing the required mutation is a Disobey Specification failure. The "loop" description suggests this may also involve Step Repetition.

#### `agent_concluded_no_cli_pathway`

- Description: Agent assumed the task requires UI interaction and gave up on the CLI pathway — fabricating artifacts (hand-crafted bytes/rows), computing answers offline via `bc`/`awk`/sed-injected JS, or calling `finish` with a guessed/empty answer — *without* attempting the canonical shell surfaces (`am broadcast`, `content insert`/`content update`, `sqlite3` INSERT) that ground-truth says exist for these tasks. Every fair-view occurrence is on a CLI-solvable task per the AndroidWorld ground-truth reference, so the cluster captures the agent's *false-impossibility conclusion* (a wrong-API-level Disobey Specification per Tie-breaker 1), not a task property. CLI agents have no screen access; none of these trajectories use a UI.
- Transcript signature: Agent reverse-engineers SeededRNG in `bc`/`awk`, sed-injects `setTimeout(...moveCharacter)` into task.html, or fabricates rows mirroring a UI editor's prefill, then calls `finish` (often with `--status incomplete`) without ever issuing the available `am broadcast`, ContentProvider write, or sqlite INSERT that the verifier would read.
- Phase 2 est_fraction: **10.0%**
- Phase 3 actual count: **29** (1.9% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: Tie-breaker 1 (clarifications) explicitly covers UI-required tasks: choosing offline computation/fabrication over the required UI pathway is wrong API level → Disobey Specification.
  - **judge3_v3** → primary=Disobey Specification; rationale: Per Tie-breaker 1 in rubric_v2_clarifications.md, when a task requires a UI interaction that the agent cannot or does not perform, it is a "wrong API level" violation classified as Disobey Specification.

#### `pm_clear_or_destructive_blanket_action`

- Description: Agent substituted `pm clear <package>` / `rm -rf /sdcard/<entire-dir>` / `DELETE FROM sqlite_master` / `rmdir notebook-root` for a selective row/file operation, wiping all sibling data the verifier expected to remain intact (deleting one expense or recipe by clearing the whole app, deleting all notes by removing the Markor root, dropping VLC trigger to 'fix' the medialibrary then losing the schema).
- Transcript signature: Single `pm clear com.flauschcode.broccoli` / `pm clear com.arduia.expense` / `rm -rf /storage/emulated/0/Documents/*` / `rm vlc_media.db` after run-as denial, followed by finish without inspecting which non-target rows survived.
- Phase 2 est_fraction: **2.0%**
- Phase 3 actual count: **16** (1.1% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: Per rubric_v2.md §C.2 DS — substituting a destructive blanket operation for a selective row/file change materially contradicts the task directive (which scoped the change), violating the implicit preservation of sibling data.
  - **judge3_v3** → primary=Disobey Specification; rationale: The agent used a destructive, non-selective command (`pm clear`) instead of a targeted one, which materially contradicts the implicit task directive and is a form of Disobey Specification. The failure to check the collateral damage constitutes No or Incorrect Verification.

#### `ocr_or_vision_tool_hunt_without_writing_target`

- Description: Task required reading text from a JPEG/PNG (recipes.jpg, expenses.jpg, receipt.png) but the bash sandbox has no tesseract/python/exiftool/Lens; agent burned its entire step budget on `which tesseract`, `strings`/`xxd` over image bytes, MediaStore description columns, GMS vision intents, and chrome-OCR.space netcat hacks, and never executed any INSERT into the target SQLite (broccoli, accounting.db) or wrote receipt.md to Markor.
- Transcript signature: Repeated `which tesseract`/`pm list packages | grep vision`/`strings recipes.jpg`/`base64` loops; trajectory ends with finish (often 'incomplete') and zero `sqlite3 INSERT` against the target app's DB.
- Phase 2 est_fraction: **6.0%**
- Phase 3 actual count: **2** (0.1% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Disobey Specification; rationale: Tie-breaker 2 (clarifications) explicitly maps OCR/vision-required tasks lacking shell OCR pathway to Disobey Specification (wrong API level), with optional Task Derailment secondary.
  - **judge3_v3** → primary=Disobey Specification; rationale: Per Tie-breaker 2 in rubric_v2_clarifications.md, attempting to process image data with byte-tools instead of the implied OCR pathway is a "wrong API level" violation. The extensive hunt for tools without performing the target write also constitutes Task Derailment.


#### *Absent TB leaves under Execution:*

- *Step Repetition* — no clusters mapped here in CLI paradigm
- *Unaware of Termination* — no clusters mapped here in CLI paradigm


## Coherence

### Reasoning-Action Mismatch

> **Definition.** The agent's stated reasoning is contradicted by its actual command. Android forms: declared method ("use ContentProvider") doesn't match action (used `sqlite3` directly); reasoning admits uncertainty about a mapping then commits to a guessed value; intended command is sound but the emitted shell string is malformed and the agent doesn't notice.

- TB top-level: **Coherence**
- Sub-leaves under this TB leaf: **2**
- Phase 2 estimated mass: **15.0%**
- Phase 3 actual share: **15.0%** (226 of 1508)

#### `treated_broadcast_or_intent_dispatch_as_state_change`

- Description: For DeskClock stopwatch/timer, Camera shutter, ACTION_SET_TIMER, ACTION_SENDTO, SET_TIMER, Retro Music queue, OsmAnd track save, and Markor paste tasks, agent fired `am start`/`am broadcast`/`am startservice` with invented or AOSP-only action strings and accepted `result=0`, 'Starting: Intent', `Status: ok`, or a `dumpsys activity topResumedActivity` match as proof, without inspecting persisted shared_prefs/sqlite state or the rendered UI.
- Transcript signature: Repeated `am broadcast -a com.android.deskclock.action.*_STOPWATCH` / `am start -a android.media.action.IMAGE_CAPTURE --ez quickCapture true` / `am start ACTION_SENDTO` followed by `finish --status complete` justified by `result=0` or a `dumpsys` activity line, never by reading the canonical state key (sw_state, timer_state_0, DCIM/Camera file, content://sms row).
- Phase 2 est_fraction: **8.0%**
- Phase 3 actual count: **119** (7.9% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Reasoning-Action Mismatch; rationale: Tie-breaker 9 (clarifications) explicitly maps dispatch-result-as-state-change to RAM primary (agent inferred dispatch ok ⇒ state changed) with WV secondary.
  - **judge3_v3** → primary=Reasoning-Action Mismatch; rationale: Per Tie-breaker 9 of rubric_v2_clarifications.md, treating a dispatch artifact like 'result=0' as proof of a state change is a Reasoning-Action Mismatch. The failure to read persisted state also constitutes Weak Verification.

#### `inverted_or_guessed_enum_mapping`

- Description: Agent guessed an integer encoding without grounding it: org.tasks `importance` (treated as bigger=higher when 0=High), Simple Calendar Pro `repeat_rule` weekday bitmask (left at 0 or guessed), Pro Expense `category` integer (extrapolated odd-number gaps for Education/Income/Transportation), DeskClock `timer_state_0` (cycled 0â2), Simple Calendar Pro `repeat_interval` (1 vs 86400 vs 604800), or `events.type` (0 vs 1 task/event).
- Transcript signature: Agent issues a DISTINCT/MAX probe on an integer column, picks a value by pattern (`>=2`, fill-the-gap, copy-existing) and writes it without consulting APK resources, shared_prefs, or the app UI; verifier mismatch is on a small integer field.
- Phase 2 est_fraction: **7.0%**
- Phase 3 actual count: **107** (7.1% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Reasoning-Action Mismatch; rationale: Per rubric_v2.md §C.2 RAM pattern 3 (uncertainty-then-commit): agent acknowledges enum is unknown then commits a guessed value. C.4 bottom-up mapping confirms schema_mapping_guessing → RAM primary, DS secondary.
  - **judge3_v3** → primary=Reasoning-Action Mismatch; rationale: The agent guessed an integer value for an enum after its reasoning showed uncertainty or a lack of grounding, which is the "uncertainty-then-commit" pattern of Reasoning-Action Mismatch per rubric_v2.md §C.2.


#### *Absent TB leaves under Coherence:*

- *Context Loss* — no clusters mapped here in CLI paradigm
- *Task Derailment* — no clusters mapped here in CLI paradigm


## Verification

### Premature Termination

> **Definition.** The agent declares completion (via `finish --status complete`) before satisfying explicit or implicit Android objectives. Two sub-types: **positive PT** (claimed success despite missing objective) and **negative PT** (submitted "None" / empty answer for a retrieval task without exhausting filter alternatives).

- TB top-level: **Verification**
- Sub-leaves under this TB leaf: **1**
- Phase 2 estimated mass: **5.0%**
- Phase 3 actual share: **5.3%** (80 of 1508)

#### `answer_question_through_wrong_provider`

- Description: For Simple Calendar Pro/OpenTracks/Joplin/Tasks questions, agent queried the AOSP system provider (content://com.android.calendar, content://com.android.calendar/instances/when, content://org.tasks/tasks with --where silently ignored) instead of the app-private SQLite under /data/data/<pkg>/databases/, accepted empty/partial results as final, and answered 'None' or returned an unrelated provider's row as the title.
- Transcript signature: Agent runs `content query --uri content://com.android.calendar/...` for Simple Calendar Pro, gets 'No result found.', calls finish with 'None' or with a system-calendar row; never tries `sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db` or `run-as`.
- Phase 2 est_fraction: **5.0%**
- Phase 3 actual count: **80** (5.3% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Premature Termination; rationale: Tie-breaker 4 (clarifications) explicitly maps Q&A reads from the wrong provider/snapshot path to Premature Termination (negative-PT variant) primary with Weak Verification secondary.
  - **judge3_v3** → primary=Premature Termination; rationale: Per Tie-breaker 4 of rubric_v2_clarifications.md, declaring an answer based on a query to a non-authoritative source without exhausting the correct path is the negative-PT variant of Premature Termination. The read itself is a form of Weak Verification.


### Weak Verification

> **Definition.** The agent verified, but through a surface the consumer doesn't read from (verify-via-same-DB-as-write, or only the app's UI not the system provider). On Android, the canonical authoritative surfaces are `dumpsys <service>`, `content query --uri content://...`, or `sqlite3` against system DBs.

- TB top-level: **Verification**
- Sub-leaves under this TB leaf: **1**
- Phase 2 estimated mass: **7.0%**
- Phase 3 actual share: **5.3%** (80 of 1508)

#### `self_confirming_select_loop`

- Description: After any write (sqlite INSERT, content insert, shared_prefs edit), agent verifies success by re-reading the exact same surface it just wrote to (SELECT on its own INSERT, settings get on its own put, cat on its own write-file), never round-tripping through the live app process, MediaStore notify, content://-resolver view, or `am force-stop`+relaunch.
- Transcript signature: Trajectory ends with `sqlite3 ... SELECT` mirroring an earlier `sqlite3 ... INSERT`, or `settings get` echoing back the value just `settings put`, with no cross-channel check (UI dump, alternate provider URI, app relaunch); agent calls finish on this circular evidence.
- Phase 2 est_fraction: **7.0%**
- Phase 3 actual count: **80** (5.3% of classified)
- Skew: balanced
- Cross-walk rationale (3 judges):
  - **judge1_v3** → primary=Weak Verification; rationale: Per rubric_v2.md §C.2 Weak Verification sub-pattern 1 (same-surface verification): agent wrote via X and verified via X without cross-surface check through the consumer's read path. This is the canonical WV case.
  - **judge3_v3** → primary=Weak Verification; rationale: The agent verified a write by reading from the same surface it wrote to, which is the canonical example of "Same-surface verification" defined in rubric_v2.md §C.2 under Weak Verification.


#### *Absent TB leaves under Verification:*

- *No or Incorrect Verification* — no clusters mapped here in CLI paradigm


## Out-of-Scope

#### *Absent TB leaves under Out-of-Scope:*

- *(not in TB - harness)* — no clusters mapped here in CLI paradigm


---

# GUI Paradigm

- **Failure trajectories (fair view):** 194 — Opus 4.7 reasoning=high per-trajectory classification
- **Sub-leaves discovered (Phase 2 Docent):** 15 (after presentation-layer merges)


## Intervention-type categorization (GUI)

Each sub-leaf is tagged with the **primary intervention** that would most directly address it. All four categories are *mental-model* interventions — consistent with the per-trajectory audit finding that **GUI failures are upstream of execution** (no plan-vs-execution divergence found in 65/65 audited DS trajectories).

### Intervention categories

| code | category | what it fixes |
|---|---|---|
| **P** | **Perception** | screen reading, target disambiguation, visual element ID |
| **K** | **Procedural Knowledge** | UI affordance / Android convention awareness |
| **S** | **Strategic Planning** | task decomposition, method choice, sub-goal ordering |
| **M** | **Self-Monitoring** | screen readback between actions, completion verification, loop detection |

### Roll-up by intervention type (share-weighted)

| code | category | sub-leaves | n | share |
|---|---|---|---|---|
| **M** | Self-Monitoring | `identical_action_loop_until_step_budget_exhausted` (52), `answered_immediately_after_open_app_without_reading_screen` (29), `declared_complete_before_dialog_confirmed` (21), `state_blind_coordinate_loop` (20) | 122 | **62.9%** |
| **K** | Procedural Knowledge | `stuck_on_search_or_filter_dialog_with_wrong_field_type` (11), `wrong_menu_path_for_markor_rename` (10), `missing_long_press_gesture_for_selection_or_marker` (5), `answer_string_emitted_as_unknown_action_or_omitted_entirely` (4), `single_clipboard_slot_overwritten_during_multi_source_merge` (4) | 34 | **17.5%** |
| **S** | Strategic Planning | `skipped_source_image_then_fabricated_destination_entries` (10), `filled_only_one_form_instance_for_multi_item_task` (7), `missing_two_step_record_or_count_observation` (3), `sent_message_in_wrong_conversation_thread` (2) | 22 | **11.3%** |
| **P** | Perception | `deletion_or_move_targeted_wrong_row_or_first_match_only` (11), `wrong_clock_face_digit_in_time_picker` (5) | 16 | **8.2%** |

### Per-sub-leaf intervention assignment

| sub-leaf | TB leaf | intervention | rationale |
|---|---|---|---|
| `identical_action_loop_until_step_budget_exhausted` | (see below) | **M** = Self-Monitoring | doesn't detect no-state-change loop |
| `answered_immediately_after_open_app_without_reading_screen` | (see below) | **M** = Self-Monitoring | doesn't check screen state before answering |
| `declared_complete_before_dialog_confirmed` | (see below) | **M** = Self-Monitoring | doesn't verify final state before completion |
| `state_blind_coordinate_loop` | (see below) | **M** = Self-Monitoring | doesn't read screen state between coordinate actions |
| `deletion_or_move_targeted_wrong_row_or_first_match_only` | (see below) | **P** = Perception | misperceives which file row is the right one (similar names) |
| `stuck_on_search_or_filter_dialog_with_wrong_field_type` | (see below) | **K** = Procedural Knowledge | doesn't know date fields require YYYY-MM-DD format |
| `skipped_source_image_then_fabricated_destination_entries` | (see below) | **S** = Strategic Planning | wrong plan: should open source before destination |
| `wrong_menu_path_for_markor_rename` | (see below) | **K** = Procedural Knowledge | doesn't know Markor's Rename is on long-press, not overflow |
| `filled_only_one_form_instance_for_multi_item_task` | (see below) | **S** = Strategic Planning | wrong plan: should loop for multi-item tasks |
| `wrong_clock_face_digit_in_time_picker` | (see below) | **P** = Perception | misperceives which TimePicker ring is hours vs minutes |
| `missing_long_press_gesture_for_selection_or_marker` | (see below) | **K** = Procedural Knowledge | doesn't know long-press is the right gesture for selection |
| `answer_string_emitted_as_unknown_action_or_omitted_entirely` | (see below) | **K** = Procedural Knowledge | doesn't know answer must be wrapped in action_type:'answer' |
| `single_clipboard_slot_overwritten_during_multi_source_merge` | (see below) | **K** = Procedural Knowledge | doesn't know clipboard is single-slot; needs paste-between-copies |
| `missing_two_step_record_or_count_observation` | (see below) | **S** = Strategic Planning | wrong plan: needs observe-between-actions step |
| `sent_message_in_wrong_conversation_thread` | (see below) | **S** = Strategic Planning | wrong plan: should back out before starting new conversation |

---

## Execution

### Disobey Specification

> **Definition.** The agent materially contradicts explicit Android-task directives — including using the **wrong consumer surface** (app DB instead of system provider), the **wrong API level** (binder hacks instead of intents/role-holders), the **wrong output format/protocol** (malformed `finish --description`), or **fabricating data** when the source was named. Also covers the agent disobeying the wrapper's expected input format (per TB11 rev: malformed JSON / un-prefixed verbs / shell-meta-broken commands).

- TB top-level: **Execution**
- Sub-leaves under this TB leaf: **10**
- Phase 2 estimated mass: **51.0%**
- Phase 3 actual share: **33.5%** (65 of 194)

#### `stuck_on_search_or_filter_dialog_with_wrong_field_type`

- Description: Agent types human-readable date strings ('October 16 2023', '2 hrs') into title-only search fields (Tasks, Broccoli, OpenTracks, Markor), gets empty results, then either answers empty/'0' or loops re-typing the same query without trying scroll-the-list or open-detail alternatives.
- Transcript signature: input_text with a date or category phrase into a top-bar search → empty result screen → repeat input_text or emit answer('0')/answer('') without opening any row.
- Phase 2 est_fraction: **5.0%**
- Phase 3 actual count: **11** (5.7% of classified)
- Skew: balanced
- **Intervention type: K = Procedural Knowledge** — doesn't know date fields require YYYY-MM-DD format
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2_clarifications.md Tie-breaker 13 (stuck_on_search_or_filter_dialog_with_wrong_field_type): typing wrong field-type values into a typed search field violates the protocol = Disobey Spec, with optional Step Repetition for re-typing the same wrong format.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2_clarifications.md Tie-breaker 13 directly maps wrong field-type input in a search/filter dialog to Disobey Specification because the UI field's accepted type is part of the protocol. Re-typing the same bad date/category query after empty results is secondary Step Repetition under the same 
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent provides input of the wrong data type to a search field, violating the UI's protocol, which maps to Disobey Specification according to rubric_v2_clarifications.md, Tie-breaker 13.

#### `deletion_or_move_targeted_wrong_row_or_first_match_only`

- Description: Agent long-presses a visually similar but wrong filename (e.g. '2023_02_13_shy_king_copy.md' instead of 'shy_king_copy.md'), or deletes only the first visible row of a category that has multiple matches, without verifying via OCR/label or scrolling for more.
- Transcript signature: Single long_press at one coordinate → Move/Delete flow completes → status=complete; verifier finds wrong file moved or duplicate entries remaining.
- Phase 2 est_fraction: **4.0%**
- Phase 3 actual count: **11** (5.7% of classified)
- Skew: balanced
- **Intervention type: P = Perception** — misperceives which file row is the right one (similar names)
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2_clarifications.md Tie-breaker 15 (deletion_or_move_targeted_wrong_row_or_first_match_only): wrong target = Disobey Spec (right app, wrong specific row), with optional RAM secondary when reasoning names one row but action hits another.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2_clarifications.md Tie-breaker 15 directly maps deletion_or_move_targeted_wrong_row_or_first_match_only to Disobey Specification because the action targets the wrong row or item. RAM is secondary when the trajectory identifies one intended file or row but the actual long-press/delete operat
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent acts on the wrong list item, which is a 'wrong target' failure that maps to Disobey Specification as defined by rubric_v2_clarifications.md, Tie-breaker 15.

#### `skipped_source_image_then_fabricated_destination_entries`

- Description: Agent launches the viewer app (Simple Gallery, VLC, etc.) for a source media file but navigates_home / switches apps before the image or video is actually rendered, then writes invented Name/Amount/Recipe/Transcription rows into the destination app's form (Pro Expense, Broccoli, Markor) and saves.
- Transcript signature: open_app(viewer) → navigate_home or open_app(destination) within 1-2 steps with no full-screen image/playback observation, followed by input_text actions containing plausible but unverifiable strings (e.g. 'Tomato Soup', 'Grocery Shopping 45.67', 'edna, pineapple').
- Phase 2 est_fraction: **12.0%**
- Phase 3 actual count: **10** (5.2% of classified)
- Skew: balanced
- **Intervention type: S = Strategic Planning** — wrong plan: should open source before destination
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2.md §C.2 Disobey Spec form #4 (fabrication when source named): the task names a specific source image/file and the agent invents destination values without reading it. Analogous to Tie-breaker 2 (vision-required) since the agent never actually consumed the named source.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2_clarifications.md Tie-breaker 2 treats image/video extraction without the implied visual/OCR pathway as Disobey Specification, and rubric_v2.md §C.2 also lists fabricating data from a named source as DS. Because the agent writes invented destination rows after no rendered-source observatio
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent invents data instead of reading it from the named source media file, a direct violation of the 'Data fabrication when source was named' rule in rubric_v2.md §C.2.

#### `wrong_menu_path_for_markor_rename`

- Description: Markor's Rename action lives on long-press of the file row in the file browser, but the agent repeatedly opens the editor's three-dot overflow → File settings / Format submenu or taps the editor title bar, cycling through the same wrong menu items without ever returning to the file list.
- Transcript signature: Repeated taps on Markor editor overflow (1024,~136) → File settings (~755,139) → Format / Move / Table-of-contents submenu, never long_press on the file-list row; filename never changes.
- Phase 2 est_fraction: **5.0%**
- Phase 3 actual count: **10** (5.2% of classified)
- Skew: balanced
- **Intervention type: K = Procedural Knowledge** — doesn't know Markor's Rename is on long-press, not overflow
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2_clarifications.md Tie-breaker 14 (wrong_menu_path_for_markor_rename): wrong UI pathway for the intended action is a wrong-API-level Disobey Spec, not Task Derailment or Step Repetition.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2_clarifications.md Tie-breaker 14 directly maps wrong_menu_path_for_markor_rename to Disobey Specification because the agent uses the wrong UI pathway for Markor Rename. The clarification says not to treat this as Task Derailment because the agent remains on the target object but invokes th
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent uses the wrong UI pathway (editor overflow menu) for the rename action, which is a 'wrong API level' failure as defined by rubric_v2_clarifications.md, Tie-breaker 14.

#### `missing_long_press_gesture_for_selection_or_marker`

- Description: Agent uses single `click` (or `scroll`) where the Android idiom requires `long_press` — Markor file-row deletion, OsmAnd map-marker placement, VLC multi-select, text-selection handles — and loops on the wrong gesture indefinitely.
- Transcript signature: Many click/scroll actions at one coordinate on screens whose target affordance (trash icon, marker menu, multi-select bar) only appears after long_press; long_press never used.
- Phase 2 est_fraction: **7.0%**
- Phase 3 actual count: **5** (2.6% of classified)
- Skew: Qwen3VL-skewed
- **Intervention type: K = Procedural Knowledge** — doesn't know long-press is the right gesture for selection
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2_clarifications.md Tie-breaker 1 (UI-required tasks) extended: long_press is the required UI affordance and the agent uses single click/scroll instead — wrong API/gesture level = Disobey Spec. Secondary Step Repetition for the looping wrong gesture.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2.md §C.2 Disobey Specification covers wrong API level/protocol, and using click or scroll where Android requires a long_press is the wrong UI gesture for the specified action. The indefinite reuse of that same wrong gesture is secondary Step Repetition under §C.2.
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent uses a `click` where a `long_press` is required, violating the UI's interaction protocol, which is a 'wrong API level' failure under Disobey Specification (rubric_v2.md §C.2).

#### `wrong_clock_face_digit_in_time_picker`

- Description: On Simple Calendar Pro NewEventActivity's Material 24-hour TimePicker, agent taps a digit ('4') on the wrong ring leaving the default 16:00 unchanged, or sets only the end time (17:00) without touching start, then saves an event with start_hour ≠ 4.
- Transcript signature: Repeated click around (770,1455) on the clock face for many steps with reasoning 'tap 4', followed by OK and Save without re-reading the start-time chip; saved event has 16:00 or 17:00 start.
- Phase 2 est_fraction: **4.0%**
- Phase 3 actual count: **5** (2.6% of classified)
- Skew: balanced
- **Intervention type: P = Perception** — misperceives which TimePicker ring is hours vs minutes
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2_clarifications.md Tie-breaker 3 (right surface, wrong value): the write reached the correct surface (calendar event saved) but with wrong time value. Family of wrong output protocol.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2_clarifications.md Tie-breaker 7, and Tie-breaker 3 for right surface wrong value, classify time values written to the correct calendar surface but rejected by the verifier as Disobey Specification. The stated plan to tap or set 4 while the actual picker state remains 16:00/17:00 can also b
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent interacts with the correct UI surface but provides wrong input by tapping the wrong location, resulting in a malformed value, mapping to Disobey Specification per rubric_v2_clarifications.md, Tie-breaker 3.

#### `answer_string_emitted_as_unknown_action_or_omitted_entirely`

- Description: Agent has read the correct titles/values but never wraps them in an `action_type:"answer"` JSON — either emitting raw text parsed as action_type=unknown, putting titles in the reasoning field of a status=complete action, or ending without any answer action.
- Transcript signature: Reasoning contains the right comma-separated titles but action_type is 'unknown'/'status'/'wait' rather than 'answer'; verifier reports missing answer payload.
- Phase 2 est_fraction: **4.0%**
- Phase 3 actual count: **4** (2.1% of classified)
- Skew: Qwen3VL-skewed
- **Intervention type: K = Procedural Knowledge** — doesn't know answer must be wrapped in action_type:'answer'
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2.md §C.2 Disobey Spec form #3 (wrong output format/protocol): agent has the correct answer content but emits via wrong action_type wrapper (unknown/status/wait) instead of the required `answer` action — verifier cannot read the answer.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2.md §C.2 Disobey Specification includes malformed final output protocols, and emitting the answer as unknown/status text or omitting the answer action blocks the verifier from reading it. Since the reasoning contains the right values while the emitted action is not an answer, §C.2 Reasoning
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent fails to wrap the final answer in the required action format, which is a 'Wrong output format/protocol' violation that blocks the verifier, as described in rubric_v2.md §C.2.

#### `single_clipboard_slot_overwritten_during_multi_source_merge`

- Description: On Markor multi-note merge tasks, the agent chains Copy operations across all source files before any Paste, so each new Copy overwrites the Android single-slot clipboard; final Pastes deliver only the last file's content (or one word).
- Transcript signature: Sequential open_file → select → Copy → open_file → select → Copy → ... → switch to destination → Paste; pastes contain only the last copied text, sometimes pasted three times.
- Phase 2 est_fraction: **3.0%**
- Phase 3 actual count: **4** (2.1% of classified)
- Skew: balanced
- **Intervention type: K = Procedural Knowledge** — doesn't know clipboard is single-slot; needs paste-between-copies
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2_clarifications.md Tie-breaker 16 (single_clipboard_slot_overwritten_during_multi_source_merge): clipboard mechanics violation is a protocol/Disobey Spec, with optional RAM secondary if reasoning shows multi-source awareness then loses it during execution.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2_clarifications.md Tie-breaker 16 directly maps single_clipboard_slot_overwritten_during_multi_source_merge to Disobey Specification: paste-between-copies is part of the clipboard protocol. The failure is a protocol misunderstanding of the single-slot clipboard, not primary Context Loss per
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent fails to follow the correct copy-paste protocol for a multi-source merge, which is a 'wrong protocol' failure mapping to Disobey Specification per rubric_v2_clarifications.md, Tie-breaker 16.

#### `missing_two_step_record_or_count_observation`

- Description: Tasks requiring an observe-between-actions pattern (start-record then stop-record for video; read per-click number then click again; count items across scrolled viewports) get collapsed into back-to-back taps or single observations, so no artifact or correct aggregate is produced.
- Transcript signature: Two identical shutter/click actions at the same coordinate in consecutive steps with zero wait/observation, then answer/status=complete; or scroll-then-answer using only one viewport's content.
- Phase 2 est_fraction: **5.0%**
- Phase 3 actual count: **3** (1.5% of classified)
- Skew: balanced
- **Intervention type: S = Strategic Planning** — wrong plan: needs observe-between-actions step
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2_clarifications.md Tie-breaker 12 (missing_two_step_record_or_count_observation): skipping the required intermediate observation between actions violates the task protocol = Disobey Spec, with optional Premature Termination secondary when the agent declares done immediately.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2_clarifications.md Tie-breaker 12 directly maps missing_two_step_record_or_count_observation to Disobey Specification because the required observe-between-actions step is part of the protocol. When the agent answers or declares complete immediately after the collapsed action pair, Premature
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent omits a required intermediate observation in a multi-step sequence, which is a 'wrong protocol' failure mapping to Disobey Specification per rubric_v2_clarifications.md, Tie-breaker 12.

#### `sent_message_in_wrong_conversation_thread`

- Description: On SMS forwarding tasks, agent reads the source message in sender's thread, then composes and sends the reply inside the same thread rather than backing out to start a new conversation with the intended recipient.
- Transcript signature: Open Oscar/Sara's thread → read address → input_text → send button tap, no navigate_back to thread list or new-message FAB used; verifier finds no SMS to the named recipient.
- Phase 2 est_fraction: **2.0%**
- Phase 3 actual count: **2** (1.0% of classified)
- Skew: GUIOwl-skewed
- **Intervention type: S = Strategic Planning** — wrong plan: should back out before starting new conversation
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Disobey Specification; rationale: Per rubric_v2.md §C.2 Disobey Spec form #1 (wrong consumer surface): the named recipient's thread is the intended destination; sending into the sender's thread means the consumer (recipient SMS) never receives the message. Wrong-target family per Tie-breaker 15.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: rubric_v2.md §C.2 Disobey Specification covers material contradictions to explicit task directives; sending the SMS in the source conversation violates the named-recipient/thread target. The read-recipient-then-send-in-current-thread pattern also supports Reasoning-Action Mismatch because the action
  - **judge3_gui_v1** → primary=Disobey Specification; rationale: The agent sends a message to the wrong recipient by staying in the source thread, which materially contradicts an explicit task directive and is a Disobey Specification failure per rubric_v2.md §C.2.


### Step Repetition

> **Definition.** The agent re-executes the same ADB command class against the same content URI / DB path / file path multiple times without strategy change. On Android, *command class* = verb + target surface. Differences in quoting / whitespace / redirection do not count as change.

- TB top-level: **Execution**
- Sub-leaves under this TB leaf: **2**
- Phase 2 estimated mass: **30.0%**
- Phase 3 actual share: **37.1%** (72 of 194)

#### `identical_action_loop_until_step_budget_exhausted`

- Description: Agent fires the exact same action (click at one coordinate, scroll in one direction, wait, or open_app) for 30-50 consecutive steps with byte-identical reasoning text, never branching when the screen fails to advance.
- Transcript signature: ≥20 consecutive identical action JSONs (open_app, click(x,y), scroll(down), wait) with verbatim-repeated reasoning text and no observable screen change.
- Phase 2 est_fraction: **18.0%**
- Phase 3 actual count: **52** (26.8% of classified)
- Skew: Qwen3VL-skewed
- **Intervention type: M = Self-Monitoring** — doesn't detect no-state-change loop
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Step Repetition; rationale: Per rubric_v2.md §C.2 Step Repetition: ≥20 byte-identical actions with no material change. Secondary Unaware (C2: after futility) since the agent ignores the absence of any screen change as a denial/futility signal.
  - **judge2_gui_v1** → primary=Step Repetition; rationale: rubric_v2.md §C.2 Step Repetition covers re-executing the same action or command class against the same target without strategy change, which fits 30-50 identical GUI actions with unchanged screen state. Continuing after repeated no-progress observations is also an Unaware-of-Termination C2-style fu
  - **judge3_gui_v1** → primary=Step Repetition; rationale: The agent re-executes the exact same action dozens of times without any change in strategy or screen state, a classic example of Step Repetition as defined in rubric_v2.md §C.2.

#### `state_blind_coordinate_loop`

- **Display-merged from 3 bottom-up clusters:**
  - `fixed_coordinate_delete_macro_on_reflowing_list` (Phase 3 count: 13)
  - `horizontal_chip_row_scroll_failure_in_pro_expense` (Phase 3 count: 4)
  - `calendar_chevron_oscillation_without_view_switch` (Phase 3 count: 3)
- Description: Agent fires a coordinate-bound action sequence (multi-tap macro, scroll-strip, or alternating chevron) repeatedly **without re-reading the screen between cycles**. The action *does* change screen state, but the agent's mental model of the screen doesn't update, so the loop produces wrong-target actions (rows shifted), zero progress (actions cancel each other), or no-effect actions (UI ignored the input). Distinct from `identical_action_loop_until_step_budget_exhausted` which fires the same action when the screen genuinely doesn't change.
- Transcript signature: Repeated coordinate-bound action patterns (≥5 cycles) without any intermediate read/observe step; reasoning narrates expected progress that the rendered screen does not confirm. Three observed app-specific flavors: (a) Broccoli RecipeListActivity 4-tap delete macro at fixed Y while list reflows upward; (b) Pro Expense category chip strip with ≥10 consecutive horizontal scrolls and no taps; (c) Simple Calendar Pro header chevron alternation for 30-44 steps with net-zero position change.
- Phase 2 est_fraction: **12.0%**
- Phase 3 actual count: **20** (10.3% of classified)
- Skew: mixed
- **Intervention type: M = Self-Monitoring** — doesn't read screen state between coordinate actions
- Per-variant skew: Broccoli reflow trap: balanced (all 3 GUI agents); Pro Expense chip strip: MAI-UI-skewed; Calendar chevron oscillation: Qwen3VL-only.
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Step Repetition; rationale: [fixed_coordinate_delete_macro_on_reflowing_list] Per rubric_v2.md §C.2 Step Repetition: identical (verb, target, argument) tap quartets repeated across cycles with no strategy change after the list reflows. Secondary Context Loss because the agent acts as if prior deletions never shifted rows.
  - **judge2_gui_v1** → primary=Disobey Specification; rationale: [fixed_coordinate_delete_macro_on_reflowing_list] rubric_v2_clarifications.md Tie-breaker 15 classifies delete/move actions on the wrong list row as DS, and the reflowing-list macro turns the hard-coded coordinate sequence into wrong-row deletions. The repeated identical delete quartets also match r
  - **judge3_gui_v1** → primary=Step Repetition; rationale: [fixed_coordinate_delete_macro_on_reflowing_list] The agent re-executes the same sequence of fixed-coordinate taps without strategy change as the UI reflows, fitting the definition of Step Repetition in rubric_v2.md §C.2.
  - **judge1_gui_v1** → primary=Step Repetition; rationale: [horizontal_chip_row_scroll_failure_in_pro_expense] Per rubric_v2.md §C.2 Step Repetition: ≥10 consecutive identical scroll(left) actions on same y with no strategy change. Secondary Unaware C2 since identical scrolls produce no observable change (futility ignored).
  - **judge2_gui_v1** → primary=Step Repetition; rationale: [horizontal_chip_row_scroll_failure_in_pro_expense] rubric_v2.md §C.2 Step Repetition covers repeated execution of the same action class against the same target without strategy change, matching repeated horizontal chip-row scrolls. After many no-progress scrolls without tapping or saving, the conti
  - **judge3_gui_v1** → primary=Step Repetition; rationale: [horizontal_chip_row_scroll_failure_in_pro_expense] The agent repeatedly issues scroll actions against the same UI element without changing strategy or making progress, which is a form of Step Repetition and shows futility under rubric_v2.md §C.2.
  - **judge1_gui_v1** → primary=Step Repetition; rationale: [calendar_chevron_oscillation_without_view_switch] Per rubric_v2.md §C.2 Step Repetition: alternating between two header-chevron taps for 30+ steps with net-zero progress is conceptually identical retries against the same surface. Secondary Unaware C2: futility ignored.
  - **judge2_gui_v1** → primary=Step Repetition; rationale: [calendar_chevron_oscillation_without_view_switch] rubric_v2.md §C.2 Step Repetition covers repeated actions on the same target without meaningful strategy change; alternating the same two calendar chevrons is a repeated navigation cycle with no net progress. Continuing that oscillation after repeat
  - **judge3_gui_v1** → primary=Step Repetition; rationale: [calendar_chevron_oscillation_without_view_switch] The agent enters a loop of alternating navigation taps that result in no net progress, which is a form of Step Repetition and demonstrates futility under rubric_v2.md §C.2.


#### *Absent TB leaves under Execution:*

- *Unaware of Termination* — no clusters mapped here in GUI paradigm


## Coherence

*No sub-leaves observed in this paradigm.*

## Verification

### Premature Termination

> **Definition.** The agent declares completion (via `finish --status complete`) before satisfying explicit or implicit Android objectives. Two sub-types: **positive PT** (claimed success despite missing objective) and **negative PT** (submitted "None" / empty answer for a retrieval task without exhausting filter alternatives).

- TB top-level: **Verification**
- Sub-leaves under this TB leaf: **3**
- Phase 2 estimated mass: **21.0%**
- Phase 3 actual share: **29.4%** (57 of 194)

#### `answered_immediately_after_open_app_without_reading_screen`

- Description: For information-retrieval tasks (Calendar/Tasks/OpenTracks questions), the agent emits an `answer` action one step after `open_app`, with no intervening scroll, click, or detail-view navigation, returning either a guessed number, fabricated title list, or '0'.
- Transcript signature: step 0: open_app(X); step 1: action_type=answer with a numeric or comma-separated string; no clicks/scrolls/waits in between.
- Phase 2 est_fraction: **8.0%**
- Phase 3 actual count: **29** (14.9% of classified)
- Skew: GUIOwl-skewed
- **Intervention type: M = Self-Monitoring** — doesn't check screen state before answering
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Premature Termination; rationale: Per rubric_v2.md §C.2 Premature Termination negative-PT: for retrieval tasks, agent submitted an answer without exhausting reasonable filter/observation alternatives. No substantive read of the authoritative surface (the rendered screen) occurred before answering.
  - **judge2_gui_v1** → primary=Premature Termination; rationale: For Q&A, emitting an answer immediately after open_app is declaring a final result before the retrieval objective has been satisfied; rubric_v2.md §C.2 Premature Termination covers final outputs before exhausting the authoritative read path. With no intervening screen/read action, §C.2 No or Incorre
  - **judge3_gui_v1** → primary=Premature Termination; rationale: The agent submits a guessed answer for a retrieval task without performing any on-screen actions to find the information, a form of negative Premature Termination under rubric_v2.md §C.2.

#### `declared_complete_before_dialog_confirmed`

- Description: Agent fills a dialog (folder name, brightness slider, Bluetooth tile tap, time picker, delete confirmation) and emits status=complete or `answer` before tapping the final OK/confirm button or verifying the post-tap state, leaving the operation uncommitted.
- Transcript signature: Last action is an input_text or single dialog tap, immediately followed by action_type=status complete or action_type=answer with no screenshot check; verifier finds no created artifact or unchanged setting.
- Phase 2 est_fraction: **8.0%**
- Phase 3 actual count: **21** (10.8% of classified)
- Skew: GUIOwl-skewed
- **Intervention type: M = Self-Monitoring** — doesn't verify final state before completion
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Premature Termination; rationale: Per rubric_v2.md §C.2 Premature Termination (positive PT): agent declared status=complete before the explicit objective (final OK/confirm tap) was satisfied. No authoritative post-tap verification, hence NIV secondary.
  - **judge2_gui_v1** → primary=Premature Termination; rationale: rubric_v2.md §C.2 Premature Termination covers claiming completion before explicit or implicit Android objectives are met; here the dialog value is not committed because OK/confirm and post-state verification are missing. With no substantive final-state read, No or Incorrect Verification is secondar
  - **judge3_gui_v1** → primary=Premature Termination; rationale: The agent declares the task complete before performing the final confirmation action in a dialog, failing to meet the objective, which is a positive Premature Termination failure per rubric_v2.md §C.2.

#### `filled_only_one_form_instance_for_multi_item_task`

- Description: Task requires N items (recipes, transactions, expenses) to be created/deleted, but the agent saves only one entry and declares complete, or treats a multi-recipe file as a single copy-paste into one Title field.
- Transcript signature: Single FAB → input_text → input_text → SAVE → status=complete, with no loop counter and no re-entry to the form; verifier expects multiple rows in the destination app.
- Phase 2 est_fraction: **5.0%**
- Phase 3 actual count: **7** (3.6% of classified)
- Skew: balanced
- **Intervention type: S = Strategic Planning** — wrong plan: should loop for multi-item tasks
- Cross-walk rationale (3 judges):
  - **judge1_gui_v1** → primary=Premature Termination; rationale: Per rubric_v2.md §C.2 Premature Termination (positive PT): agent declared complete with explicit objective (N items) unmet, only 1 of N saved. Secondary Disobey Spec since the task's count is an explicit directive.
  - **judge2_gui_v1** → primary=Premature Termination; rationale: rubric_v2.md §C.2 Premature Termination covers declaring completion with unmet objectives; creating only one of N required entries leaves the multi-item objective unsatisfied. Because the transcript shows no substantive count/readback of all expected rows, No or Incorrect Verification is secondary u
  - **judge3_gui_v1** → primary=Premature Termination; rationale: The agent stops after creating only one of N required items and declares completion, a positive Premature Termination failure for not meeting an explicit task objective, per rubric_v2.md §C.2.


#### *Absent TB leaves under Verification:*

- *Weak Verification* — no clusters mapped here in GUI paradigm
- *No or Incorrect Verification* — no clusters mapped here in GUI paradigm


## Out-of-Scope

#### *Absent TB leaves under Out-of-Scope:*

- *(not in TB - harness)* — no clusters mapped here in GUI paradigm


---

## Tie-breaker rules referenced

All cross-walk decisions follow the base `rubric_v2.md` plus 16 numbered tie-breakers in `rubric_v2_clarifications.md`:

| # | covers cluster pattern | maps to |
|---|---|---|
| TB1 | UI-required tasks (no shell pathway) | Disobey Specification (wrong API level) |
| TB2 | OCR/vision-required tasks | Disobey Specification (wrong API level) |
| TB3 | Right surface, wrong value | Disobey Specification (wrong output format) |
| TB4 | Q&A from wrong provider | Premature Termination |
| TB5 | Intent to nonexistent receiver | Reasoning-Action Mismatch |
| TB6 | Recon-only without mutation | Disobey Specification |
| TB7 | Timezone/epoch misinterpretation | Disobey Specification (right surface, wrong value) |
| TB8 | Clipboard read from shell uid | Disobey Specification (wrong API level) |
| TB9 | Dispatch-as-state-change | Reasoning-Action Mismatch |
| TB10 | SQL predicate / filter omission | Disobey Specification |
| TB11 | Harness/wrapper-layer failures (rev 2026-05-22) | Disobey Specification (wrong output protocol) |
| TB12 | Skipped intermediate observation step (GUI) | Disobey Specification |
| TB13 | Wrong field-type input in dialog (GUI) | Disobey Specification |
| TB14 | Wrong menu/navigation path (GUI) | Disobey Specification |
| TB15 | Wrong row/item target on list (GUI) | Disobey Specification |
| TB16 | Clipboard overwrite during multi-source merge (GUI) | Disobey Specification |

For full text of each tie-breaker, see:
- CLI: `docent_analyses/2026-05-21_android-cli-failures-combined/rubric_v2_clarifications.md`
- GUI: `docent_analyses/2026-05-22_android-gui-failures/rubric_v2_clarifications.md`
