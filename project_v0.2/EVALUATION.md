# Evaluating GOKO’s entity extraction and watchlist matching

This study will compare GOKO’s results and successive versions of our system against the same independently reviewed claim evidence. Subject-matter experts (SMEs) will establish which people and organizations the evidence identifies, what it states about them, and whether proposed watchlist matches represent the same real-world entity. This reference is the **answer key**, or gold data.

We need two complementary reviews: **complete claims first**, then **entities and items across claims**. The first measures what a system can establish within a claim. The second measures whether it joins evidence across claims correctly. Neither should silently change the scope of the other.

This document separates the proposed benchmark from the current annotation app. It specifies required information without prescribing a database or export layout. A **reported entity** means a person or organization a system says it identified; a **reported detail** means a value it assigns to an entity; a **watchlist candidate** means a proposed pairing between an identified entity and a particular watchlist entry. These are different evaluation units.

## 1. Select and freeze the benchmark material

We will endeavor to identify claims for which GOKO has already identified entities, freeze all their notes at a stated cutoff, and capture the corresponding GOKO results. We will also seek newer claims with less overall note volume, drawn from a variety of clients and multiple coverage groups.

The final claim count has not been agreed. **At least 100 distinct claims per coverage group is the proposed bare minimum**, with equal representation across agreed note-taking-quality bands. SMEs must recommend how to define those bands and the optimal distribution; any departure from equal allocation should be documented before selection. Quality should consider clarity, completeness, ambiguity and copied text, not just note length. Record client, coverage, claim age, note count and quality band for subgroup analysis.

This is a planning floor, not a guarantee of statistical precision or sufficient watchlist positives. Rare errors and coverage/client subgroups may need more material. Selecting only claims where GOKO found entities conditions the benchmark on GOKO’s success at finding something. Report that selection explicitly; add a separately tracked sample with no GOKO-identified entities before claiming portfolio-wide performance.

Each benchmark release must retain:

- Complete original note contents, claim-to-note associations, source IDs, version fingerprints, dates where available and the exact input cutoff. A repeated note ID across claims does not make their claim contexts identical.
- An immutable copy of GOKO’s corresponding entity, detail, category and watchlist results, including below-threshold candidates when available, export time, processing cutoff and run/configuration identifiers where available.
- The relevant watchlist contents and version, matching rules, thresholds and category restrictions. Record missing information rather than reconstructing it from a score alone.
- The SME answer-key version, review/adjudication history, category definitions, normalization rules, eligibility decisions and evaluation implementation version.

The notes GOKO actually processed must correspond to the frozen note version. An export taken today may reflect a different cutoff. Reconcile that before scoring, rerun GOKO on the frozen material if possible, or mark the comparison non-equivalent; do not present it as a fair head-to-head benchmark.

Each system version receives the same permitted inputs and cutoff. Claim-only systems are compared on claim-only evidence. Experiments adding other claims, external information or a different watchlist are reported separately. Archive each new system’s predictions before exposing its errors to developers.

