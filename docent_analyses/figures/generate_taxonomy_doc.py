#!/usr/bin/env python3
"""Generate `taxonomy.md` — a 2-level failure taxonomy document.

For each paradigm (CLI / GUI):
  - Top-level (4 TB groups + Out-of-Scope)
  - TB leaf (9 TB leaves + harness)
  - Sub-leaves (Docent-discovered clusters)
      - description + transcript signature
      - est_fraction (Phase 2 LLM mass estimate)
      - actual count + share % (Phase 3 per-trajectory, where available)
      - mapping rationale (citing rubric_v2.md or tie-breaker number)
"""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WS_CLI = ROOT.parent / "2026-05-21_android-cli-failures-combined"
WS_GUI = ROOT.parent / "2026-05-22_android-gui-failures"

CLI_PROP   = WS_CLI / "discovery/cluster_proposal.json"
CLI_MAP    = WS_CLI / "consensus_mapping_v3.json"
CLI_LABELS = WS_CLI / "classification/cluster_labels_full.jsonl"
CLI_JUDGES = [
    WS_CLI / "crosswalk_judge1_v3.json",
    WS_CLI / "crosswalk_judge2_v3.json",
    WS_CLI / "crosswalk_judge3_v3.json",
]

GUI_PROP   = WS_GUI / "discovery/cluster_proposal.json"
GUI_MAP    = WS_GUI / "consensus_mapping_gui.json"
GUI_LABELS = WS_GUI / "classification/cluster_labels.jsonl"
GUI_JUDGES = [
    WS_GUI / "crosswalk_judge1_gui_v1.json",
    WS_GUI / "crosswalk_judge2_gui_v1.json",
    WS_GUI / "crosswalk_judge3_gui_v1.json",
]

LEAF_GROUP = {
    "Disobey Specification":        "Execution",
    "Step Repetition":              "Execution",
    "Unaware of Termination":       "Execution",
    "Reasoning-Action Mismatch":    "Coherence",
    "Context Loss":                 "Coherence",
    "Task Derailment":              "Coherence",
    "Premature Termination":        "Verification",
    "Weak Verification":            "Verification",
    "No or Incorrect Verification": "Verification",
    "(not in TB - harness)":        "Out-of-Scope",
    "(not in TB)":                  "Out-of-Scope",
}

GROUP_ORDER = ["Execution", "Coherence", "Verification", "Out-of-Scope"]
LEAF_ORDER = [
    "Disobey Specification", "Step Repetition", "Unaware of Termination",
    "Reasoning-Action Mismatch", "Context Loss", "Task Derailment",
    "Premature Termination", "Weak Verification", "No or Incorrect Verification",
    "(not in TB - harness)",
]

# Android-native one-line framings from rubric_v2.md §C.1
TB_LEAF_DEFINITIONS = {
    "Disobey Specification": (
        "The agent materially contradicts explicit Android-task directives — including using the "
        "**wrong consumer surface** (app DB instead of system provider), the **wrong API level** "
        "(binder hacks instead of intents/role-holders), the **wrong output format/protocol** "
        "(malformed `finish --description`), or **fabricating data** when the source was named. "
        "Also covers the agent disobeying the wrapper's expected input format (per TB11 rev: malformed "
        "JSON / un-prefixed verbs / shell-meta-broken commands)."
    ),
    "Step Repetition": (
        "The agent re-executes the same ADB command class against the same content URI / DB path / "
        "file path multiple times without strategy change. On Android, *command class* = verb + target "
        "surface. Differences in quoting / whitespace / redirection do not count as change."
    ),
    "Unaware of Termination": (
        "The agent continues acting past an Android-recognizable stopping signal — **confirmed "
        "device-state success** (the row is now visible via the canonical reader), **explicit denial** "
        "(`run-as: not debuggable`, `Only sync adapters may write`), or **futility** (≥ 2 consecutive "
        "identical errors from the same surface)."
    ),
    "Reasoning-Action Mismatch": (
        "The agent's stated reasoning is contradicted by its actual command. Android forms: declared "
        "method (\"use ContentProvider\") doesn't match action (used `sqlite3` directly); reasoning "
        "admits uncertainty about a mapping then commits to a guessed value; intended command is sound "
        "but the emitted shell string is malformed and the agent doesn't notice."
    ),
    "Context Loss": (
        "The agent forgets or contradicts established Android device state or task content. Forms: "
        "re-discovers a package it already found, re-queries the device timezone after using it "
        "earlier, paraphrases the task's exact phone number / event title / file content after having "
        "captured it."
    ),
    "Task Derailment": (
        "The agent's pursued sub-goal drifts from the task's primary objective. Android forms: "
        "over-investigating one app of a multi-app task, reading an unrelated app's DB, deep-diving "
        "an unrelated subsystem (clipboard, accessibility, services)."
    ),
    "Premature Termination": (
        "The agent declares completion (via `finish --status complete`) before satisfying explicit or "
        "implicit Android objectives. Two sub-types: **positive PT** (claimed success despite missing "
        "objective) and **negative PT** (submitted \"None\" / empty answer for a retrieval task "
        "without exhausting filter alternatives)."
    ),
    "No or Incorrect Verification": (
        "The agent calls `finish --status complete` without any substantive read against an "
        "authoritative Android surface (`dumpsys` / `content query` / `sqlite3` / `settings get`) — "
        "only self-assertions."
    ),
    "Weak Verification": (
        "The agent verified, but through a surface the consumer doesn't read from "
        "(verify-via-same-DB-as-write, or only the app's UI not the system provider). On Android, the "
        "canonical authoritative surfaces are `dumpsys <service>`, `content query --uri "
        "content://...`, or `sqlite3` against system DBs."
    ),
}


