# Design Doc: ADB-Based Verifiers for Android-Lab Terminal Agent Evaluation

**Date:** 2026-03-22
**Status:** Draft
**Prerequisite:** Android-Lab GUI baseline reproduced (26.8% SR with GPT-4o XML-only)

---

## 1. Problem Statement

Android-Lab's evaluation system checks task success by inspecting **XML UI state at each step** during GUI agent execution. Terminal agents interact via ADB/SQL commands and never produce UI state — making the existing evaluation inapplicable.

```
GUI agent:     10 UI steps → 10 XML dumps → judge checks each → complete=True at step 7
Terminal agent: 4 ADB cmds → 0 XML dumps → judge has nothing to evaluate
```

Even opening the app post-execution doesn't work because:
- `judge_page()` expects a **specific page** (e.g., the expense edit form), not the app home screen
- Some judges check **intermediate states** (e.g., verify original value before checking edited value)
- The terminal agent may never navigate the UI at all

## 2. Proposed Solution: ADB-Based Verifiers

Write a parallel set of verifiers that check **the same ground truth criteria** as Android-Lab's XML judges, but using ADB queries (SQLite, content providers, `settings get`, `dumpsys`, file inspection) instead of XML tree parsing.

### 2.1 Architecture

```
Android-Lab XML Judge (original)          ADB Verifier (new)
─────────────────────────────             ──────────────────────
class SingleTask_bluecoins_6:             class ADBVerifier_bluecoins_6:
  def judge(self, xml, line):               def verify(self, adb_executor):
    bill = extract_from_XML(xml)              result = adb("sqlite3 ... SELECT ...")
    return bill["cash"] == "512"              return "512" in result
```

### 2.2 Base Class

Inherit from a new `ADBVerifier` base class inspired by AndroidWorld's `TaskEval`:

```python
class ADBVerifier:
    """Base class for ADB-based task verification."""

    def __init__(self, task_id: str, adb_executor: Callable):
        self.task_id = task_id
        self.adb = adb_executor  # function(cmd) -> stdout

    def verify(self) -> dict:
        """Check if the task was completed successfully.

        Returns:
            {"complete": bool, "1": bool, "2": bool, ..., "details": str}
        """
        raise NotImplementedError

    def _adb_shell(self, cmd: str) -> str:
        """Shorthand for adb shell commands."""
        return self.adb(f"adb shell {cmd}")

    def _content_query(self, uri: str, where: str = "") -> str:
        """Query a content provider."""
        cmd = f"content query --uri {uri}"
        if where:
            cmd += f" --where \"{where}\""
        return self._adb_shell(cmd)

    def _sqlite_query(self, db_path: str, sql: str) -> str:
        """Query an SQLite database directly."""
        return self._adb_shell(f"sqlite3 {db_path} '{sql}'")

    def _settings_get(self, namespace: str, key: str) -> str:
        """Read an Android setting."""
        return self._adb_shell(f"settings get {namespace} {key}").strip()

    def _package_installed(self, package: str) -> bool:
        """Check if a package is installed."""
        return package in self._adb_shell(f"pm list packages {package}")
```

### 2.3 Dual-Track Evaluation Flow

```python
def evaluate_task(task_def, adb_executor, agent_answer=None):
    """Evaluate a single Android-Lab task."""
    task_id = task_def["task_id"]
    metric_type = task_def["metric_type"]

    if metric_type == "query_detect":
        # Track 1: LLM judge (identical to original)
        ground_truth = GROUND_TRUTH_ANSWERS[task_id]
        return llm_judge(task_def["task"], agent_answer, ground_truth)

    elif metric_type == "operation":
        # Track 2: ADB verifier (new)
        verifier = VERIFIER_MAP[task_id](task_id, adb_executor)
        return verifier.verify()
```

---

## 3. Per-App Verifier Design

### 3.1 Settings (14 operation tasks)

**Verification method:** `settings get`, `getprop`, `dumpsys`, `pm list`

