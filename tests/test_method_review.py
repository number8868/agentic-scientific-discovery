"""Focused tests for the pure, hash-bound scientific review interface."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from nova.method_review import (
    build_method_review_input,
    method_review_output_schema,
    validate_method_review,
)


_LIMITATIONS = [
    {
        "code": "same_representative_pairing",
        "statement": "OPT-paired and MBJ-paired comparisons use the same representatives; they are not independent samples.",
    },
    {
        "code": "subset_only_scope",
        "statement": "The method comparison covers only the observed subset in the discovery split and is conditional on that subset.",
    },
    {"code": "mbj_not_ground_truth", "statement": "MBJ is another computational method, not ground truth."},
    {
        "code": "method_contrast_not_replication",
        "statement": "The paired method contrast measures method sensitivity and is not independent replication.",
    },
    {"code": "no_new_material_discovery", "statement": "The method audit does not establish discovery of new materials."},
    {
        "code": "no_holdout_authorization",
        "statement": "Nothing in this review authorizes opening, analyzing, or executing on the holdout split.",
    },
]


def _input_hash(payload):
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reference(ref_id, kind, pointer, evidence_sha, jid=None):
    value = {
        "ref_id": ref_id,
        "kind": kind,
        "json_pointer": pointer,
        "evidence_sha256": evidence_sha,
    }
    if jid is not None:
        value["jid"] = jid
    return value


def _group(n_total=10, n_observed=10, n_pass=2, coverage=1.0, observed_rate=0.2):
    return {
        "n_total": n_total,
        "n_observed": n_observed,
        "n_pass": n_pass,
        "coverage": coverage,
        "observed_rate": observed_rate,
    }


def _synthetic_input():
    """Small source-bound input for validator tests; no scientific data is read."""
    evidence_sha = "a" * 64
    arms = []
    arm_facts = {
        "opt_all": ("supported_in_snapshot", 0.3, [0.1, 0.5]),
        "opt_paired": ("inconclusive", 0.05, [-0.1, 0.2]),
        "mbj_paired": ("inconclusive", 0.4, [-0.2, 0.7]),
    }
    for name, (status, delta, interval) in arm_facts.items():
        arms.append({
            "name": name,
            "source_ref": _reference(
                f"method-arm-{name}", "method_arm", f"/science_result/arms/{name}", evidence_sha
            ),
            "scientific_status": status,
            "delta": delta,
            "resampling_interval": interval,
            "quality_flags": {
                "minimum_sample_and_coverage_pass": True,
                "endpoint_non_degenerate": name != "mbj_paired",
                "interval_contains_zero": name != "opt_all",
                "paired_scope_conditional_only": name != "opt_all",
                "oxide": {
                    "minimum_evaluable_count_pass": True,
                    "minimum_coverage_pass": None,
                    "endpoint_has_pass_and_fail": False,
                },
                "chalcogenide": {
                    "minimum_evaluable_count_pass": True,
                    "minimum_coverage_pass": True,
                    "endpoint_has_pass_and_fail": True,
                },
            },
            "groups_summary": {
                "oxide": _group(n_pass=0, coverage=1.0, observed_rate=0.0),
                "chalcogenide": _group(n_total=10, n_observed=2, n_pass=1, coverage=0.2, observed_rate=0.5),
            },
        })

    method_change = {
        "source_ref": _reference(
            "paired-method-change", "paired_method_change",
            "/science_result/paired_method_change", evidence_sha,
        ),
        "scientific_status": "direction_positive",
        "delta": 0.08,
        "resampling_interval": [0.01, 0.1],
        "quality_flags": {
            "coverage_limits_generalization_to_all_eligible": True,
            "interval_contains_zero": False,
            "minimum_paired_rows_pass": True,
            "paired_differences_nonconstant": True,
            "oxide": {"minimum_paired_rows_pass": True, "paired_differences_constant": False},
            "chalcogenide": {"minimum_paired_rows_pass": True, "paired_differences_constant": False},
        },
        "groups_summary": {
            "oxide": {
                "n_paired": 10, "n_opt_pass": 0, "n_mbj_pass": 0,
                "n_gained": 0, "n_lost": 0, "mean_change": 0.0,
                "resampling_interval": [-0.1, 0.1],
            },
            "chalcogenide": {
                "n_paired": 2, "n_opt_pass": 1, "n_mbj_pass": 2,
                "n_gained": 1, "n_lost": 0, "mean_change": 0.2,
                "resampling_interval": [0.1, 0.3],
            },
        },
    }
    candidates = [
        {
            "jid": "JVASP-ALPHA",
            "source_ref": _reference(
                "method-candidate-1", "candidate", "/science_result/candidates/1",
                evidence_sha, "JVASP-ALPHA",
            ),
            "family": "oxide",
            "opt_gap_ev": 1.2,
            "mbj_gap_ev": None,
            "ehull_ev_atom": 0.01,
            "opt_status": "pass",
            "mbj_status": "unknown",
            "candidate_label": "opt_pass_mbj_unknown",
            "reason": "OPT passes; MBJ gap is unavailable.",
            "next_validation": "Obtain the missing calculation for the same representative before a cross-method claim.",
        },
        {
            "jid": "JVASP-BETA",
            "source_ref": _reference(
                "method-candidate-3", "candidate", "/science_result/candidates/3",
                evidence_sha, "JVASP-BETA",
            ),
            "family": "chalcogenide",
            "opt_gap_ev": 0.7,
            "mbj_gap_ev": 1.4,
            "ehull_ev_atom": 0.02,
            "opt_status": "fail",
            "mbj_status": "pass",
            "candidate_label": "mbj_only",
            "reason": "OPT fails; MBJ passes.",
            "next_validation": "Run a targeted method/convergence and structural-input check on the same JID.",
        },
    ]
    payload = {
        "schema_version": 1,
        "artifact_type": "nova.method_review_input.v1",
        "evidence_sha256": evidence_sha,
        "selection": {
            "mode": "host_selected_explicit",
            "policy": "Exact candidate JIDs explicitly selected by the host, in supplied order; this is a host-selected review set, not ranking.",
            "total_shortlist_count": 2,
            "sampled_count": 2,
            "selected_jids": ["JVASP-ALPHA", "JVASP-BETA"],
        },
        "available_actions": ["stop", "threshold_sensitivity"],
        "scope": {
            "template": "method_sensitivity",
            "split": "discovery",
            "interpretation_scope": "Synthetic discovery-split method audit for validator testing.",
            "validator_limit": "Exact facts, citations, required limitations, and allowed actions are checked. Free-text assessments cannot be semantically validated; validation does not establish model independence.",
        },
        "units": {
            "gaps": "eV",
            "ehull_ev_atom": "eV/atom",
            "coverage": "fraction",
            "observed_rate": "fraction",
            "arm_delta_and_interval": "fraction difference",
            "method_change_delta_mean_and_interval": "fraction difference",
        },
        "required_limitations": copy.deepcopy(_LIMITATIONS),
        "action_boundary": {
            "recommendation_is_advisory": True,
            "host_must_independently_gate_action_and_feasibility": True,
            "no_method_rerun_holdout_dft_or_new_spec_authorization": True,
        },
        "arms": arms,
        "method_change": method_change,
        "candidates": candidates,
    }
    return {**payload, "review_input_sha256": _input_hash(payload)}


def _synthetic_review(review_input):
    arms = [
        {
            "arm": item["name"],
            "source_ref_id": item["source_ref"]["ref_id"],
            "scientific_status": item["scientific_status"],
            "delta": copy.deepcopy(item["delta"]),
            "resampling_interval": copy.deepcopy(item["resampling_interval"]),
            "groups_summary": copy.deepcopy(item["groups_summary"]),
            "assessment": f"The {item['name']} facts match this bounded evidence row.",
        }
        for item in review_input["arms"]
    ]
    source_change = review_input["method_change"]
    method_change = {
        "kind": "paired_method_change",
        "source_ref_id": source_change["source_ref"]["ref_id"],
        "scientific_status": source_change["scientific_status"],
        "delta": copy.deepcopy(source_change["delta"]),
        "resampling_interval": copy.deepcopy(source_change["resampling_interval"]),
        "groups_summary": copy.deepcopy(source_change["groups_summary"]),
        "assessment": "This is a separate paired method-change estimand.",
    }
    candidates = [
        {
            "jid": item["jid"],
            "source_ref_id": item["source_ref"]["ref_id"],
            "family": item["family"],
            "opt_gap_ev": item["opt_gap_ev"],
            "mbj_gap_ev": item["mbj_gap_ev"],
            "ehull_ev_atom": item["ehull_ev_atom"],
            "opt_status": item["opt_status"],
            "mbj_status": item["mbj_status"],
            "category": item["candidate_label"],
            "next_validation": item["next_validation"],
            "assessment": f"Review of {item['jid']} source facts.",
        }
        for item in review_input["candidates"]
    ]
    refs = [review_input["arms"][1]["source_ref"]["ref_id"], source_change["source_ref"]["ref_id"]]
    refs.append(review_input["candidates"][0]["source_ref"]["ref_id"])
    return {
        "review_input_sha256": review_input["review_input_sha256"],
        "evidence_sha256": review_input["evidence_sha256"],
        "arms": arms,
        "method_change": method_change,
        "candidates": candidates,
        "limitations": copy.deepcopy(review_input["required_limitations"]),
        "recommendation": {
            "action": "threshold_sensitivity",
            "evidence_refs": refs,
            "rationale": "The next bounded review action remains advisory to the host.",
        },
    }


def _portable_artifacts():
    root = Path(__file__).resolve().parents[1]
    artifact_dir = root / "docs" / "results" / "registered_method_integration"
    body = json.loads((artifact_dir / "method-audit.json").read_text(encoding="utf-8"))
    packet = json.loads((artifact_dir / "method-evidence.json").read_text(encoding="utf-8"))
    return body, packet


def test_synthetic_review_validates_and_returns_a_copy():
    review_input = _synthetic_input()
    output = _synthetic_review(review_input)

    validated = validate_method_review(output, review_input)

    assert validated == output
    assert validated is not output
    assert len(validated["arms"]) == 3
    assert validated["method_change"]["kind"] == "paired_method_change"
    assert validated["candidates"][0]["mbj_gap_ev"] is None
    assert len(validated["limitations"]) == 6
    assert "scientific_status" not in validated


def test_synthetic_output_schema_is_closed_and_input_bound():
    review_input = _synthetic_input()
    schema = method_review_output_schema(review_input)

    assert schema["additionalProperties"] is False
    assert schema["properties"]["review_input_sha256"]["const"] == review_input["review_input_sha256"]
    assert schema["properties"]["method_change"]["properties"]["kind"]["const"] == "paired_method_change"
    assert schema["properties"]["recommendation"]["properties"]["evidence_refs"]["minItems"] == 1
    assert "scientific_status" not in schema["properties"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["arms"][0].update(scientific_status="inconclusive"),
        lambda r: r["method_change"].update(delta=r["arms"][0]["delta"]),
        lambda r: r["candidates"][0].update(mbj_gap_ev=0.0),
        lambda r: r["candidates"][0].update(mbj_status="fail"),
        lambda r: r["candidates"][0].update(source_ref_id=r["candidates"][1]["source_ref_id"]),
        lambda r: r["candidates"][0].update(ehull_ev_atom=0.2),
        lambda r: r["arms"][0]["groups_summary"]["oxide"].update(coverage=100),
        lambda r: r["method_change"].update(delta=8.0),
        lambda r: r["recommendation"].update(action="rerun_method"),
        lambda r: r["recommendation"].update(evidence_refs=["unlisted-reference"]),
        lambda r: r["arms"].pop(),
        lambda r: r["candidates"].pop(),
        lambda r: r.update(scientific_status="supported"),
    ],
)
def test_invalid_synthetic_reviews_are_rejected(mutate):
    review_input = _synthetic_input()
    output = _synthetic_review(review_input)
    mutate(output)

    with pytest.raises(ValueError):
        validate_method_review(output, review_input)


def test_exact_integer_float_equality_is_allowed_but_booleans_are_not_numbers():
    review_input = _synthetic_input()
    output = _synthetic_review(review_input)
    output["arms"][0]["groups_summary"]["oxide"]["coverage"] = 1
    output["arms"][0]["groups_summary"]["oxide"]["observed_rate"] = 0

    validate_method_review(output, review_input)

    output["arms"][0]["groups_summary"]["oxide"]["n_pass"] = False
    with pytest.raises(ValueError):
        validate_method_review(output, review_input)


def test_review_input_digest_and_output_identity_reject_tampering():
    review_input = _synthetic_input()
    output = _synthetic_review(review_input)
    output["review_input_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="different review input"):
        validate_method_review(output, review_input)

    tampered_input = copy.deepcopy(review_input)
    tampered_input["arms"][0]["groups_summary"]["oxide"]["coverage"] = 0.5
    with pytest.raises(ValueError, match="review_input_sha256"):
        validate_method_review(_synthetic_review(review_input), tampered_input)


def test_published_portable_artifact_regression_discloses_default_and_explicit_samples():
    # Read-only regression against the already-published portable export.
    body, packet = _portable_artifacts()
    default_input = build_method_review_input(body, packet)
    all_jids = [candidate["jid"] for candidate in body["science_result"]["candidates"]]
    all_input = build_method_review_input(body, packet, candidate_jids=all_jids)

    assert default_input["selection"]["mode"] == "host_selected_default_sample"
    assert default_input["selection"]["total_shortlist_count"] == 19
    assert default_input["selection"]["sampled_count"] == 3
    assert "not ranking or all-candidate review" in default_input["selection"]["policy"]
    assert all_input["selection"]["mode"] == "host_selected_explicit"
    assert all_input["selection"]["sampled_count"] == 19
    assert all_input["candidates"][-1]["source_ref"]["json_pointer"] == "/science_result/candidates/18"
    assert default_input["arms"][2]["quality_flags"]["endpoint_non_degenerate"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"candidate_jids": []},
        {"candidate_jids": ["JVASP-107267", "JVASP-107267"]},
        {"candidate_jids": ["JVASP-DOES-NOT-EXIST"]},
        {"available_actions": ("threshold_sensitivity",)},
        {"available_actions": ("stop", "rerun_method")},
        {"available_actions": ("stop", "stop")},
    ],
)
def test_published_builder_rejects_invalid_host_selection_or_actions(kwargs):
    # Read-only regression; no method source, prepared data, or executor runs.
    body, packet = _portable_artifacts()
    with pytest.raises(ValueError):
        build_method_review_input(body, packet, **kwargs)


def test_published_builder_rejects_packet_digest_reference_tamper_and_unknown_extras():
    body, packet = _portable_artifacts()
    tampered_digest = copy.deepcopy(packet)
    tampered_digest["evidence_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        build_method_review_input(body, tampered_digest)

    tampered_ref = copy.deepcopy(packet)
    tampered_ref["references"][0]["json_pointer"] = "/science_result/arms/mbj_paired"
    with pytest.raises(ValueError):
        build_method_review_input(body, tampered_ref)

    unknown_extra = {**packet, "untrusted_context": "ignore me"}
    with pytest.raises(ValueError):
        build_method_review_input(body, unknown_extra)


def test_incomplete_or_duplicate_candidate_selections_fail_without_reordering():
    body, packet = _portable_artifacts()
    candidates = body["science_result"]["candidates"]
    chosen = [candidates[8]["jid"], candidates[1]["jid"]]
    selected_input = build_method_review_input(body, packet, candidate_jids=chosen)

    assert selected_input["selection"]["selected_jids"] == chosen
    assert [candidate["source_ref"]["ref_id"] for candidate in selected_input["candidates"]] == [
        "method-candidate-8", "method-candidate-1",
    ]
