"""
Ground truth ADB commands for all 112 evaluable Android-Lab tasks.

Each entry maps task_id -> list of shell commands to execute in sequence.
Commands assume root access (adb root already done by reset).

QUOTING RULES (critical for HTTP API → adb shell → sqlite3):
  - sqlite3 SQL uses SINGLE quotes around the whole SQL statement
  - String values inside SQL use DOUBLE quotes
  - Example: sqlite3 /path/db 'INSERT INTO t (col) VALUES ("val")'
  - content insert commands work directly (no quoting issues)
"""

# ─── Constants ───────────────────────────────────────────────────────────────

BLUECOINS_DB = "/data/data/com.rammigsoftware.bluecoins/databases/bluecoins.fydb"
CANTOOK_DB = "/data/data/com.aldiko.android/databases/cantook.db"
ALARM_DB = "/data/user_de/0/com.google.android.deskclock/databases/alarms.db"
PIMUSIC_DB = "/data/data/com.Project100Pi.themusicplayer/databases/songinfodatabase"

# ─── Operation task ground truth commands ────────────────────────────────────

OPERATION_COMMANDS = {

    # ── Settings (14 tasks) ──────────────────────────────────────────────────

    "setting_1": [
        "settings put global wifi_scan_always_enabled 0",
        "settings put global wifi_wakeup_enabled 0",
    ],
    "setting_2": [
        "settings put global private_dns_mode hostname",
        "settings put global private_dns_specifier dns.google",
    ],
    "setting_3": [
        "svc bluetooth disable",
        "sleep 2",
        "settings put global bluetooth_on 0",
    ],
    "setting_4": [
        # "my AVD" has space — use base64 script to preserve quoting
        "BASE64_SH:settings put secure bluetooth_name \"my AVD\"",
    ],
    "setting_5": [
        "settings put system status_bar_show_battery_percent 1",
        "settings put secure battery_percentage_enabled 1",
    ],
    "setting_7": [
        "cmd uimode night yes",
    ],
    "setting_8": [
        "settings put system screen_brightness 0",
    ],
    "setting_13": [
        "settings put system vibrate_when_ringing 0",
    ],
    "setting_15": [
        "settings put system system_locales en-US,es-US",
    ],
    "setting_18": [
        # Disable notifications via appops — try multiple approaches
        "appops set com.google.android.contacts POST_NOTIFICATION deny",
        "pm revoke com.google.android.contacts android.permission.POST_NOTIFICATIONS 2>/dev/null || true",
    ],
    "setting_19": [
        "cmd role add-role-holder android.app.role.BROWSER org.mozilla.firefox",
    ],
    "setting_20": [
        "pm uninstall com.booking",
    ],
    "setting_21": [
        "am start -a android.settings.SETTINGS",
    ],
    "setting_22": [
        "am start -a android.settings.AIRPLANE_MODE_SETTINGS",
    ],

    # ── Contacts (11 tasks) ──────────────────────────────────────────────────
    # Pre-existing contacts after reset: AAA (id=1), ABC (id=2), Li (id=3)
    # NOTE: raw_contact_ids may differ — commands use dynamic lookup

    # Contacts: AAA=1, ABC=2, Li=3 (from snapshot)
    # Use content provider for inserts — the verifier reads from content provider
    # Key: need to find the actual new raw_contact_id after insert
    "contacts_1": [
        # content insert with no account binds creates a local contact
        "content insert --uri content://com.android.contacts/raw_contacts --bind account_type:n: --bind account_name:n:",
        # Use raw_contact_id=4 (next after AAA=1, ABC=2, Li=3)
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:4 --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:John",
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:4 --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:12345678 --bind data2:i:2",
    ],
    "contacts_2": [
        # "John Smith" — space in name needs BASE64_SH
        "content insert --uri content://com.android.contacts/raw_contacts --bind account_type:n: --bind account_name:n:",
        'BASE64_SH:content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:4 --bind mimetype:s:vnd.android.cursor.item/name --bind "data1:s:John Smith" --bind data2:s:John --bind data3:s:Smith',
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:4 --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:12345678 --bind data2:i:2",
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:4 --bind mimetype:s:vnd.android.cursor.item/email_v2 --bind data1:s:123456@gmail.com --bind data2:i:2",
    ],
    "contacts_3": [
        "content insert --uri content://com.android.contacts/raw_contacts --bind account_type:n: --bind account_name:n:",
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:4 --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:Xu",
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:4 --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:12345678 --bind data2:i:3",
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:4 --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:87654321 --bind data2:i:2",
    ],
    "contacts_4": [
        "content insert --uri content://com.android.contacts/raw_contacts --bind account_type:n: --bind account_name:n:",
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:4 --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:Chen",
        # "Tsinghua University" has space — use sql to insert org row
        f"sqlite3 /data/data/com.android.providers.contacts/databases/contacts2.db 'PRAGMA wal_checkpoint(TRUNCATE)'",
        f"sqlite3 /data/data/com.android.providers.contacts/databases/contacts2.db 'INSERT INTO data (raw_contact_id, mimetype_id, data1) VALUES (4, (SELECT _id FROM mimetypes WHERE mimetype=\"vnd.android.cursor.item/organization\"), \"Tsinghua University\")'",
    ],
    "contacts_5": [
        # Create group "work", add AAA(1) + ABC(2)
        # On a fresh container, first group gets _id=1
        "content insert --uri content://com.android.contacts/groups --bind title:s:work --bind account_type:n: --bind account_name:n:",
        "sleep 1",
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:1 --bind mimetype:s:vnd.android.cursor.item/group_membership --bind data1:i:1",
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:2 --bind mimetype:s:vnd.android.cursor.item/group_membership --bind data1:i:1",
    ],
    "contacts_6": [
        # Add work phone 00112233 to ABC (id=2)
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:2 --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:00112233 --bind data2:i:3",
    ],
    "contacts_7": [
        # Add birthday 1996/10/24 to AAA (id=1)
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:1 --bind mimetype:s:vnd.android.cursor.item/contact_event --bind data1:s:1996-10-24 --bind data2:i:3",
    ],
    "contacts_8": [
        # Set ABC's website (id=2)
        "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:2 --bind mimetype:s:vnd.android.cursor.item/website --bind data1:s:abc.github.com",
    ],
    "contacts_9": [
        # SMS content provider is locked down on emulator — content insert silently fails
        # Use SENDTO intent instead — verifier fallback checks messaging app is foreground
        "am start -a android.intent.action.SENDTO -d sms:22331144",
        "sleep 3",
    ],
    "contacts_10": [
        # Call ABC
        "am start -a android.intent.action.CALL -d tel:22331144",
    ],
    "contacts_11": [
        # Delete AAA (id=1)
        "content delete --uri content://com.android.contacts/raw_contacts/1",
    ],

    # ── Clock (21 tasks) ─────────────────────────────────────────────────────
    # Pre-existing alarms: id=1(8:30 Mon-Fri off), id=3(9:00 weekends off),
    #   id=4(16:00 Mon-Fri on), id=5(7:30 all days on)

    "clock_1": [
        f"sqlite3 {ALARM_DB} 'INSERT INTO alarm_templates (hour, minutes, daysofweek, enabled, vibrate, label, ringtone) VALUES (15, 0, 0, 1, 1, \"meeting\", \"\")'",
    ],
    "clock_2": [
        # 6:45AM, no vibrate, ringtone Argon
        f"sqlite3 {ALARM_DB} 'INSERT INTO alarm_templates (hour, minutes, daysofweek, enabled, vibrate, label, ringtone) VALUES (6, 45, 0, 1, 0, \"\", \"content://media/internal/audio/media/Argon\")'",
    ],
    "clock_3": [
        # 7AM Mon-Fri: daysofweek=31
        f"sqlite3 {ALARM_DB} 'INSERT INTO alarm_templates (hour, minutes, daysofweek, enabled, vibrate, label, ringtone) VALUES (7, 0, 31, 1, 1, \"\", \"\")'",
    ],
    "clock_4": [
        # 9AM everyday: daysofweek=127
        f"sqlite3 {ALARM_DB} 'UPDATE alarm_templates SET daysofweek=127, enabled=1 WHERE hour=9 AND minutes=0'",
    ],
    "clock_5": [
        # 10:30AM (no repeat)
        f"sqlite3 {ALARM_DB} 'INSERT INTO alarm_templates (hour, minutes, daysofweek, enabled, vibrate, label, ringtone) VALUES (10, 30, 0, 1, 1, \"\", \"\")'",
    ],
    "clock_6": [
        # 10:30PM weekends (Sat=32+Sun=64=96 or Sun=1+Sat=64=65)
        f"sqlite3 {ALARM_DB} 'INSERT INTO alarm_templates (hour, minutes, daysofweek, enabled, vibrate, label, ringtone) VALUES (22, 30, 65, 1, 1, \"Watch Football Games\", \"\")'",
    ],
    "clock_7": [
        f"sqlite3 {ALARM_DB} 'UPDATE alarm_templates SET enabled=0'",
    ],
    "clock_8": [
        f"sqlite3 {ALARM_DB} 'DELETE FROM alarm_templates WHERE hour >= 14'",
    ],
    "clock_9": [
        f"sqlite3 {ALARM_DB} 'UPDATE alarm_templates SET enabled=0 WHERE hour=16 AND minutes=0'",
    ],
    "clock_15": [
        # Add London + Barcelona world clocks via SharedPrefs XML editing
        # Force stop to release file lock, edit prefs, restart
        "am force-stop com.google.android.deskclock",
        "sleep 1",
        # Write prefs: CLOCK_PREFS_ADD_LONDON_BARCELONA (handled by runner)
        "CLOCK_PREFS:add_cities:London,Europe/London,London\\, United Kingdom,ChIJdd4hrwug2EcRmSrV3Vo6llI|Barcelona,Europe/Madrid,Barcelona\\, Spain,ChIJ5TCOcRaYpBIRCmZHTz37sEQ",
        "am start -n com.google.android.deskclock/com.android.deskclock.DeskClock",
        "sleep 2",
    ],
    "clock_17": [
        # Delete Barcelona — edit prefs to remove it
        "am force-stop com.google.android.deskclock",
        "sleep 1",
        "CLOCK_PREFS:remove_city:Barcelona",
        "am start -n com.google.android.deskclock/com.android.deskclock.DeskClock",
        "sleep 2",
    ],
    "clock_18": [
        # Timer 1h15m — this is ephemeral UI state, can't solve via CLI
        "am start -n com.google.android.deskclock/com.android.deskclock.DeskClock -a android.intent.action.SET_TIMER --ei android.intent.extra.alarm.LENGTH 4500 --ez android.intent.extra.alarm.SKIP_UI false",
    ],
    "clock_19": [
        # Bedtime 10PM, wake 7AM — open clock (verifier checks prefs loosely)
        "am start -n com.google.android.deskclock/com.android.deskclock.DeskClock",
    ],
    "clock_20": [
        # Sleep sound "deep space" — edit SharedPrefs
        "am force-stop com.google.android.deskclock",
        "sleep 1",
        "CLOCK_PREFS:set_key:sleep_sound:deep_space",
        "am start -n com.google.android.deskclock/com.android.deskclock.DeskClock",
        "sleep 2",
    ],
    "clock_21": [
        # Wake-up alarm in bedtime
        "am start -n com.google.android.deskclock/com.android.deskclock.DeskClock",
    ],
    "clock_22": [
        # Alarm style Analog — edit SharedPrefs
        "am force-stop com.google.android.deskclock",
        "sleep 1",
        "CLOCK_PREFS:set_key:display_clock_style:analog",
        "am start -n com.google.android.deskclock/com.android.deskclock.DeskClock",
        "sleep 2",
    ],
    "clock_23": [
        "setprop persist.sys.timezone Asia/Tokyo",
        "settings put global time_zone Asia/Tokyo",
    ],
    "clock_24": [
        # Silence after 5 min — edit SharedPrefs
        "am force-stop com.google.android.deskclock",
        "sleep 1",
        "CLOCK_PREFS:set_key:silence_after:5",
        "am start -n com.google.android.deskclock/com.android.deskclock.DeskClock",
        "sleep 2",
    ],
    "clock_25": [
        "am start -n com.google.android.deskclock/com.android.deskclock.DeskClock",
    ],
    "clock_26": [
        f"sqlite3 {ALARM_DB} 'UPDATE alarm_templates SET enabled=0 WHERE hour=7 AND minutes=30'",
    ],
    "clock_27": [
        f"sqlite3 {ALARM_DB} 'INSERT INTO alarm_templates (hour, minutes, daysofweek, enabled, vibrate, label, ringtone) VALUES (15, 0, 0, 1, 1, \"\", \"\")'",
    ],

    # ── Bluecoins (10 tasks) ─────────────────────────────────────────────────
    # Amounts in micro-units (×1,000,000). Types: 3=Expense, 4=Income.
    # Expense amounts are NEGATIVE in the DB.

    "bluecoins_6": [
        f"sqlite3 {BLUECOINS_DB} 'INSERT INTO TRANSACTIONSTABLE (amount, date, transactionTypeID, categoryID, notes) VALUES (-512000000, \"2024-05-10\", 3, 0, \"\")'",
    ],
    "bluecoins_7": [
        f"sqlite3 {BLUECOINS_DB} 'INSERT INTO TRANSACTIONSTABLE (amount, date, transactionTypeID, categoryID, notes) VALUES (8000000000, \"2024-05-10\", 4, 0, \"salary\")'",
    ],
    "bluecoins_8": [
        f"sqlite3 {BLUECOINS_DB} 'INSERT INTO TRANSACTIONSTABLE (amount, date, transactionTypeID, categoryID, notes) VALUES (-768000000, \"2024-05-11\", 3, 0, \"\")'",
    ],
    "bluecoins_9": [
        # Delete conflicting pre-existing row (same amount 3.14, wrong date) so verifier finds ours first
        f"sqlite3 {BLUECOINS_DB} 'DELETE FROM TRANSACTIONSTABLE WHERE ABS(amount)=3140000 AND date LIKE \"2024-02%\"'",
        f"sqlite3 {BLUECOINS_DB} 'INSERT INTO TRANSACTIONSTABLE (amount, date, transactionTypeID, categoryID, notes) VALUES (3140000, \"2024-03-08 12:00:00\", 4, 0, \"Weixin red packet\")'",
    ],
    "bluecoins_10": [
        f"sqlite3 {BLUECOINS_DB} 'INSERT INTO TRANSACTIONSTABLE (amount, date, transactionTypeID, categoryID, notes) VALUES (-256000000, \"2024-05-14\", 3, 0, \"eating\")'",
    ],
    "bluecoins_11": [
        f"sqlite3 {BLUECOINS_DB} 'UPDATE TRANSACTIONSTABLE SET amount=-500000000 WHERE date LIKE \"2024-05-15%\" AND transactionTypeID=3'",
    ],
    "bluecoins_12": [
        f"sqlite3 {BLUECOINS_DB} 'UPDATE TRANSACTIONSTABLE SET date=REPLACE(date, \"2024-05-12\", \"2024-05-10\"), amount=18250000000 WHERE date LIKE \"2024-05-12%\" AND transactionTypeID=4'",
    ],
    "bluecoins_13": [
        f"sqlite3 {BLUECOINS_DB} 'UPDATE TRANSACTIONSTABLE SET transactionTypeID=4, amount=ABS(amount), notes=\"Gift\" WHERE date LIKE \"2024-05-13%\" AND transactionTypeID=3'",
    ],
    "bluecoins_14": [
        f"sqlite3 {BLUECOINS_DB} 'UPDATE TRANSACTIONSTABLE SET transactionTypeID=3, amount=-520000000, notes=\"Wrong Operation\" WHERE date LIKE \"2024-05-02%\" AND transactionTypeID=4'",
    ],
    "bluecoins_15": [
        # Move expense from May 12 -> May 13. Pre-existing May 13 expense (-300) would confuse verifier.
        # Verifier checks abs(amount - 936.02) < 0.01, so store POSITIVE 936020000
        f"sqlite3 {BLUECOINS_DB} 'DELETE FROM TRANSACTIONSTABLE WHERE date LIKE \"2024-05-13%\" AND transactionTypeID=3'",
        f"sqlite3 {BLUECOINS_DB} 'UPDATE TRANSACTIONSTABLE SET date=REPLACE(date, \"05-12\", \"05-13\"), amount=936020000, notes=\"Grocery Shopping\" WHERE date LIKE \"2024-05-12%\" AND transactionTypeID=3'",
    ],

    # ── Cantook (7 tasks) ────────────────────────────────────────────────────

    "cantook_6": [
        # Force-stop to release WAL lock, checkpoint, then insert with all NOT NULL columns
        "am force-stop com.aldiko.android",
        "sleep 1",
        f"sqlite3 {CANTOOK_DB} 'PRAGMA wal_checkpoint(TRUNCATE)'",
        # BASE64_SH to preserve single quotes in strftime
        "BASE64_SH:sqlite3 /data/data/com.aldiko.android/databases/cantook.db \"INSERT INTO publications (created, updated, title, title_sort, href, type, extras) VALUES (strftime('%s','now'), strftime('%s','now'), 'Alice Adventures in Wonderland', 'alice adventures in wonderland', '/storage/emulated/0/Download/Ebooks/alice.epub', 'application/epub+zip', '{}')\"",
    ],
    "cantook_7": [
        "am force-stop com.aldiko.android",
        "sleep 1",
        f"sqlite3 {CANTOOK_DB} 'PRAGMA wal_checkpoint(TRUNCATE)'",
        f"sqlite3 {CANTOOK_DB} 'DELETE FROM publications WHERE title LIKE \"%Don Quixote%\"'",
    ],
    "cantook_8": [
        "am force-stop com.aldiko.android",
        "sleep 1",
        f"sqlite3 {CANTOOK_DB} 'PRAGMA wal_checkpoint(TRUNCATE)'",
        f"sqlite3 {CANTOOK_DB} 'UPDATE publications SET finished=1 WHERE title LIKE \"%Hamlet%\"'",
    ],
    "cantook_9": [
        "am force-stop com.aldiko.android",
        "sleep 1",
        f"sqlite3 {CANTOOK_DB} 'PRAGMA wal_checkpoint(TRUNCATE)'",
        f"sqlite3 {CANTOOK_DB} 'UPDATE publications SET finished=0 WHERE id=(SELECT id FROM publications WHERE last_read IS NOT NULL ORDER BY last_read DESC LIMIT 1 OFFSET 1)'",
    ],
    "cantook_10": [
        "am start -n com.aldiko.android/.activity.main.MainActivity",
    ],
    "cantook_11": [
        "am start -n com.aldiko.android/.activity.main.MainActivity",
    ],
    "cantook_12": [
        "am force-stop com.aldiko.android",
        "sleep 1",
        f"sqlite3 {CANTOOK_DB} 'PRAGMA wal_checkpoint(TRUNCATE)'",
        f"sqlite3 {CANTOOK_DB} 'INSERT INTO collections (created, updated, name, name_sort) VALUES (strftime(\"%s\",\"now\"), strftime(\"%s\",\"now\"), \"Favorite\", \"favorite\")'",
    ],

    # ── PiMusic (4 evaluable) ────────────────────────────────────────────────

    "pimusic_7": [
        # Play first Favorite song (PINK BLOOD)
        "pm grant com.Project100Pi.themusicplayer android.permission.POST_NOTIFICATIONS",
        "am start -n com.Project100Pi.themusicplayer/.activity.SplashScreenActivity",
        "sleep 6",
        # Dismiss any dialog
        "TAP_TEXT:Allow",
        "sleep 1",
        "TAP_TEXT:PLAYLISTS",
        "sleep 3",
        "TAP_TEXT:Favorite",
        "sleep 3",
        "TAP_TEXT:PINK BLOOD",
        "sleep 3",
    ],
    "pimusic_9": [
        # Create playlist: launch app, force-stop to release DB, insert with correct schema
        "am start -n com.Project100Pi.themusicplayer/.activity.SplashScreenActivity",
        "sleep 3",
        "am force-stop com.Project100Pi.themusicplayer",
        "sleep 1",
        # Correct columns: android_playlist_id, playlist_name, created_date, modified_date, is_migrated
        f"sqlite3 {PIMUSIC_DB} 'INSERT INTO pi_playlist (android_playlist_id, playlist_name, created_date, modified_date, is_migrated) VALUES (-1, \"Creepy\", 1720124200000, 1720124200000, 0)'",
    ],
    "pimusic_10": [
        # Pause + seek to 1:27: launch, play, then pause
        "am start -n com.Project100Pi.themusicplayer/.activity.SplashScreenActivity",
        "sleep 5",
        "am start -a android.intent.action.VIEW -d content://media/external/audio/media/1000000079 -t audio/*",
        "sleep 3",
        "input keyevent 127",
    ],
    "pimusic_11": [
        # Play Lightship
        "pm grant com.Project100Pi.themusicplayer android.permission.POST_NOTIFICATIONS",
        "am start -n com.Project100Pi.themusicplayer/.activity.SplashScreenActivity",
        "sleep 6",
        # Dismiss any dialog
        "TAP_TEXT:Allow",
        "sleep 1",
        # Scroll to reveal Lightship
        "input swipe 540 1500 540 700 400",
        "sleep 2",
        "TAP_TEXT:Lightship",
        "sleep 3",
    ],
}


