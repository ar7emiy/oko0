# ADO Backlog: Entity Intelligence Evaluation Benchmark

*Work-item descriptions, acceptance criteria and a sequenced development breakdown, written so they can be pasted into Azure DevOps and handed to a developer with no prior context.*

**Source of truth:** [Entity Intelligence: Evaluation Benchmark and SME Review Platform](ENTITY-INTELLIGENCE-EVALUATION-PROPOSAL.md). References written **REQ-B7** or **REQ-E3** point at the requirement catalogue in that paper's Part 3 §10.1. Every acceptance criterion here traces back to one, so a reviewer can always ask *which requirement does this serve* and get an answer.

**Do not confuse the two ID schemes.** Story IDs below (A1, C6, F3 …) are work items in section 3. Requirement IDs always carry the **REQ-** prefix. They overlap numerically and mean different things.

**Assumption for the development breakdown:** the annotator is built from scratch. If the §10.7 trial selects an adopt or hybrid path, Features C and D below shrink substantially and Feature K (integration) replaces them — the requirements and acceptance criteria do not change, only who satisfies them.

**On estimates:** sizes below are **relative indications only** (S ≈ a day or two, M ≈ up to a week, L ≈ more than a week for one developer). They are a starting point for planning poker, not a commitment. The team sizes their own work.

---

## 1. Do the seven tickets fit the effort?

**They cover roughly 60% of it.** The shape is right — discovery before build, build before SME work, QA before analysis — and the seven map cleanly onto real workstreams. What is missing is mostly **data engineering** and **definitional** work that has no owner in the current set, and every one of those gaps is on the critical path.

### What the seven tickets cover well

| Your ticket | Covers | Proposal reference |
|---|---|---|
| Requirements critique + sponsor approval | Phase 0 alignment and scope sign-off | §9 Phase 0 |
| Discovery: golden notes + claims scope | Sampling design, quality bands | Part 2 §1 |
| Discovery: schema contract | The logical model and its physical form | Part 2 §2.1, §11 Data architects |
| Annotator workbench development | The reviewer-facing platform | §10.1 groups A–I, §11 Web developers |
| QA: UX/UI and data output validation | Verification of the above | §11, H5–H6 |
| SME evaluation of notes | Building the answer key | Part 2 §3 |
| Analysis against golden dataset | Scoring and the scorecard | Part 2 §4–§7, Part 4 |

### What is missing, and why each one matters

| # | Gap | Why it is on the critical path | Suggested ticket |
|---|---|---|---|
| 1 | **Data intake and point-in-time snapshot pipeline** | The annotator cannot be fed without it. Notes must be assembled per claim, fingerprinted, frozen at a cutoff, and reconciled against the system extract. This is a data-engineering workstream with no ticket. | *Data intake, snapshot and reconciliation pipeline* |
| 2 | **Confirm the meaning of the current system's output** | Three questions must be answered in writing by the data owners before any counting logic is written: what a repeated row means, whether the candidate export is complete, and the snapshot and watchlist versioning. Getting this wrong produces confident, wrong headline numbers. Risk #3 in the proposal. | *Discovery: system extract semantics and completeness* |
| 3 | **Definitions: categories, quality bands, value equivalence** | The scope discovery ticket covers *which* claims. It does not cover the category taxonomy, the note-quality band definitions, or the rules for when two differently formatted values are equal. SMEs cannot annotate consistently without the first two; scoring cannot run without the third. | *Definitions: taxonomy, quality bands, value-equivalence rules* |
| 4 | **SME onboarding, guidelines and adjudication process** | Your SME ticket is the *doing*. The guideline document, reviewer training, the double-annotation plan and the adjudication process are prerequisites, and reviewer agreement is the measure of whether the answer key is trustworthy at all. | *SME annotation guidelines, training and adjudication process* |
| 5 | **Benchmark release packaging and versioning** | H1–H3: binding a published release to exact record revisions so a later correction cannot silently change a published score, and so a second person can re-run to identical numbers. Without it there is no re-runnable benchmark, only a one-off report. | *Benchmark release packaging and reproducibility* |
| 6 | **Watchlist data access and the missed-match audit** | The below-threshold review and the independent audit both need watchlist access. If that request is not raised early it will block the most valuable half of the watchlist analysis. Risk #5. | *Watchlist access and independent missed-match audit* |
| 7 | **Environment and data-governance approval** | Not a delivery ticket — a PM-tracked dependency. Whether real notes can be annotated, and where, determines the Phase 1 start date more than any engineering decision. §12. | Track as a dependency/impediment, not a story |

### Sequencing problems in the current set

- **The seven are listed flat.** Three of them are hard blockers for the others. The development ticket cannot start meaningfully before the schema contract is agreed; SME evaluation cannot start before development and guidelines; analysis cannot start before SME evaluation produces frozen claims.
- **"SME evaluation of notes" is not a ticket, it is an ongoing workstream.** It runs for as long as the benchmark is being built and its throughput is the programme's rate limit. Model it as an epic with per-batch child items so progress is visible, rather than one ticket that sits at *In Progress* for months.
- **The build-or-adopt trial is missing and should precede development.** §10.7 defines a two-to-three day trial with a decision rule agreed in advance. Running it inside the requirements-critique ticket is reasonable; skipping it is not, because it determines how much of the development ticket exists at all.

### Recommended board shape

```text
EPIC  Entity Intelligence Evaluation Benchmark
├── FEATURE  Phase 0 — Align and unblock
│   ├── Annotator Workbench requirements critique + sponsor approval   ← your #1
│   ├── Discovery: optimal golden notes + claims scope                 ← your #6
│   ├── Discovery: annotation workbench data schema contract           ← your #7
│   ├── Discovery: system extract semantics and completeness           ← NEW (gap 2)
│   ├── Definitions: taxonomy, quality bands, equivalence rules        ← NEW (gap 3)
│   └── Build-or-adopt trial (§10.7)                                   ← NEW, or fold into #1
├── FEATURE  Data foundation
│   ├── Data intake, snapshot and reconciliation pipeline              ← NEW (gap 1)
│   └── Benchmark release packaging and reproducibility                ← NEW (gap 5)
├── FEATURE  Annotator Workbench application development               ← your #3
│   └── (Features A–J below)
├── FEATURE  Quality assurance
│   └── QA: annotator workbench UX/UI and data output validation       ← your #4
├── FEATURE  SME operations
│   ├── SME annotation guidelines, training and adjudication           ← NEW (gap 4)
│   └── SME evaluation of notes via annotator workbench                ← your #2
└── FEATURE  Analysis and reporting
    ├── Analysis against golden dataset                                ← your #5
    └── Watchlist access and independent missed-match audit            ← NEW (gap 6)
```

