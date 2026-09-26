# General-first assessment of the existing builds

This assessment supersedes `assessment.md` as the design recommendation. It excludes accuracy metrics, benchmark results, model scores, and historical performance claims from its reasoning. Its basis is the structure of the inspected code and the logical consequences of its contracts. No notes corpus was read for this assessment.

Read this document first, then [the replacement system design](general-first-system-design.md).

## The judgment

**Neither build should be the architectural foundation for a general unstructured-text system.** Useful components can be reused, but their surrounding assumptions should not be inherited.

v0.0 has too many downstream representations making their own interpretations. v0.1 simplifies that arrangement, but elevates claim-specific conventions into universal rules. Both need a clearer boundary between what the source contains, what the system proposes, and what a user has accepted.

The replacement should be a small evidence system with a general-purpose interpretation layer and an early dossier interface. Domain tuning should change interpretation policies without changing the evidence model.

“General” means that the architecture accepts different document structures, subjects, languages, entity kinds, and relationships without redefining identity or provenance. It does not mean that one extractor can fully understand every possible text. Unsupported or ambiguous content must remain available without a forced interpretation.

## Where v0.0 overengineers the problem

### Multiple representations act like independent authorities

The system carries mentions, assertions, linkage edges, entity membership, attribute profiles, dossier JSON, vectors, and a graph. Multiple representations can be useful, but they should be projections of one decision state. Here, downstream builders also introduce meaning.

In [build_graph.py](../../project/src/build_graph.py), the role-edge construction derives treatment/representation relationships from claim membership and entity class. In [profiles.py](../../project/src/profiles.py), role selection and attribute survivorship create another interpretation. In [agent.py](../../project/src/agent.py), retrieved material becomes synthesized answers.

This makes a simple user question—“Why does this dossier say that?”—require tracing several different rule systems. A source citation alone cannot explain all those transformations.

**Design correction:** only the interpretation/decision layer may introduce a semantic conclusion. Dossiers, graphs, and exports render those conclusions with their support and status. Presentation code must not silently decide ownership, role, identity, or a relationship.

### Retrieval infrastructure arrives before its information contract

Separate mention and chunk vectors, probabilistic linkage, graph persistence, and agent synthesis each introduce update and synchronization rules. They are possible later optimizations, not prerequisites for finding a source occurrence or opening a dossier.

The complexity is especially visible in [ingest.py](../../project/src/ingest.py), which coordinates these stores, and [incremental.py](../../project/src/incremental.py), which reconstructs membership. Incremental processing is necessary eventually; several independently refreshed views are not necessary initially.

**Design correction:** one authoritative store, direct structured lookup, and full-text search first. Add a derived index only to support a named interaction that the current system cannot serve adequately. Its deletion and rebuild must not lose meaning or review history.

### Elaborate labels substitute for explicit semantics

“Bitemporal,” “validated,” “grounded,” and “linked” sound precise, but each hides different questions. Is the value well formed? Who owns it? Was a statement denied? Did the source say it, or does the system infer it? Is a citation address valid, or does the cited passage support the sentence?

For example, [profiles.py](../../project/src/profiles.py) groups equal values and handles negation/retraction without a complete time-and-statement supersession model. [agent.py](../../project/src/agent.py) validates citation locations without establishing sentence-level support.

**Design correction:** use modest, literal concepts first: observed span, proposed interpretation, reported statement, rejected proposal, superseded decision, and source date when present. Add sophisticated temporal or inference semantics only when a user-facing operation requires them.

## Where v0.1 simplifies the wrong things

### A claim is a context boundary, not an identity boundary

[contracts.py](../../project_v0.1/src/contracts.py) makes entities claim-scoped and requires claim IDs on documents. [ARCHITECTURE.md](../../project_v0.1/ARCHITECTURE.md) treats within-claim names as suitable local merge keys.

A general text corpus may contain emails, meeting minutes, scientific papers, transcripts, fiction, or maintenance logs. It may have no claim-like grouping. A single document may describe several cases; several documents may discuss the same entity. Even within one conversation, two participants can share a name.

**Design correction:** documents may belong to optional collections, conversations, cases, or other contexts. Those relationships help interpretation and retrieval. They do not define identity. A claim is a domain-specific context supplied through metadata.

### The type system is narrower than the intended task

The name-based person/organization/unknown scheme cannot naturally represent a machine, location, software component, animal, fictional character, group, or referenced event. Restricting “it” to organizations in [coref.py](../../project_v0.1/src/coref.py) follows from this narrow foundation.

