"""Cluster GPT-5.1-Codex failure modes on Terminal-Bench.

Phases (run incrementally — see comments):
    1. Per-run failure summary (LLM)
    2. Propose clusters from all summaries (LLM)
    3. Classify each run into a cluster (LLM)
    4. Sub-cluster the dominant cluster (added later)
"""

from docent import Docent

client = Docent()
COLLECTION_ID = "ee8a1051-3ae6-4d24-bccc-daf08dc5598f"
client.plan_name = "gpt51_codex_failure_clustering"

MODEL = "openai/gpt-5.4-mini"

# All GPT-5.1-Codex failures (reward=0 or null).
# Include task name + exception so the summarizer knows whether it was a timeout
# (agent ran out of wall time) or a clean exit (agent declared done but validation failed).
failed_runs = client.query(
    COLLECTION_ID,
    """
    SELECT ar.id AS run_id,
           ar.metadata_json->>'task' AS task,
           COALESCE(ar.metadata_json->>'exception', 'none') AS exception_type,
           COALESCE(CAST(CAST(ar.metadata_json->'scores'->>'reward' AS DOUBLE PRECISION) AS TEXT), 'null') AS reward
    FROM agent_runs ar
    WHERE ar.metadata_json->'agent'->>'model_name' = 'openai/gpt-5.1-codex'
      AND (CAST(ar.metadata_json->'scores'->>'reward' AS DOUBLE PRECISION) = 0
           OR ar.metadata_json->'scores'->>'reward' IS NULL)
    """,
    name="GPT-5.1 failed runs",
)

# ---------------- Phase 1: per-run failure summary ----------------

summarize = client.read(
    prompt_template=[
        "You are reviewing a single failed Terminal-Bench run by an AI coding agent ",
        "(GPT-5.1-Codex inside the terminus-2 harness). The agent operates a Linux shell ",
        "to solve a coding/sysadmin task; it fails if it does not complete before the ",
        "wall-clock budget expires (exception_type = AgentTimeoutError) or if it stops ",
        "early but the task's hidden tests fail (exception_type = none).\n\n",
        "Task name: ", failed_runs.task.as_type("text"),
        "\nException type: ", failed_runs.exception_type.as_type("text"),
        "\nReward: ", failed_runs.reward.as_type("text"),
        "\n\nFull agent run:\n", failed_runs.run_id.as_type("agent_run"),
        "\n\nWrite a focused 3-5 sentence summary of the *root cause* of failure:\n",
        "1. What the agent was trying to do at a high level.\n",
        "2. The specific blocker, mistake, or wrong direction that made the run fail. ",
        "(For timeouts: what was the agent stuck on or repeating? ",
        "For clean exits: what flawed assumption led it to stop early?)\n",
        "3. Any secondary contributing pattern (e.g. inefficient exploration, ",
        "misreading errors, fighting the environment, hallucinating an API, ",
        "premature declaration of success, etc.).\n\n",
        "Be specific about behaviors, not the task itself. ",
        "\"The agent kept rebuilding the toolchain after every edit\" is more useful than ",
        "\"the build was slow\". Cite specific transcript moments where helpful.",
    ],
    model=MODEL,
    name="Summarize GPT-5.1 failures",
)

# ---------------- Phase 2: propose clusters ----------------

summaries = client.query(
    COLLECTION_ID,
    f"""
    SELECT array_agg(rr.id) AS summary_ids
    FROM reading_results rr
    JOIN reading_result_links rrl ON rrl.result_id = rr.id
    WHERE rrl.reading_id = '{summarize}'
    """,
    name="All failure summaries",
)

propose_clusters = client.read(
    prompt_template=[
        "You are reviewing failure summaries from a sample of GPT-5.1-Codex runs ",
        "on Terminal-Bench (a benchmark of coding/sysadmin tasks done in a Linux shell).\n\n",
        "Failure summaries:\n",
        summaries.summary_ids.as_type("reading_result", is_list=True),
        "\n\nPropose 8-12 mutually exclusive failure-mode categories that capture the ",
        "distinct ways these runs went wrong. Each category should be specific enough ",
        "that a developer reading it could imagine a concrete fix or intervention. ",
        "Avoid vague categories like \"agent confused\" or \"task too hard\".\n\n",
        "Examples of good category granularity:\n",
        "- 'rebuild_loop': agent rebuilt a heavy artifact (toolchain, dataset, image) ",
        "after every small edit, exhausting time on redundant work.\n",
        "- 'misread_test_harness': agent declared success after running a wrong or ",
        "non-existent test command, missing the actual hidden tests.\n",
        "- 'env_dependency_fight': agent burned time installing/diagnosing a missing ",
        "system dependency it could have stubbed or worked around.\n\n",
        "For each category, output:\n",
        "- name: short snake_case identifier\n",
        "- description: 1-2 sentence specific behavior pattern\n",
        "- example_signature: one-sentence description of a tell-tale transcript pattern.",
    ],
    model=MODEL,
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
    name="Propose failure clusters",
)

