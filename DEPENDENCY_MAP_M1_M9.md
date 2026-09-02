# Unified Dependency Map

```text
M1–M4 legacy data / indicator / evidence / registry layers
                    |
                    v
             MarketSnapshot
                    |
                    v
M9 StrategyIntelligenceEngine -> FusedSignal
                    |
                    v
M5 ScientificLedger integrity and AVAILABLE lifecycle
                    |
                    v
M6 StrategyDecisionBridge / DecisionAdapter
                    |
                    v
M7 RiskManager -> PaperTradingEngine -> PaperPortfolio
                    |
                    v
M8 RuntimeHealthMonitor + AlertCenter
                    |
                    v
            DVSAICore + EventBus
```

The application kernel owns orchestration. Domain modules do not import the kernel, preventing circular dependencies.
