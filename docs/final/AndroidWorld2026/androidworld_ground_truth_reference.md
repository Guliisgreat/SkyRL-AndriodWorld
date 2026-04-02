# AndroidWorld Ground Truth Reference — 116 Tasks

Complete reference for all AndroidWorld benchmark tasks: task descriptions,
ground truth ADB commands with step-by-step explanations, and verifier logic.

**Seed:** 7 | **Total tasks:** 116 | **CLI-solvable:** 101 | **GUI-only:** 15 | **SR:** 87.1%
**Total steps:** 282 | **Avg steps/task:** 2.8 | **No shell scripts — all individual commands**

**Action types used:** bash (`am start`, `svc`, `mv`, `rm`, `mkdir`), sql (`sqlite3`), read-file (`cat`), write-file (`echo ... | base64 -d >`), search (`content query`)

---

## Table of Contents

- [System Settings](#system-settings)
- [App Launch](#app-launch)
- [Contacts](#contacts)
- [Markor Notes](#markor-notes)
- [Broccoli Recipes](#broccoli-recipes)
- [Simple Calendar Pro](#simple-calendar-pro)
- [Pro Expense](#pro-expense)
- [Simple SMS Messenger](#simple-sms-messenger)
- [Retro Music](#retro-music)
- [VLC Media Player](#vlc-media-player)
- [OsmAnd Maps](#osmand-maps)
- [Files](#files)
- [Camera & Media](#camera--media)
- [Clock](#clock)
- [Browser](#browser)
- [Composite (Multi-App)](#composite-multi-app)
- [Calendar Queries (IR)](#calendar-queries-ir)
- [Tasks App Queries (IR)](#tasks-app-queries-ir)
- [OpenTracks Queries (IR)](#opentracks-queries-ir)
- [Joplin Notes Queries (IR)](#joplin-notes-queries-ir)

---

## System Settings

### Task 007: SystemBluetoothTurnOn

**Status:** PASS | **Steps:** 1

**Goal:** Turn bluetooth on.

**Ground Truth Steps:**

**Step 1** (bash): Turn on Bluetooth
```
adb shell svc bluetooth enable
```
> Output: `BluetoothShellCommand: Execenable
enable: Success`

**Verifier:** Reads `settings get global bluetooth_on`. Returns 1.0 if '1'.

### Task 017: SystemBluetoothTurnOff

**Status:** PASS | **Steps:** 1

**Goal:** Turn bluetooth off.

**Ground Truth Steps:**

**Step 1** (bash): Turn off Bluetooth
```
adb shell svc bluetooth disable
```
> Output: `BluetoothShellCommand: Execdisable
disable: Success`

**Verifier:** Reads `settings get global bluetooth_on`. Returns 1.0 if '0'.

### Task 018: SystemWifiTurnOff

**Status:** PASS | **Steps:** 1

**Goal:** Turn wifi off.

**Ground Truth Steps:**

**Step 1** (bash): Turn off WiFi
```
adb shell svc wifi disable
```

**Verifier:** Reads `settings get global wifi_on`. Returns 1.0 if '0'.

### Task 019: SystemWifiTurnOn

**Status:** PASS | **Steps:** 1

**Goal:** Turn wifi on.

**Ground Truth Steps:**

**Step 1** (bash): Turn on WiFi
```
adb shell svc wifi enable
```

**Verifier:** Reads `settings get global wifi_on`. Returns 1.0 if '1' or '2'.

### Task 025: SystemBrightnessMax

**Status:** PASS | **Steps:** 1

**Goal:** Turn brightness to the max value.

**Ground Truth Steps:**

**Step 1** (bash): Set brightness to max
```
adb shell settings put system screen_brightness 255
```

**Verifier:** Reads `settings get system screen_brightness`. Returns 1.0 if '255'.

### Task 026: SystemBrightnessMin

**Status:** PASS | **Steps:** 1

**Goal:** Turn brightness to the min value.

**Ground Truth Steps:**

**Step 1** (bash): Set brightness to min
```
adb shell settings put system screen_brightness 1
```

**Verifier:** Reads `settings get system screen_brightness`. Returns 1.0 if '1'.

### Task 027: SystemCopyToClipboard

**Status:** PASS | **Steps:** 3

**Goal:** Copy the following text to the clipboard: Membership ID: ABC123

**Ground Truth Steps:**

**Step 1** (bash): Launch clipper app
```
adb shell am start ca.zgrs.clipper/.Main
```
> Output: `Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=ca.zgrs.clipper/.Main }
Warning: Activity not started, its current task has been brought to the front`

**Step 2** (bash): Wait for clipper
```
adb shell sleep 1
```

**Step 3** (bash): Copy to clipboard: Membership ID: ABC123
```
adb shell "am broadcast -a clipper.set --es text 'Membership ID: ABC123'"
```
> Output: `Broadcasting: Intent { act=clipper.set flg=0x400000 (has extras) }
Broadcast completed: result=-1, data="Text is copied into clipboard."`

**Verifier:** Reads clipboard via ADB. Fuzzy match against expected text.

### Task 041: SystemBluetoothTurnOffVerify

**Status:** PASS | **Steps:** 1

**Goal:** Turn bluetooth off.

**Ground Truth Steps:**

**Step 1** (bash): Turn off Bluetooth
```
adb shell svc bluetooth disable
```
> Output: `BluetoothShellCommand: Execdisable
disable: Success`

**Verifier:** Same as SystemBluetoothTurnOff.

### Task 042: SystemBluetoothTurnOnVerify

**Status:** PASS | **Steps:** 1

**Goal:** Turn bluetooth on.

**Ground Truth Steps:**

**Step 1** (bash): Turn on Bluetooth
```
adb shell svc bluetooth enable
```
> Output: `BluetoothShellCommand: Execenable
enable: Success`

**Verifier:** Same as SystemBluetoothTurnOn.

### Task 043: SystemBrightnessMaxVerify

**Status:** PASS | **Steps:** 1

**Goal:** Turn brightness to the max value.

**Ground Truth Steps:**

**Step 1** (bash): Set brightness to max
```
adb shell settings put system screen_brightness 255
```

**Verifier:** Same as SystemBrightnessMax.

### Task 044: SystemBrightnessMinVerify

**Status:** PASS | **Steps:** 1

**Goal:** Turn brightness to the min value.

**Ground Truth Steps:**

**Step 1** (bash): Set brightness to min
```
adb shell settings put system screen_brightness 1
```

**Verifier:** Same as SystemBrightnessMin.

### Task 045: SystemWifiTurnOffVerify

**Status:** PASS | **Steps:** 1

**Goal:** Turn wifi off.

**Ground Truth Steps:**

**Step 1** (bash): Turn off WiFi
```
adb shell svc wifi disable
```

**Verifier:** Same as SystemWifiTurnOff.

### Task 046: SystemWifiTurnOnVerify

**Status:** PASS | **Steps:** 1

**Goal:** Turn wifi on.

**Ground Truth Steps:**

**Step 1** (bash): Turn on WiFi
```
adb shell svc wifi enable
```

**Verifier:** Same as SystemWifiTurnOn.

---

## App Launch

### Task 002: OpenAppTaskEval

**Status:** PASS | **Steps:** 1

**Goal:** Open the contacts app. Clear any pop-ups that may appear by granting all permissions that are required.

**Ground Truth Steps:**

**Step 1** (bash): Open contacts
```
adb shell am start -n com.google.android.contacts/com.android.contacts.activities.PeopleActivity
```
> Output: `Starting: Intent { cmp=com.google.android.contacts/com.android.contacts.activities.PeopleActivity }`

**Verifier:** Checks current foreground package matches expected app package.

---

## Contacts

### Task 009: ContactsAddContact

**Status:** PASS | **Steps:** 4

**Goal:** Create a new contact for David Li. Their number is +16018159083.

**Ground Truth Steps:**

**Step 1** (bash): Create raw contact
```
adb shell content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s: --bind account_name:s:
```

**Step 2** (search): Query last raw_contact_id
```
adb shell "content query --uri content://com.android.contacts/raw_contacts --projection _id --sort '_id DESC' | head -1"
```
> Output: `Row: 0 _id=1`

**Step 3** (bash): Set contact name: David Li
```
adb shell "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:1 --bind mimetype:s:vnd.android.cursor.item/name --bind 'data1:s:David Li'"
```

**Step 4** (bash): Set contact number: +16018159083
```
adb shell "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:1 --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind 'data1:s:+16018159083'"
```

**Verifier:** Queries contacts content provider for name + phone number.

### Task 010: ContactsNewContactDraft

**Status:** PASS | **Steps:** 1

**Goal:** Go to the new contact screen and enter the following details: First Name: Frank, Last Name: Brown, Phone: 504-766-1791, Phone Label: Home. Do NOT hit save.

**Ground Truth Steps:**

**Step 1** (bash): Open new contact: Frank Brown
```
adb shell "am start -a android.intent.action.INSERT -t vnd.android.cursor.dir/contact --es name 'Frank Brown' --es phone '504-766-1791' --es phone_type Home"
```
> Output: `Starting: Intent { act=android.intent.action.INSERT typ=vnd.android.cursor.dir/contact (has extras) }`

**Verifier:** UI check: verifies form fields filled (name, phone, label). Fuzzy match.

---

## Markor Notes

### Task 012: MarkorDeleteAllNotes

**Status:** PASS | **Steps:** 1

**Goal:** Delete all my notes in Markor.

**Ground Truth Steps:**

**Step 1** (bash): Delete all notes in Markor
```
adb shell rm -rf /storage/emulated/0/Documents/Markor/*
```

**Verifier:** Checks Markor directory is empty.

### Task 013: MarkorDeleteNote

**Status:** PASS | **Steps:** 1

**Goal:** Delete the note in Markor named eHwd_helpful_jacket.

**Ground Truth Steps:**

**Step 1** (bash): Delete note eHwd_helpful_jacket
```
adb shell rm -f /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md
```

**Verifier:** Checks named file does NOT exist.

### Task 022: MarkorCreateFolder

**Status:** PASS | **Steps:** 1

**Goal:** Create a new folder in Markor named folder_20260401_190322.

**Ground Truth Steps:**

**Step 1** (bash): Create folder folder_20260401_190322
```
adb shell mkdir -p /storage/emulated/0/Documents/Markor/folder_20260401_190322
```

**Verifier:** Checks directory exists at expected path.

### Task 023: MarkorDeleteNewestNote

**Status:** PASS | **Steps:** 1

**Goal:** Delete the newest note in Markor.

**Ground Truth Steps:**

**Step 1** (bash): Delete newest note
```
adb shell "rm /storage/emulated/0/Documents/Markor/$(ls -t /storage/emulated/0/Documents/Markor/ | head -1)"
```

**Verifier:** Compares before/after listings. Newest file removed.

### Task 024: MarkorEditNote

**Status:** PASS | **Steps:** 1

**Goal:** Edit note_ujOeH.txt in Markor. Replace the text with The dog's vet appointment is next Monday at 11 AM.
Better late than never.
Wedding anniversary on the 30th. Make reservations!

**Ground Truth Steps:**

**Step 1** (write-file): Edit note note_ujOeH.txt
```
adb shell "echo VGhlIGRvZydzIHZldCBhcHBvaW50bWVudCBpcyBuZXh0IE1vbmRheSBhdCAxMSBBTS4KQmV0dGVyIGxhdGUgdGhhbiBuZXZlci4KV2VkZGluZyBhbm5pdmVyc2FyeSBvbiB0aGUgMzB0aC4gTWFrZSByZXNlcnZhdGlvbnMh | base64 -d > /storage/emulated/0/Documents/Markor/note_ujOeH.txt"
```

**Verifier:** Reads file, fuzzy-matches against new expected text.

### Task 051: MarkorChangeNoteContent

**Status:** PASS | **Steps:** 2

**Goal:** Update the content of eHwd_helpful_jacket.md to "6Jy8c1rihtYlKNxHddmQ" in Markor and change its name to oIdJ_clever_bear.md.

**Ground Truth Steps:**

**Step 1** (write-file): Update content of eHwd_helpful_jacket.md
```
adb shell "echo Nkp5OGMxcmlodFlsS054SGRkbVE= | base64 -d > /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md"
```

**Step 2** (bash): Rename eHwd_helpful_jacket.md to oIdJ_clever_bear.md
```
adb shell mv /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md /storage/emulated/0/Documents/Markor/oIdJ_clever_bear.md
```

**Verifier:** Verifies old file deleted, new file exists with expected content.

### Task 052: MarkorCreateNote

**Status:** PASS | **Steps:** 2

**Goal:** Create a new note in Markor named eHwd_helpful_jacket.md with the following text: Lunch meeting with Sarah at 1 PM Cafe L'amour.

**Ground Truth Steps:**

**Step 1** (bash): Ensure Markor dir exists
```
adb shell mkdir -p /storage/emulated/0/Documents/Markor
```

**Step 2** (write-file): Create note eHwd_helpful_jacket.md
```
adb shell "echo THVuY2ggbWVldGluZyB3aXRoIFNhcmFoIGF0IDEgUE0gQ2FmZSBMJ2Ftb3VyLg== | base64 -d > /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md"
```

**Verifier:** Reads file, fuzzy-matches content against expected text.

### Task 053: MarkorCreateNoteFromClipboard

**Status:** PASS | **Steps:** 4

**Goal:** Create a note in Markor named eHwd_helpful_jacket.md. Perform a paste operation in the note and save the note.

**Ground Truth Steps:**

**Step 1** (bash): Ensure Markor dir
```
adb shell mkdir -p /storage/emulated/0/Documents/Markor
```

**Step 2** (bash): Launch clipper
```
adb shell am start ca.zgrs.clipper/.Main
```
> Output: `Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=ca.zgrs.clipper/.Main }
Warning: Activity not started, its current task has been brought to the front`

**Step 3** (bash): Wait
```
adb shell sleep 1
```

**Step 4** (bash): Write clipboard to eHwd_helpful_jacket.md
```
adb shell "am broadcast -a clipper.get 2>&1 | grep -o 'data=\"[^\"]*\"' | sed 's/data=\"//;s/\"//' > /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md"
```

**Verifier:** Reads file, compares against preset clipboard text.

### Task 054: MarkorMoveNote

**Status:** PASS | **Steps:** 2

**Goal:** In Markor, move the note 2023_10_02_sharp_pig.md from PersonalJournal to DailyNotes.

**Ground Truth Steps:**

**Step 1** (bash): Create destination folder DailyNotes
```
adb shell mkdir -p /storage/emulated/0/Documents/Markor/DailyNotes
```

**Step 2** (bash): Move 2023_10_02_sharp_pig.md to DailyNotes
```
adb shell mv /storage/emulated/0/Documents/Markor/PersonalJournal/2023_10_02_sharp_pig.md /storage/emulated/0/Documents/Markor/DailyNotes/2023_10_02_sharp_pig.md
```

**Verifier:** Verifies file absent from source, present in destination.

### Task 055: MarkorTranscribeReceipt

**Status:** GUI-only | **Steps:** 0

**Goal:** Create a file in Markor, called receipt.md with the transactions from the receipt.png. Use Simple Gallery to view the receipt. Please enter transactions in csv format including the header "Date, Item, Amount".

*No CLI ground truth — requires GUI interaction.*

**Verifier:** GUI-only.

### Task 069: MarkorAddNoteHeader

**Status:** PASS | **Steps:** 3

**Goal:** Update the Markor note eHwd_helpful_jacket.md by adding the following text, along with a new blank line before the existing content: "ZhnM6Jy8c1rihtYlKNxH", and rename it to 2023_02_16_super_ant.txt.

**Ground Truth Steps:**

**Step 1** (read-file): Read existing note eHwd_helpful_jacket.md
```
adb shell "cat /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md"
```
> Output: `Monthly budget meeting pushed to Friday.`

**Step 2** (write-file): Write note with header prepended
```
adb shell "echo WmhuTTZKeThjMXJpaHRZbEtOeEgKCk1vbnRobHkgYnVkZ2V0IG1lZXRpbmcgcHVzaGVkIHRvIEZyaWRheS4K | base64 -d > /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md"
```

**Step 3** (bash): Rename eHwd_helpful_jacket.md to 2023_02_16_super_ant.txt
```
adb shell mv /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md /storage/emulated/0/Documents/Markor/2023_02_16_super_ant.txt
```

**Verifier:** Reads file. Verifies header prepended with blank line separator.

### Task 078: MarkorTranscribeVideo

**Status:** GUI-only | **Steps:** 0

**Goal:** Transcribe the contents of video clip_69__2023_01_30.mp4 by watching it in VLC player (located in Download) and writing the sequence of strings shown on each frame to the text file clip_69__2023_01_30_transcription.txt in Markor as a comma separated list. For example, if the first frame shows the text "edna" and the second frame shows the text "pineapple", then the text file should contain only the following text: "edna, pineapple".

*No CLI ground truth — requires GUI interaction.*

**Verifier:** GUI-only.

### Task 087: MarkorMergeNotes

**Status:** PASS | **Steps:** 4

**Goal:** Merge the contents of Markor notes eHwd_helpful_jacket.md, oIdJ_clever_bear.md and brave_koala_backup.md (in the same order) into a new Markor note named IizHJIQg and save it. Add a new line between the content of each note.

**Ground Truth Steps:**

**Step 1** (read-file): Read note eHwd_helpful_jacket.md
```
adb shell "cat /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md"
```
> Output: `JlgSIMEGWC5wplWfsEvB`

**Step 2** (read-file): Read note oIdJ_clever_bear.md
```
adb shell "cat /storage/emulated/0/Documents/Markor/oIdJ_clever_bear.md"
```
> Output: `LeFkv5A7eIWYvvEXefqR`

**Step 3** (read-file): Read note brave_koala_backup.md
```
adb shell "cat /storage/emulated/0/Documents/Markor/brave_koala_backup.md"
```
> Output: `eTtJQBS2v6wLEnrTy4Ek`

**Step 4** (write-file): Merge 3 notes into IizHJIQg
```
adb shell "echo SmxnU0lNRUdXQzV3cGxXZnNFdkIKCkxlRmt2NUE3ZUlXWXZ2RVhlZnFSCgplVHRKUUJTMnY2d0xFbnJUeTRFawo= | base64 -d > /storage/emulated/0/Documents/Markor/IizHJIQg"
```

**Verifier:** Reads merged file. Verifies all sources concatenated with '\n\n' separators.

---

## Broccoli Recipes

### Task 003: RecipeDeleteMultipleRecipes

**Status:** PASS | **Steps:** 2

**Goal:** Delete the following recipes from Broccoli app: Chicken Caesar Salad Wrap, Kale and Quinoa Salad, Greek Salad Pita Pockets.

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Delete 3 recipes
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"DELETE FROM recipes WHERE title='Chicken Caesar Salad Wrap' OR title='Kale and Quinoa Salad' OR title='Greek Salad Pita Pockets';\""
```

**Verifier:** Queries Broccoli SQLite DB. Verifies target recipe rows deleted, others preserved.

### Task 004: RecipeDeleteSingleRecipe

**Status:** PASS | **Steps:** 2

**Goal:** Delete the following recipes from Broccoli app: Chicken Caesar Salad Wrap.

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Delete recipe 'Chicken Caesar Salad Wrap'
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"DELETE FROM recipes WHERE title='Chicken Caesar Salad Wrap';\""
```

**Verifier:** Same as RecipeDeleteMultipleRecipes for single target.

### Task 014: RecipeDeleteDuplicateRecipes

**Status:** PASS | **Steps:** 2

**Goal:** Delete all but one of any recipes in the Broccoli app that are exact duplicates, ensuring at least one instance of each unique recipe remains

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Delete duplicate recipes
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"DELETE FROM recipes WHERE recipeId NOT IN (SELECT MIN(recipeId) FROM recipes GROUP BY title, description, servings, preparationTime, ingredients, directions);\""
```

**Verifier:** Queries Broccoli DB. Verifies duplicates removed, one instance of each unique recipe kept.

### Task 031: RecipeAddSingleRecipe

**Status:** PASS | **Steps:** 2

**Goal:** Add the following recipes into the Broccoli app:
Recipe: Chicken Caesar Salad Wrap
 description: A quick and easy meal, perfect for busy weekdays.
 servings: 6 servings
 preparationTime: 10 mins
 ingredients: as desired
 directions: Toss chopped romaine lettuce with Caesar dressing, grilled chicken strips, and Parmesan cheese. Wrap in a large tortilla. Try adding a pinch of your favorite spices for extra flavor.

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Add recipe 'Chicken Caesar Salad Wrap'
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"INSERT INTO recipes (title, description, servings, preparationTime, source, ingredients, directions, favorite, imageName) VALUES ('Chicken Caesar Salad Wrap', 'A quick and easy meal, perfect for busy weekdays.', '6 servings'...
```

**Verifier:** Queries Broccoli DB. Verifies new row with matching title, description, servings, preparationTime, ingredients, directions.

### Task 032: RecipeDeleteSingleWithRecipeWithNoise

**Status:** PASS | **Steps:** 2

**Goal:** Delete the following recipes from Broccoli app: Shrimp Avocado Salad.

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Delete recipe 'Shrimp Avocado Salad'
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"DELETE FROM recipes WHERE title='Shrimp Avocado Salad';\""
```

**Verifier:** Same — only named recipe deleted, noise recipes preserved.

### Task 056: RecipeAddMultipleRecipes

**Status:** PASS | **Steps:** 4

**Goal:** Add the following recipes into the Broccoli app:
Recipe: Chicken Caesar Salad Wrap
 description: A quick and easy meal, perfect for busy weekdays.
 servings: 6 servings
 preparationTime: 10 mins
 ingredients: as desired
 directions: Toss chopped romaine lettuce with Caesar dressing, grilled chicken strips, and Parmesan cheese. Wrap in a large tortilla. Try adding a pinch of your favorite spices for extra flavor.

Recipe: Kale and Quinoa Salad
 description: A quick and easy meal, perfect for busy weekdays.
 servings: 3-4 servings
 preparationTime: 10 mins
 ingredients: to preference
 directions: Toss chopped kale, cooked quinoa, dried cranberries, sliced almonds, and feta cheese with a lemon vinaigrette. Garnish with fresh herbs for a more vibrant taste.

Recipe: Greek Salad Pita Pockets
 description: A quick and easy meal, perfect for busy weekdays.
 servings: 6 servings
 preparationTime: 3 hrs
 ingredients: to preference
 directions: Fill pita pockets with lettuce, cucumber, tomato, feta, olives, and Greek dressing. Try adding a pinch of your favorite spices for extra flavor.

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Add recipe 'Chicken Caesar Salad Wrap'
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"INSERT INTO recipes (title, description, servings, preparationTime, source, ingredients, directions, favorite, imageName) VALUES ('Chicken Caesar Salad Wrap', 'A quick and easy meal, perfect for busy weekdays.', '6 servings'...
```

**Step 3** (sql): Add recipe 'Kale and Quinoa Salad'
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"INSERT INTO recipes (title, description, servings, preparationTime, source, ingredients, directions, favorite, imageName) VALUES ('Kale and Quinoa Salad', 'A quick and easy meal, perfect for busy weekdays.', '3-4 servings', ...
```

**Step 4** (sql): Add recipe 'Greek Salad Pita Pockets'
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"INSERT INTO recipes (title, description, servings, preparationTime, source, ingredients, directions, favorite, imageName) VALUES ('Greek Salad Pita Pockets', 'A quick and easy meal, perfect for busy weekdays.', '6 servings',...
```

**Verifier:** Queries Broccoli DB. Verifies all specified recipe rows added.

### Task 057: RecipeDeleteMultipleRecipesWithNoise

**Status:** PASS | **Steps:** 2

**Goal:** Delete the following recipes from Broccoli app: Shrimp Avocado Salad, Sweet Potato and Black Bean Tacos, Spicy Tuna Wraps.

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Delete 3 recipes
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"DELETE FROM recipes WHERE title='Shrimp Avocado Salad' OR title='Sweet Potato and Black Bean Tacos' OR title='Spicy Tuna Wraps';\""
```

**Verifier:** Same — only named recipes deleted, noise preserved.

### Task 070: RecipeDeleteDuplicateRecipes2

**Status:** PASS | **Steps:** 2

**Goal:** Delete all but one of any recipes in the Broccoli app that are exact duplicates, ensuring at least one instance of each unique recipe remains

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Delete duplicate recipes
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"DELETE FROM recipes WHERE recipeId NOT IN (SELECT MIN(recipeId) FROM recipes GROUP BY title, description, servings, preparationTime, ingredients, directions);\""
```

**Verifier:** Same as RecipeDeleteDuplicateRecipes (variant).

### Task 071: RecipeDeleteDuplicateRecipes3

**Status:** PASS | **Steps:** 2

**Goal:** Delete all but one of any recipes in the Broccoli app that are exact duplicates, ensuring at least one instance of each unique recipe remains

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Delete duplicate recipes
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"DELETE FROM recipes WHERE recipeId NOT IN (SELECT MIN(recipeId) FROM recipes GROUP BY title, description, servings, preparationTime, ingredients, directions);\""
```

**Verifier:** Same as RecipeDeleteDuplicateRecipes (variant).

### Task 080: RecipeAddMultipleRecipesFromImage

**Status:** GUI-only | **Steps:** 0

**Goal:** Add the recipes from recipes.jpg in Simple Gallery Pro to the Broccoli recipe app.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** GUI-only. Reads recipe from image, checks Broccoli DB.

### Task 081: RecipeAddMultipleRecipesFromMarkor

**Status:** PASS | **Steps:** 3

**Goal:** Add the recipes from recipes.txt in Markor to the Broccoli recipe app.

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (read-file): Read recipes file
```
adb shell cat /storage/emulated/0/Documents/Markor/recipes.txt
```

**Step 3** (sql): Insert recipes from file into DB
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"INSERT INTO recipes (title,description,servings,preparationTime,source,ingredients,directions,favorite,imageName) VALUES ('Chicken Caesar Salad Wrap','A quick and easy meal, perfect for busy weekdays.','6 servings','10 mins'...
```

**Verifier:** Reads recipes.txt, checks Broccoli DB for matching rows.

### Task 082: RecipeAddMultipleRecipesFromMarkor2

**Status:** PASS | **Steps:** 3

**Goal:** Add the recipes from recipes.txt in Markor that take 2 hrs to prepare into the Broccoli recipe app.

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (read-file): Read recipes file
```
adb shell cat /storage/emulated/0/Documents/Markor/recipes.txt
```

**Step 3** (sql): Insert recipes from file into DB
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"INSERT INTO recipes (title,description,servings,preparationTime,source,ingredients,directions,favorite,imageName) VALUES ('Pesto Pasta with Peas','An ideal recipe for experimenting with different flavors and ingredients.','8...
```

**Verifier:** Same but filters by preparationTime.

### Task 090: RecipeDeleteMultipleRecipesWithConstraint

**Status:** PASS | **Steps:** 2

**Goal:** Delete the recipes from Broccoli app that use broccoli in the directions.

**Ground Truth Steps:**

**Step 1** (bash): Stop Broccoli app
```
adb shell am force-stop com.flauschcode.broccoli
```

**Step 2** (sql): Delete recipes with broccoli in directions
```
adb shell "sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"DELETE FROM recipes WHERE directions LIKE '%broccoli%';\""
```

**Verifier:** Queries Broccoli DB for recipes matching constraint. Verifies only matching deleted.

---

## Simple Calendar Pro

### Task 005: SimpleCalendarDeleteEvents

**Status:** PASS | **Steps:** 2

**Goal:** In Simple Calendar Pro, delete all the calendar events on 2023-10-25

**Ground Truth Steps:**

**Step 1** (bash): Stop calendar app
```
adb shell am force-stop com.simplemobiletools.calendar.pro
```

**Step 2** (sql): Delete events on 2023-10-25
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"DELETE FROM events WHERE start_ts >= 1698192000 AND start_ts < 1698278400;\""
```

**Verifier:** Queries events.db. Verifies all events in date range deleted.

### Task 006: SimpleCalendarDeleteOneEvent

**Status:** PASS | **Steps:** 2

**Goal:** In Simple Calendar Pro, delete the calendar event on 2023-10-25 at 4h with the title 'Review session for Project X'

**Ground Truth Steps:**

**Step 1** (bash): Stop calendar app
```
adb shell am force-stop com.simplemobiletools.calendar.pro
```

**Step 2** (sql): Delete event 'Review session for Project X' at 2023-10-25 4h
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"DELETE FROM events WHERE title='Review session for Project X' AND start_ts=1698206400;\""
```

**Verifier:** Queries events.db. Verifies specific event (title + start_ts) deleted.

### Task 034: SimpleCalendarAddOneEventRelativeDay

**Status:** PASS | **Steps:** 3

**Goal:** In Simple Calendar Pro, create a calendar event for this Wednesday at 4h with the title 'Review session for Project X' and the description 'We will finalize business objectives.'. The event should last for 60 mins.

**Ground Truth Steps:**

**Step 1** (bash): Stop calendar app
```
adb shell am force-stop com.simplemobiletools.calendar.pro
```

**Step 2** (bash): Get current day of week and timestamp
```
adb shell "echo $(date +%u):$(date +%s)"
```
> Output: `7:1697384044`

**Step 3** (sql): Add event 'Review session for Project X' this Wednesday at 4h
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"INSERT INTO events (start_ts, end_ts, title, location, description, reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, reminder_1_type, reminder_2_type, reminder_3_type, repeat_interval, repeat_rule, repe...
```

**Verifier:** Same — target date is 'this Wednesday' etc.

### Task 035: SimpleCalendarAddOneEventTomorrow

**Status:** PASS | **Steps:** 2

**Goal:** In Simple Calendar Pro, create a calendar event for tomorrow at 4h with the title 'Review session for Project X' and the description 'We will finalize business objectives.'. The event should last for 60 mins.

**Ground Truth Steps:**

**Step 1** (bash): Stop calendar app
```
adb shell am force-stop com.simplemobiletools.calendar.pro
```

**Step 2** (sql): Add event 'Review session for Project X' tomorrow at 4h
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"INSERT INTO events (start_ts, end_ts, title, location, description, reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, reminder_1_type, reminder_2_type, reminder_3_type, repeat_interval, repeat_rule, repe...
```

**Verifier:** Same — target date is 'tomorrow'.

### Task 036: SimpleCalendarAddRepeatingEvent

**Status:** PASS | **Steps:** 2

**Goal:** In Simple Calendar Pro, create a recurring calendar event titled 'Review session for Project X' starting on 2023-10-25 at 4h. The event recurs weekly, forever, and lasts for 60 minutes each occurrence. The event description should be 'We will finalize business objectives.'.

**Ground Truth Steps:**

**Step 1** (bash): Stop calendar
```
adb shell am force-stop com.simplemobiletools.calendar.pro
```

**Step 2** (sql): Add repeating event 'Review session for Project X'
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"INSERT INTO events (start_ts, end_ts, title, location, description, reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, reminder_1_type, reminder_2_type, reminder_3_type, repeat_interval, repeat_rule, repe...
```

**Verifier:** Queries events.db. Verifies repeat_interval (604800 for weekly) and repeat_rule.

### Task 060: SimpleCalendarAddOneEventInTwoWeeks

**Status:** PASS | **Steps:** 2

**Goal:** In Simple Calendar Pro, create a calendar event in two weeks from today at 4h with the title 'Review session for Project X' and the description 'We will finalize business objectives.'. The event should last for 60 mins.

**Ground Truth Steps:**

**Step 1** (bash): Stop calendar app
```
adb shell am force-stop com.simplemobiletools.calendar.pro
```

**Step 2** (sql): Add event 'Review session for Project X' in 2 weeks at 4h
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"INSERT INTO events (start_ts, end_ts, title, location, description, reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, reminder_1_type, reminder_2_type, reminder_3_type, repeat_interval, repeat_rule, repe...
```

**Verifier:** Same — target date is '14 days from today'.

### Task 061: SimpleCalendarDeleteEventsOnRelativeDay

**Status:** PASS | **Steps:** 3

**Goal:** In Simple Calendar Pro, delete all events scheduled for this Wednesday.

**Ground Truth Steps:**

**Step 1** (bash): Stop calendar app
```
adb shell am force-stop com.simplemobiletools.calendar.pro
```

**Step 2** (bash): Get current day of week and timestamp
```
adb shell "echo $(date +%u):$(date +%s)"
```
> Output: `7:1697384044`

**Step 3** (sql): Delete events on this Wednesday
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"DELETE FROM events WHERE start_ts >= 1697587200 AND start_ts < 1697673600;\""
```

**Verifier:** Same as delete but target date is relative ('this Wednesday').

### Task 085: SimpleCalendarAddOneEvent

**Status:** PASS | **Steps:** 2

**Goal:** In Simple Calendar Pro, create a calendar event on 2023-10-25 at 4h with the title 'Review session for Project X' and the description 'We will finalize business objectives.'. The event should last for 60 mins.

**Ground Truth Steps:**

**Step 1** (bash): Stop calendar app
```
adb shell am force-stop com.simplemobiletools.calendar.pro
```

**Step 2** (sql): Add event 'Review session for Project X' on 2023-10-25
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"INSERT INTO events (start_ts, end_ts, title, location, description, reminder_1_minutes, reminder_2_minutes, reminder_3_minutes, reminder_1_type, reminder_2_type, reminder_3_type, repeat_interval, repeat_rule, repe...
```

**Verifier:** Queries events.db. Verifies new event row with matching fields.

---

## Pro Expense

### Task 011: ExpenseDeleteSingle

**Status:** PASS | **Steps:** 2

**Goal:** Delete the following expenses from pro expense: Taxi Fare.

**Ground Truth Steps:**

**Step 1** (bash): Stop expense app
```
adb shell am force-stop com.arduia.expense
```

**Step 2** (sql): Delete expense 'Taxi Fare'
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"DELETE FROM expense WHERE name='Taxi Fare';\""
```

**Verifier:** Queries accounting.db. Verifies target expense deleted, others preserved.

### Task 015: ExpenseDeleteMultiple

**Status:** PASS | **Steps:** 2

**Goal:** Delete the following expenses from pro expense: Taxi Fare, Amusement Park, Capital Gains.

**Ground Truth Steps:**

**Step 1** (bash): Stop expense app
```
adb shell am force-stop com.arduia.expense
```

**Step 2** (sql): Delete 3 expenses
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"DELETE FROM expense WHERE name='Taxi Fare' OR name='Amusement Park' OR name='Capital Gains';\""
```

**Verifier:** Same for multiple targets.

### Task 021: ExpenseAddSingle

**Status:** PASS | **Steps:** 3

**Goal:** Add the following expenses into the pro expense:
Expense: Taxi Fare
 amount_dollars: $57.47
 category_name: Transportation
 note: I may repeat this

**Ground Truth Steps:**

**Step 1** (bash): Stop expense app
```
adb shell am force-stop com.arduia.expense
```

**Step 2** (sql): Discover existing expense categories
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"SELECT DISTINCT category, name FROM expense LIMIT 10;\""
```
> Output: `6|Amusement Park
2|Capital Gains
9|Gym Membership
4|Pest Control
1|Household Items
5|Social Club Dues
5|Night Out
10|Online Courses
2|Consulting Fees
11|Medical Research`

**Step 3** (sql): Add expense 'Taxi Fare' (amount=5747, category=7)
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"INSERT INTO expense (name, amount, category, note, created_date, modified_date) VALUES ('Taxi Fare', 5747, 7, 'I may repeat this', $(date +%s)000, $(date +%s)000);\""
```

**Verifier:** Queries DB. Verifies new row: name, amount (cents), category (ID), note.

### Task 048: ExpenseAddMultiple

**Status:** PASS | **Steps:** 5

**Goal:** Add the following expenses into the pro expense:
Expense: Taxi Fare
 amount_dollars: $57.47
 category_name: Transportation
 note: I may repeat this

Expense: Amusement Park
 amount_dollars: $48.01
 category_name: Entertainment
 note: A need

Expense: Capital Gains
 amount_dollars: $284.05
 category_name: Income
 note: Paid by card

**Ground Truth Steps:**

**Step 1** (bash): Stop expense app
```
adb shell am force-stop com.arduia.expense
```

**Step 2** (sql): Discover existing expense categories
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"SELECT DISTINCT category, name FROM expense LIMIT 10;\""
```
> Output: `9|Gym Membership
4|Pest Control
1|Household Items
5|Social Club Dues
5|Night Out
10|Online Courses
2|Consulting Fees
11|Medical Research
10|Library Fees
4|Mortgage`

**Step 3** (sql): Add expense 'Taxi Fare' (amount=5747, category=7)
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"INSERT INTO expense (name, amount, category, note, created_date, modified_date) VALUES ('Taxi Fare', 5747, 7, 'I may repeat this', $(date +%s)000, $(date +%s)000);\""
```

**Step 4** (sql): Add expense 'Amusement Park' (amount=4801, category=6)
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"INSERT INTO expense (name, amount, category, note, created_date, modified_date) VALUES ('Amusement Park', 4801, 6, 'A need', $(date +%s)000, $(date +%s)000);\""
```

**Step 5** (sql): Add expense 'Capital Gains' (amount=28405, category=2)
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"INSERT INTO expense (name, amount, category, note, created_date, modified_date) VALUES ('Capital Gains', 28405, 2, 'Paid by card', $(date +%s)000, $(date +%s)000);\""
```

**Verifier:** Same for multiple expenses.

### Task 049: ExpenseDeleteDuplicates

**Status:** PASS | **Steps:** 2

**Goal:** Delete all but one of any expenses in pro expense that are exact duplicates, ensuring at least one instance of each unique expense remains.

**Ground Truth Steps:**

**Step 1** (bash): Stop expense app
```
adb shell am force-stop com.arduia.expense
```

**Step 2** (sql): Delete duplicate expenses
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"DELETE FROM expense WHERE expense_id NOT IN (SELECT MIN(expense_id) FROM expense GROUP BY name, amount, category);\""
```

**Verifier:** Queries DB. Verifies duplicates removed, one per unique tuple kept.

### Task 050: ExpenseDeleteDuplicates2

**Status:** PASS | **Steps:** 2

**Goal:** Delete all but one of any expenses in pro expense that are exact duplicates, ensuring at least one instance of each unique expense remains.

**Ground Truth Steps:**

**Step 1** (bash): Stop expense app
```
adb shell am force-stop com.arduia.expense
```

**Step 2** (sql): Delete duplicate expenses
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"DELETE FROM expense WHERE expense_id NOT IN (SELECT MIN(expense_id) FROM expense GROUP BY name, amount, category);\""
```

**Verifier:** Same (variant).

### Task 076: ExpenseAddMultipleFromGallery

**Status:** GUI-only | **Steps:** 0

**Goal:** Add the expenses from expenses.jpg in Simple Gallery Pro to pro expense.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** GUI-only.

### Task 077: ExpenseDeleteMultiple2

**Status:** PASS | **Steps:** 2

**Goal:** Delete the following expenses from pro expense: Taxi Fare, Amusement Park, Capital Gains.

**Ground Truth Steps:**

**Step 1** (bash): Stop expense app
```
adb shell am force-stop com.arduia.expense
```

**Step 2** (sql): Delete 3 expenses
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"DELETE FROM expense WHERE name='Taxi Fare' OR name='Amusement Park' OR name='Capital Gains';\""
```

**Verifier:** Same (variant).

### Task 086: ExpenseAddMultipleFromMarkor

**Status:** PASS | **Steps:** 3

**Goal:** Go through the transactions in my_expenses.txt in Markor. Log the reimbursable transactions in the pro expense.

**Ground Truth Steps:**

**Step 1** (bash): Stop expense app
```
adb shell am force-stop com.arduia.expense
```

**Step 2** (read-file): Read expenses file
```
adb shell cat /storage/emulated/0/Documents/Markor/my_expenses.txt
```

**Step 3** (sql): Insert reimbursable expenses into DB
```
adb shell "sqlite3 /data/data/com.arduia.expense/databases/accounting.db \"INSERT INTO expense (name, amount, category, note, created_date, modified_date) VALUES ('Amusement Park', 4801, 6, 'A need', strftime('%s','now')*1000, strftime('%s','now')*1000); INSERT INTO expense (name, amount, category, ...
```

**Verifier:** Reads my_expenses.txt, filters 'Reimbursable', checks DB.

---

## Simple SMS Messenger

### Task 038: SimpleSmsReply

**Status:** PASS | **Steps:** 2

**Goal:** Reply to +15260181590 with message: Better late than never. in Simple SMS Messenger

**Ground Truth Steps:**

**Step 1** (sql): Reply SMS to +15260181590
```
adb shell "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db \"INSERT INTO sms (address, body, type, date, read, seen) VALUES ('+15260181590', 'Better late than never.', 2, $(date +%s)000, 1, 1);\""
```

**Step 2** (bash): Launch SMS app
```
adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity
```
> Output: `Starting: Intent { cmp=com.simplemobiletools.smsmessenger/.activities.MainActivity }`

**Verifier:** Queries mmssms.db for outgoing SMS to number. Fuzzy body match.

### Task 039: SimpleSmsSendClipboardContent

**Status:** PASS | **Steps:** 5

**Goal:** Send a message to +15260181590 with the clipboard content in Simple SMS Messenger

**Ground Truth Steps:**

**Step 1** (bash): Launch clipper
```
adb shell am start ca.zgrs.clipper/.Main
```
> Output: `Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] cmp=ca.zgrs.clipper/.Main }
Warning: Activity not started, its current task has been brought to the front`

**Step 2** (bash): Wait for clipper
```
adb shell sleep 1
```

**Step 3** (bash): Read clipboard content
```
adb shell "am broadcast -a clipper.get 2>&1"
```
> Output: `Broadcasting: Intent { act=clipper.get flg=0x400000 }
Broadcast completed: result=-1, data="Better late than never."`

**Step 4** (sql): Send clipboard as SMS to +15260181590
```
adb shell "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db \"INSERT INTO sms (address, body, type, date, read, seen) VALUES ('+15260181590', 'Better late than never.', 2, $(date +%s)000, 1, 1);\""
```

**Step 5** (bash): Launch SMS app
```
adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity
```
> Output: `Starting: Intent { cmp=com.simplemobiletools.smsmessenger/.activities.MainActivity }`

**Verifier:** Queries DB. Verifies sent body matches clipboard content.

### Task 065: SimpleSmsReplyMostRecent

**Status:** PASS | **Steps:** 2

**Goal:** Reply to the most recent text message using Simple SMS Messenger with message: Better late than never.

**Ground Truth Steps:**

**Step 1** (sql): Reply to most recent with: Better late than never.
```
adb shell "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db \"INSERT INTO sms (address, body, type, date, read, seen) SELECT address, 'Better late than never.', 2, strftime('%s','now')*1000, 1, 1 FROM sms WHERE type=1 ORDER BY date DESC LIMIT 1;\""
```

**Step 2** (bash): Launch SMS app
```
adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity
```
> Output: `Starting: Intent { cmp=com.simplemobiletools.smsmessenger/.activities.MainActivity }`

**Verifier:** Verifies reply sent to most recent incoming message address.

### Task 066: SimpleSmsResend

**Status:** PASS | **Steps:** 2

**Goal:** Resend the message I just sent to David Li in Simple SMS Messenger

**Ground Truth Steps:**

**Step 1** (sql): Resend last sent message
```
adb shell "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db \"INSERT INTO sms (address, body, type, date, read, seen) SELECT address, body, 2, strftime('%s','now')*1000, 1, 1 FROM sms WHERE type=2 ORDER BY date DESC LIMIT 1;\""
```

**Step 2** (bash): Launch SMS app
```
adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity
```
> Output: `Starting: Intent { cmp=com.simplemobiletools.smsmessenger/.activities.MainActivity }`

**Verifier:** Verifies last sent message duplicated (count +1, body matches).

### Task 067: SimpleSmsSend

**Status:** PASS | **Steps:** 2

**Goal:** Send a text message using Simple SMS Messenger to +15260181590 with message: Better late than never.

**Ground Truth Steps:**

**Step 1** (sql): Insert SMS to +15260181590
```
adb shell "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db \"INSERT INTO sms (address, body, type, date, read, seen) VALUES ('+15260181590', 'Better late than never.', 2, $(date +%s)000, 1, 1);\""
```

**Step 2** (bash): Launch SMS app
```
adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity
```
> Output: `Starting: Intent { cmp=com.simplemobiletools.smsmessenger/.activities.MainActivity }`

**Verifier:** Same — checks sent message to target number.

### Task 068: SimpleSmsSendReceivedAddress

**Status:** PASS | **Steps:** 4

**Goal:** Text the address of the event to David Li that Sara Lopez just sent me in Simple SMS Messenger

**Ground Truth Steps:**

**Step 1** (sql): Read most recent received SMS
```
adb shell "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db \"SELECT body FROM sms WHERE type=1 ORDER BY date DESC LIMIT 1;\""
```
> Output: `6 Elm St, Birmingham, AL, 35217`

**Step 2** (search): Look up contact number for David Li
```
adb shell "content query --uri content://contacts/phones/ --projection number --where \"display_name='David Li'\" | head -1"
```
> Output: `Row: 0 number=+10181590830`

**Step 3** (sql): Send received address to David Li
```
adb shell "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db \"INSERT INTO sms (address, body, type, date, read, seen) VALUES ('+10181590830', '6 Elm St, Birmingham, AL, 35217', 2, $(date +%s)000, 1, 1);\""
```

**Step 4** (bash): Launch SMS app
```
adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity
```
> Output: `Starting: Intent { cmp=com.simplemobiletools.smsmessenger/.activities.MainActivity }`

**Verifier:** Verifies address from received SMS forwarded to correct contact.

---

## Retro Music

### Task 033: RetroPlayingQueue

**Status:** PASS | **Steps:** 6

**Goal:** Add the following songs, in order, Twilight Calling, Lost in the Echo to my playing queue in Retro music.

**Ground Truth Steps:**

**Step 1** (bash): Stop Retro Music
```
adb shell am force-stop code.name.monkey.retromusic
```

**Step 2** (sql): Ensure playing_queue table exists
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/music_playback_state.db \"CREATE TABLE IF NOT EXISTS playing_queue (id INTEGER PRIMARY KEY, title TEXT NOT NULL, data TEXT, duration INTEGER, album_id INTEGER, artist_id INTEGER);\""
```

**Step 3** (search): Query MediaStore for 'Twilight Calling'
```
adb shell "content query --uri content://media/external/audio/media --projection _id:duration:_data:album_id:artist_id --where \"title='Twilight Calling'\" | head -1"
```
> Output: `Row: 0 _id=1000000019, duration=199889, _data=/storage/emulated/0/Music/Twilight Calling.mp3, album_id=6539316500227728566, artist_id=5100418335803832042`

**Step 4** (sql): Insert 'Twilight Calling' into playing queue
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/music_playback_state.db \"INSERT INTO playing_queue (id, title, data, duration, album_id, artist_id) VALUES (1000000019, 'Twilight Calling', '/storage/emulated/0/Music/Twilight Calling.mp3', 199889, 6539316500227728566, 510041833580...
```

**Step 5** (search): Query MediaStore for 'Lost in the Echo'
```
adb shell "content query --uri content://media/external/audio/media --projection _id:duration:_data:album_id:artist_id --where \"title='Lost in the Echo'\" | head -1"
```
> Output: `Row: 0 _id=1000000020, duration=265456, _data=/storage/emulated/0/Music/Lost in the Echo.mp3, album_id=6539316500227728566, artist_id=5291092861614729230`

**Step 6** (sql): Insert 'Lost in the Echo' into playing queue
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/music_playback_state.db \"INSERT INTO playing_queue (id, title, data, duration, album_id, artist_id) VALUES (1000000020, 'Lost in the Echo', '/storage/emulated/0/Music/Lost in the Echo.mp3', 265456, 6539316500227728566, 529109286161...
```

**Verifier:** Queries music_playback_state.db playing_queue table for songs in order.

### Task 058: RetroCreatePlaylist

**Status:** PASS | **Steps:** 7

**Goal:** Create a playlist in Retro Music titled "Hip Hop Hits 332" with the following songs, in order: Twilight Calling, Lost in the Echo

**Ground Truth Steps:**

**Step 1** (bash): Stop Retro Music
```
adb shell am force-stop code.name.monkey.retromusic
```

**Step 2** (sql): Create playlist 'Hip Hop Hits 332'
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"INSERT INTO PlaylistEntity (playlist_name) VALUES ('Hip Hop Hits 332');\""
```

**Step 3** (sql): Get playlist ID
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"SELECT MAX(playlist_id) FROM PlaylistEntity;\""
```
> Output: `1`

**Step 4** (search): Query MediaStore for 'Twilight Calling'
```
adb shell "content query --uri content://media/external/audio/media --projection _id:duration:_data:album_id:album:artist_id:artist:date_modified --where \"title='Twilight Calling'\" | head -1"
```
> Output: `Row: 0 _id=1000000019, duration=199889, _data=/storage/emulated/0/Music/Twilight Calling.mp3, album_id=6539316500227728566, album=Music, artist_id=5100418335803832042, artist=Ivan, date_modified=17750`

**Step 5** (sql): Insert 'Twilight Calling' into playlist
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) VALUES (1, 1000000019, 'Twilight Calling'...
```

**Step 6** (search): Query MediaStore for 'Lost in the Echo'
```
adb shell "content query --uri content://media/external/audio/media --projection _id:duration:_data:album_id:album:artist_id:artist:date_modified --where \"title='Lost in the Echo'\" | head -1"
```
> Output: `Row: 0 _id=1000000020, duration=265456, _data=/storage/emulated/0/Music/Lost in the Echo.mp3, album_id=6539316500227728566, album=Music, artist_id=5291092861614729230, artist=Liam, date_modified=17750`

**Step 7** (sql): Insert 'Lost in the Echo' into playlist
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) VALUES (1, 1000000020, 'Lost in the Echo'...
```

**Verifier:** Queries playlist.db. Verifies PlaylistEntity + SongEntity rows.

### Task 059: RetroPlaylistDuration

**Status:** PASS | **Steps:** 6

**Goal:** Create a playlist in Retro Music titled "Hip Hop Hits 332" with a duration between 45 and 50 minutes using the provided songs.

**Ground Truth Steps:**

**Step 1** (bash): Stop Retro Music
```
adb shell am force-stop code.name.monkey.retromusic
```

**Step 2** (search): Query all songs with durations
```
adb shell "content query --uri content://media/external/audio/media --projection title:duration --sort title"
```

**Step 3** (sql): Create playlist 'Hip Hop Hits 332'
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"INSERT INTO PlaylistEntity (playlist_name) VALUES ('Hip Hop Hits 332');\""
```

**Step 4** (sql): Get playlist ID
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"SELECT MAX(playlist_id) FROM PlaylistEntity;\""
```
> Output: `1`

**Step 5** (search): Query metadata for selected songs
```
adb shell "content query --uri content://media/external/audio/media --projection _id:title:duration:_data:album_id:album:artist_id:artist:date_modified --where \"title='Echoes of Silence' OR title='Silent Dreams' OR title='Chasing Shadows' OR title='Golden Days' OR title='Lost in the Echo' OR title=...
```

**Step 6** (sql): Insert all selected songs into playlist
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) VALUES (1, 1000000019, 'Twilight Calling'...
```

**Verifier:** Same + total song duration in 45-50 min range.

### Task 083: RetroSavePlaylist

**Status:** PASS | **Steps:** 10

**Goal:** Create a playlist in Retro Music titled "Hip Hop Hits 332" with the following songs, in order: Twilight Calling, Lost in the Echo. Then export the playlist to the Downloads directory on the device.

**Ground Truth Steps:**

**Step 1** (bash): Stop Retro Music
```
adb shell am force-stop code.name.monkey.retromusic
```

**Step 2** (bash): Ensure download dirs
```
adb shell mkdir -p /storage/emulated/0/Downloads /storage/emulated/0/Download
```

**Step 3** (sql): Create playlist 'Hip Hop Hits 332'
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"INSERT INTO PlaylistEntity (playlist_name) VALUES ('Hip Hop Hits 332');\""
```

**Step 4** (sql): Get playlist ID
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"SELECT MAX(playlist_id) FROM PlaylistEntity;\""
```
> Output: `1`

**Step 5** (search): Query MediaStore for 'Twilight Calling'
```
adb shell "content query --uri content://media/external/audio/media --projection _id:duration:_data:album_id:album:artist_id:artist:date_modified --where \"title='Twilight Calling'\" | head -1"
```
> Output: `Row: 0 _id=1000000019, duration=199889, _data=/storage/emulated/0/Music/Twilight Calling.mp3, album_id=6539316500227728566, album=Music, artist_id=5100418335803832042, artist=Ivan, date_modified=17750`

**Step 6** (sql): Insert 'Twilight Calling' into playlist
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) VALUES (1, 1000000019, 'Twilight Calling'...
```

**Step 7** (write-file): Append 'Twilight Calling' path to m3u
```
adb shell "echo '/storage/emulated/0/Music/Twilight Calling.mp3' >> '/storage/emulated/0/Download/Hip Hop Hits 332.m3u'"
```

**Step 8** (search): Query MediaStore for 'Lost in the Echo'
```
adb shell "content query --uri content://media/external/audio/media --projection _id:duration:_data:album_id:album:artist_id:artist:date_modified --where \"title='Lost in the Echo'\" | head -1"
```
> Output: `Row: 0 _id=1000000020, duration=265456, _data=/storage/emulated/0/Music/Lost in the Echo.mp3, album_id=6539316500227728566, album=Music, artist_id=5291092861614729230, artist=Liam, date_modified=17750`

**Step 9** (sql): Insert 'Lost in the Echo' into playlist
```
adb shell "sqlite3 /data/data/code.name.monkey.retromusic/databases/playlist.db \"INSERT INTO SongEntity (playlist_creator_id, id, title, track_number, year, duration, data, date_modified, album_id, album_name, artist_id, artist_name, composer, album_artist) VALUES (1, 1000000020, 'Lost in the Echo'...
```

**Step 10** (write-file): Append 'Lost in the Echo' path to m3u
```
adb shell "echo '/storage/emulated/0/Music/Lost in the Echo.mp3' >> '/storage/emulated/0/Download/Hip Hop Hits 332.m3u'"
```

**Verifier:** Same + verifies .m3u file in Downloads.

---

## VLC Media Player

### Task 072: VlcCreatePlaylist

**Status:** PASS | **Steps:** 21

**Goal:** Create a playlist titled "Recipe Collection Favorites" with the following files in VLC (located in Internal Memory/VLCVideos), in order: final_moment_10_.mp4, 2023_02_14_highlight_65_.mp4, 2023_10_10_recording_9_raw.mp4, 2023_02_01_recording_73_.mp4, 2023_01_24_highlight_51_export.mp4

**Ground Truth Steps:**

**Step 1** (bash): Stop VLC
```
adb shell am force-stop org.videolan.vlc
```

**Step 2** (sql): Inspect VLC DB schema
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \".schema\" 2>&1 | head -3"
```
> Output: `Error: malformed database schema (playlist_update_nb_media_on_media_deletion) - near "FROM": syntax error`

**Step 3** (bash): Remove corrupt DB if needed
```
adb shell "rm -f /data/data/org.videolan.vlc/app_db/vlc_media.db /data/data/org.videolan.vlc/app_db/vlc_media.db-wal /data/data/org.videolan.vlc/app_db/vlc_media.db-shm"
```

**Step 4** (sql): Create DB tables
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"CREATE TABLE IF NOT EXISTS Playlist (id_playlist INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL); CREATE TABLE IF NOT EXISTS Media (id_media INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL); CREATE TABLE IF NOT EXI...
```

**Step 5** (sql): Create playlist 'Recipe Collection Favorites'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Playlist (name) VALUES ('Recipe Collection Favorites');\""
```

**Step 6** (sql): Get playlist ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_playlist) FROM Playlist;\""
```
> Output: `1`

**Step 7** (sql): Add media file 'final_moment_10_.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('final_moment_10_.mp4');\""
```

**Step 8** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `1`

**Step 9** (sql): Link media to playlist at position 0
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 1, 0);\""
```

**Step 10** (sql): Add media file '2023_02_14_highlight_65_.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('2023_02_14_highlight_65_.mp4');\""
```

**Step 11** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `2`

**Step 12** (sql): Link media to playlist at position 1
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 2, 1);\""
```

**Step 13** (sql): Add media file '2023_10_10_recording_9_raw.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('2023_10_10_recording_9_raw.mp4');\""
```

**Step 14** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `3`

**Step 15** (sql): Link media to playlist at position 2
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 3, 2);\""
```

**Step 16** (sql): Add media file '2023_02_01_recording_73_.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('2023_02_01_recording_73_.mp4');\""
```

**Step 17** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `4`

**Step 18** (sql): Link media to playlist at position 3
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 4, 3);\""
```

**Step 19** (sql): Add media file '2023_01_24_highlight_51_export.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('2023_01_24_highlight_51_export.mp4');\""
```

**Step 20** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `5`

**Step 21** (sql): Link media to playlist at position 4
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 5, 4);\""
```

**Verifier:** Queries vlc_media.db. Verifies Playlist + Media + PlaylistMediaRelation.

### Task 073: VlcCreateTwoPlaylists

**Status:** PASS | **Steps:** 38

**Goal:** Create a playlist titled "Recipe Collection Favorites" with the following files in VLC (located in Internal Memory/VLCVideos), in order: final_moment_10_.mp4, 2023_02_14_highlight_65_.mp4, 2023_10_10_recording_9_raw.mp4, 2023_02_01_recording_73_.mp4, 2023_01_24_highlight_51_export.mp4. And then, create a playlist titled "Recipe Collection Specials" with the following files in VLC, in order: scene_10_export_2023_03_26.mp4, episode_20_4K_cPVJ.mp4, episode_44_4K_edited.mp4, highlight_9_raw_2023_08_31.mp4, moment_8__edited.mp4.

**Ground Truth Steps:**

**Step 1** (bash): Stop VLC
```
adb shell am force-stop org.videolan.vlc
```

**Step 2** (sql): Inspect VLC DB schema
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \".schema\" 2>&1 | head -3"
```
> Output: `Error: malformed database schema (playlist_update_nb_media_on_media_deletion) - near "FROM": syntax error`

**Step 3** (bash): Remove corrupt DB if needed
```
adb shell "rm -f /data/data/org.videolan.vlc/app_db/vlc_media.db /data/data/org.videolan.vlc/app_db/vlc_media.db-wal /data/data/org.videolan.vlc/app_db/vlc_media.db-shm"
```

**Step 4** (sql): Create DB tables
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"CREATE TABLE IF NOT EXISTS Playlist (id_playlist INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL); CREATE TABLE IF NOT EXISTS Media (id_media INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL); CREATE TABLE IF NOT EXI...
```

**Step 5** (sql): Create playlist 'Recipe Collection Favorites'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Playlist (name) VALUES ('Recipe Collection Favorites');\""
```

**Step 6** (sql): Get playlist ID for 'Recipe Collection Favorites'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_playlist) FROM Playlist;\""
```
> Output: `1`

**Step 7** (sql): Add media file 'final_moment_10_.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('final_moment_10_.mp4');\""
```

**Step 8** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `1`

**Step 9** (sql): Link media to playlist at position 0
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 1, 0);\""
```

**Step 10** (sql): Add media file '2023_02_14_highlight_65_.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('2023_02_14_highlight_65_.mp4');\""
```

**Step 11** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `2`

**Step 12** (sql): Link media to playlist at position 1
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 2, 1);\""
```

**Step 13** (sql): Add media file '2023_10_10_recording_9_raw.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('2023_10_10_recording_9_raw.mp4');\""
```

**Step 14** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `3`

**Step 15** (sql): Link media to playlist at position 2
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 3, 2);\""
```

**Step 16** (sql): Add media file '2023_02_01_recording_73_.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('2023_02_01_recording_73_.mp4');\""
```

**Step 17** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `4`

**Step 18** (sql): Link media to playlist at position 3
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 4, 3);\""
```

**Step 19** (sql): Add media file '2023_01_24_highlight_51_export.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('2023_01_24_highlight_51_export.mp4');\""
```

**Step 20** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `5`

**Step 21** (sql): Link media to playlist at position 4
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (1, 5, 4);\""
```

**Step 22** (sql): Create playlist 'Recipe Collection Specials'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Playlist (name) VALUES ('Recipe Collection Specials');\""
```

**Step 23** (sql): Get playlist ID for 'Recipe Collection Specials'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_playlist) FROM Playlist;\""
```
> Output: `2`

**Step 24** (sql): Add media file 'scene_10_export_2023_03_26.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('scene_10_export_2023_03_26.mp4');\""
```

**Step 25** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `6`

**Step 26** (sql): Link media to playlist at position 0
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (2, 6, 0);\""
```

**Step 27** (sql): Add media file 'episode_20_4K_cPVJ.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('episode_20_4K_cPVJ.mp4');\""
```

**Step 28** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `7`

**Step 29** (sql): Link media to playlist at position 1
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (2, 7, 1);\""
```

**Step 30** (sql): Add media file 'episode_44_4K_edited.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('episode_44_4K_edited.mp4');\""
```

**Step 31** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `8`

**Step 32** (sql): Link media to playlist at position 2
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (2, 8, 2);\""
```

**Step 33** (sql): Add media file 'highlight_9_raw_2023_08_31.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('highlight_9_raw_2023_08_31.mp4');\""
```

**Step 34** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `9`

**Step 35** (sql): Link media to playlist at position 3
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (2, 9, 3);\""
```

**Step 36** (sql): Add media file 'moment_8__edited.mp4'
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO Media (filename) VALUES ('moment_8__edited.mp4');\""
```

**Step 37** (sql): Get media ID
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"SELECT MAX(id_media) FROM Media;\""
```
> Output: `10`

**Step 38** (sql): Link media to playlist at position 4
```
adb shell "sqlite3 /data/data/org.videolan.vlc/app_db/vlc_media.db \"INSERT INTO PlaylistMediaRelation (playlist_id, media_id, position) VALUES (2, 10, 4);\""
```

**Verifier:** Same for two playlists.

---

## OsmAnd Maps

### Task 074: OsmAndFavorite

**Status:** PASS | **Steps:** 2

**Goal:** Add a favorite location marker for Planken, Liechtenstein in the OsmAnd maps app.

**Ground Truth Steps:**

**Step 1** (bash): Ensure favorites dir
```
adb shell mkdir -p /data/media/0/Android/data/net.osmand/files/favorites/
```

**Step 2** (write-file): Write favorite GPX for Planken, Liechtenstein
```
adb shell "echo PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPGdweCB4bWxucz0iaHR0cDovL3d3dy50b3BvZ3JhZml4LmNvbS9HUFgvMS8xIiB2ZXJzaW9uPSIxLjEiPgogIDx3cHQgbGF0PSI0Ny4xODU4ODgyIiBsb249IjkuNTQ1MjIwMSI+CiAgICA8bmFtZT5QbGFua2VuLCBMaWVjaHRlbnN0ZWluPC9uYW1lPgogIDwvd3B0Pgo8L2dweD4= | base64 -d > /data...
```

**Verifier:** Parses favorites.gpx. Verifies <wpt> with matching name + coords (±0.001°).

### Task 088: OsmAndMarker

**Status:** PASS | **Steps:** 1

**Goal:** Add a location marker for Planken, Liechtenstein in the OsmAnd maps app.

**Ground Truth Steps:**

**Step 1** (sql): Add marker for Planken, Liechtenstein
```
adb shell "sqlite3 /data/data/net.osmand/databases/map_markers_db \"INSERT INTO map_markers (marker_id, marker_lat, marker_lon, marker_description, marker_active, marker_added, marker_visited, group_name, group_key, marker_color, marker_next_key, marker_disabled, marker_selected, marker_map_object_n...
```

**Verifier:** Queries map_markers_db for matching lat/lon + description.

### Task 089: OsmAndTrack

**Status:** PASS | **Steps:** 2

**Goal:** Save a track with waypoints Malbun, Liechtenstein, Rotenboden, Liechtenstein, Balzers, Liechtenstein in the OsmAnd maps app in the same order as listed.

**Ground Truth Steps:**

**Step 1** (bash): Ensure tracks dir
```
adb shell mkdir -p /data/media/0/Android/data/net.osmand/files/tracks/
```

**Step 2** (write-file): Write track GPX with 6 waypoints
```
adb shell "echo PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPGdweCB4bWxucz0iaHR0cDovL3d3dy50b3BvZ3JhZml4LmNvbS9HUFgvMS8xIiB2ZXJzaW9uPSIxLjEiPgogIDx0cms+CiAgICA8dHJrc2VnPgogICAgICA8dHJrcHQgbGF0PSI0Ny4xMDI2MTkxIiBsb249IjkuNjA4MzA1NyI+PG5hbWU+TWFsYnVuPC9uYW1lPjwvdHJrcHQ+CiAgICAgIDx0cmtwdCBsYXQ9...
```

**Verifier:** Parses GPX tracks. Verifies <trkpt> elements match waypoints.

---

## Files

### Task 062: FilesDeleteFile

**Status:** PASS | **Steps:** 1

**Goal:** Delete the file backup_funny_zebra.mp4 from the Android filesystem located in the Movies folder within the sdk_gphone_x86_64 storage area.

**Ground Truth Steps:**

**Step 1** (bash): Delete backup_funny_zebra.mp4 from Movies
```
adb shell rm -f /storage/emulated/0/Movies/backup_funny_zebra.mp4
```

**Verifier:** Checks file does NOT exist.

### Task 063: FilesMoveFile

**Status:** PASS | **Steps:** 1

**Goal:** Move the file first_day_school.jpg from Movies within the sdk_gphone_x86_64 storage area to the DCIM within the same sdk_gphone_x86_64 storage area in the Android filesystem.

**Ground Truth Steps:**

**Step 1** (bash): Move first_day_school.jpg from Movies to DCIM
```
adb shell mv /storage/emulated/0/Movies/first_day_school.jpg /storage/emulated/0/DCIM/first_day_school.jpg
```

**Verifier:** Verifies absent from source, present at destination.

### Task 084: SaveCopyOfReceiptTaskEval

**Status:** PASS | **Steps:** 1

**Goal:** In Simple Gallery Pro, copy receipt_4nfz_cool_guitar.jpg in DCIM and save a copy with the same name in Download

**Ground Truth Steps:**

**Step 1** (bash): Copy receipt_4nfz_cool_guitar.jpg from DCIM to Download
```
adb shell cp /storage/emulated/0/DCIM/receipt_4nfz_cool_guitar.jpg /storage/emulated/0/Download/receipt_4nfz_cool_guitar.jpg
```

**Verifier:** Checks copy exists in Download directory.

---

## Camera & Media

### Task 000: AudioRecorderRecordAudio

**Status:** GUI-only | **Steps:** 0

**Goal:** Record an audio clip using Audio Recorder app and save it.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** Checks AUDIORECORDER_DATA directory for exactly 1 new audio file with size > 0.

### Task 008: CameraTakePhoto

**Status:** GUI-only | **Steps:** 0

**Goal:** Take one photo.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** Compares DCIM/Camera listing before/after. 1.0 if 1 new file.

### Task 028: AudioRecorderRecordAudioWithFileName

**Status:** GUI-only | **Steps:** 0

**Goal:** Record an audio clip and save it with name "discussion_2023_01_25.m4a" using Audio Recorder app.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** Checks if file with given name (+ .m4a ext) exists in AUDIORECORDER_DATA.

### Task 037: SimpleDrawProCreateDrawing

**Status:** GUI-only | **Steps:** 0

**Goal:** Create a new drawing in Simple Draw Pro. Name it dolor_backup_funny_zebra.jpg. Save it in the Pictures folder within the sdk_gphone_x86_64 storage area.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** GUI-only.

### Task 047: CameraTakeVideo

**Status:** GUI-only | **Steps:** 0

**Goal:** Take one video.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** Compares Movies listing before/after. 1.0 if 1 new file.

---

## Clock

### Task 001: ClockStopWatchRunning

**Status:** GUI-only | **Steps:** 0

**Goal:** Run the stopwatch.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** UI check: verifies 'Pause' and 'Lap' buttons visible on DeskClock.

### Task 020: ClockTimerEntry

**Status:** GUI-only | **Steps:** 0

**Goal:** Create a timer with 10 hours, 9 minutes, and 25 seconds. Do not start the timer.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** UI check: verifies timer display shows exact format on DeskClock.

### Task 040: ClockStopWatchPausedVerify

**Status:** GUI-only | **Steps:** 0

**Goal:** Pause the stopwatch.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** UI check: verifies 'Start' button visible on DeskClock.

---

## Browser

### Task 029: BrowserDraw

**Status:** GUI-only | **Steps:** 0

**Goal:** Open the file task.html in Downloads in the file manager; when prompted open it with Chrome. Then create a drawing using the three colors shown at the top and hit submit.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** GUI-only.

### Task 030: BrowserMaze

**Status:** GUI-only | **Steps:** 0

**Goal:** Open the file task.html in Downloads in the file manager; when prompted open it with Chrome. Then navigate the X to the bottom-right cell, by using the direction buttons.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** GUI-only.

### Task 075: BrowserMultiply

**Status:** GUI-only | **Steps:** 0

**Goal:** Open the file task.html in Downloads in the file manager; when prompted open it with Chrome. Then click the button 5 times, remember the numbers displayed, and enter their product in the form.

*No CLI ground truth — requires GUI interaction.*

**Verifier:** GUI-only.

---

## Composite (Multi-App)

### Task 016: TurnOnWifiAndOpenApp

**Status:** PASS | **Steps:** 2

**Goal:** Turn on Wifi, then open the contacts app

**Ground Truth Steps:**

**Step 1** (bash): Turn on WiFi
```
adb shell svc wifi enable
```

**Step 2** (bash): Open contacts
```
adb shell am start -n com.google.android.contacts/com.android.contacts.activities.PeopleActivity
```
> Output: `Starting: Intent { cmp=com.google.android.contacts/com.android.contacts.activities.PeopleActivity }`

**Verifier:** Composite: averages (wifi_on + correct_app_foreground) / 2.

### Task 064: TurnOffWifiAndTurnOnBluetooth

**Status:** PASS | **Steps:** 2

**Goal:** Turn off WiFi, then enable bluetooth

**Ground Truth Steps:**

**Step 1** (bash): Turn off WiFi
```
adb shell svc wifi disable
```

**Step 2** (bash): Turn on Bluetooth
```
adb shell svc bluetooth enable
```
> Output: `BluetoothShellCommand: Execenable
enable: Success`

**Verifier:** Composite: averages (wifi_off + bluetooth_on) / 2.

### Task 079: MarkorCreateNoteAndSms

**Status:** PASS | **Steps:** 4

**Goal:** Create a new note in Markor named eHwd_helpful_jacket.md with the following text: Lunch meeting with Sarah at 1 PM Cafe L'amour.. Share the entire content of the note with the phone number +11661318609 via SMS using Simple SMS Messenger

**Ground Truth Steps:**

**Step 1** (bash): Ensure Markor dir
```
adb shell mkdir -p /storage/emulated/0/Documents/Markor
```

**Step 2** (write-file): Create note eHwd_helpful_jacket.md
```
adb shell "echo THVuY2ggbWVldGluZyB3aXRoIFNhcmFoIGF0IDEgUE0gQ2FmZSBMJ2Ftb3VyLg== | base64 -d > /storage/emulated/0/Documents/Markor/eHwd_helpful_jacket.md"
```

**Step 3** (sql): Send SMS to +11661318609
```
adb shell "sqlite3 /data/data/com.android.providers.telephony/databases/mmssms.db \"INSERT INTO sms (address, body, type, date, read, seen) VALUES ('+11661318609', 'Lunch meeting with Sarah at 1 PM Cafe L''amour.', 2, $(date +%s)000, 1, 1);\""
```

**Step 4** (bash): Launch SMS app
```
adb shell am start -n com.simplemobiletools.smsmessenger/.activities.MainActivity
```
> Output: `Starting: Intent { cmp=com.simplemobiletools.smsmessenger/.activities.MainActivity }`

**Verifier:** Composite: averages (markor_create + sms_send) / 2.

---

## Calendar Queries (IR)

### Task 091: SimpleCalendarEventsOnDate

**Status:** PASS | **Steps:** 2

**Goal:** What events do I have Tuesday in Simple Calendar Pro? Answer with the titles only. If there are multiple titles, format your answer as a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query events on October 17 2023
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title FROM events WHERE start_ts >= 1697500800 AND start_ts < 1697587200 ORDER BY start_ts;\""
```
> Output: `Family reunion`

**Step 2** (bash): Answer: Family reunion
```
answer(content='Family reunion')
```

**Verifier:** Queries events.db for date. Compares agent answer titles.

### Task 092: SimpleCalendarNextEvent

**Status:** PASS | **Steps:** 2

**Goal:** What is my next upcoming event in Simple Calendar Pro? Answer with the title only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query next upcoming event (using device clock for current time)
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title FROM events WHERE start_ts > $(date +%s) ORDER BY start_ts ASC LIMIT 1;\""
```
> Output: `Movie night`

**Step 2** (bash): Answer: Movie night
```
answer(content='Movie night')
```

**Verifier:** Queries events.db for next event after now. Compares title.

### Task 093: SimpleCalendarEventOnDateAtTime

**Status:** PASS | **Steps:** 2

**Goal:** What is on my schedule for Friday at 10:00am in Simple Calendar Pro? Answer with the titles only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query event at 10:00
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title FROM events WHERE start_ts <= 1697796000 AND end_ts > 1697796000;\""
```
> Output: `Sports game`

**Step 2** (bash): Answer: Sports game
```
answer(content='Sports game')
```

**Verifier:** Queries events.db for event at timestamp. Compares title.

### Task 094: SimpleCalendarAnyEventsOnDate

**Status:** PASS | **Steps:** 2

**Goal:** Do I have any events October 20 in Simple Calendar Pro? Answer with the titles only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query events on October 20 2023
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title FROM events WHERE start_ts >= 1697760000 AND start_ts < 1697846400 ORDER BY start_ts;\""
```
> Output: `Sports game
1-on-1 with Manager
Quarterly review`

**Step 2** (bash): Answer: Sports game, 1-on-1 with Manager, Quarterly review
```
answer(content='Sports game, 1-on-1 with Manager, Quarterly review')
```

**Verifier:** Same as EventsOnDate.

### Task 095: SimpleCalendarNextMeetingWithPerson

**Status:** PASS | **Steps:** 2

**Goal:** When is my next meeting with Emily in Simple Calendar Pro? Express your answer in the format <month name> <day> <year> <hour in 24-hour format>:<minutes>.

**Ground Truth Steps:**

**Step 1** (sql): Query next meeting with Emily (using device clock for current time)
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT start_ts FROM events WHERE title LIKE '%Emily%' AND start_ts > $(date +%s) ORDER BY start_ts ASC LIMIT 1;\""
```
> Output: `1697500800`

**Step 2** (bash): Answer: October 17 2023 00:00
```
answer(content='October 17 2023 00:00')
```

**Verifier:** Queries for next event with person name. Compares date string.

### Task 096: SimpleCalendarLocationOfEvent

**Status:** PASS | **Steps:** 2

**Goal:** What is the location of my Coding challenge event in Simple Calendar Pro? Answer with the location only.

**Ground Truth Steps:**

**Step 1** (sql): Query location of 'Coding challenge'
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT location FROM events WHERE title LIKE '%Coding challenge%' LIMIT 1;\""
```
> Output: `The Coffee Bean`

**Step 2** (bash): Answer: The Coffee Bean
```
answer(content='The Coffee Bean')
```

**Verifier:** Queries event location. Compares answer.

### Task 097: SimpleCalendarEventsInNextWeek

**Status:** PASS | **Steps:** 3

**Goal:** What events do I have in the next week in Simple Calendar Pro? Assume the week starts from Monday. Answer with the titles only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (bash): Get current day of week and timestamp
```
adb shell "echo $(date +%u):$(date +%s)"
```
> Output: `7:1697384044`

**Step 2** (sql): Query events in next week
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title FROM events WHERE start_ts >= 1697414400 AND start_ts < 1698019200 ORDER BY start_ts;\""
```
> Output: `Dinner with friends
Coffee with CEO`

**Step 3** (bash): Answer: Dinner with friends, Coffee with CEO
```
answer(content='Dinner with friends, Coffee with CEO')
```

**Verifier:** Queries events in Mon-Sun range. Compares title list.

### Task 098: SimpleCalendarFirstEventAfterStartTime

**Status:** PASS | **Steps:** 2

**Goal:** What is my first event after 10:30am Friday in Simple Calendar Pro? Answer with the titles only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query first event at or after 10:30
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title FROM events WHERE start_ts >= 1697797800 ORDER BY start_ts ASC LIMIT 1;\""
```
> Output: `Training Session`

**Step 2** (bash): Answer: Training Session
```
answer(content='Training Session')
```

**Verifier:** Queries first event after timestamp. Compares title.

### Task 099: SimpleCalendarEventsInTimeRange

**Status:** PASS | **Steps:** 2

**Goal:** Do I have any events between 12pm and 8pm Tuesday in Simple Calendar Pro? Answer with the titles only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query events between 12:00 and 20:00
```
adb shell "sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title FROM events WHERE start_ts >= 1697544000 AND start_ts < 1697572800 ORDER BY start_ts;\""
```
> Output: `Cooking Class`

**Step 2** (bash): Answer: Cooking Class
```
answer(content='Cooking Class')
```

**Verifier:** Queries events in time range. Compares titles.

---

## Tasks App Queries (IR)

### Task 100: TasksDueOnDate

**Status:** PASS | **Steps:** 2

**Goal:** What tasks do I have due October 20 2023 in Tasks app? Answer with the titles only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query tasks due on October 20 2023
```
adb shell "sqlite3 /data/data/org.tasks/databases/database \"SELECT title FROM tasks WHERE dueDate >= 1697760000000 AND dueDate < 1697846400000 AND completed = 0;\""
```
> Output: `Review code changes
Call client for follow-up
Update website content`

**Step 2** (bash): Answer: Review code changes, Call client for follow-up, Update website content
```
answer(content='Review code changes, Call client for follow-up, Update website content')
```

**Verifier:** Queries Tasks DB for date range, completed=0. Compares titles.

### Task 101: TasksHighPriorityTasks

**Status:** PASS | **Steps:** 2

**Goal:** What are my high priority tasks in Tasks app? Answer with the titles only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query high priority tasks
```
adb shell "sqlite3 /data/data/org.tasks/databases/database \"SELECT title FROM tasks WHERE importance = 0 AND completed = 0;\""
```
> Output: `Call client for follow-up`

**Step 2** (bash): Answer: Call client for follow-up
```
answer(content='Call client for follow-up')
```

**Verifier:** Queries importance=0, completed=0. Compares titles.

### Task 102: TasksHighPriorityTasksDueOnDate

**Status:** PASS | **Steps:** 2

**Goal:** Which tasks with high priority are due Friday in the Tasks app? Answer with the title only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query high priority tasks due October 20
```
adb shell "sqlite3 /data/data/org.tasks/databases/database \"SELECT title FROM tasks WHERE importance = 0 AND dueDate >= 1697760000000 AND dueDate < 1697846400000 AND completed = 0;\""
```
> Output: `Marketing Campaign Launch`

**Step 2** (bash): Answer: Marketing Campaign Launch
```
answer(content='Marketing Campaign Launch')
```

**Verifier:** Combines priority + date filter. Compares titles.

### Task 103: TasksDueNextWeek

**Status:** PASS | **Steps:** 2

**Goal:** How many tasks do I have due next week in Tasks app? Assume the week starts from Monday. Express your answer as a single integer.

**Ground Truth Steps:**

**Step 1** (sql): Count tasks due next week
```
adb shell "sqlite3 /data/data/org.tasks/databases/database \"SELECT COUNT(*) FROM tasks WHERE dueDate >= 1697414400000 AND dueDate < 1698019200000 AND completed = 0;\""
```
> Output: `6`

**Step 2** (bash): Answer: 6
```
answer(content='6')
```

**Verifier:** Counts tasks in week range. Compares number.

### Task 104: TasksCompletedTasksForDate

**Status:** PASS | **Steps:** 2

**Goal:** Which tasks have I completed for October 16 in Tasks app? Answer with the titles only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query completed tasks for October 16
```
adb shell "sqlite3 /data/data/org.tasks/databases/database \"SELECT title FROM tasks WHERE dueDate >= 1697414400000 AND dueDate < 1697500800000 AND completed > 0;\""
```
> Output: `Research market trends
Review code changes
Organize movie night`

**Step 2** (bash): Answer: Research market trends, Review code changes, Organize movie night
```
answer(content='Research market trends, Review code changes, Organize movie night')
```

**Verifier:** Queries completed>0 in range. Compares titles.

### Task 105: TasksIncompleteTasksOnDate

**Status:** PASS | **Steps:** 2

**Goal:** What incomplete tasks do I have still have to do by October 25 in Tasks app? Answer with the titles only. If there are multiples titles, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query incomplete tasks by October 25
```
adb shell "sqlite3 /data/data/org.tasks/databases/database \"SELECT title FROM tasks WHERE dueDate < 1698278400000 AND completed = 0 AND dueDate > 0;\""
```
> Output: `Review code changes
Research market trends
Book flights for conference`

**Step 2** (bash): Answer: Review code changes, Research market trends, Book flights for conference
```
answer(content='Review code changes, Research market trends, Book flights for conference')
```

**Verifier:** Queries completed=0, dueDate before cutoff. Compares titles.

---

## OpenTracks Queries (IR)

### Task 106: SportsTrackerActivitiesOnDate

**Status:** PASS | **Steps:** 2

**Goal:** What activities did I do October 03 in the OpenTracks app? Answer with the activity type only. If there are multiple types, format your answer in a comma separated list.

**Ground Truth Steps:**

**Step 1** (sql): Query activities on October 03 2023
```
adb shell "sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db \"SELECT DISTINCT category FROM tracks WHERE starttime >= 1696291200000 AND starttime < 1696377600000;\""
```
> Output: `snow boarding
inline skating`

**Step 2** (bash): Answer: snow boarding, inline skating
```
answer(content='snow boarding, inline skating')
```

**Verifier:** Queries OpenTracks DB DISTINCT category for date. Compares answer.

### Task 107: SportsTrackerActivitiesCountForWeek

**Status:** PASS | **Steps:** 2

**Goal:** How many swimming activities did I do this week in the OpenTracks app? Assume the week starts from Monday. Express your answer as a single integer.

**Ground Truth Steps:**

**Step 1** (sql): Count swimming activities this week
```
adb shell "sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db \"SELECT COUNT(*) FROM tracks WHERE category = 'swimming' AND starttime >= 1696809600000 AND starttime < 1697414400000;\""
```
> Output: `2`

**Step 2** (bash): Answer: 2
```
answer(content='2')
```

**Verifier:** Counts tracks for category in week. Compares number.

### Task 108: SportsTrackerActivityDuration

**Status:** PASS | **Steps:** 2

**Goal:** How long was my swimming activity October 10 2023 in the OpenTracks app? Express your answer in minutes as a single integer.

**Ground Truth Steps:**

**Step 1** (sql): Query swimming duration on October 10
```
adb shell "sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db \"SELECT totaltime / 60000 FROM tracks WHERE category = 'swimming' AND starttime >= 1696896000000 AND starttime < 1696982400000 LIMIT 1;\""
```
> Output: `135`

**Step 2** (bash): Answer: 135
```
answer(content='135')
```

**Verifier:** Gets totaltime/60000 for activity. Compares minutes.

### Task 109: SportsTrackerLongestDistanceActivity

**Status:** PASS | **Steps:** 2

**Goal:** What was the longest distance covered in a swimming activity in the OpenTracks app this week? Assume the week starts from Monday. Express your answer as a single number in meters rounded to the nearest integer.

**Ground Truth Steps:**

**Step 1** (sql): Query longest swimming distance this week
```
adb shell "sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db \"SELECT CAST(MAX(totaldistance) AS INTEGER) FROM tracks WHERE category = 'swimming' AND starttime >= 1696809600000 AND starttime < 1697414400000;\""
```
> Output: `306`

**Step 2** (bash): Answer: 306
```
answer(content='306')
```

**Verifier:** Gets MAX(totaldistance) for category. Compares meters.

### Task 110: SportsTrackerTotalDurationForCategoryThisWeek

**Status:** PASS | **Steps:** 2

**Goal:** What was the total duration of swimming activities in the OpenTracks app this week? Assume the week starts from Monday. Express your answer in minutes as a single integer.

**Ground Truth Steps:**

**Step 1** (sql): Query total swimming duration this week
```
adb shell "sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db \"SELECT SUM(totaltime) / 60000 FROM tracks WHERE category = 'swimming' AND starttime >= 1696809600000 AND starttime < 1697414400000;\""
```
> Output: `75`

**Step 2** (bash): Answer: 75
```
answer(content='75')
```

**Verifier:** Gets SUM(totaltime)/60000. Compares minutes.

### Task 111: SportsTrackerTotalDistanceForCategoryOverInterval

**Status:** PASS | **Steps:** 2

**Goal:** What was the total distance covered for skiing activities in the OpenTracks app from October 06 2023 to October 11 2023? Express your answer as a single number in meters rounded to the nearest integer.

**Ground Truth Steps:**

**Step 1** (sql): Query total skiing distance
```
adb shell "sqlite3 /data/data/de.dennisguse.opentracks/databases/database.db \"SELECT CAST(SUM(totaldistance) AS INTEGER) FROM tracks WHERE category = 'skiing' AND starttime >= 1696550400000 AND starttime < 1697068800000;\""
```
> Output: `3299`

**Step 2** (bash): Answer: 3299
```
answer(content='3299')
```

**Verifier:** Gets SUM(totaldistance). Compares meters.

---

## Joplin Notes Queries (IR)

### Task 112: NotesRecipeIngredientCount

**Status:** PASS | **Steps:** 2

**Goal:** What quantity of goji berries do I need for the recipe 'Beef Stew' in the Joplin app? Express your answer in the format <amount> <unit> where both the amount and unit exactly match the format in the recipe.

**Ground Truth Steps:**

**Step 1** (sql): Query goji berries in recipe 'Beef Stew'
```
adb shell "sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite \"SELECT body FROM notes WHERE title = 'Beef Stew' LIMIT 1;\""
```

**Step 2** (bash): Answer: 1/2 cup
```
answer(content='1/2 cup')
```

**Verifier:** Queries Joplin note body, parses ingredient. Compares answer.

### Task 113: NotesMeetingAttendeeCount

**Status:** PASS | **Steps:** 2

**Goal:** How many attendees were present in the meeting titled 'Financial Performance Analysis' in the Joplin app? Express your answer as just a single number.

**Ground Truth Steps:**

**Step 1** (sql): Query attendees for 'Financial Performance Analysis'
```
adb shell "sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite \"SELECT body FROM notes WHERE title = 'Financial Performance Analysis' LIMIT 1;\""
```
> Output: `Meeting Agenda:
- Review project status
- Plan upcoming tasks
- Discuss resource allocation
- 25 individuals attended`

**Step 2** (bash): Answer: 25
```
answer(content='25')
```

**Verifier:** Queries Joplin note, parses attendee count. Compares number.

### Task 114: NotesIsTodo

**Status:** PASS | **Steps:** 2

**Goal:** Is the note titled 'Research Notes' in the Joplin app marked as a todo item? Respond with either 'True' if it is a todo or 'False' if not.

**Ground Truth Steps:**

**Step 1** (sql): Check if 'Research Notes' is a todo
```
adb shell "sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite \"SELECT is_todo FROM notes WHERE title = 'Research Notes' LIMIT 1;\""
```
> Output: `1`

**Step 2** (bash): Answer: True
```
answer(content='True')
```

**Verifier:** Queries is_todo field. Compares 'True'/'False'.

### Task 115: NotesTodoItemCount

**Status:** PASS | **Steps:** 2

**Goal:** How many to-dos do I have in the 'Ideas' folder in the Joplin app? Express your answer as just a single number.

**Ground Truth Steps:**

**Step 1** (sql): Count todos in 'Ideas' folder
```
adb shell "sqlite3 /data/data/net.cozic.joplin/databases/joplin.sqlite \"SELECT COUNT(*) FROM notes WHERE is_todo = 1 AND parent_id = (SELECT id FROM folders WHERE title = 'Ideas');\""
```
> Output: `3`

**Step 2** (bash): Answer: 3
```
answer(content='3')
```

**Verifier:** Counts is_todo=1 in folder. Compares number.

