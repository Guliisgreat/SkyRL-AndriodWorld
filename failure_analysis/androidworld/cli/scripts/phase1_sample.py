"""Phase 1 sampler — verify logs (1.1) and emit pilot_set.jsonl (1.2).

Composes the reusable `verify_logs` module. For every failed task in every
surviving config, picks the trajectory-file path that actually has real agent
content (atif vs. native), and writes one row per failure to pilot_set.jsonl.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "failure_analysis/androidworld/cli"))
from verify_logs import (  # noqa: E402
    verify_config, ConfigReport, read_trajectory,
)

RESULTS = REPO / "failure_analysis/androidworld/cli/data/raw"
OUT_DIR = REPO / "failure_analysis/androidworld/cli/data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SELECTED = [
    "ClaudeCodeCLI_claudeopus47_seed30_bash_only",
    "MiniSweAgent_openaigpt53codex_seed30_bash_only",
    "Terminus2_openrouterminimaxminimaxm27_seed30_bash_only",
]


def pick_trajectory_path(config_dir: Path, task_id: int) -> tuple[Path, str] | None:
    """Pick whichever of atif/native has real agent content; prefer atif when both do.

    Returns (path, format) or None if no readable trajectory exists.
    """
    candidates = []
    atif = config_dir / "atif_trajectories" / f"task_{task_id:03d}.json"
    native = config_dir / "trajectories" / f"task_{task_id:03d}.json"
    if atif.exists():
        candidates.append(atif)
    if native.exists():
        candidates.append(native)
    real, fallback = None, None
    for p in candidates:
        v = read_trajectory(p)
        if v.has_real_agent_content:
            real = (p, v.format)
            break
        if fallback is None:
            fallback = (p, v.format)
    return real or fallback


def sample_failures(config_dir: Path, summary: dict, rows: list[dict]) -> tuple[list[dict], dict]:
    """Emit one row per failure; return (rows, stats)."""
    out: list[dict] = []
    stats = {"agent_failures": 0, "no_agent_content": 0, "no_trajectory_file": 0}
    config_tag = config_dir.name
    for r in rows:
        if r.get("reward", 0) != 0:
            continue
        task_id = r["task_id"]
        seed = r.get("seed")
        chosen = pick_trajectory_path(config_dir, task_id)
        if chosen is None:
            stats["no_trajectory_file"] += 1
            continue
        traj_path, traj_format = chosen
        view = read_trajectory(traj_path)
        readable = view.has_real_agent_content
        if not readable:
            stats["no_agent_content"] += 1
        else:
            stats["agent_failures"] += 1
        out.append({
            "trajectory_id": f"{config_tag}__t{task_id:03d}__s{seed}",
            "config": config_tag,
            "agent_class": config_tag.split("_")[0],
            "model": summary.get("model"),
            "task_id": task_id,
            "task_name": r.get("task"),
            "seed": seed,
            "reward": r.get("reward"),
            "step_count": r.get("step_count"),
            "finished": r.get("finished"),
            "max_turns": summary.get("max_turns"),
            "traj_path": str(traj_path.relative_to(REPO)),
            "traj_format": traj_format,
            "traj_real_agent_steps": view.real_agent_step_count,
            "traj_total_steps": view.total_steps,
            "readable": readable,
        })
    return out, stats


def main():
    print("=" * 70)
    print("Phase 1.1 — Verify logs")
    print("=" * 70)
    reports: list[ConfigReport] = []
    for name in SELECTED:
        rep = verify_config(RESULTS / name)
        reports.append(rep)
        print(rep.human_summary())
        print()

    surviving = [r for r in reports if r.passed]
    print(f"Surviving configs: {len(surviving)}/{len(reports)}")

    print()
    print("=" * 70)
    print("Phase 1.2 — Sample failures into pilot_set.jsonl")
    print("=" * 70)
    pilot_rows: list[dict] = []
    excluded_rows: list[dict] = []
    for rep in surviving:
        config_dir = Path(rep.config_dir)
        # Re-load summary + results since ConfigReport doesn't carry rows in detail
        summary = json.loads((config_dir / "summary.json").read_text())
        rows = [
            json.loads(ln) for ln in (config_dir / "results.jsonl").read_text().splitlines() if ln.strip()
        ]
        emitted, stats = sample_failures(config_dir, summary, rows)
        readable = [r for r in emitted if r["readable"]]
        unreadable = [r for r in emitted if not r["readable"]]
        pilot_rows.extend(readable)
        excluded_rows.extend(unreadable)
        print(f"  {rep.config_name}:")
        print(f"     readable failures (kept): {len(readable)}")
        print(f"     unreadable failures (excluded): {len(unreadable)}")

    out_path = OUT_DIR / "pilot_set.jsonl"
    with out_path.open("w") as f:
        for row in pilot_rows:
            f.write(json.dumps(row) + "\n")
    print()
    print(f"Total readable failures written: {len(pilot_rows)}")
    print(f"Output: {out_path.relative_to(REPO)}")

    excluded_path = OUT_DIR / "excluded_set.jsonl"
    with excluded_path.open("w") as f:
        for row in excluded_rows:
            f.write(json.dumps(row) + "\n")
    print(f"Excluded (no agent content): {len(excluded_rows)} → {excluded_path.relative_to(REPO)}")

    # Per-config breakdown
    from collections import Counter
    by_cfg = Counter(r["config"] for r in pilot_rows)
    print()
    print("Per-config readable counts:")
    for cfg, n in by_cfg.most_common():
        print(f"  {cfg}: {n}")

    # Save verification report
    idx_path = OUT_DIR / "sample_index.jsonl"
    with idx_path.open("w") as f:
        for rep in reports:
            f.write(json.dumps(rep.to_dict(), default=str) + "\n")
    print(f"\nVerification report: {idx_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
