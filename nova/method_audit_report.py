"""Render the paired OPT/MBJ screening audit as local, self-contained reports."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


ARM_ORDER = ("opt_all", "opt_paired", "mbj_paired")
FAMILY_ORDER = ("oxide", "chalcogenide")
CANDIDATE_LABELS = (
    "passes_both_methods",
    "opt_only",
    "mbj_only",
    "opt_pass_mbj_unknown",
    "mbj_pass_opt_unknown",
    "neither_passes",
    "no_current_pass_incomplete_evidence",
    "insufficient_evidence",
)
AUDIT_FIELDS = (
    "jid",
    "reduced_formula",
    "family",
    "opt_gap_ev",
    "mbj_gap_ev",
    "ehull_ev_atom",
    "ehull_valid",
    "paired",
    "opt_status",
    "mbj_status",
    "candidate_label",
    "shortlisted",
    "reason",
    "next_validation",
)

_UNKNOWN = "Unknown"


def ensure_output_dir_available(output_dir: str | Path) -> Path:
    """Refuse any existing target path without creating or changing it."""
    path = Path(output_dir).expanduser()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Output path already exists; choose a fresh directory: {path}")
    return path


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _finite_number(value: Any, label: str, *, optional: bool = True) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number" if not optional else f"{label} must be null or a finite number")
    return float(value)


def _count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _fmt_number(value: Any, *, percent: bool = False, percentage_points: bool = False) -> str:
    number = _finite_number(value, "reported value")
    if number is None:
        return _UNKNOWN
    if percent or percentage_points:
        number *= 100.0
    # Preserve sparse nonzero rates and provide at least six decimal places.
    if number != 0.0 and abs(number) < 1e-8:
        rendered = f"{number:.8g}"
    else:
        rendered = f"{number:.9f}".rstrip("0").rstrip(".")
    if rendered in {"-0", ""}:
        rendered = "0"
    return rendered + ("%" if percent else " pp" if percentage_points else "")


def _fmt_interval(value: Any, *, percent: bool = False, percentage_points: bool = False) -> str:
    if value is None:
        return _UNKNOWN
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("resampling_interval must be a pair or null")
    low = _finite_number(value[0], "resampling interval lower endpoint", optional=False)
    high = _finite_number(value[1], "resampling interval upper endpoint", optional=False)
    assert low is not None and high is not None
    if low > high:
        raise ValueError("resampling_interval lower endpoint exceeds upper endpoint")
    return (
        f"[{_fmt_number(low, percent=percent, percentage_points=percentage_points)}, "
        f"{_fmt_number(high, percent=percent, percentage_points=percentage_points)}]"
    )


def _display(value: Any) -> str:
    if value is None:
        return _UNKNOWN
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _fmt_number(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _md_cell(value: Any) -> str:
    text = _display(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "&#124;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _md_table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    header_values = list(headers)
    rendered = ["| " + " | ".join(_md_cell(value) for value in header_values) + " |", "| " + " | ".join("---" for _ in header_values) + " |"]
    for row in rows:
        rendered.append("| " + " | ".join(_md_cell(value) for value in row) + " |")
    return "\n".join(rendered)


def _html_table(headers: Iterable[str], rows: Iterable[Iterable[Any]], *, table_id: str | None = None) -> str:
    identifier = "" if table_id is None else f' id="{html.escape(table_id, quote=True)}"'
    head = "".join(f"<th scope=\"col\">{html.escape(str(name), quote=True)}</th>" for name in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(_display(value), quote=True)}</td>" for value in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<div class=\"table-wrap\"><table{identifier}><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"


def _ordered_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(rows, key=lambda row: (str(row["family"]), str(row["jid"])))


def _fmt_flags(value: Any) -> str:
    if value is None:
        return _UNKNOWN
    if isinstance(value, Mapping):
        if not value:
            return "None"
        return "; ".join(f"{key}={_display(item)}" for key, item in sorted(value.items(), key=lambda pair: str(pair[0])))
    if isinstance(value, (list, tuple, set)):
        return "; ".join(_display(item) for item in value) or "None"
    return _display(value)


def _validate_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    parsed = []
    for index, original in enumerate(rows):
        row = _as_mapping(original, f"audit row {index}")
        missing = [field for field in AUDIT_FIELDS if field not in row]
        extra = [field for field in row if field not in AUDIT_FIELDS]
        if missing or extra:
            raise ValueError(f"audit row {index} fields do not match the frozen schema (missing={missing}, extra={extra})")
        for key in ("ehull_valid", "paired", "shortlisted"):
            if not isinstance(row[key], bool):
                raise ValueError(f"audit row {index} {key} must be boolean")
        for key in ("opt_status", "mbj_status"):
            if row[key] not in {"pass", "fail", "unknown"}:
                raise ValueError(f"audit row {index} {key} must be pass, fail, or unknown")
        for key in ("opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom"):
            _finite_number(row[key], f"audit row {index} {key}")
        for key in ("jid", "reduced_formula", "family", "candidate_label", "reason", "next_validation"):
            if not isinstance(row[key], str):
                raise ValueError(f"audit row {index} {key} must be text")
        if row["candidate_label"] not in CANDIDATE_LABELS:
            raise ValueError(f"audit row {index} has an unknown candidate_label")
        parsed.append(row)
    return _ordered_rows(parsed)


def _validate_result(result: Mapping[str, Any]) -> None:
    for key in ("arms", "subset_shift", "paired_method_change", "transitions", "candidate_counts", "candidate_counts_by_family"):
        if key not in result:
            raise ValueError(f"result is missing {key}")
    arms = _as_mapping(result["arms"], "arms")
    for arm_name in ARM_ORDER:
        if arm_name not in arms:
            raise ValueError(f"result is missing arm {arm_name}")
        arm = _as_mapping(arms[arm_name], f"arm {arm_name}")
        summaries = _as_mapping(arm.get("groups_summary"), f"arm {arm_name} groups_summary")
        for family in FAMILY_ORDER:
            group = _as_mapping(summaries.get(family), f"arm {arm_name} {family} summary")
            total, observed, passed = (
                _count(group.get(key), f"arm {arm_name} {family} {key}")
                for key in ("n_total", "n_observed", "n_pass")
            )
            if observed > total or passed > observed:
                raise ValueError(f"arm {arm_name} {family} counts are inconsistent")
            coverage = _finite_number(group.get("coverage"), f"arm {arm_name} {family} coverage")
            rate = _finite_number(group.get("observed_rate"), f"arm {arm_name} {family} observed_rate")
            expected_coverage = None if total == 0 else observed / total
            expected_rate = None if observed == 0 else passed / observed
            if expected_coverage is None:
                if coverage is not None:
                    raise ValueError(f"arm {arm_name} {family} coverage must be null when no rows are eligible")
            elif coverage is None or not math.isclose(coverage, expected_coverage, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"arm {arm_name} {family} coverage does not match its stored counts")
            if expected_rate is None:
                if rate is not None:
                    raise ValueError(f"arm {arm_name} {family} rate must be null when no rows are observed")
            elif rate is None or not math.isclose(rate, expected_rate, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"arm {arm_name} {family} rate does not match its stored counts")
        delta = _finite_number(arm.get("delta"), f"arm {arm_name} delta")
        _fmt_interval(arm.get("resampling_interval"))
        groups = arms[arm_name]["groups_summary"]
        oxide_rate = groups["oxide"].get("observed_rate")
        chalcogenide_rate = groups["chalcogenide"].get("observed_rate")
        expected_delta = None if oxide_rate is None or chalcogenide_rate is None else chalcogenide_rate - oxide_rate
        if expected_delta is None:
            if delta is not None:
                raise ValueError(f"arm {arm_name} delta must be null when a family rate is unavailable")
        elif delta is None or not math.isclose(delta, expected_delta, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"arm {arm_name} delta does not match its family rates")


def _summary_table_rows(result: Mapping[str, Any]) -> list[list[Any]]:
    arms = result["arms"]
    rows: list[list[Any]] = []
    for arm_name in ARM_ORDER:
        arm = arms[arm_name]
        groups = arm["groups_summary"]
        for family in FAMILY_ORDER:
            group = groups[family]
            rows.append([
                arm_name,
                family,
                f"{group['n_pass']}/{group['n_observed']}",
                group["n_total"],
                _fmt_number(group.get("coverage"), percent=True),
                _fmt_number(group.get("observed_rate"), percent=True),
                _fmt_number(arm.get("delta"), percentage_points=True),
                _fmt_interval(arm.get("resampling_interval"), percentage_points=True),
                arm.get("scientific_status", _UNKNOWN),
                _fmt_flags(arm.get("quality_flags", [])),
            ])
    return rows


def _paired_rows(result: Mapping[str, Any]) -> list[list[Any]]:
    changes = _as_mapping(result["paired_method_change"], "paired_method_change")
    summaries = _as_mapping(changes.get("groups_summary"), "paired_method_change groups_summary")
    rows = []
    for family in FAMILY_ORDER:
        group = _as_mapping(summaries.get(family), f"paired_method_change {family}")
        rows.append([
            family,
            group.get("n_paired", _UNKNOWN),
            group.get("n_opt_pass", _UNKNOWN),
            group.get("n_mbj_pass", _UNKNOWN),
            group.get("n_gained", _UNKNOWN),
            group.get("n_lost", _UNKNOWN),
            _fmt_number(group.get("mean_change"), percentage_points=True),
            _fmt_interval(group.get("resampling_interval"), percentage_points=True),
        ])
    return rows


def _paired_contrast_row(result: Mapping[str, Any]) -> list[Any]:
    changes = _as_mapping(result["paired_method_change"], "paired_method_change")
    return [
        "chalcogenide − oxide paired change",
        _fmt_number(changes.get("delta"), percentage_points=True),
        _fmt_interval(changes.get("resampling_interval"), percentage_points=True),
        changes.get("scientific_status", _UNKNOWN),
        _fmt_flags(changes.get("quality_flags", [])),
    ]


def _transition_rows(result: Mapping[str, Any]) -> list[list[Any]]:
    transitions = _as_mapping(result["transitions"], "transitions")
    keys = ("pass_to_pass", "pass_to_fail", "fail_to_pass", "fail_to_fail")
    rows = []
    for family in FAMILY_ORDER:
        summary = _as_mapping(transitions.get(family), f"transitions {family}")
        rows.append([family, *[summary.get(key, _UNKNOWN) for key in keys]])
    return rows


def _count_rows(counts: Mapping[str, Any]) -> list[list[Any]]:
    return [[label, counts.get(label, 0)] for label in CANDIDATE_LABELS]


def _candidate_table_rows(rows: list[Mapping[str, Any]]) -> list[list[Any]]:
    fields = ("family", "jid", "reduced_formula", "opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom", "opt_status", "mbj_status", "candidate_label", "reason", "next_validation")
    return [[row[field] for field in fields] for row in rows if row["shortlisted"]]


def _metadata_rows(result: Mapping[str, Any]) -> list[list[Any]]:
    metadata_fields = (
        "schema_version", "template", "execution_status", "split", "dataset_sha256",
        "parent_protocol_sha256", "protocol_sha256", "representative_compositions_csv_sha256",
        "split_assignment_sha256", "started_at", "finished_at", "elapsed_seconds",
        "interpretation_scope", "selection_mode", "no_new_model_calls",
    )
    rows = [[field, result.get(field, _UNKNOWN)] for field in metadata_fields]
    timing = result.get("timing_seconds", _UNKNOWN)
    if isinstance(timing, Mapping):
        if not timing:
            rows.append(["timing_seconds", "Unknown"])
        else:
            rows.extend([[f"timing_seconds.{key}", value] for key, value in sorted(timing.items(), key=lambda item: str(item[0]))])
    else:
        rows.append(["timing_seconds", timing])
    for field in ("source_sha256", "source_hashes"):
        source_hashes = result.get(field, _UNKNOWN)
        if isinstance(source_hashes, Mapping):
            if not source_hashes:
                rows.append([field, "Unknown"])
            else:
                rows.extend([[f"{field}.{key}", value] for key, value in sorted(source_hashes.items(), key=lambda item: str(item[0]))])
        else:
            rows.append([field, source_hashes])
    return rows


def render_markdown(result: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> str:
    shortlist = [row for row in rows if row["shortlisted"]]
    content = [
        "# Paired OPT/MBJ Method Audit",
        "",
        "Exploratory discovery-split screening audit on frozen JARVIS representatives. The report uses existing OPT/MBJ calculations and makes no new DFT or model calls.",
        "",
        "## Three-arm comparison",
        "",
        "Coverage is observed rows divided by all eligible rows. Observed pass rate uses only observed rows; missing property values remain unknown. The family delta is chalcogenide minus oxide for that arm.",
        "",
        _md_table(("Arm", "Family", "Pass / observed", "Eligible", "Coverage", "Observed rate", "Family delta (percentage points)", "95% resampling interval (pp)", "Status", "Quality flags"), _summary_table_rows(result)),
        "",
        "`opt_all` describes every evaluable OPT row; `opt_paired` and `mbj_paired` describe the same rows with both methods available. The `opt_paired` minus `opt_all` difference is a descriptive subset shift and has no causal interpretation. The paired comparison is conditional on paired rows; low paired coverage limits generalization to all eligible representatives.",
        "",
        "### Descriptive OPT subset shift",
        "",
        _md_table(("Family", "OPT paired minus OPT all (percentage points)"), [[family, _fmt_number(result["subset_shift"].get(family), percentage_points=True)] for family in FAMILY_ORDER]),
        "",
        "The subset shift reflects selection into paired-data availability. It is shown separately from the within-row paired method change and should not be read as a causal effect.",
        "",
        "## Paired method changes",
        "",
        "A gained row passes MBJ and fails OPT; a lost row passes OPT and fails MBJ. Mean change is MBJ pass minus OPT pass on identical JIDs. Intervals describe this snapshot, not replication or experimental validation.",
        "",
        _md_table(("Family", "Paired n", "OPT passes", "MBJ passes", "Gained", "Lost", "Mean change (pp)", "95% resampling interval (pp)"), _paired_rows(result)),
        "",
        _md_table(("Across-family contrast", "Change (pp)", "95% resampling interval (pp)", "Status", "Quality flags"), [_paired_contrast_row(result)]),
        "",
        "## Paired pass transitions",
        "",
        _md_table(("Family", "Pass → pass", "Pass → fail", "Fail → pass", "Fail → fail"), _transition_rows(result)),
        "",
        "## Candidate evidence list",
        "",
        f"Shortlisted {len(shortlist)} of {len(rows)} eligible rows. The local full-row audit is in `audit_rows.csv`; this table contains only rows marked `shortlisted=true`.",
        "",
        _md_table(("Family", "JID", "Reduced formula", "OPT gap (eV)", "MBJ gap (eV)", "Ehull (eV/atom)", "OPT", "MBJ", "Candidate label", "Reason", "Next validation"), _candidate_table_rows(rows)),
        "",
        "### Candidate label counts",
        "",
        _md_table(("Label", "All families"), _count_rows(_as_mapping(result["candidate_counts"], "candidate_counts"))),
        "",
        _md_table(("Label", "Oxide", "Chalcogenide"), [[label, _as_mapping(result["candidate_counts_by_family"].get("oxide", {}), "candidate_counts_by_family oxide").get(label, 0), _as_mapping(result["candidate_counts_by_family"].get("chalcogenide", {}), "candidate_counts_by_family chalcogenide").get(label, 0)] for label in CANDIDATE_LABELS]),
        "",
        "## Interpretation limits",
        "",
        "- This is an exploratory discovery-only extension. The holdout remains untouched.",
        "- OPT and MBJ are computational screening methods; MBJ is not ground truth. Passing both is screen agreement, not validation.",
        "- Candidate labels prioritize evidence status. They do not establish synthesizability, physical performance, or new-material discovery.",
        "- Subset availability can change the observed composition mix. Paired estimates apply only to rows with both method values and valid stability data.",
        "- The run is manually selected and uses no new model calls. No autonomous selection or speedup is claimed.",
        "",
        "<details>",
        "<summary>Run metadata, timing, and source hashes</summary>",
        "",
        _md_table(("Field", "Value"), _metadata_rows(result)),
        "",
        "</details>",
        "",
    ]
    return "\n".join(content)


def render_html(result: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> str:
    shortlist = [row for row in rows if row["shortlisted"]]
    comparison = _html_table(
        ("Arm", "Family", "Pass / observed", "Eligible", "Coverage", "Observed rate", "Family delta (percentage points)", "95% resampling interval (pp)", "Status", "Quality flags"),
        _summary_table_rows(result),
    )
    paired = _html_table(
        ("Family", "Paired n", "OPT passes", "MBJ passes", "Gained", "Lost", "Mean change (pp)", "95% resampling interval (pp)"),
        _paired_rows(result),
    )
    paired_contrast = _html_table(
        ("Across-family contrast", "Change (pp)", "95% resampling interval (pp)", "Status", "Quality flags"),
        [_paired_contrast_row(result)],
    )
    shifts = _html_table(
        ("Family", "OPT paired minus OPT all (percentage points)"),
        [[family, _fmt_number(result["subset_shift"].get(family), percentage_points=True)] for family in FAMILY_ORDER],
    )
    transitions = _html_table(("Family", "Pass → pass", "Pass → fail", "Fail → pass", "Fail → fail"), _transition_rows(result))
    counts = _html_table(("Label", "All families"), _count_rows(_as_mapping(result["candidate_counts"], "candidate_counts")))
    counts_by_family = _html_table(
        ("Label", "Oxide", "Chalcogenide"),
        [[label, _as_mapping(result["candidate_counts_by_family"].get("oxide", {}), "candidate_counts_by_family oxide").get(label, 0), _as_mapping(result["candidate_counts_by_family"].get("chalcogenide", {}), "candidate_counts_by_family chalcogenide").get(label, 0)] for label in CANDIDATE_LABELS],
    )
    candidate_fields = ("family", "jid", "reduced_formula", "opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom", "opt_status", "mbj_status", "candidate_label", "reason", "next_validation")
    candidate_header = "".join(f"<th scope=\"col\">{html.escape(name.replace('_', ' '), quote=True)}</th>" for name in candidate_fields)
    candidate_rows = []
    for row in shortlist:
        cells = "".join(f"<td>{html.escape(_display(row[field]), quote=True)}</td>" for field in candidate_fields)
        family = html.escape(row["family"], quote=True)
        label = html.escape(row["candidate_label"], quote=True)
        candidate_rows.append(f'<tr data-family="{family}" data-label="{label}">{cells}</tr>')
    label_options = "".join(
        f'<option value="{html.escape(label, quote=True)}">{html.escape(label.replace("_", " ").title(), quote=True)}</option>'
        for label in CANDIDATE_LABELS
    )
    candidate_table = (
        '<div class="controls"><label>Search candidates <input id="candidate-search" type="search" placeholder="JID, formula, reason…"></label> '
        '<label>Family <select id="family-filter"><option value="all">All families</option><option value="oxide">Oxide</option><option value="chalcogenide">Chalcogenide</option></select></label> '
        f'<label>Candidate label <select id="label-filter"><option value="all">All labels</option>{label_options}</select></label> '
        f'<span id="candidate-count">Showing {len(shortlist)} of {len(shortlist)}</span></div>'
        f'<div class="table-wrap"><table id="candidate-table"><thead><tr>{candidate_header}</tr></thead><tbody>{"".join(candidate_rows)}</tbody></table></div>'
    )
    metadata = _html_table(("Field", "Value"), _metadata_rows(result))
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paired OPT/MBJ Method Audit</title>
<style>
:root {{ color-scheme: light; --ink: #18212b; --muted: #5a6672; --line: #d8dee5; --panel: #f5f7f9; --accent: #245b83; }}
* {{ box-sizing: border-box; }} body {{ margin: 0; color: var(--ink); background: #fff; font: 16px/1.55 system-ui, sans-serif; }}
main {{ max-width: 1440px; margin: auto; padding: 2rem clamp(1rem, 4vw, 3rem) 4rem; }}
h1, h2, h3 {{ line-height: 1.2; }} h1 {{ margin-bottom: .5rem; }} h2 {{ margin-top: 2.2rem; padding-bottom: .4rem; border-bottom: 1px solid var(--line); }}
.lede, .note {{ color: var(--muted); }} .callout {{ background: var(--panel); border-left: 4px solid var(--accent); padding: .8rem 1rem; }}
.table-wrap {{ overflow-x: auto; margin: .8rem 0 1rem; border: 1px solid var(--line); border-radius: .45rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: .91rem; }} th, td {{ text-align: left; vertical-align: top; padding: .55rem .7rem; border-bottom: 1px solid var(--line); }}
th {{ background: var(--panel); white-space: nowrap; }} tr:last-child td {{ border-bottom: 0; }} td {{ overflow-wrap: anywhere; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 1rem; align-items: end; margin: 1rem 0; }} input, select {{ display: block; min-width: 14rem; padding: .55rem; border: 1px solid #aab5c0; border-radius: .3rem; font: inherit; }}
#candidate-count {{ color: var(--muted); padding-bottom: .55rem; }} footer {{ margin-top: 3rem; color: var(--muted); font-size: .9rem; }}
</style>
</head>
<body><main>
<h1>Paired OPT/MBJ Method Audit</h1>
<p class="lede">Exploratory discovery-split screening audit on frozen JARVIS representatives. It uses existing OPT/MBJ calculations and makes no new DFT or model calls.</p>
<p class="callout">Coverage is observed rows divided by all eligible rows. Observed pass rate uses observed rows only; missing values stay unknown. The paired method comparison is conditional on paired rows.</p>
<h2>Three-arm comparison</h2>
<p>OPT on all evaluable rows exposes the full observed subset. The other two arms use the same paired rows. The OPT paired-minus-all difference is a descriptive subset shift, with no causal interpretation.</p>{comparison}
<h2>Paired method changes</h2>
<p>A gained row passes MBJ and fails OPT; a lost row passes OPT and fails MBJ. Mean change is MBJ pass minus OPT pass on identical JIDs. Intervals describe resampling stability in this snapshot.</p>{paired}
{paired_contrast}
<h3>Descriptive OPT subset shift</h3>{shifts}
<p class="note">Low paired coverage limits generalization to all eligible representatives. Subset availability and within-row method change are separate quantities.</p>
<h2>Paired pass transitions</h2>{transitions}
<h2>Candidate evidence list</h2>
<p>Shortlisted {len(shortlist)} of {len(rows)} eligible rows. The local full-row audit is retained separately in <code>audit_rows.csv</code>.</p>{candidate_table}
<h3>Candidate label counts</h3>{counts}{counts_by_family}
<h2>Interpretation limits</h2>
<ul><li>This is an exploratory discovery-only extension; the holdout remains untouched.</li>
<li>OPT and MBJ are computational screening methods. MBJ is not ground truth, and passing both is screen agreement rather than validation.</li>
<li>Candidate labels do not establish synthesizability, physical performance, or new-material discovery.</li>
<li>Paired estimates apply only to rows with both method values and valid stability data.</li>
<li>The run is manually selected and uses no new model calls. No autonomous selection or speedup is claimed.</li></ul>
<details><summary>Run metadata, timing, and source hashes</summary>{metadata}</details>
<footer>All displayed counts and values come from the accompanying aggregate result and local audit CSV. This standalone page uses no external resources.</footer>
</main>
<script>
(() => {{
  const search = document.getElementById('candidate-search');
  const family = document.getElementById('family-filter');
  const label = document.getElementById('label-filter');
  const table = document.getElementById('candidate-table');
  const count = document.getElementById('candidate-count');
  const rows = Array.from(table.tBodies[0].rows);
  const update = () => {{
    const term = search.value.trim().toLowerCase();
    const selected = family.value;
    const selectedLabel = label.value;
    let visible = 0;
    for (const row of rows) {{
      const matches = (selected === 'all' || row.dataset.family === selected)
        && (selectedLabel === 'all' || row.dataset.label === selectedLabel)
        && row.textContent.toLowerCase().includes(term);
      row.hidden = !matches;
      if (matches) visible += 1;
    }}
    count.textContent = `Showing ${{visible}} of ${{rows.length}}`;
  }};
  search.addEventListener('input', update);
  family.addEventListener('change', update);
  label.addEventListener('change', update);
}})();
</script>
</body></html>
'''


def _csv_bytes(rows: list[Mapping[str, Any]]) -> bytes:
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=AUDIT_FIELDS, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        output = {}
        for field in AUDIT_FIELDS:
            value = row[field]
            if value is None:
                output[field] = ""
            elif isinstance(value, bool):
                output[field] = "true" if value else "false"
            elif isinstance(value, float):
                output[field] = repr(value)
            else:
                output[field] = value
        writer.writerow(output)
    return stream.getvalue().encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_report(result: Mapping[str, Any], audit_rows: Iterable[Mapping[str, Any]], output_dir: str | Path) -> dict[str, Any]:
    """Write a new report directory, preserving full rows only in local CSV."""
    target = ensure_output_dir_available(output_dir)
    _validate_result(_as_mapping(result, "result"))
    rows = _validate_rows(audit_rows)
    if "n_eligible" in result and _count(result["n_eligible"], "n_eligible") != len(rows):
        raise ValueError("n_eligible does not match the number of full audit rows")
    if "n_shortlisted" in result and _count(result["n_shortlisted"], "n_shortlisted") != sum(row["shortlisted"] for row in rows):
        raise ValueError("n_shortlisted does not match the shortlisted audit rows")

    shortlist_rows = [row for row in rows if row["shortlisted"]]
    artifacts = {
        "result.json": _json_bytes(dict(result)),
        "audit_rows.csv": _csv_bytes(rows),
        "candidates.csv": _csv_bytes(shortlist_rows),
        "report.md": render_markdown(result, rows).encode("utf-8"),
        "report.html": render_html(result, rows).encode("utf-8"),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(exist_ok=False)
    created: list[Path] = []
    try:
        for name, content in artifacts.items():
            file_path = target / name
            with file_path.open("xb") as stream:
                created.append(file_path)
                stream.write(content)
        checksums = {name: hashlib.sha256(content).hexdigest() for name, content in sorted(artifacts.items())}
        manifest = {"schema_version": 1, "files": checksums}
        manifest_path = target / "checksums.json"
        with manifest_path.open("xb") as stream:
            created.append(manifest_path)
            stream.write(_json_bytes(manifest))
        return {"output_dir": target, "n_eligible": len(rows), "n_shortlisted": len(shortlist_rows), "checksums": checksums}
    except Exception:
        for file_path in created:
            try:
                file_path.unlink()
            except OSError:
                pass
        try:
            target.rmdir()
        except OSError:
            pass
        raise
