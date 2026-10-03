import pytest
from nova.contracts import *
from nova.storage import Storage

def make_spec(i="E1"):
    return ExperimentSpec(1,i,"H1","a"*64,Split.DISCOVERY,Template.FAMILY_SCREEN,("oxide",),"opt",(1.1,1.8),.05,10,1729,120)

def test_register_idempotent_and_events(tmp_path):
    st=Storage(tmp_path/"n.sqlite").initialize(); s=make_spec(); st.register_spec(s); st.register_spec(s)
    assert [st.append_event("r","x"), st.append_event("r","y")][1].seq == 2
    assert [e.seq for e in st.list_events("r")] == [1,2]
    conflicting = ExperimentSpec(
        1,"E1","H1","a"*64,Split.DISCOVERY,Template.FAMILY_SCREEN,
        ("oxide",),"opt",(1.1,1.8),.10,10,1729,120,
    )
    with pytest.raises(ValueError): st.register_spec(conflicting)

def test_result_requires_registered_spec(tmp_path):
    st=Storage(tmp_path/"n.sqlite").initialize()
    r=Result("R","missing","x","a","failed",None,"s","f",0,error={"type":"x"})
    with pytest.raises(ValueError): st.save_result(r)
