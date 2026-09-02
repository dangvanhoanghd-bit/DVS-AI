import random
from dvs_ai.engines.microstructure_engine import MicrostructureEngine

def raw(size):
    random.seed(1)
    bs=[random.uniform(600,1400) for _ in range(100)]
    asks=[random.uniform(600,1400) for _ in range(100)]
    bs[3]=size
    bids=[[100-i*.01, v/(100-i*.01)] for i,v in enumerate(bs)]
    asks=[[100+i*.01, v/(100+i*.01)] for i,v in enumerate(asks)]
    trades=[{"p":"100","q":"1","m":False} for _ in range(60)]
    return {"depth":{"bids":bids,"asks":asks},"agg_trades":trades,"liquidations":[]}

def state(s,t):
    return {"bid":{
        "price":s.bid_wall_price,"notional":s.bid_wall_notional,
        "streak":s.bid_wall_streak,
        "first_seen_ts":t-s.bid_wall_age_seconds,
        "last_seen_ts":t,"raw_score":s.bid_wall_score,
        "age_seconds":s.bid_wall_age_seconds,
    },"ask":{
        "price":s.ask_wall_price,"notional":s.ask_wall_notional,
        "streak":s.ask_wall_streak,
        "first_seen_ts":t-s.ask_wall_age_seconds,
        "last_seen_ts":t,"raw_score":s.ask_wall_score,
        "age_seconds":s.ask_wall_age_seconds,
    }}

def test_time_persistence():
    a=MicrostructureEngine.analyze("T",raw(30000),100,observed_at=1000)
    b=MicrostructureEngine.analyze("T",raw(29500),100,previous_wall_state=state(a,1000),observed_at=1015)
    assert 45 <= b.bid_wall_persistence <= 55
    assert b.bid_wall_age_seconds == 15

def test_consumption():
    a=MicrostructureEngine.analyze("T",raw(30000),100,observed_at=1000)
    b=MicrostructureEngine.analyze("T",raw(24000),100,previous_wall_state=state(a,1000),observed_at=1015)
    assert b.bid_wall_consumption_score > 0
    assert b.bid_wall_velocity_pct_per_sec < 0

def test_refresh():
    a=MicrostructureEngine.analyze("T",raw(20000),100,observed_at=1000)
    b=MicrostructureEngine.analyze("T",raw(28000),100,previous_wall_state=state(a,1000),observed_at=1010)
    assert b.bid_wall_refresh_score > 0
    assert b.bid_wall_velocity_pct_per_sec > 0

def test_fast_removal_spoofing():
    a=MicrostructureEngine.analyze("T",raw(30000),100,observed_at=1000)
    b=MicrostructureEngine.analyze("T",raw(800),100,previous_wall_state=state(a,1000),observed_at=1002)
    assert b.spoofing_probability >= 70
    assert b.bid_wall_velocity_pct_per_sec < 0
