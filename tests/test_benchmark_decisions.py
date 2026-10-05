import copy

import pytest

from nova.benchmark_decisions import (
    canonical_corpus_bytes,
    corpus_sha256,
    fixed_decision,
    load_corpus,
    score_decision,
)


def test_corpus_is_frozen_six_case_discovery_only_packet_set():
    corpus = load_corpus()
    assert len(corpus["cases"]) == 6
    assert corpus["scope"] == "frozen_discovery_only_decision_structural_evaluation"
    assert corpus["evidence"]["split"] == "discovery"
    assert corpus["evidence"]["groups"] == {
        "oxide": {"n_observed": 7657, "n_pass": 3},
        "chalcogenide": {"n_observed": 3158, "n_pass": 6},
    }
    assert corpus_sha256() == "b6902af180e303204352cc71e94e8a2770fca03c6e224c1cb744842b831a786a"
    assert canonical_corpus_bytes(corpus) == canonical_corpus_bytes()
    assert "holdout" not in str(corpus).lower()


def test_fixed_policy_obeys_threshold_method_stop_precedence():
    corpus = load_corpus()
    decisions = [fixed_decision(case)["action"] for case in corpus["cases"]]
    assert decisions == [
        "threshold_sensitivity",
        "threshold_sensitivity",
        "method_sensitivity",
        "stop",
        "stop",
        "stop",
    ]


def test_structural_rubric_accepts_fixed_decision_without_claiming_semantic_accuracy():
    case = load_corpus()["cases"][0]
    result = score_decision(case, fixed_decision(case))
    assert result["structural_pass"] is True
    assert result["scoring_scope"] == "structural_check_only_not_semantic_accuracy"


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda d: d.update(citations=["invented-result-ref"]), "citation_valid"),
        (lambda d: d["claim_tags"].append("replicated_material_discovery"), "no_unsupported_claim_tags"),
    ],
)
def test_rubric_rejects_invalid_action_fabricated_citation_and_unsupported_claim_tag(mutate, field):
    case = load_corpus()["cases"][0]
    decision = copy.deepcopy(fixed_decision(case))
    mutate(decision)
    result = score_decision(case, decision)
    assert result[field] is False
    assert result["structural_pass"] is False


def test_action_not_feasible_in_packet_fails_even_if_globally_supported():
    case = load_corpus()["cases"][2]
    decision = fixed_decision(case)
    decision["action"] = "threshold_sensitivity"
    result = score_decision(case, decision)
    assert result["action_valid"] is False


def test_every_feasible_action_in_ambiguous_case_is_accepted():
    case = load_corpus()["cases"][1]
    for action in ("threshold_sensitivity", "method_sensitivity", "stop"):
        decision = fixed_decision(case)
        decision["action"] = action
        assert score_decision(case, decision)["action_valid"] is True


def test_citation_requires_exact_result_reference_set():
    case = load_corpus()["cases"][0]
    decision = fixed_decision(case)
    decision["citations"].append("extra-ref")
    assert score_decision(case, decision)["citation_valid"] is False


def test_score_rejects_non_string_citation_entries():
    case = load_corpus()["cases"][0]
    decision = fixed_decision(case)
    decision["citations"] = [None]
    with pytest.raises(TypeError, match="exact result-reference"):
        score_decision(case, decision)


def test_malformed_action_is_scored_false():
    case = load_corpus()["cases"][0]
    decision = fixed_decision(case)
    decision["action"] = None
    assert score_decision(case, decision)["action_valid"] is False


def test_fixed_policy_does_not_read_hidden_rubric():
    case = load_corpus()["cases"][0]
    expected = fixed_decision(case)
    altered = {**case, "required_result_refs": [], "supported_claim_tags": [],
               "acceptable_actions": ["method_sensitivity"]}
    assert fixed_decision(altered) == expected
    altered["available_citations"] = []
    assert fixed_decision(altered)["action"] == "stop"