def normalize_leaf(leaf: str) -> str:
    leaf = leaf.strip().replace("–", "-").replace("—", "-")
    low = leaf.lower()
    if low.startswith("(not in tb"):
        return "(not in TB - harness)"
    if low.startswith("reasoning") and "action" in low and "mismatch" in low:
        return "Reasoning-Action Mismatch"
    if low.startswith("unaware") and "termination" in low:
        return "Unaware of Termination"
    return leaf


def load_proposal(path: Path) -> dict[str, dict]:
    d = json.loads(path.read_text())
    return {c["name"]: c for c in d["clusters"]}


def load_consensus(path: Path) -> dict[str, dict]:
    d = json.loads(path.read_text())
    return d["consensus"]  # {cluster: {primary_tb_leaf, method}}


import re as _re
GUI_ONLY_TASK_IDS = {0, 8, 20, 28, 29, 30, 37, 47, 55, 75, 76, 78, 80}
_TID_RE = _re.compile(r"__t(\d+)$")

# Per-trajectory leaf overrides (none active). The 2 CLI shell-quoting RAM
# verdicts from the 2026-05-23 raw audit are folded back into DS so that
# `wrapper_input_format_violation` is a single-leaf cluster under Disobey
# Specification (per TB11 rev: wrapper input format violations are DS).
PER_TRAJECTORY_LEAF_OVERRIDES: dict = {}


# Intervention-type categorization (GUI). Assigned 2026-05-23 from a manual
# review of each cluster's underlying mechanism. Each cluster gets one primary
# intervention type; secondary noted where the fix involves multiple layers.
#
# P = Perception        — screen reading, target disambiguation, visual element ID
# K = Procedural Knowledge — UI affordance / Android convention awareness
# S = Strategic Planning  — task decomposition, method choice, sub-goal ordering
# M = Self-Monitoring     — screen readback, completion verification, loop detection
INTERVENTION_CATEGORIES = {
    "P": ("Perception",
          "screen reading, target disambiguation, visual element ID"),
    "K": ("Procedural Knowledge",
          "UI affordance / Android convention awareness"),
    "S": ("Strategic Planning",
          "task decomposition, method choice, sub-goal ordering"),
    "M": ("Self-Monitoring",
          "screen readback between actions, completion verification, loop detection"),
}

INTERVENTION_BY_CLUSTER = {
    # GUI Disobey Specification (10 active sub-leaves)
    "deletion_or_move_targeted_wrong_row_or_first_match_only":     ("P", "misperceives which file row is the right one (similar names)"),
    "stuck_on_search_or_filter_dialog_with_wrong_field_type":      ("K", "doesn't know date fields require YYYY-MM-DD format"),
    "skipped_source_image_then_fabricated_destination_entries":    ("S", "wrong plan: should open source before destination"),
    "wrong_menu_path_for_markor_rename":                           ("K", "doesn't know Markor's Rename is on long-press, not overflow"),
    "missing_long_press_gesture_for_selection_or_marker":          ("K", "doesn't know long-press is the right gesture for selection"),
    "wrong_clock_face_digit_in_time_picker":                       ("P", "misperceives which TimePicker ring is hours vs minutes"),
    "answer_string_emitted_as_unknown_action_or_omitted_entirely": ("K", "doesn't know answer must be wrapped in action_type:'answer'"),
    "single_clipboard_slot_overwritten_during_multi_source_merge": ("K", "doesn't know clipboard is single-slot; needs paste-between-copies"),
    "missing_two_step_record_or_count_observation":                ("S", "wrong plan: needs observe-between-actions step"),
    "sent_message_in_wrong_conversation_thread":                   ("S", "wrong plan: should back out before starting new conversation"),
    # GUI Step Repetition (after merge: 2 sub-leaves)
    "identical_action_loop_until_step_budget_exhausted":           ("M", "doesn't detect no-state-change loop"),
    "state_blind_coordinate_loop":                                 ("M", "doesn't read screen state between coordinate actions"),
    # GUI Premature Termination (3 sub-leaves)
    "answered_immediately_after_open_app_without_reading_screen":  ("M", "doesn't check screen state before answering"),
    "declared_complete_before_dialog_confirmed":                   ("M", "doesn't verify final state before completion"),
    "filled_only_one_form_instance_for_multi_item_task":           ("S", "wrong plan: should loop for multi-item tasks"),
}