| task_id | Task | Sub-goals | ADB Verification |
|---------|------|-----------|-----------------|
| setting_1 | Turn off auto wifi | wifi_auto=off | `settings get global wifi_scan_always_enabled` == 0 |
| setting_2 | Set private DNS to dns.google | dns=dns.google | `settings get global private_dns_specifier` == dns.google |
| setting_3 | Turn off bluetooth | bt=off | `settings get global bluetooth_on` == 0 |
| setting_4 | BT name = "my AVD" | name=my AVD | `settings get secure bluetooth_name` == "my AVD" |
| setting_5 | Show battery % | battery_pct=on | `settings get system battery_percentage_enabled` or `dumpsys battery` |
| setting_7 | Dark theme | dark=on | `settings get secure ui_night_mode` == 2 |
| setting_8 | Brightness to 0% | brightness=0 | `settings get system screen_brightness` == 0 |
| setting_13 | Turn off ring vibration | vibrate=off | `settings get system vibrate_when_ringing` == 0 |
| setting_15 | Add Spanish language | lang=es_US | `settings get system system_locales` contains es-US |
| setting_18 | Disable Contacts notifications | notif=off | `dumpsys notification | grep contacts` or `cmd appops get com.google.android.contacts POST_NOTIFICATION` |
| setting_19 | Default browser = Firefox | browser=firefox | `cmd package resolve-activity --brief -a android.intent.action.VIEW -d http://` contains firefox |
| setting_20 | Uninstall booking app | uninstalled | `pm list packages com.booking` returns empty |
| setting_21 | Open settings | app_open | `dumpsys activity activities | grep mResumedActivity` contains settings |
| setting_22 | Check airplane mode status | query | `settings get global airplane_mode_on` — return value to agent |

**Difficulty:** EASY — all verifiable via `settings get` / system commands.

### 3.2 Clock (22 operation tasks)

**Verification method:** `content query --uri content://com.google.android.deskclock`

| task_id | Task | ADB Verification |
|---------|------|-----------------|
| clock_1 | Alarm 3PM label "meeting" | `content query --uri content://com.android.deskclock/alarms` → check hour=15, label=meeting |
| clock_2 | Alarm 6:45AM, no vibrate, Argon | content query → hour=6, minutes=45, vibrate=0, alert contains Argon |
| clock_3 | Alarm 7AM Mon-Fri | content query → hour=7, daysofweek=31 (Mon-Fri bitmask) |
| clock_4 | 9AM alarm ring everyday | content query → hour=9, daysofweek=127 |
| clock_5 | Alarm 10:30AM tomorrow | content query → hour=10, minutes=30 |
| clock_6 | 10:30PM weekends, label "Watch Football" | content query → hour=22, minutes=30, daysofweek=96, label |
| clock_7 | Turn off all alarms | content query → all enabled=0 |
| clock_8 | Delete alarms after 2PM | content query → no alarms with hour>14 |
| clock_9 | Turn off 4PM alarm | content query → hour=16, enabled=0 |
| clock_15 | Add London + Barcelona clocks | `dumpsys` or content query for world clocks |
| clock_17 | Delete Barcelona clock | content query → no Barcelona in world clocks |
| clock_18 | Timer 1h15m not started | Check timer state (may need UI inspection) |
| clock_19-21 | Bedtime settings | May need `settings get` or shared_preferences |
| clock_22 | Alarm style Analog | shared_preferences or settings |
| clock_23 | Home timezone Tokyo | `settings get global time_zone` or clock prefs |
| clock_24 | Silence after 5 min | shared_preferences |
| clock_25 | Open clock app | `dumpsys activity` check foreground |
| clock_26 | Close 7:30AM alarm | content query → hour=7, minutes=30, enabled=0 |
| clock_27 | Set alarm 3PM | content query → hour=15 exists |

**Difficulty:** EASY-MEDIUM — most via content provider, some need shared_preferences.

### 3.3 Contacts (11 operation tasks)

**Verification method:** `content query --uri content://com.android.contacts`

| task_id | Task | ADB Verification |
|---------|------|-----------------|
| contacts_1 | Add John, phone 12345678 | content query contacts → name=John, phone=12345678 |
| contacts_2 | Add John Smith, phone+email | content query → name, phone, email fields |
| contacts_3 | Add Xu, work+mobile phones | content query → two phone numbers |
| contacts_4 | Add Chen, company Tsinghua | content query → organization=Tsinghua |
| contacts_5 | Create label "work", add AAA+ABC | content query groups + membership |
| contacts_6 | Add work phone to ABC | content query → ABC has work phone 00112233 |
| contacts_7 | Add birthday to AAA | content query → birthday=1996/10/24 |
| contacts_8 | Set ABC website | content query → website=abc.github.com |
| contacts_9 | Draft message to ABC | `content query --uri content://sms` or dumpsys |
| contacts_10 | Call ABC | `dumpsys telecom` check call log |
| contacts_11 | Delete AAA | content query → AAA not found |

