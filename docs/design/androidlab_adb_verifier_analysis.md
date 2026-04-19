# Android-Lab Operation Tasks: ADB Verifier Analysis

Analysis of operation tasks across 9 Android-Lab apps, classifying each by whether success can be verified via ADB commands (without XML/UI inspection).

**Difficulty key:**
- **EASY** -- directly verifiable via `settings get`, `content query`, `pm list`, `dumpsys`, `sqlite3`, or similar ADB command
- **MEDIUM** -- verifiable but requires app-specific knowledge (database schema, content URI, shared-prefs path)
- **HARD** -- requires live UI state inspection; no ADB shortcut exists

---

## 1. Bluecoins (tasks 6--15)

Bluecoins stores financial data in a SQLite database (`/data/data/com.rammigsoftware.bluecoins/databases/`). All operation tasks create or edit transactions. The original judge inspects the edit-form XML on screen.

| task_id | Task Description | Judge Sub-goals | ADB Verification Strategy | Difficulty |
|---------|-----------------|-----------------|--------------------------|------------|
| bluecoins_6 | Add an expense of 512 CNY | type=Expense, cash=512 | `sqlite3` query on transactions table for amount=512, type=expense | MEDIUM |
| bluecoins_7 | Add income of 8000 CNY with note "salary" | type=Income, cash=8000, note="salary" | `sqlite3` query for amount=8000, note=salary, type=income | MEDIUM |
| bluecoins_8 | Add expense of 768 CNY on May 11, 2024 | type=Expense, date=May 11 2024, cash=768 | `sqlite3` query for amount=768, date, type | MEDIUM |
| bluecoins_9 | Add income of 3.14 CNY on Mar 8, 2024, note "weixin red packet" | type=Income, date=Mar 8 2024, cash=3.14, note="weixin red packet" | `sqlite3` query for amount=3.14, date, note, type | MEDIUM |
| bluecoins_10 | Add expense of 256 CNY on May 14, 2024, note "eating" | type=Expense, date=May 14 2024, cash=256, note="eating" | `sqlite3` query for amount=256, date, note, type | MEDIUM |
| bluecoins_11 | Edit existing transaction (May 15, 400) to cash=500 | original found (date=May 15, cash=400), then cash=500, date stays | `sqlite3` check old row updated: amount=500 at date May 15 | MEDIUM |
| bluecoins_12 | Edit existing transaction (May 12, 18000) to date=May 10, cash=18250 | original found, then date=May 10, cash=18250 | `sqlite3` check row with amount=18250 at date May 10 | MEDIUM |
| bluecoins_13 | Edit existing expense (May 13) to income, note "gift", sign="+" | original expense found, then type=Income, sign=+, date=May 13, note="gift" | `sqlite3` check type changed to income, note=gift | MEDIUM |
| bluecoins_14 | Edit existing income (May 2) to expense, cash=520, note "wrong operation", sign="-" | type=Expense, sign=-, date=May 2, cash=520, note="wrong operation" | `sqlite3` check type=expense, amount=520, note | MEDIUM |
| bluecoins_15 | Edit existing transaction (May 12, 794.20) to date=May 13, cash=936.02, note "grocery shopping" | date=May 13, cash=936.02, note="grocery shopping" | `sqlite3` check updated row | MEDIUM |

**Summary:** All 10 Bluecoins tasks are MEDIUM. The app uses SQLite; we need the exact DB path and schema but once known, all verifications are straightforward queries. The judge currently checks the *edit form* UI, but post-save verification via DB is more robust.

---

## 2. Calendar (tasks 1--14)

The Calendar app (likely Etar or Simple Calendar) stores events. The original judge checks the event-creation/edit form XML for field values. Events are often queryable via the Android CalendarProvider content provider.

