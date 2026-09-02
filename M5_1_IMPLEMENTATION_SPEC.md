# M5.1 Scientific Core Contracts — Implementation Specification

## Scope
Introduce immutable, versioned contracts shared by evidence, validation, certification, registry and explainability layers.

## Safety boundaries
- Contract package has no dependency on GUI, runtime, exchange, execution or database packages.
- No network, file write, order or deployment behavior.
- Evidence cannot be marked meaningful unless every hard gate has passed.
- Registry cannot mark a model REGISTERED without a certification identifier.
- Lifecycle transitions are explicit and fail closed.

## Added package
`dvs_ai/scientific/contracts/`

Contracts:
- `EvidenceRecord`
- `EvidenceDelta`
- `ValidationResult`
- `CertificationRecord`
- `RegistrySnapshot`
- `ExplainabilityTrace`
- `ScientificLifecycleState`
- `ScientificReasonCode`
