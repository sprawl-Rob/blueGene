# Architecture and operating boundaries

Python's standard library serves a static HTML/CSS/JavaScript client on loopback. SQLite supplies durable, transactional local storage without installing a framework or database service. The maintainability tradeoff is manual request validation and a compact client instead of framework machinery.

## Modules

- `gedcom.py`: bounded archive decoding, hierarchical GEDCOM parser, date preservation, explicit normalization and field accounting.
- `store.py`: schema version 1, indexed project/kind/person lookups, edit history, seed three-way updates, staged imports, deterministic merges, managed BLOB attachments, export/restore validation.
- `recommend.py`: local deterministic ranking and filters; no network or AI.
- `seeds.py`: versioned provider, collection, repository and pathway metadata with per-entry verification scope.
- `ai.py`: scoped task interface; distinct OpenAI Responses and Anthropic Messages payloads, metadata/list requests, validated review artifacts.
- `server.py`: HTTP boundary, CSRF/Origin/Host checks, bounded background jobs and preview lifecycle.
- `static/`: responsive, keyboard-operable workspace. Research and credentials are not stored in browser localStorage.

Entity IDs are local UUIDs, scoped by a project. Flexible JSON fields preserve raw detail; application validation checks typed person/source/citation/participant/repository/attachment edges and disallows cross-project references. Projects carry a revision for stale-preview and undo protection. Read operations and mutations share a reentrant database lock; imports are committed in one transaction. Long jobs show progress and cancellation; an already committed operation cannot be cancelled. Parse/backup validation cancellation is checked at phase boundaries rather than inside every parser instruction.

Schema initialization records migration 1. There is no destructive upgrade in this version. A future migration must create a verified backup before changing or removing schema, add its version, and test upgrade/rollback on a copied database. The app does not claim a tested future upgrade path.

## Recommendations, rules v1

For each assertion hypothesis, explicit recorded geography and overlapping dates are evaluated separately. A user-accepted historical place mapping is used only within its effective dates. No gazetteer or modern-boundary-to-historic-jurisdiction inference is implemented. Full token inclusion gives known geographic overlap; partial shared locality terms give partial overlap; missing data is unknown. This can still confuse homonymous places: review recorded jurisdictions and collection details.

Weights: known geography +40, partial +15; contained dates +30, overlapping +10; relevant record type +20; available subscription +8, otherwise free search +5. The same no-result query, person, question, collection and coverage receives −25. A changed query is not penalized as the same search. Alternative index/browse/household routes remain visible. Provider-wide suppression never occurs. Collection overlap metadata warns that multiple copies are not independent evidence.

Known/partial/exploratory bands sort first, then descending score, then stable resource ID. Only coverage-checked entries can be a known match. All supplied assertions remain; the selected hypothesis appears on every result. Known disjoint coverage is excluded with an explanation. Scores are ordering weights, not probabilities.

## Security and privacy

- Exact loopback Host allowlist; cross-site GET requests rejected; state changes require same-origin (when supplied) and a random per-process CSRF token. No permissive CORS.
- Self-only script/style/connect CSP, no active object embedding, frame protection, `nosniff`, no referrer and no-store responses.
- Dynamic text is escaped. Outbound links must be HTTP(S) and open without opener/referrer. CSV exports neutralize leading spreadsheet formula markers.
- No telemetry, background provider requests, remote media retrieval, system-file resolution from GEDCOM paths, or unsolicited external searches. Reviewed Smart search requests retrieve public catalog data and optional OCR.
- Credentials remain on the backend, in an owner-readable file or environment. They are absent from research backups, logs and browser storage. This is not an encrypted credential vault.
- Local HTTP has no multi-user login. It is intended for one trusted OS account; another process in that account can access the app. Do not expose it through a proxy or tunnel as an authenticated service.
- Backups contain private research. ZIP hashes detect changed/missing binary blobs; they are integrity checks, not signed authenticity or encryption.

## AI boundaries

Current official API references consulted 2026-10-05: [OpenAI text/Responses](https://developers.openai.com/api/docs/guides/text), [OpenAI models](https://developers.openai.com/api/reference/resources/models), [Anthropic models](https://platform.claude.com/docs/en/api/models/list), and [Anthropic messages](https://platform.claude.com/docs/en/api/messages/create). Account metadata is rechecked before inference. Unsupported known capabilities are rejected; unknown capabilities remain explicitly unverified. Output token limits are exposed. Anthropic effort controls appear only for values explicitly supported by cached model metadata and are rechecked before inference. OpenAI effort is left at provider default because its generic model listing does not supply the corresponding capability matrix.

Each preview is bound to an exact provider/model, context and attachments. Changed context requires a new preview/consent; previews expire after 30 minutes and can be submitted once. Maximum scope is 30 records and 3 attachments, 10 MiB each, with a bounded text context. Document-analysis requests have no tools. The separate Smart search workflow enables the provider-native web-search tool, retains its citations, and never executes arbitrary model-generated tools. Supplied content is explicitly untrusted data. There are no automatic retries or fallbacks when completion/charges may be uncertain.

Artifacts preserve prompt/task versions, schema, input context, source IDs, raw and parsed output, attachment IDs, usage when available, elapsed time, and acceptance history. Returned citation IDs and locators must exist in the approved context. The inspector presents source excerpts, but human review must decide whether they support the statement. Raw artifact fields are immutable through the UI; corrected transcription and review rationale are separate. AI-assisted claims require manual creation with citations.
