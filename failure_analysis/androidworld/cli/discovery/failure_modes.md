# Bottom-Up Failure Modes — Claude Opus 4.7 (max effort)

**Method:** 2-phase Claude Code CLI pipeline, no Docent, no v2-rubric anchoring.
**Pool:** 211 CLI-solvable readable failures, 3 agent classes × 6 model combos.
**Phase 1:** 211 per-trajectory root-cause summaries (Claude opus-4-7 max effort).
**Phase 2:** 1 synthesis call over all summaries (Claude opus-4-7 max effort, 254s).

## Overarching observations

The single largest cross-agent pattern is data-store confusion: agents reflexively reached for AOSP system providers (CalendarContract, content://sms, MediaStore) when third-party apps like Simple Calendar Pro, Simple SMS Messenger, and Retro Music maintain their own private SQLite/Room databases — producing writes that never reached the verifier's read path, and Q&A answers of 'None' based on querying empty wrong-source providers. A second cross-cutting pattern is 'fake the end state via raw sqlite3' — when high-level surfaces (content insert, run-as, SmsManager) were blocked, agents progressively escalated to root sqlite writes that bypassed Room invalidation, FTS indexes, default-SMS-role permission gating, and ContentObserver notifications, satisfying their own readback queries but leaving app-managed state inconsistent. Terminus2 was distinctive for a harness-level failure: its action interface required a registered verb wrapper (likely `adb shell`), but agents persistently passed bare shell binaries as the first token and burned ~25 of its 78 runs cycling through alternate binaries instead of fixing the envelope — an entire failure class that ClaudeCodeCLI and MiniSweAgent essentially never exhibited because they used the shell directly. Across all three agents, the Pro Expense category-ID and org.tasks importance-encoding tasks consistently elicited fabricated/inverted enum mappings (categories extrapolated from observed odd-number sequences, importance=3 read as 'high' when 0=High), suggesting all models share a default 'higher integer = higher priority / next-in-sequence = valid' prior that goes unverified.

## Failure modes (proposed)

### 1. `wrote_to_wrong_app_data_store` (~22%)

**Description:** Agent reflexively targeted a system/AOSP provider or generic Android surface (content://com.android.calendar, content://sms, content://media/external/audio/playlists, content://contacts) when the third-party target app keeps its data in its own private SQLite/Room database under /data/data/<pkg>/. Includes Q&A tasks where the agent queried the wrong source, got empty results, and answered 'None' without ever inspecting the target package's sandbox.

**Transcript signature:** Agent runs `content insert --uri content://com.android.calendar/events` or queries content://com.android.calendar/instances, then verifies through the same URI it just wrote/read, while never touching /data/data/com.simplemobiletools.calendar.pro/databases/ or the target app's own provider authority.

### 2. `raw_sqlite_write_bypassed_app_pipeline` (~16%)

**Description:** Agent located the correct app database and inserted/updated rows directly via root sqlite3, but skipped Room's InvalidationTracker, FTS index updates, ContentObserver notifications, the default-SMS-app role gate, or SmsManager's transmission path — and often force-stopped the target app without relaunching so the in-memory state never reconciled. Includes SMS tasks where direct mmssms.db / conversations.db writes substituted for an actual send.

**Transcript signature:** After `content insert` silently returns 'No result found' (provider rejection) or `run-as` is denied, agent escalates to `adb shell sqlite3 /data/data/<pkg>/databases/<file> 'INSERT INTO ...'` and treats its own follow-up SELECT readback as proof of success.

### 3. `terminus2_command_envelope_misuse` (~13%)

**Description:** Agent treated the harness's `command` field as a raw shell line and submitted bare binaries (pm, ls, am, cmd, dumpsys, echo) as the first token, while the Terminus2 action dispatcher required a registered action verb (likely an adb_shell/bash wrapper) — every call returned 'X is not a recognized verb' before any bytes reached the device. The agent burned its full budget cycling through alternative binaries rather than recognizing the error came from the harness layer, not the shell.

**Transcript signature:** Twenty-plus consecutive steps with identical 'is not a recognized verb' rejections as the agent swaps the leading token between ls, pm, cmd, sh, /system/bin/ls, true, echo — and the only command that ever dispatches is `finish`.

### 4. `fabricated_values_after_failed_or_truncated_read` (~10%)

**Description:** After a `cat`/`sed` output was visibly truncated, a clipboard read returned an error or empty Parcel, or geocoding/network access was unavailable, the agent invented specific values (transaction names, recipe ingredients, lat/lon coordinates, paste payload, SongEntity metadata) from prior knowledge or filename tokens rather than re-reading, paginating, or pivoting to a different source. The committed write contains data that never appeared in any prior tool observation.

**Transcript signature:** An earlier `cat` output ends mid-line or returns empty, then a few steps later the agent's INSERT or write command carries specific string/numeric literals that don't appear anywhere in the captured tool output above.

### 5. `guessed_or_inverted_integer_enum_mapping` (~8%)

**Description:** Agent saw an integer-typed column (Pro Expense category, org.tasks importance, brightness level) and either extrapolated a pattern from a small sample (e.g., extending odd-number category IDs 1,3,5,7,9,11 → 13,15) or assumed a standard numeric direction (higher integer = higher priority), when the app's real enum has a different or inverted encoding (org.tasks: 0=High, 3=None). The row write or filter then used semantically wrong IDs.

**Transcript signature:** Agent observes a distinct-values set like {1,3,5,7,9,11} or {0,1,2,3} and immediately picks the next integer or the largest value as its target — without consulting APK resources, app UI, or a known-labeled reference row to confirm the mapping.

### 6. `reconnaissance_burnout_no_mutation` (~10%)

**Description:** Agent spent its entire step budget on discovery — `strings base.apk | grep`, repeated `service call <svc>` binder transaction-code probing, `dumpsys package` enumeration, broadcast-receiver coaxing of MediaScanner, or cycling speculative `content://` URIs — and never issued the required INSERT/DELETE/send action before timeout. Includes cases where the agent had a viable fallback (educated-guess INSERT) and refused to take it.

**Transcript signature:** Step count approaches the 50-turn budget while the agent is still re-running variants of the same probing command (different transaction codes, alternate grep patterns, additional resources.arsc/od/xxd attempts) and the database/provider it needs to mutate has the same state as at step 1.

### 7. `filesystem_artifact_without_app_ingestion` (~7%)

**Description:** Agent wrote a GPX, M3U, or note file to a shared-storage or app-external directory expecting the target app to auto-discover and index it on next launch, often issuing a MEDIA_SCANNER_SCAN_FILE broadcast or `am force-stop` as the only 'sync', without ever launching the app, importing through its intent, or writing into the app's internal medialibrary/favorites database that actually tracks the entity.

**Transcript signature:** Agent constructs a GPX/M3U file under /sdcard/Android/data/<app>/files/.../ or similar, runs `am force-stop <pkg>`, immediately calls finish — and never invokes `am start` to launch the app, never inserts into the app's internal Playlist/PlaylistMediaRelation/gpxTable/favourites SQLite tables.

### 8. `wrote_to_wrong_filesystem_directory` (~5%)

**Description:** Agent created the file or folder at a non-canonical path inferred from the package name or first-found plausible directory (e.g., /sdcard/Documents/Markor/ vs /sdcard/Markor/, OsmAnd's external favorites/ vs internal map_markers DB), often after a missed shared_prefs probe or after substituting an alternate location when the canonical path appeared absent. The verifier inspects the configured notebook root that the agent never confirmed.

**Transcript signature:** Agent's shared_prefs read returned empty or failed with a shell-quoting error, after which the agent picked a directory matching the app's display name and proceeded to `mkdir`/`echo >` there without re-attempting the configuration lookup or asking the app via intent.

### 9. `byte_level_content_separator_mismatch` (~3%)

**Description:** File content was written with the wrong byte structure — double newlines from `printf '\n'`/`echo ""` separators stacked on top of source files that already ended with `\n`, missing trailing newline from `printf '...!'`, or other separator/terminator choices — so the verifier's exact-content equality check fails by a handful of bytes despite the visible text looking correct.

**Transcript signature:** Agent uses `printf '%s\n\n%s\n\n%s'` or interleaves `cat file; printf '\n'; cat file` without first inspecting whether each source file already ended in `\n`, then declares success based on a `cat` of the output that visually 'looks right'.

### 10. `date_or_timezone_window_off` (~4%)

**Description:** Agent computed wrong epoch boundaries — confused UTC with the device's local timezone, hand-derived timestamps after `date -d` failed, miscounted 'Friday after next' (off by one week), or used a one-sided `start_ts > X` filter without an upper bound — so its SQL window or event insert targeted the wrong calendar day or wrong hour-of-day.

**Transcript signature:** Agent hardcodes specific Unix-seconds constants like 1698144000 or 1698116340 after a `date -d 'tomorrow'` invocation fails, then trusts the resulting query rows or INSERT without running `datetime(<ts>, 'unixepoch', 'localtime')` to sanity-check the boundary against the intended human date.

### 11. `intent_launch_treated_as_persistence` (~2%)

**Description:** Agent fired `am start -a android.intent.action.SENDTO/INSERT/SEND/VIEW` with pre-populated extras and immediately called finish, treating successful Activity launch as task completion — even though the target Activity is an interactive editor (Contacts editor, Simple SMS Messenger NewConversationActivity, Broccoli's CreateAndEditRecipeActivity) that requires a user Save/Send tap to persist anything to the database.

**Transcript signature:** Agent issues a single `am start -a android.intent.action.SENDTO -d smsto:+1... --es sms_body "..."` (or equivalent ACTION_SEND/INSERT for recipes/contacts) and finishes the next step without ever inspecting through `content query`/sqlite that a row actually persisted.


---

Generated at 2026-05-12 16:01:20.