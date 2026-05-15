"""Per-agent drilldown: for each failed trajectory, print task description,
heuristic leaf assignment, and a 3-line failure example.

Usage:
    python agent_drilldown.py ClaudeCodeCLI
"""
from __future__ import annotations
import json, re, sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DATA_DIR = REPO / "failure_analysis/androidworld/cli/data"


def extract_first_n_commands(traj_path: Path, n: int = 3) -> list[str]:
    raw = json.loads(traj_path.read_text())
    cmds: list[str] = []
    if raw.get("schema_version", "").startswith("ATIF-"):
        for s in raw.get("steps", []):
            if s.get("source") in ("agent", "assistant", "model"):
                msg = (s.get("message") or "").strip()
                m = re.match(r"^Execute:\s*(.+?)$", msg, re.DOTALL | re.MULTILINE)
                cmds.append((m.group(1).strip() if m else msg)[:200])
    elif "messages" in raw:
        for m in raw.get("messages", []):
            if m.get("role") == "assistant":
                content = m.get("content") or ""
                cb = re.search(r"```bash\s*\n(.+?)\n```", content, re.DOTALL)
                if cb:
                    cmds.append(cb.group(1).strip()[:200])
    return cmds[:n] + cmds[-1:] if len(cmds) > n else cmds


def get_submission(traj_path: Path) -> str | None:
    raw = json.loads(traj_path.read_text())
    if "info" in raw:
        return (raw.get("info") or {}).get("submission")
    return None


def main(agent_class: str):
    rows = [json.loads(l) for l in (DATA_DIR / "rubric_flags.jsonl").read_text().splitlines() if l.strip()]
    pilot = {r["trajectory_id"]: r for r in
             (json.loads(l) for l in (DATA_DIR / "pilot_set.jsonl").read_text().splitlines() if l.strip())}

    rows = [r for r in rows if r["agent_class"] == agent_class]
    print(f"# {agent_class} — {len(rows)} failures, grouped by heuristic primary leaf\n")

    grouped: dict[str, list] = defaultdict(list)
    for r in rows:
        grouped[r["primary_leaf"]].append(r)

    leaf_order = [
        "step_repetition", "context_loss", "weak_verification",
        "disobey_specification", "unaware_of_termination_conditions",
        "reasoning_action_mismatch", "premature_termination",
        "no_or_incorrect_verification", "_GAP_honest_infeasibility_",
        "_unclassified_",
    ]
    seq = 1
    for leaf in leaf_order:
        if leaf not in grouped: continue
        items = sorted(grouped[leaf], key=lambda r: r["task_id"])
        print(f"\n## {leaf}  ({len(items)} trajectories)\n")
        for r in items:
            tid = r["task_id"]
            traj_path = REPO / pilot[r["trajectory_id"]]["traj_path"]
            cmds = extract_first_n_commands(traj_path, 3)
            sub = get_submission(traj_path)
            print(f"### #{seq}  task_id={tid}  step_count={r['step_count']}/{r['max_turns']}")
            print(f"")
            print(f"**Task:** {r['task_name']}")
            print(f"")
            print(f"**Heuristic detail:** `{r['primary_detail']}`")
            print(f"")
            if cmds:
                print(f"**Sample agent commands:**")
                for c in cmds:
                    one = c.replace("\n", " ⏎ ")[:180]
                    print(f"  - `{one}`")
                print()
            if sub:
                print(f"**Submission:** {sub[:300]}")
                print()
            seq += 1


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ClaudeCodeCLI")
