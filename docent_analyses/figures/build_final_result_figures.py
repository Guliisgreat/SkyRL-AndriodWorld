#!/usr/bin/env python3
"""Build the final main-paper + appendix figure set.

Produces, into `../final_result_figures/`, four (pdf, png, csv, md) bundles:

  fig1_paradigm_comparison         — CLI vs GUI (main paper)
  fig2_variant_effect_leaf         — Codex bash_only vs bash_tool, TB-leaf
  figA1_model_x_harness            — model × harness compound (appendix)
  figA2_variant_effect_clusters    — Codex bash_only vs bash_tool, DS clusters

…plus a README.md manifest at the folder root.
"""
from __future__ import annotations
import csv
import json
import shutil
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from _render_lib import (
    GUI_ONLY_TASK_IDS, task_id_from_trajectory_id,
    load_cluster_to_leaf, load_labels, normalize_leaf,
)
from figure4_paradigm_tb_grouped import (
    LEAF_PLOT_ORDER, LEAF_GROUP, GROUP_COLOR, LEAF_HATCH,
    compute_prevalence as fig4_compute_prevalence,
    render as fig4_render,
)
from figure7_bash_only_vs_bash_tool import (
    compute_prevalence_for_variant,
    render as fig7_render,
    VARIANTS,
)
from figure6_model_vs_harness import (
    ACTIVE_LEAVES as FIG6_ACTIVE_LEAVES,
    MODEL_DISPLAY,
    collect_cells, render_compound,
)
from figure7_codex_composite import (
    compute_codex_data,
    DISPLAY_MERGES as FIG7_DISPLAY_MERGES,
    CLUSTER_DISPLAY_ALIAS as FIG7_ALIAS,
    COLOR_HELP, COLOR_HURT,
)

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "final_result_figures"
OUT.mkdir(exist_ok=True)

WS_CLI = ROOT.parent / "2026-05-21_android-cli-failures-combined"
WS_GUI = ROOT.parent / "2026-05-22_android-gui-failures"
CLI_LABELS = WS_CLI / "classification/cluster_labels_full.jsonl"
CLI_MAP    = WS_CLI / "consensus_mapping_v3.json"
GUI_LABELS = WS_GUI / "classification/cluster_labels.jsonl"
GUI_MAP    = WS_GUI / "consensus_mapping_gui.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def write_text(path: Path, text: str) -> None:
    path.write_text(text)
    print(f"  wrote {path.name}")


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
    print(f"  wrote {path.name}")


