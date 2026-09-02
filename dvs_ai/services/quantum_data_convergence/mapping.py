from __future__ import annotations

from dataclasses import dataclass


UNIFIED_TERMINAL = frozenset({"WIN", "LOSS", "AMBIGUOUS", "EXPIRED_UNFILLED"})


@dataclass(frozen=True)
class MappingResult:
    original_status: str | None
    original_result: str | None
    unified: str
    rule_id: str


class OutcomeMappingError(ValueError):
    pass


def map_legacy_outcome(*, status: object, result: object, realized_r: object = None) -> MappingResult:
    """Map terminal paper-trade vocabulary with explicit governed rules.

    CLOSED is a lifecycle status, not an outcome label. Explicit terminal
    results are mapped without using PnL, except PARTIAL_STOP: that legacy
    label encodes a split exit whose net result can only be classified from
    finite realized-R. The exception is isolated under a provenance rule ID.

    INVALID is a historical name for STOP_BEFORE_TP1 after a filled trade,
    not an unfilled setup invalidation; therefore it maps to LOSS. Unknown
    values fail closed instead of being guessed.
    """
    s = str(status or "").strip().upper()
    r = str(result or "").strip().upper()
    if s != "CLOSED":
        raise OutcomeMappingError(f"legacy record is not terminal: status={s!r}")
    table = {
        "WIN": ("WIN", "LEGACY_RESULT_WIN_V1"),
        "LOSS": ("LOSS", "LEGACY_RESULT_LOSS_V1"),
        "TP2": ("WIN", "LEGACY_TP2_TO_WIN_V1"),
        "STOP": ("LOSS", "LEGACY_STOP_TO_LOSS_V1"),
        "SL": ("LOSS", "LEGACY_SL_TO_LOSS_V1"),
        "INVALID": ("LOSS", "LEGACY_INVALID_TO_LOSS_V1"),
        "AMBIGUOUS": ("AMBIGUOUS", "LEGACY_AMBIGUOUS_V1"),
        "PARTIAL_AMBIGUOUS": ("AMBIGUOUS", "LEGACY_PARTIAL_AMBIGUOUS_COLLAPSE_V1"),
        "EXPIRED": ("EXPIRED_UNFILLED", "LEGACY_EXPIRED_TO_UNFILLED_V1"),
    }
    if r == "PARTIAL_STOP":
        try:
            value = float(realized_r)
        except (TypeError, ValueError) as exc:
            raise OutcomeMappingError("PARTIAL_STOP requires finite realized_r") from exc
        if value != value or value in (float("inf"), float("-inf")):
            raise OutcomeMappingError("PARTIAL_STOP requires finite realized_r")
        unified = "WIN" if value > 0.0 else "LOSS"
        rule_id = "LEGACY_PARTIAL_STOP_R_SIGN_V1"
        return MappingResult(s, r, unified, rule_id)
    try:
        unified, rule_id = table[r]
    except KeyError as exc:
        raise OutcomeMappingError(f"unsupported legacy result: {r!r}") from exc
    return MappingResult(s, r, unified, rule_id)


def map_episode_outcome(*, status: object) -> MappingResult:
    s = str(status or "").strip().upper()
    if s not in UNIFIED_TERMINAL:
        raise OutcomeMappingError(f"episode outcome is not terminal/supported: {s!r}")
    return MappingResult(s, s, s, "EPISODE_NATIVE_V1")
