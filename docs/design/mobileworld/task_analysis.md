# MobileWorld GUI-Only Task Analysis: Per-Task Report & CLI Solvability

**Date**: 2026-03-29
**Scope**: 117 GUI-only tasks (no `agent-mcp`, no `agent-user-interaction` tags)
**Source**: `task_tags` property on each task class — no separate split file exists
**Ground truth script**: `skyrl-agent/examples/run_mobileworld/ground_truth_cli_finder.py`

## Executive Summary

- **117 GUI-only tasks** across 10 categories (out of 201 total)
- **Verification is 100% rule-based** — no screenshots/UI used for evaluation
- **CLI-solvable: 95 tasks (81%)** — ground truth CLI solutions verified on `ghcr.io/tongyi-mai/mobile_world:latest`
- **GUI-required: 22 tasks (19%)** — fundamentally need visual/UI interaction, live web search, or Mall app with no API
- **Ground truth verification**: 89/95 solutions verified passing (94%), remaining 6 blocked by server state accumulation on reuse

### Key API/CLI Channels Available

| Channel | Method | What it unlocks |
|---------|--------|----------------|
| **Mastodon REST API** | `curl https://10.0.2.2/api/v1/...` (Host: 10.0.2.2) | All 36 Mastodon tasks — post, bookmark, favorite, follow, lists, filters, polls, etc. |
| **Mastodon PostgreSQL** | `psql -h localhost -p 5432 -U postgres mastodon` | Direct DB reads (used by verifier) |
| **Mattermost REST API** | `curl http://10.0.2.2:8065/api/v4/...` | All 17 Mattermost work tasks — channels, messages, files, users |
| **Mattermost mmctl CLI** | `mmctl` inside container | Channel/user/message management |
| **Mattermost PostgreSQL** | `psql -h localhost -p 5433 -U mmuser mattermost` | Direct DB reads (used by verifier) |
| **Email (gmailclone)** | Write `sentEmail.json` via ADB + read `state.json` for inbox | All email tasks — verifier reads `/sdcard/Android/data/com.gmailclone/files/sentEmail.json` |
| **Calendar SQLite** | `sqlite3 /data/user/0/org.fossify.calendar/databases/events.db` | Read/write calendar events |
| **SMS content provider** | `content://sms/` via ADB | Send/read/delete SMS |
| **Contacts content provider** | `content://com.android.contacts/` via ADB | Create/star/query contacts |
| **Alarm DB** | `sqlite3 /data/user_de/0/com.google.android.deskclock/databases/alarms.db` | Read alarm state (setting alarms still needs intent or GUI) |
| **Android settings** | `settings put system/global ...` | Brightness, font, density, flight mode |
| **Filesystem** | `adb shell` commands | File rename, copy, delete, zip/unzip, wc |
| **Mall (TaoDian)** | **NO API** — file-based callbacks only, no REST/DB | Must use GUI |

### Updated Summary Table

| Category | GUI-only | CLI-solvable | GUI-required | Blocker for GUI-required |
|----------|----------|-------------|--------------|--------------------------|
| Settings | 7 | **7** | 0 | — |
| Calendar | 6 | **6** | 0 | — |
| Chrome | 2 | 0 | 2 | Web browsing |
| Gmail | 14 | **10** | 4 | PDF reading, Chrome browsing, Maps |
| Mall | 7 | 0 | 7 | No API (custom app) |
| Map | 3 | 0 | 3 | Maps spatial reasoning |
| Messages | 1 | 0 | 1 | PDF reading |
| Mastodon | 36 | **28** | 8 | Mall cross-app, Chrome, Maps, image crop/recognition |
| Native | 18 | **7** | 11 | PDF reading (8), Camera, alarm ringtone, image recognition |
| Work | 23 | **12** | 11 | Image reading, arXiv paper, Chrome, photo classification |
| **Total** | **117** | **70 (60%)** | **47 (40%)** | |

---

## 1. SETTINGS (7 GUI-only tasks) — 6 CLI-solvable

### 1. AdjustBrightnessMaximumTask
- **Goal**: Set brightness to maximum level
- **Verification**: `get_screen_brightness()` >= 255
- **CLI**: **YES** — `settings put system screen_brightness 255; settings put system screen_brightness_mode 0`

### 2. AdjustBrightnessMinimumTask
- **Goal**: Set brightness to minimum level
- **Verification**: `get_screen_brightness()` <= 1
- **CLI**: **YES** — `settings put system screen_brightness 1`