---

## 2. Your seven tickets — descriptions and acceptance criteria

### 2.1. Annotator Workbench App requirements critique, sponsor approval

> **You said you were not sure what this entails.** Here is what it is for, and it is arguably the highest-value ticket on the board: **it is the gate that stops us building the wrong thing.** We have a written requirement set (§10.1, 55 requirements in nine groups). Nobody has yet challenged it, prioritized it, or agreed to pay for it. This ticket does those three things and produces a signed scope.
>
> Concretely it answers four questions: *Are these the right requirements? Which are must-have versus later? Do we build or adopt? Does the sponsor approve the resulting scope?* Without it, development starts from a document nobody has agreed to, and the first demo becomes the requirements review — which is the most expensive time to have it.

**Type:** Feature / Enabler
**Size:** M

**Description**

As the Product Owner, I need the annotator workbench requirement set challenged by the people who will use, build and pay for it, and the resulting scope approved by the sponsor, so that development starts from an agreed baseline rather than an unreviewed proposal.

The requirement catalogue in the evaluation proposal (Part 3 §10.1, groups A–I) is the input. This ticket walks that catalogue with SMEs, engineering, data architecture and the sponsor; records challenges and changes; classifies every requirement as Must / Should / Could / Won't for the first release; incorporates the outcome of the build-or-adopt trial; and obtains written sponsor approval of the resulting scope.

**Acceptance criteria**

1. Every requirement in §10.1 (A1–I4) has a recorded disposition: **confirmed as written**, **amended** (with the amended text), or **removed** (with the reason).
2. Every retained requirement carries a MoSCoW classification for release 1, agreed by the PO and SME lead.
3. SMEs have reviewed the reviewer-facing requirements (groups A–D, F) against how they actually work, and their challenges are recorded with a disposition each.
4. Engineering has flagged any requirement they consider technically expensive or ambiguous, and each flag has a recorded resolution.
5. The build-or-adopt trial (§10.7) has been run and its findings recorded against the pre-agreed decision rule; the platform decision is written down with its reasoning.
6. Requirements that depend on an unresolved external decision — data governance, environment, watchlist access — are listed explicitly as scope assumptions rather than silently assumed.
7. The sponsor has approved the resulting scope in writing, including what is explicitly deferred.
8. Every Phase 0 decision-log item due before development has a written outcome (proposal §14).

**Definition of done:** an approved requirements baseline document exists, is linked from this ticket, and is the reference every development story traces to.

**Dependencies:** none. This is the first ticket.

---

### 2.2. Discovery: optimal golden notes + claims scope for SME eval

**Type:** Feature / Spike
**Size:** M

**Description**

As the Data Scientist and Product Owner, we need an agreed, documented sampling plan for the claims and notes that will form the benchmark, so that results are defensible, comparable between subgroups, and honest about what population they describe.

Covers: how many claims, spread across which coverage groups and note-quality bands; the supplementary sample of claims where the current system found nothing; the rule that keeps claims sharing notes or identities from spanning the development and held-out collections; and documented selection probabilities wherever review will be sampled rather than exhaustive.

**Acceptance criteria**

1. A target sample size per coverage group is agreed and its rationale recorded, including what it does and does not support statistically.
2. Note-quality bands are defined (in coordination with the definitions ticket) and the sample allocation across them is agreed, with any departure from equal allocation recorded before selection.
3. Note volume is captured as a separate variable from note quality.
4. The plan includes a supplementary sample of claims where the current system returned no entities, and states that portfolio-wide claims cannot be made without it.
5. A grouping rule is defined that prevents claims sharing source notes or confirmed identities from appearing in both the development and held-out collections.
6. Where review will be sampled rather than exhaustive, selection probabilities are documented so weighted estimates are possible later.
7. The plan states explicitly which population the results will describe, and which they will not.
8. A pilot subset is identified for Phase 1 — small, but including at least one high-note-volume claim, because the easy cases mislead.

**Definition of done:** a written sampling plan, approved by PO and Data Scientist, sufficient for a data engineer to execute selection without further interpretation.

**Dependencies:** needs note-quality band definitions from the definitions ticket. Can start in parallel and converge.

---

### 2.3. Discovery: annotation workbench data schema contract

**Type:** Feature / Spike
**Size:** L

**Description**

As the Data Architect, I need the logical information model in the evaluation proposal (Part 2 §2.1) turned into an agreed physical schema contract, so that the application, the intake pipeline and the scoring layer all write and read the same shapes, and so that a later environment change does not force a redesign.

This is the **single most important blocker for development.** Nothing in Feature A of the development breakdown can be built without it.

**Acceptance criteria**

1. Every logical record in Part 2 §2.1 maps to named physical tables, with primary keys, foreign keys and constraints specified.
2. **Claim-scoping is enforced by constraint, not convention**: evidence and claim-local ownership cannot reference records outside their own claim.
3. An ownership decision with **no owner** is representable without violating any constraint — a nullable column plus a status value, not an absent row (**REQ-B7**).
4. Two supported owners for one value are representable as two separate decision records (**REQ-B8**).
5. The revision strategy is specified: every record carries reviewer, timestamp and revision; superseded decisions are retained and queryable; nothing is destructively overwritten (**REQ-G4**).
6. A benchmark release can bind to exact record revisions, so a later correction cannot alter a published score (**REQ-H1**).
7. The permitted SQL feature set is agreed so the same schema deploys to the local and target environments without structural change (**REQ-I2**).
8. Storage of sensitive identifiers (SSN, TIN) is specified: who can read them, any masking at rest, and retention and deletion rules (**REQ-I1**).
9. Original values and normalized values are separate columns; normalization carries a named version and never replaces the original (**REQ-B5**).
10. The contract is reviewed and accepted by the developer who will implement it — not handed over.

