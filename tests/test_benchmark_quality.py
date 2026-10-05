from __future__ import annotations

from nova import benchmark_quality as bq


def _gold(case):
    r = case["rubric"]
    return {"answers": {q: spec["value"] for q, spec in r["expected_answers"].items()},
            "action": r["expected_action"], "citations": list(r["expected_citations"])}


def test_all_frozen_gold_decisions_pass():
    corpus = bq.load_corpus()
    assert len(corpus["cases"]) == 6
    for case in corpus["cases"]:
        result = bq.score_decision(case, _gold(case))
        assert result["quality_score"] == 1
        assert result["exact_pass"]


def test_rubric_citations_are_exactly_packet_references():
    for case in bq.load_corpus()["cases"]:
        packet = bq.visible_packet(case)["packet"]
        assert packet["citation_policy"] == "Cite every supplied source reference exactly once."
        supplied = set(packet["citations"].values())
        assert set(case["rubric"]["expected_citations"]) == supplied
        assert set(packet["questions"]) == set(case["rubric"]["expected_answers"])


def test_substantive_errors_action_and_citation_errors_are_scored():
    case = bq.load_corpus()["cases"][0]
    d = _gold(case)
    d["answers"]["q1"] = 3  # count substituted for rate
    d["action"] = "stop"
    d["citations"] = ["invented"]
    result = bq.score_decision(case, d)
    assert result["answer_correct"] == 4
    assert not result["action_valid"] and not result["citation_valid"]
    assert result["quality_score"] < 1


def test_null_is_not_zero_and_bool_is_not_number():
    case = next(c for c in bq.load_corpus()["cases"] if c["id"] == "missing_zero_denominator")
    d = _gold(case)
    d["answers"]["q2"] = 0  # undefined rate is null
    assert bq.score_decision(case, d)["answer_correct"] == 5
    case = bq.load_corpus()["cases"][0]
    d = _gold(case)
    d["answers"]["q1"] = True
    assert bq.score_decision(case, d)["answer_correct"] == 4


def test_malformed_or_cross_reference_answers_fail_closed():
    case = bq.load_corpus()["cases"][0]
    for d in (None, {}, {**_gold(case), "extra": 1}):
        assert bq.score_decision(case, d)["quality_score"] == 0
    d = _gold(case)
    d["answers"]["fake_question"] = 1
    assert bq.score_decision(case, d)["quality_score"] == 0
    d = _gold(case)
    d["answers"].pop("q1")
    assert bq.score_decision(case, d)["quality_score"] == 0


def test_visible_packet_excludes_rubric_and_returns_isolated_copy():
    case = bq.load_corpus()["cases"][0]
    packet = bq.visible_packet(case)
    assert set(packet) == {"id", "packet"}
    assert "rubric" not in packet and "expected_answers" not in str(packet)
    packet["packet"]["facts"].clear()
    assert case["packet"]["facts"]


def test_frozen_digest():
    assert bq.corpus_sha256() == bq.FROZEN_CORPUS_SHA256
