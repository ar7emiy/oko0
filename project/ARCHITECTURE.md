# Layer 1–4 Architecture: Hybrid High-Recall Entity Intelligence

Implementation and **measured evaluation** of the four-layer blueprint over the
synthetic claim corpus (2,224 notes / 300 claims / 180 ground-truth entities).

Everything here is measured against the sealed ground-truth manifest, so the
architecture's central claim — that a union ensemble plus a verification sweep
drives missed entities toward zero — is tested rather than asserted.

```
[ Raw notes: 2,224 docs / 300 claims ]
        │
        ▼
LAYER 1  HYBRID HIGH-RECALL EXTRACTION          src/chunking, gazetteers, coref,
  chunking (300 tok, 50% overlap)                   ner_ensemble, sweep, pipeline_v2
  coreference (pronouns -> canonical)
  UNION: token-NER ∪ gazetteer ∪ LLM
  pass-2 differential sweep
        │  spans + provenance
        ▼
LAYER 2  ENTITY RESOLUTION                       src/resolution
  blocking passes (A1,B0..B4,C1,D1)
  weighted scoring + adjudicator
  greedy correlation clustering
        │  canonical entity ids
        ▼
LAYER 3  DUAL STORAGE                            src/vectorstore, graph_store,
  chunk vector index (claim_id in metadata)          build_graph
  claim-scoped graph (claim_id on every node/edge)
        │
        ▼
LAYER 4  PER-CLAIM AGENT                         src/agent
  1 hard claim filter  2 vector entry
  3 graph expansion    4 grounded synthesis
```

Notebooks: `10_layer1_hybrid_extraction`, `11_recall_ablation`,
`12_layer3_scoped_graph`, `13_layer4_agent`.

---

## The headline result: the union strategy is worth it

Cumulative recall ablation over the **full corpus**, scored against every planted
mention in the manifest (`notebooks/11_recall_ablation.ipynb`):

| stage | name recall | lift | name precision | identifier recall | missed |
|---|---|---|---|---|---|
| `llm_only` | 0.7817 | — | 0.677 | 0.089 | 1567 |
| `+ token_ner` | **0.9943** | **+0.213** | 0.591 | 0.135 | 41 |
| `+ gazetteer` | 0.9943 | +0.000 | 0.654 | **1.0000** | 41 |
| `+ sweep` | **0.9964** | +0.002 | 0.627 | 1.0000 | **26** |

Read this carefully, because each layer earns its place on a *different* metric:

- **Token-level NER is the single biggest win: +21.3 recall points.** It rescued
  1,526 mentions that the semantic pass never emitted at all. This is the
  attention-drift failure mode, quantified.
- **Gazetteers contribute nothing to *name* recall and everything to
  *identifier* recall: 13.5% → 100%.** Scoring them on name placements alone
  would have wrongly concluded they were useless. Structured codes (NPI with
  Luhn check, TIN, SSN, email, phone, address, DOB) are recovered exactly, by
  regex and checksum, never by a model.
- **The sweep is a small but real net: +0.2 points, 15 more mentions,** and it
  is what turns "we think we got everything" into "here is the residual list".
- **Precision moves in the opposite direction** (0.677 → 0.627). Recall-first
  extraction has a precision cost; it is paid back downstream by filtering and
  entity resolution, not inside the extractor.

End-to-end through the real pipeline (Layer 1 feeding Layers 2–4), mention recall
is **99.4%** with **no systematic miss pattern remaining** — every segment kind
(template, narrative, email header/body/signature/quoted) scores ≥ 99%. The
previous single-pass pipeline scored 88.9% with several structural blind spots.

### Honest caveat on the baseline

There is no Gemini key and no HuggingFace access in this environment, so:

- `llm_only` is a **deliberately salience-biased deterministic stub** that keeps
  early and role-cued mentions and drops the long tail — it simulates the
  documented LLM failure mode rather than measuring a real Gemini pass. The
  *shape* of the finding (a token-level scanner rescues what a salience-driven
  extractor drops) is architectural, but **the 0.78 baseline number is a property
  of that stub, not of Gemini.** With `GEMINI_API_KEY` set, the identical
  ablation runs against the real model and prints the real number.
- `token_ner` runs as `DeterministicTokenNER`. `GlinerBackend` is implemented and
  activates automatically when `gliner` is installed with reachable weights.
- Coreference runs rule-based; `FastCorefResolver` activates when `fastcoref` is
  installed.

Both backends sit behind one-method interfaces (`TokenNERBackend`,
`CorefResolver`), so swapping in the real models changes no other code.

---

## Layer 1 details

**Chunking** (`src/chunking.py`) — 300 tokens, 50% overlap, absolute char offsets
preserved so every downstream span maps back to true raw-document coordinates.

> **Measured caveat:** these legacy notes average 412 characters, so only
> **70 of 2,224 docs (3%) need more than one chunk** and mean re-read depth is
> 2.1%. Chunk-boundary truncation is a real production failure mode but it is
> **near-absent on this corpus** — the overlap machinery is correct and general,
> but it is not what earns the recall here. Saying otherwise would overclaim.

