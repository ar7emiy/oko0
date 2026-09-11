# Client workbook and claim-scoped note citations

User need: import the client's Excel columns and comma-separated numeric note
citations, while one source note ID can appear in several claim packets.

Permitted interpretation: map declared header aliases to the existing firm
schema; split citation lists and strip only an all-zero decimal suffix from
digit-only IDs. Preserve original cell values. Do not infer entities or expand
the set of notes from firm predictions.

Evidence/dependencies: original workbook bytes determine the source fingerprint;
filenames determine (claim, note) membership. Each claim retains independent
annotations, decisions and frozen evidence. Missing citations stay explicit and
must never resolve through another claim. Blank optional columns remain unknown.

Unresolved outcome: malformed workbooks and ambiguous headers produce explicit
import warnings. Missing cited files are labeled unavailable in comparison.

Dossier effect: none; matching citations navigate to existing notes within the
current claim. Shared note IDs do not combine entities or annotation histories.

Disable/reverse: continue using the existing canonical CSV format. No source note
or client workbook is rewritten, and no existing annotation schema is migrated.
