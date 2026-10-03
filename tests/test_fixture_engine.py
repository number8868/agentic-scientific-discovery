import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest
from nova.fixture_engine import execute


def test_fixed_seed_and_result():
    spec = {"mode": "fixture", "template": "family_screen", "seed": 1729}
    assert execute(spec).to_dict() == execute(spec).to_dict()


def test_threshold_changes_output():
    result = execute({"mode": "fixture", "template": "threshold_sensitivity"})
    assert len(result.points) == 3
    assert len({p["delta"] for p in result.points}) > 1


def test_gap_window_changes_output():
    result = execute({"mode": "fixture", "template": "gap_window_sensitivity"})
    assert len(result.points) == 3
    assert len({p["delta"] for p in result.points}) > 1


def test_mode_is_fixture_and_live_rejected():
    assert execute({"template": "family_screen"}).mode == "fixture"
    with pytest.raises(ValueError):
        execute({"mode": "live", "template": "family_screen"})