**Definition of done:** a schema contract document plus executable DDL, both reviewed by the implementing developer and the data engineer.

**Dependencies:** requirements critique (scope), and the environment decision for the portability constraint.

---

### 2.4. Annotator workbench application development

**Type:** Epic
**Size:** L

**Description**

As an SME reviewer, I need a purpose-built application in which I can read a claim's notes, record the people and organizations I find with the evidence that supports them, and later compare the current system's output against what I established — so that an independent answer key can be built and the benchmark can be scored.

The full breakdown is in section 3 below: ten features, sequenced so a walking skeleton exists early and each subsequent feature is independently demonstrable.

**Acceptance criteria (epic-level; each is decomposed in section 3)**

1. A reviewer can take one claim from raw notes to a frozen answer key without leaving the application or editing data by hand.
2. Every stored annotation carries its source note, exact character offsets, reviewer, timestamp and revision.
3. The evaluated system's output is unreachable by any route — UI or API — until the claim is frozen.
4. A detail can be saved with **Owner not established** and later assigned without losing the original decision.
5. Every identifier type survives entry and export with its exact original characters.
6. A complete claim's decisions export in the agreed schema, and re-exporting the same frozen claim produces identical output.
7. Two reviewers can annotate the same claim independently and their disagreements can be adjudicated with both judgments preserved.

**Dependencies:** schema contract (2.3), requirements critique (2.1). Blocks SME evaluation (2.6).

---

### 2.5. QA — annotator workbench UX/UI and data output validation

**Type:** Feature
**Size:** M

**Description**

As the Product Owner, I need independent verification that the workbench behaves as specified and that what it exports is fit for scoring, so that we do not discover data problems after SMEs have spent weeks annotating.

Two halves. **UX/UI validation**: can a reviewer who is not the developer complete a real claim without help, and where do they get stuck? **Data output validation**: does the export match the schema contract, preserve values exactly, and survive a round trip?

**Acceptance criteria**

1. A test plan exists covering every acceptance criterion in section 3, traced to its requirement ID.
2. An SME who did not participate in development completes a full claim end to end; every point of confusion is logged with severity.
3. **Blind-review isolation is tested adversarially**, including direct API access and any URL a curious reviewer might construct (**REQ-C1**).
4. Round-trip integrity is verified: values with leading zeros, masked identifiers, unicode and unusual whitespace export exactly as entered (**REQ-B5**).
5. Offsets in the export resolve back to the correct passage in the correct source note (**REQ-A3**).
6. Re-exporting the same frozen claim produces byte-identical output (**REQ-H3**).
7. Exported data loads into the scoring layer without manual correction.
8. Unassigned details and any excluded populations appear in the export and are visibly marked as excluded rather than silently dropped (**REQ-H5**).
9. Note-change detection is verified: a note altered mid-annotation stops further saves with a clear explanation (**REQ-A2**).
10. Access control is verified against the sensitive-data rules in the schema contract (**REQ-I1**).
11. Every defect is logged with severity, and release-blocking defects are agreed with the PO.

**Definition of done:** test plan executed, results recorded, blocking defects closed, PO sign-off to begin SME annotation at scale.

**Dependencies:** development features A–E at minimum.

---

### 2.6. SME — evaluation of notes via annotator workbench app

**Type:** Epic (ongoing workstream — see note below)
**Size:** L, continuous

> **Model this as an epic with per-batch child items,** not as a single ticket. It runs for the life of the benchmark build and its throughput is the programme's rate limit. A single ticket sitting at *In Progress* for three months tells the PM nothing; a batch per sprint tells them everything.

**Description**

As an SME reviewer, I need to work through the selected claims in the workbench, recording every person and organization I find with its supporting evidence, so that an independent answer key exists against which the current system can be measured.

Reviewers work **blind** — the current system's output is hidden until a claim is frozen. A defined subset is annotated independently by two reviewers so agreement can be measured and disagreements adjudicated.

**Acceptance criteria (per batch)**

1. Every claim in the batch reaches **frozen** status, or is recorded as blocked with a reason.
2. Every entity carries at least one piece of supporting evidence traceable to a passage in a source note.
3. Categories are assigned where evidence supports one; *insufficient evidence* is recorded explicitly where it does not, rather than guessed.
4. Details with no determinable owner are saved as unassigned with a reason, not omitted and not guessed (**REQ-B7**).
5. The agreed proportion of the batch is double-annotated, agreement is measured, and disagreements are adjudicated with both original judgments preserved (**G1–G3**).
6. Per-claim effort is recorded, so Phase 2 planning rests on measured hours rather than estimates.
7. Guideline ambiguities encountered during the batch are logged and fed back into the guideline document.

**Tracking measures (report weekly):** claims frozen against plan; average SME hours per claim; proportion double-annotated and the agreement rate; open adjudications and their age; claims blocked on missing or mismatched source data.

**Dependencies:** application (2.4) through QA (2.5); guidelines and training (gap ticket 4); sampling plan (2.2); data intake (gap ticket 1).

---

### 2.7. Analysis against golden dataset — entity resolution and watchlist matching benchmark

**Type:** Feature
**Size:** L

**Description**

As the Data Scientist, I need the scoring implementation and the published scorecard, so that the business learns how completely and precisely the current system identifies parties and their details, and how well its watchlist matching separates genuine matches from noise.

Implements the formulas in the proposal's Part 4 and reports the metrics in Part 2 §4–§7. **The counting rules are where this goes wrong if rushed** — one-to-one matching, duplicate handling, and the rule that several watchlist candidates for one extraction do not inflate the extracted-entity count.

**Acceptance criteria**

