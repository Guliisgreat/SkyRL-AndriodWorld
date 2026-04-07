#!/usr/bin/env python3
"""
Generate ATIF-v1.6 ground truth trajectories for MobileWorld.

Output: one JSON file per task in a directory, matching the Harbor viewer format.
Same structure as AndroidWorld GroundTruth_oracle_final/atif_trajectories/.

Each step uses the Bash tool with raw CLI commands:
  adb shell ...   — device control
  sql ...         — device database
  http ...        — backend services

Usage:
    python generate_gt_atif_v2.py --output-dir results/GroundTruth_mobileworld/atif_trajectories
"""

import argparse
import base64
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone


# Import the raw command builder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_gt_atif_raw import build_all


# Task goals (from MobileWorld task definitions)
TASK_GOALS = {
    "AdjustBrightnessMaximumTask": "Set the brightness to the maximum level.",
    "AdjustBrightnessMinimumTask": "Set the brightness to the minimum level.",
    "AdjustFontIconMaximumTask": "Increase the font size and icons on your phone to the maximum setting.",
    "AdjustFontIconMinimumTask": "Decrease the font size and icons on your phone to the minimum setting.",
    "OpenFlightModeTask": "Turn on device flight mode.",
    "CloseFlightModeTask": "Turn off device flight mode.",
    "ChangeWallpaperTask": "Change the wallpaper to a photo from the album that features sunflowers.",
    "CheckConferenceDurationTask": "How many days of conference meetings did I schedule in October?",
    "CheckDeduplicatedEventsTask": "How many deduplicated events are there in the calendar, from October 20 to October 26?",
    "CheckConferenceAndSendSmsTask1": "Check my calendar and send an SMS notification to Mia with the dates of my arrival and departure from Paris.",
    "CheckConferenceAndSendSmsTask2": "Check my calendar and send an SMS notification to Mia with the dates of my arrival and departure from Tokyo.",
    "ScheduleCoffeeTimeViaSmsTask": "I've received a coffee time invitation via text message; please check the calendar and reply accordingly.",
    "ScheduleLunchViaSmsTask": "I've received a lunch invitation via text message; please reply 'OK' and schedule a corresponding event on my calendar.",
    "AcceptMeetingTask": "Reply to Daniel's most recent email to tell him: 'I'll be there at 10:00 AM on Thursday.'",
    "CancelMeetingTask": "Reply to Daniel's most recent email to tell him I'll have to cancel the meeting on Thursday.",
    "CheckDepartTimeTask": "Check if I've received an email about the depart time for the CoolHacks hackathon.",
    "CheckEventTimeTask": "Check my email for the time of the Christmas party today. Set an alarm for one hour before then.",
    "CheckInterviewTimesTask": "Check my email for any job interviews I have in November. Set calendar events for each of them.",
    "CheckRegistrationTask": "Check my email for Putnam registration confirmation.",
    "CheckSetMeetTimeTask": "Check my email for the date and time of my meeting with Carl. Then, set a calendar event titled 'Board Meeting'.",
    "RequestCarpoolingTask": "Check email for math competition time tomorrow. If 12-5pm, text Daniel.",
    "SendWaiverTask": "Send the file 'waiver.jpg' as an email attachment to bob@gmail.com. Title the email 'Updated waiver'.",
    "SendInterviewEmailTask": "Find Kevin's resume and send email to Kevin about his interview schedule.",
    "SendFormsTask": "Check email for field trip forms from October 3rd onward. Download all and send to principal.",
    "DownloadSendReceiptTask": "Find receipt.jpg in email, download it, send to treasurer with total amount.",
    "SuggestPaperTask": "Reply to Tony's email asking for paper suggestions with a pdf of the ddpm paper.",
    "GraduationMassEmailTask": "Email math department graduates about graduation party and set calendar event.",
    "ThanksgivingPrepTask": "Email ingredient list for Pecan pie and set Thanksgiving shopping calendar event.",
    "CheckInvoiceTask1": "Read the invoice PDF. Recalculate total amount payable with 45-day late payment.",
    "CheckInvoiceTask2": "Read the invoice PDF. Email recalculated amount to customer.",
    "CheckInvoiceTask3": "Read the invoice PDF. SMS Mia the consulting vs development hours difference.",
    "ReadQwen3PaperTask1": "Read the Qwen3 paper. By how many points does Qwen3-32B lag behind on AIME25?",
    "ReadQwen3PaperTask2": "Read the Qwen3 paper. How many core contributors?",
    "ReadQwen3PaperTask3": "Read the Qwen3-Omni paper. How many benchmarks for Text-to-Text evaluation?",
    "ReadQwen3PaperTask4": "Read the Qwen3-Omni paper. Vision encoder size in Qwen3-Omni-30B-A3B?",
    "ReadQwen3PaperTask5": "Read the Qwen3 paper. What Austroasiatic languages in Belebele Benchmark?",
    "SendInterviewInvitationTask": "Send a text message to Kevin about his interview schedule.",
    "CheckCartPriceTask": "Find the three most expensive items in TaoDian shopping cart and calculate total.",
    "CheckPuchasedItem": "Check what shoe size my friend wears from the TaoDian order history.",
    "RecentTotalExpenseTask": "Calculate total spending on TaoDian in the past month.",
    "GoogleMapsAlibabaSouthNeighborTask": "Find which company is directly south of Alibaba Hangzhou headquarters.",
    "GoogleMapsAlibabaPhoneContactTask": "Find Alibaba HQ phone number on Maps and create a contact.",
    "TextArrivalTimeTask": "Check driving time Orlando to Miami and text Susan estimated arrival.",
    "CountFileLinesTask": "Count lines in file_1.txt inside earliest July zip in Downloads.",
    "SumFileLinesTask": "Sum line counts of all files in earliest July zip in Downloads.",
    "CheckConferenceLocationTask": "Check email for conference hotel, text address, and calculate walk time.",
    "SMSManagement": "Check unread SMS, delete spams, email recruitment summary.",
    "SharePhotosTask": "Find all flower pictures in gallery and send them via email.",
    "TakeSelfieTask": "Take a photo.",
    "SetAlarmTask": "Set a weekend alarm for 8:25 a.m. with ringtone beebeep and vibration off.",
    "BidFileRenameTask": "Rename bid_ files in Download by creation date order.",
    "InvoiceReceiptCopyTask": "Copy November invoice/receipt PDFs to Finance/invoice folder.",
    "InvoiceReceiptCopyAskUserTask": "Copy November invoice/receipt PDFs to Documents/expense/invoice folder.",
    "CVEmailTask": "Find CV files from past month and email to HR.",
    "ReviewPaperEmailTask": "Find review PDFs, move to Documents/paper, email all.",
    "PhotoManagementTask": "Classify food photos by travel destination into folders.",
    "MastodonNewPostTask": "Post a new toot with 'Hello from AI agent!'",
    "MastodonAddBookmarkTask": "Add all posts of user kitty with #cats tag to bookmarks.",
    "MastodonRemoveBookmarkTask": "Remove posts with #pets tag from bookmarks.",
    "MastodonFavoriteTootsTask": "Search for #dogs toots and favorite all of them.",
    "MastodonConditionalFavoTask": "Favorite #dogs toots not already in favorites or bookmarks.",
    "MastodonAdjustTootsTask": "Remove all bookmarks, add as favorites, and boost all.",
    "MastodonPinTootsTask": "Pin the first post published after creating the account.",
    "MastodonReplyTask": "Reply to gourmet's Moussaka post with 'Nice sharing, i love it'.",
    "MastodonAddFeaturedHashtagsTask": "Add featured hashtags: summerrain, nature, photography.",
    "MastodonManageHashtagsTask": "Unfollow animal-related hashtags.",
    "MastodonFollowTask": "Find Robert's nickname in Contacts, search on Mastodon, follow him.",
    "MastodonUnfollowTask": "Keep only the latest three followed users, unfollow all others.",
    "MastodonCreateListTask": "Create a list called 'Family' with Alex, Emma, and Jack.",
    "MastodonExportFollowsTask": "Export follows as my_following.csv.",
    "MastodonImportMutedUsersTask": "Import muted list from muted_accounts.csv.",
    "MastodonNewFilterTask": "Create filter 'Anti-Spoiler-BCS' with keywords from file.",
    "MastodonChangeLanguageTask": "Set Mastodon account language to Chinese Simplified.",
    "MastodonFilterLanguageTask": "Set filters to show posts in English, Japanese, and Chinese Simplified.",
    "MastodonRevisePhotoAltTask": "Check and update ALT text of Impression Sunrise image.",
    "MastodonRevisePollTask": "Edit poll: remove USA, change Brazil to Canada.",
    "MastodonReportTask": "Report Frank's gas leak post for spam and block Frank.",
    "MastodonInviteTask": "Generate invite link and SMS to Leonard.",
    "MastodonMultiInviteTask": "Generate two invite links with different settings, SMS both.",
    "MastodonUpdateContactsTask": "Update Olivia's contact info from her Mastodon post and send SMS.",
    "MastodonServerInfoReportTask": "Query database size and email report count.",
    "MastodonOpenAutomatedDeletionTask": "Enable auto-delete old posts with specific settings.",
    "MastodonGetServerInfoTask": "Query database size and post as owner.",
    "MastodonPostPollTask": "Create poll with Nobel Prize Economics winners.",
    "MastodonMattermostPostNoticeTask": "Sync security announcement from Mattermost to Mastodon.",
    "MastodonCreateMemoTask": "Find #openTalk lecture and create calendar event with reminder.",
    "MastodonCalendarMultiMemosTask": "Find #openTalk lectures and create calendar events.",
    "MastodonChangeHeaderTask": "Replace profile header with tiger photo.",
    "MastodonPostEditedPhotoTask": "Crop photo to 9:16 and post with #onePhoto.",
    "MastodonShareLocationTask": "Share Eiffel Tower map link and image on Mastodon.",
    "MastodonSavePhotosTask": "Save images from Alice's October 5 post to phone.",
    "MastodonManageMultiListTask": "Delete old lists, create 'open' and 'cute' lists with members.",
    "MastodonMallPurchaseCommodityTask": "Buy 2 pairs of shoes shared on Mastodon via TaoDian.",
    "MastodonMallShareOrderTask": "Share TaoDian watch order on Mastodon with image.",
    "CartInfoNotificationTask": "Find items awaiting shipment and SMS reminder.",
    "CartManagementTask": "Delete all short-sleeve T-shirts from shopping cart.",
    "ItemCheckoutTask": "Checkout iPhone 15 Pro with specific delivery address.",
    "SearchItemAndCheckoutTask": "Search and order temporary tattoos for Halloween.",
    "MattermostCreateChannelTask": "Create 'reading' channel, add everyone, send welcome.",
    "MattermostReplyToMessageTask": "Reply to own message with OSWorld eval result.",
    "MattermostEmailTask": "Forward contract to legal with tracking code.",
    "MattermostProjectHandoverTask": "Add Alex to phoenix channel and schedule meeting.",
    "MattermostReadingGroupTask": "Post arXiv paper link and MMMU_Pro score.",
    "MattermostSendFileTask": "Send birthday message with cake image to Alex.",
    "MattermostBudgetApprovalPipelineTask": "Review budget requests, calculate ROI, post summary table.",
    "MattermostCustomerFeedbackAnalysisTask": "Identify negative feedback, email digest, schedule review.",
    "MattermostDeadlineReconciliationTask": "Cross-reference deadlines with calendar, create auto events.",
    "MattermostIncidentEscalationTask": "Create incident channel, email CTO, schedule meeting.",
    "MattermostProjectStatusReportTask": "Aggregate team statuses, email risk matrix, create escalation events.",
    "MattermostResourceConflictResolutionTask": "Check resource requests vs calendar, email results.",
    "MattermostShiftCoverageTask": "Review shift swaps, deny conflicts, escalate valid to HR.",
    "MattermostTechnicalDebtTriageTask": "Analyze complexity scores, SMS highest, post sorted table.",
    "MattermostVisualInstructionResponseTask": "Create contacts and set alarms from channel instructions.",
    "LocalFileManagementTask": "Delete old zip files and send list via Mattermost DM.",
    "LocalFileManagementTask2": "Compress old files, delete originals, email list.",
    "CheckGithubInfoTask": "Check AndroidWorld GitHub stars/contributors, email results.",
    "ChromeSearchBeijingWeatherTask": "Search Beijing highest temperature today.",
}


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Execute a CLI command. Supports: adb shell (device control), "
                           "sql (device database), http (backend services)",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"}
                },
                "required": ["command"]
            }
        }
    }
]