| task_id | Task Description | Judge Sub-goals | ADB Verification Strategy | Difficulty |
|---------|-----------------|-----------------|--------------------------|------------|
| calendar_1 | Create event "work" today at 5:00 PM | page has "work", date=Today, time=5:00 PM | `content query --uri content://com.android.calendar/events` -- check title="work", dtstart matches today 17:00 | EASY |
| calendar_2 | Create event "homework" on May 21 with 10-min reminder | page has "homework", date=May 21, reminder=10 min | `content query` events for title="homework" + `content query` reminders table for minutes=10 | EASY |
| calendar_3 | Create event "meeting" on May 13 at location "conference room B202" | page has "meeting", date=May 13, location="conference room B202" | `content query` events for title="meeting", eventLocation="conference room B202" | EASY |
| calendar_4 | Create event "new month" on Jun 01 with Monthly recurrence | page has "new month", date=Jun 01, rrule=Monthly | `content query` events for title="new month", rrule contains FREQ=MONTHLY | EASY |
| calendar_5 | Create event "exam" today at 7:00 PM | page has "exam", date=Today, time=7:00 PM | `content query` events for title="exam", dtstart matches today 19:00 | EASY |
| calendar_6 | Edit "homework" event: add location "classroom 101" | original fields present (homework, May 21, 10-min reminder), then location="classroom 101" | `content query` events for title="homework", eventLocation="classroom 101" | EASY |
| calendar_7 | Edit "meeting" event: change reminder to 30 min | original fields present (meeting, May 13, B202), then reminder=30 min | `content query` reminders for event_id of "meeting", minutes=30 | EASY |
| calendar_8 | Edit "work" event: change reminder to 30 min | original fields present (work, Today, 5PM), then reminder=30 min | `content query` reminders for event_id of "work", minutes=30 | EASY |
| calendar_9 | Edit "work" event: set recurrence to Daily | original fields present (work, Today, 5PM, 30-min reminder), then rrule=Daily | `content query` events for title="work", rrule contains FREQ=DAILY | EASY |
| calendar_10 | Create event "birthday" (just needs to be on correct page) | page keyword "birthday" present | `content query` events for title="birthday" | EASY |
| calendar_11 | Edit event: set recurrence to Weekly | page has event + recurrence=Weekly | `content query` events for rrule contains FREQ=WEEKLY | EASY |
| calendar_12 | Edit event: add description "Hello" with Weekly recurrence visible | Weekly recurrence present, description contains "Hello" | `content query` events for description="Hello" | EASY |
| calendar_13 | Create event "sports" (just needs correct page) | page keyword "sports" present | `content query` events for title="sports" | EASY |
| calendar_14 | Edit event: set recurrence to Yearly | page has event + recurrence=Yearly | `content query` events for rrule contains FREQ=YEARLY | EASY |

**Summary:** All 14 Calendar tasks are EASY. Android's CalendarProvider (`content://com.android.calendar/events` and `content://com.android.calendar/reminders`) exposes all fields: title, dtstart, eventLocation, rrule, description. This is the most ADB-friendly app.

---

## 3. Clock (operation tasks: 1--9, 15, 17--27)

The Clock app (Google/AOSP) stores alarms in a content provider or database. Alarms can be queried via `content://com.android.deskclock/alarm` or `content query --uri content://com.google.android.deskclock/alarm`. World clocks and settings are trickier.