**Difficulty:** EASY — contacts content provider is well-documented.

### 3.4 Calendar (14 operation tasks)

**Verification method:** `content query --uri content://com.android.calendar/events`

Note: Android-Lab uses `com.skuld.calendario` (not Google Calendar). Need to check if it uses Android's standard calendar content provider or its own database.

| task_id | Task | ADB Verification |
|---------|------|-----------------|
| calendar_1 | Add event "work" at 5PM today | content query → title=work, dtstart matches 5PM |
| calendar_2 | Event "homework" May 21, notify 10min | content query events + reminders |
| calendar_3 | Event "meeting" May 13, note "B202" | content query → description=conference room B202 |
| calendar_4 | Event starting 2024/6/1, monthly repeat | content query → rrule contains MONTHLY |
| calendar_5-14 | Various edits | content query for modified values |

**Difficulty:** MEDIUM — depends on whether Calendario uses standard content provider or custom DB. May need `sqlite3` on app's database.

### 3.5 Bluecoins (10 operation tasks)

**Verification method:** `sqlite3` on Bluecoins database

| task_id | Task | ADB Verification |
|---------|------|-----------------|
| bluecoins_6 | Expense 512 CNY | `sqlite3 /data/data/com.rammigsoftware.bluecoins/databases/*.db 'SELECT * FROM TRANSACTIONSTABLE ORDER BY rowid DESC LIMIT 1'` → type=expense, amount=512 |
| bluecoins_7 | Income 8000 CNY, salary | Similar query → type=income, amount=8000, note=salary |
| bluecoins_8-10 | Create entries | Similar with date/amount/note checks |
| bluecoins_11-15 | Edit entries | Query specific records and check updated values |

**Difficulty:** MEDIUM — need to discover exact database schema (table names, column names). Can be done by inspecting `.schema` on the running container.

### 3.6 Maps.me (5 operation tasks)

**Verification method:** Likely requires UI inspection

| task_id | Task | ADB Verification |
|---------|------|-----------------|
| map_11 | Add OpenAI address to Work | shared_preferences or bookmarks DB |
| map_12-15 | Navigate to locations | Check if navigation is active via dumpsys or UI state |

**Difficulty:** HARD — Maps.me stores data in custom binary formats, navigation state requires UI.

### 3.7 Pi Music Player (6 operation tasks)

**Verification method:** UI-dependent or media database

| task_id | Task | ADB Verification |
|---------|------|-----------------|
| pimusic_7 | Play first song in Favorite | `dumpsys media_session` → check playing state |
| pimusic_8 | Sort by duration descending | App internal state — HARD |
| pimusic_9 | Create playlist "Creepy" | `sqlite3` on Pi Music DB or `content query --uri content://media/external/audio/playlists` |
| pimusic_10 | Pause + seek to 1:27 | `dumpsys media_session` → check paused + position |
| pimusic_11 | Play Lightship by Sonny Boy | `dumpsys media_session` → check now playing |
| pimusic_12 | Sort by duration ascending | App internal state — HARD |

**Difficulty:** MEDIUM-HARD — playback via media_session, sorting is UI-only.

### 3.8 Cantook (7 operation tasks)

**Verification method:** File system + app database

| task_id | Task | ADB Verification |
|---------|------|-----------------|
| cantook_6 | Import Alice in Wonderland | Check file exists in app's import dir |
| cantook_7 | Delete Don Quixote | `sqlite3` on Cantook/Aldiko DB → book not found |
| cantook_8 | Mark Hamlet as read | DB → read_status=1 |
| cantook_9 | Mark 2nd recent as unread | DB → read_status=0 |
| cantook_10 | Open Romeo and Juliet | `dumpsys activity` → reading activity open |
| cantook_11 | Open category "Tragedies" | App navigation state — HARD |
| cantook_12 | Create collection "Favorite" | DB → collection exists |

**Difficulty:** MEDIUM-HARD — need to discover Aldiko's database schema.

