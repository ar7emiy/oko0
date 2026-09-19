# Windows Excel acceptance run

Status: this checklist requires licensed Windows desktop Excel. Static checks and workbook rendering do not constitute a VBA runtime pass.

Use a disposable .xlsm named QA-Annotation.xlsm. Wire every module and compile. Run RunCoreSelfTests. Record Excel version/bitness, file location, AutoSave state and result for every case below.

| Test | Expected result |
|---|---|
| Setup twice, save under another name and setup again | One button per action; every action targets this workbook; no merged cells. |
| With no Copilot, import the 60-note fictional packet | 60 source rows; full source text; reading order editable. |
| First note, first word: Dr. Ada Monroe | Occurrence 1 starts at offset 0; new entity and first mention save together. |
| Same quote, occurrence 2 | Different exact source span; link to first Ada entity, not a duplicate. |
| Save address, TIN, context, statement and uncertain text | All correct output tables populate; leading zeros preserved; evidence locates. |
| Same name for two people / ambiguous pronoun | Reviewer can choose distinct entities or uncertainty; no automatic identity acceptance. |
| Manual draft, save, close/reopen, Resume saved draft | Draft remains unaccepted and editable. |
| Edit accepted entry; Previous; Cancel / discard / save draft | Correct navigation behavior; accepted record unchanged until re-attested. |
| Double click acceptance; save same unchanged revision again | No duplicate entity/mention/revision. |
| Delete entity with accepted dependents | Block with explanation; no orphan references. |
| Queue snapshot; load, correct, accept; return to entry | Latest SME edits appear, not the original AI wording. |
| Snapshot identical queue twice | No second pending copy; accepted/dismissed decisions survive. |
| Wrong note quote, repeated quote, blank occurrence, unresolved draft entity key | Cannot accept without evidence/entity correction; attention message. |
| Formula in queue/form, formula-like literal note | Formula rejected; literal note remains literal. |
| Long notes at 32,766 / 32,767 / 32,768 / 100,000+ units | Complete reconstruction, first/last text match, no cell truncation. |
| Emoji at split point, CRLF, combining accents, quote crossing part boundary | Exact source and code-point offsets preserved. |
| Sixth distinct note paste, old pending queue | Oldest analysis removed only; source/pending/accepted records intact. |
| Re-paste same note unchanged / changed | Same source reused / explicit new version; old evidence not shifted. |
| All AI proposals done but manual draft remains | Completion blocked until saved draft resolved. |
| Zero entities / reviewed uncertainty | Explicit note completion possible without fabricating an entity. |
| InjectNextSaveFailure, then try an entry save | No accepted rows or queue update; form retained. Toggle injection OFF and save once. |
| Read-only file, unavailable save destination | No false success and no progression. |
| Client import missing header / malformed CSV | Existing imports remain unchanged. |
| Watchlist metadata conflicts / no numeric score | All available metadata visible; insufficient_evidence possible. |
| Edit source annotation after watchlist decision | Note reopens and watchlist result marked recheck. |
| Actual tenant Copilot table write + AutoSave | Staging inserts expected columns; no concurrent acceptance corruption. |

Also inspect more than 205 accepted rows, many entities and lengthy explanations. Confirm no panel overflow, clipped controls or counts that imply completeness. Measure load/save time at the expected packet size; workbook-wide snapshots prioritise correctness but may need optimisation for very large workbooks.

If a test fails, record exact steps and error text. Do not mark native qualification passed until every applicable case has been run. Recovery copies and QA files contain note data; handle them like the source workbook.