# Force flush + auto-approve so the script can continue to phase 3 without manual gate.
client.flush(auto_approve=True)
clusters = propose_clusters.results[0].output
assert clusters is not None
categories = clusters["categories"]
category_names = [c["name"] for c in categories]
category_descriptions = "\n".join(
    f"  - {c['name']}: {c['description']} (signature: {c['example_signature']})"
    for c in categories
)
print(f"Proposed {len(category_names)} clusters: {', '.join(category_names)}")
print(category_descriptions)

# ---------------- Phase 3: classify each failed run ----------------

classify = client.read(
    prompt_template=[
        "You are classifying a failed Terminal-Bench run by GPT-5.1-Codex.\n",
        "Task: ", failed_runs.task.as_type("text"),
        "\nException: ", failed_runs.exception_type.as_type("text"),
        "\nReward: ", failed_runs.reward.as_type("text"),
        "\n\nFull agent run:\n", failed_runs.run_id.as_type("agent_run"),
        "\n\nClassify this run into exactly one of the failure-mode categories below. ",
        "Choose the category that *most directly caused* the run to fail (not a ",
        "secondary or earlier mistake). If multiple categories partially apply, pick ",
        "the one that captures the decisive moment.\n\n",
        "Categories:\n",
        category_descriptions,
        "\n\nIn the description field, briefly cite the transcript moment that made ",
        "this category the right choice.",
    ],
    model=MODEL,
    output_schema={
        "type": "object",
        "properties": {
            "failure_category": {"type": "string", "enum": category_names},
            "description": {"type": "string", "citations": True},
        },
        "required": ["failure_category", "description"],
    },
    name="Classify each failure",
)

# Force flush so we can aggregate.
client.flush(auto_approve=True)

# Aggregate counts per category, broken out by exception type.
cluster_counts = client.query(
    COLLECTION_ID,
    f"""
    SELECT failure_category,
           SUM(CASE WHEN exception_type = 'AgentTimeoutError' THEN 1 ELSE 0 END) AS timeouts,
           SUM(CASE WHEN exception_type = 'none' THEN 1 ELSE 0 END) AS clean_exits,
           COUNT(failure_category) AS total
    FROM (
        SELECT rr.output->>'failure_category' AS failure_category,
               COALESCE(ar.metadata_json->>'exception', 'none') AS exception_type
        FROM reading_results rr
        JOIN reading_result_links rrl ON rrl.result_id = rr.id
        JOIN agent_runs ar ON CAST(ar.id AS TEXT) = rr.arguments_dict->'run_id'->>'id'
        WHERE rrl.reading_id = '{classify}'
    ) AS sub
    GROUP BY failure_category
    ORDER BY total DESC
    """,
    name="Cluster sizes",
)

# ---------------- Phase 4: sub-cluster the two largest categories ----------------

