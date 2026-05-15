"""Apply heuristic pattern detectors across all 126 readable failures.

Exploratory: not the formal Phase 4 LLM judge. The detectors are simple
string/regex matches against the patterns surfaced in
`annotations/notes.md` from the 10-trajectory blind read.

Outputs:
  data/pattern_flags.jsonl   — per-trajectory flags (one row per traj)
  data/pattern_summary.md    — human report: per-flag counts, per-config
                               breakdown, co-occurrence, primary cluster
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "failure_analysis/androidworld/cli"))

DATA_DIR = REPO / "failure_analysis/androidworld/cli/data"
PILOT_PATH = DATA_DIR / "pilot_set.jsonl"


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

QUOTING_ERROR_RE = re.compile(
    r"(syntax error|no closing quote|incomplete input|unterminated|"
    r"unknown command|missing closing|unexpected EOF|"
    r"adb: usage:|content \[subcommand\]|usage: adb shell content)",
    re.IGNORECASE,
)

APK_EXTRACTION_RE = re.compile(
    # Match only clearly-forbidden patterns from the agent's own system prompt:
    #   "extracting APKs (unzip / xxd / strings on base.apk or classes.dex)"
    r"(\baapt2?\b|"
    r"\bunzip\b[^\n]*(\.apk|\.dex|/base\.apk)|"
    r"\bxxd\b[^\n]*(\.apk|\.dex|/base\.apk)|"
    r"\bstrings\b[^\n]*(\.apk|\.dex|/base\.apk)|"
    r"/data/app/[^\s\"']+/base\.apk|"
    r"\bclasses\.dex\b)",
    re.IGNORECASE,
)

INFEASIBLE_RE = re.compile(
    r"(could not|cannot|unable to|infeasible|not possible|"
    r"no\s+support|no\s+writable\s+surface|blocked\s+by|"
    r"under\s+the\s+given\s+constraints|exhausted\s+(all|the))",
    re.IGNORECASE,
)

SQLITE_INSERT_APP_DB_RE = re.compile(
    r"sqlite3\s+(/data/(?:user/0|data)/[^\s\"']+)[^\n]*INSERT\s+INTO",
    re.IGNORECASE | re.DOTALL,
)
SQLITE_SELECT_APP_DB_RE = re.compile(
    r"sqlite3\s+(/data/(?:user/0|data)/[^\s\"']+)[^\n]*SELECT\b",
    re.IGNORECASE | re.DOTALL,
)
MEDIASTORE_INSERT_RE = re.compile(
    r"content\s+insert\s+--uri\s+content://media/",
    re.IGNORECASE,
)
SYSTEM_PROVIDER_INSERT_RE = re.compile(
    r"content\s+insert\s+--uri\s+content://(sms|contacts|com\.android\.contacts|calendar|com\.android\.calendar)",
    re.IGNORECASE,
)
APP_PROVIDER_INSERT_RE = re.compile(
    r"content\s+insert\s+--uri\s+content://[a-z][a-z0-9_]*\.[^\s/]+",
    re.IGNORECASE,
)
FINISH_CALL_RE = re.compile(
    r"\bfinish\s+--status\s+complete\b|"
    r"\bmark_task_complete\(|"
    r'"task_complete"\s*:\s*true|'
    r"\btask_complete\b\s*=\s*True",
    re.IGNORECASE,
)


def collect_text(path: Path) -> tuple[str, list[str], list[str]]:
    """Return (full_text, agent_messages, observation_messages) for a trajectory.

    Format-agnostic: handles ATIF and MiniSWE native.
    """
    raw = json.loads(path.read_text())
    agent_msgs: list[str] = []
    obs_msgs: list[str] = []
    if raw.get("schema_version", "").startswith("ATIF-"):
        for s in raw.get("steps", []):
            src = s.get("source")
            msg = s.get("message") or ""
            if src in ("agent", "assistant", "model"):
                agent_msgs.append(msg)
                obs = s.get("observation")
                if obs:
                    obs_text = obs if isinstance(obs, str) else json.dumps(obs)
                    obs_msgs.append(obs_text)
    elif "messages" in raw:  # MiniSWE native
        for m in raw["messages"]:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "assistant":
                agent_msgs.append(content)
            elif role == "user":  # in MiniSWE native, user msgs are observations after the first
                if obs_msgs or agent_msgs:  # skip the initial task description
                    obs_msgs.append(content)
    full = "\n".join(agent_msgs + obs_msgs)
    return full, agent_msgs, obs_msgs


def detect_quoting_retries(obs_msgs: list[str]) -> bool:
    """3+ consecutive observations matching a shell/parse-error pattern."""
    streak = 0
    for o in obs_msgs:
        if QUOTING_ERROR_RE.search(o):
            streak += 1
            if streak >= 3:
                return True
        else:
            streak = 0
    return False


def detect_self_verify_same_db(agent_msgs: list[str]) -> bool:
    """Agent INSERTs into a /data/.../db then SELECTs from same path."""
    inserted_dbs: set[str] = set()
    for msg in agent_msgs:
        for m in SQLITE_INSERT_APP_DB_RE.finditer(msg):
            inserted_dbs.add(m.group(1))
    if not inserted_dbs:
        return False
    for msg in agent_msgs:
        for m in SQLITE_SELECT_APP_DB_RE.finditer(msg):
            if m.group(1) in inserted_dbs:
                return True
    return False


def detect_wrong_surface(agent_msgs: list[str], task_name: str) -> str | None:
    """Heuristic — returns surface label if the trajectory looks like it
    used a non-canonical write surface for the named task class."""
    full = "\n".join(agent_msgs).lower()
    task_low = (task_name or "").lower()
    has_app_db_insert = bool(SQLITE_INSERT_APP_DB_RE.search("\n".join(agent_msgs)))
    has_mediastore_insert = bool(MEDIASTORE_INSERT_RE.search(full))
    has_system_provider = bool(SYSTEM_PROVIDER_INSERT_RE.search(full))
    if has_app_db_insert and not has_system_provider and any(
        kw in task_low for kw in ("sms", "contact", "calendar", "alarm")
    ):
        return "app_db_for_system_provider_task"
    if has_mediastore_insert and any(
        kw in task_low for kw in ("retro music", "playlist", "music", "vlc")
    ):
        return "mediastore_for_app_specific_player"
    if has_app_db_insert and "expense" in task_low:
        return "app_db_no_mapping_recovery"
    return None


def detect_apk_extraction(agent_msgs: list[str]) -> bool:
    full = "\n".join(agent_msgs)
    return bool(APK_EXTRACTION_RE.search(full))


def detect_no_finish(full_text: str) -> bool:
    return not bool(FINISH_CALL_RE.search(full_text))


def detect_infeasibility_admission(full_text: str, submission: str | None) -> bool:
    text = (submission or "") + "\n" + full_text[-3000:]
    return bool(INFEASIBLE_RE.search(text))


def detect_hit_max_turns(row: dict) -> bool:
    sc = row.get("step_count") or 0
    mt = row.get("max_turns") or 0
    return mt > 0 and sc >= mt


def detect_long_quoting_streak(obs_msgs: list[str]) -> int:
    """Returns max consecutive quoting-error streak length (for diagnostics)."""
    longest, streak = 0, 0
    for o in obs_msgs:
        if QUOTING_ERROR_RE.search(o):
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    return longest


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def get_submission(path: Path) -> str | None:
    raw = json.loads(path.read_text())
    if "info" in raw:
        return (raw.get("info") or {}).get("submission")
    return None


def cluster_one(row: dict) -> dict:
    p = REPO / row["traj_path"]
    full, agent_msgs, obs_msgs = collect_text(p)
    submission = get_submission(p)

    flags = {
        "quoting_retries": detect_quoting_retries(obs_msgs),
        "quoting_streak_max": detect_long_quoting_streak(obs_msgs),
        "self_verify_same_db": detect_self_verify_same_db(agent_msgs),
        "wrong_surface_kind": detect_wrong_surface(agent_msgs, row.get("task_name") or ""),
        "apk_extraction": detect_apk_extraction(agent_msgs),
        "no_finish_call": detect_no_finish(full),
        "infeasibility_admitted": detect_infeasibility_admission(full, submission),
        "hit_max_turns": detect_hit_max_turns(row),
    }

    # Primary cluster — pick the most "diagnostic" agent-behavior signal.
    # Note: `no_finish_call` is intentionally NOT a primary cluster — it's an
    # ATIF-export artifact (ClaudeCodeCLI / Terminus2: ~100%; MiniSweAgent: 0%)
    # and would dominate the distribution without describing agent behavior.
    primary = "unclassified"
    if flags["apk_extraction"]:
        primary = "self_prompt_violation_apk"
    elif flags["wrong_surface_kind"]:
        primary = f"wrong_surface__{flags['wrong_surface_kind']}"
    elif flags["self_verify_same_db"]:
        primary = "verify_through_same_surface"
    elif flags["infeasibility_admitted"]:
        primary = "honest_infeasibility"
    elif flags["hit_max_turns"]:
        primary = "hit_max_turns"
    elif flags["quoting_retries"]:
        primary = "shell_quoting_fight"

    return {
        "trajectory_id": row["trajectory_id"],
        "config": row["config"],
        "agent_class": row["agent_class"],
        "task_id": row["task_id"],
        "task_name": (row.get("task_name") or "")[:100],
        "step_count": row.get("step_count"),
        "max_turns": row.get("max_turns"),
        "submission_preview": (submission or "")[:200] if submission else None,
        **flags,
        "primary_cluster": primary,
    }


def main():
    rows = [json.loads(l) for l in PILOT_PATH.read_text().splitlines() if l.strip()]
    print(f"Clustering {len(rows)} failures...")
    out: list[dict] = []
    for i, r in enumerate(rows):
        try:
            out.append(cluster_one(r))
        except Exception as e:
            print(f"  ERROR on {r['trajectory_id']}: {type(e).__name__}: {e}")
    out_path = DATA_DIR / "pattern_flags.jsonl"
    out_path.write_text("\n".join(json.dumps(r) for r in out) + "\n")
    print(f"  wrote {out_path.relative_to(REPO)}")

    # ---- summary ----
    flag_keys = [
        "quoting_retries", "self_verify_same_db", "apk_extraction",
        "no_finish_call", "infeasibility_admitted", "hit_max_turns",
    ]
    cluster_counts = Counter(r["primary_cluster"] for r in out)
    flag_counts = Counter()
    for r in out:
        for k in flag_keys:
            if r.get(k):
                flag_counts[k] += 1
    wrong_surface_counts = Counter(r["wrong_surface_kind"] for r in out if r.get("wrong_surface_kind"))

    by_config_cluster: dict[str, Counter] = defaultdict(Counter)
    for r in out:
        by_config_cluster[r["config"]][r["primary_cluster"]] += 1

    by_config_flag: dict[str, Counter] = defaultdict(Counter)
    for r in out:
        for k in flag_keys:
            if r.get(k):
                by_config_flag[r["config"]][k] += 1

    # Co-occurrence: pairs of flags
    cooc: Counter = Counter()
    for r in out:
        active = [k for k in flag_keys if r.get(k)]
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                cooc[(active[i], active[j])] += 1

    # ---- Markdown report ----
    md = []
    md.append("# Heuristic Pattern Clustering — All 126 Failures")
    md.append("")
    md.append("> **Exploratory only.** Pattern detectors are regex/string heuristics derived from")
    md.append("> the 10-trajectory blind read. NOT rubric labels — those come from Phase 3+4.")
    md.append("> Use this to spot signal/clusters early and validate that the patterns from the")
    md.append("> 10-sample generalize.")
    md.append("")
    md.append(f"**Pool:** {len(out)} failures from `pilot_set.jsonl`")
    md.append("")

    md.append("## Primary cluster distribution")
    md.append("")
    md.append("| Cluster | Count | % |")
    md.append("|---|---:|---:|")
    for c, n in cluster_counts.most_common():
        pct = 100 * n / len(out)
        md.append(f"| {c} | {n} | {pct:.1f}% |")
    md.append("")

    md.append("## Per-flag prevalence (multiple flags can coexist)")
    md.append("")
    md.append("| Flag | Count | % |")
    md.append("|---|---:|---:|")
    for k in flag_keys:
        n = flag_counts.get(k, 0)
        pct = 100 * n / len(out)
        md.append(f"| `{k}` | {n} | {pct:.1f}% |")
    md.append("")
    if wrong_surface_counts:
        md.append("**Wrong-surface breakdown:**")
        md.append("")
        md.append("| Surface kind | Count |")
        md.append("|---|---:|")
        for k, n in wrong_surface_counts.most_common():
            md.append(f"| `{k}` | {n} |")
        md.append("")

    md.append("## Per-config cluster distribution")
    md.append("")
    all_clusters = sorted(cluster_counts.keys())
    header = "| Config | " + " | ".join(all_clusters) + " | total |"
    sep = "|---|" + "|".join(["---:"] * (len(all_clusters) + 1)) + "|"
    md.append(header)
    md.append(sep)
    for cfg, c in by_config_cluster.items():
        cells = [str(c.get(k, 0)) for k in all_clusters]
        total = sum(c.values())
        md.append(f"| {cfg.replace('_', ' ')} | " + " | ".join(cells) + f" | {total} |")
    md.append("")

    md.append("## Per-config raw flag counts")
    md.append("")
    md.append("| Config | " + " | ".join(flag_keys) + " |")
    md.append("|---|" + "|".join(["---:"] * len(flag_keys)) + "|")
    for cfg, c in by_config_flag.items():
        cells = [str(c.get(k, 0)) for k in flag_keys]
        md.append(f"| {cfg.replace('_', ' ')} | " + " | ".join(cells) + " |")
    md.append("")

    md.append("## Top flag co-occurrences")
    md.append("")
    md.append("| Flag A | Flag B | Count |")
    md.append("|---|---|---:|")
    for (a, b), n in cooc.most_common(15):
        md.append(f"| `{a}` | `{b}` | {n} |")
    md.append("")

    md.append("## Caveats")
    md.append("")
    md.append("- Detectors are heuristic; precision/recall unknown until calibrated.")
    md.append("- `no_finish_call` is sensitive to format quirks — Terminus2 trajectories may")
    md.append("  end without a recorded finish even when the agent intended to terminate.")
    md.append("- `wrong_surface_kind` triggers on combinations of (write target × task keyword).")
    md.append("  False positives are likely on tasks where multiple surfaces are valid.")
    md.append("- `self_verify_same_db` only catches direct sqlite3 patterns; provider-based")
    md.append("  self-verification (insert+query through the same `content://`) is missed.")
    md.append("- `infeasibility_admitted` matches generic phrases; agents may say 'unable to'")
    md.append("  about a sub-task while actually completing the main task. Manual review needed.")

    rep_path = DATA_DIR / "pattern_summary.md"
    rep_path.write_text("\n".join(md))
    print(f"  wrote {rep_path.relative_to(REPO)}")
    print()
    print("Top clusters:")
    for c, n in cluster_counts.most_common(8):
        print(f"  {c}: {n}")


if __name__ == "__main__":
    main()
