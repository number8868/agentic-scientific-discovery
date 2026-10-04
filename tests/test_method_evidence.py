from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from nova.contracts import ExperimentSpec, GroupSummary, Result, Split, Template
from nova.data import pipeline
from nova.experiments import method_sensitivity
from nova.method_evidence import build_method_evidence, build_method_evidence_packet


def _parent_spec(protocol):
    return ExperimentSpec(
        schema_version=1,
        experiment_id="parent-exp-1",
        hypothesis_id="H1",
        dataset_sha256=protocol["dataset_sha256"],
        split=Split.DISCOVERY,
        template=Template.FAMILY_SCREEN,
        groups=tuple(protocol["groups"]),
        bandgap_method="opt",
        gap_window_ev=tuple(protocol["gap_window_ev"]),
        ehull_max_ev_atom=protocol["ehull_max_ev_atom"],
        bootstrap_repeats=protocol["bootstrap_repeats"],
        seed=protocol["seed"],
        timeout_seconds=120,
    )


def _source_hashes():
    module = Path(method_sensitivity.__file__).resolve()
    # Hash the exact three files recorded by the scientific executor.
    from nova import statistics as statistics_module

    pipeline_path = Path(pipeline.__file__).resolve()
    files = {
        "nova/experiments/method_sensitivity.py": module,
        "nova/statistics.py": Path(statistics_module.__file__).resolve(),
        "nova/data/pipeline.py": pipeline_path,
    }
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}


def _row(family, index, *, opt_pass=False, mbj_pass=False, mbj_unknown=False):
    return {
        "jid": f"JVASP-{family}-{index:03d}",
        "formula": f"X{family[0]}{index}",
        "reduced_formula": f"X{family[0]}{index}",
        "elements": "Li,O" if family == "oxide" else "Li,S",
        "n_elements": "2",
        "family": family,
        "opt_gap_ev": "1.5" if opt_pass else "2.0",
        "mbj_gap_ev": None if mbj_unknown else "1.5" if mbj_pass else "2.0",
        "ehull_ev_atom": "0.01",
        "ehull_valid": "True",
        "ehull_rounded_to_zero": "False",
        "ehull_invalid_reason": "",
        "excluded": "False",
        "exclusion_reason": "",
        "record_quality_issue": "",
        "is_representative": "True",
        "representative_reason": "frozen synthetic representative",
        "split": "discovery",
    }


def _make_fixture():
    protocol, protocol_sha256 = method_sensitivity._read_method_protocol()
    rows = []
    for family in ("oxide", "chalcogenide"):
        for index in range(40):
            opt_pass = index < (2 if family == "oxide" else 3)
            mbj_pass = family == "chalcogenide" and index < 10
            rows.append(_row(family, index, opt_pass=opt_pass, mbj_pass=mbj_pass))
        # The unpaired chalcogenide OPT passes shift opt_all away from its paired subset.
        # One unpaired oxide OPT pass also remains a shortlisted MBJ unknown.
        rows.append(_row(family, 40, opt_pass=(family == "chalcogenide"), mbj_unknown=True))
        for index in range(41, 50):
            rows.append(_row(family, index, opt_pass=(family == "chalcogenide"), mbj_unknown=True))

    analysis, audit_rows = method_sensitivity.analyze_rows(rows, protocol)
    source_hashes = _source_hashes()
    timing = {
        "protocol_validation": 0.01,
        "prepared_data_validation": 0.02,
        "computation": 0.07,
        "total": 0.10,
    }
    result = {
        "schema_version": 1,
        "template": "method_sensitivity",
        "execution_status": "success",
        "split": "discovery",
        "dataset_sha256": protocol["dataset_sha256"],
        "parent_protocol_sha256": protocol["parent_protocol_sha256"],
        "protocol_sha256": protocol_sha256,
        "representative_compositions_csv_sha256": protocol["representative_compositions_csv_sha256"],
        "split_assignment_sha256": protocol["split_assignment_sha256"],
        "started_at": "2026-10-03T20:00:00+00:00",
        "finished_at": "2026-10-03T20:00:00.100000+00:00",
        "elapsed_seconds": 0.1,
        "timing_seconds": timing,
        "source_sha256": source_hashes["nova/experiments/method_sensitivity.py"],
        "source_hashes": source_hashes,
        "interpretation_scope": "Observed JARVIS representatives in the frozen discovery split; MBJ is a computational method, not ground truth.",
        "selection_mode": "human_selected",
        "no_new_model_calls": True,
        **analysis,
    }
    request = {
        "schema_version": 1,
        "audit_id": "",
        "run_id": "run-method-1",
        "parent_result_id": "parent-result-1",
        "parent_experiment_id": "parent-exp-1",
        "parent_spec_sha256": "",
        "dataset_sha256": protocol["dataset_sha256"],
        "protocol_sha256": protocol_sha256,
        "status": "registered",
    }
    spec = _parent_spec(protocol)
    request["parent_spec_sha256"] = spec.sha256
    request["audit_id"] = "NOVA-METHOD-" + hashlib.sha256(
        f"{request['run_id']}:{request['parent_result_id']}:{spec.sha256}:{protocol_sha256}".encode()
    ).hexdigest()[:24]

    opt_all = analysis["arms"]["opt_all"]
    groups = []
    for family in ("oxide", "chalcogenide"):
        item = opt_all["groups_summary"][family]
        n_total, n_observed, n_pass = item["n_total"], item["n_observed"], item["n_pass"]
        missing_lower = n_pass / n_total if n_total else None
        missing_upper = (n_pass + n_total - n_observed) / n_total if n_total else None
        groups.append(GroupSummary(
            family,
            n_total,
            n_observed,
            n_pass,
            item["coverage"],
            item["observed_rate"],
            missing_lower,
            missing_upper,
        ))
    oxide, chalcogenide = groups
    parent_missingness = (
        chalcogenide.missing_lower - oxide.missing_upper,
        chalcogenide.missing_upper - oxide.missing_lower,
    )
    parent = Result(
        result_id="parent-result-1",
        experiment_id=spec.experiment_id,
        spec_sha256=spec.sha256,
        dataset_sha256=spec.dataset_sha256,
        execution_status="completed",
        scientific_status=opt_all["scientific_status"],
        started_at="2026-10-03T19:59:00+00:00",
        finished_at="2026-10-03T19:59:01+00:00",
        elapsed_seconds=1.0,
        groups_summary=tuple(groups),
        delta=opt_all["delta"],
        resampling_interval=tuple(opt_all["resampling_interval"]),
        missingness_interval=parent_missingness,
        quality_flags=(),
    )
    return protocol, request, {"audit_id": request["audit_id"], "result": result, "audit_rows": audit_rows}, parent, spec