[entity_type.py](../../project_v0.1/src/entity_type.py) then adds custom vocabulary learning to maintain that restriction. Deterministically assigning a label does not make the label intrinsic to the text. A name can refer to different kinds of things in different contexts.

**Design correction:** keep occurrence form separate from semantic type. Name, pronoun, description, identifier, and other expression are mention forms. Person, organization, vehicle, and so forth are revisable type hypotheses. Unrecognized types must not exclude a mention from storage or candidate retrieval.

### Identifier policy is treated as universal meaning

[config/config.py](../../project_v0.1/config/config.py) names identifier kinds that should drive linking. This bundles together recognizing a value, validating its form, understanding its namespace, and attributing it to an entity.

In general text, a number may identify a shipment, specimen, machine, case, person, or account. Two people can discuss the same account without being the same person. Even a perfectly recognized value does not decide which relationship applies.

**Design correction:** identifiers are sourced values with a namespace and proposed relation to a referent. Optional domain adapters may know specific identifier formats and assignment rules. The core does not assume that shared values imply identity.

### “Links, not merges” leaves the crucial decision unspecified

Keeping links is useful for reversibility. But if every reachable identity link contributes facts to one dossier, traversal performs the same logical consolidation as a merge. Rejecting one link does not help if another path silently reconnects the same entities.

**Design correction:** define exactly what dossier membership means. An accepted identity view and a possible-connection neighborhood are separate query results. Never use arbitrary graph reachability to decide the former.

### The model is prevented from proposing judgments it is needed to make

The project correctly reserves IDs and source positions for code. But the broader prohibition against model-produced closed-vocabulary labels conflates semantic judgment with structural validation.

A model may propose that an expression is a pronoun, that a sentence is negated, or that an entity is a location. Code can validate the output schema and preserve the proposal without pretending to prove it true. Conversely, code cannot infer a referent's true type merely by making the classification deterministic.

**Design correction:** models propose semantic interpretations; code controls identifiers, source anchoring, allowed structural forms, persistence, and decision permissions. Keep uncertain proposals visible. Neither mechanism is a universal authority on meaning.

## Shared omissions that matter more than additional features

| Missing or unclear contract | Why a general system needs it |
|---|---|
| Immutable source versions | Updated notes, edited messages, and document revisions must not move old citations. |
| Unresolved mentions | “She,” “the device,” and “the committee” must survive even without a known referent. |
| Unresolved statement arguments | A source statement remains useful when the subject's identity is unknown. |
| Speaker and reporting context | A quotation, allegation, hypothetical, or fictional statement is not an unqualified real-world fact. |
| Stable entity handles with membership revisions | Adding an occurrence should not change an investigator's dossier address. |
| Explicit proposal/decision history | Reinterpretation must not erase what was previously reviewed. |
| Distinct mention and source duplication | Repeated text may be one copied statement, while each physical occurrence still exists. |
| Clear stage outcomes | No detected entity, unprocessed text, failed interpretation, and unresolved identity are different states. |

These are justified by ordinary inputs and user actions, not by benchmark results. They are also not a demand to build every advanced feature immediately. The storage model must preserve the information; richer interpretation can arrive later.

## The dossier stays; GraphRAG changes position

The dossier is the main product surface, not a late-stage reporting extra. It should show mentions, statements, connections, source context, and uncertainty. It gives you a direct way to understand and correct each decision.

A dossier may be provisional. That allows immediate use without requiring manual approval of every extraction. It may also have a saved, versioned snapshot. “Derived from evidence” does not mean “forbidden to store.”

GraphRAG should be a projection and retrieval adapter over the same records. It should not create relationships from co-occurrence or decide identity through traversal. A general graph-shaped export can be added before choosing a graph database or a specialized retrieval framework.

## What changes in the design method

The previous assessment still organized much of the recommendation around the existing system's failures. That can produce another accumulation of defensive rules. The next build should instead begin with the smallest complete user journey:

**Import text → inspect mentions → open a provisional dossier → inspect why a statement belongs there → correct that decision → see the dossier update without losing history.**

For each added capability, write a short decision card: the user need, the new decision permitted, the evidence retained, the unresolved outcome, and how to undo or disable it. Change one gate at a time. Do not use accuracy metrics as the reason to select an architecture or advance a stage in this design.

The recommended replacement follows in [General-first system design](general-first-system-design.md).