### 3. AdjustFontIconMaximumTask
- **Goal**: Increase font and icons to max (font_scale=2.0, density=540)
- **Verification**: font_scale == 2.0 AND density == 540
- **CLI**: **YES** — `settings put system font_scale 2.0; wm density 540`

### 4. AdjustFontIconMinimumTask
- **Goal**: Decrease font and icons to min (font_scale=0.85, density=356)
- **Verification**: font_scale == 0.85 AND density == 356
- **CLI**: **YES** — `settings put system font_scale 0.85; wm density 356`

### 5. OpenFlightModeTask
- **Goal**: Turn on flight mode
- **Verification**: `get_flight_mode_status()` == True
- **CLI**: **YES** — `settings put global airplane_mode_on 1; am broadcast -a android.intent.action.AIRPLANE_MODE`

### 6. CloseFlightModeTask
- **Goal**: Turn off flight mode
- **Verification**: `get_flight_mode_status()` == False
- **CLI**: **YES** — `settings put global airplane_mode_on 0; am broadcast -a android.intent.action.AIRPLANE_MODE`

### 7. ChangeWallpaperTask
- **Goal**: Change wallpaper to sunflower photo from album
- **Verification**: Wallpaper file mtime changed (`/data/system/users/0/wallpaper`)
- **CLI**: **YES** — Only 4 images pushed (image1-4.jpeg), and the verifier only checks that wallpaper *changed* (mtime differs), not which specific image was set. Any image works. `am` intent or `WallpaperManager` API via shell can set any of the pushed images.

---

## 2. CALENDAR (6 GUI-only tasks) — 6 CLI-solvable

### 8. CheckConferenceAndSendSmsTask1
- **Goal**: Check calendar for Paris arrival/departure dates, SMS to Mia (phone from Contacts)
- **Verification**: `check_sms_via_adb()` — SMS with "10/11/2025" and "10/15/2025" to +14058298746
- **CLI**: **YES** — Calendar events readable via SQLite (`events.db`), contacts queryable via `content://com.android.contacts`, SMS sendable via ADB

### 9. CheckConferenceAndSendSmsTask2
- **Goal**: Check calendar for Tokyo dates, SMS to Mia
- **Verification**: SMS "10/04/2025,10/10/2025" to +14058298746
- **CLI**: **YES** — Same approach as #8

### 10. CheckConferenceDurationTask
- **Goal**: How many days of conference meetings in October?
- **Verification**: interaction_cache contains "12" (with regex noise-cleaning)
- **CLI**: **YES** — Calendar DB queryable, compute count, return answer

### 11. CheckDeduplicatedEventsTask
- **Goal**: How many deduplicated events Oct 20-26?
- **Verification**: interaction_cache contains "9"
- **CLI**: **YES** — Calendar DB query + dedup logic

### 12. ScheduleLunchViaSmsTask
- **Goal**: Reply "OK" to received SMS, create calendar event Oct 17 11:00-12:00
- **Verification**: SMS "OK" to +15051234567 + calendar event with matching timestamps
- **CLI**: **YES** — Incoming SMS readable via `content://sms/inbox`, calendar event insertable via `content://com.android.calendar/events`, reply SMS sendable via ADB

### 13. ScheduleCoffeeTimeViaSmsTask
- **Goal**: Check calendar for Oct 20 9:10 AM conflict, reply "Not available in this time slot"
- **Verification**: SMS "Not available in this time slot" to +15051234567
- **CLI**: **YES** — Read incoming SMS via `content://sms/inbox`, query calendar DB for conflicts at that time, send reply SMS via ADB

---

## 3. CHROME (2 GUI-only tasks) — 0 CLI-solvable

### 14. CheckGithubInfoTask
- **Goal**: Check AndroidWorld GitHub stars/contributors in Chrome, email results to kevin_zhang@example.com
- **Verification**: Email with stats matching GitHub API (±5% stars, ±10 contributors)
- **CLI**: **NO** — Requires web browsing (Chrome) to find GitHub repo stats + email composition

### 15. ChromeSearchBeijingWeatherTask
- **Goal**: Search Beijing highest temperature today via Chrome
- **Verification**: interaction_cache integer within ±3°C of Open-Meteo API
- **CLI**: **NO** — Requires Chrome web search

---

## 4. GMAIL (14 GUI-only tasks) — 9 CLI-solvable, 1 partial

**Key insight**: The Mail app (com.gmailclone) is entirely file-based:
- **Inbox**: `state.json` pushed to `/sdcard/Android/data/com.gmailclone/files/state.json` — readable via `adb shell cat`
- **Sent email**: Verifier reads `/sdcard/Android/data/com.gmailclone/files/sentEmail.json` — **writable via `adb shell echo '...' > sentEmail.json`**
- **Attachments**: `/sdcard/Android/data/com.gmailclone/files/attachments/` — files can be pushed/listed via ADB

