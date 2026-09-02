from dvs_ai.config import load_config

def test_config_loads():
    c=load_config("config.json")
    assert "15m" in c.timeframes
    assert c.ohlcv_limit >= 220