def build_intervention_rollup_section(paradigm: str, counts: dict,
                                       paradigm_n: int) -> list[str]:
    """Build a markdown section showing intervention-type rollup for a paradigm."""
    if paradigm != "GUI":
        return []  # Currently only GUI has the intervention categorization
    md = []
    md.append("\n## Intervention-type categorization (GUI)\n\n")
    md.append("Each sub-leaf is tagged with the **primary intervention** that would "
              "most directly address it. All four categories are *mental-model* "
              "interventions — consistent with the per-trajectory audit finding "
              "that **GUI failures are upstream of execution** (no plan-vs-execution "
              "divergence found in 65/65 audited DS trajectories).\n\n")
    md.append("### Intervention categories\n\n")
    md.append("| code | category | what it fixes |\n|---|---|---|\n")
    for code, (name, desc) in INTERVENTION_CATEGORIES.items():
        md.append(f"| **{code}** | **{name}** | {desc} |\n")
    md.append("\n### Roll-up by intervention type (share-weighted)\n\n")

    # Sum shares by intervention category
    by_intervention = defaultdict(lambda: {"count": 0, "clusters": []})
    for cluster, n in counts.items():
        if cluster not in INTERVENTION_BY_CLUSTER:
            continue
        code, _ = INTERVENTION_BY_CLUSTER[cluster]
        by_intervention[code]["count"] += n
        by_intervention[code]["clusters"].append((cluster, n))

    md.append("| code | category | sub-leaves | n | share |\n|---|---|---|---|---|\n")
    for code in sorted(by_intervention, key=lambda k: -by_intervention[k]["count"]):
        info = by_intervention[code]
        name = INTERVENTION_CATEGORIES[code][0]
        sub_str = ", ".join(f"`{c}` ({n})" for c, n in sorted(info["clusters"], key=lambda kv: -kv[1]))
        share = info["count"] / paradigm_n * 100 if paradigm_n else 0
        md.append(f"| **{code}** | {name} | {sub_str} | {info['count']} | **{share:.1f}%** |\n")
    md.append("\n")

    md.append("### Per-sub-leaf intervention assignment\n\n")
    md.append("| sub-leaf | TB leaf | intervention | rationale |\n|---|---|---|---|\n")
    # Need cluster→leaf mapping; we'll get from caller via counts only, so do without leaf here
    for cluster, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if cluster not in INTERVENTION_BY_CLUSTER:
            continue
        code, rationale = INTERVENTION_BY_CLUSTER[cluster]
        cat_name = INTERVENTION_CATEGORIES[code][0]
        md.append(f"| `{cluster}` | (see below) | **{code}** = {cat_name} | {rationale} |\n")
    md.append("\n---\n")
    return md


def _task_id_from_tid(tid: str) -> int | None:
    m = _TID_RE.search(tid)
    return int(m.group(1)) if m else None


def load_actual_counts(labels_path: Path, filter_cli_solvable: bool = False) -> tuple[int, Counter, int, dict]:
    """Returns (n_kept, cluster_counts, n_dropped, traj_overrides).
    If filter_cli_solvable, drop trajectories whose task_id is in
    GUI_ONLY_TASK_IDS. traj_overrides maps cluster_name → {original_count: int,
    overridden_count: int, override_leaf: str} for clusters where some
    trajectories were re-assigned to a different leaf by audit."""
    if not labels_path.exists():
        return 0, Counter(), 0, {}
    rows = []
    dropped = 0
    overrides = defaultdict(lambda: {"original_count": 0, "overridden_to": Counter()})
    for line in labels_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if "error" in r:
                continue
            if filter_cli_solvable:
                tid = _task_id_from_tid(r.get("trajectory_id", ""))
                if tid is not None and tid in GUI_ONLY_TASK_IDS:
                    dropped += 1
                    continue
            tid_str = r.get("trajectory_id", "")
            cluster = r["primary_cluster"]
            if tid_str in PER_TRAJECTORY_LEAF_OVERRIDES:
                override_leaf, _ = PER_TRAJECTORY_LEAF_OVERRIDES[tid_str]
                overrides[cluster]["overridden_to"][override_leaf] += 1
            rows.append(cluster)
        except Exception:
            pass
    return len(rows), Counter(rows), dropped, dict(overrides)


def load_judges(judge_paths: list[Path]) -> dict[str, list[dict]]:
    """Returns {cluster_name: [{judge, primary, secondaries, rationale}]}"""
    out = defaultdict(list)
    for jp in judge_paths:
        if not jp.exists():
            continue
        d = json.loads(jp.read_text())
        judge = d.get("judge", jp.stem)
        for m in d.get("mappings", []):
            out[m["cluster_name"]].append({
                "judge": judge,
                "primary": normalize_leaf(m["primary_tb_leaf"]),
                "secondaries": [normalize_leaf(s) for s in (m.get("secondary_tb_leaves") or [])],
                "rationale": m.get("rationale", ""),
            })
    return out


