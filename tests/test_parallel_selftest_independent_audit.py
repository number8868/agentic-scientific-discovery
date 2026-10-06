"""Independent hand-calculated checks, not fixtures copied from answer keys."""
import json

from nova.benchmark_parallel_cases import grade_response, load_corpus


def test_development_answers_independently_recomputed():
    # D1: 3/8, D2: 3/4 => 6/12, not mean(3/8, 3/4).
    # D3: 120 cm => 1.2 m. D4: only A fits cost <=5, capacity >=3.
    # S-DEV says unknown, which cannot be replaced by false or zero.
    answers = {
        "dev-quantity": {"fraction": 6 / 12},
        "dev-units": {"metres": 120 / 100},
        "dev-conflict": {"action": "A"},
        "dev-evidence": {"status": "unknown", "value": None},
    }
    for case in load_corpus()["development"]:
        response = {"answers": answers[case["id"]],
                    "citations": case["required_citations"],
                    "explanation": "synthetic-only; no real-world validation is claimed."}
        grade = grade_response(case, json.dumps(response))
        assert grade["semantic_score"] == 1
        assert grade["strict_schema_pass"]
        assert grade["scope_pass"]  # Safe negation is not a fabricated claim.
        for question in case["questions"]:
            assert f'"{question["id"]}"' in case["packet"]


def test_development_invalid_null_substitutions_not_silently_accepted():
    case = next(c for c in load_corpus()["development"] if c["id"] == "dev-evidence")
    for value in (False, 0, "null"):
        grade = grade_response(case, {
            "answers": {"status": "unknown", "value": value},
            "citations": ["S-DEV"], "explanation": "synthetic-only",
        })
        assert not grade["strict_schema_pass"]
        assert grade["semantic_score"] == .5
