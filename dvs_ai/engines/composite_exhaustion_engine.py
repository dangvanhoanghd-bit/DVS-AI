from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class CompositeExhaustionResult:
    distribution_progress: float
    selling_pressure: float
    exhaustion_score: float
    absorption_score: float
    passive_bid_score: float
    panic_score: float
    bottom_formation_probability: float
    state: str
    bottom_state: str
    observe_only: bool
    explanation: tuple[str, ...]
    timeline: tuple[str, ...]


class CompositeExhaustionEngine:
    """Observe-only heuristic for composite selling exhaustion.

    This engine never creates an entry, changes confidence, or bypasses any
    Decision/Smart Entry gate.  Its probability is an evidence-progress score,
    not a forecast that a precise market bottom has been found.
    """

    def __init__(self, history_size: int = 12) -> None:
        self._history_size = max(4, int(history_size))
        self._history: dict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=self._history_size)
        )
        self._lock = RLock()

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(100.0, float(value)))

    def evaluate(self, analysis) -> CompositeExhaustionResult:
        tf15 = analysis.timeframes.get("15m")
        tf1h = analysis.timeframes.get("1h")
        snap = analysis.snapshot
        micro = getattr(analysis, "microstructure", None)
        smart = analysis.smart_entry
        structure = analysis.structure

        price_loss = max(0.0, -float(getattr(snap, "change_24h_pct", 0.0)))
        cmf15 = float(getattr(tf15, "cmf", 0.0)) if tf15 else 0.0
        cmf1h = float(getattr(tf1h, "cmf", cmf15)) if tf1h else cmf15
        rsi15 = float(getattr(tf15, "rsi", 50.0)) if tf15 else 50.0
        adx15 = float(getattr(tf15, "adx", 0.0)) if tf15 else 0.0
        short_trend = float(getattr(analysis, "short_trend_score", 0.0))
        oi15 = float(getattr(snap, "oi_change_15m_pct", 0.0))
        oi1h = float(getattr(snap, "oi_change_1h_pct", 0.0))
        funding = float(getattr(snap, "funding_pct", 0.0))

        absorption = self._clamp(
            getattr(micro, "absorption_score", getattr(smart, "absorption_score", 0.0))
        )
        bid = self._clamp(getattr(micro, "bid_wall_effective_score", 0.0))
        ofi = float(getattr(micro, "ofi_score", 0.0))
        book = float(getattr(micro, "book_imbalance", 0.0))
        micro_exhaustion = self._clamp(getattr(micro, "exhaustion_score", 0.0))
        panic = self._clamp(getattr(smart, "panic_flush_score", 0.0))

        distribution = self._clamp(
            0.26 * min(100.0, price_loss * 2.2)
            + 0.24 * self._clamp((-cmf15) * 220.0)
            + 0.18 * self._clamp((-cmf1h) * 180.0)
            + 0.18 * short_trend
            + 0.14 * min(100.0, adx15 * 1.8)
        )
        selling = self._clamp(
            0.30 * distribution
            + 0.22 * self._clamp((-cmf15) * 230.0)
            + 0.16 * self._clamp((-ofi) * 1.2)
            + 0.12 * self._clamp((-book) * 180.0)
            + 0.10 * self._clamp(max(0.0, oi1h) * 45.0)
            + 0.10 * self._clamp(max(0.0, -funding) * 30.0)
        )

        price_stretch = self._clamp(price_loss * 2.4)
        oversold = self._clamp((42.0 - rsi15) * 4.0)
        oi_relief = self._clamp(max(0.0, -oi15) * 50.0)
        micro_turn = self._clamp(max(0.0, ofi) * 1.1 + max(0.0, book) * 160.0)
        exhaustion = self._clamp(
            0.20 * price_stretch
            + 0.16 * oversold
            + 0.17 * absorption
            + 0.12 * bid
            + 0.13 * oi_relief
            + 0.12 * micro_turn
            + 0.10 * micro_exhaustion
        )

        spring = bool(getattr(tf15, "spring", False)) if tf15 else False
        test_long = bool(getattr(tf15, "wyckoff_test_long", False)) if tf15 else False
        structure_test = str(getattr(structure, "wyckoff_test", "NONE")).upper()
        structure_confirmed = spring or test_long or structure_test not in {"", "NONE"}
        cmf_turn = cmf15 > -0.05 and cmf15 > cmf1h
        flow_turn = ofi > 8.0 and book > 0.02
        stabilization = oi15 <= 0.0 and rsi15 >= 32.0

        bottom_probability = self._clamp(
            0.28 * exhaustion
            + 0.17 * absorption
            + 0.12 * bid
            + 0.13 * micro_turn
            + (12.0 if cmf_turn else 0.0)
            + (14.0 if structure_confirmed else 0.0)
            + (8.0 if stabilization else 0.0)
            - 0.18 * selling
        )
        # Fail-closed guardrails: no structural/flow confirmation means this
        # remains an early-warning score, never a confirmed-bottom claim.
        if not structure_confirmed:
            bottom_probability = min(bottom_probability, 49.0)
        if absorption < 35.0 and not flow_turn:
            bottom_probability = min(bottom_probability, 39.0)
        if cmf15 < -0.15 and selling > 65.0:
            bottom_probability = min(bottom_probability, 29.0)

        if selling >= 50.0 and exhaustion < 45.0:
            state = "SELLING"
        elif selling >= 50.0 and exhaustion >= 45.0:
            state = "SELLING_EXHAUSTING"
        elif exhaustion >= 60.0 and (flow_turn or structure_confirmed):
            state = "ABSORPTION_WATCH"
        elif selling < 40.0 and exhaustion >= 55.0:
            state = "SELLING_PAUSED"
        else:
            state = "MIXED"

        if bottom_probability >= 70.0 and structure_confirmed and flow_turn:
            bottom_state = "BOTTOM_FORMATION_CONFIRMED_FOR_REVIEW"
        elif bottom_probability >= 45.0:
            bottom_state = "BOTTOM_FORMATION_WATCH"
        else:
            bottom_state = "BOTTOM_NOT_CONFIRMED"

        marker = {
            "SELLING": "SELL",
            "SELLING_EXHAUSTING": "SELL_EXHAUSTING",
            "ABSORPTION_WATCH": "ABSORB_WATCH",
            "SELLING_PAUSED": "SELL_PAUSED",
            "MIXED": "NEUTRAL",
        }[state]
        with self._lock:
            history = self._history[str(analysis.symbol)]
            history.append(marker)
            timeline = tuple(history)

        explanation = (
            f"Distribution estimate {distribution:.1f}/100; selling pressure {selling:.1f}/100.",
            f"Exhaustion {exhaustion:.1f}; absorption {absorption:.1f}; passive bid {bid:.1f}.",
            f"Flow turn {'YES' if flow_turn else 'NO'}; CMF turn {'YES' if cmf_turn else 'NO'}; structure confirmation {'YES' if structure_confirmed else 'NO'}.",
            f"Bottom-formation evidence {bottom_probability:.1f}/100 ({bottom_state}).",
            "Observe-only: this score never creates an entry or identifies an exact bottom price.",
        )
        return CompositeExhaustionResult(
            distribution_progress=distribution,
            selling_pressure=selling,
            exhaustion_score=exhaustion,
            absorption_score=absorption,
            passive_bid_score=bid,
            panic_score=panic,
            bottom_formation_probability=bottom_probability,
            state=state,
            bottom_state=bottom_state,
            observe_only=True,
            explanation=explanation,
            timeline=timeline,
        )
