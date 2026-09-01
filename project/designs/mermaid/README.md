# Pipeline activity diagrams — mermaid sources

Mermaid versions of the UML activity diagrams in
[`../pipeline-activity-diagrams.html`](../pipeline-activity-diagrams.html), which
remains the fuller companion: it carries the per-stage goal statements, the
worked-example tables in full, and the `entity_class` design discussion that has
no diagram.

These show the *process* — what happens to a document as it moves through the
pipeline. For the *data model* — what tables exist and how they relate — see
[`erd/`](erd/README.md).

Each `.mermaid` file here is standalone and is the source of truth. The blocks
below are generated copies so they render on GitHub — regenerate with
`python3 build_readme.py` after editing any diagram.

## Reading these

| shape | meaning |
|---|---|
| stadium, dark fill | initial / final node |
| rectangle, grey fill | activity — something happens |
| rectangle, blue fill | object node — data at rest |
| diamond | decision |
| dark bar | fork / join |
| rectangle, red fill | data discarded here |
| rectangle, amber fill | a path worth noticing |
| dashed box, dotted edge | worked data example, or a design caveat |
| **green, thick dashed** | **PROPOSED — designed, not built.** Shown at the point in the flow where it would land, so it can be reviewed in place. |
| purple, dashed | `src/research/` — corpus-fitted, unimported by the pipeline, entered only by naming it |

## Proposed changes currently on the board

Both are drawn into the diagram at their insertion point rather than described
separately, so the review question is "does this belong here?" and not "where
would this go?".

| # | change | where | status |
|---|---|---|---|
| 1 | Split `entity_class` into a closed `entity_type` (person / organization) and an **open** `role` defaulting to `NULL` | [diagram 06](06-filter-classify-persist.mermaid), replacing the *Classify entity_class* node | designed, not built |
| 2 | Normalize the mention surface (strip leading role/title tokens) before deriving ER blocking keys | [diagram 07](07-entity-resolution.mermaid), inserted between *build_mention_frame* and *derive blocking keys* | designed, not built |

Proposal 1 fixes a live defect: `_classify` falls back to
`LABEL_TO_CLASS.get(label, "claimant")`, so an unmatched person is silently
stored as a claimant and an unmatched organization as a medical provider — a
guess written into a field readers treat as a fact.

Proposal 2 is backed by measurement rather than intuition: on this machine
GLiNER's recall was identical across casing regimes (9/9 mixed, ALL CAPS and
lowercase), but exact span-boundary agreement was only 24/31 = 77%, and the
disagreements were leading role words (`adjuster Karen Wu` vs `Karen Wu`).
Role-word absorption happens in mixed case too, so it is not a casing bug.

Two notational compromises, since Mermaid's flowchart grammar is not UML:

- **Fork and join bars** are drawn as labelled dark nodes rather than the thin
  UML synchronisation bar, which the grammar has no shape for. `stateDiagram-v2`
  does provide a real `<<fork>>`, but gives up the decision diamond, the object
  node, and multi-line labels — a bad trade for diagrams whose whole point is the
  per-node data examples.
- **Data examples** hang off their activity as dashed notes on a dotted edge,
  rather than sitting in a table beside the figure as they do in the HTML.

Every diagram in this folder is checked to parse and render with mermaid 11.

## Diagrams


### A — Freeze and fingerprint the note

Source: [`01-freeze-fingerprint.mermaid`](01-freeze-fingerprint.mermaid)

```mermaid
---
title: "A — Freeze and fingerprint the note"
---
flowchart TD
  classDef act  fill:#EDF0F4,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef obj  fill:#E0E8EF,stroke:#3E5C76,stroke-width:1.3px,color:#10151C
  classDef dec  fill:#FFFFFF,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef bar  fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef bad  fill:#F6E0DB,stroke:#A33A2A,stroke-width:1.4px,color:#10151C
  classDef key  fill:#F6E7CE,stroke:#B4650A,stroke-width:1.6px,color:#10151C
  classDef muted fill:#FFFFFF,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:4 3,color:#4A5666
  classDef ex   fill:#FBFCFD,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:3 3,color:#33404F
  classDef warn fill:#FFF6E8,stroke:#B4650A,stroke-width:1.3px,stroke-dasharray:5 3,color:#3A2C16
  classDef term fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF


  A0(["raw note file arrives"]):::term
  A1["<b>Read note bytes from disk</b><br/><i>hashing.sha256_file</i>"]:::act
  A2["<b>sha256 hex digest</b><br/>64-char string"]:::obj
  A3["<b>Write digest to hashes.json</b><br/><i>hashing.write_hashes</i>"]:::act
  A4["<b>Assign stable doc_id</b><br/>doc_id ← filename stem"]:::act
  A5{"re-run:<br/>digest matches?"}:::dec
  A6["<b>HALT — corpus mutated</b><br/><i>verify_hashes raises</i>"]:::bad
  A7["<b>frozen corpus + hash manifest</b><br/>every later span anchors here"]:::obj
  A8(["ready for segmentation"]):::term

  A0 --> A1 --> A2 --> A3 --> A4 --> A5
  A5 -->|"no"| A6
  A5 -->|"yes"| A7 --> A8

  AX1["<b>in</b> — note_0734.txt, 2,317 bytes<br/>'Spoke with Robert Miller regarding the POA update filed last week. He confirmed…'<br/><b>out</b> — 'note_0734': 'a3f1c9e2b7d4…8e1f'<br/><i>The whole file collapses to one fixed-length digest, so a single changed character produces a different digest and is caught on the next verify.</i>"]:::ex
  A2 -.->|"example"| AX1
```