# Helper: rerun summarize+propose+classify but limited to one parent cluster.
def subcluster(parent_name: str, parent_description: str, num_subclusters: str = "5-7"):
    """Sub-cluster runs whose top-level category equals parent_name."""
    runs_in_cluster = client.query(
        COLLECTION_ID,
        f"""
        SELECT ar.id AS run_id,
               ar.metadata_json->>'task' AS task,
               COALESCE(ar.metadata_json->>'exception', 'none') AS exception_type
        FROM agent_runs ar
        JOIN reading_results rr
          ON CAST(ar.id AS TEXT) = rr.arguments_dict->'run_id'->>'id'
        JOIN reading_result_links rrl ON rrl.result_id = rr.id
        WHERE rrl.reading_id = '{classify}'
          AND rr.output->>'failure_category' = '{parent_name}'
        """,
        name=f"Runs in {parent_name}",
    )

    sub_summarize = client.read(
        prompt_template=[
            f"You are doing a fine-grained analysis of a single run that has already ",
            f"been classified into the high-level failure category '{parent_name}'.\n",
            f"Category meaning: {parent_description}\n\n",
            "Task: ", runs_in_cluster.task.as_type("text"),
            "\nException: ", runs_in_cluster.exception_type.as_type("text"),
            "\n\nFull agent run:\n", runs_in_cluster.run_id.as_type("agent_run"),
            "\n\nWrite a 2-3 sentence summary that distinguishes *why this run, ",
            "specifically*, fits this failure category. Focus on the specific ",
            "behavior pattern (what was the agent doing in lieu of progress, what ",
            "specifically did it skip / over-rely on / get stuck on). The goal is to ",
            "expose finer sub-patterns within the category.",
        ],
        model=MODEL,
        name=f"Sub-summarize {parent_name}",
    )

    sub_summaries = client.query(
        COLLECTION_ID,
        f"""
        SELECT array_agg(rr.id) AS summary_ids
        FROM reading_results rr
        JOIN reading_result_links rrl ON rrl.result_id = rr.id
        WHERE rrl.reading_id = '{sub_summarize}'
        """,
        name=f"All {parent_name} sub-summaries",
    )

    sub_propose = client.read(
        prompt_template=[
            f"You are reviewing fine-grained failure summaries from runs already ",
            f"classified as '{parent_name}'.\n",
            f"Category meaning: {parent_description}\n\n",
            "Sub-summaries:\n",
            sub_summaries.summary_ids.as_type("reading_result", is_list=True),
            f"\n\nPropose {num_subclusters} mutually exclusive *sub-categories* of this ",
            "failure mode. Each sub-category must be specific enough that a developer ",
            "can imagine a concrete fix or intervention (e.g., a prompt change, an ",
            "agent-loop adjustment, a tool addition). Avoid restating the parent ",
            "category in different words.\n\n",
            "For each sub-category output: name (snake_case), description (1-2 ",
            "sentence concrete behavior), example_signature (one-sentence transcript ",
            "tell), and proposed_fix (one-sentence developer-actionable mitigation).",
        ],
        model=MODEL,
        output_schema={
            "type": "object",
            "properties": {
                "subcategories": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "example_signature": {"type": "string"},
                            "proposed_fix": {"type": "string"},
                        },
                        "required": ["name", "description", "example_signature", "proposed_fix"],
                    },
                },
            },
            "required": ["subcategories"],
        },
        name=f"Propose {parent_name} sub-clusters",
    )

    client.flush(auto_approve=True)
    sub_clusters = sub_propose.results[0].output
    assert sub_clusters is not None
    sub_categories = sub_clusters["subcategories"]
    sub_names = [c["name"] for c in sub_categories]
    sub_descriptions = "\n".join(
        f"  - {c['name']}: {c['description']} (signature: {c['example_signature']}; "
        f"fix: {c['proposed_fix']})"
        for c in sub_categories
    )
    print(f"[{parent_name}] sub-clusters: {', '.join(sub_names)}")

    sub_classify = client.read(
        prompt_template=[
            f"You are classifying a run already labelled '{parent_name}' into one of ",
            "the sub-categories below. Choose the sub-category that most directly ",
            "describes the run's specific failure pattern.\n\n",
            "Task: ", runs_in_cluster.task.as_type("text"),
            "\nException: ", runs_in_cluster.exception_type.as_type("text"),
            "\n\nFull agent run:\n", runs_in_cluster.run_id.as_type("agent_run"),
            "\n\nSub-categories:\n",
            sub_descriptions,
            "\n\nIn 'description', briefly cite the transcript moment that made this ",
            "the right choice.",
        ],
        model=MODEL,
        output_schema={
            "type": "object",
            "properties": {
                "subcategory": {"type": "string", "enum": sub_names},
                "description": {"type": "string", "citations": True},
            },
            "required": ["subcategory", "description"],
        },
        name=f"Classify {parent_name} sub-clusters",
    )

    sub_counts = client.query(
        COLLECTION_ID,
        f"""
        SELECT subcategory, COUNT(subcategory) AS cnt
        FROM (
            SELECT rr.output->>'subcategory' AS subcategory
            FROM reading_results rr
            JOIN reading_result_links rrl ON rrl.result_id = rr.id
            WHERE rrl.reading_id = '{sub_classify}'
        ) AS sub
        GROUP BY subcategory
        ORDER BY cnt DESC
        """,
        name=f"{parent_name} sub-cluster sizes",
    )
    return sub_classify, sub_counts


with client.step_group("recon_only_timeout sub-clusters"):
    recon_classify, recon_counts = subcluster(
        "recon_only_timeout",
        "Agent spent the entire run inspecting files/repo/binary structure but never "
        "transitioned to writing/editing code or running the actual task.",
    )

with client.step_group("premature_success sub-clusters"):
    prem_classify, prem_counts = subcluster(
        "premature_success",
        "Agent declared the task complete after a superficial check (file exists, "
        "command exited cleanly), without validating the hidden requirements.",
    )

client.flush(auto_approve=True)