def test_builder_preserves_all_estimands_candidates_and_provenance_without_audit_rows():
    protocol, request, output, parent, spec = _make_fixture()
    body = build_method_evidence(request, output, parent, spec)
    science = body["science_result"]

    assert body["artifact_type"] == "nova.method_evidence.v1"
    assert body["registered_execution"]["mode"] == "registered_host_execution"
    assert body["request"]["request_sha256"]
    assert body["request"].get("status") is None
    assert body["parent"] == {
        "result_id": parent.result_id,
        "experiment_id": spec.experiment_id,
        "spec_sha256": spec.sha256,
        "dataset_sha256": spec.dataset_sha256,
    }
    assert set(science["arms"]) == {"opt_all", "opt_paired", "mbj_paired"}
    assert all("scientific_status" in science["arms"][arm] for arm in science["arms"])
    assert science["paired_method_change"]["scientific_status"] == "direction_positive"
    assert "scientific_status" not in science
    assert science["arms"]["opt_all"]["scientific_status"] == parent.scientific_status
    assert science["arms"]["opt_all"]["scientific_status"] == "supported_in_snapshot"
    assert science["arms"]["opt_paired"]["scientific_status"] == "inconclusive"
    assert science["arms"]["mbj_paired"]["scientific_status"] == "inconclusive"
    assert science["quality_scope"]["overall_scientific_status"] is None
    assert science["quality_scope"]["missingness_bounds"] is None
    assert body["provenance"]["scientific_executor"]["selection_mode"] == "human_selected"
    assert body["provenance"]["scientific_executor"]["no_new_model_calls_scope"] == "scientific_executor_only"
    assert body["provenance"]["scientific_executor"]["source_hashes"] == output["result"]["source_hashes"]
    assert body["frozen_protocol"]["protocol_id"] == protocol["protocol_id"]
    assert "created_at_utc" not in body["frozen_protocol"]
    assert any(candidate["mbj_gap_ev"] is None for candidate in science["candidates"])
    assert all("reason" in candidate and "next_validation" in candidate for candidate in science["candidates"])
    assert "audit_rows" not in json.dumps(body)
    assert not any(key in json.dumps(body) for key in ("started_at", "finished_at", "elapsed_seconds", "timing_seconds"))