### B — Source claim identity, then segment and score the note

Source: [`02-claim-identity-and-segmentation.mermaid`](02-claim-identity-and-segmentation.mermaid)

```mermaid
---
title: "B — Source claim identity, then segment and score the note"
---
flowchart TD
  classDef act  fill:#EDF0F4,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef obj  fill:#E0E8EF,stroke:#3E5C76,stroke-width:1.3px,color:#10151C
  classDef dec  fill:#FFFFFF,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef bar  fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef bad  fill:#F6E0DB,stroke:#A33A2A,stroke-width:1.4px,color:#10151C
  classDef key  fill:#F6E7CE,stroke:#B4650A,stroke-width:1.6px,color:#10151C
  classDef muted fill:#FFFFFF,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:4 3,color:#4A5666
  classDef ex   fill:#FBFCFD,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:3 3,color:#33404F
  classDef warn fill:#FFF6E8,stroke:#B4650A,stroke-width:1.3px,stroke-dasharray:5 3,color:#3A2C16
  classDef term fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef research fill:#EEE9F5,stroke:#6B5B95,stroke-width:1.2px,stroke-dasharray:5 3,color:#2E2640
  classDef proposed fill:#E4F2EA,stroke:#2F6B4F,stroke-width:2px,stroke-dasharray:7 3,color:#12301F

  B0(["frozen note file"]):::term
  B1["<b>Parse claim_number + note_id from filename</b><br/>filename pattern: ClaimNumber_NoteID.txt"]:::act
  B2["<b>Join against the client's occurrence table</b><br/>Occurrence Number · Claim Number · Note ID<br/>client-provided, never extracted from text"]:::key
  B3["<b>doc_id → claim_id + occurrence_id</b><br/>structural metadata, known before any text is read"]:::obj
  B4["<b>Split note into physical lines</b><br/><i>profiling._line_spans</i>"]:::act
  B5{"line begins a quoted chain?"}:::dec
  B6["<b>kind = quoted</b><br/>a re-sent chain; a mention inside it is not a new sighting"]:::act
  B7["<b>kind = body</b><br/>everything else"]:::act
  B8["<b>Group runs of like lines into segments</b><br/><i>profiling.segment_document</i> — stateless, no latch"]:::act
  B9["<b>Score each segment; never gate on it</b><br/><i>boilerplate_score</i> over a disclaimer cue bundle<br/><i>casing.profile</i> → regime + case_informative"]:::key
  B10["<b>Fingerprint form-like segments</b><br/><i>profiling.template_fingerprint</i> — hash of the label sequence"]:::act
  B11["<b>MinHash shingles → near-dup groups</b><br/><i>profiling._minhash + assign_dup_groups</i><br/>content-based; the part of Layer 0 that generalizes cleanly"]:::act
  B12["<b>segments rows</b><br/>kind, char_start, char_end, dup_group_id,<br/>boilerplate_score, casing_regime, case_informative"]:::obj
  B13(["ready for chunking"]):::term

  B0 --> B1 --> B2 --> B3 --> B4 --> B5
  B5 -->|"yes"| B6
  B5 -->|"no"| B7
  B6 --> B8
  B7 --> B8
  B8 --> B9 --> B10 --> B11 --> B12 --> B13

  BX1["<b>in</b> — CLM00182_0734.txt, the filename as delivered<br/><b>out</b> — claim_number='CLM00182', note_id='0734'<br/><i>Parsed directly from the name; no text has been read yet.</i>"]:::ex
  B1 -.->|"example"| BX1

  BX2["<b>in</b> — join row: OCC0091 · CLM00182 · 0734<br/><b>out</b> — doc_id='note_0734' → claim_id='CLM00182', occurrence_id='OCC0091'<br/><i>Structural metadata established before extraction runs — not a claim about what the text says. The old CLM-plus-4-digits text fallback is gone: it only ever matched our own synthetic corpus, and on real data would mint an identity from any four digits following those letters.</i>"]:::ex
  B2 -.->|"example"| BX2

  BX3["<b>in</b> — 'This e-mail and any attachments are confidential and may be legally privileged. If you are not the intended recipient, any dissemination is unauthorized.'<br/><b>out</b> — boilerplate_score = 1.00<br/><i>Wording our generator never produced. The previous rule was three literal phrases and would have scored this 0, leaving every name inside a real disclaimer exposed to the name filter.</i>"]:::ex
  B9 -.->|"example"| BX3

  BX4["<b>in</b> — 'Counsel asserted attorney-client privilege over the file notes.'<br/><b>out</b> — boilerplate_score = 0.48, below the 0.5 flag<br/><i>Narrative that merely mentions privilege is not a disclaimer. And because the score is advisory, being wrong here costs a flag, never a deleted name.</i>"]:::ex
  B9 -.->|"example"| BX4

  BX5["<b>in</b> — an ALL CAPS header block above a normally-cased body<br/><b>out</b> — header: regime='upper', case_informative=0 · body: regime='mixed', case_informative=1<br/><i>Profiled per segment, because the common legacy shape is a case-degenerate header sitting on a clean narrative. Recorded for measurement — it no longer routes anything, see diagram 04.</i>"]:::ex
  B9 -.->|"example"| BX5

  BW["<b>What was removed here, and why</b><br/>Seven segment kinds became two. template_block, narrative, email_header, email_body and email_signature had <b>no consumer</b> in the production path, and were produced by the module's most fragile rules.<br/>· The signature rule matched only a bare double-hyphen line — the Usenet convention, which Outlook does not emit — and drove a latch that was <b>never cleared</b>, so one stray divider retyped the whole rest of a note as signature.<br/>· Boilerplate was a <b>hard kind</b>: a misclassification silently deleted every real name inside the segment, and a differently-worded disclaimer excluded nothing at all.<br/>Retired rules live in <i>src/research/corpus_heuristics.py</i>, unimported by the pipeline."]:::warn
  B8 -.->|"design note"| BW
```

