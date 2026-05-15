# Phase 2.3 — Blind Reading Notes (10 trajectories)

**Date:** 2026-05-07
**Reader:** Claude (pilot, no co-annotator)
**Source set:** `pilot_set.jsonl` (126 readable failures, seed 30)
**Sample seed:** 11
**Rubric in hand:** `rubric/rubric_v0.md` (TB Appendix C verbatim + Android edits to *Disobey Specification* and *Weak Verification*; placeholder rubric for *Task Derailment*)

> Per Phase 2.3 protocol, this is a **blind read**. No leaf assignments yet.
> Just observations of what each agent did and where it appears to have gone wrong.
> Goal: identify ambiguities and gaps in the rubric before the labeling phase.

---

## Per-trajectory observations

### 1. Terminus2 / task 102 — "High-priority tasks due Monday after next" (Tasks app)
- **What happened:** Agent discovered `org.tasks` DB, learned schema, queried with date-range filters in unix-millisecond timestamps. Iterated SQL ranges 4 times trying to find the right window. Got conflicting results across queries (no rows for one range, "Quarterly Sales Review" with importance=0 for another). Trajectory ends without `finish` call.
- **Notable:** The agent's first SQL query failed with `Error: incomplete input` due to shell-escaping (steps 7→8 were the same query with different quoting). Agent **adapted** rather than retrying blind — reasonable.
- **Likely failure mode:** Either ran out of context budget without committing to an answer, or computed wrong "Monday after next" semantically (the agent treated Oct 23 UTC as Monday, but device timezone might be different, and "after next" interpretation is ambiguous).
- **Doesn't fit cleanly:** the trajectory just *ends* without a finish call. None of the 9 leaves cover "stopped without declaring completion".

### 2. Terminus2 / task 021 — "Add 'Tuition Fees' to Pro Expense" (Education category)
- **What happened:** Discovered DB, found `expense` table with `category INTEGER`. Tried `content insert` against the Pro Expense provider — got "Could not find provider" (provider not exported). Fell back to direct `sqlite3 INSERT` with `category=4` *without verifying* that 4 maps to "Education". Verified row exists by re-querying same DB. Force-stopped app.
- **Likely failure mode:** Fabricated the category-name→id mapping. The agent's own system prompt principle 1 says "recover the mapping by `SELECT DISTINCT <text_field>, <id_field>` from existing rows" — but the existing `expense` table has no text field, only the integer. Mapping is recoverable only from app resources (strings.xml inside APK), which isn't trivial. Agent picked 4 by guess.

### 3. Terminus2 / task 067 — "Send SMS to +18490934066 with body 'The library book is due back on the 15th.'"
- **What happened:** Tried 5 variants of `content insert --uri content://sms/` — all returned the `usage:` error (argument-parse failure, likely shell-quoting + provider permissions combined). Pivoted to direct `sqlite3 INSERT` against `com.simplemobiletools.smsmessenger/conversations.db`. Inserted into both `conversations` and `messages` tables. Verified via the same DB.
- **Likely failure mode:** Wrote to the **app's local DB**, not the system SMS provider (`content://sms/`). The eval almost certainly reads from the system provider. Even if eval reads the app DB, the agent's INSERT used `id=1` as a hardcoded primary key — likely conflicts.
- **Notable:** 5 successive `content insert` attempts all hit the same `usage:` error wall. This is a candidate **Step Repetition** under the rubric (semantically identical with no strategy change), but the agent did vary surface arguments each time — borderline.

### 4. Terminus2 / task 082 — "Add recipes from recipes.txt that take 1 hr to Broccoli"
- **What happened:** Discovered Markor's recipes.txt and Broccoli's SQLite DB. Read recipes.txt (mixed prep times). Inserted 3 recipes into Broccoli's `recipes` table with `preparationTime='1 hrs'`. Verified by querying back. Force-stopped.
- **Likely failure mode:** Couldn't see the rest of recipes.txt due to truncation in our viewer — but the agent likely picked a wrong subset of recipes (selection error). Direct SQL also bypasses Broccoli's Room/FTS triggers, which may leave the search index inconsistent.