| task_id | Task Description | Judge Sub-goals | ADB Verification Strategy | Difficulty |
|---------|-----------------|-----------------|--------------------------|------------|
| clock_1 | Create alarm at 3:00 PM, label "meeting", enabled | time=3:00 PM, label="meeting", status=checked | `content query` alarm provider for hour=15, minutes=0, label="meeting", enabled=1 | MEDIUM |
| clock_2 | Create alarm at 6:45 AM, vibrate off, ringtone=Argon, enabled | time=6:45 AM, vibrate=off, ringtone=Argon, status=checked | `content query` alarm provider for hour=6, minutes=45, vibrate=0, alert URI contains "Argon" | MEDIUM |
| clock_3 | Create alarm at 7:00 AM, Mon-Fri, enabled | time=7:00 AM, days=Mon-Fri, status=checked | `content query` alarm for hour=7, minutes=0, daysofweek bitmask=31 (Mon-Fri), enabled=1 | MEDIUM |
| clock_4 | Create alarm at 9:00 AM, every day, enabled | time=9:00 AM, days=Every day, status=checked | `content query` alarm for hour=9, daysofweek=127, enabled=1 | MEDIUM |
| clock_5 | Create alarm at 10:30 AM, tomorrow, enabled | time=10:30 AM, days=Tomorrow, status=checked | `content query` alarm for hour=10, minutes=30, enabled=1 (no repeat) | MEDIUM |
| clock_6 | Create alarm at 10:30 PM, Sat-Sun, label "Watch Football Games", enabled | time=10:30 PM, days=Sat+Sun, label, status=checked | `content query` alarm for hour=22, minutes=30, daysofweek=96 (Sat+Sun), label, enabled=1 | MEDIUM |
| clock_7 | Disable all alarms | all alarms have status=unchecked | `content query` alarm provider, verify all rows have enabled=0 | MEDIUM |
| clock_8 | Delete all PM alarms after 2:00 PM | no PM alarms with hour > 14:00 remain | `content query` alarm provider, verify no rows with hour >= 14 | MEDIUM |
| clock_9 | Disable 4:00 PM alarm | 4:00 PM alarm has status=unchecked | `content query` alarm for hour=16, minutes=0, enabled=0 | MEDIUM |
| clock_15 | Add world clocks for London and Barcelona | London and Barcelona visible on Clock tab | World clocks stored in DB or shared prefs; `sqlite3` on deskclock DB `selected_cities` table | HARD |
| clock_17 | Delete Barcelona world clock | Barcelona no longer visible on Clock tab | Similar to 15, check `selected_cities` table for absence of Barcelona | HARD |
| clock_18 | Set timer to 1h 15m 0s | timer shows hour=1, minute=15, second=0 | Timer is ephemeral UI state, not persisted; no ADB query | HARD |
| clock_19 | Set bedtime to 10:00 PM, wake-up to 7:00 AM | bedtime=10:00 PM, wake-up=7:00 AM | Bedtime/DND schedule may be in `settings list secure` (zen_mode, next_alarm); or Clock app DB | HARD |
| clock_20 | Set sleep sound to "Deep space" | sleep sound = "Deep space" | App-specific preference, likely SharedPreferences XML; `cat /data/data/com.google.android.deskclock/shared_prefs/*.xml` | HARD |
| clock_21 | Enable wake-up alarm (7:00 AM bedtime alarm) | 7:00 AM bedtime alarm checked | Bedtime alarm may be in alarm provider or separate; requires investigation | HARD |
| clock_22 | Switch clock display to Analog | Analog clock mode visible | SharedPreferences key `display_clock_style`; `cat` shared_prefs | HARD |
| clock_23 | Set home time zone to Tokyo | home timezone = Tokyo | `settings get global time_zone` or Clock shared_prefs for home_time_zone | MEDIUM |
| clock_24 | Set "Silence after" to 5 minutes | silence_after = 5 minutes | Clock shared_prefs or `settings list system` for alarm_duration | MEDIUM |
| clock_25 | Navigate to show all tabs (Alarm, Clock, Timer, Stopwatch) | all 4 tabs visible | Pure UI navigation state; no persistent data to check | HARD |
| clock_26 | Disable 7:30 AM alarm | 7:30 AM alarm status=unchecked | `content query` alarm for hour=7, minutes=30, enabled=0 | MEDIUM |
| clock_27 | Enable 3:00 PM alarm | 3:00 PM alarm status=checked | `content query` alarm for hour=15, minutes=0, enabled=1 | MEDIUM |

**Summary:** Alarm CRUD tasks (1--9, 26, 27) are MEDIUM -- queryable via alarm content provider once URI is known. World clock, timer, bedtime, and display-preference tasks (15, 17--22, 25) are HARD -- they involve ephemeral UI state or app-specific SharedPreferences. Tasks 23-24 are MEDIUM (settings/prefs).

---

## 4. Contacts (operation tasks: 1--11)

Android Contacts are stored in the ContactsContract content provider, one of the best-documented Android APIs.

| task_id | Task Description | Judge Sub-goals | ADB Verification Strategy | Difficulty |
|---------|-----------------|-----------------|--------------------------|------------|
| contacts_1 | Create contact "John" with phone 1(234)567-8 | name="John", phone="1 (234) 567-8" visible | `content query --uri content://contacts/phones` or `content://com.android.contacts/data` for display_name="John", data1="12345678" | EASY |
| contacts_2 | View John's contact: verify mobile call + work email | Call Mobile 1(234)567-8, Email Work 123456@qq.com | `content query` contacts/data for mimetype=phone AND mimetype=email with matching values | EASY |
| contacts_3 | Add work phone and mobile to John Smith | Call Work 1(234)567-8, Call Mobile (876)543-21 | `content query` contacts/data for two phone entries with correct types | EASY |
| contacts_4 | View Xu's organization = "Tsinghua University" | organization = "Tsinghua University" | `content query` contacts/data mimetype=organization, data1="Tsinghua University" | EASY |
| contacts_5 | View "work" group with 3 contacts: Chen Chen, Lee Lee, Xu Xu | group "work" has 3 members | `content query` groups for title="work", then query group_membership | EASY |
| contacts_6 | Add phone number 00112233 to a contact | phone "00112233" exists | `content query` contacts/data mimetype=phone, data1 contains "00112233" | EASY |
| contacts_7 | Add birthday Oct 24, 1996 to a contact | birthday = "October 24, 1996" | `content query` contacts/data mimetype=event (birthday), data1="1996-10-24" | EASY |
| contacts_8 | Add website "abc.github.com" to a contact | website = "abc.github.com" | `content query` contacts/data mimetype=website, data1="abc.github.com" | EASY |
| contacts_9 | Send SMS "Nice to meet you" to ABC | messaging app shows "Texting with ABC" + message text | `content query content://sms` for body="Nice to meet you", address matches ABC | MEDIUM |
| contacts_10 | Call a contact (end call state) | page shows "End call" | `dumpsys telecom` or `dumpsys telephony.registry` for call state; ephemeral though | HARD |
| contacts_11 | Delete contact "AAA AAA" | "AAA AAA" no longer in contacts list | `content query` contacts for display_name="AAA AAA" returns empty | EASY |