**Coreference** (`src/coref.py`) — pronouns and vague descriptors ("the
physician", "the shop") are resolved to typed antecedents and are **never emitted
as nodes**. Resolution is **non-destructive**: we emit `CorefLink` records plus an
optional `resolved_view()` with an offset map, rather than rewriting the corpus —
this preserves both corpus immutability and span grounding. 260 links resolved.

**Gazetteers** (`src/gazetteers.py`) — deterministic patterns with checksum
validation and **label-priority conflict resolution** (a valid NPI also matches
the bare-10-digit phone shape; priority + containment rules settle it).

**Union** (`src/ner_ensemble.py`) — overlapping spans collapse to the longest and
**union their provenance**, so every span records which extractors saw it. That
provenance is what makes the ablation table above possible.

**Sweep** (`src/sweep.py`) — finds tokens covered by *no* span, adjudicates them
(Gemini differential audit online / deterministic rule offline), and promotes
genuine misses. `residual_report()` lists whatever still isn't covered.

---

## Layer 3: scope is a structural property, not a filter

Every node and edge carries `claim_id`, and the graph keeps **adjacency
partitioned by claim**: `neighbors()` only ever reads `self._adj[claim_id]`, so
another claim's edges are *unreachable*, not merely filtered out.

**Predicate whitelist** — 13 domain verbs (`TREATED_BY`, `REPRESENTED_BY`,
`ISSUED_PAYMENT`, …). `MENTIONED_IN`, `HAS_NOTE`, `RELATED_TO`,
`ASSOCIATED_WITH` raise `PredicateRejected` at insert time. Result: **25.4 edges
per claim** — a navigable graph, not a hairy ball.

### The cross-claim tension (a real finding)

Shared-identifier links are exactly the fraud signals that matter (a phoenix shop
reusing an address under a new TIN; one attorney across many files) — and they
are **inherently cross-claim**, which the security model forbids traversing.

Silently dropping them loses the signal; putting them in a claim scope breaks the
boundary. Resolution: they are stored under a reserved `__CROSS_CLAIM__` scope,
**unreachable via `neighbors()`** (raises `ScopeViolation`) and exposed only via
`cross_claim_links(authorized=True)`, a separately-gated API. 818 such links.

Graph totals: 4,167 nodes · 7,663 edges · 302 scopes · 920 allegation edges
(allegations stay segregated from facts).

---

## Layer 4: retrieval with a proven boundary

`ClaimScopedAgent.answer()` runs hard filter → scoped vector top-k → 1–2 hop
expansion → grounded synthesis with `doc_id:span` citations. The offline
synthesizer is fully deterministic and emits only retrieved content.

`test_scope_isolation()` is an executable proof, run in notebook 13:

```
leaked_chunks 0 · leaked_triples 0 · leaked_entities 0
cross_claim_traversal_blocked True · unauthorized_cross_claim_blocked True
isolation_holds True
```

---

## Where this architecture currently fails: Layer 2

**High-recall extraction moved the bottleneck to entity resolution.** This is the
most important negative result here, and it is exactly the failure mode the
blueprint names ("fragmentation or false merging").

| | single-pass pipeline | Layer 1 ensemble |
|---|---|---|
| mention recall | 88.9% | **99.4%** |
| mention precision | 70.0% | 73.8% |
| systematic miss patterns | 5 | **0** |
| resolved entities (GT = 180) | 198 | **521** |
| B-cubed P / R | 0.92 / 0.94 | 0.85 / 0.63 |

Feeding 9,674 mentions (up from ~9,400, with far more surface variety and org
spans) into an ER stage tuned for a lower-recall extractor **fragments entities**:
one real adjuster split across 10 clusters despite 2,070 positive-scoring edges
between the fragments.

Four principled interventions were tried and measured:

1. **Tightened identifier binding** (same-line / previous-line only, instead of
   nearest-preceding-anywhere) — B³ precision 0.76 → **0.86**. Worked.
2. **B0 exact-name blocking** (large phonetic blocks were falling back to star
   topology anchored on a possibly-different person) — 604 → 525 clusters. Small.
3. **Structural-only cannot-link veto** + cluster-level identifier consistency
   (so one mis-bound identifier can't veto a merge) — no effect.
4. **Dominant-value identifier semantics** (a value asserted by a single mention
   can't define cluster identity) — no effect.

Interventions 3 and 4 did not move the number, so **the residual under-merge is
not where those hypotheses predicted**, and I stopped rather than keep guessing.
Diagnosing it properly is the top open item. Candidate next steps, in order:

- Instrument `cluster()` directly to log the *rejected reason* per blocked merge
  (the fastest way to end the guesswork).
- Implement the blueprint's Layer 2 prescription properly: contextual embedding
  over `name + type + description` (the ensemble now produces descriptions, and
  `rapidfuzz` is available) — the current embedding is a hashing stand-in with
  weak discriminative power offline.
- Give organizations their own entity class so firm/shop spans stop competing
  with person clusters.

Until that is fixed, **Layer 1 + Layers 3–4 are the parts of this stack that are
production-shaped; Layer 2 is not.**

---

## What is verified

- Ablation reproduces on the full corpus (notebook 11).
- All four new notebooks execute top-to-bottom in a fresh kernel (10: 9.8s,
  11: 8.0s, 12: 2.7s, 13: 3.2s).
- **Scan coverage remains 100%** of characters per doc after the architecture
  change; the chunk ledger replaces the segment ledger and still proves it.
- **Leakage guard extended** to all 15 pipeline modules and the new notebooks;
  `src/ablation.py` is registered audit-side. All four isolation guards pass.
- Corpus hashes unchanged — the raw notes were never modified.
