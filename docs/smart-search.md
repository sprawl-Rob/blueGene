# Smart search

Implemented 2026-10-05. This workflow executes external searches; the local directory remains a separate source-discovery aid.

| Mode | Implemented scope | Validation |
|---|---|---|
| Internet Archive | Text-item catalog search, first 15 items per query; optional public OCR inspection | Live query for Frederick Douglass returned 15 items of 1,575 reported matches; public OCR download verified (35,211 characters, two exact name occurrences) |
| Library of Congress | Public collection search JSON | Adapter tested; live endpoint refused HTTP 403 in this environment |
| OpenAI | Responses native web search, real tool citations and source links | Mocked responses verified; live account validation pending credentials |
| Anthropic | Messages native web search, at most 3 tool uses, real tool citations | Mocked responses verified; live account validation pending credentials |
| Subscription databases | No adapter without approved API documentation/access | Unavailable; public web leads do not imply access to locked records |

Choose a person or enter a custom query. Query drafting uses recorded names, aliases and locality; no silent historical-place normalization or event-date filter. Preview up to three queries before sending. Archive services receive only those queries. AI providers receive the displayed minimal research context and instructions; notes, tree exports and attachments are not included. AI may reformulate queries within this scope. OpenAI search-call count is provider-managed; token output is bounded but total charges are unknown. Both AI modes require enabling AI and supplying an exact model ID and local credentials. Living/unknown person scope requires an additional per-run acknowledgment.

Each completed attempt is logged. Refusals, malformed responses, partial tool execution and connection failures are not recorded as definitive negative evidence. Successful identical searches are cached for 24 hours, with an explicit run-again option. Cancellation stops subsequent requests; it cannot undo an already submitted provider request or charge. There are no automatic retries or cross-provider fallback.

Ranking is local: exact recorded name/alias overlap +60, surname-only overlap +15, place-text overlap +20. Scores order leads and are not identity probabilities. Catalog search is not a comprehensive person-record or full-text index. Provider totals can exceed the bounded returned page. Dates describe the publication/catalog item rather than proving a life event.

Internet Archive OCR inspection requests only metadata and a listed public DjVuTXT file, with a 6 MiB limit. HTTPS redirects remain within archive.org subdomains. It retains up to 20 matching name excerpts and character offsets, not invented page numbers. The SHA-256 describes decoded UTF-8 text. Restricted items are refused. The saved source/citation initially describes the catalog entry; reviewed OCR findings can be added manually with their file and locator.

Saving evidence requires a locator and creates an unreviewed source plus citation atomically. Search provenance stays linked, repeated acceptance is idempotent, and no person, assertion or relationship is automatically changed. History, raw AI output, native citation metadata and accepted evidence are included in backups. Treat retrieved pages and model output as untrusted research leads.

## References

- [Internet Archive metadata API](https://archive.org/developers/md-read.html)
- [Internet Archive search guide](https://archivesupport.zendesk.com/hc/en-us/articles/360018359991-Search-A-Basic-Guide)
- [Library of Congress API endpoints](https://www.loc.gov/apis/json-and-yaml/requests/endpoints/)
- [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search)
- [Anthropic web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
