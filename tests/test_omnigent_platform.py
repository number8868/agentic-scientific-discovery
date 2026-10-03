from __future__ import annotations

import pytest

from scripts import run_omnigent_live


def test_live_pilot_allows_posix_platforms(monkeypatch):
    monkeypatch.setattr(run_omnigent_live.os, "name", "posix")
    run_omnigent_live._check_live_platform()


def test_live_pilot_rejects_non_posix_platforms(monkeypatch):
    monkeypatch.setattr(run_omnigent_live.os, "name", "nt")
    with pytest.raises(RuntimeError, match="POSIX runtime"):
        run_omnigent_live._check_live_platform()
