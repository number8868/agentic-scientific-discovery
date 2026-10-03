import pytest

from nova.runtime import Proposal, Run, RunState, fixture_executor
from nova.tools import execute_registered_experiment


def proposals():
    return [
        Proposal("exp-family", "family_screen", {"template": "family_screen", "mode": "fixture"}),
        Proposal("exp-threshold", "threshold_sensitivity", {"template": "threshold_sensitivity", "mode": "fixture"}),
    ]


def test_closed_loop_two_candidates_changed_second_experiment():
    run = Run("Which family has higher observed pass rate?", fixture_executor)
    run.freeze_hypothesis()
    assert run.register_plan(proposals()) == ["exp-family", "exp-threshold"]
    assert len(run.proposals) == 2
    run.choose("exp-family")
    first = run.run_first()
    assert first["template"] == "family_screen"
    run.submit_skeptic_review(concern="threshold dependence", next_template="threshold_sensitivity")
    second = run.run_second("exp-threshold")
    assert second["template"] == "threshold_sensitivity"
    assert run.state is RunState.SECOND_RESULT_READY


def test_runner_only_registered_id_and_skeptic_cannot_execute():
    run = Run("q", fixture_executor)
    with pytest.raises(PermissionError):
        execute_registered_experiment("arbitrary-path-or-code")
    run.freeze_hypothesis()
    run.register_plan(proposals())
    run.choose("exp-family")
    run.run_first()
    with pytest.raises(RuntimeError):
        run.review = {"concern": "bad"}
        run.run_second("exp-threshold")


def test_fixture_label_is_not_live_label():
    run = Run("q", fixture_executor)
    run.freeze_hypothesis()
    run.register_plan(proposals())
    run.choose("exp-family")
    result = run.run_first()
    assert result["mode"] == "fixture"
    assert result["mode"] != "live"


def test_second_experiment_rejects_same_template_under_new_id():
    run = Run("q", fixture_executor)
    run.freeze_hypothesis()
    run.register_plan([
        Proposal("first", "family_screen", {"template": "family_screen", "mode": "fixture"}),
        Proposal("renamed", "family_screen", {"template": "family_screen", "mode": "fixture"}),
    ])
    run.choose("first")
    first = run.run_first()
    run.submit_skeptic_review(
        concern="needs another axis",
        next_template="gap_window_sensitivity",
        result_id=first["result_id"],
    )
    with pytest.raises(ValueError, match="different template"):
        run.run_second("renamed")