# Presentation-layer merges: collapse multiple bottom-up clusters into a
# single named display sub-leaf when their TB-leaf mapping is the same
# AND their underlying mechanism is a family of one pattern. The
# original clusters are preserved in the cluster_proposal.json; merging
# happens only at doc/figure render time.
DISPLAY_MERGES = {
    # paradigm → {merged_name: [source_clusters]}
    "GUI": {
        "state_blind_coordinate_loop": [
            "fixed_coordinate_delete_macro_on_reflowing_list",
            "horizontal_chip_row_scroll_failure_in_pro_expense",
            "calendar_chevron_oscillation_without_view_switch",
        ],
    },
    "CLI": {
        # Merge of 2 wrapper-input-format clusters per Step 2 (2026-05-23)
        "wrapper_input_format_violation": [
            "shell_quoting_or_harness_parse_blocked_action",
            "harness_verb_or_command_prefix_violation",
        ],
        # Merge of 3 "right surface, wrong value" clusters per Step 2 (2026-05-23)
        "wrong_output_value_at_correct_surface": [
            "time_or_timezone_misinterpretation",
            "recurrence_or_filter_predicate_omission",
            "byte_exact_file_content_mismatch",
        ],
    },
}

# Merged cluster metadata (shown in the taxonomy doc in place of the source clusters)
MERGED_CLUSTER_META = {
    "wrapper_input_format_violation": {
        "description": (
            "Agent's emitted shell command / JSON tool-call payload violates the "
            "wrapper / harness expected input protocol — apostrophe/quote bugs in "
            "SQL strings, multi-line commands rejected by Terminus2's parser, "
            "max_tokens truncation that leaves the parser with partial JSON, "
            "tool-call prefix violations (bare `<verb>` when the wrapper expects "
            "`adb shell <verb>`). The agent's reasoning typically describes a "
            "sound command at the abstract level; the failure surfaces at the "
            "byte/character level the wrapper enforces. Per TB11 (rev 2026-05-22), "
            "this maps to Disobey Specification (wrong output protocol)."
        ),
        "transcript_signature": (
            "Wrapper rejects an action before it reaches the device — `<llm-error>` "
            "from token-limit truncation, `Extra data: line N column M` from JSON "
            "parse failure, `not a recognized verb` from missing `adb shell` "
            "prefix, or sqlite syntax error from apostrophe-broken quoting. The "
            "agent's reasoning was typically the abstract intent (correct), but "
            "the emitted bytes carry the bug."
        ),
        "est_fraction": 0.045,
        "variant_skew": "bash_tool-skewed",
        "agent_skew_note": (
            "shell_quoting (83): bash_tool-skewed (wrappers enforce strict JSON parsing); "
            "harness_verb (3): bash_tool-only (mini-swe-agent enforces `adb shell` prefix)."
        ),
    },
    "wrong_output_value_at_correct_surface": {
        "description": (
            "Agent reaches the correct surface (right DB, right file path, right "
            "query target) but emits a wrong value or wrong query semantics: "
            "timezone/epoch offset (TB7), missing SQL recurrence/filter predicate "
            "(TB10), wrong byte separator or trailing-newline pattern (file "
            "content). The agent's reasoning is consistent with the action at "
            "each step; the failure is in the *semantic interpretation* of "
            "what the spec wanted (which timezone, which recurrence rule, which "
            "newline pattern). Per TB3/7/10, this is the canonical 'right "
            "surface, wrong value' family of Disobey Specification."
        ),
        "transcript_signature": (
            "Final write hits the verifier's surface (correct sqlite DB / file / "
            "content URI) but a specific field — start_ts, dueDate, completed "
            "filter, separator, recurrence expansion — fails the per-field check. "
            "The agent's prior reasoning explains the wrong interpretation as if "
            "it were correct; no observable plan-vs-action divergence."
        ),
        "est_fraction": 0.13,
        "variant_skew": "balanced",
        "agent_skew_note": (
            "time_or_timezone_misinterpretation (80): semantic time/wall-clock errors; "
            "recurrence_or_filter_predicate_omission (76): missing SQL recurrence/filter expansion; "
            "byte_exact_file_content_mismatch (70): wrong separator/newline pattern."
        ),
    },
    "state_blind_coordinate_loop": {
        "description": (
            "Agent fires a coordinate-bound action sequence (multi-tap macro, "
            "scroll-strip, or alternating chevron) repeatedly **without re-reading "
            "the screen between cycles**. The action *does* change screen state, "
            "but the agent's mental model of the screen doesn't update, so the "
            "loop produces wrong-target actions (rows shifted), zero progress "
            "(actions cancel each other), or no-effect actions (UI ignored the "
            "input). Distinct from `identical_action_loop_until_step_budget_"
            "exhausted` which fires the same action when the screen genuinely "
            "doesn't change."
        ),
        "transcript_signature": (
            "Repeated coordinate-bound action patterns (≥5 cycles) without any "
            "intermediate read/observe step; reasoning narrates expected progress "
            "that the rendered screen does not confirm. Three observed app-specific "
            "flavors: (a) Broccoli RecipeListActivity 4-tap delete macro at fixed Y "
            "while list reflows upward; (b) Pro Expense category chip strip with "
            "≥10 consecutive horizontal scrolls and no taps; (c) Simple Calendar "
            "Pro header chevron alternation for 30-44 steps with net-zero position "
            "change."
        ),
        "est_fraction": 0.12,  # ~12% (sum of est_fractions: 6+3+3 = 12%)
        "agent_skew": "mixed",
        "agent_skew_note": (
            "Broccoli reflow trap: balanced (all 3 GUI agents); "
            "Pro Expense chip strip: MAI-UI-skewed; "
            "Calendar chevron oscillation: Qwen3VL-only."
        ),
    },
}