1. Entity precision and recall are implemented per Part 4 §B, with each extraction and each reference entity contributing at most one match credit.
2. Duplicate extractions remain in the precision denominator and cannot generate additional match credits.
3. Several watchlist candidates for one extraction do not increase the extracted-entity count (**REQ-E3**).
4. Attribute precision, attribute recall and the false-negative rate are implemented per Part 4 §C.
5. Value precision, unsupported-value rate and **conditional attribution accuracy** are implemented and reported separately, so *wrong value* is distinguishable from *right value, wrong party*.
6. Watchlist precision, candidate-conditional recall, candidate-conditional false-positive rate and abstention rate are implemented per Part 4 §D.
7. Threshold analysis re-computes outcomes at alternative thresholds with SME identity judgments held fixed; historical and simulated results are reported separately and never combined.
8. Every published figure emits its numerator, denominator, scope and unresolved count (**REQ-H6**).
9. A zero denominator reports **not evaluable**, never 0%.
10. Pooled (micro) and mean-per-claim (macro) results are both reported, and a material divergence between them is flagged rather than left for a reader to notice.
11. Breakdowns by coverage group, client, note-quality band and note volume are produced (**REQ-H7**).
12. Scoring refuses to publish for any claim not marked complete — incomplete pairing otherwise looks like missed entities and understates recall.
13. Scoring the same frozen release twice produces identical numbers (**REQ-H3**).
14. The implemented counting rules have been checked against the agreed method by someone other than the implementer, before any number is published.

**Dependencies:** frozen claims from SME evaluation (2.6); release packaging (gap ticket 5); watchlist access for the below-threshold half (gap ticket 6).

---

## 3. Development breakdown

*Under the epic "Annotator workbench application development". Written for a developer joining cold: each story states what to build and what proves it works. Sequence matters — features are ordered so something demonstrable exists early and nothing is built on an unagreed foundation.*

**Build order principle.** Feature A is a walking skeleton: one claim, one note, one annotation, stored with full provenance, exported. It is deliberately thin and deliberately first, because it forces the schema, the audit trail and the export format to be real before any UI work depends on them.

### Feature A — Foundation and walking skeleton

**Goal:** a running application that can store one annotation with complete provenance and export it. Nothing else.

| ID | Story | Size |
|---|---|---|
| A1 | Project scaffold and local run | S |
| A2 | Core schema implementation | M |
| A3 | Revision and audit infrastructure | M |
| A4 | Reviewer identity and session | S |
| A5 | Walking-skeleton export | S |

---

**A1 — Project scaffold and local run**

*As a developer, I need a runnable project skeleton so that every later story has somewhere to land.*

**Acceptance criteria**
1. A single documented command starts the application and opens it in a browser.
2. The README states the runtime version, every dependency and why each is needed.
3. Configuration — storage location, port, source-data paths — is supplied at startup, not hard-coded.
4. The application starts with no network access available (**REQ-I1** — it must be deployable in a restricted environment).
5. A health endpoint returns application version and schema version.

*Tasks:* repo and structure · dependency decision per §11 · config handling · README · health endpoint.

---

**A2 — Core schema implementation**

*As a developer, I need the agreed schema implemented so that all storage matches the contract the data architect signed off.*

**Acceptance criteria**
1. DDL from the schema contract (ticket 2.3) is applied by a migration, not by hand.
2. Claim-scoping constraints are enforced by the database: evidence cannot reference a record in another claim, and a violation raises an error.
3. An ownership decision with no owner inserts successfully (**REQ-B7**).
4. Original and normalized value columns are separate; normalization carries a version (**REQ-B5**).
5. A migration mechanism exists and is documented — later stories will add tables.
6. Schema version is recorded and exposed by the health endpoint.

*Tasks:* migration framework · DDL · constraint tests · fixtures.

---

**A3 — Revision and audit infrastructure**

*As a reviewer, I need every decision recorded with who made it and when, and never silently overwritten, so that the answer key is auditable.*

**Acceptance criteria**
1. Every write records reviewer, UTC timestamp and revision number (**REQ-G4**).
2. Editing a decision appends a new revision; the previous revision remains readable.
3. No code path issues a destructive UPDATE or DELETE on a decision record — enforced by review and by test.
4. Any record's full revision history is retrievable.
5. Revision numbers are contiguous per record and gap-free.

*Tasks:* revision write path · history query · destructive-write test · document the pattern for later stories.

---

**A4 — Reviewer identity and session**

*As a reviewer, I need the application to know who I am so that my decisions are attributed to me.*

**Acceptance criteria**
1. A reviewer identifies themselves before any write is accepted.
2. Every record created in a session is attributed to that reviewer.
3. Switching reviewer does not reattribute existing records.
4. Identity handling matches the access-control approach agreed in the schema contract (**REQ-I1**).

---

**A5 — Walking-skeleton export**

*As a developer, I need an end-to-end export so that the output format is proven before features depend on it.*

**Acceptance criteria**
1. One claim with one annotation exports in the agreed schema.
2. Export includes reviewer, timestamp, revision and source offsets.
3. Re-exporting unchanged data produces byte-identical output (**REQ-H3**).
4. The export is loadable by the scoring layer's reader without manual correction.

**Feature A demo:** create a claim, record one annotation, export it, show the export resolving back to the source passage.

---

### Feature B — Source evidence intake

**Goal:** real claims and notes in the application, with integrity guarantees.

| ID | Story | Size |
|---|---|---|
| B1 | Note ingestion and claim assembly | M |
| B2 | Note integrity and change detection | M |
| B3 | Point-in-time snapshot binding | M |
| B4 | System extract import | L |

---

**B1 — Note ingestion and claim assembly**

*As a reviewer, I need every note belonging to a claim available together, so that I can see the whole claim.*

**Acceptance criteria**
1. All supplied notes for a claim are assembled into one unit of work (**REQ-A1**).
2. A claim supports many notes; the same note identifier can appear under several claims without the two being merged (**REQ-A1**).
3. Claim membership is determined by the agreed rule, independently of which notes the evaluated system cited (**REQ-A5**).
4. Note text is preserved exactly — encoding, line breaks and whitespace unchanged (**REQ-A2**).
5. Notes never cited by the evaluated system are present and indistinguishable in the reviewer's view (**REQ-A5**).
6. Ingestion is idempotent: re-running produces no duplicates.

---

**B2 — Note integrity and change detection**

*As a reviewer, I need the application to refuse work on a note that has changed, so that my recorded positions remain trustworthy.*

**Acceptance criteria**
1. A content fingerprint is recorded for every note at ingestion (**REQ-A2**).
2. The fingerprint is re-checked when a note is opened.
3. If a note has changed since annotation began, saves against it are refused with an explanation naming the note (**REQ-A2**).
4. Existing annotations on a changed note are retained and flagged, not deleted.
5. The condition is visible in the claim's status, not only at the moment of failure.

---

**B3 — Point-in-time snapshot binding**

