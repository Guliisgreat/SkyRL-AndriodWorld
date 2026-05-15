"""Bottom-up free-form clustering of 211 AndroidWorld CLI failures.

This intentionally does NOT use the v1 rubric — the goal is to re-discover
failure-mode categories from the data with no prior taxonomy.

Phases (build incrementally):
    1. Per-trajectory failure summary (LLM)
    2. Propose 5-12 categories from all summaries (LLM, one call)
    3. Classify each trajectory into a proposed category (LLM)
    4. Aggregate counts per category by agent / app
"""
from pathlib import Path
from docent import Docent

client = Docent()
COLLECTION_ID = (Path(__file__).parent / "collection_id.txt").read_text().strip()
client.plan_name = "android_cli_failure_freeform_clustering"

MODEL = "openai/gpt-5.4-mini"

# Pull all 211 readable failures with the metadata fields the summarizer needs
failed_runs = client.query(
    COLLECTION_ID,
    """
    SELECT ar.id AS run_id,
           ar.metadata_json->>'task_id' AS task_id,
           ar.metadata_json->>'task_name' AS task_name,
           ar.metadata_json->>'agent_class' AS agent_class,
           ar.metadata_json->>'model' AS model,
           ar.metadata_json->>'step_count' AS step_count,
           ar.metadata_json->>'max_turns' AS max_turns
    FROM agent_runs ar
    """,
    name="All 211 readable failures",
)

# ---------------- Phase 1: per-trajectory failure summary ----------------
# Goal: a 3-5 sentence root-cause summary, framed to surface BEHAVIORS, not task names.
# Deliberately *no Android-app-name biasing*, *no v1-rubric language*.

summarize = client.read(
    prompt_template=[
        "You are reviewing a single failed run by an AI CLI agent on AndroidWorld. ",
        "AndroidWorld is a benchmark of 116 Android tasks (calendar, SMS, notes, maps, music, ",
        "expense apps, system settings) that the agent attempts to solve via `adb shell` commands ",
        "only — no screen interaction, no taps, no screenshots. The agent fails when its actions ",
        "don't produce the system state the verifier expects.\n\n",
        "Task ID: ", failed_runs.task_id.as_type("text"),
        "\nTask description: ", failed_runs.task_name.as_type("text"),
        "\nAgent harness: ", failed_runs.agent_class.as_type("text"),
        "\nModel: ", failed_runs.model.as_type("text"),
        "\nSteps used / max: ", failed_runs.step_count.as_type("text"), " / ", failed_runs.max_turns.as_type("text"),
        "\n\nFull agent run:\n", failed_runs.run_id.as_type("agent_run"),
        "\n\nWrite a focused 3-5 sentence summary of the ROOT CAUSE of failure.\n\n",
        "Cover:\n",
        "1. What the agent was attempting at a high level.\n",
        "2. The specific behavior, mistake, blocker, or wrong direction that made the run fail. ",
        "Be concrete: did the agent write to the wrong DB? Hit a permission wall and not pivot? ",
        "Fabricate a value? Loop on the same command? Give up early? Misread an error?\n",
        "3. Any secondary contributing pattern.\n\n",
        "**Focus on agent BEHAVIORS, not the task or the app.** ",
        "Bad: \"the SMS task failed because SMS is hard\". ",
        "Good: \"the agent inserted a row directly into mmssms.db without setting the ",
        "default-SMS-app, so the SmsProvider didn't surface the row\". ",
        "Cite specific transcript moments where helpful.",
    ],
    model=MODEL,
    name="Failure root-cause summaries",
)

# ---------------- Phase 2: propose clusters ----------------
# One call sees ALL 211 summaries and proposes a free-form taxonomy.
# Range 5-12: enough granularity to be useful, not so many that each leaf is sparse.

summaries = client.query(
    COLLECTION_ID,
    f"""
    SELECT array_agg(rr.id) AS summary_ids
    FROM reading_results rr
    JOIN reading_result_links rrl ON rrl.result_id = rr.id
    WHERE rrl.reading_id = '{summarize}'
    """,
    name="All failure summaries (aggregated)",
)