# Presentation-layer renames. Raw JSONL/judge transcripts keep the original
# bottom-up names for provenance; user-visible docs/figures use the aliases.
CLUSTER_DISPLAY_ALIAS = {
    # Original name implied a task property ("task_required_..."); the cluster
    # actually captures the AGENT's false-impossibility conclusion. Renamed so
    # readers don't think these trajectories used a GUI (they can't — CLI
    # agents have no screen access).
    "task_required_gui_only_no_cli_pathway": "agent_concluded_no_cli_pathway",
}

CLUSTER_DESCRIPTION_OVERRIDE = {
    "agent_concluded_no_cli_pathway": {
        "description": (
            "Agent assumed the task requires UI interaction and gave up on the "
            "CLI pathway — fabricating artifacts (hand-crafted bytes/rows), "
            "computing answers offline via `bc`/`awk`/sed-injected JS, or "
            "calling `finish` with a guessed/empty answer — *without* "
            "attempting the canonical shell surfaces (`am broadcast`, "
            "`content insert`/`content update`, `sqlite3` INSERT) that "
            "ground-truth says exist for these tasks. Every fair-view "
            "occurrence is on a CLI-solvable task per the AndroidWorld "
            "ground-truth reference, so the cluster captures the agent's "
            "*false-impossibility conclusion* (a wrong-API-level Disobey "
            "Specification per Tie-breaker 1), not a task property. "
            "CLI agents have no screen access; none of these trajectories "
            "use a UI."
        ),
        "transcript_signature": (
            "Agent reverse-engineers SeededRNG in `bc`/`awk`, sed-injects "
            "`setTimeout(...moveCharacter)` into task.html, or fabricates "
            "rows mirroring a UI editor's prefill, then calls `finish` "
            "(often with `--status incomplete`) without ever issuing the "
            "available `am broadcast`, ContentProvider write, or sqlite "
            "INSERT that the verifier would read."
        ),
    },
}


def apply_display_aliases(proposal: dict, consensus: dict,
                          counts: Counter, judges: dict
                          ) -> tuple[dict, dict, Counter, dict]:
    """Rename clusters per CLUSTER_DISPLAY_ALIAS for user-facing rendering."""
    if not CLUSTER_DISPLAY_ALIAS:
        return proposal, consensus, counts, judges

    new_proposal = dict(proposal)
    new_consensus = dict(consensus)
    new_counts = Counter(counts)
    new_judges = dict(judges)

    for old, new in CLUSTER_DISPLAY_ALIAS.items():
        if old in new_proposal:
            entry = dict(new_proposal.pop(old))
            entry["name"] = new
            override = CLUSTER_DESCRIPTION_OVERRIDE.get(new)
            if override:
                entry["description"] = override["description"]
                entry["transcript_signature"] = override["transcript_signature"]
            new_proposal[new] = entry
        if old in new_consensus:
            new_consensus[new] = new_consensus.pop(old)
        if old in new_counts:
            new_counts[new] = new_counts.pop(old)
        if old in new_judges:
            new_judges[new] = new_judges.pop(old)
    return new_proposal, new_consensus, new_counts, new_judges


def apply_display_merges(paradigm_label: str, proposal: dict, consensus: dict,
                         counts: Counter, judges: dict
                         ) -> tuple[dict, dict, Counter, dict]:
    """Apply presentation-layer merges. Returns adapted (proposal, consensus,
    counts, judges) with merged clusters substituted for their sources."""
    merges = DISPLAY_MERGES.get(paradigm_label, {})
    if not merges:
        return proposal, consensus, counts, judges

    new_proposal = dict(proposal)
    new_consensus = dict(consensus)
    new_counts = Counter(counts)
    new_judges = dict(judges)

    for merged_name, source_names in merges.items():
        sources = [s for s in source_names if s in proposal]
        if not sources:
            continue
        # Sum counts
        merged_count = sum(counts.get(s, 0) for s in sources)
        for s in sources:
            new_counts.pop(s, None)
        new_counts[merged_name] = merged_count
        # Build merged proposal entry
        meta = MERGED_CLUSTER_META[merged_name]
        # Total est_fraction = sum of sources
        total_est = sum(proposal[s].get("est_fraction", 0) for s in sources)
        new_proposal[merged_name] = {
            "name": merged_name,
            "description": meta["description"],
            "transcript_signature": meta["transcript_signature"],
            "est_fraction": total_est,
            # CLI uses variant_skew, GUI uses agent_skew — propagate whichever was set
            "variant_skew": meta.get("variant_skew"),
            "agent_skew": meta.get("agent_skew"),
            "agent_skew_note": meta.get("agent_skew_note"),
            "merged_from": list(sources),
            "merged_source_counts": {s: counts.get(s, 0) for s in sources},
        }
        for s in sources:
            new_proposal.pop(s, None)
        # All sources share the same TB leaf (precondition); take any
        first_leaf = consensus[sources[0]]["primary_tb_leaf"]
        new_consensus[merged_name] = {
            "primary_tb_leaf": first_leaf,
            "method": "merged",
        }
        for s in sources:
            new_consensus.pop(s, None)
        # Combine judge rationales (take first 1 per judge across sources)
        combined = []
        for s in sources:
            for jr in judges.get(s, []):
                combined.append({
                    **jr,
                    "rationale": f"[{s}] {jr['rationale']}",
                })
        new_judges[merged_name] = combined
        for s in sources:
            new_judges.pop(s, None)

    return new_proposal, new_consensus, new_counts, new_judges