### 3.9 Zoom (5 operation tasks)

**Verification method:** Requires UI inspection

| task_id | Task | ADB Verification |
|---------|------|-----------------|
| zoom_1-3 | Join meeting (various configs) | UI state — meeting ID field populated |
| zoom_4 | Auto-connect audio on WiFi | shared_preferences |
| zoom_5 | Reaction skin tone | shared_preferences |

**Difficulty:** HARD — Zoom stores most config in encrypted prefs or requires UI.

---

## 4. Difficulty Summary

| App | Operation Tasks | EASY | MEDIUM | HARD |
|-----|---------------:|-----:|-------:|-----:|
| Settings | 14 | 14 | 0 | 0 |
| Clock | 22 | 12 | 7 | 3 |
| Contacts | 11 | 11 | 0 | 0 |
| Calendar | 14 | 0 | 14 | 0 |
| Bluecoins | 10 | 0 | 10 | 0 |
| Maps.me | 5 | 0 | 0 | 5 |
| PiMusic | 6 | 0 | 2 | 4 |
| Cantook | 7 | 0 | 4 | 3 |
| Zoom | 5 | 0 | 2 | 3 |
| **Total** | **93** | **37** | **39** | **18** |

- **EASY (37):** Direct `settings get`, `content query`, `pm list` — no schema discovery needed
- **MEDIUM (39):** Need app database schema discovery + `sqlite3` queries — one-time effort per app
- **HARD (18):** Require UI state or proprietary storage — may need fallback to post-agent XML dump

## 5. Implementation Plan

### Phase 1: EASY verifiers (37 tasks, ~2 days)

Implement verifiers for **Settings** (14) + **Contacts** (11) + **Clock** (12 easy ones).

Steps:
1. Create `skyrl-agent/examples/run_androidlab/verifiers/` directory
2. Implement `base.py` with `ADBVerifier` base class
3. Implement `settings_verifier.py` (14 tasks)
4. Implement `contacts_verifier.py` (11 tasks)
5. Implement `clock_verifier.py` (12 easy tasks)
6. Create `verifier_map.py` mapping task_id → verifier class

### Phase 2: MEDIUM verifiers (39 tasks, ~3 days)

Schema discovery + implementation for **Bluecoins**, **Calendar**, **Clock** (remaining), **Cantook**, **Zoom** (prefs).

Steps:
1. Boot container, run `sqlite3 .schema` on each app's database
2. Document schemas in `docs/ref_agent/androidlab_db_schemas.md`
3. Implement `bluecoins_verifier.py` (10 tasks)
4. Implement `calendar_verifier.py` (14 tasks)
5. Implement `clock_verifier.py` (remaining 10 tasks)
6. Implement `cantook_verifier.py` (4 medium tasks)
7. Implement `zoom_verifier.py` (2 medium tasks)

### Phase 3: HARD verifiers (18 tasks, ~2 days)

Fallback strategy: **post-agent XML dump** for tasks that can't be verified via ADB.

Steps:
1. For each HARD task: open app → navigate → dump XML → run original judge
2. Write per-app navigation scripts (tap sequences to reach correct page)
3. Implement `ui_fallback_verifier.py` that wraps original Android-Lab judges
4. Tasks: Maps.me (5), PiMusic (4), Cantook (3), Zoom (3), Clock (3)

---

## 6. Correctness Verification

### 6.1 Cross-Validation Protocol

To prove our ADB verifiers produce the **same results** as Android-Lab's XML judges:

1. **Run GUI agent (GPT-4o) on all 138 tasks** — already done (26.8% SR)
2. **Re-evaluate the same traces with ADB verifiers:**
   - For each task where the GUI agent succeeded (37 tasks):
     - Boot a fresh container
     - **Replay** the GUI agent's actions (from saved traces)
     - After replay, run ADB verifier
     - Check: ADB verifier should also return `complete=True`
   - For each task where the GUI agent failed:
     - ADB verifier should also return `complete=False`
3. **Agreement rate must be >95%** before using ADB verifiers for terminal agent evaluation

### 6.2 Per-Task Spot Checks

For each verifier module, manually test on the running container:

