"""Pure, storage-free Knowledge Graph runtime helpers (Slice 7).

This package holds logic shared by *both* the extraction engine and the
persistence projector: deterministic page-template fingerprinting
(`templates`) and frozen-contract execution policy (`contract_runtime`).

It lives under ``app.core`` — not ``app.extraction`` (which is at its ratcheted
24-file ceiling) and not ``app.persistence`` (which the extraction architecture
ratchet forbids extraction from importing). Everything here is pure: no database
access, no ORM, no I/O. The projector and the engine call into it; it calls into
neither.
"""
