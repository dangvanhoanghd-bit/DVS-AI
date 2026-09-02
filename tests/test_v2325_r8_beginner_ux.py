from types import SimpleNamespace

from dvs_ai.services.plain_language_presenter import PlainLanguagePresenter


def analysis(action="ĐỨNG NGOÀI", direction="SHORT", entry="WAIT", risk=55):
    return SimpleNamespace(
        symbol="HOME/USDT:USDT",
        action=action,
        direction=direction,
        entry_status=SimpleNamespace(value=entry),
        risk=SimpleNamespace(risk_score=risk, risk_level="CAO" if risk > 50 else "THẤP"),
        explainable_blockers=(
            "Đa khung chưa đồng pha đủ mạnh.",
            "Smart Entry chưa có edge xác nhận.",
        ),
        explainable_next_confirmation=(
            "Chờ Structure Test/Spring/Upthrust được xác nhận.",
            "Chờ absorption/passive bid tăng bền vững.",
        ),
        explainable_narrative=SimpleNamespace(market_story=("Dòng tiền đang rút.",)),
    )


def test_stand_aside_is_red_and_plain_language():
    view = PlainLanguagePresenter().build(analysis())
    assert view.traffic_light == "RED"
    assert view.traffic_label == "ĐỨNG NGOÀI"
    assert any("khung thời gian" in x.lower() for x in view.reasons)
    assert any("lực hấp thụ mua" in x.lower() for x in view.next_steps)


def test_ready_low_risk_is_green():
    view = PlainLanguagePresenter().build(analysis(action="VÀO LỆNH", direction="LONG", entry="READY", risk=35))
    assert view.traffic_light == "GREEN"
    assert view.traffic_label == "CÓ THỂ HÀNH ĐỘNG"


def test_presenter_is_observe_only():
    a = analysis()
    before = (a.action, a.direction, a.risk.risk_score, a.entry_status.value)
    PlainLanguagePresenter().build(a)
    after = (a.action, a.direction, a.risk.risk_score, a.entry_status.value)
    assert after == before
