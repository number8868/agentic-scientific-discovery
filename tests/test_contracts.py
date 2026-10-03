import pytest
from nova.contracts import ExperimentSpec, Split, Template

def spec(**overrides):
    x=dict(schema_version=1, experiment_id="E1", hypothesis_id="H1", dataset_sha256="a"*64,
           split=Split.DISCOVERY, template=Template.FAMILY_SCREEN, groups=("oxide",),
           bandgap_method="opt", gap_window_ev=(1.1,1.8), ehull_max_ev_atom=.05,
           bootstrap_repeats=10, seed=1729, timeout_seconds=120)
    x.update(overrides); return ExperimentSpec(**x)

def test_roundtrip_and_frozen():
    s=spec(); assert ExperimentSpec.from_dict(s.to_dict()) == s
    with pytest.raises((AttributeError, TypeError)): s.timeout_seconds=4

@pytest.mark.parametrize("change", [{"template":"unknown"},{"split":"unknown"},{"gap_window_ev":[2,1]},{"ehull_max_ev_atom":-1},{"timeout_seconds":0}])
def test_validation(change):
    if "template" in change or "split" in change:
        with pytest.raises(ValueError): ExperimentSpec.from_dict(dict(spec().to_dict(), **change))
    else:
        with pytest.raises(ValueError): spec(**change)

def test_unknown_field_rejected():
    with pytest.raises(ValueError): ExperimentSpec.from_dict(dict(spec().to_dict(), extra=1))