*As the Data Scientist, I need a claim's evidence bound to a cutoff, so that the reviewer and the evaluated system are judged on the same material.*

**Acceptance criteria**
1. Each claim binds to a named snapshot with a cutoff date (**REQ-A4**).
2. Notes after the cutoff are excluded from the reviewer's packet and the exclusion is recorded.
3. The snapshot identifier appears in every export.
4. Where correspondence between the notes and the system's output cannot be established, the claim is marked **non-equivalent** with a reason and excluded from scoring rather than scored.
5. Two claims may belong to different snapshots without interfering.

---

**B4 — System extract import**

*As a reviewer, I need the evaluated system's output imported and linked to claims, so that it can be compared after freeze.*

**Acceptance criteria**
1. The extract imports with its fields mapped per the agreed mapping (**REQ-E1**).
2. Multi-value citation cells split into individual note references (**REQ-E1**).
3. Spreadsheet numeric artifacts resolve correctly — a value rendered `1234567890.0` locates note `1234567890` — while the original value is preserved unchanged in storage and export (**REQ-E1**).
4. Leading zeros survive import (**REQ-B5**).
5. Each citation resolves only within its own row's claim; unresolvable citations are recorded as *not supplied for this claim* rather than dropped.
6. Result types are classified per the agreed semantics (extraction versus watchlist activity) and misclassification is impossible to introduce silently — an unknown type fails the import loudly (**REQ-E3**).
7. Imported data is stored separately from reviewer data and joined only through explicit comparison records.
8. **Imported output is not readable through any interface until the claim is frozen** (**REQ-C1**) — see D1.

*Dependency:* requires the extract-semantics discovery ticket (gap 2). Do not write the classification logic before those answers are in writing.

---

### Feature C — Claim annotation

**Goal:** the core reviewer experience. This is the heart of the application.

| ID | Story | Size |
|---|---|---|
| C1 | Claim workspace and note navigation | M |
| C2 | Text selection and offset capture | M |
| C3 | Claim entity roster | M |
| C4 | Cross-note evidence attachment | M |
| C5 | Typed detail capture | L |
| C6 | Ownership decisions | L |
| C7 | Evidence roles and repetition | M |
| C8 | Category decisions | M |
| C9 | Actions and participants | M |
| C10 | Claim dossier | L |
| C11 | Freeze | M |

---

**C1 — Claim workspace and note navigation**

*As a reviewer, I need to move between a claim's notes without losing my place or my working context.*

**Acceptance criteria**
1. All notes for the claim are listed with an indication of which have annotations.
2. Opening a note preserves the claim context — the roster stays visible (**REQ-B1**).
3. Note text renders with original line breaks and whitespace.
4. Long notes are navigable; the reviewer can find their previous position.
5. Per-claim progress is visible: notes reviewed, entities recorded, outstanding items.

---

**C2 — Text selection and offset capture**

*As a reviewer, I need my highlighted passage stored exactly, so that every fact traces to its source.*

**Acceptance criteria**
1. Selecting text captures start and end character offsets, counted in Unicode characters from zero, end exclusive (**REQ-A3**).
2. The stored offsets resolve back to the identical passage.
3. Selection works across line breaks and around punctuation.
4. The stored quote and the note fingerprint are retained together (**REQ-A2**).
5. Overlapping selections are permitted — two facts may share text.

---

**C3 — Claim entity roster**

*As a reviewer, I need one running list of the parties in this claim, available while reading any note.*

> **This is REQ-B1, and it is the single most important interaction in the application.** Notes are read sequentially; parties accumulate across them. If the roster is not continuously available and editable, the reviewer is forced to remember or re-derive it, and the workflow fails on exactly the long claims that matter most.

**Acceptance criteria**
1. The roster persists across every note in the claim and is visible while reading any of them (**REQ-B1**).
2. A party can be created while reading any note.
3. Party types include person, organization and other subjects including vehicles (**REQ-B2**).
4. A vehicle is never coerced into a person-shaped record (**REQ-B2**).
5. The roster is searchable and remains usable at realistic party counts — test with at least 30.
6. Each entry shows enough to disambiguate similar names at a glance.

---

**C4 — Cross-note evidence attachment**

*As a reviewer, I need to attach a passage from the note I am reading to a party I created while reading a different note.*

**Acceptance criteria**
1. A passage selected in note 31 can be attached to a party first created in note 4, **without leaving note 31** (**REQ-B3**).
2. The evidence records which note it came from; attaching it does not move it to the party's original note (**REQ-B3**).
3. Attaching to an existing party is at least as easy as creating a new one — otherwise reviewers will create duplicates.
4. A party's evidence list shows every passage with its source note.
5. Evidence can be detached, and detaching appends a decision rather than deleting the record (**REQ-G4**).

---

**C5 — Typed detail capture**

*As a reviewer, I need to record details with their correct type and exact value.*

**Acceptance criteria**
1. Supported types: address with components, phone, TIN, SSN, NPI, attorney bar number, VIN, and other with a required named scheme (**REQ-B4**).
2. The original string is preserved exactly — leading zeros, masking, partial values, spacing (**REQ-B5**).
3. Masked or partial values are explicitly marked as such rather than silently stored as complete.
4. Issuer or jurisdiction is captured where needed to interpret the value; a bar number retains its issuing state (**REQ-B6**).
5. Format validation is advisory only and never blocks saving — a malformed value in the notes is a fact about the notes.
6. Address components are stored individually **and** as a bundle, so component-level and whole-address comparison are both possible.
7. Any normalized form is stored beside the original with a normalization version, never replacing it (**REQ-B5**).

---

**C6 — Ownership decisions**

*As a reviewer, I need to record whose a detail is as a separate decision, including that I cannot tell.*

> **REQ-B7, and the one most likely to be built wrong.** The instinct is to model ownership as a foreign key on the detail. That conflates *no owner recorded yet* with *reviewer determined the owner cannot be established* — and the benchmark depends on telling those apart. Ownership is a decision record with a status, not a column.