def test_positive_mbj_interval_with_zero_oxide_endpoint_stays_inconclusive():
    _, request, output, parent, spec = _make_fixture()
    mbj = output["result"]["arms"]["mbj_paired"]
    assert mbj["groups_summary"]["oxide"]["n_pass"] == 0
    assert mbj["resampling_interval"][0] > 0
    assert mbj["quality_flags"]["endpoint_non_degenerate"] is False
    assert mbj["scientific_status"] == "inconclusive"

    body = build_method_evidence(request, output, parent, spec)
    assert body["science_result"]["arms"]["mbj_paired"]["scientific_status"] == "inconclusive"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("parent_result", "parent Result delta"),
        ("representatives", "representative_compositions_csv_sha256"),
        ("split", "split_assignment_sha256"),
        ("request", "audit_id"),
        ("reason", "reason does not match"),
        ("next_validation", "next_validation does not match"),
    ],
)
def test_builder_rejects_tampered_parent_request_provenance_or_candidate_guidance(mutation, match):
    _, request, output, parent, spec = _make_fixture()
    if mutation == "parent_result":
        parent = replace(parent, delta=parent.delta + 0.001)
    elif mutation == "representatives":
        output["result"]["representative_compositions_csv_sha256"] = "0" * 64
    elif mutation == "split":
        output["result"]["split_assignment_sha256"] = "0" * 64
    elif mutation == "request":
        request["audit_id"] = "NOVA-METHOD-" + "0" * 24
    elif mutation == "reason":
        output["audit_rows"][0]["reason"] = "forged reason"
    elif mutation == "next_validation":
        output["audit_rows"][0]["next_validation"] = "skip verification"

    with pytest.raises(ValueError, match=match):
        build_method_evidence(request, output, parent, spec)


def test_builder_rejects_nested_audit_rows_and_untrusted_interpretation():
    _, request, output, parent, spec = _make_fixture()
    output["result"]["arms"]["mbj_paired"]["audit_rows"] = []
    with pytest.raises(ValueError, match="method arm mbj_paired does not match the frozen schema"):
        build_method_evidence(request, output, parent, spec)

    _, request, output, parent, spec = _make_fixture()
    output["result"]["interpretation_scope"] = "MBJ is ground truth."
    with pytest.raises(ValueError, match="interpretation_scope"):
        build_method_evidence(request, output, parent, spec)


def test_tampered_frozen_protocol_bytes_fail_and_prepared_loader_is_never_called(tmp_path, monkeypatch):
    _, request, output, parent, spec = _make_fixture()
    changed_protocol = tmp_path / "METHOD_AUDIT_PROTOCOL.json"
    changed_protocol.write_bytes(method_sensitivity.METHOD_PROTOCOL_PATH.read_bytes() + b" ")
    monkeypatch.setattr(method_sensitivity, "METHOD_PROTOCOL_PATH", changed_protocol)
    monkeypatch.setattr(
        pipeline,
        "_read_prepared_compositions",
        lambda: (_ for _ in ()).throw(AssertionError("evidence builder loaded prepared data")),
    )

    with pytest.raises(ValueError, match="protocol hash mismatch"):
        build_method_evidence(request, output, parent, spec)


def test_body_hash_packet_has_exact_hash_bound_pointers_and_rejects_mismatched_hash():
    _, request, output, parent, spec = _make_fixture()
    body = build_method_evidence(request, output, parent, spec)
    canonical_bytes = (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    packet = build_method_evidence_packet(body, digest)

    pointers = [item["json_pointer"] for item in packet["references"]]
    assert pointers[:4] == [
        "/science_result/arms/opt_all",
        "/science_result/arms/opt_paired",
        "/science_result/arms/mbj_paired",
        "/science_result/paired_method_change",
    ]
    assert pointers[4:10] == [
        "/science_result/candidate_counts",
        "/science_result/candidate_counts_by_family",
        "/science_result/subset_shift",
        "/science_result/transitions",
        "/request",
        "/parent",
    ]
    assert pointers[10:] == [f"/science_result/candidates/{index}" for index in range(len(body["science_result"]["candidates"]))]
    assert all(item["evidence_sha256"] == digest for item in packet["references"])
    for reference in packet["references"]:
        assert reference["json_pointer"].startswith("/science_result/") or reference["json_pointer"] in {"/request", "/parent"}
    with pytest.raises(ValueError, match="does not match"):
        build_method_evidence_packet(body, "0" * 64)


def test_evidence_is_stable_when_only_executor_timing_changes():
    _, request, first_output, parent, spec = _make_fixture()
    _, _, second_output, _, _ = _make_fixture()
    second_output["result"]["started_at"] = "2026-10-03T21:10:00+00:00"
    second_output["result"]["finished_at"] = "2026-10-03T21:10:00.200000+00:00"
    second_output["result"]["elapsed_seconds"] = 0.2
    second_output["result"]["timing_seconds"] = {
        "protocol_validation": 0.02,
        "prepared_data_validation": 0.03,
        "computation": 0.15,
        "total": 0.2,
    }

    first = build_method_evidence(request, first_output, parent, spec)
    second = build_method_evidence(request, second_output, parent, spec)
    assert first == second
