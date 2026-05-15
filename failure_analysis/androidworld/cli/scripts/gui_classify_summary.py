"""Aggregate GUI classification outputs into a comparison vs the CLI 11-mode baseline."""
from __future__ import annotations
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
GUI_DIR = REPO / "failure_analysis/androidworld/cli/discovery/gui"

# Prevalence in the CLI-211 baseline
CLI_BASELINE = {
    "wrote_to_wrong_app_data_store": 22.0,
    "raw_sqlite_write_bypassed_app_pipeline": 16.0,
    "terminus2_command_envelope_misuse": 13.0,
    "fabricated_values_after_failed_or_truncated_read": 10.0,
    "guessed_or_inverted_integer_enum_mapping": 8.0,
    "reconnaissance_burnout_no_mutation": 10.0,
    "filesystem_artifact_without_app_ingestion": 7.0,
    "wrote_to_wrong_filesystem_directory": 5.0,
    "byte_level_content_separator_mismatch": 3.0,
    "date_or_timezone_window_off": 4.0,
    "intent_launch_treated_as_persistence": 2.0,
}


def report(jsonl_path: Path) -> None:
    rows = [json.loads(l) for l in jsonl_path.read_text().splitlines() if l.strip()]
    n = len(rows)
    print(f"\n{'=' * 78}")
    print(f"Run: {jsonl_path.name}")
    print(f"Total classified failures: {n}")
    print('=' * 78)

    # Primary distribution
    primary = Counter(r["primary_mode"] for r in rows)
    print(f"\nPrimary mode distribution ({n} failures):")
    print(f"{'Mode':<48} {'GUI':>8} {'CLI-baseline':>14}")
    print("-" * 72)
    all_modes = set(primary) | set(CLI_BASELINE)
    for mode in sorted(all_modes, key=lambda m: -primary.get(m, 0)):
        cnt = primary.get(mode, 0)
        pct = 100 * cnt / n if n else 0
        baseline = CLI_BASELINE.get(mode, None)
        baseline_str = f"{baseline:>5.1f}%" if baseline is not None else "    n/a"
        gui_str = f"{cnt:>2} ({pct:>4.1f}%)"
        marker = "★" if mode == "doesnt_fit_any_mode" else " "
        print(f"{marker} {mode:<46} {gui_str:>8} {baseline_str:>14}")

    # GUI-specific patterns (when primary == doesnt_fit_any_mode)
    gui_specific = [r for r in rows if r.get("primary_mode") == "doesnt_fit_any_mode"]
    if gui_specific:
        print(f"\nGUI-specific patterns ({len(gui_specific)}):")
        # Try to extract a snake_case label from rationale; otherwise just show first sentence
        for r in gui_specific:
            print(f"  - task_{r['task_id']:03d}: {r['rationale'][:150]}")

    # Confidence breakdown
    conf = Counter(r["confidence"] for r in rows)
    print(f"\nConfidence: {dict(conf)}")

    # Secondary modes
    sec = Counter()
    for r in rows:
        for s in r.get("secondary_modes", []) or []:
            sec[s] += 1
    if sec:
        print(f"\nSecondary modes (any-position):")
        for m, c in sec.most_common():
            print(f"  {c:>3} {m}")


def main():
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        paths = sorted(GUI_DIR.glob("*.jsonl"))
    for p in paths:
        if not p.is_absolute():
            p = REPO / p
        report(p)


if __name__ == "__main__":
    main()