### C — Cut the note into overlapping chunks

Source: [`03-chunking.mermaid`](03-chunking.mermaid)

```mermaid
---
title: "C — Cut the note into overlapping chunks"
---
flowchart TD
  classDef act  fill:#EDF0F4,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef obj  fill:#E0E8EF,stroke:#3E5C76,stroke-width:1.3px,color:#10151C
  classDef dec  fill:#FFFFFF,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef bar  fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef bad  fill:#F6E0DB,stroke:#A33A2A,stroke-width:1.4px,color:#10151C
  classDef key  fill:#F6E7CE,stroke:#B4650A,stroke-width:1.6px,color:#10151C
  classDef muted fill:#FFFFFF,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:4 3,color:#4A5666
  classDef ex   fill:#FBFCFD,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:3 3,color:#33404F
  classDef warn fill:#FFF6E8,stroke:#B4650A,stroke-width:1.3px,stroke-dasharray:5 3,color:#3A2C16
  classDef term fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF


  C0(["segmented note"]):::term
  C1["<b>Compute target window size</b><br/><i>chunking.words_per_chunk</i> from config"]:::act
  C2["<b>Walk words, emit overlapping windows</b><br/><i>chunking.chunk_document</i>"]:::act
  C3["<b>Chunk objects</b><br/>chunk_id, char_start, char_end, index, n_words"]:::obj
  C4["<b>Verify every char lands in ≥1 chunk</b><br/><i>chunking.coverage_report</i>"]:::act
  C5{"coverage == 100%?"}:::dec
  C6["<b>Report shortfall</b><br/>hygiene check fails loudly"]:::bad
  C7["<b>chunks ready for extraction</b><br/>text + absolute offsets preserved"]:::obj
  C8(["ready for D1"]):::term

  C0 --> C1 --> C2 --> C3 --> C4 --> C5
  C5 -->|"no"| C6
  C5 -->|"yes"| C7 --> C8

  CX1["<b>in</b> — narrative segment, 470 words, chars 43–2317<br/><b>out</b> — chunk_id='c0734_02', char_start=43, char_end=1180, index=2, n_words=190<br/><i>The segment becomes a window small enough to process, tagged with the absolute offsets that let any span found inside it map back to the raw note.</i>"]:::ex
  C3 -.->|"example"| CX1

  CW["<b>Why overlap at all</b><br/>A hard cut can land mid-entity: 'Dr. Alicia' ends one window and 'Reyes' opens the next, so neither window contains the mention. Overlapping the windows means every span is wholly inside at least one of them; the coverage check then proves no character was read by nobody. The duplicate hits this creates are collapsed by union_spans in D1/D2, which is why overlap is safe to add."]:::warn
  C2 -.->|"rationale"| CW
```

### D1 — Generate candidates: fork, extract, join, sweep

Source: [`04-generate-candidates.mermaid`](04-generate-candidates.mermaid)

