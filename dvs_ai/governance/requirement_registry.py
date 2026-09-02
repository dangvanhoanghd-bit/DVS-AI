from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Literal

EvidenceLevel = Literal["A", "B", "C"]
VerificationSource = Literal["SOURCE", "RUNTIME", "SOURCE+RUNTIME"]

@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    title: str
    normative: str
    verification_method: str
    verification_source: VerificationSource
    required_evidence_level: EvidenceLevel

REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("TS-0.1", "No unverifiable MUST", "Every MUST MUST have a documented independent verification path.", "Review registry and generated matrix; no verification fields may be empty.", "SOURCE", "B"),
    Requirement("TS-3.1", "Single source release identity", "APP_VERSION and BUILD_ID MUST each have exactly one assignment in source; all manifests MUST derive from them.", "AST-scan source assignments, then compare generated manifests and runtime identity.", "SOURCE+RUNTIME", "A"),
    Requirement("TS-6.1", "JSONL writer integrity", "The writer MUST NOT create malformed records during normal operation; interrupted shutdown MUST be distinguishable.", "Validate every JSONL line and classify malformed tails using explicit shutdown evidence.", "RUNTIME", "C"),
    Requirement("TS-7.1", "Callback attribution", "Instrumented callbacks MUST expose stable name and duration; summary MUST expose P50/P95/P99/max.", "Inspect attribution source and validate runtime callback records and summary.", "SOURCE+RUNTIME", "A"),
    Requirement("TS-8.1", "Memory budget ownership", "Each memory budget MUST declare a real owner_path, measurement method and item count; residual MUST NOT be represented as an owner budget.", "Inspect estimator registry and compare runtime records to live owner paths.", "SOURCE+RUNTIME", "A"),
    Requirement("TS-9.1", "Estimator lifetime", "Temporary measurement references MUST remain inside measurement scope and MUST NOT escape into callback, queue or cache.", "Inspect lexical scope and lifetime helper; run negative lifetime tests.", "SOURCE", "B"),
    Requirement("TS-9.2", "No measurement deepcopy", "Estimators MUST NOT deepcopy payloads solely for measurement.", "Static scan estimator modules for deepcopy/copy patterns and inspect measurement code.", "SOURCE", "B"),
    Requirement("TS-10.1", "Thread identity", "Every estimator record MUST expose measurement_thread_id, gui_thread_id and is_gui_thread.", "Inspect thread identity implementation and validate emitted runtime fields.", "SOURCE+RUNTIME", "A"),
    Requirement("TS-10.2", "GUI thread safety", "Heavy estimators MUST NOT execute on the GUI thread.", "Compare measurement_thread_id against gui_thread_id for every heavy estimator record.", "SOURCE+RUNTIME", "A"),
    Requirement("TS-11.1", "Traversal deadline", "Bounded traversal estimators MUST check their deadline inside the traversal loop where cancellation is possible.", "Inspect loop body and run deadline regression test.", "SOURCE", "B"),
    Requirement("TS-12.1", "Burn-in evidence", "A validation burn-in MUST record runtime, RSS, allocator, GC, callback and memory-budget evidence.", "Validate required artifact presence and non-empty runtime records.", "RUNTIME", "C"),
    Requirement("TS-15.1", "Telemetry compatibility", "Schema evolution MUST append fields or bump schema_version; existing field meanings MUST NOT change silently.", "Diff schema declarations and validate schema_version in runtime records.", "SOURCE+RUNTIME", "A"),
    Requirement("TS-16.1", "Fail-open instrumentation", "Instrumentation MUST fail open and MUST NOT change pipeline semantics.", "Inspect exception/lock paths and execute negative failure injection tests.", "SOURCE+RUNTIME", "A"),
    Requirement("TS-17.1", "Shutdown safety", "Instrumentation MUST NOT block shutdown or retain worker/thread/queue references after shutdown.", "Inspect shutdown paths and validate clean shutdown lifecycle telemetry.", "SOURCE+RUNTIME", "A"),
)

def requirement_dicts() -> list[dict[str, str]]:
    return [asdict(item) for item in REQUIREMENTS]