# ---------------------------------------------------------------------------
# fig1 — CLI vs GUI paradigm prevalence (figure 4)
# ---------------------------------------------------------------------------
def build_fig1():
    print("\n[fig1] CLI vs GUI paradigm prevalence")
    cli_c2l = load_cluster_to_leaf(CLI_MAP)
    gui_c2l = load_cluster_to_leaf(GUI_MAP)
    cli_n, cli_prev = fig4_compute_prevalence(CLI_LABELS, cli_c2l)
    gui_n, gui_prev = fig4_compute_prevalence(GUI_LABELS, gui_c2l)

    fig4_render(cli_n, cli_prev, gui_n, gui_prev,
                OUT / "fig1_paradigm_comparison.pdf",
                OUT / "fig1_paradigm_comparison.png",
                title="Cross-paradigm Comparison")

    # CSV — all leaves (including 0% leaves marked)
    rows = []
    for leaf in LEAF_PLOT_ORDER:
        rows.append(["CLI", cli_n, leaf, LEAF_GROUP.get(leaf, "-"),
                     f"{cli_prev.get(leaf, 0):.2f}"])
        rows.append(["GUI", gui_n, leaf, LEAF_GROUP.get(leaf, "-"),
                     f"{gui_prev.get(leaf, 0):.2f}"])
    write_csv(OUT / "fig1_paradigm_comparison.csv",
              ["paradigm", "n_failures", "tb_leaf", "tb_group", "prevalence_pct"],
              rows)

    md = f"""# fig1 — Paradigm Comparison: CLI vs GUI

**Paper placement:** **Main paper.**
**Figure file:** `fig1_paradigm_comparison.pdf` / `.png`
**Raw data:** `fig1_paradigm_comparison.csv`
**Source script:** `docent_analyses/figures/figure4_paradigm_tb_grouped.py`

---

## Caption (paper-ready)

**Figure 1. Failure-mode prevalence across TB leaves for CLI vs GUI agents.**
Each group corresponds to one paradigm on the fair-comparison subset of
AndroidWorld (CLI: {cli_n:,} trajectories from {{ClaudeCodeCLI, MiniSweAgent,
Terminus2}} × 5 models; GUI: {gui_n} trajectories from {{Qwen3-VL-32B,
MAI-UI-8B, GUI-Owl-1.5-32B}}; both pools restricted to the 103 CLI-solvable
AndroidWorld tasks, with 13 GUI-only tasks excluded). Within a group, each
bar gives the prevalence of one TB leaf — the fraction of trajectories whose
primary or secondary cluster maps to that leaf; because a trajectory can
carry multiple co-occurring leaves, bars within a group need not sum to
100\\%. Color encodes the top-level TB group (blue = Execution, red =
Coherence, orange = Verification); hatch distinguishes leaves within a
group. Four TB leaves (Unaware of Termination, Context Loss, Task
Derailment, No or Incorrect Verification) were 0\\% in both paradigms and
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
   {cli_prev['Disobey Specification']:.0f}% prevalence in CLI,
   {gui_prev['Disobey Specification']:.0f}% in GUI — the only TB leaf that
   is highly active in both paradigms. CLI disobeys at the *command* level
   (wrong DB surface, wrong API, wrong output bytes); GUI disobeys at the
   *gesture* level (wrong row, wrong menu path, wrong field type).

2. **Step Repetition is a GUI-only failure mode.** GUI agents hit
   {gui_prev['Step Repetition']:.0f}% Step Repetition; CLI agents have 0%.
   CLI's command-line surface gives syntactic feedback (quoting error,
   exception, "no such file") that breaks identical retries; GUI's silent
   no-op on a wrong-affordance tap gives no such signal.

3. **Reasoning-Action Mismatch is a CLI-only failure mode.** CLI:
   {cli_prev['Reasoning-Action Mismatch']:.0f}%. GUI: 0% — confirmed by
   raw-trajectory audit of 65 GUI Disobey-Specification trajectories where
   every step's stated reasoning matched its action. GUI failures are
   upstream of execution; CLI failures often involve a reasoning-action
   divergence at the command-string level.

4. **Verification fails differently on each paradigm.** Every CLI agent
   has *some* verification failure, but almost always **Weak Verification**
   ({cli_prev['Weak Verification']:.0f}%, 0% in GUI) — verify-via-same-DB
   as the write. Every GUI agent has *some* verification failure, but
   almost always **Premature Termination**
   ({gui_prev['Premature Termination']:.0f}%, {cli_prev['Premature Termination']:.0f}% in CLI) — `finish`
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

| TB group | TB leaf | CLI (n={cli_n:,}) | GUI (n={gui_n}) |
|---|---|---:|---:|
| Execution | **Disobey Specification** | **{cli_prev['Disobey Specification']:.0f}%** | **{gui_prev['Disobey Specification']:.0f}%** |
| Execution | Step Repetition | {cli_prev['Step Repetition']:.0f}% | **{gui_prev['Step Repetition']:.0f}%** |
| Execution | *Unaware of Termination* | 0% | 0% |
| Coherence | **Reasoning-Action Mismatch** | **{cli_prev['Reasoning-Action Mismatch']:.0f}%** | 0% |
| Coherence | *Context Loss* | 0% | 0% |
| Coherence | *Task Derailment* | 0% | 0% |
| Verification | Premature Termination | {cli_prev['Premature Termination']:.0f}% | **{gui_prev['Premature Termination']:.0f}%** |
| Verification | *No or Incorrect Verification* | 0% | 0% |
| Verification | **Weak Verification** | **{cli_prev['Weak Verification']:.0f}%** | 0% |

### Top co-occurrence pairs

| Pair | CLI | GUI |
|---|---:|---:|
| DS + Weak Verification | **41%** | — |
| DS + Reasoning-Action Mismatch | 19% | — |
| RAM + Weak Verification | 12% | — |
| DS + Premature Termination | 4% | **40%** |
| DS + Step Repetition | — | **35%** |
| Premature Termination + Step Repetition | — | 14% |
"""
    write_text(OUT / "fig1_paradigm_comparison.md", md)


