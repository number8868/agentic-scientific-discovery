from scripts.check_live_config import check
def test_live_config():
    result=check(); assert result["ok"], result