propose_clusters = client.read(
    prompt_template=[
        "You are reviewing failure summaries from 211 AndroidWorld CLI agent runs (3 agent ",
        "harnesses × 2 underlying models each, all on seed 30). All runs are failures.\n\n",
        "Failure summaries:\n",
        summaries.summary_ids.as_type("reading_result", is_list=True),
        "\n\nPropose 5-12 MUTUALLY EXCLUSIVE failure-mode categories that capture the ",
        "distinct BEHAVIORS that caused these runs to fail.\n\n",
        "Quality bar for categories:\n",
        "- Specific enough that a researcher reading it could imagine a concrete prompt-engineering ",
        "  fix, training data change, or harness intervention.\n",
        "- About the AGENT'S BEHAVIOR, not the task type. \"SMS tasks failed\" is not a category. ",
        "  \"Agent insists on using the standard Android API path when the agent's UID lacks ",
        "  permission, then writes around it incorrectly\" IS a category.\n",
        "- Mutually exclusive: a typical run should clearly fit ONE category most.\n",
        "- Collectively exhaustive of what you saw — every summary should be classifiable.\n\n",
        "AVOID category names that simply restate TB/MAST rubric leaves like \"weak verification\", ",
        "\"step repetition\", \"context loss\" — those are pre-existing labels. We want categories that ",
        "describe what we observed in THIS data, not generic agent-failure jargon.\n\n",
        "For each category, output:\n",
        "- name: short snake_case identifier\n",
        "- description: 1-2 sentence specific behavior pattern\n",
        "- example_signature: one-sentence description of a tell-tale transcript pattern",
    ],
    model=MODEL,
    reasoning_effort="high",
    max_new_tokens=12000,
    output_schema={
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "example_signature": {"type": "string"},
                    },
                    "required": ["name", "description", "example_signature"],
                },
            },
        },
        "required": ["categories"],
    },
    name="Propose failure-mode clusters",
)

# Approve phase 1+2 auto so we can read clusters in this same script
client.flush(auto_approve=True)
clusters = propose_clusters.results[0].output
assert clusters is not None
categories = clusters["categories"]
category_names = [c["name"] for c in categories]
category_descriptions = "\n".join(
    f"  - {c['name']}: {c['description']} (signature: {c['example_signature']})"
    for c in categories
)
print(f"\nProposed {len(category_names)} clusters: {', '.join(category_names)}\n")
print(category_descriptions)

# Save clusters to disk for inspection
cdesc_path = Path(__file__).parent / "proposed_clusters.md"
cdesc_path.write_text(
    f"# Proposed Free-Form Clusters ({len(category_names)})\n\n"
    + "\n".join(f"## {c['name']}\n\n**Description:** {c['description']}\n\n"
                f"**Signature:** {c['example_signature']}\n\n"
                for c in categories)
)
print(f"\nSaved clusters → {cdesc_path}")

# ---------------- Phase 3: classify each run ----------------
# v2: re-run with Opus max effort (was gpt-5.4-mini in v1 run; mini under-powered
# for per-trajectory classification given each call requires reading the full
# trajectory + 9 category descriptions and assigning one with cited evidence).
CLASSIFY_MODEL = "anthropic/claude-opus-4-7"

classify = client.read(
    prompt_template=[
        "Classify this AndroidWorld CLI agent failure into exactly one of the categories below.\n\n",
        "Task ID: ", failed_runs.task_id.as_type("text"),
        "\nTask description: ", failed_runs.task_name.as_type("text"),
        "\nAgent: ", failed_runs.agent_class.as_type("text"), " / ", failed_runs.model.as_type("text"),
        "\n\nFull agent run:\n", failed_runs.run_id.as_type("agent_run"),
        "\n\nChoose the category that MOST DIRECTLY caused the run to fail (not a secondary ",
        "or earlier mistake). If multiple partially apply, pick the one that captures the ",
        "DECISIVE moment.\n\n",
        "Categories:\n",
        category_descriptions,
        "\n\nIn 'description', briefly cite the transcript moment that made this category fit.",
    ],
    model=CLASSIFY_MODEL,
    max_new_tokens=4000,
    output_schema={
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": category_names},
            "description": {"type": "string", "citations": True},
        },
        "required": ["category", "description"],
    },
    name="Classify each failure (Opus 4.7)",
)

client.flush(auto_approve=True)

# Aggregate counts per category broken out by agent
cluster_counts = client.query(
    COLLECTION_ID,
    f"""
    SELECT category,
           SUM(CASE WHEN agent_class = 'ClaudeCodeCLI' THEN 1 ELSE 0 END) AS claude_code,
           SUM(CASE WHEN agent_class = 'MiniSweAgent' THEN 1 ELSE 0 END) AS minisweagent,
           SUM(CASE WHEN agent_class = 'Terminus2' THEN 1 ELSE 0 END) AS terminus2,
           COUNT(category) AS total
    FROM (
        SELECT rr.output->>'category' AS category,
               ar.metadata_json->>'agent_class' AS agent_class
        FROM reading_results rr
        JOIN reading_result_links rrl ON rrl.result_id = rr.id
        JOIN agent_runs ar ON CAST(ar.id AS TEXT) = rr.arguments_dict->'run_id'->>'id'
        WHERE rrl.reading_id = '{classify}'
    ) AS sub
    GROUP BY category
    ORDER BY total DESC
    """,
    name="Cluster sizes by agent class",
)

print("\nDone. Inspect at:")
print(f"  https://docent.transluce.org/dashboard/{COLLECTION_ID}")