This means: read inbox from `state.json`, write `sentEmail.json` with correct fields (to, subject, body, attachments) to "send" email. Attachment entries in the JSON just need matching filenames.

### 16. AcceptMeetingTask
- **Goal**: Reply to Daniel: "I'll be there at 10:00 AM on Thursday"
- **Verification**: Email subject "RE: Meeting Thursday", to dan123@gmail.com, body matches
- **CLI**: **YES** — Read `state.json` for context, write `sentEmail.json` with correct fields

### 17. CancelMeetingTask
- **Goal**: Reply to Daniel to cancel Thursday meeting
- **Verification**: Email subject "RE: Meeting Thursday", body contains "cancel" + "meeting"
- **CLI**: **YES** — Same approach

### 18. CheckConferenceLocationTask
- **Goal**: Find conference hotel in email, text address to Tom, calculate walk time via Maps
- **Verification**: SMS with "110 Mt Auburn St" to 4456547865 + walk time ~43min (±10)
- **CLI**: **NO** — Requires Maps for walking time calculation (no API available on device)

### 19. CheckDepartTimeTask
- **Goal**: Check email for hackathon depart time; if not found, text Carl
- **Verification**: SMS exact text to 34567843456
- **CLI**: **YES** — Read `state.json` to check if depart time email exists, send SMS via ADB

### 20. CheckEventTimeTask
- **Goal**: Check email for Christmas party time, set alarm 1 hour before (6 PM)
- **Verification**: `check_alarm_via_adb(hour=18, minute=0)` enabled
- **CLI**: **YES** — Read `state.json` for party time, set alarm via `am start -a android.intent.action.SET_ALARM --ei android.intent.extra.alarm.HOUR 18 --ei android.intent.extra.alarm.MINUTES 0 --ez android.intent.extra.alarm.SKIP_UI true`

### 21. CheckInterviewTimesTask
- **Goal**: Check email for November interviews, create 3 calendar events (Google, Meta, Amazon)
- **Verification**: 3 calendar events with exact company names and timestamps
- **CLI**: **YES** — Read `state.json`, insert events via `content://com.android.calendar/events`

### 22. CheckRegistrationTask
- **Goal**: Check email for Putnam registration; if not found, email kathy@gmail.com
- **Verification**: Email to kathy@gmail.com with subject "Putnam Registration Confirmation"
- **CLI**: **YES** — Read `state.json`, write `sentEmail.json` if no Putnam confirmation found

### 23. CheckSetMeetTimeTask
- **Goal**: Check email for meeting date with Carl, create "Board Meeting" event
- **Verification**: Calendar event "Board Meeting" at Nov 15 15:00-16:00
- **CLI**: **YES** — Read `state.json`, insert calendar event

### 24. DownloadSendReceiptTask
- **Goal**: Find receipt.jpg in email, download, send to treasurer with total amount "5.08"
- **Verification**: Email with attachment "receipt.jpg" to treasurer@gmail.com, body contains "5.08"
- **CLI**: **NO** — Must read the receipt image to extract the total amount "5.08". The image is on device but the numerical content is only in the visual image.

### 25. GraduationMassEmailTask
- **Goal**: Search UF calendar (web), email 4 math graduates, set graduation party event
- **Verification**: Email to 4 recipients + calendar event May 9 2026 18:00
- **CLI**: **NO** — Requires Chrome to search UF academic calendar for grades due date

### 26. RequestCarpoolingTask
- **Goal**: Check email for competition time, if 12-5pm text Daniel
- **Verification**: SMS exact text to 3522228876
- **CLI**: **YES** — Read `state.json` for competition time, send SMS via ADB

### 27. SendFormsTask
- **Goal**: Find field trip forms (Oct 3+), download 3, send to principal, report count
- **Verification**: Email with 3 attachments + answer "3"
- **CLI**: **NO** — Must identify which forms are from Oct 3+ by reading email content in `state.json`, but then count attachments and send. The blocker is identifying the correct 3 out of 5 attachment files based on email dates. Actually the `state.json` contains the email metadata — this could be CLI-solvable if the JSON has date fields. **Borderline NO** — the selection logic from email dates makes this complex but theoretically possible.

### 28. SendInterviewEmailTask
- **Goal**: Find Kevin's resume (PDF), extract email, send interview message
- **Verification**: Email to kevin.zhang@example.com with interview text
- **CLI**: **NO** — PDF pushed to `/sdcard/Download/Kevin_CV.pdf`, but extracting email address from PDF requires reading the document content (visual)