# ---------------------------------------------------------------------------
# fig2 — Codex bash_only vs bash_tool, TB-leaf (panel a of composite)
# ---------------------------------------------------------------------------
def build_fig2():
    print("\n[fig2] Codex bash_only vs bash_tool — TB-leaf level")
    c2l = load_cluster_to_leaf(CLI_MAP)
    rows = load_labels(CLI_LABELS)
    accepted_apis = {"openaigpt53codex"}
    variant_data = []
    for v in VARIANTS:
        n, prev = compute_prevalence_for_variant(rows, v, c2l, accepted_apis)
        variant_data.append((v, n, prev))

    fig7_render(variant_data,
                OUT / "fig2_variant_effect_leaf.pdf",
                OUT / "fig2_variant_effect_leaf.png",
                title="CLI: Tool Effect")

    csv_rows = []
    for v, n, prev in variant_data:
        for leaf in LEAF_PLOT_ORDER:
            csv_rows.append([v, n, leaf, LEAF_GROUP.get(leaf, "-"),
                             f"{prev[leaf]:.2f}"])
    write_csv(OUT / "fig2_variant_effect_leaf.csv",
              ["variant", "n_failures", "tb_leaf", "tb_group", "prevalence_pct"],
              csv_rows)

    p_only = variant_data[0][2]
    p_tool = variant_data[1][2]
    n_only = variant_data[0][1]
    n_tool = variant_data[1][1]
    md = f"""# fig2 — Variant Effect (TB-leaf level): Codex bash_only vs bash_tool

**Paper placement:** **Main paper.**
**Figure file:** `fig2_variant_effect_leaf.pdf` / `.png`
**Raw data:** `fig2_variant_effect_leaf.csv`
**Source script:** `docent_analyses/figures/figure7_bash_only_vs_bash_tool.py`
**Companion (appendix):** `figA2_variant_effect_clusters.{{pdf,csv,md}}` — same
finding decomposed into Disobey-Specification sub-clusters.

---

## Caption (paper-ready)

**Figure 2. Effect of the bash-tool wrapper on GPT-5.3 Codex's failure
profile (TB-leaf level).** Two variant groups (bash\\_only: raw shell
strings emitted by the agent; bash\\_tool: structured JSON tool calls
unwrapped by the harness), each showing the prevalence of the four active
TB leaves. Both pools are restricted to GPT-5.3 Codex trajectories on the
fair-comparison subset ({n_only} bash\\_only failures, {n_tool} bash\\_tool
failures; 13 GUI-only AndroidWorld tasks excluded). Bars are TB-leaf
prevalence — a trajectory contributes to a bar if its primary or any
secondary cluster maps to that leaf. The five TB leaves not shown (Step
Repetition, Unaware of Termination, Context Loss, Task Derailment, No or
Incorrect Verification) were 0\\% in both variants.

**Headline reading:** the tool wrapper halves Codex's Premature
Termination (−{p_only['Premature Termination']-p_tool['Premature Termination']:.0f} pp) but raises
Reasoning-Action Mismatch (+{p_tool['Reasoning-Action Mismatch']-p_only['Reasoning-Action Mismatch']:.0f} pp) and
Weak Verification (+{p_tool['Weak Verification']-p_only['Weak Verification']:.0f} pp) by a similar
combined amount. Disobey Specification stays essentially flat
({p_only['Disobey Specification']:.0f}\\% → {p_tool['Disobey Specification']:.0f}\\%). The
wrapper does not reduce overall failure load; it *converts* one kind of
failure (cheap-exit) into another (tried-but-still-wrong). The mechanism
is unpacked at the sub-cluster level in Appendix Figure A2.

---

## Headline findings

1. **Premature Termination halves.** {p_only['Premature Termination']:.0f}% →
   {p_tool['Premature Termination']:.0f}%
   (Δ = −{p_only['Premature Termination']-p_tool['Premature Termination']:.0f} pp). The
   wrapper's structured-action contract makes it harder for Codex to call
   `finish` while the verifier has no readable state.

2. **Reasoning-Action Mismatch grows by ~12 pp.**
   {p_only['Reasoning-Action Mismatch']:.0f}% → {p_tool['Reasoning-Action Mismatch']:.0f}%. Trajectories
   that previously *quit* (PT) now *try* — but the tries are still wrong
   ("uncertainty-then-commit" guessed enums, dispatch-as-state-change).

3. **Weak Verification grows by ~9 pp.**
   {p_only['Weak Verification']:.0f}% → {p_tool['Weak Verification']:.0f}%. The wrapper
   also induces more "verify by re-reading the same surface I just wrote
   to" patterns — formal verification that doesn't cross-check.

4. **Disobey Specification is variant-invariant.**
   {p_only['Disobey Specification']:.0f}% → {p_tool['Disobey Specification']:.0f}%
   (Δ = {p_tool['Disobey Specification']-p_only['Disobey Specification']:+.0f} pp). The dominant
   failure mode does not budge — *what* Codex tries to do is set by the
   model; the wrapper only shapes *whether and how* it follows through.

5. **The PT shift is real reorganization, not absorption.** The
   ≈14 pp of PT-mass lost reappears as +12 pp RAM + +9 pp WV — i.e., the
   trajectories that used to quit early are now staying alive and
   migrating into other failure modes (this redistribution is mechanically
   explained at the cluster level in Figure A2).

---

## Raw values (also in `fig2_variant_effect_leaf.csv`)

| TB leaf | bash\\_only (n={n_only}) | bash\\_tool (n={n_tool}) | Δ pp |
|---|---:|---:|---:|
| **Disobey Specification** | {p_only['Disobey Specification']:.0f}% | {p_tool['Disobey Specification']:.0f}% | {p_tool['Disobey Specification']-p_only['Disobey Specification']:+.0f} |
| **Reasoning-Action Mismatch** | {p_only['Reasoning-Action Mismatch']:.0f}% | {p_tool['Reasoning-Action Mismatch']:.0f}% | {p_tool['Reasoning-Action Mismatch']-p_only['Reasoning-Action Mismatch']:+.0f} |
| **Premature Termination** | {p_only['Premature Termination']:.0f}% | {p_tool['Premature Termination']:.0f}% | {p_tool['Premature Termination']-p_only['Premature Termination']:+.0f} |
| **Weak Verification** | {p_only['Weak Verification']:.0f}% | {p_tool['Weak Verification']:.0f}% | {p_tool['Weak Verification']-p_only['Weak Verification']:+.0f} |

(All other TB leaves are 0% in both variants.)
"""
    write_text(OUT / "fig2_variant_effect_leaf.md", md)


