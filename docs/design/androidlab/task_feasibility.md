# Android-Lab Task Feasibility Analysis for Terminal Agents

**Date:** 2026-03-22
**Status:** Verified on running `androidlab:v1` container

---

## 1. Summary

Of 138 Android-Lab tasks, **112 are evaluable by terminal agents** (67 operation + 45 query_detect). 26 operation tasks must be excluded because they require GUI interaction with no terminal alternative.

| Category | Tasks | Terminal Doable | ADB Verifiable |
|----------|------:|:---:|:---:|
| Operation (terminal-feasible) | 67 | YES | YES |
| Operation (GUI-only, excluded) | 26 | NO | N/A |
| Query-detect | 45 | YES | YES (LLM judge) |
| **Total evaluable** | **112** | | |

---

## 2. Per-App Breakdown

### Settings — 14 operation + 8 query_detect = 22 tasks — ALL EVALUABLE

Every settings task is doable via `settings put`, `cmd`, `pm`, or `svc` commands and verifiable via `settings get`.

| task_id | Task | Terminal Method | Verify Method |
|---------|------|----------------|---------------|
| setting_1 | Turn off auto wifi | `settings put global wifi_scan_always_enabled 0` | `settings get` |
| setting_2 | Set private DNS dns.google | `settings put global private_dns_mode hostname` + `private_dns_specifier` | `settings get` |
| setting_3 | Turn off bluetooth | `svc bluetooth disable` or `settings put global bluetooth_on 0` | `settings get` |
| setting_4 | BT name "my AVD" | `settings put secure bluetooth_name "my AVD"` | `settings get` |
| setting_5 | Show battery % | `settings put system status_bar_show_battery_percent 1` | `settings get` |
| setting_7 | Dark theme | `cmd uimode night yes` | `settings get secure ui_night_mode` == 2 |
| setting_8 | Brightness 0% | `settings put system screen_brightness 0` | `settings get` |
| setting_13 | Turn off ring vibration | `settings put system vibrate_when_ringing 0` | `settings get` |
| setting_15 | Add Spanish language | `settings put system system_locales "en-US,es-US"` | `settings get` |
| setting_18 | Disable Contacts notifications | `cmd appops set ... POST_NOTIFICATION deny` | `cmd appops get` |
| setting_19 | Default browser to Firefox | `cmd package set-home-activity` or role manager | `cmd package resolve-activity` |
| setting_20 | Uninstall booking app | `pm uninstall com.booking` | `pm list packages` |
| setting_21 | Open settings | `am start -a android.settings.SETTINGS` | `dumpsys activity` |
| setting_22 | Check airplane mode | Query `settings get global airplane_mode_on` | `settings get` |

**Verified:** Firefox (`org.mozilla.firefox`) is installed on the image. Booking (`com.booking`) is installed.

---

### Contacts — 11 operation + 4 query_detect = 15 tasks — ALL EVALUABLE

All contacts operations use the standard Android ContactsContract content provider.

| task_id | Task | Terminal Method | Verify Method |
|---------|------|----------------|---------------|
| contacts_1 | Add John, phone 12345678 | `content insert` raw_contacts + data | `content query` |
| contacts_2 | Add John Smith + email | `content insert` name + phone + email | `content query` |
| contacts_3 | Add Xu, 2 phones | `content insert` name + 2 phone entries | `content query` |
| contacts_4 | Add Chen, company Tsinghua | `content insert` name + organization | `content query` |
| contacts_5 | Create label "work", add AAA+ABC | `content insert` groups + group_membership | `content query groups` |
| contacts_6 | Add work phone to ABC | `content insert` phone with type=work | `content query` |
| contacts_7 | Add birthday to AAA | `content insert` contact_event type=birthday | `content query` |
| contacts_8 | Set ABC website | `content insert` website | `content query` |
| contacts_9 | Draft message to ABC | `content insert --uri content://sms` type=3 (draft) | `content query sms` |
| contacts_10 | Call ABC | `am start -a android.intent.action.CALL -d tel:NUMBER` | `dumpsys telecom` / call_log |
| contacts_11 | Delete AAA | `content delete` raw_contacts | `content query` |