### 5. MiniSWE / task 048 — Pro Expense (3 expenses: Tuition Fees / Dinner Party / Reimbursements)
- **What happened:** 14 turns. Discovered package, schema, sample rows. Found existing categories: 1, 3, 5, 7, 9, 11 (odd numbers only). Could only confirm `Social=5` from the sample data. Per its system prompt principle "extend the observed integer pattern", **picked 13 for Education and 15 for Income by guess**. Inserted 3 rows. Verified by re-querying same DB. Submitted "Added 3 expenses... and verified".
- **Notable:** Step 23 had a `<returncode>2</returncode>` "HTTP request failed" — a tool-pipeline error. Agent ignored it.
- **Likely failure mode:** Fabrication of category mapping (same as Terminus2/021, but explicitly so — agent reasoned about it then guessed anyway). Education and Income are not at category=13 or 15 in this app.
- **Doesn't fit cleanly:** This is interesting — agent's reasoning is correct ("I lack a definitive mapping"), the action is the **acknowledged risky guess**, the agent then verified its own fabrication. Three leaves potentially apply: *Disobey Specification* (wrong source of truth — should have checked APK strings or reported infeasibility), *Weak Verification* (verified the fabricated insert via the same DB it wrote to), *Reasoning–Action Mismatch* (reasoning admits uncertainty but action proceeds as if confident). Hard to pick one.

### 6. MiniSWE / task 066 — "Resend the message I just sent to Ian Pereira"
- **What happened:** Found Ian's number, found last sent message. Tried `content insert content://sms/sent` (no row). Tried service-level: `cmd phone`, `isms`, `imms` — none expose SMS-send verbs. Tried setting Simple SMS Messenger as the default SMS app via `cmd role add-role-holder` — still blocked. **Submitted** with description: "Could not resend the SMS under the given constraints..." with concrete handoff describing all attempted paths.
- **Likely failure mode:** This is the cleanest "infeasibility under constraints" case. Agent was honest, comprehensive, terminated correctly. Eval still scored 0.
- **Doesn't fit cleanly:** Per Premature Termination rubric, the agent provided "a concrete, actionable handoff that enables continuation" — so it's NOT premature termination. Per all other leaves, the agent didn't make any mistake. **No leaf in the rubric matches "task is infeasible under given constraints AND agent recognized this correctly".** This is a real gap.

### 7. MiniSWE / task 059 — "Create playlist 'Party Mix 553' (45–50 min) in Retro Music"
- **What happened:** Discovered MediaStore audio API. Listed songs with durations. Calculated 11-song playlist totaling 45m38s. Created via `content insert content://media/external/audio/playlists`. Added members via `content://media/.../playlists/<id>/members`. Verified members through the same URI. Submitted success.
- **Likely failure mode:** Retro Music (`code.name.monkey.retromusic`) maintains its own playlist DB, and recent versions ignore MediaStore playlists entirely. Agent never checked Retro Music's own data dir — went straight for MediaStore as a generic surface.
- **Cleanly fits:** *Weak Verification* — verified through a surface (MediaStore) that the consumer (Retro Music) doesn't read from. Matches the Android-edited rubric well.

### 8. MiniSWE / task 073 — VLC playlists (Mystery and Thrills Series + Ultimate Fails Marathon)
- **What happened:** Found VLC's `medialib/playlists/` folder (empty). Wrote two `.m3u` files there. Force-stopped VLC. Submitted success.
- **Likely failure mode:** VLC's `medialib/` is for VLC's own SQLite cache (`medialib.db`), not for user-dropped .m3u files. The .m3u files won't be picked up unless VLC scans them at next launch — and even then they don't appear as "playlists" the way the app's UI defines them.
- **Cleanly fits:** *Disobey Specification* (Android edit) — wrong write surface; *or* *Weak Verification* (no verification of whether VLC actually loaded the playlists).

