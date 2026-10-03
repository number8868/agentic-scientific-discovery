import pytest

from scripts.check_omnigent_luna_export import check_export


def test_partial_luna_export_fails_closed():
    with pytest.raises(ValueError, match="13-event"):
        check_export("docs/results/omnigent_luna_run")