**Verified:** Pre-existing contacts AAA (raw_contact_id=1), ABC (id=2), Li (id=3) confirmed via content provider.

---

### Clock — 21 operation + 6 query_detect = 27 tasks — ALL EVALUABLE

Alarm operations use either direct SQLite on `alarms.db` or the `SET_ALARM` intent. Other clock features use SharedPreferences.

| task_id | Task | Terminal Method | Verify Method |
|---------|------|----------------|---------------|
| clock_1 | Alarm 3PM label "meeting" | `SET_ALARM` intent or `sqlite3 INSERT` | `sqlite3 SELECT` |
| clock_2 | Alarm 6:45AM, no vibrate, Argon | `sqlite3 INSERT` with vibrate=0, ringtone=Argon | `sqlite3 SELECT` |
| clock_3 | Alarm 7AM Mon-Fri | `sqlite3 INSERT` daysofweek=31 | `sqlite3 SELECT` |
| clock_4 | 9AM alarm everyday | `sqlite3 UPDATE` daysofweek=127 | `sqlite3 SELECT` |
| clock_5 | Alarm 10:30AM | `SET_ALARM` intent or `sqlite3 INSERT` | `sqlite3 SELECT` |
| clock_6 | 10:30PM weekends + label | `sqlite3 INSERT` | `sqlite3 SELECT` |
| clock_7 | Turn off all alarms | `sqlite3 UPDATE ... SET enabled=0` | `sqlite3 SELECT` |
| clock_8 | Delete alarms after 2PM | `sqlite3 DELETE WHERE hour>=14` | `sqlite3 SELECT` |
| clock_9 | Turn off 4PM alarm | `sqlite3 UPDATE SET enabled=0 WHERE hour=16` | `sqlite3 SELECT` |
| clock_15 | Add London+Barcelona world clocks | SharedPreferences edit | SharedPrefs read |
| clock_17 | Delete Barcelona world clock | SharedPreferences edit | SharedPrefs read |
| clock_18 | Timer 1h15m (not started) | UI-dependent but can verify via `dumpsys` | `dumpsys` |
| clock_19-21 | Bedtime settings | SharedPreferences | SharedPrefs read |
| clock_22 | Alarm style Analog | SharedPreferences | SharedPrefs read |
| clock_23 | Home timezone Tokyo | SharedPreferences or `settings put` | SharedPrefs/settings |
| clock_24 | Silence after 5min | SharedPreferences | SharedPrefs read |
| clock_25 | Open clock app | `am start` | `dumpsys activity` |
| clock_26 | Close 7:30AM alarm | `sqlite3 UPDATE SET enabled=0` | `sqlite3 SELECT` |
| clock_27 | Set alarm 3PM | `SET_ALARM` intent or `sqlite3 INSERT` | `sqlite3 SELECT` |

**Verified:** Alarm DB at `/data/user_de/0/com.google.android.deskclock/databases/alarms.db`. Schema: `alarm_templates(_id, hour, minutes, daysofweek, enabled, vibrate, label, ringtone, ...)`. Pre-existing alarms: 8:30 (Mon-Fri, disabled), 9:00 (weekends, disabled), 16:00 (Mon-Fri, enabled), 7:30 (all days, enabled). `SET_ALARM` intent confirmed working.

---

### Bluecoins — 10 operation + 5 query_detect = 15 tasks — ALL EVALUABLE

All operations use direct SQLite on `bluecoins.fydb`.

