# blueGene

A private, local genealogy research notebook. Import a tree, retain its evidence and uncertainty, record searches, and choose an explainable next step. The directory and research tools work offline without accounts or API keys.

## Start

Requires **Python 3.10 or newer**. No packages or build step are required. Tested on this Mac with Python 3.14.3.

Double-click **Start blueGene.command**, or run from this directory:

```sh
python3 -m bluegene
```

Open **http://127.0.0.1:8877/**. Keep the Terminal process running; Ctrl-C stops it. If the port is occupied, use `python3 -m bluegene --port 8878` and open that port. The app binds only to this computer's loopback interface.

## First research session

1. Select the clearly labeled fictional Whitcomb demonstration, or create your own project.
2. Under **Import & backups**, select an Ancestry/desktop GEDCOM, ordinary ZIP with one GEDCOM, or supported GEDZIP. Optionally select exported media. Preview first; review warnings, profiles and raw-only fields before committing.
3. Open a person and add a focused research question. Preserve competing dates as separate assertions.
4. Use **Next searches** to see collection coverage, the hypothesis used, access restrictions, exclusions and suggested queries. Use **Smart search** to execute reviewed queries against public archives or an AI web-search provider.
5. Record what you actually searched, including filters, coverage and negative results. Add sources and citations, then attach those citations to supporting or contradicting claims.
6. Download a backup ZIP. Restore validates links and checksums and creates a **separate database**, with its launch command shown in the result.

A second project named “UI acceptance · fictional test” may be present in this working copy: it contains invented Clara Example data used for browser validation. It is not family research.

## Optional AI

Settings supports OpenAI and Anthropic, an exact default model ID, task overrides, model-list refresh, and a metadata-only or explicitly charge-bearing connection test. Supply keys yourself in Settings or through `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`. AI is disabled initially. No inference occurs when opening Settings.

Each planning, query, transcription, comparison or summary action shows the selected provider, model, actual fields and attachment list before consent. Redact the preview or cancel it. Living or unknown-status people and all attachments require a separate sensitive-data preference. Output remains a reviewable artifact; it never automatically merges people, creates sources or replaces claims. Costs are labeled unknown. There is no cross-provider fallback. Smart search is a separate workflow that retrieves external public results after a reviewed preview.

Both AI adapters are implemented and tested with mocked responses. **Live provider validation is pending user credentials.** Model capabilities and account access vary; listing an ID does not guarantee compatibility.

## Data and backups

Default data lives in `data/research.sqlite3`. Research, original import bytes, raw GEDCOM hierarchy, history and managed attachment bytes live in SQLite, so a transaction can roll back an import completely. Credentials are separate in `data/credentials.json` with owner-only permissions; they are excluded from application backups and source control. The data directory is owner-only. This is not application-level encryption: protect the Mac and any exported files.

Use the application's ZIP backup or structured JSON export for portability. CSV exports cover directory entries and search logs. GEDCOM **export** is not implemented; GEDCOM import and full-fidelity blueGene restore are different workflows. Do not copy a running SQLite file by itself: its WAL may contain recent work. Stop the app first or use the application backup.

## Validation and limits

```sh
python3 -m unittest discover -s tests -v
python3 -m scripts.benchmark
node --check static/app.js   # optional developer syntax check; Node is not needed to run the app
```

See [validation](docs/validation.md), [import compatibility](docs/import-compatibility.md), [architecture](docs/architecture.md), [directory verification](docs/directory-verification.md), and [measured performance](docs/performance.json).

Actual Ancestry, RootsMagic and Family Tree Maker exports have **not** been supplied or validated. ANSEL files require a UTF-8 re-export. Some vendor/custom fields are preserved raw without semantic mapping. Media is never fetched remotely. There is no continuous Ancestry synchronization, account scraping, DNA analysis or tree-merging engine. Inspect representative profiles before treating any migration as complete.

## Smart search

Open **Smart search** in the sidebar. Build queries from recorded names, aliases and locality, edit the queries, and review the exact outbound scope before execution. Internet Archive search requires no account; AI web research uses your configured OpenAI or Anthropic key and exact model ID. Results include clickable sources, explainable local ranking, search history and optional public OCR inspection. Saving a lead creates an unreviewed source and citation, never a family claim.

Subscription API retrieval remains unavailable until provider-approved access is supplied. AI search can find publicly indexed subscription-site pages but cannot read locked records. See [search scope and validation](docs/smart-search.md).
