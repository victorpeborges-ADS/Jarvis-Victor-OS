# ADR-010 — Trust Boundary for Local Review Authenticity

- Status: accepted for the R6 candidate; no formal G5 acceptance implied.
- Date: 2026-09-30.
- Supersedes: none. Clarifies the local authenticity limit described by ADR-009.

## Context

G5 stores mission data, review snapshots, hashes, decisions, and the review ledger in one local SQLite database. The application can compare those records and detect contradictions. A writer with unrestricted access to that same database can also fabricate a mutually consistent set of records. That database contains no independent evidence that distinguishes a human decision made through the API from a fabricated decision made by its administrator.

Adding more joins, strings, hashes, or snapshots inside the same database cannot close that gap. R6 does not add cryptographic signatures, local key stores, external keys, or remote identity services.

## Decision

For G5, JARVIS code and process, the versioned synthetic catalog, process-controlled local files, and SQLite under normal application operation are the trusted computing base (TCB). G5 derives canonical review state from the review, immutable snapshot, exact version/hash binding, and ledger record. It derives selected-source trust from one complete owner/mission/domain/artifact/source/catalog/bytes/knowledge/review/snapshot chain and the review ledger when a decision exists.

The supported guarantee is:

> Any database tampering that is inconsistent with the existing canonical chain fails closed.

G5 does not guarantee cryptographic authenticity against an administrator who can fabricate all coherent rows in SQLite, alter the executable, or control both code and database. Such a writer is outside this gate's authenticity guarantee. Stronger authenticity requires a future identity/secure-storage gate with a trust root outside SQLite.

| Threat | Inside G5? | Control or boundary |
|---|---:|---|
| Client without a valid session/grant | Yes | Volatile local session/grant checks and server-side domain filters |
| Client payload or imported decision claim | Yes | Strict input models; imported decision claims are rejected/quarantined |
| Cross-owner, cross-mission, or cross-domain source link | Yes | One full relational source projection; mismatches are withheld |
| Stale review, replay, or old-version decision | Yes | Current artifact version, snapshot/hash comparison, idempotency, and ledger checks |
| Inconsistent SQLite edits | Yes | Rebuild the canonical chain and fail closed on any broken edge |
| Revocation and concurrent read/reconcile order | Yes | Existing grant confirmation and store lock order; regression probes |
| Arbitrary administrator fabricates a fully coherent review + ledger | **No** | Outside G5 authenticity guarantee; future external trust root required |
| Administrator changes executable and database together | **No** | Host-administrator compromise is outside this local gate |
| Remote attacker | Not applicable to this gate | API binds to loopback; remote access is not enabled |

## Consequences

- A ledger row that is missing, stale, duplicated, or inconsistent remains invalid and cannot approve a supported read or action.
- A fully coherent SQLite fabrication is documented as a TCB assumption, not misrepresented as detectable tampering.
- Sessions and grants remain volatile and local. G5 remains local, synthetic, and single-process.
- OAuth, remote services, multiworker operation, personal data, signatures, Keychain/Keystore, and external trust roots remain outside R6.

## Evidence

`apps/api/test_r6_combined_tampering.py` includes 19 inconsistent tampering combinations and a separate passing boundary demonstration showing why an all-powerful SQLite writer is outside G5 authenticity. `docs/r6/TRUST_BOUNDARY.md` and `docs/r6/TRUSTED_STATE_MATRIX.md` state the operational contract.
