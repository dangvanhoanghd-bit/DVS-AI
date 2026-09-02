from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FootprintGraph:
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    chain: tuple[str, ...]
    completeness: float
    direction: str
    explanation: tuple[str, ...]

    @property
    def chain_text(self) -> str:
        return " → ".join(self.chain) if self.chain else "NO_CONFIRMED_CHAIN"


class FootprintGraphEngine:
    """Builds an explainable evidence chain without changing the decision."""

    def build(self, analysis) -> FootprintGraph:
        footprint = getattr(analysis, "footprint", None)
        scores = getattr(footprint, "component_scores", {}) or {}
        direction = str(getattr(footprint, "direction", analysis.direction)).upper()
        lifecycle = str(
            getattr(footprint, "lifecycle_stage", analysis.trend_lifecycle)
        ).upper()
        regime = str(getattr(analysis, "position_building_regime", "UNKNOWN"))

        candidates = [
            ("LIFECYCLE", lifecycle, 1.0 if lifecycle != "UNKNOWN" else 0.0),
            ("LIQUIDITY", "Liquidity Grab/Sweep", float(scores.get("liquidity_sweep", 0))/100.0),
            ("ORDER_BLOCK", f"{direction} Order Block", float(scores.get("order_block", 0))/100.0),
            ("FVG", f"{direction} FVG", float(scores.get("fvg", 0))/100.0),
            ("STRUCTURE", "BOS/CHOCH", float(scores.get("bos_choch", 0))/100.0),
            ("ABSORPTION", "Absorption", float(scores.get("absorption", 0))/100.0),
            ("POSITIONING", regime, float(getattr(analysis, "position_building_score", 0))/100.0),
        ]

        nodes = []
        chain = []
        for key, label, strength in candidates:
            if key == "LIFECYCLE" or strength >= 0.55:
                nodes.append(key)
                chain.append(label)

        edges = tuple(
            (nodes[i], nodes[i+1])
            for i in range(len(nodes)-1)
        )
        completeness = min(100.0, len(nodes)/7.0*100.0)
        explanation = (
            f"Evidence chain contains {len(nodes)}/7 major stages.",
            f"Direction {direction}; completeness {completeness:.1f}/100.",
            "Chain is descriptive only; Decision Engine remains authoritative.",
        )
        return FootprintGraph(
            nodes=tuple(nodes),
            edges=edges,
            chain=tuple(chain),
            completeness=completeness,
            direction=direction,
            explanation=explanation,
        )
