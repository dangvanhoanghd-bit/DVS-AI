# RC6.4.7G-r1 — Non-blocking Telemetry & Auto-paper Hang Probe

- Confirms the prior implementation used `threading.Lock` in `RetentionOwnerTelemetry`.
- Every telemetry lock acquisition is now `blocking=False`; a busy lock drops telemetry and increments primitive diagnostics.
- Adds precise auto-paper stage markers around owner release, retention mutation, and worker emit.
- The callback monitor writes one all-Python-thread faulthandler dump after a callback remains active for 5 seconds.
- Regenerates SOURCE_SHA256.txt and both code identity manifests from the same final source tree.
- Decision Engine remains unchanged and paper-only constraints remain in force.