def build_section(paradigm_label: str, paradigm_n_full: int,
                  paradigm_n_classified: int, proposal: dict,
                  consensus: dict, counts: Counter, judges: dict,
                  classified_label: str,
                  traj_overrides: dict | None = None) -> list[str]:
    """Build markdown for one paradigm."""
    proposal, consensus, counts, judges = apply_display_merges(
        paradigm_label, proposal, consensus, counts, judges)
    proposal, consensus, counts, judges = apply_display_aliases(
        proposal, consensus, counts, judges)
    traj_overrides = traj_overrides or {}

    md = []
    md.append(f"# {paradigm_label} Paradigm\n\n")
    md.append(f"- **Failure trajectories (fair view):** {paradigm_n_classified:,} — {classified_label}\n")
    md.append(f"- **Sub-leaves discovered (Phase 2 Docent):** {len(proposal)} (after presentation-layer merges)\n\n")

    # Intervention-type rollup (GUI only currently)
    md.extend(build_intervention_rollup_section(paradigm_label, counts, paradigm_n_classified))

    # Group clusters by TB leaf
    by_leaf = defaultdict(list)
    for name, c in proposal.items():
        leaf = normalize_leaf(consensus.get(name, {}).get("primary_tb_leaf", "?"))
        by_leaf[leaf].append((name, c))

    for group in GROUP_ORDER:
        leaves_in_group = [l for l in LEAF_ORDER
                           if LEAF_GROUP.get(l) == group and l in by_leaf]
        if not leaves_in_group and group != "Out-of-Scope":
            md.append(f"\n## {group}\n\n*No sub-leaves observed in this paradigm.*\n")
            continue
        md.append(f"\n## {group}\n")
        for leaf in leaves_in_group:
            clusters = by_leaf.get(leaf, [])
            n_actual = sum(counts.get(name, 0) for name, _ in clusters)
            share_actual = (n_actual / paradigm_n_classified * 100
                            if paradigm_n_classified else 0)
            sum_est = sum(c.get("est_fraction", 0) for _, c in clusters)
            md.append(f"\n### {leaf}\n\n")
            # TB leaf definition (Android-native, from rubric_v2.md §C.1)
            definition = TB_LEAF_DEFINITIONS.get(leaf)
            if definition:
                md.append(f"> **Definition.** {definition}\n\n")
            md.append(f"- TB top-level: **{group}**\n")
            md.append(f"- Sub-leaves under this TB leaf: **{len(clusters)}**\n")
            md.append(f"- Phase 2 estimated mass: **{sum_est*100:.1f}%**\n")
            if paradigm_n_classified:
                md.append(f"- Phase 3 actual share: **{share_actual:.1f}%** ({n_actual} of {paradigm_n_classified})\n")
            md.append("\n")
            # Sort clusters by actual count desc, then est_fraction
            clusters_sorted = sorted(clusters,
                                      key=lambda kv: (-counts.get(kv[0], 0),
                                                       -kv[1].get("est_fraction", 0)))
            for name, c in clusters_sorted:
                est = c.get("est_fraction", 0) * 100
                act = counts.get(name, 0)
                act_pct = act / paradigm_n_classified * 100 if paradigm_n_classified else 0
                variant_or_agent_skew = c.get("variant_skew") or c.get("agent_skew", "balanced")
                md.append(f"#### `{name}`\n\n")
                if c.get("merged_from"):
                    md.append(f"- **Display-merged from {len(c['merged_from'])} bottom-up clusters:**\n")
                    for src in c["merged_from"]:
                        src_count = c["merged_source_counts"].get(src, 0)
                        md.append(f"  - `{src}` (Phase 3 count: {src_count})\n")
                md.append(f"- Description: {c.get('description','').strip()}\n")
                md.append(f"- Transcript signature: {c.get('transcript_signature','').strip()}\n")
                md.append(f"- Phase 2 est_fraction: **{est:.1f}%**\n")
                if paradigm_n_classified:
                    md.append(f"- Phase 3 actual count: **{act}** ({act_pct:.1f}% of classified)\n")
                md.append(f"- Skew: {variant_or_agent_skew}\n")
                # Intervention type tag (GUI only for now)
                if name in INTERVENTION_BY_CLUSTER:
                    code, rat = INTERVENTION_BY_CLUSTER[name]
                    cat_name = INTERVENTION_CATEGORIES[code][0]
                    md.append(f"- **Intervention type: {code} = {cat_name}** — {rat}\n")
                if c.get("agent_skew_note") and c.get("merged_from"):
                    md.append(f"- Per-variant skew: {c['agent_skew_note']}\n")
                # Surface per-trajectory leaf-override note (from DS-vs-RAM audit)
                ov = traj_overrides.get(name)
                if ov and ov.get("overridden_to"):
                    parts = ", ".join(f"{leaf} ({n})" for leaf, n in ov["overridden_to"].items())
                    md.append(f"- **Per-trajectory leaf overrides** (from DS-vs-RAM audit): "
                              f"{parts}\n")
                # Judges' rationale (show majority + dissent)
                jrows = judges.get(name, [])
                if jrows:
                    rat_lines = []
                    for jr in jrows:
                        rat_lines.append(f"  - **{jr['judge']}** → "
                                          f"primary={jr['primary']}; "
                                          f"rationale: {jr['rationale'].strip()[:300]}")
                    md.append("- Cross-walk rationale (3 judges):\n" + "\n".join(rat_lines) + "\n")
                md.append("\n")

        # Absent leaves under this group
        absent = [l for l in LEAF_ORDER
                  if LEAF_GROUP.get(l) == group and l not in by_leaf]
        if absent:
            md.append(f"\n#### *Absent TB leaves under {group}:*\n\n")
            for l in absent:
                md.append(f"- *{l}* — no clusters mapped here in {paradigm_label} paradigm\n")
            md.append("\n")
    return md