**Acceptance criteria**
1. Ownership status is one of **assigned**, **owner not established**, or **disputed**, each with a reason and a reviewer (**REQ-B7**).
2. A detail saves successfully with *owner not established*, and no entity reference (**REQ-B7**).
3. Such a detail is retrievable in the claim dossier and in the export with its type, value and source intact (**REQ-B7**).
4. Assigning an owner later **appends** a new decision; the original unassigned decision remains readable (**REQ-B7**).
5. Undo restores the unassigned state as one coherent action — value, status and evidence together.
6. Where two owners are supported, two separate ownership decisions are held; the application never infers a merge (**REQ-B8**).
7. An assigned owner must be a party in the same claim — enforced by constraint.
8. Unassigned details appear in a claim-level collection so they can be resolved later.

---

**C7 — Evidence roles and repetition**

*As a reviewer, I need to record what each passage does, so that repetition is not mistaken for corroboration.*

**Acceptance criteria**
1. Every evidence link carries a role: **support**, **conflict** or **repetition** (**REQ-B10**).
2. Several passages can support one fact; all are retained (**REQ-B9**).
3. Three notes repeating one phone number produce one fact with three evidence links, not three facts (**REQ-B9**).
4. Conflicting evidence is recorded without forcing resolution.
5. Qualifications are retained: historical, disputed, and denied as distinct from confirmed (**REQ-B13**).

---

**C8 — Category decisions**

*As a reviewer, I need to classify each party against the agreed taxonomy, with evidence, or record that the evidence does not support one.*

**Acceptance criteria**
1. Categories come from a versioned taxonomy; the version is stored with the decision (**REQ-B11**).
2. **Insufficient evidence** is a first-class outcome, not an empty field (**REQ-B11**).
3. Supporting evidence can be linked to the category decision (**REQ-B11**).
4. Changing a category appends a decision and retains the previous one.
5. The taxonomy is configuration, not code — updating it does not require a release.
6. The distinction between a claim role and a general occupation is expressible.

---

**C9 — Actions and participants**

*As a reviewer, I need to record what happened and who was involved.*

**Acceptance criteria**
1. An action links two or more participants, each with a role (**REQ-B12**).
2. Negation is recorded: a denied visit is distinguishable from a confirmed one (**REQ-B12**, **REQ-B13**).
3. Time and attribution are captured where the notes support them (**REQ-B12**).
4. Source evidence links to the action.
5. More than two participants are supported without a workaround.

---

**C10 — Claim dossier**

*As a reviewer, I need to see every party with its assembled evidence so that I can check completeness before freezing.*

**Acceptance criteria**
1. The dossier lists every party with its details, categories, actions and evidence (**REQ-B14**).
2. Clicking any fact opens its supporting passage **in its source note, in context** (**REQ-B14**).
3. Unassigned details appear in their own claim-level section (**REQ-B7**).
4. Conflicting evidence is visibly flagged.
5. Per-party review status is shown, and required reviews are listed.
6. The dossier remains usable on a claim with many notes and many parties.

---

**C11 — Freeze**

*As a reviewer, I need to lock a completed claim so that later edits cannot silently change a published score.*

**Acceptance criteria**
1. Freeze is available only when required reviews are complete; unmet conditions are listed explicitly (**REQ-B15**).
2. Freezing records the exact revision of every record in the claim (**REQ-B15**, **REQ-H1**).
3. After freeze, annotation records are read-only; an attempted edit is refused with an explanation.
4. Freeze is the event that unlocks comparison (**REQ-C2**).
5. Unfreezing, if permitted at all, requires a recorded reason and produces a new answer-key version — it never mutates the frozen one.
6. A frozen claim exports identically on every subsequent export (**REQ-H3**).

**Feature C demo:** a full claim annotated from scratch and frozen, with cross-note attachment and an unassigned detail shown.

---

### Feature D — Blind review and workflow state

**Goal:** the integrity controls that make the answer key independent. **Small feature, disproportionate importance** — if blind review leaks, every claim annotated up to that point is compromised.

| ID | Story | Size |
|---|---|---|
| D1 | System output isolation | M |
| D2 | Claim state machine | M |
| D3 | Practice and training material | S |

---

**D1 — System output isolation**

*As the Product Owner, I need the evaluated system's output unreachable until a claim is frozen, so that the answer key is genuinely independent.*

**Acceptance criteria**
1. Before freeze, no UI route displays any imported system output for that claim (**REQ-C1**).
2. Before freeze, no API route returns it — including direct requests, guessed identifiers and any export (**REQ-C1**).
3. Isolation is enforced server-side. Hiding it in the client is not sufficient and will be tested adversarially.
4. After freeze, output becomes available **only** through the comparison views (**REQ-C2**).
5. Any attempt to access it before freeze is logged.
6. An automated test asserts isolation and fails the build if it regresses.

---

**D2 — Claim state machine**

*As a reviewer and as the PM, we need each claim's state visible and its transitions controlled.*

**Acceptance criteria**
1. States: **not started → in progress → reviewed → frozen → comparison in progress → comparison complete** (**REQ-C3**, **REQ-E5**).
2. Invalid transitions are refused with an explanation.
3. Comparison completion is tracked independently of annotation completion (**REQ-E5**).
4. State is queryable across all claims for progress reporting.
5. Every transition is recorded with reviewer and timestamp.
6. Blocked claims carry a reason.

---

**D3 — Practice and training material**

*As an SME lead, I need practice claims for training that never contaminate results.*

**Acceptance criteria**
1. Practice claims are clearly marked in the interface (**REQ-C4**).
2. Practice data is excluded from all scoring and export by default (**REQ-C4**).
3. Including it requires an explicit, visible opt-in.
4. Practice claims are independent — completing one does not prevent another reviewer using it.
5. Practice data contains no real claim or client information.

---

### Feature E — System comparison

**Goal:** the post-freeze comparison stage.

| ID | Story | Size |
|---|---|---|
| E1 | Result pairing | L |
| E2 | Detail-level comparison | L |
| E3 | Duplicate versus repeated presentation | M |

---

**E1 — Result pairing**

*As a reviewer, I need to pair each system result with the party I established, or record that it matches none.*

**Acceptance criteria**
1. After freeze, system results for the claim are listed beside the answer key (**REQ-C2**, **REQ-E2**).
2. Each result can be paired with one reference party, or marked **unsupported** or **unresolved**, with a reason (**REQ-E2**).
3. A reference party can receive at most one pairing credit; attempting a second pairing warns and records it as a duplicate finding (**REQ-E3**).
4. The answer key stays visible alongside the result being judged (**REQ-B14**).
5. Pairing decisions carry reviewer, timestamp and revision, and are revisable with history retained (**REQ-G4**).
6. Outstanding pairings are visible; completion requires every result decided.

