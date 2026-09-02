# M5.3 Audit Notes

- SHA-256 canonical event hashing.
- Per-run GENESIS anchor and previous-hash chain.
- Verification detects payload edits, sequence edits and broken links.
- Existing JSONL bytes are never rewritten by the storage implementation.
- Pipeline integration is optional to preserve backward compatibility.
