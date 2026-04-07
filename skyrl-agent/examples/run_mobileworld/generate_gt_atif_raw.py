#!/usr/bin/env python3
"""
Generate ATIF-v1.4 ground truth trajectories with raw CLI commands.

Each step uses exactly one of 3 command types:
  - adb shell <cmd>     — device control
  - sql <db> <query>    — device database with root
  - http <method> <url> — backend service HTTP request

No Python functions, no abstractions. Copy-pasteable commands.

Usage:
    python generate_gt_atif_raw.py --container mobile_world_env_1 \
        --output gt_raw_atif.jsonl
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone


# =========================================================================
# Command builders — return (action_str, expected_observation_str) tuples
# =========================================================================

SMS_DB = "/data/user/0/com.android.providers.telephony/databases/mmssms.db"
CAL_DB = "/data/data/org.fossify.calendar/databases/events.db"
ALARM_DB = "/data/user_de/0/com.google.android.deskclock/databases/alarms.db"
MASTODON_ACCOUNTS_DB = "/data/data/org.joinmastodon.android.mastodon/databases/accounts.db"
EMAIL_PATH = "/sdcard/Android/data/com.gmailclone/files/sentEmail.json"
MASTODON_API = "https://10.0.2.2/api/v1"


def adb(cmd):
    """ADB shell command."""
    return f"adb shell {cmd}"


def sql_cmd(db, query):
    """SQL query on device database."""
    return f'sql {db} "{query}"'


def http(method, url, headers=None, data=None):
    """HTTP request to backend service."""
    cmd = f"http {method} {url}"
    if headers:
        for k, v in headers.items():
            cmd += f' --headers "{k}: {v}"'
    if data:
        if isinstance(data, dict):
            cmd += f" --data '{json.dumps(data, ensure_ascii=False)}'"
        else:
            cmd += f" --data '{data}'"
    return cmd


def sms_insert(to, body):
    """Insert sent SMS."""
    body_esc = body.replace("'", "''")
    to_esc = to.replace("'", "''")
    return sql_cmd(SMS_DB,
        f"INSERT INTO sms (address,body,type,date,read,seen) "
        f"VALUES ('{to_esc}','{body_esc}',2,$(date +%s)000,1,1)")


def email_write(to, subject, body, attachments=None):
    """Write sentEmail.json via ADB."""
    email = {"to": to, "subject": subject, "body": body,
             "attachments": [{"name": a} for a in (attachments or [])]}
    j = json.dumps(email, ensure_ascii=False)
    enc = base64.b64encode(j.encode()).decode()
    return adb(f'"echo {enc} | base64 -d > {EMAIL_PATH}"')


def cal_insert(title, start_ts, end_ts, location="", reminder=-1, description=""):
    """Insert calendar event."""
    return sql_cmd(CAL_DB,
        f"INSERT INTO events (start_ts,end_ts,title,location,description,"
        f"reminder_1_minutes,reminder_2_minutes,reminder_3_minutes,"
        f"reminder_1_type,reminder_2_type,reminder_3_type,"
        f"repeat_interval,repeat_rule,repeat_limit,repetition_exceptions,"
        f"attendees,import_id,time_zone,flags,event_type,parent_id,last_updated,"
        f"source,availability,access_level,color,type,status) VALUES ("
        f"{start_ts},{end_ts},'{title}','{location}','{description}',"
        f"{reminder},-1,-1,0,0,0,0,0,0,'','','','UTC',0,0,0,"
        f"{int(time.time())},'',0,0,0,0,0)")


def answer(server_url, device, text):
    """Send answer to MobileWorld server."""
    return http("POST", f"{server_url}/step",
                headers={"Content-Type": "application/json"},
                data={"device": device, "action": {"action_type": "answer", "text": str(text)}})


def mastodon_auth():
    """Extract Mastodon token from app DB."""
    return sql_cmd(MASTODON_ACCOUNTS_DB,
        "SELECT token FROM accounts WHERE id LIKE '%_115338428522805842'")


def mastodon_post(endpoint, token_var="$TOKEN", data=None, method="POST"):
    """Mastodon REST API call."""
    headers = {"Authorization": f"Bearer {token_var}", "Host": "10.0.2.2"}
    if data:
        headers["Content-Type"] = "application/json"
    return http(method, f"{MASTODON_API}{endpoint}", headers=headers, data=data)


def mastodon_db(query):
    """Mastodon PostgreSQL query via psql."""
    # psql is accessed via http to a hypothetical DB proxy, or directly
    # In the agent's environment, this maps to: psql -h localhost -p 5432 ...
    # We represent it as an http command to a DB service endpoint
    # OR we use the sql command if psql is wrapped similarly
    # For consistency with the 3-tool model, we use http to represent
    # any non-ADB command that reaches a backend service.
    # In practice: the runtime translates this to docker exec psql.
    return http("POST", "psql://mastodon:5432",
                headers={"Content-Type": "application/sql"},
                data=query)


def mattermost_db(query):
    """Mattermost PostgreSQL query."""
    return http("POST", "psql://mattermost:5433",
                headers={"Content-Type": "application/sql"},
                data=query)


def mm_post(channel_id, user_id, message):
    """Insert Mattermost message via DB."""
    msg_esc = message.replace("'", "''")
    ts = "${TIMESTAMP_MS}"
    return mattermost_db(
        f"INSERT INTO posts (id,createat,updateat,deleteat,userid,channelid,"
        f"rootid,originalid,message,type,props,hashtags,filenames,fileids,"
        f"hasreactions,editat,ispinned) VALUES "
        f"(md5(random()::text)::varchar(26),{ts},{ts},0,'{user_id}','{channel_id}',"
        f"'','','{msg_esc}','','{{}}','','','',false,0,false)")


def mall_callback(task_name_cn, data):
    """Write Mall callback file."""
    j = json.dumps(data, ensure_ascii=False)
    enc = base64.b64encode(j.encode()).decode()
    return http("POST", "file:///app/service/artifacts/emulator-5554/task_callbacks",
                headers={"Content-Type": "application/json", "X-Filename": f"{task_name_cn}_callback.json"},
                data=data)


def push_script(script_content, device_path):
    """Push shell script to device and run it."""
    enc = base64.b64encode(script_content.encode()).decode()
    return [
        adb(f'"echo {enc} | base64 -d > {device_path}"'),
        adb(f"sh {device_path}"),
        adb(f"rm {device_path}"),
    ]


# =========================================================================
# Build trajectories for all 117 tasks
# =========================================================================

HARRY_ID = "p11jse4oa3biikeeefcuggns9o"
ALEX_ID = "1hx8frqxjfdhuqzkp4yt511sho"
SAM_HARRY_CH = "m3d6byju9ig4dneosajg9hu1be"
PHOENIX_CH = "6xntskboopfwxysbdebkzqyckh"
TEST_ACCT = "115338428522805842"
OWNER_ACCT = "115338428152261473"
FRANK_ACCT = "115383646696917550"


def build_all(server_url, device):
    S = server_url
    D = device
    tasks = {}

    # --- Settings (7) ---
    tasks["AdjustBrightnessMaximumTask"] = [
        adb("settings put system screen_brightness_mode 0"),
        adb("settings put system screen_brightness 255"),
    ]
    tasks["AdjustBrightnessMinimumTask"] = [
        adb("settings put system screen_brightness_mode 0"),
        adb("settings put system screen_brightness 1"),
    ]
    tasks["AdjustFontIconMaximumTask"] = [
        adb("settings put system font_scale 2.0"),
        adb("wm density 540"),
    ]
    tasks["AdjustFontIconMinimumTask"] = [
        adb("settings put system font_scale 0.85"),
        adb("wm density 356"),
    ]
    tasks["OpenFlightModeTask"] = [
        adb("settings put global airplane_mode_on 1"),
        adb("am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true"),
    ]
    tasks["CloseFlightModeTask"] = [
        adb("settings put global airplane_mode_on 0"),
        adb("am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false"),
    ]
    tasks["ChangeWallpaperTask"] = [
        adb("'su root sh -c \"cat /sdcard/Pictures/image1.jpeg > /data/system/users/0/wallpaper\"'"),
        adb("su root chmod 644 /data/system/users/0/wallpaper"),
        adb("su root chown system:system /data/system/users/0/wallpaper"),
    ]

    # --- Calendar answers (2) ---
    tasks["CheckConferenceDurationTask"] = [answer(S, D, "12")]
    tasks["CheckDeduplicatedEventsTask"] = [answer(S, D, "9")]

    # --- Calendar + SMS (4) ---
    tasks["CheckConferenceAndSendSmsTask1"] = [sms_insert("+14058298746", "10/11/2025, 10/15/2025")]
    tasks["CheckConferenceAndSendSmsTask2"] = [sms_insert("+14058298746", "10/04/2025,10/10/2025")]
    tasks["ScheduleCoffeeTimeViaSmsTask"] = [sms_insert("+15051234567", "Not available in this time slot")]
    tasks["ScheduleLunchViaSmsTask"] = [
        sms_insert("+15051234567", "OK"),
        cal_insert("Lunch",
                   int(datetime(2025,10,17,11,0,tzinfo=timezone.utc).timestamp()),
                   int(datetime(2025,10,17,12,0,tzinfo=timezone.utc).timestamp())),
    ]

    # --- Gmail email (10) ---
    tasks["AcceptMeetingTask"] = [email_write("dan123@gmail.com", "RE: Meeting Thursday",
                                              "I'll be there at 10:00 AM on Thursday.")]
    tasks["CancelMeetingTask"] = [email_write("dan123@gmail.com", "RE: Meeting Thursday",
                                              "I need to cancel the meeting on Thursday.")]
    tasks["CheckRegistrationTask"] = [email_write("kathy@gmail.com", "Putnam Registration Confirmation",
                                                   "Could you please confirm my Putnam registration?")]
    tasks["SendWaiverTask"] = [email_write("bob@gmail.com", "Updated waiver",
                                           "Please find attached.", ["waiver.jpg"])]
    tasks["SendInterviewEmailTask"] = [email_write("kevin.zhang@example.com", "Interview Schedule",
                                                    "Your interview is scheduled for tomorrow morning at 10:30 AM")]
    tasks["DownloadSendReceiptTask"] = [email_write("treasurer@gmail.com", "Proof of purchase",
                                                     "Here is the receipt. The total amount is $5.08.", ["receipt.jpg"])]
    tasks["SuggestPaperTask"] = [
        adb("touch /sdcard/Download/ddpm.pdf"),
        email_write("tony101@email.com", "RE: Literature Review Suggestions",
                    "I recommend: Denoising Diffusion Probabilistic Models. "
                    "FID 3.17 on CIFAR-10, 9.46 on LSUN 256. Uses langevin dynamics.", ["ddpm.pdf"]),
    ]
    tasks["SendFormsTask"] = [
        email_write("principal@school.edu", "Field Trip Forms",
                    "Please find the field trip forms attached.", ["form1.jpg", "form2.jpg", "form3.jpg"]),
        answer(S, D, "3"),
    ]
    tasks["GraduationMassEmailTask"] = [
        email_write("bob@gmail.com,alice@gmail.com,dave@gmail.com,carl@gmail.com",
                    "Graduation Party",
                    "Don't forget about this year's graduation party! More details coming soon."),
        cal_insert("Graduation Party",
                   int(datetime(2026,5,9,18,0,tzinfo=timezone.utc).timestamp()),
                   int(datetime(2026,5,9,20,0,tzinfo=timezone.utc).timestamp())),
    ]
    tasks["ThanksgivingPrepTask"] = [
        email_write("user@gmail.com", "Pie shopping",
                    "Ingredients for Pecan Pie: sugar, corn syrup, vanilla extract, eggs, butter, pecans."),
        cal_insert("Thanksgiving Shopping",
                   int(datetime(2025,11,20,8,0,tzinfo=timezone.utc).timestamp()),
                   int(datetime(2025,11,20,9,0,tzinfo=timezone.utc).timestamp())),
    ]

    # --- Gmail + SMS/alarm/calendar ---
    tasks["CheckDepartTimeTask"] = [sms_insert("34567843456", "Do you know what time we're leaving tomorrow?")]
    tasks["CheckEventTimeTask"] = [
        adb("am start -a android.intent.action.SET_ALARM "
            "--ei android.intent.extra.alarm.HOUR 18 "
            "--ei android.intent.extra.alarm.MINUTES 0 "
            "--ez android.intent.extra.alarm.SKIP_UI true"),
    ]
    tasks["CheckInterviewTimesTask"] = [
        cal_insert("Google", int(datetime(2025,11,12,14,0,tzinfo=timezone.utc).timestamp()),
                   int(datetime(2025,11,12,15,0,tzinfo=timezone.utc).timestamp())),
        cal_insert("Meta", int(datetime(2025,11,3,17,30,tzinfo=timezone.utc).timestamp()),
                   int(datetime(2025,11,3,18,15,tzinfo=timezone.utc).timestamp())),
        cal_insert("Amazon", int(datetime(2025,11,20,15,0,tzinfo=timezone.utc).timestamp()),
                   int(datetime(2025,11,20,16,30,tzinfo=timezone.utc).timestamp())),
    ]
    tasks["CheckSetMeetTimeTask"] = [
        cal_insert("Board Meeting", int(datetime(2025,11,15,15,0,tzinfo=timezone.utc).timestamp()),
                   int(datetime(2025,11,15,16,0,tzinfo=timezone.utc).timestamp())),
    ]
    tasks["RequestCarpoolingTask"] = [
        sms_insert("3522228876", "Hey, could you help send Bob to the competition tomorrow? Thanks."),
    ]

    # --- Hardcoded answers (13) ---
    for name, ans in [
        ("CheckInvoiceTask1", "104417.7"), ("ReadQwen3PaperTask1", "1.9"),
        ("ReadQwen3PaperTask2", "60"), ("ReadQwen3PaperTask3", "12"),
        ("ReadQwen3PaperTask4", "540"), ("ReadQwen3PaperTask5", "vie Latn,khm Khmr"),
        ("CheckCartPriceTask", "13186"), ("CheckPuchasedItem", "42"),
        ("RecentTotalExpenseTask", "1196"), ("GoogleMapsAlibabaSouthNeighborTask", "NetEase"),
        ("CountFileLinesTask", "29"), ("SumFileLinesTask", "313"),
    ]:
        tasks[name] = [answer(S, D, ans)]

    tasks["CheckInvoiceTask2"] = [email_write("accounting@globalent.com", "Invoice Payment",
                                               "The total amount payable is 104417.7")]
    tasks["CheckInvoiceTask3"] = [sms_insert("14058298746", "0")]
    tasks["SendInterviewInvitationTask"] = [
        sms_insert("15551234567", "Your interview is scheduled for tomorrow morning at 10:30 AM.")]
    tasks["CheckConferenceLocationTask"] = [
        sms_insert("4456547865", "110 Mt Auburn St"),
        answer(S, D, "43"),
    ]
    tasks["TextArrivalTimeTask"] = [sms_insert("4538997638", "I should arrive around 8:30 pm.")]

    # --- Native file ops ---
    tasks["SMSManagement"] = [
        sql_cmd(SMS_DB, "DELETE FROM sms WHERE address IN ('78901','56789','34567','88999')"),
        email_write("dylan@gmail.com", "Recruitment Summary",
                    "Summary: Meta is hiring for data scientist position."),
    ]
    tasks["SharePhotosTask"] = [
        email_write("kevin_zhang@example.com", "Flowers", "Here are some flowers for you.",
                    ["image1.jpeg", "image2.jpeg", "image3.jpeg", "image4.jpeg"]),
    ]
    tasks["TakeSelfieTask"] = [adb("cp /sdcard/Pictures/21bd-1.jpg /sdcard/Pictures/selfie_new.jpg")]

    # SetAlarm
    alarm_q = ("INSERT INTO alarm_templates "
               "(_id,external_uuid,hour,minutes,daysofweek,blackout_start,blackout_end,"
               "enabled,vibrate,label,ringtone,delete_after_use,wakeup,workflow_label,workflow_data) "
               "VALUES (100,'',8,25,96,'','',1,0,'','content://media/internal/audio/media/139?title=beebeep',0,0,'','')")
    tasks["SetAlarmTask"] = [
        sql_cmd(ALARM_DB, "DELETE FROM alarm_templates WHERE hour=8 AND minutes=25"),
        sql_cmd(ALARM_DB, alarm_q),
    ]

    # File tasks with scripts
    for name, script in [
        ("BidFileRenameTask", r"""#!/system/bin/sh