---

**E2 — Detail-level comparison**

*As a reviewer, I need to say precisely how a reported detail is wrong.*

**Acceptance criteria**
1. For each reported detail the reviewer distinguishes **correct**, **wrong value**, **wrong owner**, **missing information** and **insufficient evidence** (**REQ-E4**).
2. *Wrong value* and *wrong owner* are separate outcomes and never collapsed — the metrics depend on this distinction.
3. The reported value, the reference value and the supporting evidence are shown together.
4. Value-equivalence rules from the definitions ticket are applied and the applied rule version is recorded.
5. A reviewer can override an automatic equivalence judgment, with a reason.
6. Details present in the answer key but absent from the system output are surfaced as omissions.

---

**E3 — Duplicate versus repeated presentation**

*As the Data Scientist, I need genuine duplicate extractions distinguished from one extraction shown several times.*

**Acceptance criteria**
1. Rows representing one extraction repeated across several watchlist candidates are grouped and counted once (**REQ-E3**).
2. Genuine duplicate extractions remain separate and are marked as duplication findings (**REQ-E3**).
3. Classification follows the agreed extract semantics; an unclassifiable case is flagged for adjudication rather than guessed.
4. The export makes the distinction explicit so scoring does not have to re-derive it.

---

### Feature F — Watchlist candidate review

**Goal:** identity judgments on watchlist candidates, above and below the alert threshold.

| ID | Story | Size |
|---|---|---|
| F1 | Candidate queue | M |
| F2 | Side-by-side identity review | L |
| F3 | Blind scoring and reveal | M |

---

**F1 — Candidate queue**

*As a reviewer, I need every candidate for a party queued for its own decision.*

**Acceptance criteria**
1. One extracted party may have many candidates, each requiring its own decision (**REQ-F1**).
2. Candidates that generated no alert are included, not only those that did (**REQ-F6**).
3. Candidate review completion is tracked separately from extraction review (**REQ-F1**, **REQ-E5**).
4. The queue supports working through candidates without losing position.

---

**F2 — Side-by-side identity review**

*As a reviewer, I need the claim evidence and the watchlist entry's attributes side by side so that I can judge identity on more than a name.*

**Acceptance criteria**
1. The watchlist entry's name, address, state, ZIP, phone and TIN are shown beside the claim party's evidence (**REQ-F2**).
2. Missing watchlist attributes display as **unknown**, never as a mismatch (**REQ-F2**).
3. Outcome is **same identity**, **different identity** or **insufficient evidence**, always with a reason (**REQ-F4**).
4. Matching method, historical alert decision and watchlist version are retained with the judgment (**REQ-F5**).
5. Decisions are revisable with history retained (**REQ-G4**).

---

**F3 — Blind scoring and reveal**

*As the Data Scientist, I need similarity scores hidden while identity is judged, then available for threshold analysis.*

**Acceptance criteria**
1. The similarity score and alert status are not displayed while the reviewer is making the identity judgment (**REQ-F3**).
2. Both are retained in storage throughout and appear in the export (**REQ-F3**, **REQ-F5**).
3. After the judgment is saved, both become visible for review (**REQ-F3**).
4. Missing or invalid scores remain visible as such and are never treated as below-threshold (**REQ-F5**).

---

### Feature G — Cross-claim identity review

**Goal:** identity linking across claims. **Schedule after the benchmark's first scorecard** unless priorities say otherwise — this is where a confident wrong answer does most damage.

| ID | Story | Size |
|---|---|---|
| G1 | Candidate group presentation | L |
| G2 | Identity decisions | M |
| G3 | Reversal and history | M |
| G4 | Item-focused views | M |

---

**G1 — Candidate group presentation**

*As a reviewer, I need candidate groups of parties shown together with the evidence that would settle whether they are the same.*

**Acceptance criteria**
1. A group shows each party's claim, names, identifiers, addresses, descriptions and actions side by side (**REQ-D1**).
2. Groups may be algorithmically suggested, but a suggestion is never an accepted link (**REQ-D1**).
3. Conflicting evidence is displayed, not hidden (**REQ-D1**).
4. A sample drawn from **outside** the suggested groups can be reviewed, so links never suggested can be measured (**REQ-D5**).

---

**G2 — Identity decisions**

*As a reviewer, I need to decide same, different or insufficient evidence, with my reasoning recorded.*

**Acceptance criteria**
1. Outcome is **same / different / insufficient evidence**, with supporting evidence and a reason (**REQ-D2**).
2. **Accepting a link never overwrites either claim-local party** (**REQ-D4**) — this is a hard constraint, not a preference.
3. A shared address or phone number alone does not pre-populate a same-identity decision (**REQ-D2**).
4. Decisions carry reviewer, timestamp and revision (**REQ-G4**).

---

**G3 — Reversal and history**

*As a reviewer, I need to reverse an identity decision with the original preserved.*

**Acceptance criteria**
1. Any accepted link can be reversed with a recorded reason (**REQ-D3**).
2. The original decision remains readable after reversal (**REQ-D3**, **REQ-G4**).
3. Reversal does not delete or alter the underlying claim-local parties (**REQ-D4**).
4. A link's full decision history is retrievable.

---

**G4 — Item-focused views**

*As a reviewer, I need to review shared addresses and identifiers without merging the parties that share them.*

**Acceptance criteria**
1. An address-focused view shows equivalent expressions of one address and the parties associated with each (**REQ-D6**).
2. An identifier-focused view does the same for identifiers (**REQ-D6**).
3. **Neither view offers a merge action** (**REQ-D6**).
4. Navigation from an item back to each party's claim evidence is available.

---

### Feature H — Quality control

| ID | Story | Size |
|---|---|---|
| H1 | Multi-reviewer assignment | M |
| H2 | Adjudication workflow | L |
| H3 | Agreement measurement | M |

---

**H1 — Multi-reviewer assignment**

*As an SME lead, I need two reviewers to annotate the same claim independently.*