**Summary:** Most Contacts tasks (1--8, 11) are EASY via ContactsContract. Task 9 (SMS) is MEDIUM (requires SMS content provider). Task 10 (phone call state) is HARD (ephemeral telephony state).

---

## 5. Settings (operation tasks: 1--5, 7--8, 13, 15, 18--22)

Settings tasks involve Android system settings -- many are directly queryable via `settings get` commands.

| task_id | Task Description | Judge Sub-goals | ADB Verification Strategy | Difficulty |
|---------|-----------------|-----------------|--------------------------|------------|
| setting_1 | Disable "Turn on Wi-Fi automatically" | Wi-Fi auto toggle = unchecked | `settings get global wifi_scan_always_enabled` = 0 | EASY |
| setting_2 | Set private DNS to "dns.google" | "dns.google" visible in DNS settings | `settings get global private_dns_specifier` = "dns.google" | EASY |
| setting_3 | Turn off Bluetooth | bluetooth_on = 0 | `settings get global bluetooth_on` = 0 | EASY |
| setting_4 | Rename Bluetooth device to "my AVD" | device name = "my AVD" | `settings get secure bluetooth_name` or `settings get global device_name` | EASY |
| setting_5 | Enable battery percentage display | battery percentage = checked | `settings get system status_bar_show_battery_percent` or `settings get secure battery_percentage_enabled` | EASY |
| setting_7 | Enable Dark theme | Dark theme = checked/on | `settings get secure ui_night_mode` = 2 (yes) or `cmd uimode night yes` then check | EASY |
| setting_8 | Set brightness to 0% | brightness = 0% | `settings get system screen_brightness` = 0 | EASY |
| setting_13 | Disable ring vibration | ring vibration = unchecked | `settings get system vibrate_when_ringing` = 0 | EASY |
| setting_15 | Add Spanish (US) as 2nd language | "Español (Estados Unidos)" present at position 2 | `settings get system system_locales` contains "es-US" | MEDIUM |
| setting_18 | Revoke Contacts permission from an app | Contacts not in "Allowed" list for the app | `dumpsys package <pkg>` check requested permissions + granted flags; or `appops get <pkg> READ_CONTACTS` | MEDIUM |
| setting_19 | Set Firefox as default browser | Firefox = default browser (checked) | `cmd role list-holders android.app.role.BROWSER` or `dumpsys role` | MEDIUM |
| setting_20 | Uninstall Booking.com app | `pm list packages` no longer contains com.booking | `pm list packages \| grep com.booking` returns empty | EASY |
| setting_21 | Open Settings main page | Settings home page visible (Search settings visible) | Pure navigation state -- but we can verify Settings is foreground via `dumpsys activity activities \| grep mResumedActivity` | EASY |
| setting_22 | Check airplane mode status (query task, answer-based) | reads `settings get global airplane_mode_on`, answers "open"/"not open" | `settings get global airplane_mode_on` | EASY |

**Summary:** Most Settings tasks are EASY -- they map directly to `settings get/put` commands. Tasks 15, 18, 19 are MEDIUM due to locale list parsing, permission management, and role queries respectively.

---

## 6. Maps/MapMe (operation tasks: 11--15)

Maps tasks involve setting locations (home/work) and starting navigation. The judge checks UI state (navigation screen showing destination + "Start" button).