```mermaid
---
title: "D1 — Generate candidates: fork, extract, join, sweep"
---
flowchart TD
  classDef act  fill:#EDF0F4,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef obj  fill:#E0E8EF,stroke:#3E5C76,stroke-width:1.3px,color:#10151C
  classDef dec  fill:#FFFFFF,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef bar  fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef bad  fill:#F6E0DB,stroke:#A33A2A,stroke-width:1.4px,color:#10151C
  classDef key  fill:#F6E7CE,stroke:#B4650A,stroke-width:1.6px,color:#10151C
  classDef muted fill:#FFFFFF,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:4 3,color:#4A5666
  classDef ex   fill:#FBFCFD,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:3 3,color:#33404F
  classDef warn fill:#FFF6E8,stroke:#B4650A,stroke-width:1.3px,stroke-dasharray:5 3,color:#3A2C16
  classDef term fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef research fill:#EEE9F5,stroke:#6B5B95,stroke-width:1.2px,stroke-dasharray:5 3,color:#2E2640
  classDef proposed fill:#E4F2EA,stroke:#2F6B4F,stroke-width:2px,stroke-dasharray:7 3,color:#12301F

  D0(["one chunk — text + absolute offsets"]):::term
  FORK["<b>fork</b> — three independent extractors read the same chunk text"]:::bar
  D0 --> FORK

  subgraph LANE1["Lane 1 · Token-NER — GLiNER, REQUIRED"]
    direction TB
    L1["<b>Load the production backend</b><br/><i>ner_ensemble.get_token_ner</i> → GlinerBackend"]:::act
    L1E["<b>NERBackendUnavailable</b><br/>raised if the weights cannot load — the run STOPS"]:::bad
    L2["<b>Zero-shot span scan over every token</b><br/>GLINER_THRESHOLD 0.35, recall-first"]:::act
    L3["<b>Drop pronouns / vague descriptors</b><br/><i>coref.is_anaphor</i>"]:::act
    L4["<b>Emit SpanCandidate</b><br/>extractors = token_ner"]:::act
    L1 -->|"cannot load"| L1E
    L1 -->|"loaded"| L2 --> L3 --> L4
  end

  subgraph LANE2["Lane 2 · Gazetteer — patterns, with honest validation strength"]
    direction TB
    M1["<b>Pattern scan</b><br/><i>gazetteers.scan</i> — phone / email / npi / ssn / tin / address / …"]:::act
    M2["<b>Record validation STRENGTH, not a bare boolean</b><br/>checksum: npi only · format: email, phone, icd10, cpt · none: the rest"]:::key
    M3["<b>Emit SpanCandidate</b><br/>extractors = gazetteer; score 1.0 / 0.8 / 0.6 by strength"]:::act
    M1 --> M2 --> M3
  end

  subgraph LANE3["Lane 3 · LLM semantic pass — what no pattern encodes"]
    direction TB
    R0{"API key present?"}:::dec
    R0E["<b>LLMExtractorUnavailable</b><br/>raised when offline was FALLEN INTO rather than chosen"]:::bad
    R1["<b>Build extraction prompt</b><br/>chunk text + allowed label enum"]:::act
    R2["<b>Constrained JSON generation</b><br/><i>genai.generate_json with _llm_ner_schema</i>"]:::act
    R3["<b>Drop pronouns / clip offsets to chunk</b>"]:::act
    R4["<b>Emit SpanCandidate</b><br/>extractors = llm; carries a free-text description"]:::act
    R0 -->|"no, and GENAI_MODE unset"| R0E
    R0 -->|"yes"| R1 --> R2 --> R3 --> R4
  end

  FORK --> L1
  FORK --> M1
  FORK --> R0

  JOIN["<b>join</b> — union_spans · see diagram 05 for the merge rule"]:::bar
  L4 --> JOIN
  M3 --> JOIN
  R4 --> JOIN

  P1["<b>per-chunk candidate list</b><br/>post first union"]:::obj
  JOIN --> P1
  SW{"sweep enabled?"}:::dec
  P1 --> SW
  SKIP["<b>Skip straight to the next chunk</b>"]:::muted
  SW -->|"no"| SKIP

  S1["<b>Find text spans no candidate covers</b><br/><i>sweep.uncovered_candidates</i>"]:::act
  S2["<b>Differential-audit prompt: 'what is missing?'</b><br/>shown its own extraction list, asked only for the gaps"]:::key
  S3["<b>Second constrained LLM pass</b><br/>low-salience recall net — paralegals, codes, secondary providers"]:::act
  S4["<b>Union sweep results into the pool</b>"]:::act
  SW -->|"yes"| S1 --> S2 --> S3 --> S4

  P2["<b>final per-chunk candidate dataset</b>"]:::obj
  S4 --> P2
  SKIP --> P2
  MERGE["<b>Merge every chunk's candidates for this document</b><br/>second union_spans call — cross-chunk overlaps collapse too"]:::act
  P2 -->|"one chunk's output ×N chunks"| MERGE
  P3["<b>per-document candidate pool</b><br/>→ continues in diagram 06"]:::obj
  MERGE --> P3 --> D9(["to filter / classify / persist"]):::term

  RESEARCH["<b>src/research/ — NOT reachable from this path</b><br/>DeterministicTokenNER (capitalized-run regex) and the salience LLM stub.<br/>Entered only by naming them: NER_BACKEND=deterministic, GENAI_MODE=offline.<br/><i>There is no automatic route into this box. Both were previously silent fallbacks, which is why every recall number measured before that change described a regex rather than a model, and why the three-way union was really two-way.</i>"]:::research
  L1E -.->|"opt-in only"| RESEARCH
  R0E -.->|"opt-in only"| RESEARCH

  MEAS["<b>Measured on this machine, GLiNER multi-v2.1</b><br/>Recall was <b>identical</b> across casing regimes — mixed 9/9, ALL CAPS 9/9, lowercase 9/9.<br/>The retired regex scanner on the same sentences: 9/9, then 5/9 with <b>11 spurious spans</b>, then <b>0/9</b>.<br/><i>Capitalization fragility was a property of that backend, not of the architecture. Small sample (7 sentences), but the gap is not subtle. What casing DOES move is span boundaries — see diagram 07.</i>"]:::ex
  L2 -.->|"casing probe"| MEAS

  MX1["<b>in</b> — 'NPI 1568291037'<br/><b>out</b> — valid=True, validation='checksum'<br/><i>A real Luhn check over '80840' plus the first 9 digits (the NPPES standard). A random 10-digit string passes with p≈0.1, so this genuinely discriminates.</i>"]:::ex
  M2 -.->|"example"| MX1

  MX2["<b>in</b> — 'SSN 123-45-6789'<br/><b>out</b> — valid=True, validation='none'<br/><i>Nothing beyond the pattern was checked. This previously re-ran the identical regex that had already matched and called the result validation — tautological, and it read in code and in this diagram as though a real check had occurred. Of 14 patterns exactly one carries a check digit; 7 have none.</i>"]:::ex
  M2 -.->|"example"| MX2

  SX["<b>in</b> — the chunk plus the candidate list already found<br/><b>out</b> — only the mentions absent from that list<br/><i>A differential audit, not a repeat of the first pass: the model is shown its own answer and asked what it missed.</i>"]:::ex
  S2 -.->|"example"| SX
```

### D2 — How union_spans merges overlapping candidates

Source: [`05-union-overlapping-candidates.mermaid`](05-union-overlapping-candidates.mermaid)

