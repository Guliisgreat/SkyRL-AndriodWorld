# GUI-Native Failure Modes

**Method:** Opus 4.7 max-effort synthesis of 80 GUI classifications (across 2 runs: [36, 44]).

## Overarching observations

Across both models, the dominant failure shape is not a misuse of a Linux/Android command surface but a breakdown in the GUI perception-action loop: the agent stops updating its world-model against the screen and either repeats a single ineffective gesture forever, replays a fixed macro of taps, or jumps straight to declaring success/answering without verifying the post-action UI state. qwen3vl32b is dramatically more susceptible to degenerate single-coordinate or single-action tap loops (often 40–50 identical actions), while GUIOwl1532BInstruct more often fabricates specific Q&A literals after a cursory app launch and skips final Save/OK commits at the end of otherwise-correct flows. Only three CLI-derived modes carry over with real signal — fabricated_values_after_failed_or_truncated_read (very common in Q&A tasks), intent_launch_treated_as_persistence (firing a UI action like SHOW-ON-MAP or record-start and stopping), and reconnaissance_burnout_no_mutation (budget consumed on UI navigation probes without ever mutating) — and even these are best read as GUI variants rather than direct matches.

## CLI modes that also appear on GUI

- `fabricated_values_after_failed_or_truncated_read`
- `intent_launch_treated_as_persistence`
- `reconnaissance_burnout_no_mutation`
- `wrote_to_wrong_app_data_store`
- `date_or_timezone_window_off`

## GUI-native modes

### 1. `stuck_single_action_loop` (~24%)

**Description:** The agent emits one identical action (tap at the same pixel coordinates, the same swipe vector, repeated open_app, or repeated wait) many consecutive times — typically 5 to 50 — without varying coordinates, action type, or strategy. It never registers that the UI did not respond and never pivots to an alternative gesture, target, or screen.

**Transcript signature:** ≥5 consecutive actions with byte-identical parameters and near-identical reason strings; no other action type interleaved (e.g., same click x=926 y=2207 for all 50 steps, or identical open_app emitted 50 times)

**Applies to agents:** GUIOwl1532BInstruct, qwen3vl32b

### 2. `fixed_macro_navigation_burnout` (~14%)

**Description:** A short 3-5 tap navigation sequence (overflow → wrong submenu → close, or forward-arrow ↔ back-arrow oscillation) is replayed as a unit across the remaining step budget because the agent cannot locate the actual affordance (rename, completed-tasks filter, jump-to-date) it needs. Unlike stuck_single_action_loop, the macro has internal variation but the macro itself never changes between iterations.

**Transcript signature:** same ordered tuple of 3-5 taps (with fixed coordinates per step) appearing 4+ times in the trajectory; step budget exhausted with zero mutating action emitted between repetitions

**Applies to agents:** GUIOwl1532BInstruct, qwen3vl32b

### 3. `premature_answer_no_observation` (~18%)

**Description:** For Q&A / information-extraction tasks, the agent emits an answer action within the first 1-3 steps after merely launching the app, containing a specific numeric or textual literal (e.g., '1160', '3420', 'Water Plants', 'Active Rest Day') that never appeared in any captured screen observation. The agent skipped scrolling, date-filtering, and opening detail views entirely.

**Transcript signature:** action_type=answer (or status=complete with answer text) issued at step ≤3 with a concrete number/title/name that does not appear in any prior screenshot or AXTree observation; no scroll/filter actions precede it

**Applies to agents:** GUIOwl1532BInstruct, qwen3vl32b

### 4. `dialog_commit_skipped` (~12%)

**Description:** Multi-step form / dialog is correctly filled via input_text and intermediate taps, but the agent emits status=complete before the final Save / OK / Create / Send / Stop-Recording button is tapped — treating data entry as persistence. Often paired with a confident success answer that is never verified against any subsequent screen read.

**Transcript signature:** input_text or radio/checkbox tap actions followed directly by status=complete with no visible tap on a labeled Save/OK/Create/Send/Stop button; no read-back observation of the saved record

**Applies to agents:** GUIOwl1532BInstruct, qwen3vl32b

### 5. `wrong_gesture_primitive_for_widget` (~8%)

**Description:** The agent uses click on a widget that semantically requires a continuous gesture: tapping a brightness/seek slider where a drag is needed, single-tapping a drawing canvas where a swipe stroke is needed, or long-pressing once and assuming Select-All semantics when the platform default is single-word selection. The widget gives no feedback and the agent never escalates to swipe / select_all.

**Transcript signature:** click action emitted only once or repeatedly on a slider/canvas widget where the expected gesture is swipe/drag; no swipe action_type ever appears on the same screen despite tap failures (e.g., brightness slider tapped 7× with no swipe attempt)

**Applies to agents:** GUIOwl1532BInstruct, qwen3vl32b

### 6. `adjacent_tap_target_misgrounding` (~12%)

**Description:** The agent's reasoning names target X but the tap coordinates resolve to a visually-near or label-similar UI element Y: the country header instead of the town row, a sibling file with a longer-prefixed name, the message input field treated as a recipient picker, or a status-bar pixel treated as a slider endpoint. The agent never re-verifies which row/element actually received the tap.

**Transcript signature:** tap reason cites element name X (e.g., 'Schönberg'), but coordinates land on element Y (e.g., 'Liechtenstein' country header) clearly visible in the screenshot; no follow-up read confirming target identity

**Applies to agents:** GUIOwl1532BInstruct, qwen3vl32b

### 7. `stale_index_after_dynamic_list_mutation` (~6%)

**Description:** In a re-flowing list (deletions, reorderings, search-result updates), the agent re-uses fixed y-coordinates or 'the second instance' reasoning across consecutive mutating actions, so each successive long-press/delete actually targets a different item than intended. Frequently leads to over-deletion of unique entries while preserving duplicates.

**Transcript signature:** ≥3 consecutive long_press → menu → delete sequences at fixed or drifting y-coordinates with reasons saying 'the second/duplicate instance', emitted without any intervening screen re-read or list-state observation

**Applies to agents:** GUIOwl1532BInstruct, qwen3vl32b
