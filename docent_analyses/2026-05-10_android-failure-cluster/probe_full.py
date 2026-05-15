"""Test Phase 3 setup on one trajectory: model + reasoning_effort + structured output."""
from pathlib import Path
from docent import Docent

client = Docent()
COLLECTION_ID = (Path(__file__).parent / "collection_id.txt").read_text().strip()
client.plan_name = "probe_full"

runs = client.query(
    COLLECTION_ID,
    "SELECT ar.id AS run_id, ar.metadata_json->>'task_name' AS task_name FROM agent_runs ar LIMIT 1",
    name="One run for full probe",
)

categories = ["category_a", "category_b", "category_c"]
cat_desc = "\n".join(f"- {c}: dummy" for c in categories)

probe = client.read(
    prompt_template=[
        "Pick one of:\n", cat_desc,
        "\n\nFor this run:\n", runs.run_id.as_type("agent_run"),
        "\n\nTask: ", runs.task_name.as_type("text"),
    ],
    model="anthropic/claude-opus-4-7",
    max_new_tokens=2000,
    output_schema={
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": categories},
            "description": {"type": "string", "citations": True},
        },
        "required": ["category", "description"],
    },
    name="Full-config probe",
)
try:
    res = probe.results
    print(f"SUCCESS: {res[0].output}")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {str(e)[:1000]}")
