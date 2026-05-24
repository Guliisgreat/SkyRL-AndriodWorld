# fig1 — Paradigm Comparison: CLI vs GUI

**Paper placement:** **Main paper.**
**Figure file:** `fig1_paradigm_comparison.pdf` / `.png`
**Raw data:** `fig1_paradigm_comparison.csv`
**Source script:** `docent_analyses/figures/figure4_paradigm_tb_grouped.py`

---

## Caption (paper-ready)

**Figure 1. Failure-mode prevalence across TB leaves for CLI vs GUI agents.**
Each group corresponds to one paradigm on the fair-comparison subset of
AndroidWorld (CLI: 1,508 trajectories from {ClaudeCodeCLI, MiniSweAgent,
Terminus2} × 5 models; GUI: 194 trajectories from {Qwen3-VL-32B,
MAI-UI-8B, GUI-Owl-1.5-32B}; both pools restricted to the 103 CLI-solvable
AndroidWorld tasks, with 13 GUI-only tasks excluded). Within a group, each
bar gives the prevalence of one TB leaf — the fraction of trajectories whose
primary or secondary cluster maps to that leaf; because a trajectory can
carry multiple co-occurring leaves, bars within a group need not sum to
100\%. Color encodes the top-level TB group (blue = Execution, red =
Coherence, orange = Verification); hatch distinguishes leaves within a
group. Four TB leaves (Unaware of Termination, Context Loss, Task
Derailment, No or Incorrect Verification) were 0\% in both paradigms and
are omitted.

**Headline reading:** the two paradigms share a single dominant failure
(Disobey Specification) but differ sharply in their secondary tails — CLI
agents fail by *acting on bad reasoning and then verifying through the
wrong channel* (RAM + Weak Verification), while GUI agents fail by
*looping on the same UI affordance and then declaring done without reading
the screen* (Step Repetition + Premature Termination).

---

## Headline findings

1. **Disobey Specification is the universal dominant failure mode.**
   87% prevalence in CLI,
   73% in GUI — the only TB leaf that
   is highly active in both paradigms. CLI disobeys at the *command* level
   (wrong DB surface, wrong API, wrong output bytes); GUI disobeys at the
   *gesture* level (wrong row, wrong menu path, wrong field type).

2. **Step Repetition is a GUI-only failure mode.** GUI agents hit
   53% Step Repetition; CLI agents have 0%.
   CLI's command-line surface gives syntactic feedback (quoting error,
   exception, "no such file") that breaks identical retries; GUI's silent
   no-op on a wrong-affordance tap gives no such signal.

3. **Reasoning-Action Mismatch is a CLI-only failure mode.** CLI:
   29%. GUI: 0% — confirmed by
   raw-trajectory audit of 65 GUI Disobey-Specification trajectories where
   every step's stated reasoning matched its action. GUI failures are
   upstream of execution; CLI failures often involve a reasoning-action
   divergence at the command-string level.

4. **Verification fails differently on each paradigm.** Every CLI agent
   has *some* verification failure, but almost always **Weak Verification**
   (53%, 0% in GUI) — verify-via-same-DB
   as the write. Every GUI agent has *some* verification failure, but
   almost always **Premature Termination**
   (57%, 8% in CLI) — `finish`
   without reading the screen. The two paradigms together activate the
   verification group ~60% of the time, but the *form* is entirely
   paradigm-determined.

5. **The Coherence group is silent in GUI.** Context Loss and Task
   Derailment are 0% in both paradigms; the only Coherence-group failure
   anywhere is CLI's RAM. GUI failures have *no* Coherence-group signal —
   the GUI agent's reasoning either matches its action and is wrong from
   the start (DS), or it acts without reasoning at all (PT, SR).

---

## Raw values (also in `fig1_paradigm_comparison.csv`)

| TB group | TB leaf | CLI (n=1,508) | GUI (n=194) |
|---|---|---:|---:|
| Execution | **Disobey Specification** | **87%** | **73%** |
| Execution | Step Repetition | 0% | **53%** |
| Execution | *Unaware of Termination* | 0% | 0% |
| Coherence | **Reasoning-Action Mismatch** | **29%** | 0% |
| Coherence | *Context Loss* | 0% | 0% |
| Coherence | *Task Derailment* | 0% | 0% |
| Verification | Premature Termination | 8% | **57%** |
| Verification | *No or Incorrect Verification* | 0% | 0% |
| Verification | **Weak Verification** | **53%** | 0% |

### Top co-occurrence pairs

| Pair | CLI | GUI |
|---|---:|---:|
| DS + Weak Verification | **41%** | — |
| DS + Reasoning-Action Mismatch | 19% | — |
| RAM + Weak Verification | 12% | — |
| DS + Premature Termination | 4% | **40%** |
| DS + Step Repetition | — | **35%** |
| Premature Termination + Step Repetition | — | 14% |
