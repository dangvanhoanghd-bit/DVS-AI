from dvs_ai.engines.retest_rules import assess_retest, breakout_buffer


def test_no_retest_gets_zero_score():
    result = assess_retest(
        direction="LONG",
        close=101.5,
        high=102.0,
        low=101.4,
        level=100.0,
        atr=1.0,
        relative_volume=0.5,
        breakout_close=101.0,
    )
    assert result.confirmed is False
    assert result.score == 0.0
    assert "Chưa có retest" in result.reason


def test_breakout_requires_buffer():
    # Only one tick above level: should not qualify.
    result = assess_retest(
        direction="LONG",
        close=100.05,
        high=100.10,
        low=99.95,
        level=100.0,
        atr=1.0,
        relative_volume=0.5,
        breakout_close=100.01,
    )
    assert result.confirmed is False
    assert result.score == 0.0
    assert "Breakout chưa đủ lớn" in result.reason


def test_low_volume_confirmed_retest_scores_high():
    result = assess_retest(
        direction="SHORT",
        close=98.8,
        high=100.05,
        low=98.5,
        level=100.0,
        atr=1.0,
        relative_volume=0.55,
        breakout_close=99.0,
    )
    assert result.confirmed is True
    assert result.score == 20.0


def test_breakout_buffer_uses_atr_or_price():
    assert breakout_buffer(100.0, 2.0) == 0.3
    assert breakout_buffer(1000.0, 0.1) == 1.0