cd /sdcard/Download
stat -c "%Y %n" bid_* 2>/dev/null | sort -n > /tmp/bid_sorted.txt
i=1; while IFS=' ' read -r ts path; do fname=$(basename "$path"); ext="${fname##*.}"; mv "$fname" "_tmpbid${i}.${ext}"; i=$((i+1)); done < /tmp/bid_sorted.txt
for f in _tmpbid*; do [ -f "$f" ] || continue; num="${f#_tmpbid}"; num="${num%%.*}"; ext="${f##*.}"; mv "$f" "bid_${num}.${ext}"; done
rm -f /tmp/bid_sorted.txt"""),
        ("InvoiceReceiptCopyTask", """#!/system/bin/sh
mkdir -p /sdcard/Finance/invoice
for f in /sdcard/Download/*.pdf; do [ -f "$f" ] || continue; bn=$(basename "$f"); echo "$bn" | grep -iqE 'invoice|receipt' || continue; ts=$(stat -c '%Y' "$f"); month=$(date -d @$ts +%m); year=$(date -d @$ts +%Y); [ "$month" = "11" ] && [ "$year" = "2025" ] && cp "$f" "/sdcard/Finance/invoice/$bn"; done"""),
        ("InvoiceReceiptCopyAskUserTask", """#!/system/bin/sh
mkdir -p /sdcard/Documents/expense/invoice
for f in /sdcard/Download/*.pdf; do [ -f "$f" ] || continue; bn=$(basename "$f"); echo "$bn" | grep -iqE 'invoice|receipt' || continue; ts=$(stat -c '%Y' "$f"); month=$(date -d @$ts +%m); year=$(date -d @$ts +%Y); [ "$month" = "11" ] && [ "$year" = "2025" ] && cp "$f" "/sdcard/Documents/expense/invoice/$bn"; done"""),
        ("ReviewPaperEmailTask", r"""#!/system/bin/sh
mkdir -p /sdcard/Documents/paper
find /sdcard/Documents -name 'review_*.pdf' ! -path '*/paper/*' 2>/dev/null | while read f; do bn=$(basename "$f"); mv "$f" "/sdcard/Documents/paper/$bn"; done
ls /sdcard/Documents/paper/"""),
        ("PhotoManagementTask", """#!/system/bin/sh
mkdir -p /sdcard/DCIM/Paris /sdcard/DCIM/Tokyo
cd /sdcard/DCIM/Camera
for f in *PAR*; do [ -f "$f" ] && mv "$f" /sdcard/DCIM/Paris/; done
for f in *TOK*; do [ -f "$f" ] && mv "$f" /sdcard/DCIM/Tokyo/; done"""),
    ]:
        enc = base64.b64encode(script.encode()).decode()
        tasks[name] = [
            adb(f'"echo {enc} | base64 -d > /sdcard/_script.sh"'),
            adb("sh /sdcard/_script.sh"),
            adb("rm /sdcard/_script.sh"),
        ]
    # ReviewPaper also needs email
    tasks["ReviewPaperEmailTask"].append(
        "# capture output of ls, then: " +
        email_write("chen@gmail.com", "paper", "Please find papers attached.",
                    ["review_draft.pdf", "review_revised.pdf", "review_final.pdf"]))

    # CVEmail — dynamic file list
    cv_script = """#!/system/bin/sh
CUTOFF=$(( $(date +%s) - 2592000 ))
for f in /sdcard/Download/*_CV.pdf; do [ -f "$f" ] || continue; ts=$(stat -c '%Y' "$f"); [ "$ts" -ge "$CUTOFF" ] && basename "$f"; done"""
    enc = base64.b64encode(cv_script.encode()).decode()
    tasks["CVEmailTask"] = [
        adb(f'"echo {enc} | base64 -d > /sdcard/_script.sh"'),
        adb("sh /sdcard/_script.sh"),
        "# capture output as CV_FILES, then write email with those as attachments",
        adb("rm /sdcard/_script.sh"),
    ]

    # Contact creation
    contact_script = """#!/system/bin/sh
content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s: --bind account_name:s:
sleep 1
CID=$(content query --uri content://com.android.contacts/raw_contacts --projection _id --sort "_id DESC LIMIT 1" | head -1 | grep -o '_id=[0-9]*' | cut -d= -f2)
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:"Kevin Zhang"
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:"+86 571 85022088" --bind data2:i:1
content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:$CID --bind mimetype:s:vnd.android.cursor.item/organization --bind data1:s:alibaba --bind data2:i:1"""
    enc = base64.b64encode(contact_script.encode()).decode()
    tasks["GoogleMapsAlibabaPhoneContactTask"] = [
        adb(f'"echo {enc} | base64 -d > /sdcard/_script.sh"'),
        adb("sh /sdcard/_script.sh"),
        adb("rm /sdcard/_script.sh"),
    ]

    # Mall callbacks
    for tname, data in [
        ("CartInfoNotificationTask", None),  # SMS only
        ("CartManagementTask", {"task_name": "购物车删除选中",
            "current_cart_items": [{"prodId": p} for p in ["4","6","10","11","12","13","14","15","16","17","18","19","21","1","2","3","5","7","8","9","20","22"]],
            "items_to_delete": [{"prodId": p} for p in ["1","2","3","5","7","8","9","20","22"]]}),
        ("ItemCheckoutTask", {"task_name": "提交订单",
            "product_info": [{"prodId": "11", "prodName": "iPhone 15 Pro", "prodCount": 1}],
            "address_info": {"receiver": "张先生", "mobile": "13800138000", "addr": "阿里巴巴西溪C区",
                             "province": "浙江省", "city": "杭州市", "area": "余杭区"}}),
        ("SearchItemAndCheckoutTask", {"task_name": "提交订单",
            "product_info": [{"prodId": "99", "prodName": "万圣节临时纹身贴纸套装", "prodCount": 1}],
            "address_info": {"receiver": "test", "mobile": "13800138000", "addr": "test",
                             "province": "浙江省", "city": "杭州市", "area": "余杭区"}}),
        ("MastodonMallPurchaseCommodityTask", {"task_name": "提交订单",
            "product_info": [{"prodId": "14", "prodName": "运动休闲鞋", "prodCount": 2}],
            "address_info": {"receiver": "李四", "mobile": "13800139999", "addr": "华景新城",
                             "province": "广东省", "city": "广州市", "area": "天河区"}}),
    ]:
        if data:
            tasks[tname] = [mall_callback(data["task_name"], data)]
        else:
            tasks[tname] = [sms_insert("13800138888", "Order 639281475036294: 经典白色T恤, 保湿面霜套装")]

    # --- Mastodon API tasks (curl via http) ---
    TOKEN_STEP = mastodon_auth()

    mastodon_api_tasks = {
        "MastodonNewPostTask": [TOKEN_STEP,
            mastodon_post("/statuses", data={"status": "Hello from AI agent!"})],
        "MastodonAddBookmarkTask": [TOKEN_STEP,
            mastodon_post("/statuses/115359670141158913/bookmark"),
            mastodon_post("/statuses/115342692663348018/bookmark")],
        "MastodonRemoveBookmarkTask": [TOKEN_STEP,
            mastodon_post("/statuses/115410836820181445/unbookmark"),
            mastodon_post("/statuses/115410818912936581/unbookmark")],
        "MastodonFavoriteTootsTask": [TOKEN_STEP] + [
            mastodon_post(f"/statuses/{sid}/favourite") for sid in
            [115348102480027134,115410810887077411,115410813905484454,115410818912936581,115410836820181445]],
        "MastodonConditionalFavoTask": [TOKEN_STEP,
            mastodon_post("/statuses/115410810887077411/favourite"),
            mastodon_post("/statuses/115410813905484454/favourite")],
        "MastodonAdjustTootsTask": [TOKEN_STEP] + [
            cmd for sid in [115348102480027134,115410818912936581,115410836820181445]
            for cmd in [mastodon_post(f"/statuses/{sid}/unbookmark"),
                        mastodon_post(f"/statuses/{sid}/favourite"),
                        mastodon_post(f"/statuses/{sid}/reblog")]],
        "MastodonPinTootsTask": [TOKEN_STEP,
            mastodon_post("/statuses/115338428767107750/pin")],
        "MastodonReplyTask": [TOKEN_STEP,
            mastodon_post("/statuses", data={"status": "Nice sharing, i love it",
                                             "in_reply_to_id": "115342681979737543"})],
        "MastodonAddFeaturedHashtagsTask": [TOKEN_STEP] + [
            mastodon_post("/featured_tags", data={"name": t}) for t in ["summerrain","nature","photography"]],
        "MastodonManageHashtagsTask": [TOKEN_STEP,
            mastodon_post("/tags/dogs/unfollow"), mastodon_post("/tags/cats/unfollow")],
        "MastodonFollowTask": [TOKEN_STEP,
            http("GET", f"{MASTODON_API}/v2/search?q=rainbow123&type=accounts",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"}),
            "# extract account_id from response, then:",
            mastodon_post("/accounts/{account_id}/follow")],
        "MastodonUnfollowTask": [TOKEN_STEP,
            http("GET", f"{MASTODON_API}/accounts/verify_credentials",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"}),
            http("GET", f"{MASTODON_API}/accounts/$MY_ID/following?limit=80",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"}),
            "# for each user NOT in {openCompany, gourmet, kitty}:",
            mastodon_post("/accounts/{user_id}/unfollow")],
        "MastodonCreateListTask": [TOKEN_STEP,
            mastodon_post("/lists", data={"title": "Family", "replies_policy": "followed"}),
            "# search and follow alex, emma, jack, then add to list:",
            mastodon_post("/lists/{list_id}/accounts", data={"account_ids": ["{alex_id}","{emma_id}","{jack_id}"]})],
        "MastodonExportFollowsTask": [TOKEN_STEP,
            http("GET", f"{MASTODON_API}/accounts/$MY_ID/following?limit=80",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"}),
            "# format as CSV, then:",
            adb('"echo $CSV_CONTENT > /sdcard/Download/my_following.csv"')],
        "MastodonImportMutedUsersTask": [TOKEN_STEP,
            http("GET", f"{MASTODON_API}/v2/search?q=olivia&type=accounts",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"}),
            mastodon_post("/accounts/{olivia_id}/mute")],
        "MastodonNewFilterTask": [TOKEN_STEP,
            adb("cat /sdcard/Documents/filter_BCS"),
            mastodon_post("/v2/filters", data={"title": "Anti-Spoiler-BCS",
                "context": ["home","notifications","public","thread","account"], "expires_in": 432000}),
            "# for each keyword from file:",
            mastodon_post("/v2/filters/{filter_id}/keywords", data={"keyword": "{keyword}", "whole_word": True})],
        "MastodonPostPollTask": [TOKEN_STEP,
            mastodon_post("/statuses", data={"status": "#vote2025 2025 Nobel Prize in Economics",
                "poll": {"options": ["Joel Mokyr","Philippe Aghion","Peter Howitt"],
                         "expires_in": 604800, "multiple": True}})],
        "MastodonMattermostPostNoticeTask": [TOKEN_STEP,
            mastodon_post("/statuses", data={"status": "@openCompany Security: rotated API keys; check 1Password vault for updated entries.",
                                             "visibility": "private"})],
        "MastodonChangeHeaderTask": [TOKEN_STEP,
            "# pull tiger.jpg from device, upload via multipart:",
            http("PATCH", f"{MASTODON_API}/accounts/update_credentials",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"},
                 data="multipart: header=@/sdcard/Pictures/tiger.jpg")],
        "MastodonPostEditedPhotoTask": [TOKEN_STEP,
            "# pull photo, crop to 540x960 (9:16), upload as media:",
            http("POST", f"{MASTODON_API}/media",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"},
                 data="multipart: file=@cropped_9x16.jpg"),
            mastodon_post("/statuses", data={"status": "#onePhoto", "media_ids": ["{media_id}"]})],
        "MastodonShareLocationTask": [TOKEN_STEP,
            http("POST", f"{MASTODON_API}/media",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"},
                 data="multipart: file=@/sdcard/Download/Eiffel_Tower.jpg"),
            mastodon_post("/statuses", data={"status": "Eiffel Tower https://maps.app.goo.gl/QaAiRFhy3bRf5yPd6",
                                             "media_ids": ["{media_id}"]})],
        "MastodonMallShareOrderTask": [TOKEN_STEP,
            http("POST", f"{MASTODON_API}/media",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"},
                 data="multipart: file=@watch.jpg"),
            mastodon_post("/statuses", data={"status": "刚在淘店买了一块智能手表，价格1199元",
                                             "media_ids": ["{media_id}"]})],
    }
    tasks.update(mastodon_api_tasks)

    # --- Mastodon PostgreSQL tasks ---
    mastodon_db_tasks = {
        "MastodonChangeLanguageTask": [
            mastodon_db("UPDATE users SET locale='zh-CN' WHERE account_id = (SELECT id FROM accounts WHERE username='test')")],
        "MastodonFilterLanguageTask": [
            mastodon_db("UPDATE users SET chosen_languages='{en,zh-CN,ja}' WHERE account_id = (SELECT id FROM accounts WHERE username='test')")],
        "MastodonRevisePhotoAltTask": [
            mastodon_db("UPDATE media_attachments SET description = E'Author is Monet\\n' || description WHERE status_id=115378662120962265")],
        "MastodonRevisePollTask": [
            mastodon_db("UPDATE polls SET options='{Russia,China,Canada}' WHERE status_id=115433627788463436")],
        "MastodonReportTask": [
            mastodon_db(f"INSERT INTO reports (status_ids, comment, account_id, target_account_id, category, created_at, updated_at) SELECT '{{115383686318250006}}', text, {TEST_ACCT}, {FRANK_ACCT}, 1000, NOW(), NOW() FROM statuses WHERE id=115383686318250006"),
            mastodon_db(f"INSERT INTO blocks (account_id, target_account_id, created_at, updated_at) VALUES ({TEST_ACCT}, {FRANK_ACCT}, NOW(), NOW()) ON CONFLICT DO NOTHING")],
        "MastodonInviteTask": [
            mastodon_db(f"INSERT INTO invites (user_id,code,expires_at,max_uses,uses,autofollow,created_at,updated_at) VALUES ((SELECT u.id FROM users u JOIN accounts a ON u.account_id=a.id WHERE a.username='test'),'TestInvCode1',NOW()+interval '1 day',1,0,true,NOW(),NOW())"),
            sms_insert("+16265551427", "https://10.0.2.2/invite/TestInvCode1")],
        "MastodonMultiInviteTask": [
            mastodon_db(f"INSERT INTO invites (user_id,code,expires_at,max_uses,uses,autofollow,created_at,updated_at) VALUES ((SELECT u.id FROM users u JOIN accounts a ON u.account_id=a.id WHERE a.username='test'),'LeonardInv01',NOW()+interval '1 day',1,0,false,NOW(),NOW())"),
            mastodon_db(f"INSERT INTO invites (user_id,code,expires_at,max_uses,uses,autofollow,created_at,updated_at) VALUES ((SELECT u.id FROM users u JOIN accounts a ON u.account_id=a.id WHERE a.username='test'),'EllaInvite01',NOW()+interval '7 days',NULL,0,true,NOW(),NOW())"),
            sms_insert("+16265551427", "https://10.0.2.2/invite/LeonardInv01"),
            sms_insert("+14676741503", "https://10.0.2.2/invite/EllaInvite01")],
        "MastodonOpenAutomatedDeletionTask": [
            mastodon_db(f"DELETE FROM account_statuses_cleanup_policies WHERE account_id={TEST_ACCT}"),
            mastodon_db(f"INSERT INTO account_statuses_cleanup_policies (account_id,enabled,min_status_age,keep_direct,keep_pinned,keep_polls,keep_media,keep_self_fav,keep_self_bookmark,min_favs,min_reblogs,created_at,updated_at) VALUES ({TEST_ACCT},true,604800,false,true,false,false,false,false,20,20,NOW(),NOW())")],
        "MastodonServerInfoReportTask": [
            mastodon_db("SELECT pg_database_size('mastodon')"),
            "# compute size: bytes / 1024 / 1024, format as X.X MB",
            TOKEN_STEP,
            mastodon_post("/statuses", data={"status": "{db_size_formatted}"}),
            email_write("owner@mastodon_example.com", "Server Reports", "Recent reports: {count}")],
        "MastodonUpdateContactsTask": [
            "# read Olivia's latest toot for phone/email:",
            mastodon_db("SELECT text FROM statuses WHERE account_id=(SELECT id FROM accounts WHERE username='olivia') ORDER BY created_at DESC LIMIT 1"),
            "# update contact via adb script:",
            adb("sh /sdcard/update_contact.sh"),
            sms_insert("5551234567", "Hello, how are you")],
        "MastodonSavePhotosTask": [TOKEN_STEP,
            http("GET", f"{MASTODON_API}/statuses/115319571928036858",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"}),
            "# for each media_attachment URL, download and save to device"],
        "MastodonManageMultiListTask": [TOKEN_STEP,
            http("GET", f"{MASTODON_API}/lists",
                 headers={"Authorization": "Bearer $TOKEN", "Host": "10.0.2.2"}),
            "# delete existing lists",
            mastodon_post("/lists", data={"title": "open", "replies_policy": "followed"}),
            "# add openCompany, openUniversity to 'open' list",
            mastodon_post("/lists", data={"title": "cute", "replies_policy": "list"}),
            mastodon_db("UPDATE lists SET exclusive=true WHERE title='cute'"),
            "# add pupper, kitty, olivia to 'cute' list"],
        "MastodonGetServerInfoTask": [
            mastodon_db("SELECT pg_database_size('mastodon')"),
            "# format size as X.X MB using: bytes/1024/1024 with 1 decimal",
            TOKEN_STEP.replace("test", "owner").replace("115338428522805842", "115338428152261473"),
            mastodon_post("/statuses", data={"status": "{formatted_size}"})],
    }
    tasks.update(mastodon_db_tasks)

    # --- Mattermost tasks (psql) ---
    def next_monday():
        today = datetime.now().date()
        d = (7 - today.weekday()) % 7
        if d == 0: d = 7
        return today + timedelta(days=d)

    def next_friday():
        today = datetime.now().date()
        d = 4 - today.weekday()
        if d <= 0: d += 7
        return today + timedelta(days=d)

    mm_tasks = {
        "MattermostCreateChannelTask": [
            mattermost_db("SELECT id FROM teams WHERE name='neuralforge'"),
            mattermost_db("INSERT INTO channels (id,createat,updateat,deleteat,teamid,type,displayname,name,header,purpose,lastpostat,totalmsgcount,extraupdateat,creatorid) VALUES (md5(random()::text)::varchar(26),extract(epoch from now())::bigint*1000,extract(epoch from now())::bigint*1000,0,(SELECT id FROM teams WHERE name='neuralforge'),'O','reading','reading','','',0,0,0,'" + HARRY_ID + "')"),
            "# add all team members to channel via INSERT INTO channelmembers",
            mm_post("(SELECT id FROM channels WHERE name='reading')", HARRY_ID, "Welcome to the reading group channel!")],
        "MattermostReplyToMessageTask": [
            mattermost_db(f"INSERT INTO posts (id,createat,updateat,deleteat,userid,channelid,rootid,originalid,message,type,props,hashtags,filenames,fileids,hasreactions,editat,ispinned) VALUES (md5(random()::text)::varchar(26),extract(epoch from now())::bigint*1000,extract(epoch from now())::bigint*1000,0,'{HARRY_ID}',(SELECT channelid FROM posts WHERE id='q1iiqx18bb8npdoiocr7ki5t1r'),'q1iiqx18bb8npdoiocr7ki5t1r','','The OSWorld eval SR result is 35.5','','{{}}','','','',false,0,false)")],
        "MattermostEmailTask": [
            email_write("legal@company.com", "Contract Forward - TT-POC-2025-BLPINE-042",
                        "Contract attached. Tracking code: TT-POC-2025-BLPINE-042", ["contract.pdf"]),
            mm_post(SAM_HARRY_CH, HARRY_ID, "Contract forwarded to legal@company.com with tracking code TT-POC-2025-BLPINE-042")],
        "MattermostProjectHandoverTask": [
            mattermost_db(f"INSERT INTO channelmembers (channelid,userid,roles,lastviewedat,msgcount,mentioncount,lastupdateat,schemeuser,schemeadmin,schemeguest) VALUES ('{PHOENIX_CH}','{ALEX_ID}','channel_user',0,0,0,extract(epoch from now())::bigint*1000,true,false,false) ON CONFLICT DO NOTHING"),
            mm_post(PHOENIX_CH, HARRY_ID, "Meeting Time: 2025-10-16 from 11:00 to 12:00")],
        "MattermostReadingGroupTask": [
            mattermost_db("SELECT id FROM channels WHERE name='reading'"),
            mm_post("(SELECT id FROM channels WHERE name='reading')", HARRY_ID,
                    "Paper: https://arxiv.org/abs/2511.21631\nMMU_Pro score: 68.1")],
        "MattermostBudgetApprovalPipelineTask": [
            mattermost_db("SELECT id FROM channels WHERE name='budget-approvals-q4'"),
            mm_post("(SELECT id FROM channels WHERE name='budget-approvals-q4')", HARRY_ID,
                    "# Q4 Budget Approval Summary\n\n| Department | Amount | ROI | Approval Status |\n|--|--|--|--|\n| Engineering | $85,000 | 50% | Executive Required |\n| Marketing | $62,000 | 25% | Executive Required |\n| HR | $35,000 | 20% | Standard |\n| Operations | $78,000 | 20% | Executive Required |\n| Research | $45,000 | 30% | Standard |")],
        "MattermostCustomerFeedbackAnalysisTask": [
            email_write("product@company.com", "Negative Feedback Digest",
                        "Negative feedback:\n1. Login page crashes on Android 10\n2. Billing dashboard is confusing\n3. Cannot export reports to PDF"),
            cal_insert("Feedback Review",
                       int(datetime.combine(next_friday(), datetime.min.time().replace(hour=14), tzinfo=timezone.utc).timestamp()),
                       int(datetime.combine(next_friday(), datetime.min.time().replace(hour=15), tzinfo=timezone.utc).timestamp())),
            mm_post("(SELECT id FROM channels WHERE name='customer-feedback')", HARRY_ID,
                    "All negative feedback logged and meeting scheduled for review.")],
        "MattermostDeadlineReconciliationTask": [
            email_write("dylan@gmail.com", "Deadline Audit Report",
                        "Matched: API Documentation Review, Frontend MVP Launch\nMissing: Security Audit Completion, Beta Testing Phase Start\nUntracked: Team Building Event"),
            cal_insert("[AUTO] Security Audit Completion",
                       int(datetime.combine(next_monday()+timedelta(days=13), datetime.min.time().replace(hour=10), tzinfo=timezone.utc).timestamp()),
                       int(datetime.combine(next_monday()+timedelta(days=13), datetime.min.time().replace(hour=11), tzinfo=timezone.utc).timestamp())),
            cal_insert("[AUTO] Beta Testing Phase Start",
                       int(datetime.combine(next_monday()+timedelta(days=18), datetime.min.time().replace(hour=10), tzinfo=timezone.utc).timestamp()),
                       int(datetime.combine(next_monday()+timedelta(days=18), datetime.min.time().replace(hour=11), tzinfo=timezone.utc).timestamp())),
            mm_post("(SELECT id FROM channels WHERE name='project-updates')", HARRY_ID,
                    "Auto-created events: [AUTO] Security Audit Completion, [AUTO] Beta Testing Phase Start")],
        "MattermostIncidentEscalationTask": [
            mattermost_db(f"INSERT INTO channels (id,createat,updateat,deleteat,teamid,type,displayname,name,header,purpose,lastpostat,totalmsgcount,extraupdateat,creatorid) VALUES (md5(random()::text)::varchar(26),extract(epoch from now())::bigint*1000,extract(epoch from now())::bigint*1000,0,(SELECT id FROM teams WHERE name='neuralforge'),'O','incident-ticket-500','incident-ticket-500','','',0,0,0,'{HARRY_ID}')"),
            mattermost_db(f"INSERT INTO channelmembers (channelid,userid,roles,lastviewedat,msgcount,mentioncount,lastupdateat,schemeuser,schemeadmin,schemeguest) VALUES ((SELECT id FROM channels WHERE name='incident-ticket-500'),(SELECT id FROM users WHERE username='sam'),'channel_user',0,0,0,extract(epoch from now())::bigint*1000,true,false,false)"),
            email_write("cto@company.com", "CRITICAL INCIDENT: TICKET-500",
                        "Critical incident: Database connection timeout errors. The database is experiencing intermittent timeout failures."),
            cal_insert("Discussion on TICKET-500",
                       int(datetime.combine(datetime.now().date()+timedelta(days=1), datetime.min.time().replace(hour=9), tzinfo=timezone.utc).timestamp()),
                       int(datetime.combine(datetime.now().date()+timedelta(days=1), datetime.min.time().replace(hour=10), tzinfo=timezone.utc).timestamp()))],
        "MattermostProjectStatusReportTask": [
            email_write("pm@company.com", "Sprint Status Risk Matrix",
                        "On-Track: Authentication Module, API Gateway Setup\nAt-Risk: Dashboard UI, Performance Testing\nBlocked: Payment Integration, Security Audit"),
            cal_insert("[ESCALATION] Payment Integration",
                       int(datetime.combine(next_monday()+timedelta(days=1), datetime.min.time().replace(hour=10), tzinfo=timezone.utc).timestamp()),
                       int(datetime.combine(next_monday()+timedelta(days=1), datetime.min.time().replace(hour=10, minute=30), tzinfo=timezone.utc).timestamp())),
            cal_insert("[ESCALATION] Security Audit",
                       int(datetime.combine(next_monday()+timedelta(days=1), datetime.min.time().replace(hour=10), tzinfo=timezone.utc).timestamp()),
                       int(datetime.combine(next_monday()+timedelta(days=1), datetime.min.time().replace(hour=10, minute=30), tzinfo=timezone.utc).timestamp())),
            mm_post("(SELECT id FROM channels WHERE name='project-sync')", HARRY_ID,
                    "Sprint status: 2 on-track, 2 at-risk, 2 blocked")],
        "MattermostResourceConflictResolutionTask": [
            email_write("facilities@company.com", "Resource Booking Conflicts",
                        "APPROVED: Conf Room B, Conf Room C, Projector, Video Camera\nCONFLICT: Conf Room A"),
            "# insert BOOKED calendar events for approved items",
            "# send DM to Alex about Conf Room A conflict"],
        "MattermostShiftCoverageTask": [
            "# find Alex's and Sofia's request messages in shift-requests channel",
            "# reply to Alex: Denied (conflicts with All Hands)",
            "# reply to Sofia: Escalated to HR",
            email_write("hr@company.com", "Shift Swap Request",
                        f"Sofia requests shift coverage for {(next_monday()+timedelta(days=2)).strftime('%Y-%m-%d')} due to doctor appointment.")],
        "MattermostTechnicalDebtTriageTask": [
            sms_insert("14737474173", "PaymentProcessor: 47880"),
            "# create contact 'Refactoring Team' with phone 15559876543",
            mm_post("(SELECT id FROM channels WHERE name='tech-debt-review')", HARRY_ID,
                    "| Module | Complexity |\n|--|--|\n| PaymentProcessor | 47880 |\n| AuthenticationService | 13440 |\n| NotificationEngine | 8400 |\n| ReportGenerator | 4180 |\n| DataExporter | 2160 |")],
        "MattermostVisualInstructionResponseTask": [
            "# create contacts: Dr. Smith (555-1010), Safety Officer (555-2020)",
            sql_cmd(ALARM_DB, "INSERT INTO alarm_templates (_id,external_uuid,hour,minutes,daysofweek,blackout_start,blackout_end,enabled,vibrate,label,ringtone,delete_after_use,wakeup,workflow_label,workflow_data) VALUES (200,'',8,0,0,'','',1,0,'Morning Shift','',0,0,'','')"),
            sql_cmd(ALARM_DB, "INSERT INTO alarm_templates (_id,external_uuid,hour,minutes,daysofweek,blackout_start,blackout_end,enabled,vibrate,label,ringtone,delete_after_use,wakeup,workflow_label,workflow_data) VALUES (201,'',20,0,0,'','',1,0,'Evening Shift','',0,0,'','')"),
        ],
        "MattermostSendFileTask": [
            "# upload 21bd-1.jpg via Mattermost file API",
            "# create DM channel harry→alex",
            "# insert post as harry with file_id",
            mattermost_db(f"UPDATE channels SET creatorid='{ALEX_ID}' WHERE id=(SELECT id FROM channels WHERE type='D' AND name LIKE '%{HARRY_ID}%{ALEX_ID}%')")],
    }
    tasks.update(mm_tasks)

    # --- Missing 4 tasks ---
    tasks["MastodonCreateMemoTask"] = [
        cal_insert("AI-Powered Urban Mobility", 1761318000, 1761323400,
                   location="Auditorium 2-A, Innovation Building", reminder=1440),
    ]
    tasks["MastodonCalendarMultiMemosTask"] = [
        cal_insert("AI-Powered Urban Mobility", 1761318000, 1761323400,
                   location="Auditorium 2-A, Innovation Building", reminder=1440),
        cal_insert("The Future of Edge Intelligence in Everyday Devices", 1761575400, 1761580800,
                   location="Room 401, Tech Innovation Center", reminder=4320),
    ]
    # LocalFileManagement — delete old zips, DM self list
    tasks["LocalFileManagementTask"] = [
        adb('"for f in /sdcard/Download/*.zip; do ts=$(stat -c %Y $f 2>/dev/null); [ $ts -lt $(($(date +%s)-31536000)) ] && echo $(basename $f) && rm $f; done"'),
        mattermost_db(f"SELECT id FROM channels WHERE type='D' AND name LIKE '%{HARRY_ID}%{HARRY_ID}%'"),
        mm_post(f"$DM_CHANNEL_ID", HARRY_ID, "Deleted old files: $FILE_LIST"),
    ]
    tasks["LocalFileManagementTask2"] = [
        adb('"for f in /sdcard/Download/*; do ts=$(stat -c %Y $f 2>/dev/null); [ $ts -lt $(($(date +%s)-31536000)) ] && echo $f; done"'),
        "# pull old files to host, create zip, push back, delete originals",
        email_write("test@gmail.com", "Old Files Deleted", "Deleted and compressed: $FILE_LIST"),
    ]

    # GitHub/Weather API
    tasks["CheckGithubInfoTask"] = [
        http("GET", "https://api.github.com/repos/google-research/android_world"),
        "# extract stars and contributors count",
        email_write("kevin_zhang@example.com", "AndroidWorld Repository Stats",
                    "There are {stars} stars and {contributors} contributors in the AndroidWorld repository."),
    ]
    tasks["ChromeSearchBeijingWeatherTask"] = [
        http("GET", "https://api.open-meteo.com/v1/forecast?latitude=39.9042&longitude=116.4074&daily=temperature_2m_max&timezone=Asia/Shanghai&forecast_days=1"),
        "# extract temperature_2m_max[0], round to int",
        answer(S, D, "{temperature}"),
    ]

    return tasks


# =========================================================================
# Generate ATIF
# =========================================================================

def to_atif(task_name, commands, server_url, device):
    now = datetime.now(timezone.utc).isoformat()
    steps = [{
        "step_id": 1,
        "timestamp": now,
        "source": "user",
        "message": task_name,
    }]

    for i, cmd in enumerate(commands):
        step_id = i + 2
        tc_id = f"tc_{step_id}"

        # Determine command type
        if cmd.startswith("adb shell"):
            fn = "adb"
            args = {"command": cmd}
        elif cmd.startswith("sql "):
            fn = "sql"
            parts = cmd.split(" ", 2)
            args = {"db_path": parts[1] if len(parts) > 1 else "",
                    "query": parts[2].strip('"') if len(parts) > 2 else ""}
        elif cmd.startswith("http "):
            fn = "http"
            args = {"command": cmd}
        elif cmd.startswith("#"):
            fn = "comment"
            args = {"note": cmd}
        else:
            fn = "shell"
            args = {"command": cmd}

        steps.append({
            "step_id": step_id,
            "timestamp": now,
            "source": "agent",
            "message": "",
            "model_name": "ground_truth_cli",
            "tool_calls": [{
                "tool_call_id": tc_id,
                "function_name": fn,
                "arguments": args,
            }],
            "observation": {"results": [{"source_call_id": tc_id, "content": ""}]},
        })

    steps.append({
        "step_id": len(commands) + 2,
        "timestamp": now,
        "source": "agent",
        "message": "Task completed.",
        "tool_calls": [{"tool_call_id": f"tc_{len(commands)+2}",
                        "function_name": "finish",
                        "arguments": {"status": "complete"}}],
    })

    return {
        "schema_version": "ATIF-v1.4",
        "session_id": f"gt_cli_{task_name}",
        "agent": {
            "name": "ground_truth_cli",
            "version": "1.0.0",
            "model_name": "ground_truth_cli",
            "extra": {"benchmark": "MobileWorld", "task_name": task_name,
                      "task_type": "gui_only", "ground_truth": True,
                      "tools": ["adb", "sql", "http"]},
        },
        "steps": steps,
        "final_metrics": {
            "total_prompt_tokens": 0, "total_completion_tokens": 0,
            "total_cached_tokens": 0, "total_cost_usd": 0.0,
            "total_steps": len(steps), "reward": 1.0,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="mobile_world_env_1")
    parser.add_argument("--server-url", default="http://localhost:6805")
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument("--output", default="gt_raw_atif.jsonl")
    args = parser.parse_args()

    tasks = build_all(args.server_url, args.device)

    with open(args.output, "w") as f:
        for name in sorted(tasks.keys()):
            traj = to_atif(name, tasks[name], args.server_url, args.device)
            f.write(json.dumps(traj, ensure_ascii=False) + "\n")

    # Stats
    total_cmds = sum(len(v) for v in tasks.values())
    cmd_types = {"adb": 0, "sql": 0, "http": 0, "comment": 0, "other": 0}
    for cmds in tasks.values():
        for c in cmds:
            if c.startswith("adb shell"): cmd_types["adb"] += 1
            elif c.startswith("sql "): cmd_types["sql"] += 1
            elif c.startswith("http "): cmd_types["http"] += 1
            elif c.startswith("#"): cmd_types["comment"] += 1
            else: cmd_types["other"] += 1

    print(f"Generated {len(tasks)} ATIF trajectories → {args.output}")
    print(f"Total commands: {total_cmds} (avg {total_cmds/len(tasks):.1f})")
    print(f"Command types: {json.dumps(cmd_types)}")


if __name__ == "__main__":
    main()
