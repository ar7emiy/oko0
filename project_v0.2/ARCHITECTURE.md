# Architecture

## The decision

One application, one authoritative evidence/decision store, one general-purpose model adapter, and an early dossier interface. The model proposes meaning; code preserves evidence and governs decisions. The detailed rationale is in [general-first-system-design.md](../archive/project_v0.2/designs/general-first-system-design.md); this file is the authoritative working summary. No historical accuracy metrics determine this architecture.

```text
source versions -> mention/statement proposals -> evidence grounding
    -> local reference proposals -> corpus identity proposals -> decision state
    -> dossier / exact and full-text lookup / later graph export
```

User corrections append decisions. Derived views recompute against the selected revision. A displayed inference is not fresh source evidence for the next inference.

## Records and ownership

- **Source version:** original UTF-8 content, stable document ID, version ID, hash, ingestion time, optional source metadata. Changes retain old versions.
- **Evidence span:** exact version and range with raw quotation. Support several spans for a decision depending on several passages. Code locates occurrences and maps display offsets; a model does not author persistent source addresses.
- **Mention:** stable occurrence ID, evidence, and form (name, pronoun, description, identifier, other). Semantic type is a separate revisable proposal. Nested/overlapping candidates can coexist.
- **Statement:** source wording, predicate wording, argument mentions/values, evidence, optional reporter, polarity, uncertainty, time, and quotation/hypothetical context. Unresolved arguments are permitted. Multiple participants need not be flattened into a binary relation.
- **Entity:** stable referent handle with display label and revisioned membership. It may concern a person, object, group, event, or another discussed thing. Claim membership does not own its identity.
- **Proposal/decision:** kind, arguments, evidence/dependencies, status, method/run, actor, timestamp, and supersession. Coreference, type, identifier ownership, and identity are different decisions.
- **Run:** input versions, effective model/prompt/configuration, outcome, and incomplete/failed ranges. Preserve proposal payloads for inspection.

Start with SQLite and source content in the same store. Use ordinary constraints and a narrow repository API. A shared deployment may later change the database without changing these concepts.

## Decision gates and defaults

| Gate | Allowed decision | Initial behavior |
|---|---|---|
| Source | Preserve/decode an input | Exact bytes and explicit UTF-8 decoding; decoding failures stay visible |
| Evidence | Locate a quoted occurrence | Exact text plus context anchors; ambiguity remains unresolved |
| Interpretation | Propose mentions, statements, qualifiers | One structured-output model; code checks structure, not semantic truth |
| Local reference | Select a referent within context | Machine selection is provisional and evidence-backed; retain alternatives |
| Corpus identity | Compare referents across documents | Retrieve candidates; no automatic identity acceptance initially |
| Presentation | Populate the selected dossier view | Mark provisional attribution; possible external matches remain separate |

Statuses: proposed, provisional, accepted, rejected, superseded. Unresolved means no selected interpretation. Accepted records name the actor or, later, an enabled automatic rule. Acceptance is revisable, not proof of infallibility.

## Resolution layer

Within text, the model proposes antecedents for names, descriptions, and pronouns using source context. Store the occurrence even when no antecedent is found. Cross-document lookup proposes candidates from names, aliases, values, and full-text context. A model may compare supporting passages, but a matching name/value is not an acceptance rule.

Every selected membership has support and status. Identity groups respect explicit rejections and group consistency; they are not arbitrary connected components. User acceptance can consolidate dossier identity without deleting local evidence. Splitting or reassigning a mention changes the view and preserves its prior decision history.

When a supporting decision is superseded, dependent decisions become pending/stale until reconsidered. Renderers never silently strengthen a provisional statement into an accepted fact.

## Dossier and graph

The baseline dossier shows identity/scope, exhaustive paginated mentions and statements, sourced connections, alternatives, and decision history. Every displayed item links to evidence and, where relevant, the attribution/identity decision. Keep reported and alleged content distinguishable. Dates remain unknown when absent.

Live dossiers may be cached; exports pin source and decision revisions. Graph export later contains entity/mention/statement nodes, typed edges, and evidence references. It preserves status, polarity, and time. Graph traversal supports connection queries, not identity acceptance. Natural-language synthesis is a later layer over retrieved evidence.

## Processing and extension

Use full-document context when feasible; otherwise stable windows with original coordinates and explicit cross-window reconciliation. An execution window is not an identity boundary. Exact re-import, duplicate extraction proposal, repeated statement, and identity consolidation are separate operations.

Domain adapters can add identifiers, vocabulary, context metadata, and explicit assignment policies. They cannot exclude unknown source content from storage. No adapter is mandatory initially.

## Delivery sequence

1. **A: evidence and first dossier.** Import, ground, display, version, and inspect source.
2. **B: local reference decisions.** Pronouns/descriptions, alternatives, corrections, and dependency history.
3. **C: corpus identity.** Candidate comparison, acceptance/rejection, stable consolidation/split views.
4. **D: targeted improvement.** One detector/retrieval/policy change at a time through a decision card.
5. **E: graph retrieval and synthesis.** Evidence-preserving exports and explicit answer support.

A-C are the baseline; the dossier appears in A. Gate walkthroughs verify behavior and reversibility. The independently built dataset tests later outcomes; it does not import predecessor metrics into architectural reasoning.