### 9. MiniSWE / task 074 — OsmAnd favorite for Schaan, Liechtenstein
- **What happened:** Found OsmAnd's `favorites/` folder (empty). Tried multiple times to find a sample .gpx — all hit shell-quoting errors. Eventually wrote `favorites.gpx` with the waypoint. Force-stopped. Submitted success.
- **Likely failure mode:** OsmAnd in recent versions stores favorites in `favorites.db` (SQLite), not GPX. Even if GPX were valid, the agent never verified by reading the file back through the surface OsmAnd uses.
- **Notable:** Steps 4, 6, 8 all attempted to read existing GPX files but **all 3 failed with shell-quoting errors**. The agent eventually gave up trying to read examples and wrote a guessed schema. This is a fragile-tooling tax that bleeds into rubric questions: is this Step Repetition (3 identical-intent commands) or Reasoning-Action Mismatch (intent was right, the shell encoding was wrong)?

### 10. ClaudeCodeCLI / task 048 — Pro Expense (50 turns, hit max_turns)
- **What happened:** Discovered package, used `su 0` (root works on this emulator). Got schema + existing categories (1,3,5,7,9,11). Then went deep: tried to extract APK with `aapt`, then with `dumpsys package`, then ls'd `/data/app/...` directories. **Violated own system prompt** which explicitly forbids "extracting APKs (`unzip`/`xxd`/`strings` on `base.apk` or `classes.dex`)" as a "forbidden time-sink". Hit 50-turn limit. Trajectory truncated past step 24 in our reading window.
- **Likely failure mode:** *Unaware of Termination Conditions* (kept going past evident futility) **and/or** *Disobey Specification* (violated explicit prohibition in system prompt). Possibly also *Step Repetition* (multiple iterations of same APK-extraction approach with minor variants).
- **Cleanly fits:** *Disobey Specification* — clear violation of an explicit `Forbidden` directive in the prompt. The Android-edited rubric still applies because directive was explicit. Worth noting that Disobey Specification can target the agent's *own* system prompt, not just the task description.

---

## Aggregate observations

### Recurring failure patterns (informal — not rubric assignments)

1. **Fabricated mappings** — agent guesses a category/enum/id without recovering it from data (trajs 2, 5).
2. **Wrong write surface** — agent writes to the app's local DB or shared storage when the consumer reads through MediaStore/system provider, or vice versa (trajs 3, 7, 8, 9).
3. **Verification of own writes through the same surface** — verifies an INSERT by re-SELECTing from the table just written, not from the consumer's read path (trajs 2, 3, 5, 7, 8).
4. **Shell-quoting fights** — agent emits a command, observes a quoting error, retries with slightly different quoting (trajs 1, 3, 4, 9). Often 2–5 turns wasted before working past it.
5. **No `finish()` call** — Terminus2 trajectories often end without explicit completion (trajs 1, 2, 3, 4). May reflect Terminus2's pipeline more than agent intent.
6. **Honest infeasibility** — agent recognizes constraint limits, provides handoff, submits anyway (traj 6).
7. **Self-prompt violation** — agent's actions contradict its own system prompt's explicit prohibitions (traj 10).

### Rubric ambiguities surfaced

- **AMBIG-1 (Step Repetition vs. Reasoning–Action Mismatch on quoting errors).** When an agent emits a syntactically-malformed command 3+ times before fixing it, is that Step Repetition (semantically identical action) or Reasoning–Action Mismatch (intended SQL was correct but shell encoding was wrong)? Affects trajs 3, 4, 9. **Action for v1:** add an explicit tie-breaker line to *Step Repetition* — "If repetitions are caused by tool-format/quoting errors that the agent observably tries to correct, prefer *Reasoning–Action Mismatch* unless the same underlying *intended* action is repeated >5 times".

- **AMBIG-2 (Disobey Specification vs. Weak Verification on wrong-surface writes).** When the agent writes to an app's private DB and the eval reads via the system content provider, both leaves can apply: *Disobey Specification* (using the wrong source of truth) or *Weak Verification* (didn't verify through the consumer's read path). The Android edit to Weak Verification covers verification specifically — but the *write* itself is what's wrong here. **Action for v1:** in *Weak Verification*, clarify that "wrong write surface AND verification through that same wrong surface" gets *Weak Verification*; "wrong write surface but no verification at all" gets *Disobey Specification*.