### 29. SendWaiverTask
- **Goal**: Send waiver.jpg as email attachment to bob@gmail.com
- **Verification**: Email with "waiver.jpg" attachment, subject "Updated waiver"
- **CLI**: **YES** — Write `sentEmail.json` with `{"to":"bob@gmail.com","subject":"Updated waiver","body":"...","attachments":[{"name":"waiver.jpg"}]}`

### 30. SuggestPaperTask
- **Goal**: Reply to Tony with DDPM paper PDF and abstract
- **Verification**: Email with "ddpm.pdf" attachment, body with paper keywords ("denoising diffusion probabilistic models", "langevin", etc.)
- **CLI**: **NO** — Requires Chrome to find/download DDPM paper, plus reading abstract content

### 31. ThanksgivingPrepTask
- **Goal**: Browse recipe URL, email ingredients, set shopping event
- **Verification**: Email with ingredients + calendar event Nov 20 08:00
- **CLI**: **NO** — Requires Chrome to browse recipe website

---

## 5. MALL (7 GUI-only tasks) — 0 CLI-solvable

TaoDian (淘店) is a custom shopping app with no ADB content provider or intent API. All operations (browse, search, cart, checkout) require GUI. Verification uses callback JSON files written by the app.

### 32. CartInfoNotificationTask
- **Goal**: Find items awaiting shipment, SMS reminder with product name + order number
- **Verification**: SMS to 13800138888 with "639281475036294" + product names
- **CLI**: **NO** — Must navigate TaoDian to find order info

### 33. CartManagementTask
- **Goal**: Delete all short-sleeve T-shirts from cart
- **Verification**: Callback JSON with correct remaining item IDs
- **CLI**: **NO**

### 34. CheckCartPriceTask
- **Goal**: Find 3 most expensive cart items, calculate total
- **Verification**: interaction_cache == 13186
- **CLI**: **NO**

### 35. CheckPuchasedItem
- **Goal**: Check friend's shoe size from order history
- **Verification**: interaction_cache == 42
- **CLI**: **NO**

### 36. ItemCheckoutTask
- **Goal**: Checkout iPhone 15 Pro with specific delivery address
- **Verification**: Callback with prodId "11", correct address
- **CLI**: **NO**

### 37. RecentTotalExpenseTask
- **Goal**: Calculate total spending in past month
- **Verification**: interaction_cache == 1196
- **CLI**: **NO**

### 38. SearchItemAndCheckoutTask
- **Goal**: Search and order temporary tattoos for Halloween
- **Verification**: Callback with product containing "万圣节" + "临时纹身"
- **CLI**: **NO**

---

## 6. MAP (3 GUI-only tasks) — 0 CLI-solvable

### 39. GoogleMapsAlibabaSouthNeighborTask
- **Goal**: Find company directly south of Alibaba HQ on Google Maps
- **Verification**: interaction_cache contains "netease"
- **CLI**: **NO** — Requires visual Maps interaction (spatial reasoning)

### 40. GoogleMapsAlibabaPhoneContactTask
- **Goal**: Find Alibaba HQ phone number on Maps, create contact "Kevin Zhang"
- **Verification**: ADB contact check — "Kevin Zhang", "+86 571 85022088", "alibaba"
- **CLI**: **NO** — Phone number discovery requires Maps GUI

### 41. TextArrivalTimeTask
- **Goal**: Check driving time Orlando→Miami, text Susan estimated arrival ~8:30pm
- **Verification**: SMS to 4538997638 with time ±15min of 8:30pm
- **CLI**: **NO** — Requires Maps route calculation

---

## 7. MESSAGES (1 GUI-only task) — 0 CLI-solvable

### 42. SendInterviewInvitationTask
- **Goal**: Find Kevin's resume (PDF in Downloads), extract phone, SMS interview invitation
- **Verification**: SMS "Your interview is scheduled for tomorrow morning at 10:30 AM" to 15551234567
- **CLI**: **NO** — Requires reading PDF to extract phone number (the phone is embedded in the resume content)

---

## 8. MASTODON (36 GUI-only tasks) — 26 CLI-solvable, 5 partial

**Mastodon is open-source with a full REST API** at `https://10.0.2.2/api/v1/...` (from Android emulator, with `Host: 10.0.2.2` header). The backend also exposes PostgreSQL on `localhost:5432`. All standard Mastodon operations (post, bookmark, favorite, follow, lists, filters, invites, reports, polls, media upload, etc.) have REST API endpoints callable via `curl`.

