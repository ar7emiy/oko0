# First-principles assessment of v0.0 and v0.1

**Superseded as a design recommendation:** see [the general-first assessment](general-first-assessment.md) and [replacement system design](general-first-system-design.md). Those documents exclude accuracy metrics from architectural reasoning and prioritize a domain-independent system with explicit decision gates. This earlier assessment is retained as historical review material.

Date: 2026-09-07. Scope: architecture, implementation, requirements, and small executable counterexamples. Decision: **retain the dossier; rebuild the evidence and decision contracts before adding more retrieval machinery.**

## Verdict

**v0.0 develops downstream sophistication before establishing trustworthy upstream semantics.** It has useful extraction, storage, lookup, and dossier components, but its graph can assert relationships that were never extracted, its entity IDs change when membership changes, and its temporal dossier logic does not implement the history its documentation promises. More ranking, embedding, and graph features cannot repair those foundations.

**v0.1 is a better direction, but it is an incomplete design with some overcorrections.** Separating roles from types, retaining identifier observations, allowing uncertainty, and protecting reviewer decisions are good choices. However, claim-local identity is not intrinsically safe; a checksum is not ownership evidence; typing from names alone is not a correctness principle; and traversing uncertain identity links can reproduce the same contamination as connected-component merging. Its schema also omits a persistent coreference model despite coreference being central to the requirement.

**Both significantly deviate from the earlier suggested build:** neither currently delivers the complete chain of immutable source version → occurrence-level mention → supported and revisable resolution → sourced assertion → reproducible dossier. v0.1 gets closer in intent, but has not demonstrated that chain in execution.

The dossier is not unnecessary scope. It is the most useful first product surface because it forces the system to answer: “What do we know, which person or thing does this concern, where was it said, and what remains uncertain?” GraphRAG is a subsequent retrieval capability over that foundation, not a reason to manufacture a graph before the evidence is ready.

## Scope and evidence limits

- I interpret `project/` as v0.0: v0.1 explicitly identifies it as the predecessor. There is no separately named `project_v0.0/` directory in the workspace inventory.
- Your latest instruction authorizes review of both builds, superseding the earlier restriction on inspecting versions. I read source, configuration, tests, and design/status documents. I did **not** open the notes corpus, ground-truth manifests, existing databases, or credentials.
- This is an independent source-level assessment. Historical design documents are evidence of intent and prior reported results, not independent verification. In particular, the reported 46% mixed-entity mention rate and roughly 43% coreference accuracy were **not remeasured here**.
- v0.1's [status file](../../project_v0.1/STATE.md) says “Scaffolding complete. No pipeline runs yet.” The inspected tree has extraction components, contracts, and typing tests, but no repository, local resolver, cross-claim linker, or dossier implementation. Findings about those proposed stages are explicitly design findings.
- [Reproduction script](reproduce_findings.py) and [captured results](probe_results.json) exercise selected original function/class definitions with standard-library dependencies and invented snippets. No model calls or project pipeline runs were performed. These prove specific counterexamples, not their prevalence in client data. The venv executable was inaccessible; the probes ran successfully with the bundled Python runtime.
- [Source hashes](source_hashes.json) fingerprint 22 referenced source/design files so the assessment can be tied to the inspected state. All 11 saved probe result groups were checked, and the report's local references were validated.

## The standard against which these builds should be judged

An occurrence is evidence; an entity is an identity hypothesis; an assertion is something a source says; a dossier is a presentation of those records under an explicit identity decision state. These must remain distinct.

The necessary invariants are:

1. Every source citation resolves to immutable original content at a named version and exact range.
2. Multiple occurrences remain individually addressable, including ambiguous and unresolved pronouns or descriptors.
3. Detection, type inference, identifier validation, identifier ownership, coreference, and identity resolution record separate conclusions.
4. No automatic identity or relationship decision becomes stronger simply because it is copied into another representation.
5. Decisions can be superseded, merges split, and earlier dossiers reproduced without destroying source observations or human review history.
6. A dossier distinguishes directly observed statements, reported/alleged statements, derived associations, identity alternatives, and missing coverage.
7. Evaluation measures omissions and contamination separately at mention, identity, assertion, retrieval, and dossier levels.

