# Figure 4 — Cross-Paradigm Failure-Mode Prevalence: CLI vs GUI

**Files**

- `figure4_paradigm_tb_grouped.pdf` / `.png` — the figure
- `figure4_data.csv` — long-format prevalence data (2 paradigms × 9 leaves)
- `figure4_paradigm_tb_grouped.py` — render script

---

## Caption (paper-style)

**Figure 4. Failure-mode prevalence across TB leaves for CLI vs GUI agents.**
Each group corresponds to one paradigm on the fair-comparison subset of
AndroidWorld (CLI: 1,508 trajectories from {ClaudeCodeCLI, MiniSweAgent,
Terminus2} × 5 models; GUI: 194 trajectories from {Qwen3-VL-32B, MAI-UI-8B,
GUI-Owl-1.5-32B}; both pools restricted to the 103 CLI-solvable AndroidWorld
tasks, with 13 GUI-only tasks excluded). Within a group, each bar gives the
prevalence of one TB leaf — the fraction of trajectories whose primary or
secondary cluster maps to that leaf; because a trajectory can carry multiple
co-occurring leaves, bars within a group need not sum to 100%. Color encodes
the top-level TB group (blue = Execution, red = Coherence, orange =
Verification); hatch distinguishes individual leaves within a group. Four TB
leaves (Unaware of Termination, Context Loss, Task Derailment, No or
Incorrect Verification) were 0% in both paradigms and are omitted from the
legend.

**Headline reading:** the two paradigms share a single dominant failure
(Disobey Specification) but differ sharply in their secondary tails — CLI
agents fail by *acting on bad reasoning and then verifying through the wrong
channel* (RAM + Weak Verification), while GUI agents fail by *looping on
the same UI affordance and then declaring done without reading the screen*
(Step Repetition + Premature Termination). The CLI/GUI difference is not a
matter of "more vs less" failure of the same kind, but of categorically
different secondary failure modes activated on each side.

---

## Findings

### 1. Disobey Specification is the universal dominant failure mode

DS reaches 87% in CLI and 73% in GUI — the only TB leaf that is highly active
in both paradigms. The CLI agent disobeys at the **command** level (wrong DB
surface, wrong API, wrong output bytes); the GUI agent disobeys at the
**gesture** level (wrong row, wrong menu path, wrong field type). The leaf is
the same; the realisation is paradigm-specific.

### 2. Step Repetition is a GUI-only failure mode

GUI agents hit 53% Step Repetition prevalence (≥20 byte-identical actions or
fixed-coordinate macros on a reflowing UI); CLI agents have 0%. This is the
clearest paradigm divider in the figure. The CLI's command-line surface gives
syntactic feedback — a quoting error, a 'no such file', a SQL exception —
that *breaks* identical retries. The GUI's silent no-op on a wrong-affordance
tap gives no such signal, so the model loops.

### 3. Reasoning-Action Mismatch is a CLI-only failure mode

CLI shows 29% RAM (uncertainty-then-commit on enum mappings,
dispatch-as-state-change, declared-method-vs-used). GUI shows 0% RAM —
confirmed by the raw-trajectory audit of 65 GUI Disobey-Specification
trajectories where every step's stated reasoning matched its action. GUI
failures are upstream of execution; CLI failures often involve a
reasoning-action divergence at the command-string level.

### 4. Weak Verification is a CLI-only failure mode

CLI: 53%. GUI: 0%. The "verify by re-reading the same surface you wrote to"
pattern is *only* available to a CLI agent that has access to multiple read
APIs (sqlite SELECT after INSERT, `settings get` after `settings put`). A GUI
agent doesn't have that affordance — its only verification surface is the
rendered screen — so its failure mode is *not verifying at all* (see #5),
not *verifying through the wrong channel*.

### 5. Premature Termination dominates GUI verification failures

GUI: 57%. CLI: 8%. GUI agents typically declare complete one step after
`open_app`, after filling a dialog without tapping OK, or after creating only
1 of N required items. CLI agents almost always do *some* read, even if
through the wrong surface — that read absorbs the failure into WV rather
than PT.

### 6. Verification fails differently on each paradigm

This is the cleanest **categorical** finding of the figure: every CLI agent
has *some* verification failure, but it is almost always Weak Verification;
every GUI agent has *some* verification failure, but it is almost always
Premature Termination. The two paradigms together activate the verification
group ~60% of the time, but the *form* is entirely paradigm-determined.

### 7. The Coherence group is absent everywhere except CLI-RAM

Context Loss and Task Derailment are at 0% in both paradigms. Combined with
RAM being CLI-only, this means GUI failures have **no Coherence-group
signal at all** — the GUI agent's reasoning either matches its action and is
wrong from the start (DS), or it acts without reasoning at all (PT, SR). The
"agent's mental model drifts mid-trajectory" pattern that Coherence captures
in coding agents (per TB) doesn't show up in either Android-CLI or
Android-GUI in our data.

### 8. Five of the nine TB leaves are silent in this benchmark

Unaware of Termination, Context Loss, Task Derailment, and No or Incorrect
Verification are at 0% in *both* paradigms. Step Repetition is at 0% in CLI.
This narrow active set (5 of 9) is itself a finding: AndroidWorld's failure
surface is more concentrated than the Terminal-Bench paper's coding
benchmark, where all 9 leaves activate. The benchmark exercises specific
failure modes (DS-heavy, paradigm-specific tails) rather than the full
Coherence/Termination spectrum.

---

## Caveat

Prevalence allows multi-leaf assignment per trajectory (CLI mean = 1.77
leaves/trajectory, GUI mean = 1.83 leaves/trajectory), so bar heights are
*not* mutually exclusive shares — they are the fraction of trajectories
whose failure profile *includes* that leaf as primary or secondary. A
primary-only stacked view (Figure 3) gives the orthogonal "what was the
single dominant cause" reading. Both views agree on the ordering of
paradigm-dominant tails, but only the prevalence view exposes the
co-occurrence pattern (e.g. CLI's 41% DS + WV pair-up, GUI's 40% DS + PT
pair-up).

---

## Raw values plotted

Fair-view prevalence (% trajectories where primary or secondary cluster maps
to that TB leaf):

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

Top co-occurring pairs (% of fair-view trajectories):

| Pair | CLI | GUI |
|---|---:|---:|
| DS + Weak Verification | **41%** | — |
| DS + Reasoning-Action Mismatch | 19% | — |
| RAM + Weak Verification | 12% | — |
| DS + Premature Termination | 4% | **40%** |
| DS + Step Repetition | — | **35%** |
| Premature Termination + Step Repetition | — | 14% |

(All figures from `figure4_data.csv`; full per-cluster mapping in
`taxonomy.md`.)