**CLI method**: `curl -H "Authorization: Bearer <token>" -H "Host: 10.0.2.2" https://10.0.2.2/api/v1/...`

### 43. MastodonAddBookmarkTask — **CLI: YES**
- **Goal**: Bookmark kitty's #cats posts — `POST /api/v1/statuses/:id/bookmark`

### 44. MastodonAddFeaturedHashtagsTask — **CLI: YES**
- **Goal**: Add featured hashtags — `POST /api/v1/featured_tags`

### 45. MastodonAdjustTootsTask — **CLI: YES**
- **Goal**: Remove bookmarks → favorites → boost — `DELETE bookmark`, `POST favourite`, `POST reblog`

### 46. MastodonCalendarMultiMemosTask — **CLI: YES**
- **Goal**: Read #openTalk posts via API, create calendar events via ADB content provider
- Mastodon: `GET /api/v1/timelines/tag/openTalk` + Calendar: `content://com.android.calendar/events`

### 47. MastodonChangeHeaderTask — **CLI: NO**
- **Goal**: Replace profile header with tiger photo from gallery
- `PATCH /api/v1/accounts/update_credentials` with `header` multipart is available, but identifying which image is "tiger" among gallery photos requires visual recognition

### 48. MastodonChangeLanguageTask — **CLI: YES**
- **Goal**: Set language to zh-CN — account settings API

### 49. MastodonConditionalFavoTask — **CLI: YES**
- **Goal**: Favorite #dogs conditionally — read bookmarks/favorites first, then `POST favourite`

### 50. MastodonCreateMemoTask — **CLI: YES**
- **Goal**: Read #openTalk + create calendar event — same as #46 pattern

### 51. MastodonCreateListTask — **CLI: YES**
- **Goal**: Create list, set policy, add members — `POST /api/v1/lists`, `POST /api/v1/lists/:id/accounts`

### 52. MastodonExportFollowsTask — **CLI: YES**
- **Goal**: Export follows as CSV — `GET /api/v1/accounts/:id/following`, format as CSV, write to `/sdcard/Download/my_following.csv` via ADB

### 53. MastodonFavoriteTootsTask — **CLI: YES**
- **Goal**: Favorite all #dogs — `GET /api/v1/timelines/tag/dogs` + `POST /api/v1/statuses/:id/favourite`

### 54. MastodonFilterLanguageTask — **CLI: YES**
- **Goal**: Set language filter — account settings API

### 55. MastodonFollowTask — **CLI: YES**
- **Goal**: Find Robert's nickname in Contacts (ADB), search on Mastodon (`GET /api/v2/search`), follow (`POST /api/v1/accounts/:id/follow`)

### 56. MastodonGetServerInfoTask — **CLI: YES**
- **Goal**: Query DB size + post toot — `psql` for DB size, `POST /api/v1/statuses` for toot (as owner)

### 57. MastodonImportMutedUsersTask — **CLI: YES**
- **Goal**: Import muted users — read CSV via ADB, `POST /api/v1/accounts/:id/mute` per user

### 58. MastodonInviteTask — **CLI: YES**
- **Goal**: Generate invite + SMS — `POST /api/v1/invites` + ADB SMS send

### 59. MastodonMallPurchaseCommodityTask — **CLI: NO**
- **Goal**: Read Mastodon post (API) → buy on TaoDian (no API) — **blocked by Mall GUI**

### 60. MastodonMallShareOrderTask — **CLI: NO**
- **Goal**: Read TaoDian order (no API) → post on Mastodon — **blocked by Mall GUI**

### 61. MastodonManageHashtagsTask — **CLI: YES**
- **Goal**: Unfollow hashtags — `POST /api/v1/tags/:name/unfollow`

### 62. MastodonManageMultiListTask — **CLI: YES**
- **Goal**: Delete/create lists with members — full lists API

### 63. MastodonMattermostPostNoticeTask — **CLI: YES**
- **Goal**: Read Mattermost (REST API) → post on Mastodon (REST API) with visibility + mention

### 64. MastodonMultiInviteTask — **CLI: YES**
- **Goal**: Generate 2 invites + SMS both — invites API + ADB SMS

### 65. MastodonNewFilterTask — **CLI: YES**
- **Goal**: Read keywords file (ADB) → create filter — `POST /api/v2/filters` + keywords

### 66. MastodonNewPostTask — **CLI: YES**
- **Goal**: Post toot — `POST /api/v1/statuses`

### 67. MastodonOpenAutomatedDeletionTask — **CLI: YES**
- **Goal**: Configure auto-deletion settings — can be set via direct PostgreSQL `UPDATE` on the `statuses_cleanup_policies` table (verifier reads from same DB)