| task_id | Task Description | Judge Sub-goals | ADB Verification Strategy | Difficulty |
|---------|-----------------|-----------------|--------------------------|------------|
| map_11 | Set work address to "18th Street, 3180" in My Places | "Work" shows "18th Street, 3180 - 50.6 km" | App-specific DB or Google Maps saved places; may query `content://com.google.android.apps.maps.provider/` | HARD |
| map_12 | Start navigation to Stanford | UI shows "Stanford" + "My location" + "Start" | Ephemeral navigation UI state; no persistent data | HARD |
| map_13 | Start navigation to University South | UI shows "University South" + "My location" + "Start" | Ephemeral navigation UI state | HARD |
| map_14 | Start navigation to OpenAI | UI shows "OpenAI" + "My location" + "Start" | Ephemeral navigation UI state | HARD |
| map_15 | Start navigation to UC Berkeley | UI shows "UC Berkeley" + "My location" + "Start" | Ephemeral navigation UI state | HARD |

**Summary:** All 5 Maps tasks are HARD. Navigation-start tasks (12--15) are purely ephemeral UI state. Task 11 (set work address) might be queryable from the Maps database but the schema is undocumented.

---

## 7. Pi Music Player (operation tasks: 7--12)

Pi Music Player is a third-party app. The judge checks UI state (now-playing screen, playlist views, sort order).

| task_id | Task Description | Judge Sub-goals | ADB Verification Strategy | Difficulty |
|---------|-----------------|-----------------|--------------------------|------------|
| pimusic_7 | Open Favorite playlist and play "PINK BLOOD" | PLAYLISTS tab selected, Favorite playlist opened, "PINK BLOOD" in now-playing | `dumpsys media_session` may show current track; playlist membership in app DB | HARD |
| pimusic_8 | Go to Artists > Pink Floyd, sort by duration (desc) | ARTISTS tab, Pink Floyd visible, songs sorted by duration descending | Sort order is ephemeral UI state; artist presence could be checked via MediaStore but sort cannot | HARD |
| pimusic_9 | Create playlist "Creepy" | PLAYLISTS tab selected, "Creepy" in list | `content query content://media/external/audio/playlists` for name="Creepy" | MEDIUM |
| pimusic_10 | Play a song and seek to 1:27 | now-playing shows "1:27" | `dumpsys media_session` may show playback position | HARD |
| pimusic_11 | Play "Lightship" | now-playing shows "Lightship" | `dumpsys media_session` for current track metadata | HARD |
| pimusic_12 | Sort tracks by duration ascending | TRACKS tab, sort step done, songs in ascending duration order | Sort order is ephemeral UI state | HARD |

**Summary:** Almost all Pi Music tasks are HARD. Task 9 (create playlist) is MEDIUM via the MediaStore playlists content provider. Playback state tasks (7, 10, 11) might be partially verifiable via `dumpsys media_session` but are unreliable. Sort-order tasks (8, 12) are purely UI state.

---

## 8. Cantook / Aldiko (operation tasks: 6--12)

Cantook (book reader app) stores library data in its own database. The judge checks UI state for book presence, read status, categories, and collections.

| task_id | Task Description | Judge Sub-goals | ADB Verification Strategy | Difficulty |
|---------|-----------------|-----------------|--------------------------|------------|
| cantook_6 | Download/add "Alice's Adventures in Wonderland" | book title in library view | Check app DB (`sqlite3 /data/data/<pkg>/databases/`) for book title; or check file existence in app storage | MEDIUM |
| cantook_7 | Remove "Don Quixote" from library | "Don Quixote" not in My Books | `sqlite3` app DB to verify book removed | MEDIUM |
| cantook_8 | Mark "Hamlet" as read (100%) | "Hamlet" visible, "Mark as unread" + "100.0%" shown | `sqlite3` app DB for read_percentage=100 on Hamlet entry | MEDIUM |
| cantook_9 | Mark "Oliver Twist" as unread | "Oliver Twist" visible, "Mark as read" shown (meaning currently unread) | `sqlite3` app DB for read status on Oliver Twist | MEDIUM |
| cantook_10 | Open a specific page/passage in a book | specific Shakespeare quote text visible | Ephemeral reading position; no simple ADB query | HARD |
| cantook_11 | Navigate to Categories > Tragedies showing Hamlet + Romeo and Juliet | Categories tab selected, "Tragedies" category, both books visible | Category assignment is in app DB; `sqlite3` query for category+books | MEDIUM |
| cantook_12 | Navigate to Collections > show "Favorite" | Collections tab selected, "Favorite" collection visible | `sqlite3` app DB for collection existence | MEDIUM |

**Summary:** Most Cantook tasks are MEDIUM -- they involve app-specific SQLite databases whose schema would need reverse-engineering. Task 10 (reading position/passage) is HARD.

