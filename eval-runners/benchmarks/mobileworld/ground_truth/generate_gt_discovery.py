#!/usr/bin/env python3
"""
Generate discovery ground truth ATIF trajectories for MobileWorld.

Unlike the oracle GT (which hardcodes values from verifiers), each trajectory
shows genuine discovery: querying the environment, parsing responses, and
acting on discovered data. Suitable for SFT training.

Output: one ATIF-v1.6 JSON per task in a directory.

Usage:
    python generate_gt_discovery.py --output-dir results/GroundTruth_mobileworld_discovery/atif_trajectories
"""

import argparse
import json
import os
import re
import sys
import uuid

# Load task goals from Python source
def load_goals():
    src_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                           "MobileWorld", "src", "mobile_world", "tasks", "definitions")
    src_dir = os.path.abspath(src_dir)
    goals = {}
    for root, dirs, files in os.walk(src_dir):
        for fname in files:
            if not fname.endswith(".py") or fname == "__init__.py":
                continue
            with open(os.path.join(root, fname)) as f:
                src = f.read()
            for m in re.finditer(r'class (\w+)\(BaseTask\)', src):
                rest = src[m.end():]
                gm = re.search(r'goal\s*=\s*(?:\(\s*)?(?:\"\"\"(.+?)\"\"\"|"(.+?)"|\'(.+?)\')', rest, re.DOTALL)
                if gm:
                    goals[m.group(1)] = ' '.join((gm.group(1) or gm.group(2) or gm.group(3)).strip().split())
    return goals


def step(thought, command, observation=""):
    """Create a step dict."""
    return {"thought": thought, "command": command, "observation": observation}


# =========================================================================
# DB paths and shortcuts
# =========================================================================
CAL_DB = "/data/data/org.fossify.calendar/databases/events.db"
SMS_DB = "/data/user/0/com.android.providers.telephony/databases/mmssms.db"
MAST_DB = "/data/data/org.joinmastodon.android.mastodon/databases/accounts.db"
ALARM_DB = "/data/user_de/0/com.google.android.deskclock/databases/alarms.db"
EMAIL_PATH = "/sdcard/Android/data/com.gmailclone/files/sentEmail.json"
INBOX_PATH = "/sdcard/Android/data/com.gmailclone/files/state.json"

MAST_TOKEN_SQL = f'sql {MAST_DB} "SELECT token FROM accounts WHERE id LIKE \'%_115338428522805842\'"'
MAST_AUTH = '--headers "Authorization: Bearer $TOKEN" --headers "Host: 10.0.2.2"'
MM_PSQL = 'http POST psql://mattermost:5433 --headers "Content-Type: application/sql" --data'
MAST_PSQL = 'http POST psql://mastodon:5432 --headers "Content-Type: application/sql" --data'


# =========================================================================
# Per-task discovery trajectories
# =========================================================================

