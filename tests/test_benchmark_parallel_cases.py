import json
from nova.benchmark_parallel_cases import grade_response, load_corpus


def _gold(case):
    answers = {q["id"]: q["expected"] for q in case["questions"]}
    return {"answers": answers, "citations": case["required_citations"],
            "explanation": "synthetic-only determination from the cited packet."}


def test_frozen_corpus_shape_and_disjoint_development():
    corpus = load_corpus()
    assert corpus["version"] == "parallel_selftest_v1"
    assert len(corpus["development"]) == 4
    assert len(corpus["exploratory"]) == 24
    cases = corpus["exploratory"]
    assert len({case["id"] for case in cases}) == 24
    assert len({case["id"] for case in corpus["development"]}) == 4
    assert {c["family"] for c in cases} == {
        "quantity", "units", "conflict", "evidence", "injection", "counterfactual"
    }
    for family in {c["family"] for c in cases}:
        subset = [c for c in cases if c["family"] == family]
        assert len(subset) == 4
        assert len({c["pair_id"] for c in subset}) == 2
        assert sorted(c["variant"] for c in subset) == [1, 1, 2, 2]


def test_all_frozen_gold_responses_pass():
    corpus = load_corpus()
    for case in corpus["development"] + corpus["exploratory"]:
        result = grade_response(case, json.dumps(_gold(case)))
        assert result == {"strict_schema_pass": True, "semantic_score": 1.0,
                          "citation_pass": True, "scope_pass": True, "errors": []}, case["id"]


def test_counterfactual_variants_change_expected_outcomes():
    corpus = load_corpus()
    pairs = {}
    for case in corpus["exploratory"]:
        pairs.setdefault(case["pair_id"], []).append(case)
    assert len(pairs) == 12
    for pair_id, variants in pairs.items():
        assert len(variants) == 2, pair_id
        left, right = sorted(variants, key=lambda c: c["variant"])
        assert any(a["expected"] != b["expected"]
                   for a, b in zip(left["questions"], right["questions"])), pair_id


def test_visible_packet_discloses_schema_citations_and_scoring_criteria():
    corpus = load_corpus()
    for case in corpus["development"] + corpus["exploratory"]:
        packet = case["packet"]
        assert "Answer contract" in packet
        assert "Required source IDs" in packet
        assert "Schema:" in packet
        assert "Rubric:" in packet
        assert "tolerance" in packet
        assert "synthetic-only" in packet


def test_multiple_feasible_actions_are_explicitly_accepted():
    case = next(c for c in load_corpus()["exploratory"]
                if c["pair_id"] == "conflict-pair-2" and c["variant"] == 1)
    action_q = next(q for q in case["questions"] if q["id"] == "action")
    assert action_q["accepted_values"] == ["C", "D"]
    response = _gold(case)
    response["answers"]["action"] = "D"
    assert grade_response(case, response)["semantic_score"] == 1.0


def test_unit_equivalent_numeric_string_is_semantic_but_not_strict():
    case = next(c for c in load_corpus()["exploratory"] if c["family"] == "units")
    response = _gold(case)
    expected = next(q["expected"] for q in case["questions"] if q["id"] == "metres")
    response["answers"]["metres"] = f"{expected} m"
    result = grade_response(case, response)
    assert result["semantic_score"] == 1.0
    assert result["strict_schema_pass"] is False


def test_wrong_typed_value_and_bad_citation_do_not_earn_semantic_credit():
    case = next(c for c in load_corpus()["exploratory"]
                if c["family"] == "evidence" and c["pair_id"] == "evidence-pair-1" and c["variant"] == 2)
    response = _gold(case)
    response["answers"]["value"] = 0  # unknown is not false/zero
    response["citations"] = ["fabricated-source"]
    result = grade_response(case, response)
    assert result["semantic_score"] < 1
    assert not result["strict_schema_pass"]
    assert not result["citation_pass"]


def test_nonfinite_and_malformed_json_rejected():
    case = load_corpus()["exploratory"][0]
    assert grade_response(case, '{"answers":{"passed":NaN}}')["strict_schema_pass"] is False
    assert grade_response(case, '{"answers":{"passed":1e999,"total":15,"fraction":0.6666666666666666},"citations":["Q1","Q2"],"explanation":"synthetic-only"}')['semantic_score'] == 2/3
    assert grade_response(case, '{"answers":{"passed":8,"passed":8,"total":15,"fraction":0.6},"citations":["Q1","Q2"],"explanation":"synthetic-only"}')['semantic_score'] is None
    assert grade_response(case, "not json")["semantic_score"] is None


def test_safe_negation_passes_visible_scope_marker():
    case = load_corpus()["exploratory"][0]
    response = _gold(case)
    response["explanation"] = "synthetic-only; not real-world validation."
    assert grade_response(case, response)["scope_pass"] is True
