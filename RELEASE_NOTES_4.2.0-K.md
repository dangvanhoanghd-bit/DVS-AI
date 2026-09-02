# DVS AI Alpha 4.2.0-K

## Research Governance Export & Independent Audit Bundle

Adds a read-only audit export that packages governance coverage, lineage/provenance, incidents, alerts, CSV tables, source database SHA-256 fingerprints, a signed-style manifest, HTML index, and an offline verification script into one independent ZIP.

The exporter opens source databases read-only, verifies that their hashes are unchanged after export, and never invokes or modifies the Decision Engine.