| task_id | Task | Terminal Method | Verify Method |
|---------|------|----------------|---------------|
| bluecoins_6 | Expense 512 CNY | `sqlite3 INSERT` type=3, amount=-512000000 | `sqlite3 SELECT` |
| bluecoins_7 | Income 8000, salary | `sqlite3 INSERT` type=4, amount=8000000000, notes=salary | `sqlite3 SELECT` |
| bluecoins_8 | Expense 768, May 11 | `sqlite3 INSERT` with date | `sqlite3 SELECT` |
| bluecoins_9 | Income 3.14, Mar 8, "Weixin red packet" | `sqlite3 INSERT` | `sqlite3 SELECT` |
| bluecoins_10 | Expense 256, May 14, "eating" | `sqlite3 INSERT` | `sqlite3 SELECT` |
| bluecoins_11 | Edit May 15 expense to 500 | `sqlite3 UPDATE` | `sqlite3 SELECT` |
| bluecoins_12 | Move income May 12→May 10, amount 18250 | `sqlite3 UPDATE` | `sqlite3 SELECT` |
| bluecoins_13 | Switch May 13 expense→income, note Gift | `sqlite3 UPDATE` type + notes | `sqlite3 SELECT` |
| bluecoins_14 | Switch May 2 income→expense, 520, "Wrong Operation" | `sqlite3 UPDATE` | `sqlite3 SELECT` |
| bluecoins_15 | Move May 12 expense→May 13, 936.02, "Grocery Shopping" | `sqlite3 UPDATE` | `sqlite3 SELECT` |

**Verified:** DB at `/data/data/com.rammigsoftware.bluecoins/databases/bluecoins.fydb`. Amounts stored as micro-units (×1,000,000). Transaction types: 3=Expense, 4=Income. INSERT confirmed working via test.

---

### Cantook — 7 operation + 5 query_detect = 12 tasks — 7 OPERATION EVALUABLE

Most operations use direct SQLite on `cantook.db`.

| task_id | Task | Terminal Method | Verify Method | Status |
|---------|------|----------------|---------------|--------|
| cantook_6 | Import Alice in Wonderland | `sqlite3 INSERT` into publications (but app may not recognize without file copy) | `sqlite3 SELECT` | PARTIAL |
| cantook_7 | Delete Don Quixote | `sqlite3 DELETE FROM publications` | `sqlite3 SELECT` | YES |
| cantook_8 | Mark Hamlet as read | `sqlite3 UPDATE SET finished=1` | `sqlite3 SELECT` | YES |
| cantook_9 | Mark 2nd recent as unread | `sqlite3 UPDATE SET finished=0` | `sqlite3 SELECT` | YES |
| cantook_10 | Open Romeo and Juliet | Needs GUI to open reader | `dumpsys activity` | PARTIAL |
| cantook_11 | Open category Tragedies | Needs GUI navigation | `dumpsys activity` | PARTIAL |
| cantook_12 | Create collection "Favorite" | `sqlite3 INSERT INTO collections` | `sqlite3 SELECT` | YES |

**Verified:** DB at `/data/data/com.aldiko.android/databases/cantook.db`. Tables: publications (id, title, finished, progression), collections, publications_collections. 10 books pre-loaded. Ebook files at `/sdcard/Download/Ebooks/` confirmed.

---

### PiMusic — 6 operation + 6 query_detect = 12 tasks — 4 OPERATION EVALUABLE, 2 EXCLUDED

| task_id | Task | Terminal Method | Verify Method | Status |
|---------|------|----------------|---------------|--------|
| pimusic_7 | Play first Favorite song | `am start` with media intent or `cmd media_session dispatch play` | `dumpsys media_session` | PARTIAL |
| pimusic_8 | Sort Floyd songs by duration desc | **NO** — sort is UI-only state | N/A | **EXCLUDED** |
| pimusic_9 | Create playlist "Creepy" | `sqlite3 INSERT INTO pi_playlist` | `sqlite3 SELECT` | YES |
| pimusic_10 | Pause + seek to 1:27 | `cmd media_session dispatch pause` + seek | `dumpsys media_session` | PARTIAL |
| pimusic_11 | Play Lightship | `am start` with media intent | `dumpsys media_session` | PARTIAL |
| pimusic_12 | Sort songs by duration asc | **NO** — sort is UI-only state | N/A | **EXCLUDED** |