Use a development benchmark for iterative improvement and a separate held-out benchmark for final claims of improvement. Repeatedly tuning against the same test answers makes them development data. Shared source notes and confirmed cross-claim identities should be grouped to prevent leakage between partitions; report the resulting number of independent groups. Group-separated evaluation is the relevant principle, not a random split of individual annotations. [Reference: grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html#group-k-fold).

Answer-key corrections require a new version and rescoring both GOKO and our system against it. Retain earlier results; never improve only one comparator’s labels after inspecting its mistakes.

## 2. Review complete claims, then entities across claims

### First pass: all notes within one distinct claim

An SME reads every frozen note belonging to the claim, with GOKO’s predictions hidden. They record entities, references, details, descriptions and actions, retaining sources and uncertainty. Notes enter the packet because they belong to the claim, not because GOKO cited them.

When information is scattered across notes, the SME adds each new piece to the existing **claim-level entity**. For example, note 1 names a clinic, note 2 gives its address and note 3 reports its phone number. These belong together if the notes establish the same clinic. The SME need not copy evidence into note 1 or create another clinic.

**Already possible in the app:** open the later note, select its source passage, choose Detail, Description, Action or Another mention, and select the entity already created in that claim. The claim evidence review gathers those annotations across notes. The SME then reviews the complete claim, resolves omissions and ownership errors, assigns supported categories or an unresolved outcome, and freezes the answer key.

Preserve reported speech, negation, disputed facts and time qualifiers. “The claimant denied visiting the clinic” is not a confirmed visit. A clinic’s address is not automatically its doctor’s address. Repeated copied text is not independent corroboration. Distinguish what a note states from independently verified truth.

### Second pass: entity and item review across completed claims

We recommend a separate review after claim annotation, using candidate groups of claim-level entities and associated details, addresses, descriptions and actions. This avoids global identity decisions based on partly read claims and preserves the original claim-only benchmark.

Candidate grouping can use identifier agreement, name variants, address components and combinations of evidence. It proposes comparisons for SMEs; it does not establish identity. Common addresses, phone numbers and categories can be shared by unrelated entities. Conflicting identifiers and temporal changes remain visible. Neither similarity nor a chain of suggested links proves a merge.

For each proposed link the SME chooses **same**, **different** or **cannot determine**, cites evidence and records a reason. Review contradictory links before accepting a group. Preserve original claim identities and accepted, rejected and reversed decisions. Review a sample outside proposed groups to assess identities the algorithm missed; candidate-only review cannot establish overall linking recall.

The combined entity review shows accepted claim associations and their evidence. It must distinguish **supported in this claim** from **known only from another claim**. A phone number in claim B does not mean GOKO should have extracted it from claim A. Cross-claim information cannot retroactively remove a claim-only miss or justify an unsupported claim-only prediction.

Item review is related but distinct: group equivalent addresses to check normalization and attribution without merging everyone associated with an address. Preserve address bundles so a street from one location cannot be combined with another location’s city or ZIP. Actions retain participants, relationship, source, timing and qualifications rather than becoming an unqualified list of things an entity did.

**Not yet implemented:** cross-claim review queues, candidate grouping, accepted global identities, relationship adjudication and global-identity scores. These are proposed additions. Gold corrections discovered here follow the answer-key versioning rule above.

For an independent cross-claim benchmark, complete this identity adjudication before revealing either evaluated system’s identity predictions. Keep candidate-generation provenance and audit unproposed links so the grouping tool does not silently define the answer key. If GOKO does not produce cross-claim identities, report this as a separate capability evaluation of our system, not a missing-output penalty in the common GOKO benchmark.

## 3. Information required for each comparison

These are information requirements, not assumed tables. A spreadsheet, relational database or another representation is acceptable if it preserves the associations unambiguously.

| Component | GOKO / evaluated system must provide | SME reference must provide |
|---|---|---|
| Entity identification | Claim association, each separately asserted identity, names/aliases, type, source-note IDs if available, output version, and a way to distinguish repeated reports from distinct predictions | All in-scope entities in the complete claim, supported aliases, type, evidence, unresolved references and completeness confirmation |
| Entity alignment | Identity/context information sufficient to distinguish namesakes and duplicates; split or merged predictions must remain visible | Reviewed association to a gold entity, unsupported prediction, ambiguous alignment or explicit split/merge assessment |
| Details and ownership | Detail kind and raw value, predicted owner, and which components belong together; preserve multiple values | Supported values, kind, owner or unresolved owner, address grouping, source, and temporal, negated, reported or conflicting status |
| Categories | Predicted category and definitions/version, including whether it means a claim role or occupation | Independently assigned claim role or insufficient/conflicting evidence under the agreed taxonomy |
| Watchlist identity | Identified entity, particular watchlist entry/ID, method, similarity if available, actual flag decision, cutoff/rules, candidate availability and watchlist version | Same/different/cannot-determine identity decision, evidence and reason for that candidate pair |
| Cross-claim identity | Proposed links or global group membership and permitted claims/evidence | Adjudicated same/different/unknown links and group membership with supporting and conflicting evidence |
| Actions and relationships | Participants and roles, action/relation, context, time, negation and attribution if the system claims to extract them | Equivalent sourced statement and qualifications, not merely matching participant names |

GOKO’s supplied headers provide claim IDs, entity/detail fields, categories, note citations, watchlist entries and similarity values. They do **not** establish stable extraction identity, address-history grouping, complete candidate-search coverage, source/run timing or the complete watchlist. GOKO must clarify these semantics. In particular, confirm whether `Entity`, `GenAI_only` and `Exact_search` are separate extraction assertions, candidate results or repeated representations of one entity. An exact watchlist-name hit must not automatically count as a separate extracted entity.

`GenAI_Note_ID` can cite several notes for a cleaned entity name. It identifies possible source documents, not which note supports each detail or whether the name is globally unique. The importer splits citations and removes numeric `.0` artifacts for lookup while retaining supplied values.

### When relationships need graph-like meaning

A list of entities with one address each cannot represent multiple owners, time-qualified addresses, statements about several parties or competing identity links. Those cases require explicit associations carrying participants, roles, provenance, time and decision status. A network view can help SMEs inspect them; graph traversal can support discovery and consistency checks.

**No graph database is required by these metrics.** Relational association records can represent the same information, including a statement with several participants and evidence passages. Use a graph representation when it makes the network easier to inspect or query; it supplies no additional truth. Core claim entity/detail metrics need sets, attributes and reviewed alignments. Identity-link and action evaluation need explicit relationships. A storage decision follows those requirements, rather than defining them.

## 4. Turn the available material into a detail benchmark

1. Freeze the claim packet and GOKO export together; reconcile claim/note associations and missing inputs before interpreting absence as an error.
2. Build and independently review the complete claim answer key. Agree eligible detail kinds and statement statuses. Do not convert unresolved ownership or conflicting evidence into a guessed answer.
3. Align reported entities to reference entities, retaining unsupported and ambiguous predictions. Separate extraction assertions from watchlist candidates so several candidates do not multiply one entity or its details.
4. Retain raw values and derive comparison values using a versioned normalization policy. Identify a gold fact by claim, owner, kind and equivalent value, retaining address grouping or time/status where they change meaning. Five notes repeating one fact do not create five gold facts.
5. For each reported detail, check whether an equivalent value of the same kind is supported anywhere in the permitted claim evidence, then whether it belongs to the predicted owner. For each eligible gold detail, check whether the system reported it on the correct owner. Track unresolved cases separately.
6. Produce reproducible counts and fractions by detail kind, claim, coverage, client and quality group, with adjudication reasons. Apply the same procedure to our system.

**Comparison policy to agree before scoring:**

| Detail | Comparison rule and clarification needed |
|---|---|
| TIN | Compare identifier digits with leading zeros preserved; remove only agreed presentation separators. Define treatment of masking, missing digits and contradictions. |
| Phone | Preserve country code and extension semantics. Agree punctuation equivalence; do not infer countries or discard extensions to manufacture equality. |
| ZIP | Preserve leading zeros. Decide whether five-digit and ZIP+4 values are equivalent for a particular score; otherwise report partial information separately. |
| Street address | Agree abbreviation, unit/suite and punctuation equivalence. Missing units can distinguish entities. Fuzzy similarity is not automatic correctness. |
| City/state | Use a fixed equivalence policy for abbreviations and names; different places are not formatting variants. |
| Complete address | Compare street, unit, city, state and ZIP as one associated location under declared completeness rules. Component scores remain separate. |
| Historical/disputed details | Specify whether the target is any supported historical value, a value valid at the cutoff, or a qualified statement. Do not credit an unqualified output with temporal meaning it never supplied. |

Multiple valid phones or addresses are allowed. A correct value on the wrong owner is a supported-value success but an ownership failure and a missed gold fact for the correct owner. A typo matching no supported value is unsupported under exact comparison, not a separately proven invention. SME error review can distinguish typo, truncation, conflation and unsupported generation; the automated score cannot infer their causes.

Agree how GOKO encodes multiple values before splitting them: a comma can separate addresses or be part of one address. Blank predictions are omissions against eligible gold facts, not reported false values. Details with unknown gold ownership need separate evaluability counts, not an automatic attribution failure. If an entire claim packet is missing, exclude it as unavailable input and report that exclusion rather than counting every fact as missed.

**Current app limit:** it compares six components (address, city, state, ZIP, phone and TIN), using case/whitespace normalization and separator removal for phone, TIN and ZIP. It deduplicates gold owner/kind/value combinations but counts supplied predictions separately. It does not implement the complete equivalence, time/status, address-bundle or duplicate-prediction policy above. Unresolved cases and complex addresses need adjudication before treating the dashboard as a final benchmark. Global punctuation removal can hide meaningful structure; retain raw values and approve field-specific rules first.

### Worked detail example

A claim supports four facts: clinic address, clinic phone, clinic TIN and lawyer phone. GOKO reports the correct clinic address, the clinic phone attached to the lawyer, a mistyped clinic TIN and the correct lawyer phone. All alignments are decided and each detail counts once.

- **Detail accuracy (supported-value precision)** = 3 / 4 = 75%.
- **Right-owner rate (conditional attribution accuracy)** = 2 / 3, about 67%.
- **Missed-detail rate (owner-aware detail false-negative rate)** = 2 / 4 = 50%: the clinic phone and TIN were not correctly reported on the clinic.
- **Made-up rate (unsupported-value rate)** = 1 / 4 = 25%. This includes the mistyped TIN; it does not prove fabrication.

## 5. Metric names, meanings and denominators

Keep familiar metric names followed by their data-science interpretation in parentheses. Precision concerns reported positives; recall concerns gold positives. Their denominators are different. [Reference: precision and recall](https://scikit-learn.org/stable/auto_examples/model_selection/plot_precision_recall.html).

| Metric | Numerator / denominator | Interpretation and boundary |
|---|---|---|
| Found rate (claim-level entity recall) | Distinct gold entities found / all eligible gold entities in completed claims | Count once per entity within a claim, regardless of mentions or watchlist candidates. |
| Right rate (entity extraction precision) | Correct distinct entity predictions / all adjudicated distinct entity predictions | Agree duplicate/split/merge policy first. The app currently counts each paired imported entity report; duplicates can inflate its operational score. |
| Detail accuracy (supported-value precision) | Reported details supported under that kind somewhere in the claim / all adjudicated reported details | Ownership is separate. This is neither classification accuracy nor owner-aware fact precision. |
| Missed-detail rate (owner-aware detail false-negative rate; 1 − recall) | Eligible gold facts absent from the correct predicted owner / all eligible gold facts | A missed entity also misses its details. Repeated gold evidence counts once. |
| Made-up rate (unsupported-value rate) | Reported details unsupported under that kind anywhere in the claim / all adjudicated reported details | Not a false-positive rate, which needs a true-negative denominator; not proof of fabrication. It complements Detail accuracy under the current binary value policy. |
| Right-owner rate (conditional attribution accuracy) | Supported reported details attached to the correct entity / all supported reported details with adjudicated ownership | Report ownership cases set aside. The app lacks a separate unresolved-ownership eligibility mechanism. |
| Person/organization tag (conditional entity-type accuracy) | Correct type assignments / aligned entities with comparable resolved types | Report missing/unrecognized predicted tags separately; they are currently excluded. |
| Category accuracy (conditional category classification accuracy) | Correct predicted categories / aligned entity predictions with resolved independent gold categories | Missing predicted categories count as wrong when gold is resolved. Show category confusion counts. |
| Category coverage (gold-label evaluability coverage) | Aligned entity predictions with resolved independent gold categories / all aligned entity predictions | Label availability, not system confidence or accuracy. |
| Watchlist accuracy (flag precision / positive predictive value) | Confirmed-same flagged candidate pairs / flagged pairs decided same or different | Separate Exact search and GenAI. This is not all-candidate accuracy or recall. |
| Can’t-tell rate (review abstention rate) | Candidate pairs judged cannot determine / all reviewed candidate pairs | Report separately for flags, below-threshold candidates and independent audits. |
| Agreement rate (annotation-set Jaccard similarity, current app) | Exact annotation items shared by two SMEs / items either SME recorded | Current comparison uses kind, note positions and detail kind, not identity, ownership or category agreement. It is insufficient as a gold-quality check. |

For headline Right rate, use one-to-one entity alignment and explicitly label duplicates, splits and merged predictions. Do not let repeated correct names improve precision. Retain an operational report-level score separately if repetition matters to workload. This policy needs implementation; it is not the current app’s counting method.

Proposed supplementary measures, separate from existing dashboard scores:

- **Correct-detail rate (owner-aware fact precision):** fully correct owner/kind/value predictions divided by all eligible predicted facts. A correct value on another entity does not count as success.
- **Claim completion success (claim-level exact-set accuracy):** completed claims without in-scope omissions or incorrect assertions divided by eligible completed claims. Report entity-only and entity-plus-detail variants separately.
- **Cross-claim linking right rate (pairwise identity precision):** correctly proposed same-identity links divided by adjudicated proposed same-identity links. **Cross-claim linking found rate (pairwise identity recall):** recovered gold same-identity links divided by all such links in a declared adjudicated universe. Candidate-only review cannot supply the full recall denominator. Also report erroneous merges/splits; large groups generate many pairs.

Report pooled counts (**micro averaging**), the mean of eligible per-claim fractions (**macro averaging**) and subgroup results. Zero denominators mean unavailable, not zero performance. Report pending, unresolved and excluded counts. Uncertainty estimates must respect claim/shared-source clustering; thousands of details from a few claims are not thousands of independent claims. Equal quality-band sampling does not itself produce a prevalence-weighted portfolio estimate.

## 6. Review watchlist candidates below 90

**Yes: add these candidates to SME review.** Preserve GOKO’s actual flag decision separately from candidate existence and numeric similarity. A score of 89 is neither a confirmed mismatch nor an 89% probability of identity. Confirm whether the operational rule is `>= 90`, `> 90`, or includes other conditions.

First freeze the extraction answer key. Then show the identified entity’s evidence alongside the particular watchlist entry, allowing same/different/cannot determine with a reason. Hide similarity and flag status during identity judgment where practical; reveal them for analysis afterward. Preserve method, score and threshold independently. Do not relabel all candidates as flagged to make them eligible for review.

Review all candidates if feasible. Otherwise use a documented probability sample covering high scores, the vicinity of 90, lower scores and missing scores. Record inclusion probabilities for weighted estimates. Enriching the review near 90 does not produce a representative sample by itself. Use bins exposing the boundary: below 75, 75 to below 85, 85 to below 90, 90 to below 95 and 95–100. Report missing/invalid scores separately.

For a declared threshold and a fully adjudicated candidate set, or appropriately weighted sample from it:

| Candidate outcome | Same identity | Different identity |
|---|---|---|
| Flagged under that rule | True positive | False positive |
| Not flagged under that rule | False negative | True negative |

Keep cannot-determine outside these four counts and report its size. Estimates conditional on decidable cases may be biased if ambiguity is systematic. Distinguish actual historical GOKO flags from simulations of alternative thresholds.

- **Watchlist accuracy (flag precision)** = true positives / (true positives + false positives).
- **Missed-match rate (candidate-conditional false-negative rate)** = false negatives / (true positives + false negatives); its complement is candidate-conditional recall.
- **False-alarm rate (candidate-conditional false-positive rate)** = false positives / (false positives + true negatives). This differs from the fraction of flags that are wrong.

Below-90 review closes the gap for **true matches present among supplied but unflagged candidates**. It does not identify entities never extracted, candidates never generated, results discarded before export, category-blocked comparisons or missing/outdated watchlist entries. These require an independent sample of gold entities—including missed and unflagged entities—searched against the complete frozen watchlist under an agreed audit procedure. GOKO must explain the completeness of its candidate export. Report pair-level matching separately from whether an entity received at least one correct watchlist match.

Wrong-category counts do not equal blocked comparisons. If GOKO’s category filter is confirmed, assessing its effect requires watchlist categories and search rules, reconstructing newly eligible comparisons and SME review of those pairs.

**Current app gap:** watchlist controls, completion checks and scores operate on flagged reports only. Its 85–94 bin straddles 90. It associates one review with each imported report rather than independently managing several candidates for one extracted entity. Separate candidate review, sampling, threshold analysis and independent search audit must be added before reporting these measures. GOKO should clarify the similarity method; the app imports scores and does not calculate RapidFuzz or verify its configuration.

## 7. Exact spans: future measures, not a prerequisite for GOKO comparison

GOKO does not capture exact character spans. Today’s common benchmark must compare claim-scoped entities, values, owners, categories and candidate identities. SME quotations verify the answer key but **must not be required for GOKO to receive credit** for a correct fact. Missing spans are not extraction errors in the common benchmark. Note citations are not span predictions.

If per-fact evidence links become available, evaluate source-document attribution separately. GOKO’s entity-level list of note IDs does not demonstrate which note supports a phone or action. Where several notes validly support a fact, any accepted supporting source may be correct; do not require one arbitrarily selected note.

Future span-capable systems can also be evaluated for:

- **Evidence-location right/found rates (span precision/recall):** require exact source versions, IDs, offset units, start/end conventions, labels and gold spans. Define discontinuous/overlapping spans. Report exact-boundary and separately defined overlap scores using one-to-one matching; a whole-note prediction must not earn credit for every gold passage it overlaps.
- **Reference-link right/found rates (coreference link precision/recall):** require gold mention identities and links, including pronouns and unresolved references, and predicted mentions/links. Separate gold-mention evaluation from end-to-end evaluation that also depends on finding mentions.
- **Evidence-support rate (claim–evidence support precision):** require predicted factual assertions, cited passages and SME judgments that the passages support the owner, value, relation and qualifications. Overlapping the right words alone does not establish support.
- **Action/relationship right/found rates (relation or event precision/recall):** require aligned participants, role direction, predicate definitions, scope, negation, attribution and time where material. A denied visit must not match an affirmative visit. Define semantic equivalence before scoring.

These are separate future tracks. No span score enters a combined ranking against GOKO until both systems supply comparable predictions for that task.

## 8. Answer-key quality and implementation priorities

Independently double-review a sample of complete claims and cross-claim identity cases, stratified by coverage and quality. Adjudicate completeness, value, ownership, category and identity disagreements while preserving original decisions. Measure agreement at those semantic levels, not just exact positions. Keep some claims free of AI suggestions and compare error patterns with assisted claims; draft acceptance alone does not establish annotation accuracy.

The app also reports **Draft acceptance rate (review acceptance proportion)** as accepted / (accepted + dismissed), **Correction rate (accepted-draft edit proportion)** as edited accepted drafts / accepted drafts, and **Manual-addition share (manual annotation proportion)** as manual annotations / all annotations on notes with AI drafts. These are workflow diagnostics, not model precision or recall: accepted suggestions can still be wrong and manual work can predate the suggestions. Pending drafts are reported separately.

| Capability | Current status | Next step |
|---|---|---|
| Add sourced evidence across notes in a claim | Implemented, with claim dossier and frozen SME checkpoint | Explicit completeness/ownership review guidance for the benchmark |
| Freeze original notes and GOKO predictions | Not a managed benchmark-release feature; app retains paths/hashes and reloads GOKO inputs | Archive full inputs and output versions under a release manifest |
| Claim entity/detail/category dashboard | Implemented with counting/equivalence limits above; scores may be provisional | Approve semantic units, duplicate/ambiguity policy and normalization, then align calculations |
| Cross-claim entity/item review | Proposed | Candidate groups, explicit identity decisions and combined views preserving provenance |
| Below-threshold watchlist review | Proposed; unflagged candidates are not in the current review workflow | Separate candidates from extraction, retain actual flags, add review and threshold analysis |
| Missed matches outside supplied candidates | Not measured | Independent gold-entity/watchlist audit and candidate-coverage information |
| Span/coreference/qualified-action benchmark | Future | Comparable predictions and task-specific labels, separate from GOKO’s present benchmark |

Before implementation, align with SMEs and GOKO on quality bands, coverage allocation, detail eligibility/equivalence, output identity and candidate semantics, watchlist completeness, cutoff consistency and adjudication policy. These decisions make the benchmark reproducible; storage technology can be chosen afterward.
