"""Quick test: which model identifiers does Docent's proxy accept?"""
from pathlib import Path
from docent import Docent

client = Docent()
COLLECTION_ID = (Path(__file__).parent / "collection_id.txt").read_text().strip()
client.plan_name = "model_probe"

# Pick one trajectory by ID
runs = client.query(
    COLLECTION_ID,
    "SELECT ar.id AS run_id FROM agent_runs ar LIMIT 1",
    name="One run for probing",
)

import sys
candidate = sys.argv[1] if len(sys.argv) > 1 else "anthropic/claude-opus-4-7"
print(f"Testing model: {candidate}")

probe = client.read(
    prompt_template=[
        "Write the word OK and nothing else.\nRun: ",
        runs.run_id.as_type("agent_run"),
    ],
    model=candidate,
    name=f"Probe {candidate}",
)
try:
    res = probe.results
    print(f"SUCCESS: {res[0].output}")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {str(e)[:500]}")
