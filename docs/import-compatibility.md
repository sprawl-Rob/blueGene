# Import compatibility and provenance

Implementation references: [official GEDCOM specifications](https://gedcom.io/specs/) and [GEDCOM 7](https://gedcom.io/specifications/FamilySearchGEDCOMv7.html), consulted 2026-10-05. The parser is a line tokenizer plus a level-checked hierarchy stack, followed by explicit semantic mapping. Regular expressions are used for derived date search intervals, not to parse GEDCOM structure.

## Format matrix

| Input | Behavior |
|---|---|
| GEDCOM 5.5 / 5.5.1 | Supported hierarchy and mappings below; synthetic fixtures tested |
| GEDCOM 7.0 / 7.0.0–7.0.9 | UTF-8 only; same explicit semantic subset; unknown tags preserved |
| UTF-8, ASCII | Supported, with replacement warnings for undecodable bytes |
| UTF-16 | Requires BOM or a decodable UNICODE declaration; legacy only |
| ANSI | Nonstandard Windows-1252 interpretation, explicitly warned |
| ANSEL or unknown encoding | Actionable rejection; re-export UTF-8, never change only the header |
| Ordinary ZIP | Exactly one `.ged`; nested relative media paths allowed; not claimed to be Ancestry's export format |
| GEDZIP `.gdz` | Unencrypted ZIP subset, root `gedcom.ged`, GEDCOM 7 required |
| Unknown version, duplicate xrefs, malformed hierarchy | Rejected before any project is committed |
| Proprietary RootsMagic/FTM database files | Not supported; export GEDCOM from the desktop application |

This is not a full GEDCOM conformance implementation. Real exporter-specific validation remains pending. Original bytes, content hash, encoding, raw nodes, line numbers, hierarchy and cross-references survive every successful import. Rejected inputs remain on the user's filesystem; the app does not retain them.

## Interpreted versus preserved

The preview/report includes `field_accounting`: interpreted-node count and an explicit list of raw-only nodes with record, tag path and source line. The raw source record can be viewed beside an interpreted record. A node classified as interpreted means that its value or structural edge was used; it does not imply all children were interpreted. Its children are audited separately.

| GEDCOM content | Local representation |
|---|---|
| INDI, NAME (including repeated NAME), UID | Person, aliases, original name structures and persistent identifiers; living status defaults to unknown |
| INDI event/attribute tags | Separate assertions, preserving repetitions and conflicts; source record and event line retained |
| Event DATE | Original expression and calendar preserved; separate derived search interval when interpretable |
| PLAC | Original place text; unresolved until explicitly reviewed |
| FAM HUSB/WIFE/CHIL; matching FAMC/PEDI | Partner and parent-child edges; biological/adoptive/foster/step when explicitly labeled, otherwise unspecified; original roles retained |
| Family events | Assertions with participant IDs and original family key |
| ASSO/RELA | Associate relationship with original role; no identity inference |
| SOUR (shared or inline), PAGE, DATA/TEXT, QUAY | Sources and separate citations, with locator, excerpt, original quality and owner links |
| REPO, source REPO | Repository records and source repository IDs; call numbers and other unsupported children remain raw |
| NOTE/SNOTE, CONT/CONC | Resolved note text, multiline content; shared note identity remains in raw source structure |
| OBJE/FILE | Referenced media edges; full relative path matching, never basename-only association |
| Unknown/custom tags and known fields outside these mappings | Raw preservation, explicit field accounting; no assertion of semantic interpretation |

SEX, detailed structured name parts, RESN, CHAN, vendor hints, unsupported nested events, submitters and extended media metadata are examples of fields that may remain raw-only. A raw-preserved Ancestry URL is not automatically retrieved or converted into a reviewed source.

Date intervals use ±5 years for ABT/CAL/EST, open intervals for BEF/AFT, and ranges for BET/AND or FROM/TO. These are search heuristics, not exact dates. Non-Gregorian dates and ambiguous dual-year dates receive no converted interval. All original wording remains available.

## Repeat imports

The same input bundle hash in the same lineage is a no-op. The original-file hash is recorded separately; explicitly supplied companion media participates in the bundle hash, so missing media can be added later without duplicating people. An updated export requires selecting that lineage and reviewing person mappings. A unique syntactically valid persistent UUID can propose continuity when xrefs were renumbered; it still requires explicit identity confirmation. A reused xref with conflicting persistent UUIDs is rejected for that lineage. Names and dates never establish identity automatically.

Without usable persistent UUIDs, matching xrefs are review proposals only. Renumbered records without a usable UID may appear as additions; import them separately and compare manually rather than confirm uncertain mappings. A three-way field comparison retains local edits and records incoming conflicts. Absent records are retained. Repeat attachments with unchanged full path and hash reuse the managed ID. Undo works only while the import is still the latest project revision; later work blocks it.

## Media and limits

Select the folder containing the GEDCOM-relative paths. Its top directory is stripped: for `FILE media/photo.jpg`, select the parent of `media` or supply a ZIP with that exact path. Matching uses complete relative paths, case-insensitively, and reports ambiguous, missing, unsafe and unused files. Absolute paths are never read. Remote URLs are retained as references and never fetched.

Attachments accept JPEG, PNG, PDF and UTF-8 TXT. Extension/signature, size and safe path checks are applied; this is not malware scanning or a full PDF/image decoder. Files are served as downloads with `nosniff`, never embedded as active content. HTML, SVG and executables are not accepted as attachments.

Import/container limit: 64 MiB; media expansion: 256 MiB; archive entries: 2,000; per-file limit: 64 MiB; compression ratio: 200:1 for entries over 1 MiB. Symlinks, traversal, drive paths, encrypted and duplicate case-folded archive paths are rejected. Backup import additionally allows a 256 MiB manifest and 512 MiB expansion, but retains the 64 MiB compressed/upload limit.

## What Ancestry supplies

The [official Ancestry export guidance](https://help.ancestry.co.uk/hc/en-gb/articles/53933352542867-Uploading-and-Downloading-Trees), checked 2026-10-05, distinguishes GEDCOM data/media references from actual image files. References cannot recover absent photographs or documents. Supply local media separately using the export application's supported transfer workflow. This app neither authenticates to Ancestry nor fetches subscription material. No particular person's migration is verified until their actual export and representative profiles have been checked.

## Parser evaluation

`nickreynke/python-gedcom` was evaluated as a legacy-oriented GPLv2 library; `vaelen/gedcom-lite` was also inspected as a preservation-oriented alternative. Neither dependency was adopted: this release uses its own small standard-library parser to retain the complete source hierarchy and avoid representing library parsing as complete semantic migration. No third-party parser code was copied. The tradeoff is explicit limited format/encoding coverage, including ANSEL, and pending validation against real vendor exports.