This does not demand a microservice architecture, an enterprise graph database, or a generic event-sourcing framework. It demands a small set of honest records and disciplined writes.

## Material findings

### F01 — Critical: graph structure is presented as semantic evidence in v0.0

**Implemented.** [Graph builder](../../project/src/build_graph.py), lines 157–176, selects the first claimant on a claim, then creates `REPRESENTED_BY`, `TREATED_BY`, `REPAIRED_BY`, and `ADJUSTED_BY` edges from other entities' role classes. It assigns `confidence=0.9` and cites the other entity's mention span. No extracted assertion is required. Lines 122–127 also classify only `repair_shop` as an organization, leaving other organizational roles represented as parties.

**Why this is wrong from first principles:** co-presence in a claim and a role label do not establish who treated or represented whom. A note can mention an opposing attorney or a previous provider. A perfectly located name does not substantiate the generated relationship. The graph becomes a second inference engine disguised as storage.

The current builder does not read the `assertions` table to construct these semantic relations. Although relation extraction exists separately, its existence does not make this path evidence-derived. The predecessor README already acknowledges the graph-edge limitation; it remains significant even when documented.

**v0.2:** derive semantic edges only from assertion records with grounded arguments and evidence. Keep co-occurrence as a distinctly labeled derived association. Do not infer role relationships from claim membership. Preserve structural metadata edges with their metadata provenance; they need not pretend to be quotations from notes.

### F02 — Critical: source immutability and historical identity are weaker than advertised

**Implemented in v0.0; incomplete contract in v0.1.** The v0.0 [schema](../../project/src/contracts.py), lines 81–95, describes immutability but has no document-version or content-hash field. [Hashing](../../project/src/hashing.py) is a useful sealed-fixture integrity guard, but cannot itself retain successive client note revisions. [Delivery](../../project/src/ingest.py), lines 53–71, copies to the incoming filename, allowing replacement of that file. Several readers retrieve current raw files when building evidence snippets.

[Extraction](../../project/src/pipeline_v2.py), lines 540–571, deletes previous extraction rows. [Batch resolution](../../project/src/entity_resolution.py), lines 1200–1202, deletes identity, version, attribute, and dossier tables. [Incremental materialization](../../project/src/incremental.py), lines 295–327, rewrites current entity membership. These may be acceptable operations on disposable projections, but the present history cannot be justified by comments saying records are append-only.

v0.1 adds `text_sha`, which is good, but [its document/span schema](../../project_v0.1/src/contracts.py) has one row per `doc_id`, no source-version identity or original-content reference, and spans reference only `doc_id`. It does not yet specify how a corrected note preserves old evidence.

**v0.2:** immutable source versions and stable mention IDs; a content blob or immutable source reference; explicit extraction runs and supersession. A rebuilt cache may be deleted. Original evidence and decisions must remain available. Use character positions only under an explicit convention, with mapping to original UTF-8 bytes and browser offsets. Byte offsets themselves are not magical; reproducible source addressing is the requirement.

### F03 — Critical: “locate the quote” is good but does not yet guarantee exact occurrence grounding

**Executed counterexamples in the carried v0.1 code.** [Locator/parser](../../project_v0.1/src/ner_ensemble.py), lines 262–357, accepts case/whitespace variants, then sets the end position to `pos + len(model_surface)` and stores the model surface.

The probe `Jane\n  Smith called.` with model quote `Jane Smith` produces stored text `Jane Smith` over actual source text `Jane\n  Smi`. Thus the advertised verbatim invariant does not hold for this case. The parser also maps two `Jane` rows without useful offset hints to the first occurrence twice, losing occurrence identity unless another extraction lane recovers it.

This contradicts the v0.1 hard rule that non-verbatim quotes are rejected, and its rule against asking models for offsets: the carried parser/schema still supports model `start` hints. A previously reported 100% grounding result on a fixed slice is not proof of the general invariant.

