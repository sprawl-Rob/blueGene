# Acceptance and validation — 2026-10-05

## Implemented and tested locally

**32 automated tests pass** using the standard-library unittest runner. JavaScript passes `node --check`. Tests use invented fixtures and mocked APIs, never private family data or paid calls. The browser workflow was checked in the actual local app at port 8877.

| Capability | Evidence | Limits / follow-up |
|---|---|---|
| Local persistence, projects, schema | SQLite restart tests; browser-created Clara Example recovered after actual server restart | Single-user; schema version 1 only |
| Approximate dates, places, conflicts | Two browser-created BIRT claims: ABT 1840 and ABT 1842; both remain; non-Gregorian and dual-year automated cases | Derived intervals are heuristics, not calendar conversion |
| Person → question → recommendations | Browser-created parentage question and explained collection suggestions | Geography is explicit token matching plus reviewed place mappings, not a gazetteer |
| Provider pages / query copies | External HTTP(S) links rendered with opener/referrer protection; copy action exercised | No external record search or authenticated retrieval |
| Negative search → alternative step | Browser log retained exact query/coverage/question; recommendation penalty and spelling, browse and household alternatives observed | Does not infer absence from an index miss |
| Evidence and citations | Browser-created source and locator; checkbox attached citation to second claim; inspector showed excerpt | Researchers determine evidentiary support |
| Competing assertions and many-to-many citations | UI retained both dates; automated shared supporting/contradicting references and cross-project rejection | No automatic merging or proof certification |
| GEDCOM 5.5/5.5.1/7 and raw provenance | Stack parser tests, Unicode/UTF-16, custom tags, notes, families; field-accounting regression; browser GEDZIP preview | ANSEL unsupported; real exporter validation pending |
| Repeat imports and identity review | Same-hash no-op, three-way local-edit conflict, unchanged media reuse, renumbered unique UUID mapping and conflicting UUID rejection tests | Xrefs without usable UID need explicit identity review; renumbered ambiguous trees should remain separate |
| Media / archive safety | Matched media-bearing GEDZIP preview; missing/ambiguous paths, traversal, symlinks, expansion/ratio limits and type signatures tested | Signature checks are not malware scanning; media not present in exports cannot be recovered |
| Atomicity and undo | Cancelled commit rolls back; stale preview and later-edit undo guards tested | Cancellation is best effort at operation checkpoints |
| Full export and restore | ZIP and JSON round trips; checksum failure/broken links rejected; browser downloaded and restored backup to separate database | 64 MiB compressed/upload limit; no GEDCOM export |
| Exact restored evidence links | Browser backup restore independently checked: person → both claims → citation → source, question and negative log | Verification used fictional data |
| Directory breadth and maintenance | 76 entries, 26 collections, 12 local repositories; filters and seed override/archive/conflict tests | Scoped public-page verification, incomplete collection/image coverage |
| Deterministic ranking | Stable ordering, unknown and partial overlap, negative exact search, changed query, hypotheses and exclusions tests | Scores are not probabilities |
| Offline core | Network-blocked mocked transport test exercises local import, persistence and research; actual app has no external core assets | Provider links and opted-in AI require connectivity |
| Host / Origin / CSRF / CSP | Actual handler tests for hostile Host, cross-site GET, unauthorized POST, valid local POST and safe download headers | Not a multi-user authenticated service |
| Rendering and keyboard | 390×844 and 1440×1000 checks; narrow layout has no document overflow; modal opened with Enter, Tab reached labeled person selector, Escape closed and restored focus | Basic accessibility check, not a full assistive-technology audit |
| Database concurrency | 200 read batches across 8 threads after fixing a browser-discovered concurrent-read issue | Heavy imports temporarily serialize database operations |
| Both AI adapters / all five tasks | Ten mocked provider/task runs; model metadata/list/cache, preferences, overrides, schema and reference checks | No live inference has been performed |
| AI failures and privacy | Auth/access/model/quota/size/unavailable errors; cancellation, duplicate token, no fallback, revoked sensitive permission, immutable raw artifacts, nonexistent citation rejection | Unknown model capabilities remain unverified until metadata/test/API response |
| AI controls / grounded review | Anthropic metadata-gated effort test, bounded output, explicit scoped/redacted preview, separate transcript/correction/translation | OpenAI effort remains provider default; images require manual locator/citation selection |
| Secrets | Test credentials absent from export and backup; backend file permissions asserted; no browser storage/logging code | OS file access is not encryption; user must protect backups |
| 10k/50k performance | Measured parse, commit, search, navigation, backup, validation, restoration; actual restored person links asserted | Synthetic workload, single run per phase; see performance.json |

## Browser acceptance trail

Created “UI acceptance · fictional test” and Clara Example with an approximate date and Fitchburg location, added a parentage question, inspected collection explanations, recorded an unsuccessful scoped search, observed the changed advice, created a source and citation, attached it to a second birth-date claim, inspected the excerpt, restarted and recovered the records, downloaded backup and restored it to `bluegene-restored-4cc0f3e5/research.sqlite3`. Independently checked the exact links and original dates in that restored database.

A media-bearing synthetic GEDZIP preview showed 6 people, 7 relationships, 6 assertions, 2 citations, 1 matched TXT media file, zero missing files, original/raw fields and representative profiles before any commit. Automated tests cover commit, identical repeat, changed repeat, undo and restore. The ordinary demo's custom markup is retained as escaped text, not executed.

## Verified live versus pending

Public official resource pages and API documentation were consulted during implementation. Per-entry references, dates and the exact verification scope are in `directory-verification.md` and `seed-directory.json`. 19 entries retain Needs verification; a reachable provider homepage does not establish its collections or access conditions. Current collection title versus actual described coverage differences are explicitly recorded where observed.

**Pending user input:** actual Ancestry GEDCOM and separately exported media; real RootsMagic/Family Tree Maker GEDCOM fixtures if used; credentials and a user-triggered live connection/inference check for each desired provider/model. Passing mocked API tests is not live provider verification, and synthetic GEDCOM headers do not prove real exporter fidelity.

## Performance

`python3 -m scripts.benchmark` generates 10,000 people and 50,000 assertions (3,988,962 input bytes), executes each measured phase, restores into a new database and compares person-linked data. Full results are in `performance.json`: macOS 26.7.1, ARM64, 10 logical CPUs, Python 3.14.3. Exact chip name and RAM were unavailable to the sandbox and are not guessed. Measurements exclude browser rendering and are not a stress/concurrency SLA.


## Smart search extension — 2026-10-05

45 automated tests pass, including 12 new retrieval/privacy/provenance tests and the new HTTP search-preview/static/history guard test. Both JavaScript files pass Node syntax checking. Live Internet Archive search returned 15 items for Frederick Douglass, and public OCR retrieval returned 35,211 characters containing two exact name occurrences. Library of Congress refused HTTP 403. AI provider responses are mocked; live AI access remains pending user credentials. Subscription retrieval is unavailable without provider-approved API access.

Browser verification of this extension could not complete: repeated in-app browser automation calls timed out even after reacquiring the tab. The earlier desktop screenshot and UI acceptance record describe the pre-search interface, not verification of this new screen. See smart-search.md for scope and limits.
