#!/usr/bin/env python3
"""Plot the three frozen threshold points from a science payload artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


THRESHOLDS = (0.025, 0.05, 0.1)
PRIMARY_THRESHOLD = 0.05


def _number(value: Any, label: str, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number" if not optional else f"{label} must be null or a finite number")
    return float(value)


def _load_science_result(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read science payload JSON from {path}: {error}") from error
    match = re.fullmatch(r"science-payload-([0-9a-f]{64})", path.stem)
    if match and hashlib.sha256(raw).hexdigest() != match.group(1):
        raise ValueError("Content-addressed science payload checksum does not match its filename")
    if not isinstance(payload, dict) or payload.get("artifact_type") != "nova.science_payload.v1":
        raise ValueError("Input must be a nova.science_payload.v1 artifact")
    science = payload.get("science_result")
    if not isinstance(science, dict) or science.get("template") != "threshold_sensitivity":
        raise ValueError("Payload must contain a threshold_sensitivity science_result")
    points = science.get("points")
    if not isinstance(points, list) or len(points) != len(THRESHOLDS):
        raise ValueError("Science result must contain all three preregistered threshold points")
    for index, (point, expected) in enumerate(zip(points, THRESHOLDS)):
        if not isinstance(point, dict) or _number(point.get("threshold_ev_atom"), f"point {index} threshold") != expected:
            raise ValueError("Science result thresholds do not match the frozen grid")
    primary_index = science.get("primary_point_index")
    if (
        isinstance(primary_index, bool)
        or not isinstance(primary_index, int)
        or primary_index != 1
        or _number(
        science.get("primary_threshold_ev_atom"), "primary threshold"
        )
        != PRIMARY_THRESHOLD
    ):
        raise ValueError("Science result does not identify 0.05 eV/atom as its primary point")
    return science


def _point_values(point: dict[str, Any], index: int) -> dict[str, Any]:
    summaries = point.get("groups_summary")
    if not isinstance(summaries, dict):
        raise ValueError(f"point {index} is missing groups_summary")
    parsed: dict[str, Any] = {"rates": {}, "counts": {}}
    for family in ("oxide", "chalcogenide"):
        group = summaries.get(family)
        if not isinstance(group, dict):
            raise ValueError(f"point {index} is missing the {family} group summary")
        total = group.get("n_total")
        observed = group.get("n_observed")
        passed = group.get("n_pass")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (total, observed, passed)):
            raise ValueError(f"point {index} has invalid {family} counts")
        if observed > total or passed > observed:
            raise ValueError(f"point {index} has inconsistent {family} counts")
        rate = _number(group.get("observed_rate"), f"point {index} {family} observed_rate", optional=True)
        if rate is not None and not 0.0 <= rate <= 1.0:
            raise ValueError(f"point {index} {family} observed_rate must be between zero and one")
        if observed == 0 and rate is not None:
            raise ValueError(f"point {index} {family} rate must be null when no compositions are observed")
        if observed > 0 and (rate is None or not math.isclose(rate, passed / observed, rel_tol=0.0, abs_tol=1e-12)):
            raise ValueError(f"point {index} {family} rate does not match its stored pass and observed counts")
        parsed["rates"][family] = rate
        parsed["counts"][family] = {"passed": passed, "observed": observed, "total": total}

    delta = _number(point.get("delta"), f"point {index} delta", optional=True)
    interval_value = point.get("resampling_interval")
    interval: tuple[float, float] | None
    if interval_value is None:
        interval = None
    elif isinstance(interval_value, list) and len(interval_value) == 2:
        low = _number(interval_value[0], f"point {index} interval lower")
        high = _number(interval_value[1], f"point {index} interval upper")
        if low > high:
            raise ValueError(f"point {index} resampling interval is reversed")
        interval = (low, high)
    else:
        raise ValueError(f"point {index} resampling_interval must be a pair or null")

    oxide_rate = parsed["rates"]["oxide"]
    chalcogenide_rate = parsed["rates"]["chalcogenide"]
    if oxide_rate is not None and chalcogenide_rate is not None:
        expected_delta = chalcogenide_rate - oxide_rate
        if delta is None or not math.isclose(delta, expected_delta, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"point {index} delta does not match its stored family rates")
    elif delta is not None:
        raise ValueError(f"point {index} delta must be null when either family rate is unavailable")

    parsed["delta"] = delta
    parsed["interval"] = interval
    return parsed


def plot_result(input_path: Path, output_path: Path) -> Path:
    science = _load_science_result(input_path)
    values = [_point_values(point, index) for index, point in enumerate(science["points"])]

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.ticker import FormatStrFormatter
    except ImportError as error:
        raise RuntimeError("Matplotlib is required to render the threshold sensitivity PNG") from error

    colors = {"oxide": "#3569a8", "chalcogenide": "#d07a16"}
    labels = {"oxide": "Oxide", "chalcogenide": "Chalcogenide"}
    fig, (rate_axis, delta_axis) = plt.subplots(
        2,
        1,
        figsize=(8.5, 7.0),
        sharex=True,
        gridspec_kw={"height_ratios": [1.2, 1.0]},
    )
    x_values = list(THRESHOLDS)
    primary_x = THRESHOLDS[1]
    rate_values_percent = [
        value["rates"][family] * 100.0
        for value in values
        for family in ("oxide", "chalcogenide")
        if value["rates"][family] is not None
    ]
    largest_rate_percent = max(rate_values_percent, default=0.0)
    rate_y_max = max(largest_rate_percent * 1.4, largest_rate_percent + 0.05, 0.05)
    rate_axis.set_ylim(0.0, rate_y_max)
    rate_axis.set_yticks([rate_y_max * index / 4 for index in range(5)])
    rate_axis.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))

    for axis in (rate_axis, delta_axis):
        axis.axvspan(primary_x - 0.0035, primary_x + 0.0035, color="#d9a441", alpha=0.13, zorder=0)
        axis.axvline(primary_x, color="#966b16", linewidth=1.2, linestyle="--", zorder=1)
        axis.grid(axis="y", color="#d8dde3", linewidth=0.7, alpha=0.8)

    for family in ("oxide", "chalcogenide"):
        y_values = [
            None if value["rates"][family] is None else value["rates"][family] * 100.0
            for value in values
        ]
        for index, y in enumerate(y_values):
            if y is None:
                counts = values[index]["counts"][family]
                rate_axis.annotate(
                    f"rate n/a; pass={counts['passed']}; n={counts['observed']}/{counts['total']}",
                    (x_values[index], 0),
                    xytext=(0, 8 if family == "oxide" else 25),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color=colors[family],
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 1.2},
                    annotation_clip=False,
                )
                continue
            rate_axis.scatter(
                [x_values[index]],
                [y],
                color=colors[family],
                s=44,
                zorder=3,
            )
            counts = values[index]["counts"][family]
            rate_axis.annotate(
                f"pass={counts['passed']}; n={counts['observed']}/{counts['total']}",
                (x_values[index], y),
                xytext=(0, 8 if family == "oxide" else 24),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
                color=colors[family],
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 1.2},
                annotation_clip=False,
            )
            if index == 1:
                rate_axis.scatter(
                    [x_values[index]],
                    [y],
                    facecolors="none",
                    edgecolors="#20252b",
                    linewidths=1.5,
                    s=120,
                    zorder=4,
                )
        for index in range(len(x_values) - 1):
            left, right = y_values[index], y_values[index + 1]
            if left is not None and right is not None:
                rate_axis.plot(
                    x_values[index : index + 2],
                    [left, right],
                    color=colors[family],
                    linewidth=1.8,
                    zorder=2,
                )

    deltas = [value["delta"] for value in values]
    for index, value in enumerate(values):
        estimate = value["delta"]
        if estimate is None:
            continue
        estimate_pp = estimate * 100.0
        delta_axis.scatter([x_values[index]], [estimate_pp], color="#30343b", s=42, zorder=3)
        interval = value["interval"]
        if interval is not None:
            lower, upper = interval
            lower_pp, upper_pp = lower * 100.0, upper * 100.0
            delta_axis.vlines(x_values[index], lower_pp, upper_pp, color="#30343b", linewidth=1.5, zorder=2)
            delta_axis.hlines(
                [lower_pp, upper_pp],
                x_values[index] - 0.002,
                x_values[index] + 0.002,
                color="#30343b",
                linewidth=1.5,
                zorder=2,
            )
        if index == 1:
            delta_axis.scatter(
                [x_values[index]],
                [estimate_pp],
                facecolors="none",
                edgecolors="#20252b",
                linewidths=1.5,
                s=120,
                zorder=4,
            )
    for index in range(len(x_values) - 1):
        left, right = deltas[index], deltas[index + 1]
        if left is not None and right is not None:
            delta_axis.plot(
                x_values[index : index + 2],
                [left * 100.0, right * 100.0],
                color="#30343b",
                linewidth=1.2,
                alpha=0.7,
                zorder=1,
            )

    rate_axis.set_ylabel("Observed pass rate (%)")
    rate_axis.set_title("Observed family pass rates")
    rate_axis.legend(
        handles=[
            Line2D([0], [0], color=colors["oxide"], marker="o", label=labels["oxide"]),
            Line2D([0], [0], color=colors["chalcogenide"], marker="o", label=labels["chalcogenide"]),
            Line2D([0], [0], color="#966b16", linestyle="--", label="Primary threshold: 0.05 eV/atom"),
        ],
        loc="best",
        frameon=False,
    )
    delta_axis.axhline(0.0, color="#6d737b", linewidth=0.9, linestyle=":", zorder=0)
    delta_axis.set_ylabel("Chalcogenide − oxide (percentage points)")
    delta_axis.set_xlabel("Inclusive ehull maximum (eV/atom)")
    delta_axis.set_xticks(x_values, ["0.025", "0.05 (primary)", "0.10"])
    delta_axis.set_title("Difference and 95% percentile resampling interval")
    fig.suptitle(
        "Threshold sensitivity on the discovery split\n"
        "Observed representative compositions in the frozen JARVIS snapshot",
        fontsize=12,
    )
    fig.text(
        0.5,
        0.012,
        "Labels show n observed / n total. Intervals describe resampling stability in this snapshot.",
        ha="center",
        fontsize=8,
        color="#4c535c",
    )
    fig.tight_layout(rect=(0, 0.045, 1, 0.94), pad=0.8)

    if output_path.suffix.lower() != ".png":
        raise ValueError("Output path must end in .png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, format="png", bbox_inches="tight")
    plt.close(fig)
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plot observed pass rates and the bootstrap delta interval from a threshold sensitivity payload."
    )
    parser.add_argument("input", type=Path, help="immutable science-payload JSON artifact")
    parser.add_argument(
        "--output",
        type=Path,
        help="destination PNG path (default: beside the payload with a -threshold-sensitivity suffix)",
    )
    args = parser.parse_args(argv)
    output_path = args.output or args.input.with_name(args.input.stem + "-threshold-sensitivity.png")
    try:
        saved = plot_result(args.input, output_path)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(f"plot_path={saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