```mermaid
---
title: "D2 — How union_spans merges overlapping candidates"
---
flowchart TD
  classDef act  fill:#EDF0F4,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef obj  fill:#E0E8EF,stroke:#3E5C76,stroke-width:1.3px,color:#10151C
  classDef dec  fill:#FFFFFF,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef bar  fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef bad  fill:#F6E0DB,stroke:#A33A2A,stroke-width:1.4px,color:#10151C
  classDef key  fill:#F6E7CE,stroke:#B4650A,stroke-width:1.6px,color:#10151C
  classDef muted fill:#FFFFFF,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:4 3,color:#4A5666
  classDef ex   fill:#FBFCFD,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:3 3,color:#33404F
  classDef warn fill:#FFF6E8,stroke:#B4650A,stroke-width:1.3px,stroke-dasharray:5 3,color:#3A2C16
  classDef term fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF


  U0(["flat list of candidates from every source"]):::term
  U1["<b>Sort by start, then by descending length</b><br/>longest-starting-first tie-break"]:::act
  U2["<b>Take the next candidate C, walk the merged list</b>"]:::act
  U3{"C overlaps an<br/>already-merged span M?"}:::dec
  U4["<b>Start a new merged entry from C</b>"]:::act
  U5["<b>Union provenance onto M</b><br/>M.extractors |= C.extractors"]:::key
  U6{"C longer than M?"}:::dec
  U7["<b>M adopts C's span and text</b><br/>and keeps C's label if it is more specific than person / organization"]:::act
  U8["<b>Keep M's span</b><br/>if M's label is generic and C's is specific, adopt C's label only"]:::act
  U9["<b>deduplicated candidate set</b><br/>one entry per real-world mention, provenance preserved"]:::obj
  U10(["to filter / classify / persist"]):::term

  U0 --> U1 --> U2 --> U3
  U3 -->|"no"| U4
  U3 -->|"yes"| U5 --> U6
  U6 -->|"yes"| U7
  U6 -->|"no"| U8
  U4 --> LOOP
  U7 --> LOOP
  U8 --> LOOP
  LOOP{"more candidates?"}:::dec
  LOOP -->|"yes — advance to the next candidate"| U2
  LOOP -->|"no — list exhausted"| U9 --> U10

  UX1["<b>in</b> — A: 'Moore' at 818:823, token_ner, person<br/>B: 'James Moore' at 812:823, llm, person<br/><b>out</b> — 'James Moore' at 812:823, extractors = token_ner + llm, person<br/><i>The spans overlap and B is longer, so its text and offsets win, while A's contribution survives in the merged extractor set.</i>"]:::ex
  U7 -.->|"example"| UX1

  UX2["<b>in</b> — A: 'Reyes' at 40:45, token_ner, person<br/>B: 'Dr. Alicia Reyes' at 30:47, gazetteer, medical_provider<br/><b>out</b> — 'Dr. Alicia Reyes' at 30:47, extractors = token_ner + gazetteer, medical_provider<br/><i>B is both longer and more specific than the generic 'person' label, so its label is kept rather than A's.</i>"]:::ex
  U7 -.->|"example"| UX2

  UW["<b>Why no extractor has to win</b><br/>Merging on overlap is what makes the three-way fork in diagram 04 safe. Agreement and disagreement are both preserved: the surviving candidate's extractor set records who found it, so a span found by all three and a span found only by the LLM stay distinguishable downstream instead of being flattened into one undifferentiated pool."]:::warn
  U5 -.->|"rationale"| UW
```

### D3 — Filter, classify, bind, and persist

Source: [`06-filter-classify-persist.mermaid`](06-filter-classify-persist.mermaid)

