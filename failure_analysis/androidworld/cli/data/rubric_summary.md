# Heuristic Rubric Pre-Classification — All 126 Failures

> **Pre-judge baseline.** Each TB rubric leaf has a heuristic detector that
> approximates its decision procedure (string/regex). Lossy by design — agents
> can fail in ways no regex can detect. Expect a high `_unclassified_` rate;
> the LLM judge in Phase 4 fills that gap.
> 
> Source rubric: `rubric/rubric_v0.md` (TB Appendix C verbatim + Android edits)

**Pool:** 289 readable failures from `pilot_set.jsonl`

## Primary leaf assignment (single-label, priority order)

| TB leaf | Count | % |
|---|---:|---:|
| unclassified | 128 | 44.3% |
| context loss | 58 | 20.1% |
| weak verification | 43 | 14.9% |
| disobey specification | 30 | 10.4% |
| step repetition | 13 | 4.5% |
| unaware of termination conditions | 11 | 3.8% |
| no or incorrect verification | 6 | 2.1% |

## Per-leaf detector firing rate (independent of priority)

Each row = how often each leaf's detector returned a match, regardless of
whether it won the priority-order tiebreaker.

| TB leaf | Fired | % |
|---|---:|---:|
| Disobey specification | 30 | 10.4% |
| Step repetition | 23 | 8.0% |
| Unaware of termination conditions | 14 | 4.8% |
| Context loss | 93 | 32.2% |
| Task derailment | 0 | 0.0% |
| Reasoning action mismatch | 0 | 0.0% |
| Premature termination | 0 | 0.0% |
| No or incorrect verification | 8 | 2.8% |
| Weak verification | 56 | 19.4% |

## Per-agent leaf distribution

| Agent class | n | unclassified | context loss | disobey specification | no or incorrect verification | step repetition | unaware of termination conditions | weak verification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ClaudeCodeCLI | 64 | 21 | 7 | 9 | 0 | 8 | 8 | 11 |
| MiniSweAgent | 100 | 51 | 10 | 12 | 3 | 4 | 3 | 17 |
| Terminus2 | 125 | 56 | 41 | 9 | 3 | 1 | 0 | 15 |

## Per-agent leaf distribution (percent)

| Agent class | unclassified | context loss | disobey specification | no or incorrect verification | step repetition | unaware of termination conditions | weak verification |
|---|---:|---:|---:|---:|---:|---:|---:|
| ClaudeCodeCLI | 33% | 11% | 14% | 0% | 12% | 12% | 17% |
| MiniSweAgent | 51% | 10% | 12% | 3% | 4% | 3% | 17% |
| Terminus2 | 45% | 33% | 7% | 2% | 1% | 0% | 12% |

## Rubric ambiguities and gaps (from notes.md, validated at scale)

| Issue | Count | % | What it means |
|---|---:|---:|---|
| AMBIG-1: Step Repetition vs RAM (quoting-driven retries) | 11 | 3.8% | Step Repetition fires alongside ≥1 quoting error → could plausibly be Reasoning–Action Mismatch instead. Sharpen v1. |
| AMBIG-2: Disobey Spec vs Weak Verification (wrong surface) | 13 | 4.5% | Both detectors fire on same trajectory; current priority assigns Disobey Spec. Decide tiebreaker in v1. |
| GAP: honest infeasibility with handoff (no TB leaf covers) | 0 | 0.0% | Above the doc's ≥ 2-trajectory threshold for adding a leaf. |

## Caveats — heuristic limits

Heuristic detectors cannot capture:
- **Context Loss** — the rubric's 'forgetting earlier state/context' requires
  semantic comparison across the trajectory window. Detectors fire only on
  obvious re-discovery patterns (`pm list packages | grep` repeated, `.schema` ≥ 3x).
- **Task Derailment** — placeholder leaf in v0 with no known regex signal.
- **Reasoning–Action Mismatch (subtle cases)** — only the narrow case of
  'submission claims success but last 5 obs had errors' is detectable.
- **Disobey Specification (subtle cases)** — only forbidden-operation and
  wrong-write-surface variants are detectable. The rubric covers many other
  directive-contradiction modes (numeric metric shortfalls, response-format
  violations excluded by Step 3, soft-guidance departures) that need an LLM.

This is why the `_unclassified_` rate is high. Phase 4's LLM judge is the
intended way to assign these. The pre-classification here is a baseline for
the judge to be measured against, not a substitute.