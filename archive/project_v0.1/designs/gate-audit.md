# Gate Audit: every place this system says no

An inventory of every **limiting gate** in the pipeline — anything that drops,
blocks, truncates, vetoes or filters — traced from the first action the program
takes, stress-tested against what real claim files actually contain rather than
what our synthetic corpus contains.

**Method.** Gates were found by reading the code path, not from memory. Claims
below are tagged `[measured]` (I ran it, output included), `[reasoned]` (follows
from the code but not executed), or `[assumed]` (judgement about real-world data
I have not seen). Numbers from the synthetic corpus are deliberately *not* used
as evidence of real-world behaviour — that is the whole point of the exercise.

**Scope note.** Stages 0–5 exist in code today. Stages 6–7 (identity) are
designed but unwritten; their gates are audited from `config/config.py` and
`ARCHITECTURE.md`, and are the cheapest to change *because* they are unwritten.

---

## The thesis

Two structural findings outrank every individual gate.

### 1. We have provenance for what we keep and no accountability for what we drop

Every assertion in this system carries a span. That is the invariant the whole
design is built on, and it holds. But it only covers **survivors**. I count
**~20 points** where a candidate is discarded, and almost none of them records
that it happened, why, or what the text was.

`relations.py` is the sole exception — it keeps a `rejected` counter by reason.
Everywhere else, a dropped mention leaves no trace.

The consequence is precise and serious for the stated goal. An investigator
opening a dossier sees an entity's activity across the corpus, every line
traceable. What they cannot see is that the entity's third claim was dropped at
the span-location gate because the PDF used a ligature. **The dossier is
confidently incomplete, and nothing in the system knows it.** For a predictive
SIU product this is the worst failure mode available: the tool is most wrong
exactly when it looks most authoritative.

`contracts.py` already defines a `scan_ledger` table. It is the right home for
this and is currently unused.

### 2. Several gates are justified by precision measurements while paying unmeasured recall costs

The archetype is `LOCAL_MERGE_BASES`. The justification in config reads:

> of 395 claims, 5 contain two distinct real entities whose names collide — and
> all 5 collide *only* on fuzzy similarity. Excluding fuzzy takes within-claim
> collisions to **zero**.

That is a real measurement and it is a **precision** result. It says fuzzy
matching causes false merges. It says nothing whatever about how many *true*
merges exact-matching will miss on names that are misspelled, OCR-mangled,
transliterated, married, abbreviated or nicknamed — because the synthetic corpus
contains almost none of those. On real intake data the recall cost is the
dominant term and it is entirely unmeasured.

This is v0's recurring defect shape wearing new clothes: **a component distrusts
a signal, and another consumes the restriction absolutely.**

---

## Gate inventory

Severity: **H** = can silently lose or corrupt an entity on real data;
**M** = degrades quality recoverably; **L** = bounded or cosmetic.

| # | stage | gate | fails on real data because | sev |
|---|---|---|---|---|
| G0.1 | ingest | `doc_id → claim_id` is 1:1 | a note references several claims; a claim spans many documents | **H** |
| G0.2 | ingest | input assumed clean UTF-8 text | real files are PDF/fax/scan/email threads; no OCR layer exists | **H** |
| G1.1 | chunk | 230 words/chunk | subject and object >230 words apart can never co-occur | **M** |
| G1.2 | chunk | `TOKENS_PER_WORD = 1.3` | codes and clinical terms tokenize far worse; underestimates | L |
| G2.1 | NER | `GLINER_THRESHOLD = 0.35`, single global value | tuned on clean prose; ALL-CAPS and abbreviations depress scores | **M** |
| G2.2 | NER | `NER_LABELS`, 13 closed labels | vehicle, employer, TPA, IME, witness, interpreter are invisible | **M** |
| G2.3 | NER | `_locate` drops an unfindable surface | unicode punctuation, ligatures, soft hyphens from PDF extraction | **H** |
| G2.4 | gaz | regex identifier patterns | redaction, spacing, spelled-out street types | **H** |
| G2.5 | gaz | NPI = any 10 digits + Luhn | 9.6% of arbitrary 10-digit strings pass | **H** |
| G2.6 | gaz | contained hit dropped by priority | the zip inside an address stops being queryable | **M** |
| G3.1 | sweep | `_CANDIDATE_RE` needs ≥3 letters/word | Ng, Li, Wu, Vo, Ho are structurally invisible | **H** |
| G3.2 | sweep | `MAX_CANDIDATES_PER_CHUNK = 40` + `break` | dense pages audited only to 33%, tail systematically unseen | **M** |
| G3.3 | sweep | `_NOISE` stoplist | English-only, corpus-specific | L |
| G4.1 | coref | `MAX_ANTECEDENT_CHARS = 600` | ~100 words of reach; names sit at the top of a long note | **M** |
| G4.2 | coref | closed pronoun/descriptor lists | no "the former", "same", "said individual" | **M** |
| G5.1 | rel | evidence must relocate verbatim | same unicode failure as G2.3 | **M** |
| G5.2 | rel | subject and object must be in one chunk | inherits G1.1 | **M** |
| G5.3 | rel | `BANNED` / `DEGENERATE` predicates | now correct; keep it a schema decision, not a vocabulary | L |
| G6.1 | identity | `LOCAL_MERGE_BASES` excludes fuzzy | precision-justified; recall cost unmeasured on dirty names | **H** |
| G7.1 | identity | `STRONG_IDENTIFIERS` auto-link, no review | shared org email fuses every provider at a clinic | **H** |
| G7.2 | identity | `WEAK_IDENTIFIERS_AUTOLINK = ()` | conservative and correct | L |
| G8.1 | type | learned lexicon needs corpus volume | thin lexicon on small corpora → more `unknown` (correct behaviour) | L |