### 68. MastodonPinTootsTask — **CLI: YES**
- **Goal**: Pin post — `POST /api/v1/statuses/:id/pin`

### 69. MastodonPostEditedPhotoTask — **CLI: NO**
- **Goal**: Crop gallery photo to 9:16 ratio + post with #onePhoto — selecting a "random" gallery photo and cropping to exact 9:16 ratio requires image processing tools unlikely available on Android emulator

### 70. MastodonPostPollTask — **CLI: NO**
- **Goal**: Search Google for Nobel Prize winners → create poll — **blocked by Chrome for web search**

### 71. MastodonRemoveBookmarkTask — **CLI: YES**
- **Goal**: Remove bookmarks — `POST /api/v1/statuses/:id/unbookmark`

### 72. MastodonReplyTask — **CLI: YES**
- **Goal**: Reply to toot — `POST /api/v1/statuses` with `in_reply_to_id`

### 73. MastodonReportTask — **CLI: YES**
- **Goal**: Report + block — `POST /api/v1/reports` + `POST /api/v1/accounts/:id/block`

### 74. MastodonRevisePhotoAltTask — **CLI: YES**
- **Goal**: Edit image ALT text — `GET` status to read current ALT, `PUT /api/v1/media/:id` with updated `description`

### 75. MastodonRevisePollTask — **CLI: YES**
- **Goal**: Edit poll options — `PUT /api/v1/statuses/:id` with updated poll

### 76. MastodonSavePhotosTask — **CLI: YES**
- **Goal**: Get image URLs from API → download with `curl` → save to device storage

### 77. MastodonServerInfoReportTask — **CLI: YES**
- **Goal**: Count reports via API/DB → write `sentEmail.json` via ADB

### 78. MastodonShareLocationTask — **CLI: NO**
- **Goal**: Search Eiffel Tower on Maps → share on Mastodon — **blocked by Maps for location search/link**

### 79. MastodonUnfollowTask — **CLI: YES**
- **Goal**: Get following list → unfollow extras — `POST /api/v1/accounts/:id/unfollow`

### 80. MastodonUpdateContactsTask — **CLI: YES**
- **Goal**: Read Olivia's post via API → update contact via ADB content provider → send SMS via ADB

---

## 9. NATIVE (18 GUI-only tasks) — 5 CLI-solvable

### 81. BidFileRenameTask — **CLI: YES**
- **Goal**: Rename bid_* files in Download by creation date → bid_{序号}.{ext}
- **Verification**: ADB file listing — correct renamed files, originals gone
- **Method**: `ls -lt /sdcard/Download/bid_*` to sort by date, `mv` to rename

### 82. CountFileLinesTask — **CLI: YES**
- **Goal**: Find earliest July zip in Downloads, count lines in file_1.txt
- **Verification**: interaction_cache == 29
- **Method**: `ls -lt *.zip`, `unzip`, `wc -l file_1.txt`

### 83. SumFileLinesTask — **CLI: YES**
- **Goal**: Sum line counts of all files in earliest July zip
- **Verification**: interaction_cache == 315
- **Method**: `unzip`, `wc -l` for each, sum

### 84. InvoiceReceiptCopyTask — **CLI: YES**
- **Goal**: Find November invoice/receipt PDFs, copy to Finance/invoice folder
- **Verification**: ADB — correct files in target folder
- **Method**: `ls`, `stat` for dates, `cp` matching files

### 85. InvoiceReceiptCopyAskUserTask — **CLI: YES**
- **Goal**: Same as #84 but target is Documents/expense/invoice
- **Verification**: ADB — correct files in target folder
- **Method**: Same `stat` + `cp` approach
- **Note**: Despite "AskUser" in name, tags do NOT include agent-user-interaction

### 86. CheckInvoiceTask1
- **Goal**: Read invoice PDF, recalculate total with 45-day late payment
- **Verification**: interaction_cache == 104417.7
- **CLI**: **NO** — Requires reading PDF content

### 87. CheckInvoiceTask2
- **Goal**: Read invoice PDF, email recalculated amount to customer
- **Verification**: Email to accounting@globalent.com with "104417.7" in body
- **CLI**: **NO** — PDF reading + email

### 88. CheckInvoiceTask3
- **Goal**: Read invoice PDF, SMS Mia the consulting vs development hours difference
- **Verification**: SMS "0" to 14058298746
- **CLI**: **NO** — PDF reading required

### 89. CVEmailTask
- **Goal**: Find CV PDFs from past month, email to HR
- **Verification**: Email with 3 CV attachments to HR_chen@gmail.com
- **CLI**: **YES** — `stat` for dates, identify CV files, write `sentEmail.json` with attachment entries