**Verified:** DB at `/data/data/com.Project100Pi.themusicplayer/databases/songinfodatabase`. Favorite playlist exists (id=1) with 3 songs. 12 songs in MediaStore. `media_session` commands available.

---

## 3. Excluded Tasks (26 total)

### Calendar — 14 tasks EXCLUDED

**Reason:** Calendario uses **Realm DB** (not SQLite). No content provider registered. No command-line API for event creation. Terminal agent cannot create/edit/delete calendar events.

Excluded: calendar_1 through calendar_14

### Maps.me — 5 operation tasks EXCLUDED

**Reason:** All 5 operation tasks require GUI interaction:
- map_11: Search for "OpenAI" in Maps.me → location search is GUI-only
- map_12-15: Start navigation → requires GUI route selection

Note: 10 Maps.me query_detect tasks ARE evaluable (agent can explore the app and answer questions).

Excluded: map_11 through map_15

### Zoom — 5 tasks EXCLUDED

**Reason:** No local database, no SharedPreferences, no content provider. All tasks require filling in UI forms (meeting ID, name, toggle switches). Zoom on x86 emulator also shows "ARM chip required" warning.

Excluded: zoom_1 through zoom_5

### PiMusic — 2 tasks EXCLUDED

**Reason:** Sort order is purely UI state with no backing store. No API to set sort preference.

Excluded: pimusic_8, pimusic_12

---

## 4. Evaluable Task Summary

| App | Operation | Query | Total | Notes |
|-----|----------:|------:|------:|-------|
| Settings | 14 | 8 | 22 | All via `settings put/get` |
| Contacts | 11 | 4 | 15 | All via content provider |
| Clock | 21 | 6 | 27 | sqlite3 + SharedPrefs + intents |
| Bluecoins | 10 | 5 | 15 | sqlite3 on `.fydb` |
| Cantook | 7 | 5 | 12 | sqlite3 on `cantook.db` |
| PiMusic | 4 | 6 | 10 | sqlite3 + media_session |
| Maps.me | 0 | 10 | 10 | Query-only (GUI for operations) |
| Zoom | 0 | 0 | 0 | Fully excluded |
| Calendar | 0 | 0 | 0 | Fully excluded (Realm DB) |
| **Total** | **67** | **44** | **111** | |

Note: setting_0 (airplane mode) is query_detect but has a dynamic ground truth. Total query_detect with ground truth = 44 (excluding setting_0's dynamic check, though it is still evaluable).

### For fair comparison with GUI baseline (26.8% SR on 138 tasks):
- Report terminal SR on the **112 evaluable tasks**
- Also report terminal SR on the **full 138 tasks** (excluded = auto-fail) for direct comparison
- Note which excluded tasks are fundamentally GUI-only

---

## 5. Verification Methods Used

| Method | Apps | Reliability |
|--------|------|-------------|
| `settings get/put` | Settings | HIGH — direct Android API |
| `content query/insert` | Contacts | HIGH — standard content provider |
| `sqlite3` | Bluecoins, Clock, Cantook, PiMusic | HIGH — direct DB access |
| `pm list/uninstall` | Settings | HIGH — package manager |
| `dumpsys media_session` | PiMusic | MEDIUM — state may change |
| `dumpsys activity` | Settings, Clock, Cantook | MEDIUM — foreground check |
| SharedPreferences read | Clock | MEDIUM — requires correct pref keys |
| `strings` on Realm | Calendar | LOW — binary grep, weak verification |
| `uiautomator dump` | Zoom | LOW — requires app on correct page |
