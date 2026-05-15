"""Phase 1.1 — verify experiment-result logs before failure-mode analysis.

Reusable component. Encodes the verification rules every results dir must pass
before its trajectories can be sampled, hand-labeled, or LLM-judged.

USAGE
-----
Library::

    from verify_logs import verify_config
    report = verify_config("path/to/RunFolder/")
    if not report.passed:
        print("DROP:", report.summary())

CLI::

    python -m verify_logs path/to/Run1 path/to/Run2 [...]
    python -m verify_logs --json path/to/Run1                  # JSONL output
    python -m verify_logs --min-tasks 50 --strict path/to/Run

OUTPUT
------
For each config dir, a `ConfigReport` with:
  - filesystem checks (summary.json, results.jsonl, trajectory dir present)
  - schema checks (row count matches summary.total)
  - run-size checks (not a smoke run)
  - per-trajectory audit (how many trajectories have real agent content vs. stubs)
  - overall pass/fail decision

DESIGN
------
Each rule is a self-contained class (`Rule`). To add a new check, define a new
Rule subclass and add it to `DEFAULT_RULES`. To support a new trajectory file
format, implement a `TrajectoryReader` subclass and register it.

This module is intentionally agnostic to the specific Android task domain —
it should work on any agent-trajectory results dir that follows the
`{summary.json, results.jsonl, atif_trajectories/}` or
`{summary.json, results.jsonl, trajectories/}` layout.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional

# --------------------------------------------------------------------------
# Trajectory readers
# --------------------------------------------------------------------------

# Stub markers seen in real-world ATIF exports. If an agent's "message" content
# matches one of these exactly, treat it as if no real content was captured.
STUB_MARKERS = frozenset({
    "(no output captured)",
    "",
    None,
})

# Minimum length of an agent message before we call it "real" content. Picked
# at 30 because shortest legitimate agent step we've seen is ~40 chars
# ("Execute: adb shell ls").
MIN_AGENT_MESSAGE_LEN = 30


@dataclass
class TrajectoryView:
    """Format-agnostic projection of a trajectory file."""
    path: str
    format: str  # "atif", "minisweagent", "unknown"
    total_steps: int
    agent_step_count: int
    real_agent_step_count: int  # excluding stubs
    first_agent_message_preview: str = ""

    @property
    def has_real_agent_content(self) -> bool:
        return self.real_agent_step_count > 0


class TrajectoryReader:
    """Subclass to add support for a new trajectory file format."""

    name: str = "abstract"

    @classmethod
    def detects(cls, raw: dict) -> bool:  # pragma: no cover
        raise NotImplementedError

    @classmethod
    def read(cls, raw: dict, path: Path) -> TrajectoryView:  # pragma: no cover
        raise NotImplementedError


class ATIFReader(TrajectoryReader):
    """Agent Trajectory Interchange Format (v1.x). schema_version starts with 'ATIF-'."""
    name = "atif"

    @classmethod
    def detects(cls, raw: dict) -> bool:
        v = raw.get("schema_version", "")
        return isinstance(v, str) and v.startswith("ATIF-")

    @classmethod
    def read(cls, raw: dict, path: Path) -> TrajectoryView:
        steps = raw.get("steps", []) or []
        agent_sources = {"agent", "assistant", "model"}
        agent_steps = [s for s in steps if s.get("source") in agent_sources]
        real_agent_steps = [
            s for s in agent_steps
            if (s.get("message") or "") not in STUB_MARKERS
            and len(s.get("message") or "") >= MIN_AGENT_MESSAGE_LEN
        ]
        first_msg = ""
        if real_agent_steps:
            first_msg = (real_agent_steps[0].get("message") or "")[:120]
        return TrajectoryView(
            path=str(path),
            format=cls.name,
            total_steps=len(steps),
            agent_step_count=len(agent_steps),
            real_agent_step_count=len(real_agent_steps),
            first_agent_message_preview=first_msg,
        )


class MiniSweAgentNativeReader(TrajectoryReader):
    """MiniSWE native trajectory format (openai-style messages array)."""
    name = "minisweagent"

    @classmethod
    def detects(cls, raw: dict) -> bool:
        return (
            isinstance(raw.get("messages"), list)
            and isinstance(raw.get("info"), dict)
            and "config" in raw.get("info", {})
        )

    @classmethod
    def read(cls, raw: dict, path: Path) -> TrajectoryView:
        msgs = raw.get("messages", []) or []
        agent_msgs = [m for m in msgs if m.get("role") == "assistant"]
        real_agent_msgs = [
            m for m in agent_msgs
            if (m.get("content") or "") not in STUB_MARKERS
            and len(m.get("content") or "") >= MIN_AGENT_MESSAGE_LEN
        ]
        first_msg = ""
        if real_agent_msgs:
            first_msg = (real_agent_msgs[0].get("content") or "")[:120]
        return TrajectoryView(
            path=str(path),
            format=cls.name,
            total_steps=len(msgs),
            agent_step_count=len(agent_msgs),
            real_agent_step_count=len(real_agent_msgs),
            first_agent_message_preview=first_msg,
        )


REGISTERED_READERS: list[type[TrajectoryReader]] = [
    ATIFReader,
    MiniSweAgentNativeReader,
]


def read_trajectory(path: Path) -> TrajectoryView:
    """Auto-detect format and produce a normalized TrajectoryView."""
    raw = json.loads(path.read_text())
    for reader in REGISTERED_READERS:
        if reader.detects(raw):
            return reader.read(raw, path)
    return TrajectoryView(
        path=str(path), format="unknown",
        total_steps=0, agent_step_count=0, real_agent_step_count=0,
    )


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


@dataclass
class RuleResult:
    name: str
    ok: bool
    reason: str = ""
    severity: str = "fatal"  # "fatal" | "warning" | "info"
    detail: dict = field(default_factory=dict)


class Rule:
    """Each Rule encapsulates one verification check."""

    name: str = "abstract"
    severity: str = "fatal"

    def check(self, config_dir: Path, ctx: dict) -> RuleResult:  # pragma: no cover
        raise NotImplementedError


class HasSummaryJson(Rule):
    name = "has_summary_json"

    def check(self, config_dir, ctx):
        p = config_dir / "summary.json"
        if not p.exists():
            return RuleResult(self.name, False, "summary.json missing")
        try:
            ctx["summary"] = json.loads(p.read_text())
        except Exception as e:
            return RuleResult(self.name, False, f"summary.json parse error: {e}")
        return RuleResult(self.name, True, "")


class HasResultsJsonl(Rule):
    name = "has_results_jsonl"

    def check(self, config_dir, ctx):
        p = config_dir / "results.jsonl"
        if not p.exists():
            return RuleResult(self.name, False, "results.jsonl missing")
        try:
            rows = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
        except Exception as e:
            return RuleResult(self.name, False, f"results.jsonl parse error: {e}")
        ctx["rows"] = rows
        return RuleResult(self.name, True, f"{len(rows)} rows")


class HasTrajectoryDir(Rule):
    """At least one of `atif_trajectories/` or `trajectories/` must exist."""
    name = "has_trajectory_dir"

    def check(self, config_dir, ctx):
        atif = config_dir / "atif_trajectories"
        native = config_dir / "trajectories"
        ctx["atif_dir"] = atif if atif.is_dir() else None
        ctx["native_dir"] = native if native.is_dir() else None
        if not atif.is_dir() and not native.is_dir():
            return RuleResult(self.name, False, "neither atif_trajectories/ nor trajectories/ found")
        present = []
        if atif.is_dir(): present.append("atif_trajectories/")
        if native.is_dir(): present.append("trajectories/")
        return RuleResult(self.name, True, ", ".join(present))


class SummaryRowCountMatches(Rule):
    """summary.total == len(results.jsonl). Mismatch suggests a corrupt/incomplete run."""
    name = "summary_matches_results"
    severity = "warning"

    def check(self, config_dir, ctx):
        summary = ctx.get("summary") or {}
        rows = ctx.get("rows") or []
        total = summary.get("total")
        if total is None:
            return RuleResult(self.name, False, "summary.total is null/missing", severity="warning")
        if total != len(rows):
            return RuleResult(
                self.name, False,
                f"summary.total={total} but results.jsonl has {len(rows)} rows",
                severity="warning",
            )
        return RuleResult(self.name, True, f"{total} == {len(rows)}")


class NontrivialRunSize(Rule):
    """Drop smoke runs (single-task or near-empty)."""
    name = "nontrivial_run_size"

    def __init__(self, min_tasks: int = 20):
        self.min_tasks = min_tasks

    def check(self, config_dir, ctx):
        rows = ctx.get("rows") or []
        n = len(rows)
        if n < self.min_tasks:
            return RuleResult(
                self.name, False,
                f"only {n} tasks (< min_tasks={self.min_tasks}); likely smoke run",
                detail={"task_count": n, "min_tasks": self.min_tasks},
            )
        return RuleResult(self.name, True, f"{n} tasks")


class TrajectoryFilesPresent(Rule):
    """For every failed task in results.jsonl, at least one trajectory file exists."""
    name = "trajectory_files_present"

    def check(self, config_dir, ctx):
        rows = ctx.get("rows") or []
        atif = ctx.get("atif_dir")
        native = ctx.get("native_dir")
        failures = [r for r in rows if r.get("reward", 0) == 0]
        missing: list[int] = []
        for r in failures:
            tid = r.get("task_id")
            if tid is None:
                continue
            f1 = atif / f"task_{tid:03d}.json" if atif else None
            f2 = native / f"task_{tid:03d}.json" if native else None
            has = (f1 and f1.exists()) or (f2 and f2.exists())
            if not has:
                missing.append(tid)
        if missing:
            return RuleResult(
                self.name, False,
                f"{len(missing)} of {len(failures)} failed tasks have no trajectory file",
                detail={"missing_task_ids": missing[:10]},
            )
        return RuleResult(self.name, True, f"all {len(failures)} failure trajectories present")


class TrajectoryAuditRule(Rule):
    """The critical content check: are agent steps real, or stubs/placeholders?

    Reads every failure trajectory through the format-agnostic reader and
    counts how many have real agent content. Fails the config if the
    *atif_trajectories/* fraction with real content falls below threshold,
    UNLESS a parallel `trajectories/` (native) directory provides the data.
    """
    name = "trajectory_audit"

    def __init__(self, min_real_fraction: float = 0.5):
        self.min_real_fraction = min_real_fraction

    def check(self, config_dir, ctx):
        rows = ctx.get("rows") or []
        atif = ctx.get("atif_dir")
        native = ctx.get("native_dir")
        failures = [r for r in rows if r.get("reward", 0) == 0]
        audit = {
            "format_counts": {},
            "real_agent_count": 0,
            "stub_atif_count": 0,
            "zero_step_count": 0,
            "total_failures": len(failures),
        }
        per_trajectory: list[dict] = []
        for r in failures:
            tid = r.get("task_id")
            if tid is None:
                continue
            # Prefer atif (canonical), fall back to native if atif is stubbed
            atif_path = atif / f"task_{tid:03d}.json" if atif else None
            native_path = native / f"task_{tid:03d}.json" if native else None

            views: dict[str, TrajectoryView] = {}
            if atif_path and atif_path.exists():
                views["atif"] = read_trajectory(atif_path)
            if native_path and native_path.exists():
                views["native"] = read_trajectory(native_path)

            chosen = None
            chosen_source = None
            for src in ("atif", "native"):
                v = views.get(src)
                if v and v.has_real_agent_content:
                    chosen, chosen_source = v, src
                    break
            if chosen is None:
                # No source has real content; pick whatever we have for diagnostics
                for src in ("atif", "native"):
                    if src in views:
                        chosen, chosen_source = views[src], src
                        break

            if chosen is None:
                continue  # already counted by trajectory_files_present
            audit["format_counts"][chosen.format] = audit["format_counts"].get(chosen.format, 0) + 1
            per_trajectory.append({
                "task_id": tid,
                "chosen_source": chosen_source,
                "format": chosen.format,
                "total_steps": chosen.total_steps,
                "real_agent_step_count": chosen.real_agent_step_count,
            })
            if chosen.has_real_agent_content:
                audit["real_agent_count"] += 1
            elif chosen.total_steps <= 2:
                audit["zero_step_count"] += 1
            else:
                audit["stub_atif_count"] += 1

        ctx["trajectory_audit"] = audit
        ctx["per_trajectory"] = per_trajectory

        if audit["total_failures"] == 0:
            return RuleResult(
                self.name, True,
                "no failures to audit",
                detail=audit,
            )
        frac = audit["real_agent_count"] / audit["total_failures"]
        if frac < self.min_real_fraction:
            return RuleResult(
                self.name, False,
                f"only {audit['real_agent_count']}/{audit['total_failures']} "
                f"failures ({frac:.0%}) have real agent content "
                f"(< min={self.min_real_fraction:.0%})",
                detail=audit,
            )
        return RuleResult(
            self.name, True,
            f"{audit['real_agent_count']}/{audit['total_failures']} "
            f"failures ({frac:.0%}) have real agent content",
            detail=audit,
        )


DEFAULT_RULES: list[Rule] = [
    HasSummaryJson(),
    HasResultsJsonl(),
    HasTrajectoryDir(),
    SummaryRowCountMatches(),
    NontrivialRunSize(min_tasks=20),
    TrajectoryFilesPresent(),
    TrajectoryAuditRule(min_real_fraction=0.5),
]


# --------------------------------------------------------------------------
# Verifier
# --------------------------------------------------------------------------


@dataclass
class ConfigReport:
    config_dir: str
    config_name: str
    passed: bool
    rule_results: list[RuleResult]
    summary: Optional[dict] = None
    row_count: int = 0
    failure_count: int = 0
    trajectory_audit: Optional[dict] = None
    per_trajectory: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def human_summary(self) -> str:
        flag = "OK" if self.passed else "DROP"
        lines = [f"[{flag}] {self.config_name}"]
        if self.summary:
            lines.append(
                f"      model={self.summary.get('model')!r} "
                f"total={self.summary.get('total')} "
                f"success={self.summary.get('success')} "
                f"max_turns={self.summary.get('max_turns')}"
            )
        for r in self.rule_results:
            mark = "✓" if r.ok else "✗"
            lines.append(f"      {mark} {r.name}: {r.reason}")
        if self.trajectory_audit:
            ta = self.trajectory_audit
            lines.append(
                f"      audit: real={ta['real_agent_count']}/{ta['total_failures']}, "
                f"stub_atif={ta['stub_atif_count']}, zero_step={ta['zero_step_count']}, "
                f"formats={ta['format_counts']}"
            )
        return "\n".join(lines)


def verify_config(
    config_dir: Path | str,
    *,
    rules: Optional[list[Rule]] = None,
    strict: bool = True,
) -> ConfigReport:
    """Run all rules against a single config directory.

    Args:
        config_dir: path to one experiment results dir.
        rules: rules to run. Defaults to DEFAULT_RULES.
        strict: if True, any fatal-severity rule failure marks config as not passed.
                If False, only "fatal" failures count; warnings tolerated.

    Returns:
        ConfigReport with per-rule outcomes and overall pass/fail.
    """
    config_dir = Path(config_dir)
    if rules is None:
        rules = DEFAULT_RULES

    ctx: dict = {}
    results: list[RuleResult] = []
    for rule in rules:
        try:
            res = rule.check(config_dir, ctx)
        except Exception as e:
            res = RuleResult(rule.name, False, f"rule raised: {type(e).__name__}: {e}")
        results.append(res)

    # Decide pass/fail
    passed = True
    for r in results:
        if not r.ok:
            if r.severity == "fatal":
                passed = False
            elif strict and r.severity == "warning":
                passed = False

    summary = ctx.get("summary")
    rows = ctx.get("rows") or []
    return ConfigReport(
        config_dir=str(config_dir),
        config_name=config_dir.name,
        passed=passed,
        rule_results=results,
        summary=summary,
        row_count=len(rows),
        failure_count=sum(1 for r in rows if r.get("reward", 0) == 0),
        trajectory_audit=ctx.get("trajectory_audit"),
        per_trajectory=ctx.get("per_trajectory") or [],
    )


def verify_runs(
    config_dirs: Iterable[Path | str],
    *,
    rules: Optional[list[Rule]] = None,
    strict: bool = True,
) -> list[ConfigReport]:
    return [verify_config(d, rules=rules, strict=strict) for d in config_dirs]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Verify experiment-result logs (Phase 1.1).")
    p.add_argument("paths", nargs="+", help="One or more results directories to verify.")
    p.add_argument("--json", action="store_true", help="Emit JSONL reports instead of human-readable.")
    p.add_argument("--strict", action="store_true", help="Fail on warning-severity rules too.")
    p.add_argument("--min-tasks", type=int, default=20, help="Minimum tasks per run (default: 20).")
    p.add_argument("--min-real-fraction", type=float, default=0.5,
                   help="Minimum fraction of failures that must have real agent content (default: 0.5).")
    args = p.parse_args(argv)

    rules = [
        HasSummaryJson(),
        HasResultsJsonl(),
        HasTrajectoryDir(),
        SummaryRowCountMatches(),
        NontrivialRunSize(min_tasks=args.min_tasks),
        TrajectoryFilesPresent(),
        TrajectoryAuditRule(min_real_fraction=args.min_real_fraction),
    ]

    reports = verify_runs(args.paths, rules=rules, strict=args.strict)
    if args.json:
        for r in reports:
            print(json.dumps(r.to_dict(), default=str))
    else:
        print("=" * 70)
        print(f"Phase 1.1 Verification — {len(reports)} config(s)")
        print("=" * 70)
        for r in reports:
            print(r.human_summary())
            print()
        passed = sum(1 for r in reports if r.passed)
        print(f"Surviving configs: {passed}/{len(reports)}")
    return 0 if all(r.passed for r in reports) else 1


if __name__ == "__main__":
    sys.exit(_cli())