```mermaid
---
title: "D3 — Filter, classify, bind, and persist"
---
flowchart TD
  classDef act  fill:#EDF0F4,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef obj  fill:#E0E8EF,stroke:#3E5C76,stroke-width:1.3px,color:#10151C
  classDef dec  fill:#FFFFFF,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef bar  fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef bad  fill:#F6E0DB,stroke:#A33A2A,stroke-width:1.4px,color:#10151C
  classDef key  fill:#F6E7CE,stroke:#B4650A,stroke-width:1.6px,color:#10151C
  classDef muted fill:#FFFFFF,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:4 3,color:#4A5666
  classDef ex   fill:#FBFCFD,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:3 3,color:#33404F
  classDef warn fill:#FFF6E8,stroke:#B4650A,stroke-width:1.3px,stroke-dasharray:5 3,color:#3A2C16
  classDef term fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef research fill:#EEE9F5,stroke:#6B5B95,stroke-width:1.2px,stroke-dasharray:5 3,color:#2E2640
  classDef proposed fill:#E4F2EA,stroke:#2F6B4F,stroke-width:2px,stroke-dasharray:7 3,color:#12301F

  F0(["per-document candidate pool — from diagram 04"]):::term
  FORK["<b>fork</b> — every candidate is routed by its label"]:::bar
  F0 --> FORK

  subgraph NAMES["Name lane — a name has to look like a name"]
    direction TB
    N1["<b>label ∈ NAME_LABELS</b><br/>person / organization / attorney / repair_shop / …"]:::act
    N2["<b>Read boilerplate_score for this span</b><br/>ADVISORY — scored, counted, carried onto the row"]:::key
    N3{"passes<br/>_is_plausible_name?"}:::dec
    N3D["<b>Dropped</b><br/>n_dropped_shape += 1"]:::bad
    N4["<b>Classify entity_class</b><br/><i>_classify</i> over surface, label, left context, right context"]:::act
    N5["<b>Persist mentions row</b><br/>mention_id, surface, char_start, char_end,<br/>entity_class, inside_quoted, boilerplate_score"]:::act
    N6["<b>Persist has_name assertion</b><br/>source_span = the mention's OWN span"]:::act
    N1 --> N2 --> N3
    N3 -->|"no"| N3D
    N3 -->|"yes"| N4 --> N5 --> N6
  end

  subgraph IDS["Identifier lane — an identifier has to be found near a name, or not"]
    direction TB
    I1["<b>label ∈ IDENTIFIER_LABEL_TO_PREDICATE</b><br/>phone / email / npi / tin / ssn / address"]:::act
    I2["<b>subject_for on char_start</b><br/>same line, or ≤120 chars on the immediately preceding line"]:::act
    I3["<b>Persist identifier_observations row — always</b><br/>subject_mention_id = the binding result, NULL if none"]:::key
    I4{"a subject<br/>was found?"}:::dec
    I5["<b>Persist binding assertion</b> e.g. has_phone<br/>source_span = the IDENTIFIER's own location, not the name's"]:::key
    I6["<b>Orphan — no assertion</b><br/>the observation row still stands on its own"]:::key
    I1 --> I2 --> I3 --> I4
    I4 -->|"yes"| I5
    I4 -->|"no"| I6
  end

  FORK --> N1
  FORK --> I1

  JOIN["<b>join</b>"]:::bar
  N6 --> JOIN
  I5 --> JOIN
  I6 --> JOIN

  G1["<b>Scan raw text for allegation language</b><br/>regex over the SOURCE TEXT directly — not over the candidate pool"]:::act
  G2["<b>Bind to nearest mention, persist allegation assertion</b><br/>polarity 'alleged' — kept separate from asserted fact"]:::act
  G3["<b>Resolve coreference over every mention found above</b><br/><i>coref.RuleBasedCorefResolver.resolve</i> over raw_text + mentions"]:::act
  G4["<b>Persist coref_links row</b><br/>anaphor span + antecedent span + antecedent_mention_id"]:::act
  G5["<b>Record scan_ledger coverage for this document</b>"]:::obj
  G6["<b>Persist mentions, assertions, identifier_observations, coref_links</b><br/>one transaction per corpus run"]:::act
  G7(["to entity resolution — diagram 07"]):::term

  JOIN --> G1 -->|"match"| G2 --> G3 -->|"anaphor found"| G4 --> G5 --> G6 --> G7

  NB["<b>in</b> — a name inside a segment scoring boilerplate_score = 1.00<br/><b>out</b> — mention PERSISTED, boilerplate_score = 1.0 stored on the row<br/><i>Previously this was a hard gate and the mention was deleted with no trace. A miss cost precision; a false positive silently erased real names. Now the evidence survives and a consumer discounts it.</i>"]:::ex
  N2 -.->|"example"| NB

  IX1["<b>in</b> — SpanCandidate text='(312) 555-0148', label='phone', no name on this line or the previous one<br/><b>out</b> — identifier_observations kind='phone', value_norm='3125550148', subject_mention_id=NULL<br/><i>Recorded anyway. An identifier with no name nearby is exactly the case this system exists to catch, not a reason to drop it.</i>"]:::ex
  I6 -.->|"example"| IX1

  IX2["<b>in</b> — subject: mention m0000153, 'Robert Miller', chars 40–52<br/>identifier '(312) 555-0148', chars 918–932, bound via subject_for<br/><b>out</b> — Assertion predicate='has_phone', object_value_norm='3125550148', source_span_start=918, source_span_end=932<br/><i><b>This is what an evidence span is.</b> The subject points at the name's location; the evidence span points at the phone number's location — a different place. The fact is ABOUT the subject but PROVEN at the evidence span.</i>"]:::ex
  I5 -.->|"example"| IX2

  CX1["<b>Resolving anaphora to antecedent mentions</b> means finding the specific earlier word or phrase that a pronoun or later reference points back to.<br/><br/>'John gave Mary a present. She loved it.'<br/><b>Antecedents</b> — 'Mary' and 'a present'<br/><b>Anaphors</b> — 'She', referring to Mary, and 'it', referring to the present.<br/><i>Without this step 'She' is either dropped or becomes its own bogus entity.</i>"]:::warn
  G3 -.->|"what this means"| CX1

  CX2["<b>in</b> — '…Spoke with Robert Miller regarding the POA update. He confirmed the demand was served…'<br/>mention m0000153 = 'Robert Miller' at 40:52<br/><b>out</b> — CorefLink surface='He', start=95, end=97, antecedent_surface='Robert Miller', antecedent_start=40, antecedent_end=52, kind='pronoun'<br/><i>The anaphor keeps its own span, so the sentence it appears in stays traceable.</i>"]:::ex
  G4 -.->|"example"| CX2

  %% ---------------- PROPOSED CHANGE 1 -------------------------------
  PROP1["<b>PROPOSED — split entity_class into two fields</b><br/>Not yet built. This node replaces N4.<br/><br/><b>entity_type</b>: person | organization — stays CLOSED. It is a genuine binary and <i>entity_resolution.cannot_link_reason</i> uses it structurally to block person↔org merges.<br/><b>role</b>: OPEN vocabulary, normalized toward canonical forms, defaulting to <b>NULL</b> when unmatched.<br/><br/><i>Why: today ENTITY_CLASSES is a closed 5-tuple (claimant, attorney, medical_provider, repair_shop, adjuster) set PER MENTION, and role-in-claim is not a closed set in reality — witnesses, landlords, employers, public adjusters, SIU investigators and opposing counsel all exist. It is the same restrictive-box problem the predicate vocabulary had before it was opened.</i>"]:::proposed
  N4 -.->|"proposed replacement"| PROP1

  PROP1B["<b>The concrete defect this fixes</b><br/><i>_classify</i> ends in <b>LABEL_TO_CLASS.get(label, 'claimant')</b>.<br/>An unmatched 'person' is silently written as <b>claimant</b>; an unmatched 'organization' as <b>medical_provider</b>.<br/><br/>· 'Marisol Vega', actually a witness → stored claimant<br/>· 'Sunrise Property Mgmt', actually the landlord → stored medical_provider<br/><br/><i>That is a guess written into a field every downstream reader — and the client — treats as a fact. Under the proposal both become role=NULL, which is honest and is queryable as 'needs a role'.</i>"]:::warn
  PROP1 -.-> PROP1B
```

