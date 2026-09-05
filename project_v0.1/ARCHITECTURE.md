# Architecture

Full first-principles derivation, including the measurements that killed each
rejected option: `../project/designs/rebuild-from-first-principles.md`. This
file is the working summary.

## The shape

```
 notes ──► spans ──► mentions ──► LOCAL entities ──► identity LINKS ──► dossier
           (1)        (2,3)          (4)                  (6)             (7)
                         └────► assertions (5) ──────────────┘
```

| # | stage | job | determinism |
|---|---|---|---|
| 1 | ingest | text + `doc_id → claim_id` + content hash | deterministic |
| 2 | span detection | gazetteer ∪ token-NER ∪ LLM reader | model-assisted, span **located** |
| 3 | normalize & type | one normalizer per kind; `entity_type` from the string | deterministic |
| 4 | local resolution | cluster mentions **within one claim** | deterministic rules |
| 5 | fact extraction | LLM quotes evidence; code grounds and binds | model reads, code records |
| 6 | cross-claim linking | auto on validated identifier; else review queue | deterministic accept rule |
| 7 | dossier / query | views over evidence rows | deterministic |

## The one decision everything follows from

**Entities are claim-scoped. Cross-claim identity is a link, not a merge.**

```
        CLAIM A                        CLAIM B
   ┌──────────────────┐          ┌──────────────────┐
   │ local entity 1   │◄────────►│ local entity 4   │
   │  "Marcus Lopez"  │   link   │  "M. Lopez"      │
   └──────────────────┘  basis:  └──────────────────┘
                    shared validated email
```

Within a claim there are few parties and names are unambiguous. Across claims,
two records connect only on evidence, recorded as a row with a basis and a
confidence.

**Why it is the whole design:** a wrong cross-claim link is one visible,
reversible edge. Local dossiers stay correct even when linking is wrong. Under
v0's global transitive clustering the same wrong edge corrupted an entire
connected component — four different Andersons in one entity, 46% of mentions in
mixed entities.

It is also what makes the reviewer's *"that's wrong"* cheap: flip one row. In a
merge-based model there is no repair short of rebuilding the cluster.

## How identity is decided

**Within a claim** — merge on exact normalized name, unambiguous token subset,
or shared validated identifier. **Not on fuzzy name similarity.**

> Measured: of 395 claims, 5 contain two distinct real entities whose names
> collide — and all 5 collide *only* on fuzzy similarity (0.886–0.911), none on
> exact match or token subset. Excluding fuzzy takes within-claim collisions to
> **zero** corpus-wide.

**Across claims** — auto-link only on a shared identifier carrying its own
validation (`npi`, `vin`, `email`, `ssn`, `tin`). Everything else is ranked and
queued for review.

> Measured: 81% of cross-claim entities carry such an identifier written in ≥2
> of their claims. The remaining **19% (44 entities) go to review** — a real
> workload, not zero.

The probability model **ranks the review queue. It does not decide identity.**
That is a deliberate demotion: measured, its ranking was sound while its
absolute numbers were 16× off.

## Type comes from the string

`entity_type ∈ {person, organization, unknown}`, computed from the name text
alone.

v0 derived a five-value `entity_class` from surrounding *context* and it
disagreed with itself on **69% of real entities** and **30% of identical
strings**. Context encodes **role**, which genuinely varies sentence to
sentence — so it can never answer a question that must stay constant.

**Role is an assertion**, claim-scoped and evidence-backed: *"acts as attorney
on CLM0010, per this span."* Free to differ across claims, which is what the
data actually does.

## Data model

See `src/contracts.py` — every table is annotated with why it exists. The core:

```
span            verbatim; text == document[start:end], always
name_mention    surface, norm, entity_type, found_by
id_mention      kind, value_raw, value_norm, validation
local_entity    claim-scoped
local_member    + basis: why this mention is in this entity
identity_link   + basis, status, decided_by  -- NOT a merge
assertion       + evidence_span_id NOT NULL  -- no span, no assertion
```

Dossiers are **views**, never stored. Corrections are new rows, never mutations.

## External data (NPPES, PECOS, LEIE, CourtListener)

Two distinct jobs, easily conflated:

- **Resolution** — barely helps. 59% of a claim corpus is claimants, whom no
  registry covers, and the linking gap is 31 claimants + 9 adjusters. Measured,
  registries would bridge **1 of 44** unlinked entities.
- **Enrichment and risk signal** — high value, and the actual product case. An
  attorney in 400 prior injury dockets, a provider on LEIE, a firm and clinic
  co-occurring across unrelated claimants. *That pattern is what a predictive
  SIU investigator is hunting.*

**Rule:** join on identifier, never on name. Matching corpus names against 8M
registry records reintroduces the Anderson failure at far greater scale.
Registry facts carry `source` and an as-of date; they are not corpus facts.

## Query-time matching

A query record (*"Physician, John Belvita, Address Unknown, CA, TIN=123456789"*)
is structurally a mention record, so it scores against local entities with the
same model. Validated identifiers short-circuit to a deterministic hit; missing
fields contribute nothing rather than a penalty; and output is a **band plus an
evidence breakdown**, never a bare percentage — a number with no breakdown is
exactly what hid the 46% over-merge.

## Deployment

Deliberately boring, so the target stays open (GCP / Azure / AWS / Vercel +
Supabase). Plain Python; storage behind a thin repository interface so
SQLite→Postgres is a swap; the LLM already behind an interface. No cloud
abstractions built now — just no coupling. Docker at the end.

The eventual viewer: pick a note, read it with system recognition highlighted
inline, open the dossiers inside it, and ask natural-language questions answered
by **graph RAG** over the assertion + link graph — structured retrieval, LLM
synthesis over retrieved evidence rows, never LLM-generated facts.