**Acceptance criteria**
1. A claim can be assigned to several reviewers, each producing an independent answer key (**REQ-G1**).
2. **Reviewers cannot see each other's work while annotating** (**REQ-G1**).
3. Each reviewer's records are attributed and separable (**REQ-G4**).
4. Each reviewer freezes their own answer key independently.

---

**H2 — Adjudication workflow**

*As an adjudicator, I need to resolve disagreements with both original judgments preserved.*

**Acceptance criteria**
1. After both reviewers freeze, differences are surfaced: parties found by one and not the other, differing details, differing ownership, differing categories (**REQ-G2**).
2. The adjudicator records a resolution with a reason (**REQ-G2**).
3. **Both original judgments remain readable after adjudication** — neither is overwritten (**REQ-G2**).
4. The adjudicated result is identifiable as the authoritative version for scoring.
5. Open adjudications and their age are queryable for progress reporting.

---

**H3 — Agreement measurement**

*As the Data Scientist, I need reviewer agreement measured so that answer-key reliability is known.*

**Acceptance criteria**
1. Agreement is computed over double-annotated claims for entities, details, ownership and categories (**REQ-G3**).
2. Each measure reports its numerator and denominator (**REQ-H6**).
3. Annotation overlap is reported separately from agreement about ownership or identity, and is labelled as a diagnostic — overlap is easy to measure and easy to over-interpret.
4. Results export for reporting.

---

### Feature I — Export, packaging and audit

| ID | Story | Size |
|---|---|---|
| I1 | Full decision export | M |
| I2 | Benchmark release packaging | L |
| I3 | Audit traceability | M |

---

**I1 — Full decision export**

*As the Data Scientist, I need every decision exported in the agreed schema.*

**Acceptance criteria**
1. Export covers entities, evidence, details, ownership decisions, categories, actions, comparison decisions, watchlist judgments and identity decisions (**REQ-I3**).
2. Every record carries reviewer, timestamp, revision and source references (**REQ-G4**).
3. Unassigned details and excluded populations are exported and **visibly marked as excluded** (**REQ-H5**).
4. Original values are unchanged; normalized values appear separately with their version (**REQ-B5**).
5. Re-exporting unchanged data produces byte-identical output (**REQ-H3**).
6. Practice data is excluded unless explicitly opted in (**REQ-C4**).

---

**I2 — Benchmark release packaging**

*As the Data Scientist, I need a versioned release that can be re-scored to identical numbers.*

**Acceptance criteria**
1. A release binds to the exact record revisions it contains (**REQ-H1**).
2. A later correction produces a new release; **it cannot alter a published one** (**REQ-H1**).
3. The release manifest lists source snapshot, rule versions, taxonomy version and normalization version.
4. Development and held-out collections are separable, with the grouping rule applied so shared notes or identities do not span them (**REQ-H2**).
5. Re-running scoring against a release produces identical numbers (**REQ-H3**).
6. The manifest is sufficient for someone uninvolved to reproduce the scorecard (**REQ-I4**).

---

**I3 — Audit traceability**

*As an auditor, I need to trace any published figure back to the decisions and passages behind it.*

**Acceptance criteria**
1. From any counted item, the decisions that produced it are retrievable (**REQ-I4**).
2. From any decision, the supporting passages and their source notes are retrievable (**REQ-I4**).
3. Superseded decisions are reachable, not only current ones (**REQ-G4**).
4. The trace works for a released benchmark even after later corrections (**REQ-H1**).

---

### Feature J — Non-functional

| ID | Story | Size |
|---|---|---|
| J1 | Access control and sensitive data | M |
| J2 | Storage portability | M |
| J3 | Undo | M |

---

**J1 — Access control and sensitive data**

**Acceptance criteria**
1. Access to notes and annotations follows the agreed model; unauthorized access is refused and logged (**REQ-I1**).
2. SSN and other sensitive identifiers are stored per the schema contract, including any masking at rest (**REQ-I1**).
3. Retention and deletion rules are implemented (**REQ-I1**).
4. The application runs with no outbound network access (**REQ-I1**).

**J2 — Storage portability**

**Acceptance criteria**
1. Only the agreed SQL feature set is used (**REQ-I2**).
2. Data access sits behind a thin abstraction, so the storage engine can change without touching feature code (**REQ-I2**).
3. The same schema deploys to local and target environments without structural change (**REQ-I2**).
4. A migration path is documented and exercised at least once.

**J3 — Undo**

**Acceptance criteria**
1. A reviewer can undo their most recent action.
2. Undo restores compound state as one coherent action — an ownership change restores value, status and evidence together (**REQ-B7**).
3. Undo appends a decision; it does not delete history (**REQ-G4**).
4. Undo is unavailable after freeze.

---

## 4. Sequencing

**Critical path:** requirements critique → schema contract → Feature A → Feature B → Feature C → QA → SME annotation → analysis.

| Sprint-ish | Development | In parallel |
|---|---|---|
| 1 | — (blocked) | Requirements critique; schema contract; extract semantics; definitions; build-or-adopt trial |
| 2 | Feature A (walking skeleton) | Sampling plan; intake pipeline design; SME guidelines v1 |
| 3 | Feature B (intake) | Intake pipeline build; SME training material |
| 4–5 | Feature C (annotation) | Pilot claim selection; reviewer recruitment |
| 6 | Feature D + QA round 1 | SME training on practice claims |
| 6+ | — | **SME annotation begins on pilot claims** |
| 7 | Feature E (comparison) | Scoring implementation starts |
| 8 | Feature F (watchlist) | Watchlist access confirmed; below-threshold review |
| 9 | Features H, I | Release packaging; pilot scorecard |
| 10+ | Feature G (cross-claim) | Full scorecard; Phase 3 scope |

*Sprint numbers are ordinal, not calendar. Real dates depend on committed SME hours and on when the environment and data-access decisions land — both are outside the development team's control and both are PM-tracked impediments.*

**Three rules for the board**

1. **Nothing in Feature A starts before the schema contract is agreed.** A rewritten storage layer costs more than the wait.
2. **SME annotation does not begin at scale before QA round 1 passes.** Discovering an export defect after 40 claims are annotated is the most expensive failure available on this programme.
3. **No scoring number is published before the counting rules have been checked against the agreed method by someone other than the implementer.**

