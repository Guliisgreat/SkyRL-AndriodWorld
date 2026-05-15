---
docent_collection_id: ee8a1051-3ae6-4d24-bccc-daf08dc5598f
docent_source_reading_plan_id: a6fbbe01-1678-452f-b934-63f4d3cd51bb
title: Why GPT-5.1-Codex Fails on Terminal-Bench
---

# Why GPT-5.1-Codex Fails on Terminal-Bench

GPT-5.1-Codex completes only 27% of the 267 Terminal-Bench attempts in this collection (72 of 267), trailing GPT-5-Codex at 35% on the same task set. This report identifies the dominant failure modes by reading every failed transcript with an LLM, clustering the resulting failure summaries into 11 top-level categories, and drilling into the two largest categories until each surviving sub-cluster maps to a concrete behavioral fix.

## Outcome split

Two-thirds of failures hit the wall-clock budget; the other third end cleanly with the agent self-declaring success. These two regimes have very different root causes and are best analysed separately.

::dql-table{title="Failure outcome split for GPT-5.1-Codex" query="SELECT exception_type, reward_bucket, COUNT(reward_bucket) AS run_count FROM (SELECT COALESCE(metadata_json->>'exception', 'none') AS exception_type, CASE WHEN CAST(metadata_json->'scores'->>'reward' AS DOUBLE PRECISION) = 1 THEN 'perfect' WHEN CAST(metadata_json->'scores'->>'reward' AS DOUBLE PRECISION) = 0 THEN 'zero' WHEN metadata_json->'scores'->>'reward' IS NULL THEN 'null' ELSE 'partial' END AS reward_bucket FROM agent_runs WHERE metadata_json->'agent'->>'model_name' = 'openai/gpt-5.1-codex') AS sub GROUP BY exception_type, reward_bucket ORDER BY exception_type, run_count DESC"}
Reward 1 = task passed; Reward 0 = task failed; null = no reward recorded. AgentTimeoutError fires when the harness kills the run for exceeding the time budget.
::

For comparison, GPT-5-Codex on the same task set times out far less often (29% vs 49%), suggesting the timeout-driven failure modes below are largely unique to the 5.1 generation rather than baked into the benchmark.

::dql-table{title="Per-model run counts and outcomes" query="SELECT model_name, COUNT(model_name) AS runs, ROUND(CAST(AVG(reward) AS NUMERIC), 3) AS avg_reward, SUM(CASE WHEN exception = 'AgentTimeoutError' THEN 1 ELSE 0 END) AS timeouts FROM (SELECT COALESCE(metadata_json->'agent'->>'model_name', 'unknown') AS model_name, CAST(metadata_json->'scores'->>'reward' AS DOUBLE PRECISION) AS reward, COALESCE(metadata_json->>'exception', 'none') AS exception FROM agent_runs) AS sub GROUP BY model_name ORDER BY runs DESC"}
::

## Top-level failure clusters

Reading every failed transcript and clustering the summaries yields 11 distinct failure modes. Two — `recon_only_timeout` and `premature_success` — together account for roughly half of all failures, and they sit on opposite sides of the timeout/clean-exit split: one is "agent never transitioned from looking to doing" and the other is "agent stopped doing too early."

::dql-table{title="Top-level failure mode distribution" query="SELECT failure_category, SUM(CASE WHEN exception_type = 'AgentTimeoutError' THEN 1 ELSE 0 END) AS timeouts, SUM(CASE WHEN exception_type = 'none' THEN 1 ELSE 0 END) AS clean_exits, COUNT(failure_category) AS total FROM (SELECT rr.output->>'failure_category' AS failure_category, COALESCE(ar.metadata_json->>'exception', 'none') AS exception_type FROM reading_results rr JOIN reading_result_links rrl ON rrl.result_id = rr.id JOIN agent_runs ar ON CAST(ar.id AS TEXT) = rr.arguments_dict->'run_id'->>'id' WHERE rrl.reading_id = '191897a6-06f2-440e-bb52-d33ffc9421d1') AS sub GROUP BY failure_category ORDER BY total DESC"}
Each row counts the failures whose root cause was classified into that category, broken out by whether the run died via timeout or self-terminated cleanly. 195 failed runs in total.
::

The next three clusters are also dominated by timeouts and form a recognisable family of "agent burned the budget on the wrong sub-problem":

- `env_dependency_fight` (22): time spent installing or fighting missing packages and toolchain versions.
- `over_broad_exploration` (20): many overlapping searches and probes without converging on an implementation.
- `tool_availability_mismatch` (14): the agent reaches for tools (`apply_patch`, `rg`, `xxd`, `tmux`...) that aren't installed and gets stuck adapting.

`hidden_test_mismatch` (19) sits with `premature_success` in the clean-exit family — the agent finished, but its artifact didn't satisfy the unspoken grader contract.

The smaller categories (`format_parsing_dead_end`, `environmental_access_block`, `shell_control_failure`, `heavy_job_churn`, `conflict_unresolved`) each affect 2–6% of failures and represent narrower environment-specific traps; they are visible in the table above but not drilled into here.

## Drill-down 1: `recon_only_timeout` — agent never transitions from reading to building

These 47 runs (all timeouts) share the same shape: the agent inspects the workspace, the test files, or the target binary and never issues a meaningful write/build/run command before the budget expires. Sub-clustering produces seven specific patterns:

::dql-table{title="recon_only_timeout sub-cluster sizes" query="SELECT subcategory, COUNT(subcategory) AS run_count FROM (SELECT rr.output->>'subcategory' AS subcategory FROM reading_results rr JOIN reading_result_links rrl ON rrl.result_id = rr.id WHERE rrl.reading_id = '8d372408-3c64-4804-90ce-1ac97fc0a384' AND rr.output->>'subcategory' IS NOT NULL) AS sub GROUP BY subcategory ORDER BY run_count DESC"}
::