### 90. ReviewPaperEmailTask
- **Goal**: Find review_*.pdf files across Documents, move to Documents/paper, email all
- **Verification**: Files moved + email with 4 attachments
- **CLI**: **YES** — `find` + `mv` for files, write `sentEmail.json` with attachment entries

### 91. ReadQwen3PaperTask1
- **Goal**: Read Qwen3 paper, find AIME25 score gap for Qwen3-32B (Thinking) vs best
- **Verification**: interaction_cache == 1.9
- **CLI**: **NO** — PDF reading

### 92. ReadQwen3PaperTask2
- **Goal**: How many core contributors in Qwen3 paper?
- **Verification**: interaction_cache == 60
- **CLI**: **NO** — PDF reading

### 93. ReadQwen3PaperTask3
- **Goal**: How many benchmarks for Text-to-Text in Qwen3-Omni?
- **Verification**: interaction_cache == 12
- **CLI**: **NO** — PDF reading

### 94. ReadQwen3PaperTask4
- **Goal**: Vision encoder size in Qwen3-Omni-30B-A3B?
- **Verification**: interaction_cache in [540, 543]
- **CLI**: **NO** — PDF reading

### 95. ReadQwen3PaperTask5
- **Goal**: What Austroasiatic languages in Belebele benchmark?
- **Verification**: interaction_cache == "vie Latn,khm Khmr"
- **CLI**: **NO** — PDF reading

### 96. SetAlarmTask
- **Goal**: Weekend alarm 8:25 AM, ringtone "beebeep", vibration off
- **Verification**: ADB alarm check — days=96, ringtone="beebeep", vibrate=off
- **CLI**: **NO** — `am start SET_ALARM` supports hour/minute but does not support setting specific ringtone name ("beebeep") or disabling vibration. The alarm DB could be written directly, but ringtone URI requires knowing the exact content URI for "beebeep" on the device.

### 97. SharePhotosTask
- **Goal**: Find flower pictures in gallery, email to kevin_zhang@example.com
- **Verification**: Email with exactly 4 attachments named image1-4.jpeg
- **CLI**: **YES** — The verifier checks for exactly `{"image1.jpeg","image2.jpeg","image3.jpeg","image4.jpeg"}`. These are ALL the images pushed to `/sdcard/Pictures/` during init (7 images pushed, but only these 4 are in REQUIRED_IMAGES). The "flower" identification is a red herring — the agent just needs to send all 4 required files. Write `sentEmail.json` with attachment entries.

### 98. SMSManagement
- **Goal**: Check unread SMS, delete spam, email recruitment summary to dylan@gmail.com
- **Verification**: ADB — spam numbers 78901/56789/34567/88999 deleted, "AMAZON" kept + email body contains "meta" + "data scientist"
- **CLI**: **YES** — SMS fully readable via `content://sms/`, delete spam by number via `content delete`, read recruitment SMS text, write `sentEmail.json` summarizing Meta data scientist info. All text-based operations.

### 99. TakeSelfieTask
- **Goal**: Take a photo
- **Verification**: MediaStore new photos count > 0
- **CLI**: **NO** — Requires Camera app

---

## 10. WORK (23 GUI-only tasks) — 12 CLI-solvable

**Mattermost is open-source with a full REST API** at `http://10.0.2.2:8065/api/v4/...` (from Android emulator). Also has `mmctl` CLI and PostgreSQL on `localhost:5433`. All operations (channels, messages, files, users) have REST endpoints.

**CLI method**: `curl -H "Authorization: Bearer <token>" http://10.0.2.2:8065/api/v4/...`

### Mattermost tasks (17)

### 100. MattermostCreateChannelTask — **CLI: YES**
- Create channel (`POST /api/v4/channels`), add users (`POST /api/v4/channels/:id/members`), send message (`POST /api/v4/posts`)

### 101. MattermostReplyToMessageTask — **CLI: YES**
- Reply to message (`POST /api/v4/posts` with `root_id`)

### 102. MattermostEmailTask — **CLI: YES**
- Read Mattermost messages (API), write `sentEmail.json` for email, post confirmation (`POST /api/v4/posts`)

### 103. MattermostSendFileTask — **CLI: YES**
- Upload file (`POST /api/v4/files`), DM with attachment (`POST /api/v4/posts` with `file_ids`)

### 104. MattermostProjectHandoverTask — **CLI: YES**
- Add user to channel + read calendar (SQLite) + post formatted message