---

## 9. Zoom (all 5 tasks)

Zoom tasks involve configuring meeting-join settings and app preferences. The judge checks the join-meeting form UI and settings pages.

| task_id | Task Description | Judge Sub-goals | ADB Verification Strategy | Difficulty |
|---------|-----------------|-----------------|--------------------------|------------|
| zoom_1 | Enter meeting ID "123 456 7890" in join form | meeting ID field shows "123 456 7890" | Ephemeral form state; no ADB query | HARD |
| zoom_2 | Enter meeting ID "098 765 4321" and name "Alice" | meeting ID + name fields filled | Ephemeral form state | HARD |
| zoom_3 | Enter meeting ID "123 456 7890", toggle off audio + video | meeting ID filled, "Don't Connect To Audio"=On, "Turn Off My Video"=On | Ephemeral form state + toggle state | HARD |
| zoom_4 | Set auto-connect audio to "WiFi or cellular data" | auto-connect setting = "WiFi or cellular data" | Zoom SharedPreferences or app DB; `cat /data/data/us.zoom.videomeetings/shared_prefs/*.xml` | HARD |
| zoom_5 | Set reaction skin tone to "Medium-light" | "Medium-light" selected | Zoom SharedPreferences | HARD |

**Summary:** All 5 Zoom tasks are HARD. Tasks 1--3 involve ephemeral form state. Tasks 4--5 involve app-specific SharedPreferences that may be readable via `cat` but the preference keys are undocumented.

---

## Aggregate Summary

| App | Total Ops | EASY | MEDIUM | HARD |
|-----|-----------|------|--------|------|
| Bluecoins | 10 | 0 | 10 | 0 |
| Calendar | 14 | 14 | 0 | 0 |
| Clock | 22 | 0 | 12 | 10 |
| Contacts | 11 | 8 | 1 | 2 |
| Settings | 14 | 10 | 3 | 1 |
| Maps | 5 | 0 | 0 | 5 |
| Pi Music | 6 | 0 | 1 | 5 |
| Cantook | 7 | 0 | 5 | 2 |
| Zoom | 5 | 0 | 0 | 5 |
| **TOTAL** | **94** | **32** | **32** | **30** |

### Recommended Implementation Priority

**Phase 1 -- EASY tasks (32 tasks, highest ROI):**
Calendar (14), Settings (10), Contacts (8). These use standard Android content providers and `settings get/put` commands with well-documented APIs.

**Phase 2 -- MEDIUM tasks (32 tasks):**
Bluecoins (10), Clock alarms (12), Contacts SMS (1), Settings locale/perms/roles (3), Cantook (5), Pi Music playlist (1). These require reverse-engineering app databases or using less-documented content providers.

**Phase 3 -- HARD tasks (30 tasks, lowest ROI):**
Maps navigation (5), Zoom forms (5), Clock non-alarm features (10), Pi Music playback/sort (5), Cantook reading position (1), Contacts call state (1), Settings navigation (1). These require UI-state inspection (XML dump + parsing) or reading undocumented SharedPreferences. For terminal agents, these would need `uiautomator dump` + grep as a fallback.

### ADB Commands Reference

```bash
# Calendar events
adb shell content query --uri content://com.android.calendar/events --projection title:dtstart:eventLocation:rrule:description

# Calendar reminders
adb shell content query --uri content://com.android.calendar/reminders --projection event_id:minutes:method

# Contacts
adb shell content query --uri content://com.android.contacts/data --projection display_name:mimetype:data1:data2

# Contact groups
adb shell content query --uri content://com.android.contacts/groups --projection title:_id

# SMS
adb shell content query --uri content://sms --projection address:body:date

# Alarms (AOSP clock)
adb shell content query --uri content://com.android.deskclock/alarm

# Settings
adb shell settings get global bluetooth_on
adb shell settings get global airplane_mode_on
adb shell settings get global wifi_scan_always_enabled
adb shell settings get global private_dns_specifier
adb shell settings get system screen_brightness
adb shell settings get system vibrate_when_ringing
adb shell settings get secure ui_night_mode
adb shell settings get system system_locales

# Package management
adb shell pm list packages | grep <pkg>
adb shell cmd role list-holders android.app.role.BROWSER
adb shell dumpsys package <pkg> | grep -A5 "requested permissions"

# Media session (playback state)
adb shell dumpsys media_session

# Current activity
adb shell dumpsys activity activities | grep mResumedActivity
```