Three of those seven account for 33 of 47 runs and represent the bulk of the budget-on-recon problem:

- **`analysis_of_tests_or_docs_only` (15)** — agent reads test files, READMEs, and prompts to extract the spec, but never executes a candidate implementation against them. This is a "specification-mining loop" with no action edge.
- **`workspace_layout_or_target_locate_stall` (9)** — agent enumerates directories and locates the right target file, then stops once orientation is "complete" rather than starting work on the file it just located.
- **`file_inspection_without_transition` (9)** — agent reads the relevant source files but never moves to `apply_patch` / file write / build / run.

A representative example showing the spec-mining pattern:

::reading-result{id="08a641f1-646c-4006-aba5-5374822a1b2d" title="schemelike-metacircular-eval — analysis_of_tests_or_docs_only"}
The classifier explains why this run fits the sub-cluster, citing transcript moments where the agent reads `interp.py`, browses test files, and infers semantics without ever creating `eval.scm`, patching code, or executing anything against the test suite.
::

The shared signature across these three sub-clusters: the agent's tool-call stream is dominated by `cat`, `grep`, `find`, and `sed`, with no `apply_patch` / file-write / `pytest` / `make` events before the timeout. That is a concrete, log-detectable behavioral pattern.

## Drill-down 2: `premature_success` — agent declares done after a superficial check

These 47 runs are mostly clean exits (44 of 47): the agent generates an artifact, performs a token check, and exits before validating against the actual grader. Sub-clustering collapses this category into two patterns, with one strongly dominant:

::dql-table{title="premature_success sub-cluster sizes" query="SELECT subcategory, COUNT(subcategory) AS run_count FROM (SELECT rr.output->>'subcategory' AS subcategory FROM reading_results rr JOIN reading_result_links rrl ON rrl.result_id = rr.id WHERE rrl.reading_id = '78067321-17bb-4479-990d-5d184056726d' AND rr.output->>'subcategory' IS NOT NULL) AS sub GROUP BY subcategory ORDER BY run_count DESC"}
::

- **`serialization_or_generated_artifact_not_round_tripped` (39)** — agent writes the deliverable (a SPARQL query, JSON result, compressed archive, generated source file...) and immediately marks the task complete, validating only that the file *exists* or that the producer command exited 0. The artifact is never fed back through its consumer (parser, decompressor, browser, model, checker) to confirm round-trip correctness.
- **`semantic_equivalence_unchecked_after_refactor` (6)** — agent rewrites code into a "cleaner" form (refactor, query rewrite, proof reorganisation) and assumes equivalence without diffing outputs against the original.

A representative example of the dominant pattern:

::reading-result{id="071d7442-d66a-451a-b5fc-658e081267db" title="mteb-retrieve — serialization_or_generated_artifact_not_round_tripped"}
The classifier cites the moment where the agent generates the result file, confirms it on disk, and stops without running the artifact through the downstream consumer that the grader actually evaluates.
::

This single sub-cluster — "wrote a file, never round-tripped it" — is the largest specific failure mode in the dataset: 39 of 195 failures (20%) and 39 of 65 clean-exit failures (60%).

## Recommendations

Each recommendation maps to a specific sub-cluster above and ought to be evaluated against the corresponding evidence rows.

::callout{color="green" title="Recommendation 1 — round-trip every generated artifact before declaring success"}
Add a hard rule to the agent loop: for any task whose deliverable is a file, the run cannot terminate as `success` until that file has been *consumed* by something other than `cat`/`ls`/`stat`. Concretely: parse the JSON, run the SPARQL, decompress the archive, load the model, etc. This single rule targets ~20% of all failures (the `serialization_or_generated_artifact_not_round_tripped` sub-cluster of `premature_success`).
::

::callout{color="green" title="Recommendation 2 — cap consecutive read-only steps with a forced action"}
The three dominant `recon_only_timeout` sub-clusters all share the signature "many `cat`/`grep`/`find` calls in a row, no `apply_patch` / write / build / run". Add a heuristic in the harness or the system prompt that, after N consecutive read-only commands, requires the next action to be a state-changing one (file write, command execution, or explicit `noop` if the agent really has nothing yet). This targets ~17% of all failures (33 of 195 in `recon_only_timeout`'s top three sub-clusters).
::

::callout{color="orange" title="Caveat on confounders"}
The 27% success rate is from a single seed per (task, model) pair. Per-task counts are only ~3 attempts per model, so a few task-level idiosyncrasies could shift the smaller cluster sizes. The two headline clusters (`recon_only_timeout` and `premature_success`) are robust at 47 examples each, but the long tail (`heavy_job_churn`, `conflict_unresolved`, etc.) should be treated as suggestive rather than precise.
::

## Methodology

The clustering pipeline ran in four phases against all 195 GPT-5.1-Codex failed runs:

1. Per-run failure summary — one LLM read of each transcript producing a 3–5 sentence root-cause diagnosis (195 calls).
2. Cluster proposal — a single LLM call over all 195 summaries proposing 8–12 mutually exclusive failure categories.
3. Per-run classification into one of the proposed categories (195 calls).
4. Sub-clustering of the two dominant top-level categories (47 + 47 runs), each repeating phases 1–3 within the cluster.

Every classification result is independently inspectable via the embedded tables and reading-result links above; clicking any row opens the underlying transcript and the LLM's explanation in the Docent UI.