---

## Stage-by-stage stress test

### Stage 0 — Ingest

**G0.1 — the claim-scoping assumption.** Claim-scoped entities are *the* load-bearing
decision of this architecture, and everything good about it follows from that
scoping being right. The system takes `doc_id → claim_id` as given.

Real intake breaks the 1:1 assumption constantly `[assumed]`:

- an adjuster's diary entry that references two related claims by number
- a subrogation demand covering a batch of claims against one tortfeasor
- an **occurrence group** — a multi-vehicle loss where one person is claimant on
  claim A and witness on claim B, which you have already raised as a real case
- a medical record spanning two dates of loss
- a law firm's letter of representation naming several clients

If a document carries two claims and we scope it to one, we do not merely
mis-file. We **create a false within-claim merge opportunity** between parties
who were never in the same claim — and within-claim merging is our *least*
guarded path, because it was measured safe under the assumption that a claim
holds few, unambiguous parties.

> **Recommendation.** Make `claim_id` a property of a **span**, not a document.
> A document then contributes mentions to however many claims it references,
> extracted with evidence like anything else. This is a data-model change and it
> is far cheaper now than after `repository.py` exists.

**G0.2 — no document layer.** Everything assumes clean text. Real claim files are
scanned faxes, PDFs with two-column layouts, email chains with quoted history and
disclaimer footers, and photographs of handwritten forms. Quoted email history
in particular will cause the same mention to be extracted repeatedly across
documents with different dates, which the identity layer will read as
corroboration. `[reasoned]`

This is the largest gap between this system and a deployable one, and it is
currently invisible because the corpus is synthetic.

### Stage 1 — Chunking

**G1.1 — the chunk is the relation horizon.** `[measured]`

```
CHUNK_TOKENS=300, TOKENS_PER_WORD=1.3  ->  230 words/chunk, stride 115
subject and object more than 230 words apart never co-occur in any chunk
COREF reach 600 chars ~ 100 words
```

Overlap protects *entity* recall at boundaries, which is what the docstring
claims and it is true. It does nothing for **relations**, which need both
endpoints in one window. A claim note that names the attorney in the header and
describes the filing three paragraphs later cannot produce
`attorney FILED suit` at any chunk size we currently use. `[reasoned]`

This is not a tuning problem — raising `CHUNK_TOKENS` trades one failure for
another. It is an argument for document-level extraction (see 2026 options).

### Stage 2 — Span detection

**G2.3 — the locate-and-drop gate.** This is the gate I have been proudest of:
it took span grounding from 33% to 100%. It is also, on real data, one of the
most dangerous, because **rejection is total and silent.**

`[measured]` against characters that PDF and OCR extraction routinely produce:

```
curly apostrophe    Dr. O’Brien      -> DROPPED   mention lost
soft hyphen         Ander-son        -> DROPPED   mention lost
fi ligature         Pacific          -> DROPPED   mention lost
non-breaking space  Marcus Lopez     -> found
double space        Jane  Reyes      -> found
case difference     CLMT JOHNSON     -> found
```

The model quotes the name as a human reads it; the document stores a different
codepoint. Three of six realistic variants lose the mention entirely, and the
system records nothing. On a scanned corpus this is not an edge case, it is the
common case.

The gate itself is right — **never trust a model's offsets** stays. What is wrong
is the comparison being byte-equality on raw text.