**v0.2:** locate exact occurrence candidates using the quoted text plus contextual anchors; record ambiguity when occurrence choice is unresolved. If normalized matching is supported, map both boundaries back to raw text and persist the actual raw slice. Keep normalized text separately. Enforce the slice equality check at persistence for every extraction lane. Record a rejected proposal diagnostically without promoting it into a grounded mention.

### F04 — Critical: coreference is treated as a helper rather than a complete evidence capability

**Implemented limitation in v0.0 and carried v0.1 code; schema omission in v0.1.** v0.0 [pipeline](../../project/src/pipeline_v2.py), lines 516–532, computes coreference after the attribute/allegation pass and persists links. The inspected dossier, graph builder, and resolution paths do not consume those links to carry pronoun-attributed assertions into the entity dossier. A stored link count therefore does not demonstrate the requested end-to-end capability. `resolved_view` and its offset projection exist without production callers in the inspected source search.

The v0.1 [rule resolver](../../project_v0.1/src/coref.py), lines 189–240, chooses the nearest preceding compatible mention with fixed confidence `0.75` for pronouns and `0.7` for descriptors. The probe “Jane spoke to Mary. She confirmed the address.” commits to Mary without representing the alternative. “She called.” with no antecedent emits no record. A vehicle antecedent for “It” is excluded by the person/organization type restriction.

Crucially, the v0.1 [DDL](../../project_v0.1/src/contracts.py) contains neither a dedicated coreference relation nor a general mention-kind/candidate-resolution structure that replaces it. The carried module returns `CorefLink`, but there is no implemented persistence contract for that output. Restricting tables to `name_mention` and `id_mention` leaves unresolved linguistic references without a clear home.

**v0.2:** pronouns and descriptors are mentions, even when they are not independent entities. Detect and store them before resolution; retain zero, one, or multiple antecedent candidates. Include speaker/quotation boundaries, scope, and cross-note context where supported. Attach assertions through recorded mention-resolution decisions. Do not silently substitute the selected name into downstream evidence and erase the uncertainty. Coreference must be tested through dossier retrieval, not only as an isolated link prediction.

### F05 — High: claim-local resolution reduces search scope, not ambiguity itself

**v0.1 design.** [Architecture](../../project_v0.1/ARCHITECTURE.md) and [configuration](../../project_v0.1/config/config.py) permit exact normalized names and unambiguous token subsets to merge within claims, based on collision measurements in the synthetic corpus. The architecture says names are unambiguous within a claim.

A claim containing two people called Alex Lee is a valid counterexample. A short reference may also be unique only because another party was missed by extraction. Absence from the detected candidate set is not proof of uniqueness in the source world. The hard rule “A name never decides identity” is inconsistent with exact-name-only local merging.

Claim scoping is still useful for contextual role resolution, candidate generation, and limiting the immediate consequences of a mistake. It should be a scope attribute, not a claim that local identity is settled.

**v0.2:** use provisional local groupings with reviewable support, not irreversible certainty. Retain membership decisions and contradictions. Permit later splitting within a claim. Do not require a claim ID as the ontological owner of every entity; a note's filing location and the claims discussed in its prose are separate concepts.

### F06 — Critical: identifier validity is confused with identity and ownership

**v0.1 design/configuration; predecessor signal misuse.** [Configuration](../../project_v0.1/config/config.py) lists `npi`, `vin`, `email`, `ssn`, and `tin` as strong identifiers for automatic linking. But [gazetteer validation](../../project_v0.1/src/gazetteers.py) marks email as format-only and SSN/TIN as `none`. The contracts say only checksum kinds are safe, while architecture/configuration describe a broader policy. No linker exists to settle this inconsistency.

Even a correctly validated value does not establish its relationship to each mentioned party. A VIN can connect an owner, driver, and repair shop through one vehicle. That is association, not identity. An email can be a shared contact. A copied identifier can preserve one original binding error across many notes.

The predecessor compounds this in [profiles._tier](../../project/src/profiles.py), lines 40–51: most normalized identifier attributes become `validated_id` without a validation result being consulted. The probe confirms this for a normalized phone value. Extraction normalization is being promoted into source reliability.

