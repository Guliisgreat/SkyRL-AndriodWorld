"""Tag pilot_set.jsonl + multilabel_flags.jsonl rows with `cli_solvable` flag,
sourced from the AndroidWorld 2026 ground-truth reference v2.

GUI-only tasks (15 of 116) are infeasible by design for CLI agents. Failures
on those tasks should not be treated as agent-reasoning failures.
"""
from __future__ import annotations
import json, re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
REF_DOC = REPO / "docs/final/AndroidWorld2026/androidworld_ground_truth_reference_v2.md"
DATA_DIR = REPO / "failure_analysis/androidworld/cli/data"


def parse_gui_only_ids() -> set[int]:
    text = REF_DOC.read_text()
    lines = text.splitlines()
    gui = set()
    current_id = None
    for ln in lines:
        m = re.match(r"###\s+Task\s+0?(\d+):\s*(\S+)", ln)
        if m:
            current_id = int(m.group(1))
            continue
        if current_id is not None and re.match(r"\*\*Status:\*\*\s*GUI-only", ln):
            gui.add(current_id)
            current_id = None
        elif current_id is not None and ln.startswith("**Status:**"):
            current_id = None
    return gui


def tag_file(path: Path, gui_ids: set[int]) -> tuple[int, int]:
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    cli_count, gui_count = 0, 0
    out_rows = []
    for r in rows:
        cli = r["task_id"] not in gui_ids
        r["cli_solvable"] = cli
        out_rows.append(r)
        if cli:
            cli_count += 1
        else:
            gui_count += 1
    path.write_text("\n".join(json.dumps(r) for r in out_rows) + "\n")
    return cli_count, gui_count


def main():
    gui = parse_gui_only_ids()
    print(f"GUI-only task IDs (from ref v2): {sorted(gui)}")
    print()
    for fname in ("pilot_set.jsonl", "multilabel_flags.jsonl", "rubric_flags.jsonl",
                  "pattern_flags.jsonl"):
        p = DATA_DIR / fname
        if p.exists():
            cli, guic = tag_file(p, gui)
            print(f"{fname}: {cli} CLI-solvable, {guic} GUI-only")


if __name__ == "__main__":
    main()