# ---------------------------------------------------------------------------
# figA1 — model × harness compound (figure 6A)
# ---------------------------------------------------------------------------
def build_figA1():
    print("\n[figA1] Model × harness compound (figure 6A)")
    c2l = load_cluster_to_leaf(CLI_MAP)
    rows = load_labels(CLI_LABELS)
    cells = collect_cells(rows, c2l)
    render_compound(cells,
                    OUT / "figA1_model_x_harness.pdf",
                    OUT / "figA1_model_x_harness.png")

    csv_rows = []
    for m, h, n, prev in cells:
        for leaf in FIG6_ACTIVE_LEAVES:
            csv_rows.append([m, h, n, leaf, LEAF_GROUP[leaf],
                             f"{prev[leaf]:.2f}"])
    write_csv(OUT / "figA1_model_x_harness.csv",
              ["model", "harness", "n_failures", "tb_leaf", "tb_group",
               "prevalence_pct"],
              csv_rows)

    # Build a compact value table inline
    table_lines = ["| Model | Harness | n | DS | RAM | PT | WV |",
                   "|---|---|---:|---:|---:|---:|---:|"]
    for m, h, n, prev in cells:
        ds  = f"{prev['Disobey Specification']:.0f}%"
        ram = f"{prev['Reasoning-Action Mismatch']:.0f}%"
        pt  = f"{prev['Premature Termination']:.0f}%"
        wv  = f"{prev['Weak Verification']:.0f}%"
        table_lines.append(f"| {MODEL_DISPLAY[m]} | {h} | {n} | {ds} | {ram} | {pt} | {wv} |")
    inline_table = "\n".join(table_lines)

    md = f"""# figA1 — Model × Harness Compound (TB-leaf prevalence)

**Paper placement:** **Appendix.**
**Figure file:** `figA1_model_x_harness.pdf` / `.png`
**Raw data:** `figA1_model_x_harness.csv`
**Source script:** `docent_analyses/figures/figure6_model_vs_harness.py`

---

## Caption (paper-ready)

**Figure A1. Failure-mode prevalence in the CLI paradigm by model and
harness.** Each column corresponds to one (model × harness) cell on the
fair-comparison subset of AndroidWorld (1,508 failed trajectories across
103 CLI-solvable tasks; 13 GUI-only tasks excluded). Within a column, the
four bars give the prevalence of each TB leaf — the fraction of
trajectories whose primary or secondary cluster maps to that leaf; because
a trajectory can be labelled with multiple co-occurring leaves, bars within
a column need not sum to 100\\%. Columns are grouped by underlying LLM
(light grey bands; dotted lines separate models), and ordered within each
band by harness. The two empty Codex / MiniMax slots under ClaudeCodeCLI
reflect that ClaudeCodeCLI is a Claude-only harness. Color encodes the
top-level TB group (blue = Execution, red = Coherence, orange =
Verification); hatch distinguishes leaves within a group.

**Headline reading:** the dominant failure mode (Disobey Specification,
blue) is essentially constant across all cells, while each model carries a
distinctive *secondary signature* (Sonnet → RAM, Codex → PT, MiniMax → WV)
that survives harness swap — model identity explains more of the
cross-cell variance than harness choice.

---

## Headline findings

1. **Disobey Specification is paradigm-universal and harness-invariant.**
   The blue bar sits at 79–89\\% in every populated cell; 10-pp range
   across seven cells. DS is a baseline floor of CLI failure, not a knob
   the harness or model choice can move.

2. **Each model has a distinctive secondary signature.**
   - **Claude Sonnet 4.6** — tall red bar (RAM = 29–41\\%), tiny PT
     (1–5\\%). "Uncertainty-then-commit" dominates the tail.
   - **GPT-5.3 Codex** — only model with meaningful PT (17–24\\%, ≈10×
     higher than others). Code-trained "ship and finish" bias.
   - **MiniMax M2.7** — tallest WV bars in the whole figure (63–66\\%,
     ≥15 pp above any other cell). Writes-then-reads-same-surface.

3. **Model effect dominates harness effect.** Inside any model band, the
   bars keep their relative ordering and rough heights across harness
   columns. Between bands, the silhouettes are visibly different shapes —
   most obviously, the PT bar goes from invisible to ~24\\% and back. The
   model is the load-bearing variable; the harness perturbs it.

4. **Harness *does* shape the Sonnet tail, but not the others.** Sonnet's
   RAM drops monotonically with harness rigidity (ClaudeCodeCLI 41\\% →
   MSA 36\\% → Terminus2 29\\%) and Terminus2 also trims its WV (35\\% vs
   48–54\\%). For Codex the effect is smaller; for MiniMax the columns
   are near-identical (model dominates).

5. **PT vs WV trade off across models.** When PT is large (Codex), WV is
   moderate; when PT is tiny (MiniMax), WV explodes. Sonnet sits in the
   middle. Every model has *some* verification failure, but the *form* is
   model-specific.

---

## Raw values (also in `figA1_model_x_harness.csv`)

{inline_table}

(All other TB leaves are 0\\% in every cell.)
"""
    write_text(OUT / "figA1_model_x_harness.md", md)