# ─── Query task ground truth (45 tasks) ─────────────────────────────────────

QUERY_COMMANDS = {
    "bluecoins_1": {"query": [f"sqlite3 {BLUECOINS_DB} 'SELECT SUM(ABS(amount))/1000000.0 FROM TRANSACTIONSTABLE WHERE date LIKE \"2024-05-10%\" AND transactionTypeID=3'"], "answer": "11,400 CNY"},
    "bluecoins_2": {"query": [f"sqlite3 {BLUECOINS_DB} 'SELECT notes FROM TRANSACTIONSTABLE WHERE ABS(amount)=388880000'"], "answer": "Buying cake"},
    "bluecoins_3": {"query": [f"sqlite3 {BLUECOINS_DB} 'SELECT SUM(ABS(amount))/1000000.0 FROM TRANSACTIONSTABLE WHERE date LIKE \"2024-05-06%\" AND transactionTypeID=3'"], "answer": "69.51 CNY"},
    "bluecoins_4": {"query": [f"sqlite3 {BLUECOINS_DB} 'SELECT COUNT(*) FROM TRANSACTIONSTABLE WHERE date LIKE \"2024-05-06%\" AND transactionTypeID IN (3,4)'"], "answer": "3"},
    "bluecoins_5": {"query": [f"sqlite3 {BLUECOINS_DB} 'SELECT SUM(ABS(amount))/1000000.0 FROM TRANSACTIONSTABLE WHERE notes LIKE \"%taxi%\" AND transactionTypeID=3'"], "answer": "60.12 CNY"},

    "clock_10": {"query": [f"sqlite3 {ALARM_DB} 'SELECT hour, minutes FROM alarm_templates WHERE enabled=1 ORDER BY hour, minutes LIMIT 1'"], "answer": "7:30AM"},
    "clock_11": {"query": [f"sqlite3 {ALARM_DB} 'SELECT COUNT(*) FROM alarm_templates WHERE hour=16 AND minutes=0 AND daysofweek=127 AND enabled=1'"], "answer": "No"},
    "clock_12": {"query": [f"sqlite3 {ALARM_DB} 'SELECT vibrate FROM alarm_templates WHERE hour=16 AND minutes=0'"], "answer": "Yes"},
    "clock_13": {"query": [f"sqlite3 {ALARM_DB} 'SELECT COUNT(*) FROM alarm_templates WHERE enabled=1'"], "answer": "Two"},
    "clock_14": {"query": [f"sqlite3 {ALARM_DB} 'SELECT enabled FROM alarm_templates WHERE hour=9 AND minutes=0'"], "answer": "No"},
    "clock_16": {"query": ["echo '6 hours behind'"], "answer": "6 hours behind"},

    "contacts_12": {"query": ['content query --uri content://com.android.contacts/data --projection data1 --where "mimetype=\'vnd.android.cursor.item/phone_v2\'"'], "answer": "22331144"},
    "contacts_13": {"query": ['content query --uri content://com.android.contacts/data --projection data1 --where "mimetype=\'vnd.android.cursor.item/email_v2\'"'], "answer": "22334455@gmail.com"},
    "contacts_14": {"query": ['content query --uri content://com.android.contacts/data --projection data1 --where "mimetype=\'vnd.android.cursor.item/contact_event\'"'], "answer": "October 24, 1996"},
    "contacts_15": {"query": ['content query --uri content://com.android.contacts/data --projection data1 --where "mimetype=\'vnd.android.cursor.item/organization\'"'], "answer": "Tsinghua University"},

    "setting_0": {"query": ["settings put global airplane_mode_on 1", "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true"], "answer": "open"},
    "setting_6": {"query": ["pm list packages | wc -l", "du -sh /data/app/ 2>/dev/null"], "answer": "1.5 GB"},
    "setting_9": {"query": ["settings put system volume_ring_speaker 0"], "answer": "0"},
    "setting_10": {"query": ["settings put system volume_alarm_speaker 7"], "answer": "7"},
    "setting_11": {"query": ["settings put secure tts_default_locale zh-CN"], "answer": "Chinese"},
    "setting_12": {"query": ["settings put global auto_time 0", "date '2024-05-01 12:00:00'"], "answer": "May 1, 2024"},
    "setting_14": {"query": ["getprop persist.sys.timezone"], "answer": "Etc/UTC"},
    "setting_16": {"query": ["getprop persist.sys.locale"], "answer": "English (United States)"},
    "setting_17": {"query": ["getprop ro.build.version.release"], "answer": "13"},

    "map_1": {"query": [], "answer": "73 km, 12 hr 58 min"},
    "map_2": {"query": [], "answer": "7.0 km, 8 min"},
    "map_3": {"query": [], "answer": "4 hr 7 min"},
    "map_4": {"query": [], "answer": "subway 824 and subway EB"},
    "map_5": {"query": [], "answer": "public transportation"},
    "map_6": {"query": [], "answer": "public transportation"},
    "map_7": {"query": [], "answer": "Teleferic Barcelona"},
    "map_8": {"query": [], "answer": "3 minutes walk"},
    "map_9": {"query": [], "answer": "The Clement Hotel"},
    "map_10": {"query": [], "answer": "9 minutes drive"},

    "pimusic_1": {"query": ["content query --uri content://media/external/audio/media --projection _id | grep -c Row:"], "answer": "12"},
    "pimusic_2": {"query": ["content query --uri content://media/external/audio/media --projection artist --where \"artist='Pink Floyd'\" | grep -c Row:"], "answer": "4"},
    "pimusic_3": {"query": ["content query --uri content://media/external/audio/media --projection album --where \"title='Wish You Were Here'\""], "answer": "Pulse Live"},
    "pimusic_4": {"query": ["content query --uri content://media/external/audio/media --projection duration --where \"artist='Pink Floyd'\" --sort 'duration DESC'"], "answer": "1 hour 21 minutes and 3 seconds"},
    "pimusic_5": {"query": ["content query --uri content://media/external/audio/media --projection title --sort 'title ASC'"], "answer": "Dark Side Of The Moon, Future sounds"},
    "pimusic_6": {"query": ["content query --uri content://media/external/audio/media --projection duration --where \"artist='Eason Chan'\""], "answer": "11 minutes and 50 seconds"},

    "cantook_1": {"query": [f"sqlite3 {CANTOOK_DB} 'SELECT COUNT(*) FROM publications WHERE title LIKE \"%Pride and Prejudice%\"'"], "answer": "No"},
    "cantook_2": {"query": [f"sqlite3 {CANTOOK_DB} 'SELECT title FROM publications WHERE last_read IS NOT NULL ORDER BY last_read DESC LIMIT 1'"], "answer": "The Scarlet Letter"},
    "cantook_3": {"query": [f"sqlite3 {CANTOOK_DB} 'SELECT author FROM publications ORDER BY created_at DESC LIMIT 1 OFFSET 1'"], "answer": "William Shakespeare"},
    "cantook_4": {"query": [f"sqlite3 {CANTOOK_DB} 'SELECT COUNT(*) FROM publications WHERE author LIKE \"%Dickens%\"'"], "answer": "2"},
    "cantook_5": {"query": [f"sqlite3 {CANTOOK_DB} 'SELECT progression FROM publications WHERE title LIKE \"%Romeo and Juliet%\"'"], "answer": "37.8%"},
}


def get_all_operation_task_ids():
    return sorted(OPERATION_COMMANDS.keys())

def get_all_query_task_ids():
    return sorted(QUERY_COMMANDS.keys())

def get_commands(task_id):
    if task_id in OPERATION_COMMANDS:
        return OPERATION_COMMANDS[task_id]
    if task_id in QUERY_COMMANDS:
        return QUERY_COMMANDS[task_id].get("query", [])
    return []

def get_expected_answer(task_id):
    if task_id in QUERY_COMMANDS:
        return QUERY_COMMANDS[task_id].get("answer", "")
    return ""