def main():
    cli_prop  = load_proposal(CLI_PROP)
    cli_cons  = load_consensus(CLI_MAP)
    # Fair-comparison filter: drop trajectories on the 13 AndroidWorld GUI-only tasks
    cli_n, cli_counts, cli_dropped, cli_overrides = load_actual_counts(CLI_LABELS, filter_cli_solvable=True)
    cli_judges = load_judges(CLI_JUDGES)

    gui_prop  = load_proposal(GUI_PROP)
    gui_cons  = load_consensus(GUI_MAP)
    gui_n, gui_counts, gui_dropped, gui_overrides = load_actual_counts(GUI_LABELS, filter_cli_solvable=True)
    gui_judges = load_judges(GUI_JUDGES)

    # Exclude clusters with 0 fair-comparison count (e.g., GUI's
    # single_tap_on_html_canvas which is entirely on GUI-only tasks)
    cli_prop = {k: v for k, v in cli_prop.items() if cli_counts.get(k, 0) > 0}
    gui_prop = {k: v for k, v in gui_prop.items() if gui_counts.get(k, 0) > 0}

    md = []
    md.append("# Two-Level Failure Taxonomy\n\n")
    md.append("This document catalogs the full 2-level failure taxonomy:\n\n")
    md.append("- **Top level (paradigm-agnostic):** Terminal-Bench 9-leaf taxonomy + 1 Out-of-Scope category (paper extension)\n")
    md.append("- **Bottom level (paradigm-specific):** Docent-discovered sub-leaves (clusters) from bottom-up clustering\n\n")
    md.append("**Methodology:**\n\n")
    md.append("1. Phase 1: per-trajectory failure summary (Claude Opus 4.7)\n")
    md.append("2. Phase 2: Docent bottom-up clustering on all summaries → emergent clusters\n")
    md.append("3. Phase 3 cross-walk: 3 cross-family LLM judges (Claude Opus 4.7 + GPT-5.5 Pro + Gemini 2.5 Pro) map each cluster → TB leaf, using `rubric_v2.md` + `rubric_v2_clarifications.md` (16 tie-breakers). Fleiss κ targets ≥ 0.90.\n")
    md.append("4. Phase 3 classification: per-trajectory cluster labels (Sonnet 4.6 for CLI; Opus 4.7 for GUI)\n")
    md.append("5. **Fair-comparison filter (applied throughout this doc).** All counts and percentages reported below are restricted to the 103 CLI-solvable AndroidWorld tasks per the ground-truth reference; 13 GUI-only tasks (canvas/maze/camera/transcribe/multi-from-image) are excluded from both paradigms so the CLI and GUI distributions are directly comparable.\n\n")
    md.append("## Cross-paradigm summary (fair view)\n\n")
    md.append("| paradigm | trajectories | sub-leaves | TB leaves activated |\n|---|---|---|---|\n")

    cli_leaves_active = sum(1 for c, m in cli_cons.items()
                            if normalize_leaf(m["primary_tb_leaf"]) and c in cli_prop)
    cli_leaves_active = len({normalize_leaf(cli_cons[c]["primary_tb_leaf"]) for c in cli_prop})
    gui_leaves_active = len({normalize_leaf(gui_cons[c]["primary_tb_leaf"]) for c in gui_prop})
    # Sub-leaf count after presentation-layer merges (if any)
    def post_merge_count(paradigm: str, n_original: int) -> str:
        merges = DISPLAY_MERGES.get(paradigm, {})
        if not merges:
            return f"{n_original}"
        n_collapsed = sum(len(srcs) - 1 for srcs in merges.values())
        return f"{n_original - n_collapsed} (after merging {n_collapsed + len(merges)} clusters)"

    md.append(f"| CLI | {cli_n:,} | {post_merge_count('CLI', len(cli_prop))} | {cli_leaves_active} of 9 |\n")
    md.append(f"| GUI | {gui_n} | {post_merge_count('GUI', len(gui_prop))} | {gui_leaves_active} of 9 |\n\n")
    md.append("---\n\n")

    # TB 9-leaf definitions (top-level reference)
    md.append("## TB 9-Leaf Definitions\n\n")
    md.append("Android-native one-line framings from `rubric_v2.md` §C.1. These are the "
              "**paradigm-agnostic top-level labels**; the bottom-level sub-leaves (clusters) under "
              "each are paradigm-specific and listed in the per-paradigm sections below.\n\n")
    GROUP_DESCRIPTIONS = {
        "Execution":    "the agent's action *itself* deviates from the spec (wrong method, looping, ignoring stop)",
        "Coherence":    "the agent's *reasoning* drifts from observation or task state",
        "Verification": "the agent's *check* before declaring done is missing, wrong, or weak",
    }
    last_group = None
    for leaf in LEAF_ORDER:
        if leaf not in TB_LEAF_DEFINITIONS:
            continue
        group = LEAF_GROUP[leaf]
        if group != last_group:
            md.append(f"\n### {group} group\n\n")
            md.append(f"*{GROUP_DESCRIPTIONS.get(group, '')}*\n\n")
            last_group = group
        md.append(f"**{leaf}.** {TB_LEAF_DEFINITIONS[leaf]}\n\n")
    md.append("---\n\n")

    md.extend(build_section("CLI", None, cli_n, cli_prop, cli_cons,
                             cli_counts, cli_judges,
                             "Sonnet 4.6 reasoning=high per-trajectory classification",
                             traj_overrides=cli_overrides))
    md.append("\n---\n\n")
    md.extend(build_section("GUI", None, gui_n, gui_prop, gui_cons,
                             gui_counts, gui_judges,
                             "Opus 4.7 reasoning=high per-trajectory classification",
                             traj_overrides=gui_overrides))

    md.append("\n---\n\n")
    md.append("## Tie-breaker rules referenced\n\n")
    md.append("All cross-walk decisions follow the base `rubric_v2.md` plus 16 numbered tie-breakers in `rubric_v2_clarifications.md`:\n\n")
    md.append("| # | covers cluster pattern | maps to |\n|---|---|---|\n")
    md.append("| TB1 | UI-required tasks (no shell pathway) | Disobey Specification (wrong API level) |\n")
    md.append("| TB2 | OCR/vision-required tasks | Disobey Specification (wrong API level) |\n")
    md.append("| TB3 | Right surface, wrong value | Disobey Specification (wrong output format) |\n")
    md.append("| TB4 | Q&A from wrong provider | Premature Termination |\n")
    md.append("| TB5 | Intent to nonexistent receiver | Reasoning-Action Mismatch |\n")
    md.append("| TB6 | Recon-only without mutation | Disobey Specification |\n")
    md.append("| TB7 | Timezone/epoch misinterpretation | Disobey Specification (right surface, wrong value) |\n")
    md.append("| TB8 | Clipboard read from shell uid | Disobey Specification (wrong API level) |\n")
    md.append("| TB9 | Dispatch-as-state-change | Reasoning-Action Mismatch |\n")
    md.append("| TB10 | SQL predicate / filter omission | Disobey Specification |\n")
    md.append("| TB11 | Harness/wrapper-layer failures (rev 2026-05-22) | Disobey Specification (wrong output protocol) |\n")
    md.append("| TB12 | Skipped intermediate observation step (GUI) | Disobey Specification |\n")
    md.append("| TB13 | Wrong field-type input in dialog (GUI) | Disobey Specification |\n")
    md.append("| TB14 | Wrong menu/navigation path (GUI) | Disobey Specification |\n")
    md.append("| TB15 | Wrong row/item target on list (GUI) | Disobey Specification |\n")
    md.append("| TB16 | Clipboard overwrite during multi-source merge (GUI) | Disobey Specification |\n")
    md.append("\nFor full text of each tie-breaker, see:\n")
    md.append("- CLI: `docent_analyses/2026-05-21_android-cli-failures-combined/rubric_v2_clarifications.md`\n")
    md.append("- GUI: `docent_analyses/2026-05-22_android-gui-failures/rubric_v2_clarifications.md`\n")

    out_path = ROOT / "taxonomy.md"
    out_path.write_text("".join(md))
    print(f"wrote → {out_path}")
    print(f"  size: {out_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
