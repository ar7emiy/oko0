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

## Vocabulary: what may be hardcoded, and what must be learned

Every hand-written word list in this system is a bet that the next corpus uses
the same words. The bet is safe for **closed** vocabulary and unsafe for
**open** vocabulary, and the two are easy to confuse because they look identical
in code — both are just a `set` of strings.

| | closed | open |
|---|---|---|
| membership fixed by | statute, standard, or our own schema | how people happen to talk |
| examples | `LLP`/`LLC`/`PC`, `Dr`/`Esq`/`MD`, NPI Luhn, the predicate vocabulary | business words, specialties, role names, descriptor phrases |
| a new client adds | nothing | acupuncture, gastroenterology, optometry, "resolution manager" |
| treatment | **hardcode it** | **learn it, or shrink its job** |

> Measured: a hardcoded business-word lexicon typed **13 of 14** realistic
> people (`Dr. Paul Frame`, `Marcus Law`) as organizations, and missed **6 of 6**
> specialties nobody had listed. Learning the same vocabulary from the corpus
> scored **88.7%** against ground truth where the list scored **22%**.

**How open vocabulary is learned.** `entity_type.learn_head_nouns` uses a
positional signal that carries no domain knowledge: an organisation head noun
can only ever *end* a name. There is no "Center Thomas". A surname has no such
restriction — "Anderson Automotive" and "William Anderson" are both fine. So a
token qualifies as a head noun when it ends ≥3 different names and leads none.

> Recorded error: the first version used recurrence instead of position — "a
> head noun trails many different names; a surname does not." False. `Anderson`
> trails William, Samuel and Andrew for exactly the reason `Center` trails
> Thomas, Lopez and Vance. It learned 52 tokens, mostly surnames, and scored
> 22%. The strict never-leads form scores 88.7%; "leads at most once" scores
> 60.9%.

**When it cannot be learned, shrink the job.** `gazetteers.ROLE_CUES` cannot
enumerate every specialty and never will. It is not being grown; it was demoted
from naming a class to supplying a recall *hint* inside an audit whose output is
filtered downstream. An incomplete hint costs one candidate a nudge. The same
incomplete list assigning a label, or gating a promotion, turns a vocabulary gap
into a silent correctness bug — which is exactly what it was doing.

**Where this bit us, and what it cost:**

| site | the hardcoded list | now |
|---|---|---|
| `entity_type` | business words | learned from trailing position |
| `coref` antecedents | 9 role names, on the deleted `entity_class` | `entity_type`; mechanics, witnesses and nurses are all `person` |
| `coref` descriptors | 18 fixed phrases | seed + `the <learned head noun>` |
| `sweep` promotion | role cue decided promotion | structure decides; cue is a tiebreak only |
| `relations` | 8 real verbs dropped as "degenerate" | copulas only; `FILED`/`CONTACTED`/`SENT` restored |
| `gazetteers.ORG_SUFFIXES` | org words, zero consumers | deleted |

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
