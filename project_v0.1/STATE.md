# STATE

Where the rebuild is. Update this at the end of a working session; it is the
first thing anyone should read to pick up where we left off.

**Last updated:** 2026-09-06

---

## Where we are

**Scaffolding complete. No pipeline runs yet.** The identity layer — the whole
point of the rebuild — is not written.

### Done

- `config/config.py` — every value annotated with what it was measured at
- `src/contracts.py` — the new schema, each table annotated with why
- `src/settings.py` — config loading, path resolution, explicit online/offline
- Carried over from v0 **unchanged**, because each is measured-good:
  `runlog`, `genai`, `textnorm`, `chunking`, `ner_ensemble`
- Carried over and then **corrected**, because each still consumed the deleted
  `entity_class` or a hardcoded open-class lexicon: `coref`, `sweep`,
  `gazetteers`, `relations`
- `AGENTS.md`, `ARCHITECTURE.md`, `README.md`, this file

- **`src/entity_type.py`** — done. Typing measures **88.7%** against the
  generator's independent labels (person recall 88.1%, org recall 92.4%), with
  the head-noun lexicon *learned* rather than listed. `tests/test_entity_type.py`
  covers it, 7/7.
- **Hardcoded-lexicon sweep** — done, prompted by the `ART:` review comments.
  `coref` now filters antecedents on `entity_type` instead of nine role words on
  the deleted `entity_class`; its descriptor detector is extended by the learned
  lexicon; `sweep` promotes on structure rather than on a role cue; `relations`
  no longer discards `FILED`/`CONTACTED`/`SENT`/`PERFORMED` as degenerate;
  `gazetteers.ORG_SUFFIXES` deleted. The principle is `AGENTS.md` rule 11.

### Next, in order

1. **`src/repository.py`** — thin store over `contracts.DDL`. Must refuse to
   modify an `identity_link` row whose status is `accepted` or `rejected`.
2. **`src/extract.py`** + `notebooks/01_extract.py` — spans → mentions.
   Mostly wiring the carried modules; the locate-the-quote rule is already in
   `ner_ensemble._locate`.
3. **`src/resolve_local.py`** — within-claim clustering. Exact name, unambiguous
   token subset, shared identifier. **No fuzzy matching.**
4. **`src/link_cross.py`** — auto-link on strong identifiers; everything else to
   review.
5. **`notebooks/03_measure.py`** — over-merge rate against ground truth, head to
   head with v0 on the same slice.
6. **`src/dossier.py`** — traversal-based views.

Nothing after step 5 should be trusted until step 5 has run.

---

## The number to beat

**v0: 46% of labeled mentions sit in an entity that fuses two or more real
entities** (60-doc slice, measured against the corpus manifest).

Also worth beating, though these were never the problem:

| | v0 |
|---|---|
| identifier recall | 1.000 |
| mention span grounding | 100% |
| mention precision | 0.868 |
| identifier binding precision | 0.940 (LLM lane 0.969) |
| entity recall | 0.971 |

**Do not use B-cubed F1 as the headline.** It read 0.907 while 46% of mentions
were in fused entities, and it *preferred* the broken system three separate
times. Report composition.

---

## Open questions

| question | status |
|---|---|
| Is the review queue volume something a human will actually process? | **open** — 19% of cross-claim entities land there. Untested. This is the live risk in the design |
| Does 81% identifier-based auto-link hold on real client data? | **open** — this corpus is identifier-rich by construction. Re-measure before promising the number |
| Coreference is ~43% accurate | **partly addressed.** Role-list filtering replaced by `entity_type` agreement, which removes a class of silent misses (mechanics, witnesses, nurses were refused as antecedents outright). Not re-measured — the 43% figure stands until `03_measure.py` runs. Must be treated as low-confidence wherever consumed. In `DOC00047` "He" resolves to Fatima Johnson and "She" to Priya Brown, both wrong |
| Is `relations.py` output good enough to wire in? | looked strong on manual read, never measured. Unwired in v0 |
| How does a reviewer correct without breaking flow? | designed, not built — the click *is* the correction, since every displayed atom carries its own id |

---

## Ground truth and validation

The corpus is shared with v0 (`config.CORPUS_DIR` → `../project/data`) so the
two systems can be measured head to head on the same slice.

`../project/validation/` holds the manual-validation kit: a golden-set template
with `DOC00000` fully worked, and per-document system dumps. The over-merge
defect was found there, by reading one note — not by any automated gate.
