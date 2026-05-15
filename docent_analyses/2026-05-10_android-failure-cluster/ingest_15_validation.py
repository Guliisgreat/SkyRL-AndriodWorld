"""Upload the 15 v2-validation-sample trajectories to a fresh Docent collection.

This gives annotators a focused, distraction-free workspace — only the 15 trajectories
they need to label, separate from the parent 211-run collection.
"""
from __future__ import annotations
import json
from pathlib import Path

from docent import Docent
from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import (
    parse_chat_message, SystemMessage, UserMessage, AssistantMessage, ToolMessage, ToolCall,
)
import re

REPO = Path(__file__).resolve().parents[2]
HIDDEN_PATH = REPO / "failure_analysis/androidworld/cli/annotations/v2_validation_picks_hidden.jsonl"
PILOT_PATH = REPO / "failure_analysis/androidworld/cli/data/pilot_set.jsonl"

COLLECTION_NAME = "android-cli-v2-validation-15"
COLLECTION_DESCRIPTION = (
    "15 trajectories sampled from android-cli-failures-211 for two-annotator validation "
    "of rubric_v2 leaf assignments. Stratified by v2 primary leaf, 56% cross-confidence."
)


def trajectory_to_messages(traj_path: Path) -> list:
    raw = json.loads(traj_path.read_text())
    messages = []
    if raw.get("schema_version", "").startswith("ATIF-"):
        for s in raw.get("steps", []):
            src = s.get("source"); content = s.get("message") or ""
            if src == "system":
                messages.append(SystemMessage(content=content))
            elif src == "user":
                messages.append(UserMessage(content=content))
            elif src in ("agent", "assistant", "model"):
                tool_calls = []
                for j, tc in enumerate(s.get("tool_calls") or []):
                    name = tc.get("name") or (tc.get("function") or {}).get("name") or "bash"
                    args = tc.get("arguments") or (tc.get("function") or {}).get("arguments") or {}
                    tool_calls.append(ToolCall(
                        id=tc.get("id") or f"call_{s.get('step_id',0)}_{j}",
                        function=name,
                        arguments=args if isinstance(args, dict) else {"raw": str(args)},
                        type="function",
                    ))
                messages.append(AssistantMessage(content=content, tool_calls=tool_calls or None))
                obs = s.get("observation")
                if obs and tool_calls:
                    obs_text = obs if isinstance(obs, str) else json.dumps(obs)
                    m = re.search(r'"content":\s*"((?:[^"\\]|\\.)*)"', obs_text)
                    if m:
                        try: obs_text = json.loads(f'"{m.group(1)}"')
                        except Exception: pass
                    messages.append(ToolMessage(
                        content=obs_text,
                        tool_call_id=tool_calls[0].id,
                        function=tool_calls[0].function,
                    ))
    elif "messages" in raw:
        for m in raw.get("messages", []):
            try: messages.append(parse_chat_message(m))
            except Exception:
                role = m.get("role", "user")
                if role == "system": messages.append(SystemMessage(content=m.get("content","")))
                elif role == "user": messages.append(UserMessage(content=m.get("content","")))
                elif role == "assistant": messages.append(AssistantMessage(content=m.get("content","")))
                else: messages.append(UserMessage(content=f"[{role}] {m.get('content','')}"))
    return messages


def main():
    hidden = [json.loads(l) for l in HIDDEN_PATH.read_text().splitlines() if l.strip()]
    pilot = {r["trajectory_id"]: r for r in
             (json.loads(l) for l in PILOT_PATH.read_text().splitlines() if l.strip())}
    print(f"Loading 15 sampled trajectories...")

    agent_runs = []
    for i, h in enumerate(hidden, 1):
        tid = h["trajectory_id"]
        p = pilot[tid]
        messages = trajectory_to_messages(REPO / p["traj_path"])
        transcript = Transcript(
            messages=messages,
            metadata={
                "task_id": h["task_id"],
                "agent_class": h["agent_class"],
                "model": p.get("model_short"),
            },
        )
        ar = AgentRun(
            transcripts=[transcript],
            metadata={
                # Same fields as parent collection
                "task_id": h["task_id"],
                "task_name": h["task_name"],
                "agent_class": h["agent_class"],
                "model": p.get("model_short"),
                "config": p["config"],
                "step_count": p.get("step_count"),
                "max_turns": p.get("max_turns"),
                "finished": p.get("finished"),
                "scores": {"reward": 0},
                "trajectory_id": tid,
                # Validation-specific fields
                "sample_index": i,
                "v2_leaf_judge": h["v2_primary"],  # for post-annotation comparison only
            },
        )
        agent_runs.append(ar)
    print(f"Converted {len(agent_runs)} trajectories.")

    client = Docent()
    cid = client.create_collection(
        name=COLLECTION_NAME,
        description=COLLECTION_DESCRIPTION,
    )
    print(f"Created collection: {cid}")
    client.add_agent_runs(cid, agent_runs)
    print(f"Uploaded {len(agent_runs)} agent runs.")
    url = f"https://docent.transluce.org/dashboard/{cid}"
    print(f"View: {url}")

    cid_path = Path(__file__).parent / "validation_collection_id.txt"
    cid_path.write_text(cid + "\n")
    print(f"Saved id → {cid_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