> **Fix.** Locate against a *folded* view of both strings (NFKC, confusable
> punctuation mapped to ASCII, soft hyphens and zero-width characters stripped,
> ligatures expanded), keeping an index map back to raw offsets so the stored
> span is still exact. Cheap, deterministic, no model involved. Then log every
> remaining failure to `scan_ledger` with the surface, so drops are countable.

**G2.4 / G2.5 — identifier patterns.** `[measured]`

```
'SSN 123-45-6789'    -> ssn found
'SSN xxx-xx-6789'    -> NOTHING        (redaction: ubiquitous in real files)
'SSN 123456789'      -> NOTHING        (unformatted)
'NPI 1234 567 893'   -> NOTHING        (spaced)
'DOB **/**/1980'     -> NOTHING

'123 Main St'                    -> matched
'123 Main Street'                -> NO MATCH   (spelled-out type)
'4500 N Central Avenue'          -> NO MATCH
'PO Box 4417'                    -> NO MATCH
'77 Sunset Blvd Suite 210'       -> '77 Sunset Blvd'          (truncated)
'1600 Pennsylvania Ave NW, ...'  -> '1600 Pennsylvania Ave'   (truncated)
```

Redaction handling is the significant one. Partially-masked identifiers are
*normal* in claim files and carry real signal — `xxx-xx-6789` is a usable
blocking key. Today they produce nothing at all.

**G2.5 is the highest-severity single finding.** `[measured]`

```
9.6% of random 10-digit strings pass the NPI Luhn check (1929/20000)
```

The NPI pattern is `\b\d{10}\b` — *any* ten digits. Luhn removes ~90%, so roughly
**one in ten** arbitrary 10-digit tokens in a document becomes a
`validation='checksum'` NPI. Claim files are full of 10-digit numbers: unformatted
phone numbers, member IDs, account numbers, internal reference codes.

`checksum` is our strongest validation tier. `npi` is in `STRONG_IDENTIFIERS`.
Per the design, a shared strong identifier **auto-links across claims with no
human review**. So a chance Luhn pass on two unrelated account numbers creates an
unreviewed cross-claim identity link.

This is the 46% over-merge failure re-entering through the one door we declared
safe — and worse than v0's version, because v0's bad merges came from name
similarity, which a reviewer can eyeball. "Same verified NPI" looks like proof.

> **Fix.** Require a **context cue** for `npi` (`NPI`, `prov #`, `provider id`
> within a short left window) exactly as `icd10`/`cpt` already do, and demote a
> cue-less Luhn pass to `format`. Then never let a single identifier
> auto-link — see G7.1.

**G2.6 — containment drop.** A zip inside a matched address is discarded. The
address remains, but the zip is no longer independently queryable, and zip is one
of the most useful weak blocking keys in insurance work. `[reasoned]` Prefer
**nesting** over dropping: keep both, mark one as contained.

### Stage 3 — Sweep

**G3.1 — short names are structurally invisible.** `[measured]`

```
_CANDIDATE_RE = [A-Z][a-zA-Z'’\-]{2,}      -> minimum 3 characters per word

Ng  False     Li  False     Wu  False     Vo  False
Ho  False     Ek  False     Oh  False     Chen True     Nguyen True
```

Two independent gates enforce this — the regex `{2,}`, and `SWEEP_MIN_TOKEN_LEN
= 3` behind it. Ng, Li, Wu, Vo, Ho, Oh are common real surnames. The sweep lane
exists specifically to catch what the other extractors missed, and it cannot see
them at all.

This is a correctness bug and a fairness problem in the same line of code: the
recall floor is systematically lower for Vietnamese, Chinese and Korean names.
On a real book of business that is a defensible-practices issue, not only a
quality one. `[reasoned]`

> **Fix.** Allow 2-character capitalized tokens when adjacent evidence supports
> a name (a title, another capitalized token, or an identifier on the same line).
> The length rule exists to suppress noise; make the noise test contextual
> instead of a blanket minimum.

**G3.2 — the audit stops at 40.** `[measured]`

```
120 candidates present -> 40 examined (33%); break in document order
first 'AlphaA'  last 'JulietN'
```

The cap is a cost control, but `break` makes it **positional**: the end of every
dense chunk is unaudited. Dense chunks are exactly where misses concentrate —
provider tables, billing line items, service lists. `[reasoned]`

> **Fix.** If a budget is needed, **rank** candidates and take the best 40, or
> sample across the chunk. Never truncate in reading order. And record the
> overflow count in `scan_ledger` so the loss is visible.

### Stage 4 — Coreference