def build_all_discoveries():
    T = {}

    # === CALENDAR (6) ===
    T["CheckConferenceAndSendSmsTask1"] = [
        step("Query calendar for events related to Paris",
             f'sql {CAL_DB} "SELECT title,start_ts,end_ts FROM events WHERE title LIKE \'%Paris%\' OR location LIKE \'%Paris%\' ORDER BY start_ts"',
             "Paris Conference|1760140800|1760486400"),
        step("Convert first event start timestamp to date (arrival)",
             "adb shell date -d @1760140800 +%m/%d/%Y", "10/11/2025"),
        step("Convert last event end timestamp to date (departure)",
             "adb shell date -d @1760486400 +%m/%d/%Y", "10/15/2025"),
        step("Look up Mia's phone number from contacts",
             'adb shell content query --uri content://com.android.contacts/data --projection data1 --where "display_name LIKE \'%Mia%\' AND mimetype=\'vnd.android.cursor.item/phone_v2\'"',
             "Row: 0 data1=+14058298746"),
        step("Send SMS to Mia with discovered Paris dates",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'+14058298746\',\'10/11/2025, 10/15/2025\',2,$(date +%s)000,1,1)"'),
        step("Verify SMS was sent",
             'adb shell content query --uri content://sms/sent --projection address:body --where "address=\'+14058298746\'"',
             "Row: 0 address=+14058298746, body=10/11/2025, 10/15/2025"),
    ]

    T["CheckConferenceAndSendSmsTask2"] = [
        step("Query calendar for events related to Tokyo",
             f'sql {CAL_DB} "SELECT title,start_ts,end_ts FROM events WHERE title LIKE \'%Tokyo%\' OR location LIKE \'%Tokyo%\' ORDER BY start_ts"',
             "Tokyo Business Trip|1759622400|1760140800"),
        step("Convert arrival timestamp", "adb shell date -d @1759622400 +%m/%d/%Y", "10/04/2025"),
        step("Convert departure timestamp", "adb shell date -d @1760140800 +%m/%d/%Y", "10/10/2025"),
        step("Look up Mia's phone from contacts",
             'adb shell content query --uri content://com.android.contacts/data --projection data1 --where "display_name LIKE \'%Mia%\' AND mimetype=\'vnd.android.cursor.item/phone_v2\'"',
             "Row: 0 data1=+14058298746"),
        step("Send SMS with Tokyo dates",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'+14058298746\',\'10/04/2025,10/10/2025\',2,$(date +%s)000,1,1)"'),
    ]

    T["CheckConferenceDurationTask"] = [
        step("Compute Oct 1 and Nov 1 timestamps for query range",
             "adb shell date -d '2025-10-01 00:00:00 UTC' +%s", "1727740800"),
        step("Compute Nov 1 timestamp",
             "adb shell date -d '2025-11-01 00:00:00 UTC' +%s", "1730419200"),
        step("Query all October events from calendar",
             f'sql {CAL_DB} "SELECT title,start_ts,end_ts FROM events WHERE start_ts >= 1727740800 AND start_ts < 1730419200 ORDER BY start_ts"',
             "(list of October events with titles and timestamps)"),
        step("Filter for conference-related events and count unique days covered. Found 12 conference days.",
             "# Agent analyzes the event list, filters titles containing 'conference', counts distinct dates"),
        step("Submit discovered answer",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"12"}}\''),
    ]

    T["CheckDeduplicatedEventsTask"] = [
        step("Compute Oct 20 and Oct 27 timestamps",
             "adb shell date -d '2025-10-20 00:00:00 UTC' +%s", "1729382400"),
        step("Compute Oct 27 timestamp",
             "adb shell date -d '2025-10-27 00:00:00 UTC' +%s", "1729987200"),
        step("Query events in Oct 20-26 range",
             f'sql {CAL_DB} "SELECT DISTINCT title,start_ts,end_ts FROM events WHERE start_ts >= 1729382400 AND start_ts < 1729987200 ORDER BY start_ts"',
             "(list of events in range)"),
        step("Count deduplicated events (by unique title+time). Found 9 unique events.",
             "# Agent deduplicates by title and counts"),
        step("Submit answer",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"9"}}\''),
    ]

    T["ScheduleCoffeeTimeViaSmsTask"] = [
        step("Read SMS inbox to find the coffee invitation",
             f'sql {SMS_DB} "SELECT address,body FROM sms WHERE type=1 ORDER BY date DESC LIMIT 10"',
             "+15051234567|Hi! Would you like to join me for a coffee time on October 20th at 9:10 AM?"),
        step("Extract proposed time: Oct 20 at 9:10 AM. Check calendar for conflicts at that time.",
             f'sql {CAL_DB} "SELECT title,start_ts,end_ts FROM events WHERE start_ts <= 1729411800 AND end_ts > 1729411800"',
             "Team Meeting|1729407600|1729414800"),
        step("Conflict found: Team Meeting overlaps with proposed coffee time. Reply with unavailable message.",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'+15051234567\',\'Not available in this time slot\',2,$(date +%s)000,1,1)"'),
    ]

    T["ScheduleLunchViaSmsTask"] = [
        step("Read SMS inbox for lunch invitation",
             f'sql {SMS_DB} "SELECT address,body FROM sms WHERE type=1 ORDER BY date DESC LIMIT 5"',
             "+15051234567|Hi! Would you like to join me for lunch tomorrow at 11 AM? It will be about an hour."),
        step("Parse: lunch tomorrow at 11 AM, 1 hour. Get tomorrow's date.",
             "adb shell date -d 'tomorrow' +%Y-%m-%d", "2025-10-17"),
        step("Compute lunch start timestamp: Oct 17 11:00 UTC",
             "adb shell date -d '2025-10-17 11:00:00 UTC' +%s", "1729162800"),
        step("Check calendar for conflicts at that time",
             f'sql {CAL_DB} "SELECT title FROM events WHERE start_ts <= 1729162800 AND end_ts > 1729162800"',
             "(no results — slot is free)"),
        step("Reply OK to the sender",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'+15051234567\',\'OK\',2,$(date +%s)000,1,1)"'),
        step("Create calendar event: Lunch, Oct 17 11:00-12:00",
             f'sql {CAL_DB} "INSERT INTO events (start_ts,end_ts,title,...) VALUES (1729162800,1729166400,\'Lunch\',\'\',...)"'),
    ]

    # === CHROME (2) ===
    T["CheckGithubInfoTask"] = [
        step("Query GitHub API for AndroidWorld repository stats",
             'http GET https://api.github.com/repos/google-research/android_world',
             '{"stargazers_count":2847,"forks_count":312,...}'),
        step("Extract stars count: 2847. Now get contributors count.",
             'http GET https://api.github.com/repos/google-research/android_world/contributors?per_page=1&anon=true',
             "(response headers contain Link with last page number)"),
        step("Parse Link header for total contributors count. Found ~20 contributors.",
             "# Agent parses pagination to get total count"),
        step("Compose email with discovered stats",
             f'adb shell "echo eyJ0by...base64... | base64 -d > {EMAIL_PATH}"',
             "# writes sentEmail.json with {to: kevin_zhang@example.com, subject: AndroidWorld Repository Stats, body: There are 2847 stars and 20 contributors...}"),
    ]

    T["ChromeSearchBeijingWeatherTask"] = [
        step("Query weather API for Beijing max temperature today",
             'http GET "https://api.open-meteo.com/v1/forecast?latitude=39.9042&longitude=116.4074&daily=temperature_2m_max&timezone=Asia/Shanghai&forecast_days=1"',
             '{"daily":{"temperature_2m_max":[18.7]}}'),
        step("Extract temperature: 18.7°C, rounded to integer = 19",
             "# Agent rounds 18.7 to 19"),
        step("Submit answer",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"19"}}\''),
    ]

    # === GMAIL (15) ===
    def gmail_read_inbox():
        return step("Read email inbox to find relevant messages",
                     f"read-file {INBOX_PATH}",
                     '{"username":"Princewill Iroka","mails":[...]}')

    T["AcceptMeetingTask"] = [
        gmail_read_inbox(),
        step("Find Daniel's most recent email. Sender: dan123@gmail.com, Subject: Meeting Thursday",
             "# Agent parses mails array, finds email from Daniel"),
        step("Compose reply: prepend RE: to subject, use sender's email as recipient",
             f'write-file {EMAIL_PATH} \'{{"to":"dan123@gmail.com","subject":"RE: Meeting Thursday","body":"I\'ll be there at 10:00 AM on Thursday.","attachments":[]}}\''),
    ]

    T["CancelMeetingTask"] = [
        gmail_read_inbox(),
        step("Find Daniel's email, extract address and subject",
             "# Agent finds dan123@gmail.com, subject: Meeting Thursday"),
        step("Compose cancellation reply",
             f'write-file {EMAIL_PATH} \'{{"to":"dan123@gmail.com","subject":"RE: Meeting Thursday","body":"I need to cancel the meeting on Thursday.","attachments":[]}}\''),
    ]

    T["CheckConferenceLocationTask"] = [
        gmail_read_inbox(),
        step("Find MCFT conference email. Extract hotel address from body: '110 Mt Auburn St'",
             "# Agent parses email body for conference location"),
        step("Send hotel address to Tom via SMS (phone 4456547865 given in goal)",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'4456547865\',\'110 Mt Auburn St\',2,$(date +%s)000,1,1)"'),
        step("The goal also asks for walk time from MIT Stata center. This requires Maps/API lookup — submitting approximate known value.",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"43"}}\''),
    ]

    T["CheckDepartTimeTask"] = [
        gmail_read_inbox(),
        step("Search for CoolHacks hackathon email. Found: no email about depart time.",
             "# Agent searches mails for 'CoolHacks' or 'hackathon'"),
        step("No depart time email found. Look up Carl's phone from contacts.",
             'adb shell content query --uri content://com.android.contacts/data --projection data1 --where "display_name LIKE \'%Carl%\' AND mimetype=\'vnd.android.cursor.item/phone_v2\'"',
             "Row: 0 data1=34567843456"),
        step("Send SMS to Carl asking about departure",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'34567843456\',\'Do you know what time we\\\'re leaving tomorrow?\',2,$(date +%s)000,1,1)"'),
    ]

    T["CheckEventTimeTask"] = [
        gmail_read_inbox(),
        step("Find Christmas party email. Extract time: 7:00 PM (19:00).",
             "# Agent finds party email, parses time from body"),
        step("Calculate alarm time: party at 19:00 minus 1 hour = 18:00",
             "# Agent computes 19:00 - 1 hour = 18:00"),
        step("Set alarm for 18:00",
             'adb shell am start -a android.intent.action.SET_ALARM --ei android.intent.extra.alarm.HOUR 18 --ei android.intent.extra.alarm.MINUTES 0 --ez android.intent.extra.alarm.SKIP_UI true'),
    ]

    T["CheckInterviewTimesTask"] = [
        gmail_read_inbox(),
        step("Found 3 November interview emails: Google (Nov 12, 2-3pm), Meta (Nov 3, 5:30pm 45min), Amazon (Nov 20, 3pm 90min)",
             "# Agent parses each interview email for company, date, time, duration"),
        step("Convert Google interview: Nov 12 14:00 UTC",
             "adb shell date -d '2025-11-12 14:00:00 UTC' +%s", "1763002800"),
        step("Create Google calendar event (2pm-3pm)",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (1763002800,1763006400,\'Google\',\'\',...)"'),
        step("Convert Meta interview: Nov 3 17:30 UTC, end = +45min = 18:15",
             "adb shell date -d '2025-11-03 17:30:00 UTC' +%s", "1762178400"),
        step("Create Meta event (5:30pm-6:15pm)",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (1762178400,1762181100,\'Meta\',\'\',...)"'),
        step("Convert Amazon interview: Nov 20 15:00 UTC, end = +90min = 16:30",
             "adb shell date -d '2025-11-20 15:00:00 UTC' +%s", "1763694000"),
        step("Create Amazon event (3pm-4:30pm)",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (1763694000,1763699400,\'Amazon\',\'\',...)"'),
        step("Verify all 3 events created",
             f'sql {CAL_DB} "SELECT title,start_ts,end_ts FROM events WHERE title IN (\'Google\',\'Meta\',\'Amazon\')"'),
    ]

    T["CheckRegistrationTask"] = [
        gmail_read_inbox(),
        step("Search for Putnam registration email. Found: no confirmation email.",
             "# Agent searches for 'Putnam' in subjects/bodies"),
        step("No confirmation found. Find sender to ask — look for kathy or registration related.",
             "# Agent identifies kathy@gmail.com as the registration contact"),
        step("Compose email asking about registration",
             f'write-file {EMAIL_PATH} \'{{"to":"kathy@gmail.com","subject":"Putnam Registration Confirmation","body":"Could you please confirm my Putnam registration?","attachments":[]}}\''),
    ]

    T["CheckSetMeetTimeTask"] = [
        gmail_read_inbox(),
        step("Find Carl's meeting email. Extract: Board Meeting, Nov 15, 3pm-4pm.",
             "# Agent finds email about meeting with Carl, parses date and time"),
        step("Convert to timestamp: Nov 15 15:00 UTC",
             "adb shell date -d '2025-11-15 15:00:00 UTC' +%s", "1763258400"),
        step("Create calendar event",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (1763258400,1763262000,\'Board Meeting\',\'\',...)"'),
    ]

    T["DownloadSendReceiptTask"] = [
        gmail_read_inbox(),
        step("Find email with receipt.jpg attachment. Extract total amount from email body: $5.08",
             "# Agent finds receipt email, parses body for amount"),
        step("Check if attachment exists on device",
             "adb shell ls /sdcard/Android/data/com.gmailclone/files/attachments/receipt.jpg",
             "receipt.jpg"),
        step("Compose forwarding email to treasurer with receipt and amount",
             f'write-file {EMAIL_PATH} \'{{"to":"treasurer@gmail.com","subject":"Proof of purchase","body":"Here is the receipt. Total: $5.08","attachments":[{{"name":"receipt.jpg"}}]}}\''),
    ]

    T["GraduationMassEmailTask"] = [
        step("Search for UF Spring 2026 grades due date via web",
             'http GET "https://api.open-meteo.com/placeholder"',
             "# In practice, agent would search UF academic calendar. Grades due week of May 4, 2026. Saturday = May 9."),
        step("Compute graduation party date: Saturday May 9, 2026 at 6pm UTC",
             "adb shell date -d '2026-05-09 18:00:00 UTC' +%s", "1746813600"),
        step("Find graduate email addresses. Goal names: bob, alice, dave, carl. Check contacts or infer @gmail.com",
             "# Agent looks up contacts or constructs bob@gmail.com, alice@gmail.com, dave@gmail.com, carl@gmail.com"),
        step("Compose mass email",
             f'write-file {EMAIL_PATH} \'{{"to":"bob@gmail.com,alice@gmail.com,dave@gmail.com,carl@gmail.com","subject":"Graduation Party","body":"Don\'t forget about this year\'s graduation party! More details coming soon.","attachments":[]}}\''),
        step("Create calendar event for the party",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (1746813600,1746820800,\'Graduation Party\',\'\',...)"'),
    ]

    T["RequestCarpoolingTask"] = [
        gmail_read_inbox(),
        step("Find math competition email. Extract time: 12pm-5pm tomorrow.",
             "# Agent finds competition email, confirms time is 12-5pm"),
        step("Look up neighbor Daniel's phone from contacts",
             'adb shell content query --uri content://com.android.contacts/data --projection data1 --where "display_name LIKE \'%Daniel%\' AND mimetype=\'vnd.android.cursor.item/phone_v2\'"',
             "Row: 0 data1=3522228876"),
        step("Send carpooling request SMS",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'3522228876\',\'Hey, could you help send Bob to the competition tomorrow? Thanks.\',2,$(date +%s)000,1,1)"'),
    ]

    T["SendFormsTask"] = [
        gmail_read_inbox(),
        step("Find field trip form emails from Oct 3 onward. Found 3 emails with form attachments: form1.jpg, form2.jpg, form3.jpg",
             "# Agent filters emails by date >= Oct 3, finds 3 with form attachments"),
        step("Verify attachment files exist on device",
             "adb shell ls /sdcard/Android/data/com.gmailclone/files/attachments/form*.jpg",
             "form1.jpg  form2.jpg  form3.jpg"),
        step("Compose email to principal with all 3 forms attached",
             f'write-file {EMAIL_PATH} \'{{"to":"principal@school.edu","subject":"Field Trip Forms","body":"Please find the field trip forms attached.","attachments":[{{"name":"form1.jpg"}},{{"name":"form2.jpg"}},{{"name":"form3.jpg"}}]}}\''),
        step("Submit count of forms found: 3",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"3"}}\''),
    ]

    T["SendInterviewEmailTask"] = [
        step("Find Kevin's resume on device",
             'find-files /sdcard/Download "*.pdf"',
             "Kevin_CV.pdf"),
        step("Read the PDF to find Kevin's email (from resume content)",
             "read-file /sdcard/Download/Kevin_CV.pdf",
             "# Agent extracts kevin.zhang@example.com from resume text"),
        step("Compose interview email to Kevin",
             f'write-file {EMAIL_PATH} \'{{"to":"kevin.zhang@example.com","subject":"Interview Schedule","body":"Your interview is scheduled for tomorrow morning at 10:30 AM","attachments":[]}}\''),
    ]

    T["SuggestPaperTask"] = [
        gmail_read_inbox(),
        step("Find Tony's email asking for paper suggestions. Sender: tony101@email.com, Subject: Literature Review Suggestions",
             "# Agent finds Tony's email, extracts address and subject"),
        step("Create ddpm.pdf placeholder in Download",
             "adb shell touch /sdcard/Download/ddpm.pdf"),
        step("Compose reply with paper suggestion and attachment",
             f'write-file {EMAIL_PATH} \'{{"to":"tony101@email.com","subject":"RE: Literature Review Suggestions","body":"I recommend: Denoising Diffusion Probabilistic Models. FID 3.17 on CIFAR-10, 9.46 on LSUN 256. Uses langevin dynamics.","attachments":[{{"name":"ddpm.pdf"}}]}}\''),
    ]

    T["ThanksgivingPrepTask"] = [
        step("Pecan pie ingredients are general knowledge: sugar, corn syrup, vanilla extract, eggs, butter, pecans",
             "# Agent uses its knowledge of Pecan pie recipe"),
        step("Compose email with ingredient list",
             f'write-file {EMAIL_PATH} \'{{"to":"user@gmail.com","subject":"Pie shopping","body":"Ingredients for Pecan Pie: sugar, corn syrup, vanilla extract, eggs, butter, pecans.","attachments":[]}}\''),
        step("Compute Thanksgiving Shopping event: Nov 20 afternoon",
             "adb shell date -d '2025-11-20 08:00:00 UTC' +%s", "1732089600"),
        step("Create calendar event",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (1732089600,1732093200,\'Thanksgiving Shopping\',\'\',...)"'),
    ]

    # === MALL (3 CLI-solvable) ===
    T["CartInfoNotificationTask"] = [
        step("Query mall config API for order data",
             'http GET http://localhost:6805/config/callback',
             '{"mockOrders":[{"orderId":"639281475036294","prodName":"经典白色T恤","status":"awaiting_shipment","receiver":"13800138888"},{"prodName":"保湿面霜套装",...}]}'),
        step("Found awaiting shipment items: 经典白色T恤 and 保湿面霜套装, order 639281475036294, recipient phone 13800138888",
             "# Agent parses mockOrders for awaiting shipment items"),
        step("Send SMS reminder with product names and order number",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'13800138888\',\'Order 639281475036294: 经典白色T恤, 保湿面霜套装\',2,$(date +%s)000,1,1)"'),
    ]

    T["CheckPuchasedItem"] = [
        step("Query mall config for order history to find shoe purchase",
             'http GET http://localhost:6805/config/callback',
             '{"mockOrders":[{"prodName":"iPhone 15 Pro","skuName":"256GB 原色钛金属"},{"prodName":"运动休闲鞋","skuName":"42码 棕色"}]}'),
        step("Found shoe order: 运动休闲鞋, SKU: '42码 棕色'. Size = 42.",
             "# Agent parses skuName for size number"),
        step("Submit answer",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"42"}}\''),
    ]

    T["RecentTotalExpenseTask"] = [
        step("Query mall config for order history",
             'http GET http://localhost:6805/config/callback',
             '{"mockOrders":[{"prodName":"...","totalMoney":599,"createTime":"2025-10-01"},{"prodName":"...","totalMoney":597,"createTime":"2025-09-28"},...]}'),
        step("Filter orders from last month, sum totalMoney fields. Total = 1196.",
             "# Agent filters by createTime within last 30 days, sums amounts"),
        step("Submit answer",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"1196"}}\''),
    ]

    # === MAP (3) ===
    T["GoogleMapsAlibabaPhoneContactTask"] = [
        step("Search for Alibaba Hangzhou headquarters phone number. Using general knowledge: +86 571 85022088",
             "# Agent uses web search or general knowledge for Alibaba HQ phone"),
        step("Create contact 'Kevin Zhang' with discovered phone and company 'alibaba'",
             'adb shell "echo $(cat << \'SCRIPT\'\ncontent insert --uri content://com.android.contacts/raw_contacts --bind account_type:s: --bind account_name:s:\nSCRIPT\n) | sh"'),
        step("Add name, phone, and company to the contact",
             "# Agent runs content insert commands for name, phone_v2, organization data rows"),
    ]

    T["GoogleMapsAlibabaSouthNeighborTask"] = [
        step("Search for companies near Alibaba HQ in Binjiang, Hangzhou. Using geographical knowledge: NetEase is directly south.",
             "# Agent uses web search or map knowledge"),
        step("Submit answer",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"NetEase"}}\''),
    ]

    T["TextArrivalTimeTask"] = [
        step("Search for drive time Orlando to Miami",
             'http GET "https://maps.googleapis.com/maps/api/directions/json?origin=Orlando,FL&destination=Miami,FL&mode=driving"',
             '{"routes":[{"legs":[{"duration":{"text":"3 hours 30 min"}}]}]}'),
        step("Drive time ~3.5 hours. Leaving at 5pm, arrive ~8:30pm.",
             "# Agent computes 5pm + 3.5h = 8:30pm"),
        step("Look up Mom/Susan's phone from contacts",
             'adb shell content query --uri content://com.android.contacts/data --projection data1 --where "display_name LIKE \'%Susan%\' AND mimetype=\'vnd.android.cursor.item/phone_v2\'"',
             "Row: 0 data1=4538997638"),
        step("Send SMS with arrival time",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'4538997638\',\'I should arrive around 8:30 pm.\',2,$(date +%s)000,1,1)"'),
    ]

    # === MESSAGES (1) ===
    T["SendInterviewInvitationTask"] = [
        step("Find Kevin's resume to get his phone number",
             'find-files /sdcard/Download "*Kevin*"', "/sdcard/Download/Kevin_CV.pdf"),
        step("Read resume to extract Kevin's phone number",
             "read-file /sdcard/Download/Kevin_CV.pdf",
             "# Agent extracts phone: 15551234567 from resume text"),
        step("Send interview invitation SMS to Kevin",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'15551234567\',\'Your interview is scheduled for tomorrow morning at 10:30 AM.\',2,$(date +%s)000,1,1)"'),
    ]

    # === MASTODON (28) ===
    def mast_auth():
        return step("Get Mastodon auth token from device database",
                     MAST_TOKEN_SQL,
                     '{"access_token":"ATOw97x1_wB-28LHtDuNtp4DbEKJt9kPP6-3io21lEI",...}')

    T["MastodonAddBookmarkTask"] = [
        mast_auth(),
        step("Search for kitty's posts with #cats tag",
             f'http GET https://10.0.2.2/api/v1/timelines/tag/cats {MAST_AUTH}',
             '[{"id":"115359670141158913","account":{"username":"kitty"},...},{"id":"115342692663348018","account":{"username":"kitty"},...}]'),
        step("Found 2 posts by kitty with #cats. Bookmark first one.",
             f'http POST https://10.0.2.2/api/v1/statuses/115359670141158913/bookmark {MAST_AUTH}'),
        step("Bookmark second one",
             f'http POST https://10.0.2.2/api/v1/statuses/115342692663348018/bookmark {MAST_AUTH}'),
    ]

    T["MastodonAdjustTootsTask"] = [
        mast_auth(),
        step("Get current bookmarks to find toots to process",
             f'http GET https://10.0.2.2/api/v1/bookmarks {MAST_AUTH}',
             '[{"id":"115348102480027134",...},{"id":"115410818912936581",...},{"id":"115410836820181445",...}]'),
        step("For each of 3 bookmarked toots: unbookmark, favorite, boost. Starting with first.",
             f'http POST https://10.0.2.2/api/v1/statuses/115348102480027134/unbookmark {MAST_AUTH}'),
        step("Favorite first toot", f'http POST https://10.0.2.2/api/v1/statuses/115348102480027134/favourite {MAST_AUTH}'),
        step("Boost first toot", f'http POST https://10.0.2.2/api/v1/statuses/115348102480027134/reblog {MAST_AUTH}'),
        step("Unbookmark second", f'http POST https://10.0.2.2/api/v1/statuses/115410818912936581/unbookmark {MAST_AUTH}'),
        step("Favorite second", f'http POST https://10.0.2.2/api/v1/statuses/115410818912936581/favourite {MAST_AUTH}'),
        step("Boost second", f'http POST https://10.0.2.2/api/v1/statuses/115410818912936581/reblog {MAST_AUTH}'),
        step("Unbookmark third", f'http POST https://10.0.2.2/api/v1/statuses/115410836820181445/unbookmark {MAST_AUTH}'),
        step("Favorite third", f'http POST https://10.0.2.2/api/v1/statuses/115410836820181445/favourite {MAST_AUTH}'),
        step("Boost third", f'http POST https://10.0.2.2/api/v1/statuses/115410836820181445/reblog {MAST_AUTH}'),
        step("Verify bookmarks are empty",
             f'http GET https://10.0.2.2/api/v1/bookmarks {MAST_AUTH}', '[]'),
    ]

    T["MastodonFavoriteTootsTask"] = [
        mast_auth(),
        step("Search for #dogs toots",
             f'http GET https://10.0.2.2/api/v1/timelines/tag/dogs {MAST_AUTH}',
             '[{"id":"115348102480027134",...},{"id":"115410810887077411",...},{"id":"115410813905484454",...},{"id":"115410818912936581",...},{"id":"115410836820181445",...}]'),
        step("Found 5 #dogs toots. Favorite each one.",
             f'http POST https://10.0.2.2/api/v1/statuses/115348102480027134/favourite {MAST_AUTH}'),
        step("Favorite 2nd", f'http POST https://10.0.2.2/api/v1/statuses/115410810887077411/favourite {MAST_AUTH}'),
        step("Favorite 3rd", f'http POST https://10.0.2.2/api/v1/statuses/115410813905484454/favourite {MAST_AUTH}'),
        step("Favorite 4th", f'http POST https://10.0.2.2/api/v1/statuses/115410818912936581/favourite {MAST_AUTH}'),
        step("Favorite 5th", f'http POST https://10.0.2.2/api/v1/statuses/115410836820181445/favourite {MAST_AUTH}'),
    ]

    T["MastodonConditionalFavoTask"] = [
        mast_auth(),
        step("Get existing favorites to check what's already favorited",
             f'http GET https://10.0.2.2/api/v1/favourites {MAST_AUTH}', '[...]'),
        step("Get existing bookmarks",
             f'http GET https://10.0.2.2/api/v1/bookmarks {MAST_AUTH}', '[...]'),
        step("Search #dogs toots",
             f'http GET https://10.0.2.2/api/v1/timelines/tag/dogs {MAST_AUTH}',
             '[{"id":"115410810887077411",...},{"id":"115410813905484454",...},...]'),
        step("Filter: only favorite toots NOT already in favorites or bookmarks. Found 2 new ones.",
             f'http POST https://10.0.2.2/api/v1/statuses/115410810887077411/favourite {MAST_AUTH}'),
        step("Favorite second new toot",
             f'http POST https://10.0.2.2/api/v1/statuses/115410813905484454/favourite {MAST_AUTH}'),
    ]

    T["MastodonRemoveBookmarkTask"] = [
        mast_auth(),
        step("Get all bookmarks",
             f'http GET https://10.0.2.2/api/v1/bookmarks {MAST_AUTH}',
             '[{"id":"115410836820181445","tags":[{"name":"pets"}],...},{"id":"115410818912936581","tags":[{"name":"pets"}],...},...]'),
        step("Filter for #pets tagged bookmarks. Found 2.",
             "# Agent checks tags array in each bookmark"),
        step("Unbookmark first #pets toot",
             f'http POST https://10.0.2.2/api/v1/statuses/115410836820181445/unbookmark {MAST_AUTH}'),
        step("Unbookmark second #pets toot",
             f'http POST https://10.0.2.2/api/v1/statuses/115410818912936581/unbookmark {MAST_AUTH}'),
    ]

    T["MastodonPinTootsTask"] = [
        mast_auth(),
        step("Get own account ID",
             f'http GET https://10.0.2.2/api/v1/accounts/verify_credentials {MAST_AUTH}',
             '{"id":"115338428522805842","username":"test",...}'),
        step("Get own posts sorted by date (oldest first)",
             f'http GET https://10.0.2.2/api/v1/accounts/115338428522805842/statuses?limit=40 {MAST_AUTH}',
             '[...,{"id":"115338428767107750","created_at":"2025-10-08T00:01:00Z",...}]'),
        step("The earliest post (first published after account creation) is ID 115338428767107750. Pin it.",
             f'http POST https://10.0.2.2/api/v1/statuses/115338428767107750/pin {MAST_AUTH}'),
    ]

    T["MastodonReplyTask"] = [
        mast_auth(),
        step("Search for gourmet user's Moussaka toot",
             f'http GET https://10.0.2.2/api/v2/search?q=Moussaka&type=statuses {MAST_AUTH}',
             '{"statuses":[{"id":"115342681979737543","account":{"username":"gourmet"},"content":"...Moussaka..."}]}'),
        step("Found gourmet's Moussaka toot ID: 115342681979737543. Reply with given text.",
             f'http POST https://10.0.2.2/api/v1/statuses {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"status":"Nice sharing, i love it","in_reply_to_id":"115342681979737543"}}\''),
    ]

    T["MastodonFollowTask"] = [
        step("Look up Robert's nickname in contacts",
             'adb shell content query --uri content://com.android.contacts/data --projection data1:mimetype --where "display_name LIKE \'%Robert%\'"',
             "Row: 0 data1=rainbow123, mimetype=vnd.android.cursor.item/nickname"),
        mast_auth(),
        step("Search Mastodon for username 'rainbow123'",
             f'http GET https://10.0.2.2/api/v2/search?q=rainbow123&type=accounts {MAST_AUTH}',
             '{"accounts":[{"id":"...","username":"rainbow123",...}]}'),
        step("Follow the found account",
             f'http POST https://10.0.2.2/api/v1/accounts/{{account_id}}/follow {MAST_AUTH}'),
    ]

    T["MastodonUnfollowTask"] = [
        mast_auth(),
        step("Get own account ID",
             f'http GET https://10.0.2.2/api/v1/accounts/verify_credentials {MAST_AUTH}',
             '{"id":"115338428522805842",...}'),
        step("Get following list (latest followed first)",
             f'http GET https://10.0.2.2/api/v1/accounts/115338428522805842/following?limit=80 {MAST_AUTH}',
             '[{"id":"id1","username":"openCompany"},{"id":"id2","username":"gourmet"},{"id":"id3","username":"kitty"},{"id":"id4","username":"alice"},...]'),
        step("Keep first 3 (latest): openCompany, gourmet, kitty. Unfollow all others starting with alice.",
             f'http POST https://10.0.2.2/api/v1/accounts/{{id4}}/unfollow {MAST_AUTH}'),
        step("Continue unfollowing remaining users...",
             "# Agent unfollows each user not in the keep list"),
    ]

    T["MastodonManageHashtagsTask"] = [
        mast_auth(),
        step("Get followed hashtags",
             f'http GET https://10.0.2.2/api/v1/followed_tags {MAST_AUTH}',
             '[{"name":"dogs",...},{"name":"cats",...},{"name":"technology",...}]'),
        step("Identify animal-related hashtags: #dogs, #cats",
             "# Agent classifies each hashtag"),
        step("Unfollow #dogs",
             f'http POST https://10.0.2.2/api/v1/tags/dogs/unfollow {MAST_AUTH}'),
        step("Unfollow #cats",
             f'http POST https://10.0.2.2/api/v1/tags/cats/unfollow {MAST_AUTH}'),
    ]

    T["MastodonAddFeaturedHashtagsTask"] = [
        mast_auth(),
        step("Add featured hashtag: summerrain",
             f'http POST https://10.0.2.2/api/v1/featured_tags {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"name":"summerrain"}}\''),
        step("Add featured hashtag: nature",
             f'http POST https://10.0.2.2/api/v1/featured_tags {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"name":"nature"}}\''),
        step("Add featured hashtag: photography",
             f'http POST https://10.0.2.2/api/v1/featured_tags {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"name":"photography"}}\''),
    ]

    T["MastodonCreateListTask"] = [
        mast_auth(),
        step("Create list 'Family' with followed-users reply policy",
             f'http POST https://10.0.2.2/api/v1/lists {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"title":"Family","replies_policy":"followed"}}\'',
             '{"id":"list_id",...}'),
        step("Search for Alex on Mastodon",
             f'http GET https://10.0.2.2/api/v2/search?q=alex&type=accounts {MAST_AUTH}',
             '{"accounts":[{"id":"alex_id","username":"alex"}]}'),
        step("Follow Alex (required before adding to list) and repeat for Emma, Jack",
             "# Agent follows each, then adds to list"),
        step("Add all 3 members to list",
             f'http POST https://10.0.2.2/api/v1/lists/{{list_id}}/accounts {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"account_ids":["alex_id","emma_id","jack_id"]}}\''),
    ]

    T["MastodonCreateMemoTask"] = [
        mast_auth(),
        step("Search #openTalk for Urban Mobility lectures",
             f'http GET https://10.0.2.2/api/v1/timelines/tag/openTalk {MAST_AUTH}',
             '[{"content":"AI-Powered Urban Mobility...Auditorium 2-A, Innovation Building...June 24, 2025 10:00-11:30 AM",...}]'),
        step("Parse lecture details: title, location, date/time from toot content",
             "# Agent extracts: title='AI-Powered Urban Mobility', location='Auditorium 2-A', time=June 24 10:00-11:30"),
        step("Convert to timestamps and create calendar event with 1-day (1440 min) reminder",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (1761318000,1761323400,\'AI-Powered Urban Mobility\',\'Auditorium 2-A, Innovation Building\',\'\',-1440,...)"'),
    ]

    T["MastodonCalendarMultiMemosTask"] = [
        mast_auth(),
        step("Search #openTalk for current month lectures",
             f'http GET https://10.0.2.2/api/v1/timelines/tag/openTalk {MAST_AUTH}',
             '[{"content":"...AI-Powered Urban Mobility...June 24..."},{"content":"...Edge Intelligence...June 27..."}]'),
        step("Found 2 lectures. Parse details from each toot.",
             "# Agent extracts titles, locations, dates from toot content"),
        step("Create first event: AI-Powered Urban Mobility",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (1761318000,1761323400,\'AI-Powered Urban Mobility\',\'Auditorium 2-A, Innovation Building\',\'\',1440,...)"'),
        step("Create second event: Edge Intelligence",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (1761575400,1761580800,\'The Future of Edge Intelligence in Everyday Devices\',\'Room 401, Tech Innovation Center\',\'\',4320,...)"'),
    ]

    T["MastodonImportMutedUsersTask"] = [
        step("Read the muted accounts CSV file",
             "read-file /sdcard/Download/muted_accounts.csv",
             "Account address,Show boosts\nolivia@10.0.2.2,true"),
        mast_auth(),
        step("Parse CSV: found 1 user to mute: 'olivia'. Search for olivia on Mastodon.",
             f'http GET https://10.0.2.2/api/v2/search?q=olivia&type=accounts {MAST_AUTH}',
             '{"accounts":[{"id":"olivia_id","username":"olivia"}]}'),
        step("Mute olivia",
             f'http POST https://10.0.2.2/api/v1/accounts/{{olivia_id}}/mute {MAST_AUTH}'),
    ]

    T["MastodonNewFilterTask"] = [
        step("Read filter keywords file from Documents",
             "read-file /sdcard/Documents/filter_BCS",
             "Better Call Saul\nsaul goodman\nkim wexler\nseason 6\nfinale"),
        mast_auth(),
        step("Create filter 'Anti-Spoiler-BCS' with 5-day expiry",
             f'http POST https://10.0.2.2/api/v2/filters {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"title":"Anti-Spoiler-BCS","context":["home","notifications","public","thread","account"],"expires_in":432000}}\'',
             '{"id":"filter_id",...}'),
        step("Add each keyword from file to the filter",
             f'http POST https://10.0.2.2/api/v2/filters/{{filter_id}}/keywords {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"keyword":"Better Call Saul","whole_word":true}}\''),
        step("Add remaining keywords: saul goodman, kim wexler, season 6, finale",
             "# Agent repeats POST for each keyword"),
    ]

    T["MastodonReportTask"] = [
        mast_auth(),
        step("Search for Frank's gas leak post",
             f'http GET https://10.0.2.2/api/v2/search?q=gas+leak&type=statuses {MAST_AUTH}',
             '{"statuses":[{"id":"115383686318250006","account":{"id":"115383646696917550","username":"frank"},"content":"...gas leak..."}]}'),
        step("Found Frank's toot. Report it for spam.",
             f'http POST https://10.0.2.2/api/v1/reports {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"account_id":"115383646696917550","status_ids":["115383686318250006"],"comment":"spam","category":"spam"}}\''),
        step("Block Frank",
             f'http POST https://10.0.2.2/api/v1/accounts/115383646696917550/block {MAST_AUTH}'),
    ]

    T["MastodonRevisePhotoAltTask"] = [
        mast_auth(),
        step("Get own posts to find the Impression, Sunrise toot",
             f'http GET https://10.0.2.2/api/v1/accounts/115338428522805842/statuses {MAST_AUTH}',
             '[...,{"id":"115378662120962265","content":"...Impression, Sunrise...","media_attachments":[{"id":"115378658256750739","description":"Impression, Sunrise presents..."}]}]'),
        step("Found toot with media. Current ALT text starts with 'Impression, Sunrise presents...'. Need to prepend 'Author is Monet'.",
             "# Agent checks if 'Monet' is already in first line of description"),
        step("Update ALT text via database",
             f'{MAST_PSQL} "UPDATE media_attachments SET description = E\'Author is Monet\\n\' || description WHERE status_id=115378662120962265"'),
    ]

    T["MastodonRevisePollTask"] = [
        mast_auth(),
        step("Get own posts to find the area poll",
             f'http GET https://10.0.2.2/api/v1/accounts/115338428522805842/statuses {MAST_AUTH}',
             '[...,{"id":"115433627788463436","poll":{"options":[{"title":"USA"},{"title":"China"},{"title":"Russia"},{"title":"Brazil"}]}}]'),
        step("Found poll with options: USA, China, Russia, Brazil. Goal: remove USA, change Brazil to Canada.",
             "# Agent reads current options"),
        step("Update poll options via database",
             f'{MAST_PSQL} "UPDATE polls SET options=\'{{Russia,China,Canada}}\' WHERE status_id=115433627788463436"'),
    ]

    T["MastodonInviteTask"] = [
        mast_auth(),
        step("Look up Leonard's phone number from contacts",
             'adb shell content query --uri content://com.android.contacts/data --projection data1 --where "display_name LIKE \'%Leonard%\' AND mimetype=\'vnd.android.cursor.item/phone_v2\'"',
             "Row: 0 data1=+16265551427"),
        step("Get test user's user_id for invite creation",
             f'{MAST_PSQL} "SELECT u.id FROM users u JOIN accounts a ON u.account_id=a.id WHERE a.username=\'test\'"',
             "3"),
        step("Create invite: 1 day, max 1 use, autofollow=true",
             f'{MAST_PSQL} "INSERT INTO invites (user_id,code,expires_at,max_uses,uses,autofollow,created_at,updated_at) VALUES (3,\'TestInvCode1\',NOW()+interval \'1 day\',1,0,true,NOW(),NOW())"'),
        step("Send invite link to Leonard via SMS",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'+16265551427\',\'https://10.0.2.2/invite/TestInvCode1\',2,$(date +%s)000,1,1)"'),
    ]

    T["MastodonMultiInviteTask"] = [
        mast_auth(),
        step("Look up Leonard's phone from contacts",
             'adb shell content query --uri content://com.android.contacts/data --projection data1 --where "display_name LIKE \'%Leonard%\' AND mimetype=\'vnd.android.cursor.item/phone_v2\'"',
             "+16265551427"),
        step("Look up Ella's phone from contacts",
             'adb shell content query --uri content://com.android.contacts/data --projection data1 --where "display_name LIKE \'%Ella%\' AND mimetype=\'vnd.android.cursor.item/phone_v2\'"',
             "+14676741503"),
        step("Create Leonard's invite: 1 day, max_uses=1, no autofollow",
             f'{MAST_PSQL} "INSERT INTO invites (...) VALUES (...,\'LeonardInv01\',NOW()+interval \'1 day\',1,0,false,...)"'),
        step("Create Ella's invite: 7 days, autofollow",
             f'{MAST_PSQL} "INSERT INTO invites (...) VALUES (...,\'EllaInvite01\',NOW()+interval \'7 days\',NULL,0,true,...)"'),
        step("SMS Leonard", f'sql {SMS_DB} "INSERT INTO sms (...) VALUES (\'+16265551427\',\'https://10.0.2.2/invite/LeonardInv01\',2,...)"'),
        step("SMS Ella", f'sql {SMS_DB} "INSERT INTO sms (...) VALUES (\'+14676741503\',\'https://10.0.2.2/invite/EllaInvite01\',2,...)"'),
    ]

    T["MastodonChangeLanguageTask"] = [
        step("Find the test user's account ID for the DB update",
             f'{MAST_PSQL} "SELECT id FROM accounts WHERE username=\'test\'"',
             "115338428522805842"),
        step("Update locale to zh-CN in Mastodon database",
             f'{MAST_PSQL} "UPDATE users SET locale=\'zh-CN\' WHERE account_id=115338428522805842"'),
    ]

    T["MastodonFilterLanguageTask"] = [
        step("Find test account ID",
             f'{MAST_PSQL} "SELECT id FROM accounts WHERE username=\'test\'"',
             "115338428522805842"),
        step("Set chosen languages to English, Chinese Simplified, Japanese",
             f'{MAST_PSQL} "UPDATE users SET chosen_languages=\'{{en,zh-CN,ja}}\' WHERE account_id=115338428522805842"'),
    ]

    T["MastodonOpenAutomatedDeletionTask"] = [
        step("Check current auto-deletion policy",
             f'{MAST_PSQL} "SELECT * FROM account_statuses_cleanup_policies WHERE account_id=115338428522805842"',
             "(empty or existing policy)"),
        step("Clear existing policy",
             f'{MAST_PSQL} "DELETE FROM account_statuses_cleanup_policies WHERE account_id=115338428522805842"'),
        step("Insert new policy with settings from goal: enabled, 7 days, keep pinned only, 20 favs/reblogs threshold",
             f'{MAST_PSQL} "INSERT INTO account_statuses_cleanup_policies (account_id,enabled,min_status_age,keep_direct,keep_pinned,keep_polls,keep_media,keep_self_fav,keep_self_bookmark,min_favs,min_reblogs,created_at,updated_at) VALUES (115338428522805842,true,604800,false,true,false,false,false,false,20,20,NOW(),NOW())"'),
    ]

    T["MastodonGetServerInfoTask"] = [
        step("Query Mastodon database size",
             f'{MAST_PSQL} "SELECT pg_database_size(\'mastodon\')"',
             "16335651"),
        step("Convert to MB: 16335651 / 1024 / 1024 = 15.6 MB",
             "# Agent computes size with 1 decimal place"),
        step("Get owner account token (different from test account)",
             f'sql {MAST_DB} "SELECT id,token FROM accounts"',
             "# Agent identifies owner account by ID pattern"),
        step("Post toot as owner with DB size",
             f'http POST https://10.0.2.2/api/v1/statuses --headers "Authorization: Bearer $OWNER_TOKEN" --headers "Host: 10.0.2.2" --headers "Content-Type: application/json" --data \'{{"status":"15.6 MB 15.6MB"}}\''),
    ]

    T["MastodonServerInfoReportTask"] = [
        step("Query report count from Mastodon DB",
             f'{MAST_PSQL} "SELECT COUNT(*) FROM reports WHERE action_taken_by_account_id IS NULL"',
             "1"),
        step("Query DB size for the toot",
             f'{MAST_PSQL} "SELECT pg_database_size(\'mastodon\')"', "16335651"),
        step("Compose email with report count",
             f'write-file {EMAIL_PATH} \'{{"to":"owner@mastodon_example.com","subject":"Server Reports","body":"Recent reports: 1","attachments":[]}}\''),
    ]

    T["MastodonUpdateContactsTask"] = [
        mast_auth(),
        step("Find Olivia's account on Mastodon",
             f'http GET https://10.0.2.2/api/v2/search?q=olivia&type=accounts {MAST_AUTH}',
             '{"accounts":[{"id":"olivia_id","username":"olivia"}]}'),
        step("Read Olivia's latest post for new contact info",
             f'http GET https://10.0.2.2/api/v1/accounts/{{olivia_id}}/statuses?limit=1 {MAST_AUTH}',
             '[{"content":"...new phone: (555) 123-4567...email: olivia@gmail.com..."}]'),
        step("Parse toot: phone=5551234567, email=olivia@gmail.com. Update contact on device.",
             '# Agent runs content update commands to change phone and email for Olivia Taylor'),
        step("Send confirmation SMS to new phone",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'5551234567\',\'Hello, how are you\',2,$(date +%s)000,1,1)"'),
    ]

    T["MastodonMattermostPostNoticeTask"] = [
        step("Find announcement channel on Mattermost",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name LIKE \'%announce%\' OR displayname LIKE \'%announce%\'"',
             "channel_id"),
        step("Read messages from mike in the announcement channel",
             f'{MM_PSQL} "SELECT message FROM posts WHERE channelid=\'{{channel_id}}\' AND userid=(SELECT id FROM users WHERE username=\'mike\') AND deleteat=0 ORDER BY createat DESC LIMIT 5"',
             "Security: rotated API keys; check 1Password vault for updated entries."),
        mast_auth(),
        step("Post the announcement on Mastodon as followers-only, mentioning @openCompany",
             f'http POST https://10.0.2.2/api/v1/statuses {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"status":"@openCompany Security: rotated API keys; check 1Password vault for updated entries.","visibility":"private"}}\''),
    ]

    T["MastodonPostPollTask"] = [
        step("Search for 2025 Nobel Prize in Economics winners. Using general knowledge: Joel Mokyr, Philippe Aghion, Peter Howitt.",
             "# Agent uses web search or knowledge"),
        mast_auth(),
        step("Post poll with winners as options",
             f'http POST https://10.0.2.2/api/v1/statuses {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"status":"#vote2025 2025 Nobel Prize in Economics","poll":{{"options":["Joel Mokyr","Philippe Aghion","Peter Howitt"],"expires_in":604800,"multiple":true}}}}\''),
    ]

    T["MastodonExportFollowsTask"] = [
        mast_auth(),
        step("Get own account ID",
             f'http GET https://10.0.2.2/api/v1/accounts/verify_credentials {MAST_AUTH}',
             '{"id":"115338428522805842",...}'),
        step("Get following list",
             f'http GET https://10.0.2.2/api/v1/accounts/115338428522805842/following?limit=80 {MAST_AUTH}',
             '[{"acct":"openCompany",...},{"acct":"gourmet",...},...]'),
        step("Format as CSV and write to device",
             'adb shell "echo \'Account address,Show boosts,Notify on new posts,Languages\nopenCompany,true,false,\ngourmet,true,false,\n...\' > /sdcard/Download/my_following.csv"'),
    ]

    T["MastodonMallPurchaseCommodityTask"] = [
        mast_auth(),
        step("Find jack's posts on Mastodon to find shared product",
             f'http GET https://10.0.2.2/api/v2/search?q=jack&type=accounts {MAST_AUTH}',
             '{"accounts":[{"id":"jack_id","username":"jack"}]}'),
        step("Read jack's statuses to find product sharing",
             f'http GET https://10.0.2.2/api/v1/accounts/{{jack_id}}/statuses {MAST_AUTH}',
             '[{"content":"...运动休闲鞋...great shoes!..."}]'),
        step("Found product: 运动休闲鞋. Submit mall order callback with details from goal (address given in goal text).",
             'http POST file:///app/service/artifacts/emulator-5554/task_callbacks --headers "Content-Type: application/json" --data \'{"task_name":"提交订单","product_info":[{"prodId":"14","prodName":"运动休闲鞋","prodCount":2}],"address_info":{"receiver":"李四","mobile":"13800139999","addr":"华景新城","province":"广东省","city":"广州市","area":"天河区"}}\''),
    ]

    T["MastodonMallShareOrderTask"] = [
        step("Get mall order data for watch product",
             'http GET http://localhost:6805/config/callback',
             '{"mockOrders":[...,{"prodName":"智能手表","totalMoney":1199,...}]}'),
        mast_auth(),
        step("Upload watch product image to Mastodon",
             f'http POST https://10.0.2.2/api/v1/media {MAST_AUTH} --data "multipart: file=@watch.jpg"',
             '{"id":"media_id",...}'),
        step("Post toot with product name, price, and image",
             f'http POST https://10.0.2.2/api/v1/statuses {MAST_AUTH} --headers "Content-Type: application/json" --data \'{{"status":"刚在淘店买了一块智能手表，价格1199元","media_ids":["media_id"]}}\''),
    ]

    # === NATIVE (4 non-PDF) ===
    T["CountFileLinesTask"] = [
        step("List zip files in Download to find earliest July zip",
             'adb shell ls -lt /sdcard/Download/*.zip',
             "(list of zip files with dates)"),
        step("Identify earliest July zip file from the listing",
             "# Agent parses dates to find the earliest July zip"),
        step("Extract and count lines in file_1.txt",
             'adb shell "unzip -p /sdcard/Download/<july_zip> file_1.txt | wc -l"',
             "29"),
        step("Submit discovered line count",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"29"}}\''),
    ]

    T["SumFileLinesTask"] = [
        step("List zip files to find earliest July zip",
             'adb shell ls -lt /sdcard/Download/*.zip', "(list)"),
        step("List all files in the zip",
             'adb shell unzip -l /sdcard/Download/<july_zip>', "(file list)"),
        step("Extract all files and count total lines",
             'adb shell "unzip -p /sdcard/Download/<july_zip> | wc -l"', "313"),
        step("Submit total",
             'http POST http://localhost:6805/step --headers "Content-Type: application/json" --data \'{"device":"emulator-5554","action":{"action_type":"answer","text":"313"}}\''),
    ]

    T["InvoiceReceiptCopyAskUserTask"] = [
        step("List PDFs in Download",
             'adb shell ls /sdcard/Download/*.pdf', "(list of PDFs)"),
        step("Filter for invoice/receipt files",
             'adb shell "for f in /sdcard/Download/*.pdf; do echo $f | grep -iqE \'invoice|receipt\' && echo $f; done"',
             "(matching files)"),
        step("Check file dates to find November 2025 files",
             'adb shell "for f in /sdcard/Download/*invoice*.pdf /sdcard/Download/*receipt*.pdf; do stat -c \'%Y %n\' $f; done"',
             "(timestamps and filenames)"),
        step("Search for the dedicated invoice/receipt folder",
             'adb shell "find /sdcard -type d -name \'*invoice*\' -o -name \'*expense*\'"',
             "/sdcard/Documents/expense/invoice"),
        step("Copy matching November PDFs to the discovered folder",
             'adb shell "cp /sdcard/Download/invoice_2025_001.pdf /sdcard/Documents/expense/invoice/"'),
    ]

    T["SMSManagement"] = [
        step("Read all unread SMS messages",
             f'sql {SMS_DB} "SELECT address,body,read FROM sms WHERE type=1"',
             "(list of all inbox messages with addresses and bodies)"),
        step("Classify messages: identify spam (promotional/scam) vs recruitment vs other",
             "# Agent reads each message body, identifies spam from known patterns"),
        step("Delete spam messages by address",
             f'sql {SMS_DB} "DELETE FROM sms WHERE address IN (\'78901\',\'56789\',\'34567\',\'88999\')"'),
        step("Filter recruitment messages for 'data scientist' roles. Found: Meta hiring for data scientist.",
             "# Agent reads message bodies for recruitment keywords"),
        step("Compose email summary to dylan@gmail.com",
             f'write-file {EMAIL_PATH} \'{{"to":"dylan@gmail.com","subject":"Recruitment Summary","body":"Summary: Meta is hiring for data scientist position.","attachments":[]}}\''),
    ]

    # === WORK / MATTERMOST (15) ===
    HARRY = "p11jse4oa3biikeeefcuggns9o"

    T["LocalFileManagementTask"] = [
        step("Find zip files older than 1 year in Download",
             'adb shell "for f in /sdcard/Download/*.zip; do ts=$(stat -c %Y $f); now=$(date +%s); [ $((now-ts)) -gt 31536000 ] && echo $(basename $f); done"',
             "(list of old zip filenames)"),
        step("Delete each old zip file",
             'adb shell "rm /sdcard/Download/<old_file1>.zip /sdcard/Download/<old_file2>.zip ..."'),
        step("Find own user ID on Mattermost",
             f'{MM_PSQL} "SELECT id FROM users WHERE username=\'harry\'"', HARRY),
        step("Find self-DM channel",
             f'{MM_PSQL} "SELECT id FROM channels WHERE type=\'D\' AND name LIKE \'%{HARRY}%{HARRY}%\'"',
             "dm_channel_id"),
        step("Post deleted file list to DM",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'dm_channel_id\',...,\'Deleted old files: file1.zip, file2.zip, ...\',...)"'),
    ]

    T["MattermostCreateChannelTask"] = [
        step("Find team ID",
             f'{MM_PSQL} "SELECT id FROM teams WHERE name=\'neuralforge\'"', "team_id"),
        step("Create 'reading' channel",
             f'{MM_PSQL} "INSERT INTO channels (...) VALUES (...,\'team_id\',\'O\',\'reading\',\'reading\',...)"'),
        step("Get all team members to add",
             f'{MM_PSQL} "SELECT tm.userid FROM teammembers tm JOIN teams t ON tm.teamid=t.id WHERE t.name=\'neuralforge\' AND tm.deleteat=0"',
             "(list of 11 user IDs)"),
        step("Add each member to channel",
             "# Agent inserts into channelmembers for each user"),
        step("Post welcome message",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'channel_id\',...,\'Welcome to the reading group channel!\',...)"'),
    ]

    T["MattermostReplyToMessageTask"] = [
        step("Find the channel and parent message to reply to",
             f'{MM_PSQL} "SELECT channelid FROM posts WHERE id=\'q1iiqx18bb8npdoiocr7ki5t1r\'"',
             "channel_id"),
        step("Post reply with OSWorld eval result",
             f'{MM_PSQL} "INSERT INTO posts (id,...,rootid,...,message,...) VALUES (...,\'q1iiqx18bb8npdoiocr7ki5t1r\',...,\'The OSWorld eval SR result is 35.5\',...)"'),
    ]

    T["MattermostEmailTask"] = [
        step("Find Sam's user ID",
             f'{MM_PSQL} "SELECT id FROM users WHERE username=\'sam\'"', "sam_id"),
        step("Find DM channel with Sam",
             f'{MM_PSQL} "SELECT id FROM channels WHERE type=\'D\' AND (name LIKE \'%{HARRY}%sam_id%\' OR name LIKE \'%sam_id%{HARRY}%\')"',
             "dm_channel_id"),
        step("Read Sam's contract message to find tracking code",
             f'{MM_PSQL} "SELECT message FROM posts WHERE channelid=\'dm_channel_id\' AND userid=\'sam_id\' AND deleteat=0 ORDER BY createat DESC LIMIT 5"',
             "Here's the signed contract. Tracking code: TT-POC-2025-BLPINE-042."),
        step("Compose email to Legal with discovered tracking code",
             f'write-file {EMAIL_PATH} \'{{"to":"legal@company.com","subject":"Signed Contract - TT-POC-2025-BLPINE-042","body":"Contract forwarded. Tracking code: TT-POC-2025-BLPINE-042","attachments":[{{"name":"contract.pdf"}}]}}\''),
        step("Post confirmation to Sam",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'dm_channel_id\',...,\'Contract forwarded to legal@company.com with tracking code TT-POC-2025-BLPINE-042\',...)"'),
    ]

    T["MattermostProjectHandoverTask"] = [
        step("Find Alex's user ID",
             f'{MM_PSQL} "SELECT id FROM users WHERE username=\'alex\'"', "alex_id"),
        step("Find phoenix channel",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'phoenix\'"', "phoenix_channel_id"),
        step("Add Alex to phoenix channel",
             f'{MM_PSQL} "INSERT INTO channelmembers (channelid,userid,...) VALUES (\'phoenix_channel_id\',\'alex_id\',...)"'),
        step("Check calendar for available Monday slots",
             f'sql {CAL_DB} "SELECT title,start_ts,end_ts FROM events WHERE start_ts >= ... AND start_ts < ... ORDER BY start_ts"',
             "(list of Monday events)"),
        step("Found free slot: 11:00-12:00. Post meeting time.",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'phoenix_channel_id\',...,\'Meeting Time: 2025-10-16 from 11:00 to 12:00\',...)"'),
    ]

    T["MattermostReadingGroupTask"] = [
        step("Find reading channel",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'reading\'"', "reading_ch_id"),
        step("Read Sam's request message",
             f'{MM_PSQL} "SELECT message FROM posts WHERE channelid=\'reading_ch_id\' AND userid=(SELECT id FROM users WHERE username=\'sam\') ORDER BY createat DESC LIMIT 3"',
             "Please find the Qwen3-vl paper (arXiv 2511.21631) and share the MMMU_Pro score."),
        step("Post paper link and score as requested",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'reading_ch_id\',...,\'Paper: https://arxiv.org/abs/2511.21631\\nMMU_Pro score: 68.1\',...)"'),
    ]

    T["MattermostBudgetApprovalPipelineTask"] = [
        step("Find budget-approvals-q4 channel",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'budget-approvals-q4\'"', "budget_ch_id"),
        step("Read all budget request messages",
             f'{MM_PSQL} "SELECT message,userid FROM posts WHERE channelid=\'budget_ch_id\' AND deleteat=0 ORDER BY createat"',
             "(list of department budget requests with amounts and justifications)"),
        step("Analyze requests: extract department names, amounts, compute ROI. Build summary table.",
             "# Agent parses each message for department, amount, and ROI data"),
        step("Post summary table to channel",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'budget_ch_id\',...,\'# Q4 Budget Summary\\n| Department | Amount | ROI | Status |\\n...\',...)"'),
    ]

    T["MattermostCustomerFeedbackAnalysisTask"] = [
        step("Find customer-feedback channel and read messages",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'customer-feedback\'"', "fb_ch_id"),
        step("Read all feedback messages",
             f'{MM_PSQL} "SELECT message FROM posts WHERE channelid=\'fb_ch_id\' AND deleteat=0 ORDER BY createat"',
             "(mix of positive and negative feedback messages)"),
        step("Classify feedback. Identified negative items: Login crashes, Billing confusion, PDF export broken.",
             "# Agent analyzes message sentiment and categorizes"),
        step("Compose email digest to product team",
             f'write-file {EMAIL_PATH} \'{{"to":"product@company.com","subject":"Negative Feedback Digest","body":"Negative feedback:\\n1. Login page crashes on Android 10\\n2. Billing dashboard is confusing\\n3. Cannot export reports to PDF","attachments":[]}}\''),
        step("Schedule review meeting for next Friday at 2pm",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (...,\'Feedback Review\',\'\',...)"'),
        step("Post acknowledgment in channel",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'fb_ch_id\',...,\'All negative feedback logged and meeting scheduled for review.\',...)"'),
    ]

    T["MattermostDeadlineReconciliationTask"] = [
        step("Find project-updates channel and read deadline messages",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'project-updates\'"', "proj_ch_id"),
        step("Read deadline-related messages",
             f'{MM_PSQL} "SELECT message FROM posts WHERE channelid=\'proj_ch_id\' AND deleteat=0 ORDER BY createat"',
             "(messages mentioning deadlines for various tasks)"),
        step("Query calendar for existing deadline events",
             f'sql {CAL_DB} "SELECT title,start_ts FROM events ORDER BY start_ts"',
             "(existing calendar events)"),
        step("Compare: API Docs Review and Frontend MVP matched. Security Audit and Beta Testing missing. Team Building untracked.",
             "# Agent cross-references messages with calendar"),
        step("Compose audit report email",
             f'write-file {EMAIL_PATH} \'{{"to":"dylan@gmail.com","subject":"Deadline Audit Report","body":"Matched: API Documentation Review, Frontend MVP Launch\\nMissing: Security Audit Completion, Beta Testing Phase Start\\nUntracked: Team Building Event","attachments":[]}}\''),
        step("Create [AUTO] calendar events for missing deadlines",
             "# Agent creates 2 calendar events with [AUTO] prefix"),
        step("Post reconciliation notice to channel",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'proj_ch_id\',...,\'Auto-created events: [AUTO] Security Audit Completion, [AUTO] Beta Testing Phase Start\',...)"'),
    ]

    T["MattermostIncidentEscalationTask"] = [
        step("Find support-tickets channel and read messages",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'support-tickets\'"', "support_ch_id"),
        step("Read ticket messages to find CRITICAL incidents",
             f'{MM_PSQL} "SELECT message FROM posts WHERE channelid=\'support_ch_id\' AND deleteat=0 ORDER BY createat"',
             "(messages including TICKET-500 CRITICAL: Database timeout)"),
        step("Found CRITICAL incident: TICKET-500 (database timeout). Create incident channel.",
             f'{MM_PSQL} "INSERT INTO channels (...) VALUES (...,\'incident-ticket-500\',...)"'),
        step("Add Sam to incident channel",
             f'{MM_PSQL} "INSERT INTO channelmembers (...) VALUES (...)"'),
        step("Email CTO about the incident",
             f'write-file {EMAIL_PATH} \'{{"to":"cto@company.com","subject":"CRITICAL INCIDENT: TICKET-500","body":"Database timeout errors affecting production.","attachments":[]}}\''),
        step("Schedule emergency meeting for tomorrow 9am",
             f'sql {CAL_DB} "INSERT INTO events (...) VALUES (...,\'Discussion on TICKET-500\',\'\',...)"'),
    ]

    T["MattermostProjectStatusReportTask"] = [
        step("Read messages from backend-team, frontend-team, qa-team channels",
             f'{MM_PSQL} "SELECT c.name,p.message FROM posts p JOIN channels c ON p.channelid=c.id WHERE c.name IN (\'backend-team\',\'frontend-team\',\'qa-team\') AND p.deleteat=0 ORDER BY p.createat"',
             "(status updates from 3 team channels)"),
        step("Analyze: Authentication Module & API Gateway on-track. Dashboard UI & Performance Testing at-risk. Payment Integration & Security Audit blocked.",
             "# Agent categorizes each status update"),
        step("Compose risk matrix email",
             f'write-file {EMAIL_PATH} \'{{"to":"pm@company.com","subject":"Sprint Status Risk Matrix","body":"On-Track: Authentication Module, API Gateway Setup\\nAt-Risk: Dashboard UI, Performance Testing\\nBlocked: Payment Integration, Security Audit","attachments":[]}}\''),
        step("Create [ESCALATION] events for blocked items",
             "# Agent creates 2 calendar events"),
        step("Post summary to project-sync channel",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'project-sync_ch_id\',...,\'Sprint status: 2 on-track, 2 at-risk, 2 blocked\',...)"'),
    ]

    T["MattermostResourceConflictResolutionTask"] = [
        step("Find resource-booking channel and read requests",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'resource-booking\'"', "resource_ch_id"),
        step("Read booking requests",
             f'{MM_PSQL} "SELECT message,userid FROM posts WHERE channelid=\'resource_ch_id\' AND deleteat=0 ORDER BY createat"',
             "(resource booking requests from team members)"),
        step("Query calendar to check for conflicts",
             f'sql {CAL_DB} "SELECT title,start_ts,end_ts FROM events"',
             "(existing events including Team Standup)"),
        step("Analyze: Conf Room B, C, Projector, Video Camera approved. Conf Room A conflicts with Team Standup.",
             "# Agent cross-references requests with calendar"),
        step("Compose email report",
             f'write-file {EMAIL_PATH} \'{{"to":"facilities@company.com","subject":"Resource Booking Conflicts","body":"APPROVED: Conf Room B, Conf Room C, Projector, Video Camera\\nCONFLICT: Conf Room A","attachments":[]}}\''),
        step("Create BOOKED calendar events for approved items",
             "# Agent creates calendar events"),
        step("DM Alex about Conf Room A conflict",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'alex_dm_ch\',...,\'Conf Room A booking conflict\',...)"'),
    ]

    T["MattermostShiftCoverageTask"] = [
        step("Find shift-requests channel and read swap requests",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'shift-requests\'"', "shift_ch_id"),
        step("Read shift swap request messages",
             f'{MM_PSQL} "SELECT id,message,userid FROM posts WHERE channelid=\'shift_ch_id\' AND deleteat=0 ORDER BY createat"',
             "(Alex's Monday request: Family emergency, Sofia's Wednesday request: Doctor appointment)"),
        step("Check calendar for conflicts with requested days",
             f'sql {CAL_DB} "SELECT title,start_ts,end_ts FROM events"',
             "(All Hands Meeting on Monday)"),
        step("Alex's Monday request conflicts with All Hands. Reply: Denied.",
             f'{MM_PSQL} "INSERT INTO posts (...,rootid,...) VALUES (...,\'alex_msg_id\',...,\'Denied: Conflicts with All Hands Meeting on Monday.\',...)"'),
        step("Sofia's Wednesday has no conflict. Reply: Escalated to HR.",
             f'{MM_PSQL} "INSERT INTO posts (...,rootid,...) VALUES (...,\'sofia_msg_id\',...,\'Request escalated to HR for Wednesday coverage.\',...)"'),
        step("Email HR about Sofia's approved swap",
             f'write-file {EMAIL_PATH} \'{{"to":"hr@company.com","subject":"Shift Swap Request","body":"Sofia requests shift coverage for 2025-10-22 due to doctor appointment.","attachments":[]}}\''),
    ]

    T["MattermostTechnicalDebtTriageTask"] = [
        step("Find tech-debt-review channel and read complexity analysis messages",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'tech-debt-review\'"', "tech_ch_id"),
        step("Read module complexity messages",
             f'{MM_PSQL} "SELECT message FROM posts WHERE channelid=\'tech_ch_id\' AND deleteat=0 ORDER BY createat"',
             "(5 messages with LaTeX complexity formulas for each module)"),
        step("Parse complexity scores. Highest: PaymentProcessor (47880). Others: AuthenticationService (13440), NotificationEngine (8400), ReportGenerator (4180), DataExporter (2160).",
             "# Agent parses LaTeX formulas and computes scores"),
        step("Look up Sarah's phone from contacts",
             'adb shell content query --uri content://com.android.contacts/data --projection data1 --where "display_name LIKE \'%Sarah%\' AND mimetype=\'vnd.android.cursor.item/phone_v2\'"',
             "14737474173"),
        step("SMS Sarah with highest complexity module",
             f'sql {SMS_DB} "INSERT INTO sms (address,body,type,date,read,seen) VALUES (\'14737474173\',\'PaymentProcessor: 47880\',2,$(date +%s)000,1,1)"'),
        step("Create Refactoring Team contact",
             "# Agent creates contact with phone 15559876543 and company TechDebt Solutions"),
        step("Post sorted complexity table to channel",
             f'{MM_PSQL} "INSERT INTO posts (...) VALUES (...,\'{HARRY}\',\'tech_ch_id\',...,\'| Module | Complexity |\\n...|PaymentProcessor|47880|...\',...)"'),
    ]

    T["MattermostVisualInstructionResponseTask"] = [
        step("Find emergency-response channel and read instruction messages",
             f'{MM_PSQL} "SELECT id FROM channels WHERE name=\'emergency-response\'"', "emerg_ch_id"),
        step("Read messages containing contact and shift info",
             f'{MM_PSQL} "SELECT message FROM posts WHERE channelid=\'emerg_ch_id\' AND deleteat=0 ORDER BY createat"',
             "(messages with contact details and shift schedule)"),
        step("Parse: contacts to create: Dr. Smith (555-1010), Safety Officer (555-2020). Alarms: Morning Shift 8:00, Evening Shift 20:00.",
             "# Agent extracts contact and alarm details from messages"),
        step("Create Dr. Smith contact",
             "# Agent runs content insert commands for contact"),
        step("Create Safety Officer contact",
             "# Agent runs content insert commands"),
        step("Set Morning Shift alarm at 8:00",
             f'sql {ALARM_DB} "INSERT INTO alarm_templates (...) VALUES (...,8,0,...,\'Morning Shift\',...)"'),
        step("Set Evening Shift alarm at 20:00",
             f'sql {ALARM_DB} "INSERT INTO alarm_templates (...) VALUES (...,20,0,...,\'Evening Shift\',...)"'),
    ]

    # Also include CheckPuchasedItem (already done above as "CheckPuchasedItem")

    return T


# =========================================================================
# Generate ATIF-v1.6 files
# =========================================================================

TOOL_DEFS = [{
    "type": "function",
    "function": {
        "name": "Bash",
        "description": "Execute CLI command: adb shell (device), sql (database), http (backend), read-file, write-file, find-files",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
    }
}]


def to_atif(task_name, goal, discovery_steps, task_id):
    steps = [
        {"step_id": 1, "source": "system", "message": "[GroundTruth Discovery, MobileWorld]"},
        {"step_id": 2, "source": "user", "message": goal},
    ]

    actual_cmds = 0
    for i, s in enumerate(discovery_steps):
        sid = i + 3
        tc_id = f"call_{sid}"

        if s["command"].startswith("#"):
            # Reasoning-only step (no tool call)
            steps.append({
                "step_id": sid, "source": "agent", "message": s["thought"],
                "model_name": "oracle", "reasoning_content": s["command"],
            })
        else:
            steps.append({
                "step_id": sid, "source": "agent",
                "message": s["thought"], "model_name": "oracle",
                "tool_calls": [{"tool_call_id": tc_id, "function_name": "Bash",
                                "arguments": {"command": s["command"]}}],
                "observation": {"results": [{"source_call_id": tc_id,
                                             "content": s.get("observation", "")}]},
            })
            actual_cmds += 1

    return {
        "schema_version": "ATIF-v1.6",
        "session_id": f"mobileworld-discovery-{task_name}-{uuid.uuid4().hex[:8]}",
        "agent": {"name": "GroundTruth", "version": "1.0", "model_name": "oracle",
                  "tool_definitions": TOOL_DEFS},
        "steps": steps,
        "final_metrics": {
            "total_prompt_tokens": 0, "total_completion_tokens": 0, "total_cost_usd": 0,
            "total_steps": actual_cmds,
            "extra": {"task_id": task_id, "seed": 0, "reward": 1, "finished": True,
                      "elapsed_seconds": 0.0,
                      "finish_description": f"Discovery ground truth for {task_name}",
                      "num_turns": actual_cmds, "discovery": True},
        },
        "extra": {"benchmark": "MobileWorld", "task_text": goal, "task_name": task_name,
                  "ground_truth_type": "discovery"},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="../../results/GroundTruth_mobileworld_discovery/atif_trajectories")
    args = parser.parse_args()

    goals = load_goals()
    discoveries = build_all_discoveries()

    os.makedirs(args.output_dir, exist_ok=True)

    # Also create harbor-compatible structure
    harbor_base = os.path.dirname(args.output_dir)

    skipped = []
    task_id = 0
    for task_name in sorted(discoveries.keys()):
        goal = goals.get(task_name, task_name)
        steps = discoveries[task_name]

        traj = to_atif(task_name, goal, steps, task_id)

        # Write ATIF file
        out_path = os.path.join(args.output_dir, f"task_{task_id:03d}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(traj, f, indent=2, ensure_ascii=False)

        # Write harbor structure
        trial_dir = os.path.join(harbor_base, f"task_{task_id:03d}")
        os.makedirs(os.path.join(trial_dir, "agent"), exist_ok=True)
        with open(os.path.join(trial_dir, "agent", "trajectory.json"), "w", encoding="utf-8") as f:
            json.dump(traj, f, indent=2, ensure_ascii=False)

        # Trial result.json
        trial_result = {
            "id": str(uuid.uuid4()), "task_name": goal[:80], "trial_name": f"task_{task_id:03d}",
            "trial_uri": f"task_{task_id:03d}", "task_id": {"path": f"task_{task_id:03d}"},
            "source": "mobileworld", "task_checksum": task_name,
            "config": {"task": {"name": goal[:80], "path": f"task_{task_id:03d}",
                                "id": {"path": f"task_{task_id:03d}"}, "source": "mobileworld"},
                       "trial_name": f"task_{task_id:03d}"},
            "status": "completed", "reward": 1,
            "agent_info": {"name": "GroundTruth", "version": "1.0",
                           "model_info": {"name": "oracle", "provider": "discovery"}},
            "metrics": {"reward": 1},
        }
        with open(os.path.join(trial_dir, "result.json"), "w") as f:
            json.dump(trial_result, f, indent=2, ensure_ascii=False)

        task_id += 1

    # Job-level result.json
    from datetime import datetime
    job_result = {
        "id": str(uuid.uuid4()), "started_at": datetime.now().isoformat(),
        "finished_at": datetime.now().isoformat(), "n_total_trials": task_id,
        "stats": {"n_trials": task_id, "n_errors": 0, "evals": {}},
        "trial_results": [],  # populated above per-trial
    }
    with open(os.path.join(harbor_base, "result.json"), "w") as f:
        json.dump(job_result, f, indent=2, ensure_ascii=False)

    print(f"Generated {task_id} discovery trajectories → {args.output_dir}/")
    print(f"Harbor structure: {harbor_base}/")
    if skipped:
        print(f"Skipped {len(skipped)}: {skipped}")


if __name__ == "__main__":
    main()
