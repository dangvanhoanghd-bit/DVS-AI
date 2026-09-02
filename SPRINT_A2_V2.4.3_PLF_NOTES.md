# Sprint A2 V2.4.3 — Process Lifetime Forensics

## Scope

External launcher/supervisor process starts DVS AI as a subprocess and survives child termination.
No Decision Engine or Paper Trade decision-path change.

## Evidence

- `artifacts/process_lifetime/process_lifetime_forensics.jsonl`
- `artifacts/process_lifetime/plf_session_<uuid>.json`
- `artifacts/process_lifetime/child_<uuid>.stdout.log`
- `artifacts/process_lifetime/child_<uuid>.stderr.log`
- `artifacts/process_lifetime/faulthandler_<pid>.log`
- `artifacts/runtime/process_exit_markers.jsonl`

## Interpretation discipline

A missing Python atexit marker proves only that normal interpreter shutdown was not observed. The external exit code is reported as raw, signed 32-bit, unsigned 32-bit, and hexadecimal. Windows status names are mappings, not standalone root-cause proof.