```bash
# 1. Manually perform the operation via ADB
adb shell settings put global bluetooth_on 0

# 2. Run ADB verifier
python -c "from verifiers import setting_verifier; v = setting_verifier.ADBVerifier_setting_3(...); print(v.verify())"
# Expected: {"complete": True, "1": True}

# 3. Reset container, verify clean state
# Expected: {"complete": False, "1": False}
```

### 6.3 Edge Cases to Test

| Scenario | Expected Behavior |
|----------|-------------------|
| Agent sets value correctly but app not open | ADB verifier: True, XML judge: may be False (judge_page) |
| Agent sets wrong value | Both: False |
| Agent doesn't act at all | Both: False |
| Agent partially completes (2/3 sub-goals) | Both: partial success, complete=False |
| Value format differs (512 vs 512.00) | ADB verifier must handle both formats (match XML judge) |

### 6.4 Discrepancy Resolution

If ADB verifier and XML judge disagree:
- **ADB=True, XML=False:** Terminal agent correctly modified state but UI didn't reflect it. ADB verifier is **more accurate** — this is an evaluator limitation in Android-Lab, not an agent failure. Document as "evaluation gap."
- **ADB=False, XML=True:** Bug in ADB verifier — fix it.
- Track discrepancy rate per app. If >10% for an app, review verifier logic.

---

## 7. Integration with Terminal Agent Runners

### 7.1 Modified Task Runner

```python
def run_terminal_task(task_def, container_url, agent_runner, adb_executor):
    """Run terminal agent + evaluate with ADB verifier."""
    # 1. Reset container
    androidlab_reset(container_url, package=task_def["package"])

    # 2. Run terminal agent (Claude CLI / Terminus-2 / mini-swe)
    agent_result = agent_runner(task_def, container_url)

    # 3. Evaluate
    if task_def["metric_type"] == "query_detect":
        reward = llm_judge(task_def, agent_result["finish_description"])
    else:
        verifier = VERIFIER_MAP[task_def["task_id"]](task_def["task_id"], adb_executor)
        result = verifier.verify()
        reward = 1.0 if result["complete"] else 0.0

    agent_result["reward"] = reward
    return agent_result
```

### 7.2 Metrics Computation

With ADB verifiers, we can compute all 4 metrics:
- **SR:** `sum(complete) / total`
- **Sub-SR:** `sum(partial_subgoals) / total` — ADB verifiers return per-sub-goal results
- **RRR:** `ground_truth_steps / agent_steps` — use `ground_truth_length.json` from Android-Lab
- **ROR:** Defined as `1 - redundant_steps / total_steps` — for terminal agents, every ADB command that changes state is "reasonable," so ROR ≈ 1.0 by construction

---

## 8. File Structure

```
skyrl-agent/examples/run_androidlab/
├── verifiers/
│   ├── __init__.py
│   ├── base.py                    # ADBVerifier base class
│   ├── settings_verifier.py       # 14 tasks
│   ├── clock_verifier.py          # 22 tasks
│   ├── contacts_verifier.py       # 11 tasks
│   ├── calendar_verifier.py       # 14 tasks
│   ├── bluecoins_verifier.py      # 10 tasks
│   ├── mapme_verifier.py          # 5 tasks
│   ├── pimusic_verifier.py        # 6 tasks
│   ├── cantook_verifier.py        # 7 tasks
│   ├── zoom_verifier.py           # 5 tasks
│   ├── query_detect_judge.py      # LLM judge for 45 query tasks
│   ├── verifier_map.py            # task_id → verifier class registry
│   └── ui_fallback_verifier.py    # Fallback: open app + XML dump for HARD tasks
├── evaluate_terminal_results.py   # Post-hoc evaluation script
└── cross_validate_verifiers.py    # Correctness check vs XML judges
```

---

## 9. Open Questions

1. **Calendario content provider:** Does `com.skuld.calendario` use Android's standard `content://com.android.calendar/events` or its own database? Need to check on running container.
2. **Bluecoins DB schema:** Need to discover table names and column names.
3. **Clock world clocks:** Where does Google Clock store world clock cities?
4. **Maps.me bookmarks:** Can we access bookmarks via file system (`/data/data/com.mapswithme.maps.pro/files/`)?
5. **Aldiko/Cantook DB:** What's the database path and schema?
6. **Zoom shared_preferences:** Can we read Zoom's preferences file for settings like auto-connect and skin tone?
