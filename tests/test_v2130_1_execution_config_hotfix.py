import json
from pathlib import Path
from dvs_ai.config import load_config

def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")

def test_missing_execution_keys_use_defaults(tmp_path):
    p = tmp_path/"config.json"
    _write(p,{})
    c = load_config(p)
    assert c.execution_mode == "PAPER"
    assert c.execution_live_enabled is False
    assert c.execution_daily_loss_limit == 50.0
    assert c.execution_max_consecutive_losses == 4
    assert c.execution_max_open_exposure == 5000.0
    assert c.execution_max_daily_trades == 30
    assert c.execution_max_api_error_rate == 0.25
    assert c.execution_max_market_data_age_seconds == 15.0

def test_unknown_mode_falls_back_to_paper(tmp_path):
    p = tmp_path/"config.json"
    _write(p,{"execution_mode":"WRONG"})
    assert load_config(p).execution_mode == "PAPER"

def test_valid_modes_preserved(tmp_path):
    for mode in ("PAPER","TESTNET","LIVE"):
        p = tmp_path/f"{mode}.json"
        _write(p,{"execution_mode":mode})
        assert load_config(p).execution_mode == mode

def test_invalid_numeric_values_fall_back(tmp_path):
    p = tmp_path/"config.json"
    _write(p,{
        "execution_daily_loss_limit":"x",
        "execution_max_consecutive_losses":None,
        "execution_max_open_exposure":"x",
        "execution_max_daily_trades":"x",
        "execution_max_api_error_rate":"x",
        "execution_max_market_data_age_seconds":"x",
    })
    c = load_config(p)
    assert c.execution_daily_loss_limit == 50.0
    assert c.execution_max_consecutive_losses == 4
    assert c.execution_max_open_exposure == 5000.0
    assert c.execution_max_daily_trades == 30
    assert c.execution_max_api_error_rate == 0.25
    assert c.execution_max_market_data_age_seconds == 15.0

def test_default_project_config_is_safe():
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw.get("execution_mode") == "PAPER"
    assert raw.get("execution_live_enabled") is False