def generate(server_url, device, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    all_commands = build_all(server_url, device)

    task_id = 0
    for task_name in sorted(all_commands.keys()):
        commands = all_commands[task_name]
        goal = TASK_GOALS.get(task_name, task_name)
        session_id = f"mobileworld-{task_name}-{uuid.uuid4().hex[:8]}"

        steps = [
            {"step_id": 1, "source": "system", "message": "[GroundTruth CLI, MobileWorld]"},
            {"step_id": 2, "source": "user", "message": goal},
        ]

        step_id = 3
        actual_steps = 0
        for cmd in commands:
            if cmd.startswith("#"):
                # Comment — include as agent reasoning, no tool call
                steps.append({
                    "step_id": step_id,
                    "source": "agent",
                    "message": cmd.lstrip("# "),
                    "model_name": "oracle",
                })
            else:
                steps.append({
                    "step_id": step_id,
                    "source": "agent",
                    "message": "",
                    "model_name": "oracle",
                    "tool_calls": [{
                        "tool_call_id": f"call_{step_id}",
                        "function_name": "Bash",
                        "arguments": {"command": cmd},
                    }],
                    "observation": {
                        "results": [{
                            "source_call_id": f"call_{step_id}",
                            "content": "",
                        }]
                    },
                })
                actual_steps += 1
            step_id += 1

        trajectory = {
            "schema_version": "ATIF-v1.6",
            "session_id": session_id,
            "agent": {
                "name": "GroundTruth",
                "version": "1.0",
                "model_name": "oracle",
                "tool_definitions": TOOL_DEFINITIONS,
            },
            "steps": steps,
            "final_metrics": {
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_cost_usd": 0,
                "total_steps": actual_steps,
                "extra": {
                    "task_id": task_id,
                    "seed": 0,
                    "reward": 1,
                    "finished": True,
                    "elapsed_seconds": 0.0,
                    "finish_description": f"Ground truth CLI solution for {task_name}",
                    "num_turns": actual_steps,
                },
            },
            "extra": {
                "benchmark": "MobileWorld",
                "task_text": goal,
                "task_name": task_name,
            },
        }

        out_path = os.path.join(output_dir, f"task_{task_id:03d}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(trajectory, f, indent=2, ensure_ascii=False)

        task_id += 1

    print(f"Generated {task_id} task files → {output_dir}/")
    print(f"Format: ATIF-v1.6, one JSON per task, Harbor viewer compatible")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", default="http://localhost:6805")
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument("--output-dir",
                        default="../../results/GroundTruth_mobileworld_cli/atif_trajectories")
    args = parser.parse_args()
    generate(args.server_url, args.device, args.output_dir)


if __name__ == "__main__":
    main()
