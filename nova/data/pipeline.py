"""Freeze one JARVIS dft_3d snapshot and prepare the screen's input tables.

The preparation step computes only composition identities, design exclusions,
representatives, group splits, and missingness metadata. It never computes a
screening rate or opens a holdout result through the public metadata adapter.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
DEFAULT_CACHE_DIR = DATA_ROOT / "cache"
MANIFEST_PATH = DATA_ROOT / "manifest.json"
PROTOCOL_PATH = DATA_ROOT / "protocol.json"
RAW_ROOT = DATA_ROOT / "raw"
AUDIT_ROOT = DATA_ROOT / "audit"

DATASET_NAME = "dft_3d"
SPLIT_SEED = 1_729
DISCOVERY_FRACTION = 0.70
EXCLUDED_ELEMENTS = frozenset({"Pb", "Cd", "Hg", "As", "Tl"})
ANION_LABELS = frozenset({"O", "S", "Se", "N", "F", "Cl", "Br", "I"})
HALOGENS_AND_NITROGEN = frozenset({"N", "F", "Cl", "Br", "I"})
PRIMARY_FAMILIES = ("oxide", "chalcogenide")
PREFROZEN_PROTOCOL_DOCUMENT_SHA256 = "2bc819e58d7168edc496edd11cb8c5f286a7b0868424f0646094ddc800217d86"

FIELDNAMES = [
    "jid",
    "formula",
    "reduced_formula",
    "elements",
    "n_elements",
    "family",
    "opt_gap_ev",
    "mbj_gap_ev",
    "ehull_ev_atom",
    "ehull_valid",
    "ehull_rounded_to_zero",
    "ehull_invalid_reason",
    "excluded",
    "exclusion_reason",
    "record_quality_issue",
    "is_representative",
    "representative_reason",
    "split",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    def json_safe(item: Any) -> Any:
        if isinstance(item, float) and not math.isfinite(item):
            return None
        if isinstance(item, dict):
            return {str(key): json_safe(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [json_safe(child) for child in item]
        return item

    return json.dumps(
        json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_new(path: Path, content: bytes, *, readonly: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as file:
        file.write(content)
    if readonly:
        path.chmod(0o444)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Required prepared input is missing: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _dependency_fingerprint() -> dict[str, Any]:
    requirements_path = PROJECT_ROOT / "requirements-science.txt"
    if not requirements_path.is_file():
        raise FileNotFoundError(f"Missing dependency specification: {requirements_path}")
    files = [requirements_path]
    lock_path = PROJECT_ROOT / "requirements-science-lock.txt"
    if lock_path.is_file():
        files.append(lock_path)
    return {
        "files": {
            path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path)
            for path in files
        },
    }


def _element_data(record: dict[str, Any]) -> tuple[str | None, str | None, list[str], str | None]:
    """Return formula and reduced key from the source atom element counts."""
    atoms = record.get("atoms")
    if not isinstance(atoms, dict) or not isinstance(atoms.get("elements"), list):
        return None, None, [], "missing_atoms_elements"
    elements = atoms["elements"]
    if not elements or any(not isinstance(element, str) or not element for element in elements):
        return None, None, [], "invalid_atoms_elements"
    counts = Counter(elements)
    try:
        from jarvis.core.composition import Composition

        composition = Composition(dict(counts), sort=True)
        formula = composition.formula
        reduced_formula = composition.reduced_formula
    except Exception as error:  # malformed or unsupported element symbols stay in the audit.
        return None, None, sorted(counts), f"invalid_composition:{type(error).__name__}"
    return formula, reduced_formula, sorted(counts), None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if value is None or (isinstance(value, str) and value.strip().lower() in {"", "na", "n/a", "none", "null"}):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _family(elements: set[str]) -> str:
    if "O" in elements and not (elements & (ANION_LABELS - {"O"})):
        return "oxide"
    if elements & {"S", "Se"} and not (elements & ({"O"} | HALOGENS_AND_NITROGEN)):
        return "chalcogenide"
    return "other"


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    formula, reduced_formula, elements, composition_issue = _element_data(record)
    element_set = set(elements)
    jid_value = record.get("jid")
    jid = str(jid_value).strip() if jid_value is not None else ""
    family = _family(element_set)

    raw_ehull = _finite_number(record.get("ehull"))  # Never substitute formation energy.
    ehull = raw_ehull
    ehull_valid = raw_ehull is not None
    rounded_to_zero = False
    ehull_invalid_reason = ""
    if raw_ehull is not None and raw_ehull < -0.000001:
        ehull = None
        ehull_valid = False
        ehull_invalid_reason = "below_minus_1e-6_ev_per_atom"
    elif raw_ehull is not None and raw_ehull < 0.0:
        ehull = 0.0
        rounded_to_zero = True

    design_exclusions: list[str] = []
    if len(element_set) < 2:
        design_exclusions.append("fewer_than_two_elements")
    banned = sorted(element_set & EXCLUDED_ELEMENTS)
    if banned:
        design_exclusions.append("contains_excluded_element:" + ",".join(banned))

    record_quality = composition_issue or ""
    if not jid:
        record_quality = ";".join(filter(None, [record_quality, "missing_jid"]))

    return {
        "jid": jid,
        "formula": formula or "",
        "reduced_formula": reduced_formula or "",
        "elements": ",".join(elements),
        "n_elements": len(element_set),
        "family": family,
        "opt_gap_ev": _finite_number(record.get("optb88vdw_bandgap")),
        "mbj_gap_ev": _finite_number(record.get("mbj_bandgap")),
        "ehull_ev_atom": ehull,
        "ehull_valid": ehull_valid,
        "ehull_rounded_to_zero": rounded_to_zero,
        "ehull_invalid_reason": ehull_invalid_reason,
        "excluded": bool(design_exclusions),
        "exclusion_reason": ";".join(design_exclusions),
        "record_quality_issue": record_quality,
        "is_representative": False,
        "representative_reason": "",
        "split": "",
    }


def _representatives(rows: list[dict[str, Any]]) -> None:
    by_formula: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["reduced_formula"] and row["jid"]:
            by_formula[row["reduced_formula"]].append(row)

    for formula_rows in by_formula.values():
        valid = [row for row in formula_rows if row["ehull_valid"]]
        if valid:
            minimum = min(row["ehull_ev_atom"] for row in valid)
            tied = [row for row in valid if row["ehull_ev_atom"] == minimum]
            selected = min(tied, key=lambda row: row["jid"])
            reason = "lowest_valid_ehull_then_lexicographic_jid;gaps_not_considered"
        else:
            selected = min(formula_rows, key=lambda row: row["jid"])
            reason = "no_valid_ehull;lexicographic_jid;gaps_not_considered"
        selected["is_representative"] = True
        selected["representative_reason"] = reason
        for row in formula_rows:
            if row is not selected:
                row["representative_reason"] = "not_selected_by_frozen_ehull_rule"


def _assign_splits(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row["reduced_formula"] and not row["excluded"] and row["family"] != "other":
            groups[row["family"]].add(row["reduced_formula"])

    assignment: dict[tuple[str, str], str] = {}
    for family in sorted(groups):
        formulas = sorted(groups[family])
        rng = np.random.default_rng(SPLIT_SEED)
        shuffled = list(np.asarray(formulas, dtype=object)[rng.permutation(len(formulas))])
        discovery_count = math.floor(DISCOVERY_FRACTION * len(formulas))
        for index, formula in enumerate(shuffled):
            assignment[(family, str(formula))] = "discovery" if index < discovery_count else "holdout"

    for row in rows:
        if row["reduced_formula"] and not row["excluded"] and row["family"] != "other":
            row["split"] = assignment[(row["family"], row["reduced_formula"])]
    return [
        {"family": family, "reduced_formula": formula, "split": split}
        for (family, formula), split in sorted(assignment.items())
    ]


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDNAMES, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _metadata(rows: list[dict[str, Any]], raw_record_count: int) -> dict[str, Any]:
    representatives = [row for row in rows if row["is_representative"]]
    eligible = [row for row in representatives if not row["excluded"] and row["family"] in PRIMARY_FAMILIES]
    families: dict[str, Any] = {}
    for family in PRIMARY_FAMILIES:
        families[family] = {}
        for split in ("discovery", "holdout"):
            group = [row for row in eligible if row["family"] == family and row["split"] == split]
            n_total = len(group)
            n_opt = sum(row["opt_gap_ev"] is not None for row in group)
            n_ehull = sum(row["ehull_valid"] for row in group)
            n_evaluable = sum(row["opt_gap_ev"] is not None and row["ehull_valid"] for row in group)
            families[family][split] = {
                "n_total": n_total,
                "n_evaluable": n_evaluable,
                "n_opt_gap_missing": n_total - n_opt,
                "n_ehull_missing_or_invalid": n_total - n_ehull,
                "opt_gap_coverage": n_opt / n_total if n_total else None,
                "ehull_coverage": n_ehull / n_total if n_total else None,
                "primary_coverage": n_evaluable / n_total if n_total else None,
            }
    return {
        "schema_version": "nova.metadata.v1",
        "dataset": DATASET_NAME,
        "raw_record_count": raw_record_count,
        "normalized_row_count": len(rows),
        "representative_count": len(representatives),
        "eligible_primary_family_representatives": len(eligible),
        "families": families,
        "holdout_access": "coverage_and_counts_only; no values, rates, passes, or direction",
    }


def _protocol(dataset_sha256: str, cleaning_sha256: str, dependency: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "nova.protocol.v1",
        "protocol_id": "family_screen_v1",
        "status": "frozen_by_prepare_before_any_screen_result",
        "dataset": DATASET_NAME,
        "dataset_sha256": dataset_sha256,
        "cleaning_script_sha256": cleaning_sha256,
        "dependency_spec": dependency,
        "prefrozen_human_protocol_document_sha256": PREFROZEN_PROTOCOL_DOCUMENT_SHA256,
        "question": "Under the fixed JARVIS snapshot and screening rule, how do observed composition pass rates compare between oxide and chalcogenide families?",
        "hypotheses": {
            "h1": "chalcogenide observed pass rate minus oxide observed pass rate > 0",
            "h2": "chalcogenide observed pass rate minus oxide observed pass rate <= 0",
        },
        "families": {
            "oxide": "contains O and contains none of S, Se, N, F, Cl, Br, I",
            "chalcogenide": "contains S or Se and contains none of O, N, F, Cl, Br, I",
            "other": "all remaining compositions; excluded from the comparison",
        },
        "design_exclusions": {
            "elements": sorted(EXCLUDED_ELEMENTS),
            "minimum_element_count": 2,
            "interpretation": "project composition design constraint; not a toxicity or safety determination",
        },
        "representative_rule": "per reduced composition, choose the lowest finite ehull >= -1e-6 eV/atom; set values in [-1e-6,0) to zero; ties use lexicographically smallest jid; if every ehull is invalid or missing choose lexicographically smallest jid and retain as unevaluable; never inspect a band gap when selecting",
        "primary_method": "OPT band gap only; source key optb88vdw_bandgap; never coalesce with MBJ",
        "primary_endpoint": {
            "opt_gap_ev_inclusive": [1.1, 1.8],
            "ehull_ev_atom_max_inclusive": 0.05,
            "ehull_unit": "eV/atom",
            "observable": "finite OPT band gap and finite valid ehull",
            "pass": "both inclusive threshold conditions hold",
            "unknown_handling": "not evaluable; reported through complete-case rate and worst-case missingness bounds",
        },
        "estimand": "equal-weight reduced compositions represented by each composition's lowest recorded valid-ehull structure in this snapshot; not all polymorphs or all real materials",
        "split": {
            "unit": "reduced_formula within family",
            "seed": SPLIT_SEED,
            "discovery_fraction": DISCOVERY_FRACTION,
            "method": "sorted eligible composition keys permuted by NumPy default_rng(seed) independently per family; floor(0.70*n) discovery; remaining keys holdout",
            "holdout_execution_allowed": False,
        },
        "inference": {
            "bootstrap_replicates": 2_000,
            "bootstrap_seed": 1_729,
            "interval": "95% percentile; composition-level resampling with replacement within each family",
            "quality_gate_min_evaluable_per_family": 40,
            "quality_gate_min_primary_coverage": 0.80,
            "quality_gate_non_degenerate": "both family endpoints must contain pass and fail compositions",
            "status_rules": {
                "supported_in_snapshot": "all quality gates pass and interval lower bound > 0",
                "reversed_in_snapshot": "all quality gates pass and interval upper bound < 0",
                "inconclusive": "quality gates pass but interval includes zero or a family endpoint is degenerate",
                "data_limited": "any sample size or coverage gate fails",
            },
            "interval_scope": "resampling stability in this snapshot, not population uncertainty for real materials",
        },
        "source_semantics": {
            "ehull_source_key": "ehull",
            "formation_energy_substitution": False,
            "gap_source_key": "optb88vdw_bandgap",
            "units_and_definition": "JARVIS energy above hull in eV/atom; see cited NIST JARVIS methods paper",
            "reference": "https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=936649",
        },
        "omnigent": {
            "status": "not_installed_or_verified_by_science_engine_at_protocol_freeze",
            "version": None,
        },
    }


def _jarvis_source() -> tuple[Any, str, dict[str, Any]]:
    try:
        from jarvis.db.figshare import get_db_info
    except ImportError as error:
        raise RuntimeError("Install requirements-science.txt before preparing the JARVIS snapshot") from error
    info = get_db_info()
    if DATASET_NAME not in info or len(info[DATASET_NAME]) < 4:
        raise RuntimeError("Installed jarvis-tools does not define dft_3d in get_db_info()")
    selected = info[DATASET_NAME]
    source = {
        "download_url": selected[0],
        "inner_json_member": selected[1],
        "library_description": selected[2],
        "reference": selected[3],
        "figshare_file_id": selected[0].rstrip("/").rsplit("/", 1)[-1],
    }
    return selected, str(selected[1]), source


def _source_license(source_url: str) -> dict[str, str]:
    return {
        "license": "CC BY 4.0",
        "figshare_article": "https://doi.org/10.6084/m9.figshare.6815699",
        "source_url": source_url,
        "attribution": "JARVIS-DFT, NIST; source article/version recorded in this manifest",
    }


def _load_download_sidecar(cache_dir: Path, js_tag: str, archive_sha: str) -> dict[str, Any]:
    sidecar = cache_dir / f"{js_tag}.download.json"
    if not sidecar.exists():
        return {}
    value = _read_json(sidecar)
    declared_sha = value.get("archive_sha256")
    if declared_sha and declared_sha != archive_sha:
        raise ValueError("JARVIS download sidecar SHA does not match cached ZIP")
    declared_size = value.get("size_bytes")
    if declared_size is not None and declared_size != (cache_dir / f"{js_tag}.zip").stat().st_size:
        raise ValueError("JARVIS download sidecar size does not match cached ZIP")
    return value


def _validate_project_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError as error:
        raise ValueError("Cache directory must be inside the project workspace") from error
    return resolved


def prepare_dataset(cache_dir: str | Path = DEFAULT_CACHE_DIR) -> dict[str, Any]:
    """Download (through jarvis-tools) and freeze the first local snapshot.

    Existing frozen artifacts are never overwritten. The caller should retain
    the source ZIP and JSON as local data; this function does not push data.
    """
    if MANIFEST_PATH.exists() or PROTOCOL_PATH.exists():
        raise FileExistsError("A frozen NOVA-MAT protocol already exists; refusing to overwrite it")
    frozen_candidates = [
        RAW_ROOT / "source.zip",
        RAW_ROOT / "source.json",
        AUDIT_ROOT / "records.csv",
        AUDIT_ROOT / "compositions.csv",
        AUDIT_ROOT / "metadata.json",
    ]
    if any(path.exists() for path in frozen_candidates):
        raise FileExistsError("Prepared NOVA-MAT inputs already exist; refusing to overwrite frozen data")

    cache_dir = _validate_project_path(Path(cache_dir))
    cache_dir.mkdir(parents=True, exist_ok=True)
    selected, js_tag, source = _jarvis_source()
    archive_path = cache_dir / f"{js_tag}.zip"
    download_started_utc = _utc_now()

    try:
        from jarvis.db.figshare import data as jarvis_data
    except ImportError as error:
        raise RuntimeError("Install requirements-science.txt before preparing the JARVIS snapshot") from error
    raw_records = jarvis_data(DATASET_NAME, store_dir=str(cache_dir))
    if not isinstance(raw_records, list) or not archive_path.is_file():
        raise RuntimeError("jarvis-tools did not return dft_3d records and its source ZIP")
    if any(not isinstance(record, dict) for record in raw_records):
        raise ValueError("JARVIS dft_3d must be a list of record objects")

    archive_bytes = archive_path.read_bytes()
    archive_sha = _sha256_bytes(archive_bytes)
    with zipfile.ZipFile(archive_path) as archive:
        try:
            original_json_bytes = archive.read(js_tag)
        except KeyError as error:
            raise ValueError(f"Source ZIP has no expected member {js_tag!r}") from error
    source_json_sha = _sha256_bytes(original_json_bytes)
    canonical_records = _json_bytes(raw_records)
    canonical_sha = _sha256_bytes(canonical_records)
    sidecar = _load_download_sidecar(cache_dir, js_tag, archive_sha)
    if sidecar.get("source_url") and sidecar["source_url"] != source["download_url"]:
        raise ValueError("Cached JARVIS archive was fetched from a URL other than installed get_db_info() selects")
    stat = archive_path.stat()
    archive_mtime_utc = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    download_completed_utc = sidecar.get("download_completed_at_utc")

    # Freeze the complete statistical and data-selection protocol before any
    # property values are cleaned or summarized.
    cleaning_sha = sha256_file(Path(__file__).resolve())
    dependency = _dependency_fingerprint()
    try:
        jarvis_version = importlib.metadata.version("jarvis-tools")
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError("jarvis-tools package metadata is unavailable; cannot freeze a reproducible manifest") from error
    protocol = _protocol(archive_sha, cleaning_sha, dependency)
    protocol_bytes = _json_bytes(protocol) + b"\n"
    protocol_sha = _sha256_bytes(protocol_bytes)
    _write_new(PROTOCOL_PATH, protocol_bytes, readonly=True)

    normalized_rows = [_normalize_record(record) for record in raw_records]
    _representatives(normalized_rows)
    split_assignments = _assign_splits(normalized_rows)
    split_sha = _sha256_bytes(_json_bytes(split_assignments))
    audit_rows_bytes = _csv_bytes(normalized_rows)
    composition_rows = [row for row in normalized_rows if row["is_representative"]]
    composition_csv_bytes = _csv_bytes(composition_rows)
    metadata = _metadata(normalized_rows, len(raw_records))
    metadata_bytes = _json_bytes(metadata) + b"\n"

    raw_zip_name = f"{Path(js_tag).stem}.{archive_sha[:12]}.zip"
    raw_json_name = f"{Path(js_tag).name}.{source_json_sha[:12]}"
    manifest = {
        "schema_version": "nova.manifest.v1",
        "dataset": DATASET_NAME,
        "source": source,
        "source_license": _source_license(source["download_url"]),
        "download_completed_at_utc": download_completed_utc,
        "download_timestamp_source": sidecar.get("time_source", "not supplied; archive filesystem mtime is recorded separately"),
        "download_started_by_prepare_at_utc": download_started_utc,
        "archive_local_mtime_utc": archive_mtime_utc,
        "archive_size_bytes": len(archive_bytes),
        "original_download_zip": f"raw/{raw_zip_name}",
        "original_download_zip_sha256": archive_sha,
        "original_inner_json": f"raw/{raw_json_name}",
        "original_inner_json_sha256": source_json_sha,
        "canonical_jarvis_records_sha256": canonical_sha,
        "canonical_jarvis_records_serialization": "UTF-8 JSON sorted recursively by object key, compact separators; non-finite numeric values are serialized as null; distinct from original ZIP and original inner JSON byte hashes",
        "raw_record_count": len(raw_records),
        "jarvis_tools_version": jarvis_version,
        "omnigent": {
            "status": "not_installed_or_verified_by_science_engine_at_protocol_freeze",
            "version_or_commit": None,
        },
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "dependency_spec": dependency,
        "cleaning_script_sha256": cleaning_sha,
        "protocol_file": "protocol.json",
        "protocol_sha256": protocol_sha,
        "full_audit_csv": "audit/records.csv",
        "full_audit_csv_sha256": _sha256_bytes(audit_rows_bytes),
        "representative_compositions_csv": "audit/compositions.csv",
        "representative_compositions_csv_sha256": _sha256_bytes(composition_csv_bytes),
        "metadata_file": "audit/metadata.json",
        "metadata_sha256": _sha256_bytes(metadata_bytes),
        "split_assignment_sha256": split_sha,
        "split_seed": SPLIT_SEED,
        "split_rule": protocol["split"],
        "exclusion_rules": protocol["design_exclusions"],
        "representative_rule": protocol["representative_rule"],
        "field_mapping": {
            "jid": "jid",
            "elements": "atoms.elements; counts computed from site symbols",
            "reduced_formula": "jarvis.core.composition.Composition(element_counts).reduced_formula",
            "opt_gap_ev": "optb88vdw_bandgap",
            "mbj_gap_ev": "mbj_bandgap",
            "ehull_ev_atom": "ehull; no formation-energy fallback",
        },
        "units": {
            "opt_gap_ev": "eV",
            "mbj_gap_ev": "eV",
            "ehull_ev_atom": "eV/atom",
            "ehull_definition_reference": protocol["source_semantics"]["reference"],
        },
        "preparation_counts": {
            "normalized_rows": len(normalized_rows),
            "representative_structures": len(composition_rows),
            "eligible_primary_family_compositions": metadata["eligible_primary_family_representatives"],
            "composition_quality_issues": sum(bool(row["record_quality_issue"]) for row in normalized_rows),
            "excluded_structure_rows": sum(row["excluded"] for row in normalized_rows),
            "missing_or_invalid_formula_rows": sum(not row["reduced_formula"] for row in normalized_rows),
            "missing_jid_rows": sum("missing_jid" in row["record_quality_issue"] for row in normalized_rows),
            "ehull_missing_rows": sum(row["ehull_invalid_reason"] == "" and not row["ehull_valid"] for row in normalized_rows),
            "ehull_below_minus_1e_6_rows": sum(row["ehull_invalid_reason"] == "below_minus_1e-6_ev_per_atom" for row in normalized_rows),
            "ehull_rounded_to_zero_rows": sum(row["ehull_rounded_to_zero"] for row in normalized_rows),
        },
        "exclusion_audit": _exclusion_audit(normalized_rows),
        "source_field_presence_counts": {
            key: sum(key in record for record in raw_records)
            for key in ("ehull", "optb88vdw_bandgap", "mbj_bandgap")
        },
        "holdout_visibility": "read_metadata exposes only family/split counts and missingness coverage; the discovery adapter rejects holdout",
    }
    manifest_bytes = _json_bytes(manifest) + b"\n"

    # Write the frozen artifacts exclusively. A partial failure remains visible
    # and a retry refuses to overwrite any file already materialized.
    _write_new(RAW_ROOT / raw_zip_name, archive_bytes, readonly=True)
    _write_new(RAW_ROOT / raw_json_name, original_json_bytes, readonly=True)
    _write_new(AUDIT_ROOT / "records.csv", audit_rows_bytes)
    _write_new(AUDIT_ROOT / "compositions.csv", composition_csv_bytes, readonly=True)
    _write_new(AUDIT_ROOT / "metadata.json", metadata_bytes, readonly=True)
    _write_new(MANIFEST_PATH, manifest_bytes, readonly=True)
    return manifest


def read_metadata() -> dict[str, Any]:
    """Return count and coverage metadata, including holdout coverage only."""
    manifest = _read_json(MANIFEST_PATH)
    metadata_path = DATA_ROOT / "audit" / "metadata.json"
    expected_sha = manifest.get("metadata_sha256")
    if not expected_sha or sha256_file(metadata_path) != expected_sha:
        raise ValueError("Prepared metadata SHA does not match the frozen manifest")
    metadata = _read_json(metadata_path)
    if metadata.get("holdout_access") != "coverage_and_counts_only; no values, rates, passes, or direction":
        raise ValueError("Prepared metadata violates the holdout information boundary")
    return metadata


def _read_prepared_compositions() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Internal loader. Contains holdout properties; never expose to an agent."""
    manifest = _read_json(MANIFEST_PATH)
    protocol_path = DATA_ROOT / manifest["protocol_file"]
    protocol_bytes = protocol_path.read_bytes()
    if _sha256_bytes(protocol_bytes) != manifest.get("protocol_sha256"):
        raise ValueError("Frozen protocol hash mismatch")
    protocol = _read_json(protocol_path)
    if protocol.get("dataset_sha256") != manifest.get("original_download_zip_sha256"):
        raise ValueError("Protocol and manifest point at different source snapshots")
    if sha256_file(Path(__file__).resolve()) != manifest.get("cleaning_script_sha256"):
        raise ValueError("Cleaning code changed after protocol freeze")
    if _dependency_fingerprint() != manifest.get("dependency_spec"):
        raise ValueError("Dependency specification changed after protocol freeze")

    raw_zip = PROJECT_ROOT / "data" / manifest["original_download_zip"]
    raw_json = PROJECT_ROOT / "data" / manifest["original_inner_json"]
    if sha256_file(raw_zip) != manifest.get("original_download_zip_sha256"):
        raise ValueError("Frozen source ZIP hash mismatch")
    if sha256_file(raw_json) != manifest.get("original_inner_json_sha256"):
        raise ValueError("Frozen source JSON hash mismatch")

    csv_path = DATA_ROOT / manifest["representative_compositions_csv"]
    if sha256_file(csv_path) != manifest.get("representative_compositions_csv_sha256"):
        raise ValueError("Frozen representative data hash mismatch")
    with csv_path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    return rows, manifest, protocol


def _exclusion_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = {
        "fewer_than_two_elements": lambda row: "fewer_than_two_elements" in row["exclusion_reason"],
        "contains_excluded_element": lambda row: "contains_excluded_element:" in row["exclusion_reason"],
    }
    audit: dict[str, Any] = {}
    for name, predicate in reasons.items():
        selected = [row for row in rows if predicate(row)]
        audit[name] = {
            "structure_rows": len(selected),
            "unique_reduced_compositions": len({row["reduced_formula"] for row in selected if row["reduced_formula"]}),
        }
    return audit
