"""Single source of truth for DVS AI Alpha build identity.

RC6.4.7H establishes auditable governance instrumentation while preserving
the stable public constants consumed by the UI and other modules.
"""

APP_NAME = "DVS AI"
APP_VERSION = "RC6.4.7H-r2-GR-01A-MEASUREMENT-CALLBACK-DECOMPOSITION"
APP_EDITION = (
    "Technical Standard Validation · Auditable Telemetry · "
    "Census Default-Off · Paper-only"
)
WINDOW_TITLE = f"{APP_NAME} Alpha {APP_VERSION} – {APP_EDITION}"
EXECUTION_STATUS_LABEL = "● DATA LIVE · ORDERS LOCKED"

RELEASE_CHANNEL = "BETA2A_UNIFIED_OUTCOME_FOUNDATION"
BUILD_ID = "RC6.4.7H-r2-GR-01A-MEASUREMENT-CALLBACK-DECOMPOSITION"

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "APP_EDITION",
    "WINDOW_TITLE",
    "EXECUTION_STATUS_LABEL",
    "RELEASE_CHANNEL",
    "BUILD_ID",
]
