# M5.2 Scientific Lifecycle Pipeline

Implements a dependency-injected, pure orchestration layer over the immutable M5.1 contracts.
The ordered lifecycle is RAW → FEATURED → EVIDENCE_READY → VALIDATED → CERTIFIED → REGISTERED → AVAILABLE.
Any rejected artifact or exception transitions to FAILED and stops all downstream stages.
No GUI, exchange, execution, runtime, or database package is imported.
