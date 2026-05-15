"""Ingest the 211 CLI-solvable readable failures into a fresh Docent collection.

Source: failure_analysis/androidworld/cli/data/pilot_set.jsonl
Filter: drop GUI-only tasks (per docs/final/AndroidWorld2026/androidworld_ground_truth_reference_v2.md)
Result: 211 agent_runs across 6 configs.
"""
from __future__ import annotations
import json, re
from pathlib import Path

from docent import Docent
from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import (
    parse_chat_message, SystemMessage, UserMessage, AssistantMessage, ToolMessage, ToolCall,
)

REPO = Path(__file__).resolve().parents[2]
PILOT_PATH = REPO / "failure_analysis/androidworld/cli/data/pilot_set.jsonl"
GT_REF = REPO / "docs/final/AndroidWorld2026/androidworld_ground_truth_reference_v2.md"

COLLECTION_NAME = "android-cli-failures-211"
COLLECTION_DESCRIPTION = (
    "211 CLI-solvable readable failures across 6 CLI agents on AndroidWorld seed 30, "
    "for bottom-up failure-mode clustering (no v1 rubric priors)."
)


def gui_only_ids() -> set[int]:
    text = GT_REF.read_text()
    gui = set(); cur = None
    for ln in text.splitlines():
        m = re.match(r'###\s+Task\s+0?(\d+):', ln)
        if m: cur = int(m.group(1)); continue
        if cur is not None and re.match(r'\*\*Status:\*\*\s*GUI-only', ln):
            gui.add(cur); cur = None
        elif cur is not None and ln.startswith('**Status:**'):
            cur = None
    return gui


def trajectory_to_messages(traj_path: Path) -> list:
    """Convert ATIF or MiniSWE native trajectory to a list of Docent messages."""
    raw = json.loads(traj_path.read_text())
    messages = []

    if raw.get("schema_version", "").startswith("ATIF-"):
        # ATIF format: steps[] with source + message + observation
        for s in raw.get("steps", []):
            src = s.get("source")
            content = s.get("message") or ""
            if src == "system":
                messages.append(SystemMessage(content=content))
            elif src == "user":
                messages.append(UserMessage(content=content))
            elif src in ("agent", "assistant", "model"):
                # Build assistant message with tool_calls if present
                tool_calls = []
                tcs = s.get("tool_calls") or []
                for j, tc in enumerate(tcs):
                    name = tc.get("name") or (tc.get("function") or {}).get("name") or "bash"
                    args = tc.get("arguments") or (tc.get("function") or {}).get("arguments") or {}
                    tool_calls.append(ToolCall(
                        id=tc.get("id") or f"call_{s.get('step_id', 0)}_{j}",
                        function=name,
                        arguments=args if isinstance(args, dict) else {"raw": str(args)},
                        type="function",
                    ))
                messages.append(AssistantMessage(
                    content=content,
                    tool_calls=tool_calls or None,
                ))
                # Observation becomes a tool message
                obs = s.get("observation")
                if obs and tool_calls:
                    obs_text = obs if isinstance(obs, str) else json.dumps(obs)
                    # Extract inner content from {"results":[{"content":"..."}]} envelope if present
                    m_ = re.search(r'"content":\s*"((?:[^"\\]|\\.)*)"', obs_text)
                    if m_:
                        try: obs_text = json.loads(f'"{m_.group(1)}"')
                        except Exception: pass
                    messages.append(ToolMessage(
                        content=obs_text,
                        tool_call_id=tool_calls[0].id,
                        function=tool_calls[0].function,
                    ))
    elif "messages" in raw:
        # MiniSWE native format: messages[] in openai-style format
        for m in raw.get("messages", []):
            try:
                messages.append(parse_chat_message(m))
            except Exception:
                # Fallback: best-effort
                role = m.get("role", "user")
                if role == "system": messages.append(SystemMessage(content=m.get("content","")))
                elif role == "user": messages.append(UserMessage(content=m.get("content","")))
                elif role == "assistant": messages.append(AssistantMessage(content=m.get("content","")))
                else: messages.append(UserMessage(content=f"[{role}] {m.get('content','')}"))
    return messages


def main():
    rows = [json.loads(l) for l in PILOT_PATH.read_text().splitlines() if l.strip()]
    print(f"Loaded pilot_set: {len(rows)} readable failures")

    gui = gui_only_ids()
    cli = [r for r in rows if r["task_id"] not in gui]
    print(f"After GUI-only filter: {len(cli)} CLI-solvable readable failures")

    # Convert each to AgentRun
    agent_runs = []
    errors = []
    for r in cli:
        traj_path = REPO / r["traj_path"]
        try:
            messages = trajectory_to_messages(traj_path)
            if not messages:
                raise ValueError("no messages")
            transcript = Transcript(
                messages=messages,
                metadata={
                    "task_id": r["task_id"],
                    "agent_class": r["agent_class"],
                    "model": r.get("model_short"),
                },
            )
            ar = AgentRun(
                transcripts=[transcript],
                metadata={
                    "task_id": r["task_id"],
                    "task_name": r["task_name"],
                    "agent_class": r["agent_class"],
                    "model": r.get("model_short"),
                    "config": r["config"],
                    "step_count": r.get("step_count"),
                    "max_turns": r.get("max_turns"),
                    "finished": r.get("finished"),
                    "real_agent_steps": r.get("real_agent_steps"),
                    "scores": {"reward": 0},  # all are failures
                    "trajectory_id": r["trajectory_id"],
                },
            )
            agent_runs.append(ar)
        except Exception as e:
            errors.append({"trajectory_id": r["trajectory_id"], "error": str(e)[:300]})

    print(f"Converted: {len(agent_runs)} / {len(cli)}")
    if errors:
        print(f"Conversion errors ({len(errors)}):")
        for e in errors[:5]: print(f"  {e}")

    # Upload to Docent — reuse collection_id.txt if present (idempotent)
    client = Docent()
    cid_path = Path(__file__).parent / "collection_id.txt"
    if cid_path.exists() and cid_path.read_text().strip():
        collection_id = cid_path.read_text().strip()
        print(f"Reusing existing collection: {collection_id}")
    else:
        collection_id = client.create_collection(
            name=COLLECTION_NAME,
            description=COLLECTION_DESCRIPTION,
        )
        print(f"Created collection: {collection_id}")

    client.add_agent_runs(collection_id, agent_runs)
    print(f"Uploaded {len(agent_runs)} agent runs.")
    print(f"View: https://docent.transluce.org/dashboard/{collection_id}")

    # Save collection id for the clustering script
    cid_path = Path(__file__).parent / "collection_id.txt"
    cid_path.write_text(collection_id + "\n")
    print(f"Saved collection_id → {cid_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