# ---------------------------------------------------------------------------
# figA2 — Codex DS-cluster Δ-pp divergence (standalone, panel b of composite)
# ---------------------------------------------------------------------------
def build_figA2():
    print("\n[figA2] Codex DS-cluster Δ-pp divergence")
    c2l = load_cluster_to_leaf(CLI_MAP)
    _, ds_data = compute_codex_data(c2l)

    n_only = ds_data["bash_only"][0]
    n_tool = ds_data["bash_tool"][0]
    all_clusters = sorted(set(ds_data["bash_only"][1]) | set(ds_data["bash_tool"][1]))
    rows_data = []
    for c in all_clusters:
        a = ds_data["bash_only"][1][c] / max(n_only, 1) * 100
        b = ds_data["bash_tool"][1][c] / max(n_tool, 1) * 100
        rows_data.append((c, a, b, b - a))
    rows_data.sort(key=lambda r: r[3])

    # Render standalone divergence chart
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.labelcolor": "#222",
        "xtick.color": "#222",
        "ytick.color": "#222",
        "axes.edgecolor": "#444",
    })
    fig, ax_b = plt.subplots(figsize=(11.5, 5.8))
    n_rows = len(rows_data)
    bar_h = 0.6
    max_abs = max(abs(r[3]) for r in rows_data)
    label_x = max_abs * 1.05 + 1.0
    x_lim_right = label_x + 4.0
    x_lim_left  = max_abs * 1.2 + 0.5

    for i, (name, a, b, delta) in enumerate(rows_data):
        color = COLOR_HELP if delta < 0 else COLOR_HURT
        ax_b.barh(i, delta, height=bar_h, color=color,
                  edgecolor="#222", linewidth=0.6, zorder=3)
        sign = "+" if delta > 0 else "−" if delta < 0 else "±"
        txt = f"{sign}{abs(delta):.1f} pp"
        offset = 0.4 if delta >= 0 else -0.4
        ha = "left" if delta >= 0 else "right"
        ax_b.text(delta + offset, i, txt, ha=ha, va="center",
                  fontsize=9, color="#222", zorder=4)
        ax_b.text(label_x, i, f"{a:.0f}% → {b:.0f}%",
                  ha="left", va="center", fontsize=9,
                  color="#666", style="italic", zorder=4)

    def pretty(name):
        marker = " ◇" if name in FIG7_DISPLAY_MERGES else ""
        return name.replace("_", " ") + marker

    ax_b.set_yticks(range(n_rows))
    ax_b.set_yticklabels([pretty(r[0]) for r in rows_data], fontsize=10.5)
    ax_b.tick_params(axis="y", length=0, pad=4)
    ax_b.invert_yaxis()

    ax_b.axvline(0, color="#444", linewidth=0.8, zorder=2)
    ax_b.set_xlim(-x_lim_left, x_lim_right)
    tick_max = int((max_abs // 5 + 1) * 5)
    ticks = list(range(-tick_max, tick_max + 1, 5))
    ax_b.set_xticks(ticks)
    ax_b.set_xticklabels([f"{t:+d}" if t != 0 else "0" for t in ticks])
    ax_b.set_xlabel("Δ prevalence under bash_tool (percentage points)",
                    fontsize=11)
    ax_b.tick_params(axis="x", length=0, labelsize=10)
    ax_b.grid(axis="x", alpha=0.3, linestyle=(0, (4, 4)), linewidth=0.6,
              color="#999", zorder=1)
    ax_b.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax_b.spines[s].set_visible(False)
    ax_b.spines["bottom"].set_color("#444")
    ax_b.spines["bottom"].set_linewidth(0.8)

    # Direction header & right-margin column header
    ax_b.text(-x_lim_left * 0.55, -0.9, "← bash_tool helps (fewer failures)",
              ha="center", va="bottom", fontsize=9.5,
              color=COLOR_HELP, fontweight="semibold")
    ax_b.text(+max_abs * 0.45, -0.9, "bash_tool hurts / no benefit →",
              ha="center", va="bottom", fontsize=9.5,
              color=COLOR_HURT, fontweight="semibold")
    ax_b.text(label_x, -0.9, "bash_only → bash_tool",
              ha="left", va="bottom", fontsize=9,
              color="#666", style="italic")

    fig.tight_layout()
    out_pdf = OUT / "figA2_variant_effect_clusters.pdf"
    out_png = OUT / "figA2_variant_effect_clusters.png"
    fig.savefig(out_pdf, format="pdf", bbox_inches="tight")
    fig.savefig(out_png, format="png", dpi=200, bbox_inches="tight")
    print(f"  wrote {out_pdf.name}, {out_png.name}")

    # CSV
    csv_rows = []
    for name, a, b, delta in rows_data:
        csv_rows.append([name, n_only, f"{a:.2f}", n_tool, f"{b:.2f}", f"{delta:+.2f}"])
    write_csv(OUT / "figA2_variant_effect_clusters.csv",
              ["ds_cluster", "n_bash_only", "bash_only_pct",
               "n_bash_tool", "bash_tool_pct", "delta_pp"],
              csv_rows)

    # Build the markdown table from the actual data so it stays in sync
    table_lines = [
        "| DS sub-cluster | bash\\_only | bash\\_tool | Δ pp |",
        "|---|---:|---:|---:|",
    ]
    for name, a, b, delta in rows_data:
        marker = " ◇" if name in FIG7_DISPLAY_MERGES else ""
        sign = "+" if delta > 0 else "−" if delta < 0 else "±"
        table_lines.append(
            f"| `{name}`{marker} | {a:.1f}% | {b:.1f}% | {sign}{abs(delta):.1f} |"
        )
    inline_table = "\n".join(table_lines)

    # Counts for the narrative
    helps = [r for r in rows_data if r[3] < 0]
    hurts = [r for r in rows_data if r[3] > 0]
    helps_total = -sum(r[3] for r in helps)
    hurts_total = sum(r[3] for r in hurts)

    md = f"""# figA2 — Variant Effect (DS-cluster level): Codex bash_only vs bash_tool

**Paper placement:** **Appendix.** Companion to main-paper **Figure 2**;
unpacks the Disobey-Specification leaf into its sub-clusters and shows
where the wrapper's effect comes from.
**Figure file:** `figA2_variant_effect_clusters.pdf` / `.png`
**Raw data:** `figA2_variant_effect_clusters.csv`
**Source script:** `docent_analyses/figures/figure7_codex_composite.py`
(panel b extracted as a standalone figure)

---

## Caption (paper-ready)

**Figure A2. Disobey-Specification sub-cluster shifts under the bash-tool
wrapper (GPT-5.3 Codex).** Each row is one DS sub-cluster; bar length is
the change in cluster prevalence when moving from bash\\_only ({n_only}
failures) to bash\\_tool ({n_tool} failures), both restricted to GPT-5.3
Codex on the fair-comparison subset (13 GUI-only AndroidWorld tasks
excluded). Blue bars (top of chart) are clusters the wrapper shrinks
(helps); orange bars (bottom) are clusters the wrapper grows. The italic
column on the right gives the absolute prevalence pair
(bash\\_only → bash\\_tool) for context. The diamond marker (◇) flags
display-merged clusters (see Methods / taxonomy.md). The cluster
`agent_concluded_no_cli_pathway` is the presentation-layer rename of the
original Phase-2 label `task_required_gui_only_no_cli_pathway`; it
captures the agent's *false-impossibility conclusion* (not a task
property — every fair-view occurrence is on a CLI-solvable task).

**Headline reading:** the wrapper acts asymmetrically inside Disobey
Specification — it dampens four "cheap-exit" failure modes by a combined
−{helps_total:.0f} pp while only slightly growing failures that involve
*more aggressive engagement* with blocked or wrong-value surfaces
(+{hurts_total:.0f} pp). Disobey Specification's leaf-level prevalence
stays flat (Figure 2) precisely because these two sets of clusters
partially cancel; the wrapper's real effect is to **raise Codex's
engagement floor**, not to fix the dominant failure leaf.

---

## Headline findings

1. **Four cheap-exit clusters shrink under bash_tool**
   (combined −{helps_total:.0f} pp). The wrapper makes Codex less likely
   to quit, fabricate, or take destructive shortcuts:
   - `agent_concluded_no_cli_pathway`: 10\\% → 3\\% (−6.3 pp) — agent gives
     up less often on tasks that *do* have a shell pathway.
   - `truncated_input_treated_as_complete`: 8\\% → 4\\% (−3.3 pp) — better
     handling of large/paged tool output.
   - `fabricated_artifact_instead_of_invoking_app_pipeline`: 14\\% → 11\\%
     (−2.9 pp) — harder to disguise hand-crafted bytes as captured.
   - `pm_clear_or_destructive_blanket_action`: 3\\% → 1\\% (−2.4 pp) —
     structured calls discourage `pm clear` / `rm -rf` shortcuts.

2. **The deepest cluster is variant-invariant.**
   `wrote_to_wrong_database_surface` sits at ~40\\% in both variants
   (+0.8 pp). The model's "which surface should I write to" decision is
   not influenced by the action contract — it's a planning-level error.

3. **One cluster genuinely grows under bash_tool.**
   `permission_or_role_blocked_clipboard_or_sms`: 14\\% → 18\\%
   (+4.9 pp). Codex attempts blocked operations *more* under the wrapper
   — plausibly because the structured-output channel makes
   SecurityException-Parcel artifacts easier for the model to misread as
   "empty result" and retry.

4. **Two "engagement" clusters grow modestly** (+2–3 pp each).
   `wrong_output_value_at_correct_surface` (+2.4 pp) and
   `apk_static_analysis_loop_without_db_write` (+2.2 pp) both reflect
   Codex *staying alive longer* — reaching the right surface, then
   getting the value wrong; or running longer recon sessions.

5. **The asymmetry confirms the engagement-floor framing.** The
   wrapper does not improve Codex's correctness — DS stays flat — but it
   redirects ≈{helps_total:.0f} pp of cheap-exit mass into trajectories
   that *try harder*. Some of those tries land on a blocked surface
   (cluster #3 above); others get the right surface but the wrong value
   (#4). The net effect on the leaf-level numbers (Figure 2) is
   reorganization, not reduction.

---

## Raw values (also in `figA2_variant_effect_clusters.csv`)

{inline_table}

◇ = display-merged cluster (see Methods / `taxonomy.md`).
The cluster `agent_concluded_no_cli_pathway` is a presentation-layer
rename of the Phase-2 label `task_required_gui_only_no_cli_pathway`;
raw classification JSONL retains the original name for provenance.
"""
    write_text(OUT / "figA2_variant_effect_clusters.md", md)


# ---------------------------------------------------------------------------
# README — manifest
# ---------------------------------------------------------------------------
def build_readme():
    print("\n[README] Manifest")
    md = """# Final result figures

Four figures destined for the main paper (Fig 1, Fig 2) and the appendix
(Fig A1, Fig A2), each shipped as a `.pdf` (LaTeX-ready) + `.png` (preview)
bundle alongside its raw data CSV and a markdown writeup with the caption,
headline findings, and an inline table copy of the values.

This folder is regenerated by
`docent_analyses/figures/build_final_result_figures.py` — re-run that
script to refresh everything in one pass.

## Manifest

| File stem | Placement | One-line summary |
|---|---|---|
| `fig1_paradigm_comparison` | **Main paper** | TB-leaf failure prevalence across CLI vs GUI paradigms (fair view). Shows DS is universal; secondary tails are paradigm-specific (CLI = RAM + WV, GUI = SR + PT). |
| `fig2_variant_effect_leaf` | **Main paper** | TB-leaf prevalence for GPT-5.3 Codex under bash\\_only vs bash\\_tool. Wrapper halves PT (−14 pp) but grows RAM + WV by ~21 pp combined; DS flat. |
| `figA1_model_x_harness` | **Appendix** | Compound-grouped bars for (model × harness) cells in the CLI paradigm. Shows model identity dominates harness for the secondary failure signature. |
| `figA2_variant_effect_clusters` | **Appendix** | DS-cluster Δ-pp divergence for Codex bash\\_only → bash\\_tool. Companion to Fig 2 — unpacks where the wrapper's effect comes from inside DS. |

## File layout per figure

For each `<stem>` above:

- `<stem>.pdf` — vector graphic, drop into LaTeX with `\\includegraphics`.
- `<stem>.png` — raster preview (200 dpi).
- `<stem>.csv` — long-format raw data, one row per (group, bar/cluster).
- `<stem>.md` — caption (paper-ready) + headline findings + inline values
  table + cross-references.

## How to use during paper writing

For each figure:

1. **Caption** — copy from the `.md`'s "Caption" section into the
   `\\caption{}` of the corresponding LaTeX figure. The captions are
   already paper-voice (no "we will show", no first person).
2. **Results-section narrative** — the "Headline findings" bullets in
   each `.md` are written so they can be paraphrased almost directly into
   the body of the results section.
3. **Numbers in the prose** — quote the values from the inline markdown
   table or the `.csv`. They agree.

## Provenance

All four figures are computed on the **fair-comparison subset** of
AndroidWorld (103 CLI-solvable tasks per the ground-truth reference; 13
GUI-only tasks excluded from both paradigms). Prevalence is computed
across both the primary cluster and the secondary clusters of each
trajectory, so bars within a group are *not* mutually exclusive shares
(this is the Terminal-Bench convention).

Full taxonomy and Phase 1/2/3 details are in
`docent_analyses/figures/taxonomy.md`.
"""
    write_text(OUT / "README.md", md)


def main():
    build_fig1()
    build_fig2()
    build_figA1()
    build_figA2()
    build_readme()
    print(f"\nAll done. Output folder: {OUT}")
    print("Files:")
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