**v0.2:** separately record identifier kind, value, namespace, validation method/result, subject-binding evidence, relationship kind, and time where known. Link identity only with compatible referent types and sufficiently supported ownership/assignment. Preserve identifiers as searchable observations when no owner is known. This is foundational semantics, not an optional registry-enrichment feature.

### F07 — High: global identity propagation is not solved merely by calling merges “links”

**v0.0 implemented; v0.1 design risk.** [cluster_at](../../project/src/entity_resolution.py), lines 1120–1143, computes connected components above a probability threshold. Suppressing an A–C pair does not keep A and C separate when accepted A–B and B–C edges connect them. Pairwise filtering is not cluster-wide consistency.

v0.1 explicitly rejects global transitive merging, but describes cross-claim dossiers as traversal of identity links at a chosen confidence. If traversal collects all reachable nodes as one person's facts, the same false bridge contaminates the dossier. The difference is physical representation, not inference behavior. A rejected A–C link likewise needs a policy when a path still connects them.

**v0.2:** define identity-view membership independently from generic graph reachability. Accepted identity groupings need group-level consistency checks and explicit exclusions. Show candidate links as possible matches, with paths and evidence, rather than folding them into confirmed identity. Keep physical observations separate regardless of whether the accepted identity view is global or claim-local.

### F08 — High: deterministic name typing replaces one flawed signal with another

**Executed v0.1 counterexamples.** Separating type from role is correct. The conclusion that type must come from the string alone is not. The same surface can name a person or a business; context supplies information about that distinction, not just roles.

[entity_type.py](../../project_v0.1/src/entity_type.py) derives organization head nouns from recurring trailing tokens that never lead names. This is a corpus-dependent heuristic, not a linguistic law. In the probe, adding `Clinic Partners` changes `Alder Clinic` from organization to person without changing the latter's text. `Dr. Jane Smith LLC` is classified as person because the title rule precedes the legal-form rule.

This subsystem is overengineered relative to its decision value: custom lexicon learning and elaborate rules create a new dependency on corpus composition before the actual identity pipeline exists. Its inputs must themselves be correctly extracted. Its repeated execution is deterministic only for a fixed lexicon, not simply a fixed name.

**v0.2:** maintain type hypotheses from contextual evidence, with provenance and versioned inference inputs. Use name-shape rules as inexpensive hints. Do not let an uncertain type veto candidates. Keep role assertions separate. Resolve type disagreement at the entity view, rather than forcing every occurrence of a string to share a label.

### F09 — High: extraction ensemble complexity is undermined by destructive reconciliation

**Implemented in carried code; nested-span probe executed.** [union_spans](../../project_v0.1/src/ner_ensemble.py), lines 428–461, collapses any overlapping candidates to a longest span, unions their extractor provenance, and takes the maximum score. In the probe, a person candidate `Jane Smith` inside `Jane Smith Foundation` disappears; the surviving organization inherits both extractors.

This does not prove the nested person interpretation is correct. It proves the reconciliation policy discards the alternative before semantics can decide. It also makes the provenance look like agreement about a span/type when the sources proposed different things. Taking the highest score across unrelated scoring schemes is not calibrated confidence.

The project pays for gazetteers, token NER, LLM extraction, overlap, and sweep, but a final heuristic can discard their marginal recall. Adding more models first is poor sequencing.

**v0.2:** deduplicate identical occurrences/proposals; preserve overlapping hypotheses with their separate labels and scores. Resolve incompatible interpretations explicitly. Measure the incremental recoveries, errors, latency, and cost of each lane before retaining it. Chunking is an execution detail; overlap must not create independent corroboration.

### F10 — High: the dossier is valuable, but current aggregation can distort what was said

**Implemented and partially reproduced in v0.0.** [profiles.py](../../project/src/profiles.py), lines 177–225, groups attributes by normalized value, treats any negated/retracted occurrence as retracting the value regardless of chronology, stores `known_to="retracted"`, and writes `known_from=None`. It does not implement bitemporal reconstruction. A probe with an older denial followed by a later affirmative statement retains the negated/retracted result.

