#!/usr/bin/env python3
"""Render the three registered method arms from an existing aggregate result."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def plot_result(result_path: Path, output_path: Path) -> None:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("template") != "method_sensitivity" or result.get("split") != "discovery":
        raise ValueError("Expected a discovery method_sensitivity aggregate result")
    if output_path.exists():
        raise FileExistsError(f"Choose a fresh output path: {output_path}")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = ("opt_all", "opt_paired", "mbj_paired")
    labels = ("OPT · all evaluable", "OPT · paired subset", "MBJ · same paired subset")
    families = ("oxide", "chalcogenide")
    colors = ("#3569a8", "#c16d16")
    fig, (rates, differences) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    maximum = 0.0
    for family_index, (family, color) in enumerate(zip(families, colors)):
        for index, name in enumerate(names):
            group = result["arms"][name]["groups_summary"][family]
            rate = group["observed_rate"]
            xpos = index + (-.19 if family_index == 0 else .19)
            if rate is None:
                rates.text(xpos, 0, "Unknown", ha="center", fontsize=8)
                continue
            value = rate * 100
            maximum = max(maximum, value)
            rates.bar(xpos, value, width=.34, color=color, label=family.title() if index == 0 else None)
            rates.annotate(f"{group['n_pass']}/{group['n_observed']:,}", (xpos, value),
                           xytext=(0, 6), textcoords="offset points", ha="center", fontsize=9, color=color)
    rates.set_ylim(0, max(maximum * 1.38, .1))
    rates.set_ylabel("Observed screening pass rate (%)")
    totals = result["arms"]["opt_all"]["groups_summary"]
    rates.set_title("Labels show pass / observed; eligible totals: " + ", ".join(
        f"{family} {totals[family]['n_total']:,}" for family in families
    ), fontsize=10)
    rates.legend(frameon=False, loc="upper left")

    for index, name in enumerate(names):
        arm = result["arms"][name]
        if arm["delta"] is None:
            continue
        estimate = arm["delta"] * 100
        differences.scatter(index, estimate, color="#293c4b", zorder=3)
        if arm["resampling_interval"] is not None:
            low, high = [value * 100 for value in arm["resampling_interval"]]
            differences.vlines(index, low, high, color="#293c4b")
            differences.hlines([low, high], index - .045, index + .045, color="#293c4b")
            differences.annotate(f"{estimate:.4f} pp\n[{low:.4f}, {high:.4f}]", (index, high),
                                 xytext=(0, 8), textcoords="offset points", ha="center", fontsize=9)
    differences.axhline(0, color="#777", linestyle="--", linewidth=.8)
    differences.set_ylabel("Chalcogenide − oxide (percentage points)")
    differences.set_title("Family difference and 95% snapshot resampling interval", fontsize=10)
    differences.set_xticks(range(len(names)), labels)
    differences.margins(y=.35)
    for axis in (rates, differences):
        axis.set_axisbelow(True)
        axis.grid(axis="y", color="#dde3e8", linewidth=.6)
        axis.spines[["top", "right"]].set_visible(False)

    paired = result["arms"]["opt_paired"]["groups_summary"]
    coverage = "; ".join(
        f"{family} " + (f"{paired[family]['coverage']:.1%}" if paired[family]['coverage'] is not None else "unknown")
        for family in families
    )
    fig.suptitle("OPT/MBJ screening audit · exploratory discovery analysis", fontsize=14)
    fig.text(.5, .03, f"Paired coverage of eligible representatives: {coverage}.\n"
             "All → paired compares subsets; paired OPT → MBJ compares methods on identical JIDs.\n"
             "Sparse screening outcomes in one frozen JARVIS snapshot; MBJ is not experimental truth.",
             ha="center", fontsize=9, color="#4c535c")
    fig.tight_layout(rect=(0, .1, 1, .95))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plot_result(args.result, args.output)
    print(f"plot_path={args.output}")
