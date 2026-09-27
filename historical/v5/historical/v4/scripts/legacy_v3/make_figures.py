"""Render six publication figures from the sanitized, validated public tables.

No selector, graph loader, record identity, reference mapping or score array is
read here. Source tables and every plotted projection are retained with hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
METHODS = ("edge_betweenness", "cut_plan_fixed", "cut_plan_fixed_singleton")
LABELS = {METHODS[0]: "Weighted BC", METHODS[1]: "Raw", METHODS[2]: "Singleton"}
SHORT = {METHODS[0]: "BC", METHODS[1]: "Raw", METHODS[2]: "Single"}
COLORS = {METHODS[0]: "#0072B2", METHODS[1]: "#D55E00", METHODS[2]: "#009E73"}
MARKERS = {METHODS[0]: "o", METHODS[1]: "s", METHODS[2]: "^"}
STYLES = {METHODS[0]: "-", METHODS[1]: "--", METHODS[2]: ":"}
DATASETS = ("wdc", "dblp_acm")
TITLES = {"wdc": "WDC", "dblp_acm": "DBLP–ACM"}
BUDGETS = (12, 24, 48)
CATEGORIES = ("paid_positive", "negative_no_split", "negative_split")
EVENT_COLORS = ("#B7C1CC", "#E69F00", "#0072B2")
WIDTH = 4.8


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def select(rows, **filters):
    return [r for r in rows if all(r.get(k) == v for k, v in filters.items())]


def singleton(rows, **filters):
    hits = select(rows, **filters)
    if len(hits) != 1:
        raise ValueError(f"Expected one row for {filters}, found {len(hits)}")
    return hits[0]


def depth_projection(rows):
    """One candidate/batch occurrence is counted once, never once per paid edge."""
    output = []
    for method in METHODS[1:]:
        for dataset in DATASETS:
            for budget in BUDGETS:
                for stage in ("generated", "capped", "scored", "selected"):
                    cells = select(rows, method=method, dataset=dataset, budget=budget, stage=stage)
                    if len(cells) != 4 or {r["depth"] for r in cells} != {1, 2, 3, 4}:
                        raise ValueError("Every depth projection needs exactly depths 1 to 4")
                    total = sum(r["count"] for r in cells)
                    multi = sum(r["count"] for r in cells if r["depth"] > 1)
                    output.append({"dataset": dataset, "method": method, "budget": budget,
                                   "stage": stage, "multi_count": multi, "total": total,
                                   "multi_fraction": multi / total if total else None,
                                   "denominator": "committed batch actions" if stage == "selected"
                                   else "candidate occurrences, accumulated once per selection"})
    return output


def setup_style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8,
                         "axes.titlesize": 8.5, "axes.labelsize": 8,
                         "xtick.labelsize": 8, "ytick.labelsize": 8,
                         "legend.fontsize": 8, "legend.frameon": False,
                         "pdf.fonttype": 42, "ps.fonttype": 42,
                         "svg.fonttype": "none", "svg.hashsalt": "cut-audit-er-v3",
                         "figure.facecolor": "white", "axes.facecolor": "white",
                         "savefig.facecolor": "white", "axes.spines.top": False,
                         "axes.spines.right": False, "axes.linewidth": .65,
                         "lines.linewidth": 1.25, "axes.axisbelow": True})


def method_legend(fig, y=.995):
    handles = [Line2D([], [], color=COLORS[m], marker=MARKERS[m], linestyle=STYLES[m],
                      label=LABELS[m], markerfacecolor="white" if m == METHODS[2] else COLORS[m],
                      markersize=4) for m in METHODS]
    fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(.5, y),
               columnspacing=1.0, handlelength=1.6)


def save(fig, out, name, projection, sources, note):
    """Keep a fixed 12.2 cm width; tight cropping must not silently shrink type."""
    fig.canvas.draw()
    small = [t.get_fontsize() for t in fig.findobj(matplotlib.text.Text)
             if t.get_text() and t.get_visible() and t.get_fontsize() < 8]
    if small:
        raise ValueError(f"Figure {name} has text smaller than 8 pt")
    for suffix in ("pdf", "svg", "png"):
        metadata = {"Creator": "CUT-AUDIT-ER public figure renderer"}
        if suffix == "pdf":
            metadata.update(CreationDate=None, ModDate=None)
        elif suffix == "svg":
            metadata = {"Creator": "CUT-AUDIT-ER public figure renderer", "Date": None}
        else:
            metadata = {"Software": "CUT-AUDIT-ER public figure renderer"}
        fig.savefig(out / f"{name}.{suffix}", dpi=300, metadata=metadata)
    data_path = out / "data" / f"{name}.json"
    data_path.write_text(json.dumps({"figure": name, "scope": note, "sources": sources,
                                     "data": projection}, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    result = {"name": name, "width_inches": float(fig.get_figwidth()),
              "height_inches": float(fig.get_figheight()), "minimum_font_pt": 8,
              "scope": note, "sources": sources,
              "files_sha256": {f"{name}.{s}": digest(out / f"{name}.{s}")
                               for s in ("pdf", "svg", "png")},
              "data_sha256": digest(data_path)}
    plt.close(fig)
    return result


def contract_figure():
    fig = plt.figure(figsize=(WIDTH, 2.45))
    ax = fig.add_axes([.015, .125, .97, .85]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.text(.01, .98, "(a) A negative answer need not change the partition", va="top", weight="bold")
    for i, label in enumerate(("Initial graph", "One negative removed", "Both negatives removed")):
        center = .16 + i * .335
        positions = [(center-.09, .78), (center-.09, .59), (center+.09, .78), (center+.09, .59)]
        for u, v in ((0, 1), (2, 3)):
            ax.plot(*zip(positions[u], positions[v]), color="#555555", lw=1.5, zorder=1)
        for j, (u, v) in enumerate(((0, 2), (1, 3))):
            deleted = j < i
            ax.plot(*zip(positions[u], positions[v]), color="#D55E00", lw=1.4,
                    linestyle="--" if deleted else "-", alpha=.30 if deleted else 1, zorder=1)
        ax.scatter(*zip(*positions), c=["#C4DEEF"]*2+["#DDE9BB"]*2,
                   s=130, edgecolors="#333333", linewidths=.7, zorder=3)
        ax.text(center, .875, label, ha="center")
        ax.text(center, .485, ("One component", "Still one component", "Two components")[i], ha="center")
    ax.text(.01, .395, "(b) Shared generation; restriction only after the common cap", weight="bold")
    boxes = [(.01, .16, .27, .16, "Generate depth ≤ 4"),
             (.335, .16, .19, .16, "Cap = 64"),
             (.585, .255, .405, .10, "Raw: all retained widths"),
             (.585, .085, .405, .10, "Singleton: retain width 1")]
    for x, y, w, h, label in boxes:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=.008", lw=.65,
                                   edgecolor="#6F7883", facecolor="#F4F6F8"))
        ax.text(x+w/2, y+h/2, label, ha="center", va="center")
    for start, end in (((.282, .24), (.328, .24)), ((.53, .24), (.58, .303)), ((.53, .24), (.58, .137))):
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=9, lw=.75, color="#475569"))
    fig.text(.025,.08,"Positive answer: pay 1; keep the edge; remove it from query eligibility.")
    fig.text(.025,.02,"Illustrative schematic. Gold is confined to the offline oracle and diagnostics.")
    return fig, {"kind": "illustrative schematic, not measured data", "shared_depth_cap": 4,
                 "shared_candidate_cap": 64, "singleton_filter_order": "after common cap",
                 "positive_answer": "one paid query, edge retained, becomes ineligible",
                 "gold_enters_selector": False}


def structure_figure(data):
    fig, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.55))
    fig.subplots_adjust(left=.12, right=.97, bottom=.25, top=.78, wspace=.50)
    ax = axes[0]
    for i, dataset in enumerate(DATASETS):
        row = singleton(data["coverage"], dataset=dataset)
        x1, x2 = 100*row["component_fraction"], 100*row["fp_fraction"]
        ax.plot([x1, x2], [i-.07, i+.07], color="#999999", lw=1)
        ax.scatter(x1, i-.07, color="#0072B2", s=40, zorder=3)
        ax.scatter(x2, i+.07, facecolors="white", edgecolors="#D55E00", marker="s", s=40, zorder=4)
        ax.annotate(f'{row["exact_components"]}/{row["components"]} CCs', (x1, i-.07),
                    xytext=(-1, 13), textcoords="offset points", ha="right")
        ax.annotate(f'{row["covered_fp"]}/{row["initial_fp"]:,} FP', (x2, i+.07),
                    xytext=(0, -16), textcoords="offset points", ha="left" if x2 < 50 else "right")
    ax.set_yticks([0, 1], ["WDC", "DBLP"]); ax.set_ylim(1.55, -.55)
    ax.set_xlim(-5, 105); ax.set_xticks([0, 50, 100]); ax.set_xlabel("Exact-solved coverage (%)")
    ax.set_title("(a) Components ≠ error mass", pad=24)
    ax.grid(axis="x", alpha=.18)
    ax.legend(handles=[Line2D([], [], marker="o", color="#0072B2", linestyle="", label="Components"),
                       Line2D([], [], marker="s", markerfacecolor="white", color="#D55E00", linestyle="", label="FP mass")],
              loc="upper center", bbox_to_anchor=(.5, 1.27), ncol=2, columnspacing=.7, handletextpad=.2)
    ax = axes[1]; curve = sorted(data["bound_curve"], key=lambda r:r["budget"])
    exact = [r for r in curve if r["status"] == "exact"]
    ax.step([r["budget"] for r in exact], [r["exact_loss"] for r in exact], where="post", color="#663399")
    floor = exact[-1]["exact_fn"]
    ax.axhline(floor, color="#6B7280", linestyle=":", lw=1)
    ax.set_xlim(0, 48); ax.set_xticks([0, 12, 24, 48]); ax.set_ylim(17, 36); ax.set_yticks([19, 24, 29, 34])
    ax.set_xlabel("Deletion budget (gold known)"); ax.set_ylabel("Clairvoyant minimum FP + FN", labelpad=2)
    ax.set_title("(b) DBLP–ACM exact bound", pad=24)
    ax.text(.40, .16, f"FN floor = {floor}", transform=ax.transAxes)
    ax.grid(alpha=.15)
    fig.text(.5, .03, "WDC whole-graph optimum: incomplete. DBLP additional FN headroom: 0.", ha="center")
    return fig, {"coverage": data["coverage"], "curve": curve}


def outcomes_figure(data):
    fig, axes = plt.subplots(2, 2, figsize=(WIDTH, 3.95), gridspec_kw={"height_ratios": [1.15, 1]})
    fig.subplots_adjust(left=.14, right=.97, bottom=.17, top=.86, hspace=.62, wspace=.50)
    method_legend(fig)
    for j, dataset in enumerate(DATASETS):
        ax = axes[0, j]
        for method in METHODS:
            rows = [singleton(data["endpoints"], dataset=dataset, method=method, budget=b) for b in BUDGETS]
            ax.plot(BUDGETS, [r["loss"] for r in rows], color=COLORS[method], marker=MARKERS[method],
                    linestyle=STYLES[method], markersize=5 if method == METHODS[2] else 4,
                    markerfacecolor="white" if method == METHODS[2] else COLORS[method])
        ax.set_title(f'({"ab"[j]}) {TITLES[dataset]} endpoints')
        ax.set_xticks(BUDGETS); ax.set_xlabel("Requested budget"); ax.grid(alpha=.16)
        if j == 0:
            ax.set_ylabel("FP + FN"); ax.ticklabel_format(axis="y", style="plain")
            ax.set_yticks([16000, 28000, 40000], ["16,000", "28,000", "40,000"])
        else:
            ax.set_ylim(27, 34); ax.set_yticks([28, 30, 32, 34])
        ax = axes[1, j]; ax.axvline(0, color="#777777", lw=.8)
        for i, budget in enumerate(BUDGETS):
            for comparison, offset, color, mark in (("raw_minus_singleton", -.14, "#009E73", "D"),
                                                     ("raw_minus_bc", .14, "#0072B2", "o")):
                row = singleton(data["contrasts"], dataset=dataset, budget=budget, comparison=comparison)
                value = row["loss_difference"]
                ax.plot([0, value], [i+offset]*2, color=color, lw=1)
                ax.scatter(value, i+offset, marker=mark, c=color, s=20, zorder=3)
                ax.annotate(f"{value:+,}" if value else "0", (value, i+offset),
                            xytext=(-4 if value<0 else 4, 0), textcoords="offset points",
                            ha="right" if value<0 else "left", va="center")
        ax.set_yticks(range(3), ["B12", "B24", "B48"]); ax.set_ylim(2.55, -.5)
        ax.set_title(f'({"cd"[j]}) Raw loss differences', pad=5)
        ax.set_xlabel("← Raw better     Raw worse →")
        if dataset == "wdc":
            ax.set_xlim(-19800, 9500); ax.set_xticks([-12000, 0], ["−12,000", "0"])
        else:
            ax.set_xlim(-1.5, 7); ax.set_xticks([0, 4])
    fig.text(.5, .049, "Differences:  ◆ Raw − singleton      ● Raw − BC", ha="center")
    tradeoff=singleton(data["contrasts"],dataset="wdc",budget=48,comparison="raw_minus_singleton")
    fig.text(.5,.012,f'WDC B48 raw − singleton: FP {tradeoff["fp_difference"]:+,}; FN {tradeoff["fn_difference"]:+,}.',ha="center")
    return fig, {"endpoints": data["endpoints"], "contrasts": data["contrasts"]}


def events_figure(data):
    fig, axes = plt.subplots(3, 2, figsize=(WIDTH, 4.65), gridspec_kw={"height_ratios": [.60, 1, .8]})
    fig.subplots_adjust(left=.145, right=.98, bottom=.095, top=.84, hspace=.90, wspace=.42)
    legend = [Rectangle((0, 0), 1, 1, facecolor=c, label=l) for c, l in zip(EVENT_COLORS,
               ("Positive", "Negative: no split", "Negative: split"))]
    fig.legend(handles=legend, ncol=3, loc="upper center", bbox_to_anchor=(.5, 1.0),
               columnspacing=.8, handlelength=.8, handletextpad=.35)
    method_legend(fig, y=.944)
    projection = []
    for j, budget in enumerate((24, 48)):
        top = axes[0, j]
        for i, method in enumerate(METHODS):
            events = sorted(select(data["events"], dataset="wdc", method=method, budget=budget), key=lambda r:r["spent"])
            for row in events:
                top.add_patch(Rectangle((row["spent"]-.5, i-.32), 1, .64,
                                       facecolor=EVENT_COLORS[CATEGORIES.index(row["category"])], lw=0))
            for row in select(data["batches"], dataset="wdc", method=method, budget=budget):
                count = row.get("recorded_physical_queries", row.get("paid_count"))
                if count and count > 1:
                    start = row["spent_before"]+.5
                    top.add_patch(Rectangle((start, i-.39), count, .78, fill=False, lw=.8, edgecolor="#333333"))
            states = sorted(select(data["states"], dataset="wdc", method=method, budget=budget), key=lambda r:r["spent"])
            initial = states[0]
            for ax, field, direction in ((axes[1, j], "fp", -1), (axes[2, j], "fn", 1)):
                ax.step([r["spent"] for r in states], [direction*(r[field]-initial[field]) for r in states],
                        where="post", color=COLORS[method], linestyle=STYLES[method], label=LABELS[method])
            projection.append({"dataset": "wdc", "budget": budget, "method": method,
                               "events": events, "states": states})
        top.set_xlim(.5, budget+.5); top.set_ylim(2.55, -.7)
        top.set_yticks(range(3), [SHORT[m] for m in METHODS]); top.set_xticks([])
        top.set_title(f'({"ab"[j]}) WDC requested B{budget}', pad=4)
        divergence=singleton(data["contrasts"],dataset="wdc",budget=budget,comparison="raw_minus_singleton")["first_paid_sequence_divergence"]
        for ax in axes[1:, j]:
            ax.set_xlim(0, budget); ax.set_xticks([0, 12, 24] if budget==24 else [0, 12, 24, 36, 48]); ax.grid(alpha=.16)
            if divergence is not None: ax.axvline(divergence, color="#777777", linestyle=":", lw=.7)
        axes[1, j].set_ylim(0, 64000); axes[1, j].set_yticks([0, 30000, 60000], ["0", "30,000", "60,000"])
        axes[2, j].set_ylim(0, 112); axes[2, j].set_yticks([0, 50, 100])
        axes[2, j].set_xlabel("Paid query within this run")
    axes[1, 0].set_ylabel("FP removed"); axes[2, 0].set_ylabel("FN added")
    first=singleton(data["contrasts"],dataset="wdc",budget=24,comparison="raw_minus_singleton")["first_paid_sequence_divergence"]
    first_event=singleton(data["events"],dataset="wdc",budget=24,method=METHODS[1],spent=first)
    action=select(data["events"],dataset="wdc",budget=24,method=METHODS[1],batch=first_event["batch"])
    action=sorted(action,key=lambda r:r["spent"])
    if [r["category"] for r in action] != ["negative_no_split", "negative_split"]:
        raise ValueError("The registered first-divergence illustration no longer matches the public events")
    last=action[-1]
    removed=sum(r["fp_removed"] for r in action);added=sum(r["fn_added"] for r in action)
    initial=singleton(data["states"],dataset="wdc",budget=24,method=METHODS[1],spent=0)
    axes[1, 0].annotate(f'Raw {first}: no split → {last["spent"]}: split\n{removed:,} FP removed; {added} FN',
                        xy=(last["spent"], initial["fp"]-last["fp_after"]),
                        xytext=(.03, 1.045), textcoords="axes fraction", fontsize=8, va="bottom",
                        arrowprops={"arrowstyle": "->", "lw": .6, "color": "#555555"},
                        bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9, "pad": 1.5})
    box=axes[1,1].get_position()
    zoom=fig.add_axes([box.x0+.055,box.y1+.035,box.width-.055,.055])
    zoom_events=[]
    for row_index,method in enumerate(METHODS[1:]):
        rows=[r for r in select(data["events"],dataset="wdc",method=method,budget=24) if 13<=r["spent"]<=18]
        zoom_events.extend(rows)
        for row in rows:
            zoom.add_patch(Rectangle((row["spent"]-.5,row_index-.42),1,.84,
                                    facecolor=EVENT_COLORS[CATEGORIES.index(row["category"])],edgecolor="white",lw=.6))
    zoom.add_patch(Rectangle((first-.5,-.45),len(action),.9,fill=False,lw=1,edgecolor="#222222"))
    zoom.set_xlim(12.5,18.5);zoom.set_ylim(1.52,-.52)
    zoom.set_xticks(range(13,19));zoom.set_yticks([0,1],["Raw","Single"])
    zoom.tick_params(axis="both",length=0,pad=2)
    zoom.set_title("(c) B24 detail",pad=4)
    for spine in zoom.spines.values():spine.set_visible(False)
    return fig, {"traces": projection, "divergence_paid_step": first, "first_divergent_raw_batch": action,
                 "paid_step_zoom_13_to_18":zoom_events,
                 "divergence_provenance": "Reported scalar from private pair-identity audit; public events omit pairs.",
                 "zoom_rule": "First raw/singleton paid-pair divergence; inspect that first raw batch."}


def depth_figure(data):
    projection = depth_projection(data["candidate_depths"])
    keys = [(m, d, b) for m in METHODS[1:] for d in DATASETS for b in BUDGETS]
    stages = ("generated", "capped", "scored", "selected")
    matrix = np.array([[singleton(projection, method=m, dataset=d, budget=b, stage=s)["multi_fraction"]
                        for s in stages] for m, d, b in keys], dtype=float)
    fig, ax = plt.subplots(figsize=(WIDTH, 3.5)); fig.subplots_adjust(left=.28, right=.93, top=.79, bottom=.15)
    im = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=1, aspect="auto", interpolation="nearest")
    ax.set_xticks(range(4), ["Generated", "Capped", "Scored", "Selected"])
    ax.xaxis.tick_top(); ax.tick_params(axis="both", length=0)
    ax.set_yticks(range(12), [f'{SHORT[m]} {"WDC" if d=="wdc" else "DBLP"} B{b}' for m,d,b in keys])
    for i, (m, d, b) in enumerate(keys):
        for j, stage in enumerate(stages):
            cell = singleton(projection, method=m, dataset=d, budget=b, stage=stage)
            ax.text(j, i, f'{cell["multi_count"]:,}/{cell["total"]:,}', ha="center", va="center",
                    color="white" if cell["multi_fraction"] is not None and cell["multi_fraction"]>.60 else "#17202A")
    ax.set_xticks(np.arange(-.5,4,1), minor=True); ax.set_yticks(np.arange(-.5,12,1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.2); ax.tick_params(which="minor", length=0)
    ax.axhline(5.5, color="#555555", lw=1); ax.axvline(2.5, color="#777777", lw=.8)
    for spine in ax.spines.values(): spine.set_visible(False)
    cax = fig.add_axes([.28, .063, .65, .018]); cb=fig.colorbar(im, cax=cax, orientation="horizontal")
    cb.set_ticks([0,.5,1], labels=["0%", "50%", "100%"]); cb.outline.set_visible(False)
    fig.text(.524, .895, "Candidate occurrences", ha="center")
    fig.text(.849, .895, "Batch actions", ha="center")
    fig.text(.50, .985, "Each cell: count with width > 1 / stage total", ha="center", va="top")
    return fig, {"cells": projection, "not_flow_conservation": True,
                 "trajectory_caveat": "After paid-sequence divergence the shared generator visits different states; full-run candidate pools need not match."}


def cost_figure(data):
    fig, axes = plt.subplots(3, 2, figsize=(WIDTH, 4.0), gridspec_kw={"height_ratios": [1, 1.1, .9]})
    fig.subplots_adjust(left=.14, right=.97, bottom=.11, top=.82, wspace=.48, hspace=.68)
    method_legend(fig)
    fig.text(.5,.925,"Point area in (a–b): B12 < B24 < B48; one run per cell.",ha="center")
    for j, dataset in enumerate(DATASETS):
        ax=axes[0,j]
        for method in METHODS:
            for budget in BUDGETS:
                r=singleton(data["endpoints"], dataset=dataset, method=method, budget=budget)
                ax.scatter(r["worker_wall_seconds"],r["loss"],color=COLORS[method],marker=MARKERS[method],
                           s={12:18,24:30,48:46}[budget],facecolors="none" if method==METHODS[2] else COLORS[method], linewidths=.8)
        ax.set_title(f'({"ab"[j]}) {TITLES[dataset]} quality / cost',pad=4)
        ax.set_xlabel("Worker wall seconds"); ax.grid(alpha=.15)
        if j==0:ax.set_ylabel("FP + FN");ax.set_yticks([20000,40000],["20,000","40,000"])
        else:ax.set_yticks([28,30,32]);ax.set_ylim(27,33)
        ax=axes[1,j]
        for k,budget in enumerate(BUDGETS):
            for i,method in enumerate(METHODS):
                r=singleton(data["endpoints"],dataset=dataset,method=method,budget=budget)
                y=k+(i-1)*.22
                ax.plot([r["selector_seconds"],r["worker_wall_seconds"]],[y,y],color=COLORS[method],lw=.9)
                ax.scatter(r["selector_seconds"],y,s=13,color=COLORS[method],marker="|")
                ax.scatter(r["worker_wall_seconds"],y,s=15,facecolors="white",edgecolors=COLORS[method],marker="o")
        ax.set_yticks(range(3),["B12","B24","B48"]);ax.set_ylim(2.5,-.5)
        ax.set_xlim(left=0);ax.set_xlabel("Seconds: | selector → ○ wall");ax.grid(axis="x",alpha=.15)
        ax=axes[2,j]
        for i,method in enumerate(METHODS):
            rows=[singleton(data["endpoints"],dataset=dataset,method=method,budget=b) for b in BUDGETS]
            ax.plot(BUDGETS,[r["logical_score_accesses"] for r in rows],color=COLORS[method],
                    marker=MARKERS[method],linestyle=STYLES[method],markersize=3,
                    markerfacecolor="white" if method==METHODS[2] else COLORS[method])
        ax.set_yscale("log");ax.set_xticks(BUDGETS);ax.set_xlabel("Requested budget");ax.grid(alpha=.15)
        if j==0:ax.set_ylabel("Logical accesses")
    return fig,{"endpoints":data["endpoints"],"cache_counts":data.get("cache_counts",[]),
                "claim_limit":"Fixed order, single execution; no speedup distribution or causal cache estimate."}


def main(evidence_dir=ROOT/"evidence", out=ROOT/"figures"):
    from scripts.schema import load_evidence
    from scripts.validate_evidence import validate
    evidence_dir,out=Path(evidence_dir),Path(out)
    validation=validate(evidence_dir)
    data=load_evidence(evidence_dir)
    out.mkdir(parents=True,exist_ok=True);(out/"data").mkdir(exist_ok=True)
    setup_style()
    specs=[("fig01_contract",contract_figure,[],"Illustrative contract, not a measured benchmark result."),
           ("fig02_structure",structure_figure,["coverage","bound_curve"],"Offline, all answers known; unavailable whole-graph optima stay unavailable."),
           ("fig03_outcomes",outcomes_figure,["endpoints","contrasts"],"Independent requested-budget endpoints; no prefix substitutes."),
           ("fig04_events",events_figure,["events","states","batches","contrasts"],"Recorded within-run paid-step paths; not independent budget endpoints."),
           ("fig05_depth",depth_figure,["candidate_depths"],"Candidate occurrences and selected batch actions have distinct denominators."),
           ("fig06_cost",cost_figure,["endpoints","cache_counts"],"One fixed-order run per cell; logical accesses differ from physical graph calculations.")]
    receipts=[]
    for name,renderer,tables,note in specs:
        fig,projection=renderer() if not tables else renderer(data)
        sources={f"{t}.csv":digest(evidence_dir/f"{t}.csv") for t in tables}
        receipts.append(save(fig,out,name,projection,sources,note))
    receipt={"schema":"cut-audit-public-figures-v3","input_manifest_sha256":digest(evidence_dir/"manifest.json"),
             "input_validation":validation,"figures":receipts,"source_access":"sanitized public CSVs only",
             "rendering":"Fixed width 4.8 inches, DejaVu Sans >= 8 pt, vector PDF/SVG and 300 dpi PNG",
             "cross_platform_note":"Numerical projections are reproducible; cross-platform image bytes are not promised identical."}
    (out/"figure_provenance.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return receipt


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence",type=Path,default=ROOT/"evidence")
    parser.add_argument("--out",type=Path,default=ROOT/"figures")
    args=parser.parse_args()
    result=main(args.evidence,args.out)
    print(json.dumps({"figures":len(result["figures"]),"output":str(args.out)}))