The same code chooses a representative by tier, with no same-tier recency comparison despite the module documentation's promise. It flags conflicting top-tier values without establishing that their validity periods overlap or that the attribute is single-valued. Two phones or successive addresses are not inherently contradictory.

Other dossier issues:

- `_roles_per_claim`, lines 241–250, derives a role from mention class and retains the first role for a claim. That loses multiple roles and repeats the role/type error.
- The identity/link index excludes negated and retracted assertions but can include `reported` and `alleged` values without carrying those distinctions into the identity summary. `_build_attributes` separates only the `allegation` predicate, not all allegedly true assertions.
- The email-domain branch in `run` follows an `if p in IDENTIFIER_ATTRS` branch that already includes `has_email`, so domain-link feature code is unreachable through that loop. The proposed shared-domain association also needs discrimination between a business domain and a common email service before it is a useful investigation lead.

**v0.2:** build the dossier from assertions and their status/time/support, preserving disagreements instead of manufacturing a winning fact. Implement explicit statement supersession; denial of a statement is not automatically retraction of every equal value. Keep chronology fields honest when unknown. Start with an ordered evidence timeline; add richer temporal queries only when their semantics are implemented and tested.

### F11 — High: stable identity and reproducible dossiers are sacrificed to content-derived IDs

**Implemented in v0.0.** [cluster_at](../../project/src/entity_resolution.py), lines 1138–1142, hashes the full sorted membership list into the entity ID. Adding one mention changes the ID. [Ingest](../../project/src/ingest.py), lines 178–185, acknowledges this and rebuilds all dossiers. [Repository](../../project/src/repository.py), lines 174–178, stores one updatable dossier JSON per entity.

This turns routine arrivals into identity churn for bookmarks, review records, cached graph references, and downstream clients. Rebuilding all dossiers is then a workaround for the ID design. It is not a reason to ban materialization: v0.1's “dossiers are views, never stored” overcorrects. A stored, versioned export is useful for an investigator who needs to reproduce what they saw.

**v0.2:** separate stable entity handles from membership revisions and dossier snapshots. Record merge/split lineage and explicit replacement choices. Live dossiers are derived views; cache them by source/decision revision. Saved dossiers pin those revisions. Neither cache nor export becomes the authority for facts.

### F12 — High: GraphRAG citation checks establish location, not support

**Implemented in v0.0.** [Agent](../../project/src/agent.py), lines 246–324, verifies that citations parse, reference an existing document, and lie within retrieved evidence. That is useful but does not verify that each answer sentence follows from that evidence. `_synthesize` returns the answer even if citations are rejected; if citations are missing, it substitutes retrieved chunk citations. The `grounded` flag therefore overstates what has been checked.

The prompt includes only `c['text'][:400]` while citation authorization covers the full chunk range. A location can pass verification even though the text at that location was not shown to the model. Graph triples are formatted as facts without their uncertainty or polarity in that prompt.

**v0.2:** return answer items tied to specific assertion/evidence IDs and preserve epistemic status. Validate citations against the actual supplied text. Separate “citation address valid” from “statement supported.” Never invent citations to fill absent model output. Use deterministic dossier sections for basic facts; introduce free synthesis with explicit limits and evaluation.

### F13 — Medium/high: too many representations before a reliable update contract

**Implemented sequencing problem in v0.0.** There is a relational store, mention vectors, chunk vectors, probabilistic pair edges, entity snapshots/members, attribute materialization, dossier JSON, and a separately persisted graph. [Ingest](../../project/src/ingest.py), lines 162–214, coordinates them stage by stage. The code documents a previous missing update that left new notes absent from retrieval. It also offers `rebuild_graph=False`, exposing stale graph state.

