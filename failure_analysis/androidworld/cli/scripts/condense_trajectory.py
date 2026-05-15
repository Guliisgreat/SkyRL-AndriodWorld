"""Print a condensed one-line-per-step view of a trajectory.

Usage:
    python condense_trajectory.py <traj_path>
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]


def truncate(s: str, n: int) -> str:
    s = s.replace("\n", " ⏎ ")
    return s if len(s) <= n else s[:n] + "…"


def view(p: Path) -> str:
    raw = json.loads(p.read_text())
    out = []
    if raw.get("schema_version", "").startswith("ATIF-"):
        for i, s in enumerate(raw.get("steps", [])):
            src = s.get("source")
            msg = s.get("message") or ""
            if src in ("system", "user"):
                if src == "user":
                    out.append(f"TASK: {truncate(msg, 200)}")
                continue
            if src in ("agent", "assistant", "model"):
                # Strip "Execute: " prefix
                m = re.match(r"^Execute:\s*(.+)$", msg.strip(), re.DOTALL)
                cmd = (m.group(1) if m else msg).strip()
                cmd = truncate(cmd, 130)
                obs = s.get("observation")
                if obs:
                    txt = obs if isinstance(obs, str) else json.dumps(obs)
                    # Strip noise
                    m2 = re.search(r'"content":\s*"([^"]*)"', txt)
                    if m2:
                        obs_text = m2.group(1).replace("\\n", " ⏎ ")
                    else:
                        obs_text = txt
                    out.append(f"  [{i}] $ {cmd}")
                    out.append(f"      → {truncate(obs_text, 220)}")
                else:
                    out.append(f"  [{i}] $ {cmd}")
    elif "messages" in raw:  # MiniSWE native
        for i, m in enumerate(raw["messages"]):
            role = m.get("role")
            content = m.get("content") or ""
            if role == "system":
                continue
            if role == "user" and i == 1:
                out.append(f"TASK: {truncate(content, 200)}")
                continue
            if role == "assistant":
                # Extract the bash block
                cb = re.search(r"```bash\s*\n(.+?)\n```", content, re.DOTALL)
                think = content.split("```")[0].strip().replace("THOUGHT:", "").strip()
                cmd = (cb.group(1).strip() if cb else "(no command)")
                out.append(f"  [{i}] THOUGHT: {truncate(think, 120)}")
                out.append(f"      $ {truncate(cmd, 130)}")
            elif role == "user":
                out.append(f"      → {truncate(content, 220)}")
        sub = (raw.get("info") or {}).get("submission")
        if sub:
            out.append(f"SUBMISSION: {truncate(sub, 250)}")
    return "\n".join(out)


if __name__ == "__main__":
    p = Path(sys.argv[1])
    if not p.is_absolute():
        p = REPO / p
    print(view(p))