- **AMBIG-3 (Reasoning–Action Mismatch when reasoning is correct *uncertainty*).** Traj 5: agent reasons "I lack a definitive mapping for Education and Income", then guesses 13 and 15. Reasoning correctly admits uncertainty; action proceeds as if certain. Is this RAM (reasoning-action mismatch) or Disobey Specification (wrong source of truth) or Weak Verification (verified the guess via the same DB)? **Action for v1:** *Reasoning–Action Mismatch* should explicitly cover "reasoning admits uncertainty/incomplete information, action proceeds without resolving it".

### Possible new leaf? — "Infeasibility under constraints"

Traj 6 (MiniSWE/066): agent tried all reasonable surfaces, recognized infeasibility, submitted with handoff. By the rubric, this matches **none** of the 9 leaves. Yet the eval scored 0.

Two interpretations:
1. This is a **benchmark/task-design failure**, not an agent failure mode. Should be excluded from the analysis (similar to how I excluded environment-crash trajectories during Phase 1.2).
2. This is a real agent failure mode — the agent could have tried *more* surfaces (e.g., `am start` with deeplink to Simple SMS's compose screen) but chose to give up. Should be a new leaf, perhaps "Premature Surrender" or "Insufficient Surface Exploration".

Per the pilot doc's rule ("add only if Step 2.3 surfaces ≥ 2 trajectories that clearly don't fit"), I see only 1 clear case of (1)/(2) ambiguity in this 10. **Defer adding a leaf**. Re-examine after Phase 3 hand-labeling of 30; if more cases of "honest-infeasibility-but-eval-fails" appear, revisit.

### Trajectories that ended without finish() call (Terminus2 specifically)

4 of 4 Terminus2 picks (trajs 1, 2, 3, 4) end without an explicit completion call. This may be a Terminus2-pipeline artifact (timeout vs. explicit `finish`). Per the rubric, none of these qualify as *Premature Termination* because the rubric requires "the agent declared completion". They might instead be flagged as `step_count == max_turns` "ran out of turns" cases — distinct from agent-decision failures.

**Recommendation:** before Phase 3, audit the 36 Terminus2 trajectories in `pilot_set.jsonl` to see what fraction end in apparent timeout vs. agent decision. If most are timeout, treat that subset as a separate "ran-out-of-turns" diagnostic axis rather than a leaf assignment.

### Coverage of rubric leaves in this 10-pick

Leaves I plausibly observed at least once:
- **Disobey Specification** — trajs 3, 8, 9, 10 (write surface / forbidden APK extraction)
- **Step Repetition** — trajs 3, 9 (quoting retries — borderline)
- **Unaware of Termination Conditions** — traj 10 (kept going at 50 turns)
- **Reasoning–Action Mismatch** — traj 5 (reasoning admits uncertainty, action proceeds)
- **Context Loss** — *not observed*
- **Task Derailment** — *not observed*
- **Premature Termination** — *not observed* in my reading; traj 6 LOOKS like it but the rubric's handoff exception applies
- **No or Incorrect Verification** — *not observed* — every trajectory verified something
- **Weak Verification** — trajs 2, 5, 7, 8 (verified through same surface as the write)

Two leaves I never observed (Context Loss, Task Derailment) — possibly because the 10-pick was too small, or because CLI agents may genuinely not exhibit them often. Worth watching during Phase 3 hand-labeling.

---

## Decisions for v1 rubric (after Phase 3 hand-labeling)

Don't iterate yet. Per the pilot doc, edit the rubric *after* hand-labeling 30 trajectories in Phase 3. The above ambiguities (AMBIG-1/2/3) are candidate edits to consider then. Likely v1 changes:

- Tighten *Step Repetition* exclusion against shell-quoting retries
- Tighten *Weak Verification* to cover "wrong write surface verified through same wrong surface"
- Expand *Reasoning–Action Mismatch* framing to include "reasoning admits uncertainty, action proceeds without resolving"
- Decide whether *Task Derailment* is mergeable into *Context Loss* (zero observations in 10 picks; will keep watching)

Defer entirely:
- Adding a "Premature Surrender" / "Infeasibility" leaf — not enough signal yet
- Removing any leaf — too early