These representations are not inherently unnecessary. Their combined maintenance burden is premature when identity and assertions remain unreliable. The [graph store's `upsert_edges`](../../project/src/graph_store.py), lines 175–184, appends rather than deduplicating when called repeatedly on the same store instance; the API name does not promise the behavior callers likely expect.

Embedding candidate generation adds another example: [blocking.py](../../project/src/blocking.py) forms connected components of neighbor pairs and turns them into blocking buckets. That expands local neighbor proposals into all pairs within a component, requiring additional bucket controls. [Configuration](../../project/config/00_config.py), line 204, still enables class-filtered embedding blocking even though the class signal was judged too unreliable to veto identity later. Its effect is specifically a recall restriction on that lane; other blocking lanes may still recover a pair.

**v0.2:** use one authoritative evidence/decision store and one thin repository. Start with exact/full-text lookup and direct joins. Introduce one derived index at a time, with a recorded source revision, repeat-safe update, and explicit freshness status. Use bounded neighbor candidate pairs unless measurements justify bucket closure. Full rebuilds can be acceptable at prototype scale if labeled and snapshot-consistent; a distributed update architecture is not required now.

### F14 — High: evaluation can reward the wrong system again

**Observed test/design issue.** v0.0 tests emphasize aggregate scores, counts, and structural checks. v0.1 improves attention to mixed identities, but its “one number that matters” over-merge rate can be minimized by never merging anything. That would fail the corpus-wide cross-reference requirement.

The v0.1 [typing tests](../../project_v0.1/tests/test_entity_type.py), lines 40–63 and 65–106, learn the lexicon from ground-truth canonical names and test against labels inferred from generator variants. This is not evidence that the runtime reads ground-truth identity, but it is an **oracle-clean input evaluation**, not end-to-end performance on extracted names. Reusing a fixed synthetic slice for repeated rule selection does not establish generalization.

Some historical docs also correctly mark earlier results stale or based on stubs. Those caveats must remain attached to the numbers; no “measured good” component should be exempt from the new source and data contracts.

**v0.2:** preserve a fixed regression slice, add held-out cases, and report mention recall, false merges, false splits, candidate recall, coreference abstention/accuracy, assertion attribution/polarity, and dossier completeness/support separately. Include copied evidence, same-name people within one claim, changed notes, shared contacts, vehicle references, unknown types, and failed extraction stages. Report review *pairs and minutes*, not merely percent of entities needing review. Historical benchmark numbers are not release gates until reproduced under the declared runtime.

### F15 — High: review protection and temporal provenance are promises awaiting enforceable contracts

**v0.1 schema/design gap; DDL probe executed.** `HUMAN_OWNED` declares protected statuses, but no repository implements enforcement. The SQLite DDL accepts identity links with nonexistent endpoints, arbitrary basis/status values, and updates from `accepted` to `auto`, even with foreign keys enabled. This is an absent constraint, not an accusation that a nonexistent pipeline already overwrites reviews.

`identity_link` offers one optional evidence span, whereas a cross-document identity decision typically needs both observations and the binding evidence for each. `local_member` has a basis but no specific supporting evidence reference. Assertions require a resolved `subject_local_id`; there is no first-class pending assertion argument for a detected but unresolved subject. Run lineage, supersession, decision history, and assertion valid/recorded times are also absent.

**v0.2:** build the smallest enforceable decision record now: actor, timestamp, status, method/run, evidence references, and superseded decision. Use ordinary foreign keys/checks and a narrow write API. Allow a reviewer to revise their own decision while retaining history; “never overwrite” should not mean “never correct.” Human intent must survive re-extraction and local entity splitting through stable evidence references.

## What to retain, simplify, defer, and remove

| Capability | Decision | Reason |
|---|---|---|
| Evidence-first dossier and highlighted source viewer | **Retain as the first deliverable** | Makes provenance, identity uncertainty, and missing coverage reviewable. |
| Gazetteers and kind-specific normalization | Retain with shared write-time checks | Cheap observed spans; validation must remain separate from ownership. |
| Source hashes and exact span validation | Strengthen immediately | Needed for the promised traceability; sealed-fixture hashing alone is insufficient. |
| Role/type separation | Retain | A person can play multiple roles; role is not identity type. |
| Unbound identifier observations | Retain and extend to unresolved mentions/assertions | Failure to resolve must not erase evidence. |
| Model transport, caching, explicit failure modes, run logs | Retain selectively | Useful infrastructure, provided cache/run provenance tracks effective inference inputs. |
| Scan ledger | Retain, simplify | Distinguishes “not processed” from “nothing detected”; cannot certify recall or model comprehension. |
| Custom name-only lexicon as decisive typing | Remove as an authority; optional candidate hint | Fragile dependence on corpus vocabulary and extraction quality. |
| Mandatory multi-model ensemble and sweep | Start smaller; add through ablation | More passes are justified only by incremental recovery at acceptable cost. |
| Probabilistic linkage model | Defer automatic decisions; optional ranking | The problem is evidence and calibration, not that probabilistic methods are inherently wrong. |
| Global connected-component identity | Remove as the unconditional identity rule | Pairwise compatibility does not establish group consistency. |
| Claim-local groupings | Retain as provisional context | Useful scope, insufficient proof of sameness. |
| Invented semantic graph edges and fixed truth-like scores | Remove | Citation to a nearby name is not evidence for the relationship. |
| GraphRAG export and retrieval | Stage after evidence/dossier correctness | Valuable for supported network questions; no separate fact authority. |
| Temporal columns without actual history semantics | Replace with honest recorded/valid times and supersession | “Bitemporal” should describe behavior, not column names. |
| Registry enrichment and predictive risk features | Defer | Identity errors would contaminate them; relevance and external provenance need separate validation. |
| Cloud portability frameworks / multiple services | Do not introduce yet | A module boundary and one store suffice for this stage. |

## Dossier requirement: keep it, but define exactly what it promises

The dossier should be the investigator's complete evidence-backed working record for a selected entity, not a top-k retrieval summary and not a flattened “best value” profile.

The first dossier should contain:

1. **Identity:** stable handle, display name, aliases, type hypotheses, and decision revision. Confirmed membership is distinguishable from possible cross-claim matches.
2. **Where it appears:** every included mention, including resolved pronouns/descriptors, grouped by source/claim with exact highlights and pagination. Unresolved candidates remain separately discoverable.
3. **Identifiers and attributes:** sourced observations, binding status, validity checks, effective dates when stated, and disagreements. No automatic conversion of mention count into reliability.
4. **Activity and relationships:** assertion-based records with actor/subject, other arguments, polarity, reporter, dates, and supporting spans. Complex events need an event plus participants, not an invented binary relation.
5. **Timeline:** source statements and later corrections in order; distinguish when an event reportedly happened, when the note was created, and when the system learned of it. Unknown dates stay unknown.
6. **Connections:** same identity, shared contact, shared vehicle, and co-occurrence shown as different relationship kinds. A possible match does not import another person's allegations into confirmed facts.
7. **Coverage and corrections:** processed source revision, failed stages, unresolved references, and actions to reject/reassign a mention, split identity, or supersede an assertion decision.

Every displayed statement needs an evidence path; every derived connection needs a derivation path. Support provenance and identity provenance are separate: the note may clearly describe an action even while the actor's cross-corpus identity remains uncertain.

Store a machine-readable dossier projection and provide a human-readable rendering. Versioned snapshots/exports are legitimate and important for reproducing investigation work. The live view can be cached; its underlying evidence remains authoritative. This is a justified revision to v0.1's “never stored” prescription, and consistent with the earlier first-principles distinction between evidence and presentation.

## GraphRAG requirement: satisfy the capability, question the premature implementation

The inspected docs use graph RAG to mean structured retrieval followed by grounded language-model synthesis. They do not establish a mandatory external consumer's exact file/schema contract. Do not choose a vendor format or introduce community summaries merely because the requirement contains “GraphRAG.” Pin a concrete adapter contract when there is a consumer.

There are three separate needs:

- “Show every note concerning this entity” is exhaustive indexed lookup, with identity decisions and pagination. Top-k vectors cannot make it complete.
- “Which claims connect through this contact or vehicle?” is a structured graph/join query with explicit relationship semantics and path evidence.
- “Explain the relevant evidence” is optional synthesis over those results, retaining uncertainty and citations.

A minimal export can contain `nodes`, `edges`, `evidence`, and a `manifest`. Nodes carry stable IDs and kinds. Edges reference assertion/decision IDs, status, polarity, time, and evidence IDs. Evidence identifies immutable document versions and exact spans. The manifest pins the schema and source/decision revision. Derived associations carry their method/version and input records. This can initially be JSONL generated from the authoritative store; a dedicated graph engine is optional.

Do not use unrestricted reachability as identity equivalence. Do not reduce an allegation to a positive triple. Do not allow a generated summary to become fresh evidence on the next run. Evaluate network-query correctness separately from synthesis quality.

## Recommended v0.2 sequence

### Milestone 1: evidence spine plus a narrow dossier

Create immutable source versions, generic occurrence-level mentions, inference-run records, evidence references, and explicit resolution decisions. Use simple exact identifier/name candidate lookup and one contextual extraction lane initially. Include deterministic identifier extraction. Build the highlighted note → mention → dossier interaction immediately, allowing a provisional entity dossier with limited claims rather than pretending full resolution is complete.

**Gate:** changed source versions preserve old citations; Unicode/CRLF/repeated-name examples highlight exactly; re-running does not erase observations or review decisions; every dossier item has source and identity provenance.

### Milestone 2: uncertain coreference and assertion attribution

Persist pronouns/descriptors independently of their resolution. Resolve within note context and retrieve prior context when needed. Store ambiguous candidates and unresolved assertion arguments. Keep reported speech, negation, and allegations explicit. The first complete acceptance scenario should include a named person, subsequent pronoun, attributed action, and a clickable dossier entry with the resolution evidence.

**Gate:** ambiguity causes a visible unresolved result, not a confident guess or disappearance; both pronoun and antecedent are reachable from the dossier; wrong attribution can be corrected without rewriting source facts.

### Milestone 3: conservative corpus-wide identity

Introduce supported cross-note/cross-claim decisions, stable identity handles, merge/split lineage, and consistent accepted identity views. Candidate generation may use fuzzy/embedding signals without treating them as proof. Measure review workload and retrieval recall alongside false merges. Add learned scoring only after the candidate/decision interface and labeled evaluation are sound.

**Gate:** same-name people can remain separate even within one claim; owner and repairer of one vehicle do not merge; rejected links cannot be bypassed silently by traversal; a correction removes contaminated current dossier content while preserving the prior snapshot.

### Milestone 4: complete dossier, graph export, then optional synthesis

Expose supported relationships, temporal evidence, possible connections, exhaustive mention retrieval, and versioned exports. Generate the graph format from the same records. Add natural-language synthesis after the graph can answer its target queries correctly without it.

**Gate:** graph and dossier agree under the same revision; duplicate/retried ingestion does not inflate associations; counts use the requested unit (mentions, distinct notes, claims, or source families); citations refer only to evidence actually used; unsupported answer statements fail evaluation even when their citations are syntactically valid.

No client-data accuracy percentage or performance promise is justified yet. Choose operating thresholds from the cost of missed connections, false attribution, and available review effort after representative evaluation. Do not replace one flattering headline metric with another.

## Assessment of the earlier first-principles suggestion itself

The earlier recommendation remains the right foundation, with three refinements made concrete by this review:

- Immutable **source versions**, not merely a hash beside a mutable filename, are required for full traceability.
- Reversibility must cover the entire decision-to-dossier path; retaining pair links alone is insufficient.
- The dossier should arrive early as the product's acceptance surface, and may have reproducible stored snapshots. A pure query-time view is not a universal requirement.

The significant deviation is therefore not “v0.0 used a graph” or “v0.1 used rules.” It is that both let convenient intermediate representations stand in for claims that still need evidence: validated value → same person; same claim/name → same entity; nearby mention → pronoun antecedent; role → relationship; valid citation range → supported answer. v0.2 should remove those implicit jumps before expanding the feature set.
