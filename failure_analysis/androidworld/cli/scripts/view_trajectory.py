"""Compact digest of a trajectory file (ATIF or MiniSWE native) for blind reading."""
from __future__ import annotations
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]


def fmt(s: str | None, w: int) -> str:
    if not s: return "(empty)"
    s = s.replace("\r", "")
    if len(s) <= w: return s
    return s[:w] + f"\n[... truncated, total {len(s)} chars ...]"


def view_atif(traj: dict, path: Path) -> str:
    out = []
    out.append(f"=== {path.name} ATIF / {traj.get('agent', {}).get('name')} ===")
    out.append(f"model: {traj.get('agent', {}).get('model_name')}")
    steps = traj.get("steps", [])
    out.append(f"steps: {len(steps)}")
    out.append("")
    for i, s in enumerate(steps):
        src = s.get("source", "?")
        msg = s.get("message", "") or ""
        if src == "system" and i == 0:
            out.append(f"[step {i}] SYSTEM: ({len(msg)} chars elided)")
            continue
        if src == "user" and i <= 2:
            out.append(f"[step {i}] USER TASK: {fmt(msg, 1200)}")
            continue
        budget = 600 if src in ("agent", "assistant", "model") else 400
        out.append(f"[step {i}] {src.upper()}: {fmt(msg, budget)}")
        for tc in (s.get("tool_calls") or []):
            name = tc.get("name") or tc.get("function", {}).get("name")
            args = tc.get("arguments") or tc.get("function", {}).get("arguments")
            out.append(f"   tool_call {name}: {fmt(json.dumps(args) if not isinstance(args,str) else args, 400)}")
        obs = s.get("observation")
        if obs:
            obs_text = obs if isinstance(obs, str) else json.dumps(obs)
            out.append(f"   OBS: {fmt(obs_text, 800)}")
    return "\n".join(out)


def view_minisweagent(traj: dict, path: Path) -> str:
    out = []
    info = traj.get("info", {})
    cfg = info.get("config", {})
    out.append(f"=== {path.name} MINISWE / {cfg.get('model', {}).get('model_name')} ===")
    out.append(f"exit_status: {info.get('exit_status')}")
    out.append(f"submission: {fmt(info.get('submission'), 200)}")
    msgs = traj.get("messages", [])
    out.append(f"messages: {len(msgs)}")
    out.append("")
    for i, m in enumerate(msgs):
        role = m.get("role", "?")
        content = m.get("content", "") or ""
        if role == "system" and i == 0:
            out.append(f"[msg {i}] SYSTEM: ({len(content)} chars elided)")
            continue
        if role == "user" and i == 1:
            out.append(f"[msg {i}] USER TASK: {fmt(content, 1200)}")
            continue
        budget = 700 if role == "assistant" else 500
        # User messages after the first are observations/tool results — they're long
        if role == "user":
            out.append(f"[msg {i}] OBS: {fmt(content, 500)}")
        else:
            out.append(f"[msg {i}] {role.upper()}: {fmt(content, budget)}")
    return "\n".join(out)


def view_path(p: Path) -> str:
    raw = json.loads(p.read_text())
    if raw.get("schema_version", "").startswith("ATIF-"):
        return view_atif(raw, p)
    if isinstance(raw.get("messages"), list) and "config" in raw.get("info", {}):
        return view_minisweagent(raw, p)
    return f"=== {p.name} UNKNOWN FORMAT ===\nkeys: {list(raw.keys())}"


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.is_absolute():
            p = REPO / arg
        print(view_path(p))
        print()