### E — Resolve mentions into entities

Source: [`07-entity-resolution.mermaid`](07-entity-resolution.mermaid)

```mermaid
---
title: "E — Resolve mentions into entities"
---
flowchart TD
  classDef act  fill:#EDF0F4,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef obj  fill:#E0E8EF,stroke:#3E5C76,stroke-width:1.3px,color:#10151C
  classDef dec  fill:#FFFFFF,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef bar  fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef bad  fill:#F6E0DB,stroke:#A33A2A,stroke-width:1.4px,color:#10151C
  classDef key  fill:#F6E7CE,stroke:#B4650A,stroke-width:1.6px,color:#10151C
  classDef muted fill:#FFFFFF,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:4 3,color:#4A5666
  classDef ex   fill:#FBFCFD,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:3 3,color:#33404F
  classDef warn fill:#FFF6E8,stroke:#B4650A,stroke-width:1.3px,stroke-dasharray:5 3,color:#3A2C16
  classDef term fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef research fill:#EEE9F5,stroke:#6B5B95,stroke-width:1.2px,stroke-dasharray:5 3,color:#2E2640
  classDef proposed fill:#E4F2EA,stroke:#2F6B4F,stroke-width:2px,stroke-dasharray:7 3,color:#12301F

  E0(["all mentions for the corpus"]):::term
  E1["<b>Build one feature row per mention</b><br/><i>entity_resolution.build_mention_frame</i>"]:::act
  E2["<b>Derive the blocking keys from the surface</b><br/>full_name · name_sorted = sorted tokens<br/>first_name = toks[0] · last_name = toks[-1] · soundex(last)"]:::key
  E3["<b>Null out missing identifiers</b><br/>empty string would block-explode; NULL is excluded by Splink"]:::act
  E4["<b>mention frame</b><br/>name keys + email, phone7, npi, tin, dob, address_key"]:::obj
  E5["<b>Declare blocking rules</b><br/>email · npi · tin · phone7 · address_key<br/>full_name · name_sorted · soundex+first_name · last_name"]:::act
  E6["<b>Estimate match prior from deterministic rules</b>"]:::act
  E7["<b>Estimate u by random sampling</b>"]:::act
  E8["<b>Train m by expectation-maximisation</b><br/>one pass per blocking rule; sparse blocks skipped"]:::act
  E9["<b>Score every blocked candidate pair</b><br/><i>linker.inference.predict</i>"]:::act
  E10["<b>same_as_edges rows</b><br/>mention_a, mention_b, probability, match_weight"]:::obj
  E11{"structural conflict?"}:::dec
  E12["<b>Edge suppressed before clustering</b><br/><i>cannot_link_reason</i> — person vs org, Jr/Sr, conflicting NPI"]:::bad
  E13["<b>Union-find over edges ≥ threshold</b><br/><i>entity_resolution.cluster_at</i>"]:::act
  E14["<b>entity_snapshot / entities / entity_members</b><br/>identity is a VIEW at T, never a destructive merge"]:::key
  E15["<b>Sweep T to plot the operating curve</b><br/>B³ precision / recall per threshold"]:::act
  E16(["to graph assembly — diagram 08"]):::term

  E0 --> E1 --> E2 --> E3 --> E4 --> E5 --> E6 --> E7 --> E8 --> E9 --> E10 --> E11
  E11 -->|"yes"| E12
  E11 -->|"no"| E13 --> E14 --> E15 --> E16

  EX1["<b>in</b> — mention pair m0000153 'Robert Miller' and m0000891 'R. Miller', same phone last-7<br/><b>out</b> — same_as_edges probability=0.94, match_weight=+6.2<br/><i>The pair is scored, not merged. A number survives into storage where a yes/no decision would have destroyed the evidence.</i>"]:::ex
  E10 -.->|"example"| EX1

  EX2["<b>in</b> — all edges, threshold T=0.90<br/><b>out</b> — entity_snapshot rows grouping both mentions under one entity_id at that T<br/><i>Identity is recomputed per threshold, so raising or lowering T re-partitions the corpus without re-running resolution.</i>"]:::ex
  E14 -.->|"example"| EX2

  EX3["<b>in</b> — 'Miller Auto Body' (organization) and 'Robert Miller' (person), high name similarity<br/><b>out</b> — edge suppressed, never reaches clustering<br/><i>A hard structural constraint applied as edge suppression rather than a permanent veto. Note this is the ONE place entity_class is load-bearing — see the proposal in diagram 06, which keeps person/organization closed precisely so this keeps working.</i>"]:::ex
  E12 -.->|"example"| EX3

  %% ---------------- PROPOSED CHANGE 2 -------------------------------
  PROP2["<b>PROPOSED — normalize the mention surface before deriving keys</b><br/>Not yet built. This node inserts between E1 and E2.<br/><br/>Strip leading role and title tokens from the surface used for BLOCKING, while the stored mention surface and its char offsets stay exactly as extracted.<br/><br/><i>Model-agnostic, and it belongs here rather than in an extractor: the retired regex scanner had a version of this (_LEADING_NOISE), but as a corpus-fitted denylist inside extraction. The need was real; the location and the shape were wrong.</i>"]:::proposed
  E1 -.->|"proposed insertion point"| PROP2
  PROP2 -.-> E2

  PROP2B["<b>Measured evidence for it, this machine, GLiNER multi-v2.1</b><br/>Exact span-boundary agreement across casing regimes: <b>24/31 = 77%</b>. Recall was 100% in every regime — casing does not cost detections, it moves <b>boundaries</b>.<br/><br/>Observed disagreements:<br/>· 'adjuster Karen Wu' vs 'Karen Wu'<br/>· 'Claimant Deborah Fitzgerald' vs 'Deborah Fitzgerald'<br/>· 'SIU' found in mixed case, lost in BOTH ALL CAPS and lowercase<br/><br/><i>Role-word absorption also happens in MIXED case — 'Claimant Deborah Fitzgerald' was the normally-cased output — so this is not a casing bug. Casing only changes which words get absorbed.</i>"]:::ex
  PROP2 -.->|"why"| PROP2B

  PROP2C["<b>What it actually costs today</b><br/>Not invisibility. last_name = toks[-1], and role words are LEADING, so 'adjuster Karen Wu' and 'Karen Wu' both key to 'wu' and still meet under block_on(last_name).<br/><br/>But <b>three of eight blocking rules miss</b>:<br/>· full_name — 'adjuster karen wu' ≠ 'karen wu'<br/>· name_sorted — 'adjuster karen wu' ≠ 'karen wu'<br/>· soundex+first_name — first_name 'adjuster' vs 'karen'<br/><br/>and when the pair does meet, <b>ForenameSurnameComparison(first_name, last_name) scores it DOWN</b> because first_name disagrees.<br/><br/><i>So the real cost is a depressed match probability on true pairs, not a missing pair. That is a subtler failure than it first looked, and it degrades the calibration the whole threshold story rests on.</i>"]:::warn
  PROP2B -.-> PROP2C
```

