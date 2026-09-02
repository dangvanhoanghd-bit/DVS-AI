import inspect
import json
import random
import sqlite3
from pathlib import Path

import pytest

from dvs_ai.services.quantum_optimizer import (
    OptimizationParams,
    QuantumOptimizer,
)


def _seed_db(path: Path, count: int = 150):
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY,
            created_at TEXT,
            lab TEXT,
            status TEXT,
            result TEXT,
            confidence REAL,
            entry_score REAL,
            risk_score REAL,
            rr_planned REAL,
            r_multiple REAL,
            setup_tags TEXT,
            evidence_snapshot_json TEXT
        )""")
        for i in range(count):
            recent = i >= count // 2
            good = (i % 3 != 0) if recent else (i % 3 == 0)
            con.execute(
                "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    i + 1,
                    f"2026-01-{1+(i//24)%28:02d} "
                    f"{i%24:02d}:00:00",
                    "SHADOW",
                    "CLOSED",
                    "TP2" if good else "STOP",
                    58 if good else 43,
                    57 if good else 42,
                    35 if good else 60,
                    1.8 if good else 1.2,
                    1.2 if good else -1.0,
                    (
                        "TREND_EARLY_FORMATION"
                        if good
                        else "TREND_LATE_TREND"
                    ),
                    json.dumps({'TIMING':{'score':70,'quality':1,'available':True},'ENTRY':{'score':70,'quality':1,'available':True},'ORDER_FLOW':{'score':70,'quality':1,'available':True},'DIRECTION':{'score':70,'quality':1,'available':True},'MARKET':{'score':70,'quality':1,'available':True},'_TRUTH':{'schema':'DVS_QUANTUM_TRAINING_V1','calibration_state':'VALIDATED','drift_state':'STABLE','order_flow_quality':'FULL','evidence_reliability_state':'VALIDATED'}}),
                ),
            )


def _base_config(path: Path):
    path.write_text(
        json.dumps({
            "main_confidence": 68,
            "main_entry": 62,
            "main_risk_max": 50,
            "main_rr_min": 1.8,
            "shadow_confidence": 45,
            "shadow_entry": 45,
            "shadow_risk_max": 65,
            "shadow_rr_min": 1.4,
        }),
        encoding="utf-8",
    )


def test_no_method_can_write_main_thresholds():
    source = inspect.getsource(QuantumOptimizer)
    for key in (
        "main_confidence",
        "main_entry",
        "main_risk_max",
        "main_rr_min",
    ):
        assert f'raw["{key}"]' not in source
        assert f"raw['{key}']" not in source


def test_apply_shadow_never_returns_or_writes_main_keys(tmp_path):
    cfg = tmp_path / "config.json"
    _base_config(cfg)
    opt = QuantumOptimizer(
        str(tmp_path / "none.db"),
        str(cfg),
    )
    report = {
        "safe_to_apply_shadow": True,
        "best_params": {
            "main_confidence": 99.0,
            "main_entry": 99.0,
            "main_risk_max": 1.0,
            "main_rr_min": 5.0,
            "shadow_confidence": 55,
            "shadow_entry": 55,
            "shadow_risk_max": 75,
            "shadow_rr_min": 1.8,
        },
    }
    candidate = opt.create_shadow_candidate(report, str(tmp_path / "candidate.json"))
    assert not any(k.startswith("main_") for k in candidate["candidate"])
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    assert raw["main_confidence"] == 68
    assert raw["main_entry"] == 62


def test_train_validation_split_is_chronological(tmp_path):
    db = tmp_path / "paper.db"
    _seed_db(db)
    cfg = tmp_path / "config.json"
    _base_config(cfg)

    opt = QuantumOptimizer(
        str(db),
        str(cfg),
        population_size=20,
        generations=10,
    )
    rows = opt._load_closed()
    train, validation = opt._chronological_split(
        rows,
        opt.validation_ratio,
    )
    assert max(x.created_at for x in train) <= min(
        x.created_at for x in validation
    )


def test_recent_validation_regime_is_preserved(tmp_path):
    db = tmp_path / "paper.db"
    _seed_db(db)
    cfg = tmp_path / "config.json"
    _base_config(cfg)

    opt = QuantumOptimizer(str(db), str(cfg))
    rows = opt._load_closed()
    train, validation = opt._chronological_split(
        rows,
        opt.validation_ratio,
    )

    train_wr = (
        sum(t.r_multiple > 0 for t in train)
        / len(train)
    )
    validation_wr = (
        sum(t.r_multiple > 0 for t in validation)
        / len(validation)
    )
    assert validation_wr > train_wr


def test_apply_shadow_raises_when_not_safe(tmp_path):
    cfg = tmp_path / "config.json"
    _base_config(cfg)
    opt = QuantumOptimizer(
        str(tmp_path / "none.db"),
        str(cfg),
    )
    with pytest.raises(ValueError):
        opt.create_shadow_candidate({
            "safe_to_apply_shadow": False,
            "best_params": {
                "shadow_confidence": 55,
                "shadow_entry": 55,
                "shadow_risk_max": 75,
                "shadow_rr_min": 1.8,
            },
        }, str(tmp_path / "candidate.json"))
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    assert raw["shadow_confidence"] == 45


def test_guardrail_clamps_both_directions(tmp_path):
    cfg = tmp_path / "config.json"
    _base_config(cfg)
    opt = QuantumOptimizer(
        str(tmp_path / "none.db"),
        str(cfg),
    )

    up = opt.create_shadow_candidate({
        "safe_to_apply_shadow": True,
        "best_params": {
            "shadow_confidence": 90.0,
            "shadow_entry": 45,
            "shadow_risk_max": 65,
            "shadow_rr_min": 1.4,
        },
    }, str(tmp_path / "up.json"))
    assert up["candidate"]["shadow_confidence"] == 47.0

    _base_config(cfg)
    down = opt.create_shadow_candidate({
        "safe_to_apply_shadow": True,
        "best_params": {
            "shadow_confidence": 5.0,
            "shadow_entry": 45,
            "shadow_risk_max": 65,
            "shadow_rr_min": 1.4,
        },
    }, str(tmp_path / "down.json"))
    assert down["candidate"]["shadow_confidence"] == 43.0


def test_clamp_hard_bounds():
    p = OptimizationParams(
        main_confidence=1000,
        main_entry=-1000,
        main_risk_max=1000,
        main_rr_min=-1000,
        shadow_confidence=1000,
        shadow_entry=-1000,
        shadow_risk_max=1000,
        shadow_rr_min=-1000,
    ).clamp()
    assert 60 <= p.main_confidence <= 78
    assert 55 <= p.main_entry <= 75
    assert 35 <= p.main_risk_max <= 60
    assert 1.4 <= p.main_rr_min <= 2.5
    assert 38 <= p.shadow_confidence <= 60
    assert 38 <= p.shadow_entry <= 60
    assert 45 <= p.shadow_risk_max <= 75
    assert 1.1 <= p.shadow_rr_min <= 2.0


def test_random_noise_requires_penalized_improvement(tmp_path):
    db = tmp_path / "paper.db"
    rng = random.Random(123)
    with sqlite3.connect(db) as con:
        con.execute("""CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY,
            created_at TEXT,
            lab TEXT,
            status TEXT,
            result TEXT,
            confidence REAL,
            entry_score REAL,
            risk_score REAL,
            rr_planned REAL,
            r_multiple REAL,
            setup_tags TEXT,
            evidence_snapshot_json TEXT
        )""")
        for i in range(150):
            r = rng.gauss(0, 1.0)
            con.execute(
                "INSERT INTO paper_trades VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    i + 1,
                    f"2026-01-{1+(i//24)%28:02d} "
                    f"{i%24:02d}:00:00",
                    "SHADOW",
                    "CLOSED",
                    "TP2" if r > 0 else "STOP",
                    rng.uniform(40, 60),
                    rng.uniform(40, 60),
                    rng.uniform(40, 60),
                    rng.uniform(1.2, 1.8),
                    r,
                    "TREND_EARLY_FORMATION",
                    json.dumps({
                        "TIMING":{"score":70,"quality":1,"available":True},
                        "ENTRY":{"score":70,"quality":1,"available":True},
                        "ORDER_FLOW":{"score":70,"quality":1,"available":True},
                        "DIRECTION":{"score":70,"quality":1,"available":True},
                        "MARKET":{"score":70,"quality":1,"available":True},
                        "_TRUTH":{"schema":"DVS_QUANTUM_TRAINING_V1","calibration_state":"VALIDATED","drift_state":"STABLE","order_flow_quality":"FULL","evidence_reliability_state":"VALIDATED"}
                    }),
                ),
            )

    cfg = tmp_path / "config.json"
    _base_config(cfg)
    opt = QuantumOptimizer(
        str(db),
        str(cfg),
        population_size=30,
        generations=15,
        min_closed=80,
        seed=7,
    )
    report = opt.optimize()
    assert (
        report["required_validation_improvement"]
        > opt.min_validation_improvement
    )
    if report["safe_to_apply_shadow"]:
        assert (
            report["validation_improvement"]
            >= report["required_validation_improvement"]
        )
        assert report["validation_avg_r_ok"]
        assert report["validation_drawdown_ok"]