Reach is ~100 words `[measured]`. Known 43% accurate. Now filters on
`entity_type` with `unknown` always eligible, so it no longer vetoes.

The honest position: this component is weak, we know it is weak, and it is
correctly treated as low-confidence. The gate that matters is not inside coref —
it is whether anything downstream ever treats a coref link as fact. Today nothing
does, because relations are unwired. **That must stay true when they are wired.**

### Stages 6–7 — Identity (designed, unwritten)

**G6.1 — no fuzzy matching within a claim.** Discussed in the thesis. The
measurement is sound and the conclusion over-reaches.

Real-world within-claim variation the current bases will miss `[assumed]`:
`Jon`/`John`, `Nguyen`/`Nguyên`, `Rodriguez`/`Rodrigues`, married vs maiden name,
`Wm.`/`William`, OCR `rn`→`m`, a transposed VIN digit, `Robert`/`Bob`.

Each becomes two local entities, each with a partial dossier — the fragmentation
failure rather than the fusion failure. Fragmentation is *safer* (a wrong link is
one reversible edge; a missing link is a missing edge), which is why the design
chose it. But it is not free, and "zero collisions" is not evidence about it.

> **Recommendation.** Keep the deterministic **decision**. Add a fuzzy/embedding
> **candidate** lane that never merges — it produces ranked review items. That is
> the recall/decision split, and it is exactly the 2026 consensus below.

**G7.1 — auto-link on one strong identifier.** `[reasoned]`

Consider a real clinic where every provider record carries `info@ashfordclinic.com`.
Under the current rule, `email ∈ STRONG_IDENTIFIERS`, shared across claims, no
review — **every provider at that clinic fuses into one entity.** Same for a law
firm's main line, a shared family email, a billing service's TIN across dozens of
unrelated providers, or a fleet VIN.

Identifier *validity* was conflated with identifier *discriminativeness*. An
email is well-formed; that says nothing about whether it identifies one person.

> **Fix.** Gate auto-link on **observed cardinality**, computed from our own
> corpus: if an identifier value is associated with more than one distinct
> name-cluster, it is not identifying — route to review regardless of kind. This
> is a few lines, it is deterministic, it needs no external data, and it converts
> a static trust list into a measured property.

---

## Findings, ranked

| rank | finding | evidence |
|---|---|---|
| 1 | Chance Luhn passes create unreviewed cross-claim auto-links | `[measured]` 9.6% |
| 2 | A shared organizational identifier fuses every party using it | `[reasoned]` |
| 3 | No accountability for drops anywhere except relations | `[measured]` code read |
| 4 | `_locate` silently loses mentions on ordinary PDF characters | `[measured]` 3 of 6 |
| 5 | Short surnames structurally invisible to the recall lane | `[measured]` |
| 6 | `claim_id` as a document property breaks on multi-claim files | `[reasoned]` |
| 7 | No-fuzzy rule justified by a precision result only | `[measured]` config |
| 8 | Sweep truncates in document order | `[measured]` 33% |
| 9 | Identifier regexes miss redacted and spelled-out forms | `[measured]` |
| 10 | Chunk width caps relation extraction | `[measured]` 230 words |

---

## Is the architecture flexible enough?

**Yes on the skeleton; no on the calibration; and one data-model change is worth
making now.**

**What holds up well.** Claim-scoped entities with links rather than merges is
the right primitive, and it is *more* right after this audit, not less: every
failure above degrades into a wrong or missing **edge**, which is visible and
reversible, rather than a corrupted connected component. Assertions carrying
mandatory evidence spans is the correct base for both dossiers and graph RAG.
Review as a first-class output — not an error path — is what makes the whole
thing survivable. None of this needs to change.

