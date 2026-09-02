from __future__ import annotations

import pandas as pd

from dvs_ai.services.frame_ownership_telemetry import FRAME_OWNERSHIP

from .absorption_engine_v2 import AbsorptionEngineV2
from .bos_choch_engine import BosChochEngine
from .footprint_composite import FootprintComposite
from .fvg_engine import FVGEngine
from .liquidity_sweep_engine import LiquiditySweepEngine
from .order_block_engine import OrderBlockEngine
from .position_building_engine import PositionBuildingEngine
from .structure_lifecycle_engine import StructureLifecycleEngine


class FootprintOrchestrator:
    """One-way Smart Money Footprint V2 evidence pipeline."""

    def __init__(self) -> None:
        self.lifecycle = StructureLifecycleEngine()
        self.order_block = OrderBlockEngine()
        self.fvg = FVGEngine()
        self.bos_choch = BosChochEngine()
        self.liquidity_sweep = LiquiditySweepEngine()
        self.absorption = AbsorptionEngineV2()
        self.position_building = PositionBuildingEngine()
        self.composite = FootprintComposite()

    def analyze(
        self,
        ohlcv: pd.DataFrame,
        context: dict,
        expected_direction: str | None = None,
    ) -> dict:
        scan_id = str(context.get("_native2_scan_id", "UNKNOWN"))
        symbol = str(context.get("_native2_symbol", "UNKNOWN"))
        timeframe = str(context.get("_native2_timeframe", "15m"))

        def measured(engine_name, callback):
            with FRAME_OWNERSHIP.operation(
                ohlcv, scan_id=scan_id, symbol=symbol,
                timeframe=timeframe, engine=engine_name,
            ):
                return callback()

        lifecycle = measured(
            "StructureLifecycleEngine.analyze",
            lambda: self.lifecycle.analyze(ohlcv, context),
        )
        enriched = dict(context)
        enriched["lifecycle_stage"] = lifecycle.stage

        order_block = measured("OrderBlockEngine.analyze", lambda: self.order_block.analyze(ohlcv, enriched))
        fvg = measured("FVGEngine.analyze", lambda: self.fvg.analyze(ohlcv, enriched))
        bos_choch = measured("BosChochEngine.analyze", lambda: self.bos_choch.analyze(ohlcv, enriched))
        liquidity_sweep = measured("LiquiditySweepEngine.analyze", lambda: self.liquidity_sweep.analyze(ohlcv, enriched))
        absorption = measured("AbsorptionEngineV2.analyze", lambda: self.absorption.analyze(ohlcv, enriched))

        # Feed available order-flow proxy into Position Building.
        enriched.setdefault(
            "absorption_score",
            float(absorption.phase_quality),
        )
        position_building = measured(
            "PositionBuildingEngine.analyze",
            lambda: self.position_building.analyze(ohlcv, enriched),
        )

        components = {
            "order_block": order_block,
            "fvg": fvg,
            "bos_choch": bos_choch,
            "liquidity_sweep": liquidity_sweep,
            "absorption": absorption,
            "position_building": position_building,
            "lifecycle": lifecycle,
        }
        composite = self.composite.combine(
            components,
            expected_direction=expected_direction,
        )

        return {
            "lifecycle": lifecycle,
            "order_block": order_block,
            "fvg": fvg,
            "bos_choch": bos_choch,
            "liquidity_sweep": liquidity_sweep,
            "absorption": absorption,
            "position_building": position_building,
            "components": components,
            "composite": composite,
        }
