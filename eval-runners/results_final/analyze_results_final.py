#!/usr/bin/env python3
"""Build a comparison table over all runs in eval-runners/results_final.

Per-row columns:
  agent, model, seed, mode, avg_in_tok, avg_out_tok, total_cost,
  success, success_rate, gui_success_rate, non_gui_success_rate,
  avg_step, adb%, finish%, tool%, error%

Action accounting (sums to 1 per row):
  adb     - commands[].action_type == 'adb'
  tool    - commands[].action_type in {find-files, sql, read-file, write-file}
  finish  - explicit finish call. For Terminus2: counted in agent_commands_log.
            For ClaudeCodeCLI (no log): 1 per task whose .finished == True.
  error   - LLM turn that produced no executable command (parse failure, empty
            commands, etc.). Only computable for Terminus2 (has agent_commands_log
            with one entry per chained sub-command, so distinct turns can be
            recovered as max(0, num_turns - n_log + finish_in_log)). 0 for
            ClaudeCodeCLI which uses structured tool-use.

Run from the eval-runners directory.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# GUI-only task IDs (from /shared/ken/SkyRL-AndriodWorld/eval.py)
GUI_TASK_IDS = {0, 1, 8, 20, 28, 29, 30, 37, 40, 47, 55, 75, 76, 78, 80}

TOOL_ACTION_TYPES = {"find-files", "sql", "read-file", "write-file"}

# How to display backend models (raw model string -> display)
MODEL_DISPLAY = {
    "claude-opus-4-7": "claude-opus-4-7",
    "anthropic/claude-sonnet-4-6": "claude-sonnet-4-6",
    "openai/gpt-5.3-codex": "gpt-5.3-codex",
    "openrouter/minimax/minimax-m2.7": "minimax-m2.7",
}

AGENT_DISPLAY = {
    "ClaudeCodeCLI": "claude code cli",
    "Terminus2": "terminus 2",
    "MiniSweAgent": "mini swe",
}

DIR_RE = re.compile(r"^(?P<agent>[A-Za-z0-9]+)_(?P<model>.+?)_seed(?P<seed>\d+)_(?P<mode>bash_only|bash_tool)$")


def parse_dirname(name: str) -> dict | None:
    m = DIR_RE.match(name)
    if not m:
        return None
    return {
        "agent_class": m["agent"],
        "model_short": m["model"],
        "seed": int(m["seed"]),
        "mode": m["mode"],
    }


FINISH_RE = re.compile(r"android_env\.py\s+finish\b")


def categorize_log_command(cmd_str: str) -> str:
    if FINISH_RE.search(cmd_str):
        return "finish"
    if re.search(r"android_env\.py\s+adb\b", cmd_str):
        return "adb"
    if re.search(r"android_env\.py\s+sql\b", cmd_str):
        return "sql"
    if re.search(r"android_env\.py\s+find-files\b", cmd_str):
        return "find-files"
    if re.search(r"android_env\.py\s+read-file\b", cmd_str):
        return "read-file"
    if re.search(r"android_env\.py\s+write-file\b", cmd_str):
        return "write-file"
    return "other"


def analyze_run(run_dir: Path) -> dict:
    summary_path = run_dir / "summary.json"
    results_path = run_dir / "results.jsonl"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}

    total_tasks = 0
    success_ids = []
    step_counts = []
    adb_actions = 0
    tool_actions = 0
    finish_actions = 0
    error_actions = 0
    has_log = False

    with results_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            total_tasks += 1
            tid = e["task_id"]
            if e.get("reward") == 1:
                success_ids.append(tid)
            step_counts.append(e.get("step_count", 0))

            cmds = e.get("commands") or []
            n_adb_cmd = sum(1 for c in cmds if c.get("action_type") == "adb")
            n_tool_cmd = sum(1 for c in cmds if c.get("action_type") in TOOL_ACTION_TYPES)
            adb_actions += n_adb_cmd
            tool_actions += n_tool_cmd

            log = e.get("agent_commands_log")
            if log:
                has_log = True
                n_finish_log = sum(1 for x in log if FINISH_RE.search(x.get("command", "")))
                finish_actions += n_finish_log
                # Estimate parse-error / empty-response turns:
                #   each non-finish log entry corresponds to one chained sub-command;
                #   each finish log entry uses one turn; remaining turns produced no
                #   executable output (parse failure or empty commands).
                n_log = len(log)
                num_turns = e.get("num_turns", 0)
                # We can only bound it: chained commands collapse multiple log
                # entries into one turn, so we use turns - finish_calls -
                # turns-with-commands. We don't know turns-with-commands exactly,
                # so use a lower bound: at least one turn is consumed per
                # "command group". Conservative estimate: any extra turns beyond
                # those that produced a command or a finish are errors.
                turns_with_cmd = max(0, num_turns - n_finish_log)
                # If chaining happened, n_log_non_finish > turns_with_cmd, so
                # subtract: errors = turns - turns_with_cmd_estimate - finish
                # Use: errors = max(0, num_turns - non_zero_turn_estimate - n_finish_log)
                # where non_zero_turn_estimate ≈ min(num_turns - n_finish_log, n_log - n_finish_log)
                non_finish_log = n_log - n_finish_log
                n_cmd_turns_est = min(num_turns - n_finish_log, non_finish_log)
                err = max(0, num_turns - n_cmd_turns_est - n_finish_log)
                error_actions += err
            else:
                # ClaudeCodeCLI: no log. Use finished as proxy for finish action.
                if e.get("finished"):
                    finish_actions += 1

    n_gui_attempted = sum(1 for tid in range(total_tasks) if tid in GUI_TASK_IDS)
    # Use task_ids actually present
    success_set = set(success_ids)
    gui_success = sum(1 for tid in success_set if tid in GUI_TASK_IDS)
    non_gui_success = sum(1 for tid in success_set if tid not in GUI_TASK_IDS)
    # Determine which gui/non-gui task ids are present in results
    present_ids = set()
    with results_path.open() as f:
        for line in f:
            if line.strip():
                present_ids.add(json.loads(line)["task_id"])
    gui_present = present_ids & GUI_TASK_IDS
    non_gui_present = present_ids - GUI_TASK_IDS

    avg_step = sum(step_counts) / len(step_counts) if step_counts else 0
    total_actions = adb_actions + tool_actions + finish_actions + error_actions

    def pct(n):
        return (n / total_actions) if total_actions else 0.0

    return {
        "total_tasks": total_tasks,
        "success": summary.get("success", len(success_ids)),
        "success_rate": summary.get("success_rate", len(success_ids) / total_tasks if total_tasks else 0),
        "gui_success": gui_success,
        "gui_total": len(gui_present),
        "gui_success_rate": gui_success / len(gui_present) if gui_present else 0,
        "non_gui_success": non_gui_success,
        "non_gui_total": len(non_gui_present),
        "non_gui_success_rate": non_gui_success / len(non_gui_present) if non_gui_present else 0,
        "avg_step": avg_step,
        "avg_in_tok": summary.get("avg_input_tokens", 0),
        "avg_out_tok": summary.get("avg_output_tokens", 0),
        "total_cost": summary.get("total_cost_usd", 0),
        "model_raw": summary.get("model", ""),
        "adb_pct": pct(adb_actions),
        "tool_pct": pct(tool_actions),
        "finish_pct": pct(finish_actions),
        "error_pct": pct(error_actions),
        "_counts": {
            "adb": adb_actions,
            "tool": tool_actions,
            "finish": finish_actions,
            "error": error_actions,
            "total": total_actions,
        },
    }


def collect(results_root: Path) -> list[dict]:
    rows = []
    for child in sorted(results_root.iterdir()):
        if not child.is_dir():
            continue
        meta = parse_dirname(child.name)
        if meta is None:
            continue
        if not (child / "results.jsonl").exists():
            continue
        analysis = analyze_run(child)
        analysis.update(meta)
        analysis["dir"] = child.name
        rows.append(analysis)
    return rows


def sort_key(row: dict) -> tuple:
    agent_order = {"ClaudeCodeCLI": 0, "Terminus2": 1, "MiniSweAgent": 2}
    mode_order = {"bash_only": 0, "bash_tool": 1}
    return (
        agent_order.get(row["agent_class"], 99),
        row["model_short"],
        row["seed"],
        mode_order.get(row["mode"], 99),
    )


def fmt_pct(x: float) -> str:
    return f"{x*100:.1f}%"


def render_table(rows: list[dict]) -> str:
    headers = [
        "agent", "model", "seed", "mode",
        "avg_in_tok", "avg_out_tok", "total_cost",
        "success", "success_rate",
        "gui_succ_rate", "non_gui_succ_rate",
        "avg_step",
        "adb%", "finish%", "tool%", "error%",
    ]

    def row_to_cells(row: dict) -> list[str]:
        agent = AGENT_DISPLAY.get(row["agent_class"], row["agent_class"])
        model = MODEL_DISPLAY.get(row["model_raw"], row["model_short"])
        return [
            agent,
            model,
            str(row["seed"]),
            row["mode"],
            f"{row['avg_in_tok']:.0f}",
            f"{row['avg_out_tok']:.0f}",
            f"${row['total_cost']:.2f}",
            f"{row['success']}/{row['total_tasks']}",
            fmt_pct(row["success_rate"]),
            fmt_pct(row["gui_success_rate"]),
            fmt_pct(row["non_gui_success_rate"]),
            f"{row['avg_step']:.1f}",
            fmt_pct(row["adb_pct"]),
            fmt_pct(row["finish_pct"]),
            fmt_pct(row["tool_pct"]),
            fmt_pct(row["error_pct"]),
        ]

    cells = [row_to_cells(r) for r in rows]
    widths = [max(len(h), max((len(c[i]) for c in cells), default=0)) for i, h in enumerate(headers)]

    def fmt_row(parts: list[str]) -> str:
        return "| " + " | ".join(p.ljust(w) for p, w in zip(parts, widths)) + " |"

    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    out = [fmt_row(headers), sep]
    out.extend(fmt_row(c) for c in cells)
    return "\n".join(out)


def render_csv(rows: list[dict]) -> str:
    import csv, io
    headers = [
        "agent", "model", "seed", "mode",
        "avg_input_tokens", "avg_output_tokens", "total_cost_usd",
        "success", "total", "success_rate",
        "gui_success", "gui_total", "gui_success_rate",
        "non_gui_success", "non_gui_total", "non_gui_success_rate",
        "avg_step",
        "adb_pct", "finish_pct", "tool_pct", "error_pct",
        "adb_count", "tool_count", "finish_count", "error_count", "total_actions",
    ]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        agent = AGENT_DISPLAY.get(r["agent_class"], r["agent_class"])
        model = MODEL_DISPLAY.get(r["model_raw"], r["model_short"])
        c = r["_counts"]
        w.writerow([
            agent, model, r["seed"], r["mode"],
            f"{r['avg_in_tok']:.0f}", f"{r['avg_out_tok']:.0f}", f"{r['total_cost']:.4f}",
            r["success"], r["total_tasks"], f"{r['success_rate']:.4f}",
            r["gui_success"], r["gui_total"], f"{r['gui_success_rate']:.4f}",
            r["non_gui_success"], r["non_gui_total"], f"{r['non_gui_success_rate']:.4f}",
            f"{r['avg_step']:.2f}",
            f"{r['adb_pct']:.4f}", f"{r['finish_pct']:.4f}",
            f"{r['tool_pct']:.4f}", f"{r['error_pct']:.4f}",
            c["adb"], c["tool"], c["finish"], c["error"], c["total"],
        ])
    return buf.getvalue()


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--results-dir",
        default=str(Path(__file__).parent),
        help="Directory containing run subfolders",
    )
    p.add_argument("--csv", help="Write CSV output to this path")
    p.add_argument("--format", choices=["md", "csv", "both"], default="md")
    args = p.parse_args()

    rows = collect(Path(args.results_dir))
    rows.sort(key=sort_key)

    if args.format in ("md", "both"):
        print(render_table(rows))
    if args.format in ("csv", "both"):
        csv_text = render_csv(rows)
        if args.csv:
            Path(args.csv).write_text(csv_text)
            print(f"\nCSV written to {args.csv}", flush=True)
        else:
            print()
            print(csv_text, end="")


if __name__ == "__main__":
    main()