The 2026 literature independently converges on the same split: for entity
resolution, deterministic scoring is preferred to LLM generation because it is
faster, explainable and cannot hallucinate, while learned embeddings are used for
**blocking** — candidate generation — rather than for the decision
([BlockingPy](https://www.sciencedirect.com/science/article/pii/S2352711026000774),
[Universal Dense Blocking](https://arxiv.org/pdf/2404.14831)). Our design already
says "the probability model ranks the review queue, it does not decide identity."
That is the same sentence.

**What does not hold up.** The gates are calibrated to a clean synthetic corpus,
and the calibration is load-bearing in places we have not acknowledged. Roughly
20 silent drop points mean the system's central promise — traceability — is
enforced only for what survives.

**The one structural change I would make now:** move `claim_id` from the document
to the span (G0.1). Every other fix above is local and can be made later; this one
gets more expensive the moment `repository.py` and the identity layer are written
against the current shape.

**The principle to adopt:** *no gate in a recall path.* Recall lanes emit
candidates with a confidence and a reason and never discard. All discarding
happens in one auditable decision layer that writes a ledger row. This makes
every finding above a tuning question instead of a silent loss, and it is the same
insight that fixed `entity_type` — the accuracy of a component matters far less
than whether anything treats it as final.

---

## 2026 options worth considering

Assessed for *benefit against a gate we actually have*, not for novelty.

| option | which gate it addresses | verdict |
|---|---|---|
| **[GLiNER2](https://arxiv.org/pdf/2507.18546)** — schema-driven multi-task IE, matches GPT-4-class F1 zero-shot on CrossNER | G2.1, G2.2 | **Adopt.** Drop-in successor to our GLiNER; schema interface makes the closed label list cheap to extend, and per-schema rather than one global threshold |
| **[GLiDRE](https://arxiv.org/pdf/2508.00757)** — document-level relation extraction, few-shot SOTA | G1.1, G5.2 | **Evaluate.** Directly attacks the chunk-as-relation-horizon limit, which no chunk-size tuning can fix |
| **[GLiNER-Relex](https://arxiv.org/html/2605.10108v1)** — joint NER + RE, one encoder | G2.2, G5.2 | **Watch.** Attractive consolidation; joint models make it harder to attribute a failure to a stage, which this project's method depends on |
| **Dense/ANN blocking** ([BlockingPy](https://www.sciencedirect.com/science/article/pii/S2352711026000774), [model2vec](https://arxiv.org/pdf/2404.14831)) | G6.1 | **Adopt.** The clean way to recover the recall the no-fuzzy rule costs, without letting similarity decide anything. Static embeddings are deterministic and run locally |
| **LLM for entity typing**, cached per string | G8.1 | **Measure first.** Discussed separately; likely better than our 88.7%, and makes the Census surname list unnecessary |
| **[LLM entity matching at scale](https://arxiv.org/pdf/2603.11051)** (OpenSanctions Pairs) | G7.1 | **Reference, don't adopt.** Useful as a benchmark for how far LLM matching gets; our review-queue ranking is the right place for it, never the decision |
| Structured context in embeddings rather than bare names | G6.1 | **Adopt with the above.** Reported as the single largest accuracy gain — names alone lack the context that separates ambiguous cases, which is precisely our Anderson problem |

Deliberately **not** recommended: an end-to-end LLM entity-resolution agent. It
would fail rule 1 (a name never decides identity), destroy the reversibility that
makes wrong links cheap, and the 2026 work above argues against it on accuracy
grounds as well as governance ones.

---

## What I did not test

Stated so this document can be attacked properly:

- **No real claim file was used.** Every real-world claim is `[reasoned]` or
  `[assumed]`. The measurements are of *our code's behaviour* on inputs I
  constructed to resemble real data — which is not the same as real data.
- Identity gates G6/G7 are audited from config and design, not from running code,
  because that code does not exist.
- I did not measure the review-queue volume any of these fixes would produce.
  Recommending "route to review" repeatedly is only credible if a human can
  actually process the result, and that remains this design's open risk.
- GLiNER threshold behaviour on degraded text is `[reasoned]` from how the model
  works, not benchmarked.
- No cost or latency modelling for any 2026 option.

## Suggested order of work

1. **`claim_id` onto spans** — data-model, cheapest now, most expensive later
2. **NPI context cue + identifier cardinality gate** — the two auto-link
   contamination paths, both small and deterministic
3. **`scan_ledger` wired to every drop point** — turns findings 3–10 from
   invisible into measurable, and is a prerequisite for honestly evaluating the rest
4. **Unicode folding in `_locate`** — small, high real-world value
5. **Sweep: contextual short-name rule, ranked budget** — recall floor and fairness
6. **Embedding candidate lane for identity review** — recovers no-fuzzy recall
   without weakening the decision rule

Sources:
[BlockingPy](https://www.sciencedirect.com/science/article/pii/S2352711026000774) ·
[Universal Dense Blocking](https://arxiv.org/pdf/2404.14831) ·
[GLiNER2](https://arxiv.org/pdf/2507.18546) ·
[GLiDRE](https://arxiv.org/pdf/2508.00757) ·
[GLiNER-Relex](https://arxiv.org/html/2605.10108v1) ·
[OpenSanctions Pairs](https://arxiv.org/pdf/2603.11051) ·
[Pre-Trained Embeddings for ER (VLDB)](https://dl.acm.org/doi/abs/10.14778/3598581.3598594)