### F — Assemble the global entity graph

Source: [`08-graph-assembly.mermaid`](08-graph-assembly.mermaid)

```mermaid
---
title: "F — Assemble the global entity graph"
---
flowchart TD
  classDef act  fill:#EDF0F4,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef obj  fill:#E0E8EF,stroke:#3E5C76,stroke-width:1.3px,color:#10151C
  classDef dec  fill:#FFFFFF,stroke:#4A5666,stroke-width:1.2px,color:#10151C
  classDef bar  fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF
  classDef bad  fill:#F6E0DB,stroke:#A33A2A,stroke-width:1.4px,color:#10151C
  classDef key  fill:#F6E7CE,stroke:#B4650A,stroke-width:1.6px,color:#10151C
  classDef muted fill:#FFFFFF,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:4 3,color:#4A5666
  classDef ex   fill:#FBFCFD,stroke:#B9C2CE,stroke-width:1px,stroke-dasharray:3 3,color:#33404F
  classDef warn fill:#FFF6E8,stroke:#B4650A,stroke-width:1.3px,stroke-dasharray:5 3,color:#3A2C16
  classDef term fill:#4A5666,stroke:#39424E,stroke-width:1px,color:#FFFFFF


  P0(["resolved entities + identifier observations"]):::term
  P1["<b>Emit a node per resolved entity</b><br/>kind: party | organization"]:::act
  P2["<b>Emit a node per distinct identifier value</b><br/>kind: identifier — first-class, not an attribute"]:::key
  P3["<b>Emit claim and occurrence container nodes</b><br/>kind: claim | occurrence"]:::act
  P4{"predicate allowed?"}:::dec
  P5["<b>Rejected: provenance-as-edge</b><br/>MENTIONED_IN / HAS_NOTE — already on every edge as doc_id + span"]:::bad
  P6["<b>Link entity → identifier</b><br/>HAS_IDENTIFIER, carrying confidence + doc_id + span"]:::act
  P7["<b>Link entity → claim, claim → occurrence</b><br/>PARTY_TO / PART_OF containment"]:::act
  P8["<b>Insert into ONE global adjacency</b><br/>claim_id is a node and edge property, not a partition"]:::key
  P9["<b>global entity graph</b><br/>claim scoping happens at query time, as a filter"]:::obj
  P10(["consumed by Layer 4 retrieval"]):::term

  P0 --> P1 --> P2 --> P3 --> P4
  P4 -->|"banned"| P5
  P4 -->|"open vocabulary, normalized"| P6 --> P7 --> P8 --> P9 --> P10

  PX1["<b>in</b> — identifier_observations value_norm='3125550148' seen on 3 claims<br/><b>out</b> — one identifier node, three HAS_IDENTIFIER edges from three different entities<br/><i>Promoting the identifier to a node is what makes the shared-phone pattern visible as graph structure instead of a repeated column value.</i>"]:::ex
  P2 -.->|"example"| PX1

  PX2["<b>in</b> — proposed edge entity → note, predicate MENTIONED_IN<br/><b>out</b> — rejected<br/><i>Provenance is already carried as doc_id + span on every real edge; adding it again as its own edge type inflates the graph without adding information.</i>"]:::ex
  P5 -.->|"example"| PX2

  PW["<b>Why the vocabulary stays open</b><br/>Only bulk provenance-as-edge is banned. Real predicates are freeform and normalized toward canonical forms over time — 'went to' / 'was seen at' / 'visited' consolidate — because a closed whitelist either drops relationships it never anticipated or force-fits them into the nearest allowed label, and both failures are invisible after the fact."]:::warn
  P4 -.->|"rationale"| PW
```