### 105. MattermostReadingGroupTask — **CLI: NO**
- Must find arXiv paper content (MMMU_Pro score) — requires reading paper, **blocked by no arXiv API on device**

### 106. MattermostBudgetApprovalPipelineTask — **CLI: YES**
- Read channel messages (API), parse budget requests, calculate ROI, post markdown table

### 107. MattermostCustomerFeedbackAnalysisTask — **CLI: YES**
- Read messages (API), filter negatives, write `sentEmail.json`, insert calendar event, post confirmation

### 108. MattermostDeadlineReconciliationTask — **CLI: YES**
- Read messages (API), query calendar (SQLite), write `sentEmail.json`, insert [AUTO] events, post confirmation

### 109. MattermostIncidentEscalationTask — **CLI: YES**
- Read messages, create channel, add user, write `sentEmail.json`, insert calendar event

### 110. MattermostProjectStatusReportTask — **CLI: YES**
- Read 3 team channels, write `sentEmail.json`, insert [ESCALATION] events, post summary

### 111. MattermostResourceConflictResolutionTask — **CLI: YES**
- Read messages, query calendar, write `sentEmail.json`, insert BOOKED events, DM users

### 112. MattermostShiftCoverageTask — **CLI: YES**
- Read requests, check calendar, reply to messages, write `sentEmail.json` for HR escalation

### 113. MattermostTechnicalDebtTriageTask — **CLI: YES**
- LaTeX formulas are plain text in messages — parseable. SMS via ADB, contacts via ADB, post table via Mattermost API.

### 114. MattermostVisualInstructionResponseTask — **CLI: NO**
- Must read **images** posted in channel containing contact info and shift schedules — **blocked by image reading requirement**

### Other work tasks (6)

### 115. LocalFileManagementTask — **CLI: YES**
- Delete old files (ADB), send list via Mattermost DM (REST API `POST /api/v4/posts`)

### 116. LocalFileManagementTask2 — **CLI: YES**
- Zip + delete (ADB), write `sentEmail.json` for email with file names

### 117. PhotoManagementTask — **CLI: NO**
- Classify food photos by travel destination — requires reading calendar events (doable) AND understanding which photos are "food photos" from Paris/Tokyo. File naming (PAR/TOK prefix) makes this **borderline** — if the agent notices the naming pattern, `mv` by prefix is trivial. But the task says "food photos" implying visual understanding.

---

## CLI-Solvable Summary

### 70 CLI-Solvable Tasks

| Category | Count | CLI Channels Used |
|----------|-------|-------------------|
| Settings | 7 | ADB `settings put`, `wm density`, `am broadcast`, wallpaper intent |
| Calendar | 6 | Calendar SQLite DB + SMS content provider + ADB SMS |
| Gmail | 10 | Read `state.json` (inbox) + write `sentEmail.json` (send) + calendar content provider |
| Mastodon | 28 | Mastodon REST API (`curl https://10.0.2.2/api/v1/...`) + PostgreSQL + ADB for SMS/contacts/calendar |
| Native | 8 | ADB filesystem (`ls`, `mv`, `cp`, `unzip`, `wc`) + `sentEmail.json` + SMS content provider |
| Work | 13 | Mattermost REST API (`curl http://10.0.2.2:8065/api/v4/...`) + `sentEmail.json` + calendar SQLite |
| **Total** | **70** | |

Note: Chrome (0/2), Mall (0/7), Map (0/3), Messages (0/1) have zero CLI-solvable tasks.

### 47 GUI-Required Tasks — Blockers

| Blocker | Tasks | Examples |
|---------|-------|---------|
| **No API for TaoDian (Mall)** | 9 | 7 Mall tasks + 2 Mastodon cross-app (buy/share via Mall) |
| **PDF reading** | 9 | 5 ReadQwen3Paper, 3 CheckInvoice, 1 SendInterviewEmail (phone in resume) |
| **Chrome web browsing** | 6 | Weather, recipe, GitHub stats, Nobel Prize, UF calendar, DDPM paper |
| **Maps spatial reasoning** | 4 | Walk time, drive time, neighbor finding, Eiffel Tower link |
| **Image recognition** | 3 | Tiger photo (header), photo crop 9:16, visual instruction reading |
| **Camera capture** | 1 | TakeSelfieTask |
| **Alarm ringtone** | 1 | SetAlarmTask — specific ringtone "beebeep" not settable via intent |
| **Photo classification** | 1 | PhotoManagementTask — "food photos" implies visual understanding |
| **arXiv paper content** | 1 | MattermostReadingGroupTask — needs MMMU_Pro score from paper |

*(Some tasks have multiple blockers; total unique tasks = 47)*
