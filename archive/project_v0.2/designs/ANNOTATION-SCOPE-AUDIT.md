# Annotation scope audit

This audit compares the offline Gold workbench with the general-first system design. The workbench is a dataset-production tool. It is not the entity-intelligence product itself. Its job is to create inspectable human reference records for the parts of the product that require evaluation.

## Now represented in the workbench

| System capability | Gold evidence captured | Status |
|---|---|---|
| Exact source traceability | Claim, note, raw selected text, character start/end | Present |
| Entity discovery | A direct named mention creates a local entity handle | Present |
| Repeated names, aliases, pronouns, descriptions | Each selected mention links to the same local entity | Present |
| Entity type | Person, organization, location, other, unknown | Present |
| Stated attributes | Value, field kind, entity, source span | Present |
| Source characterization | Exact wording, entity, source span, optional open label | Present |
| Statement / relationship | Exact predicate source span, primary entity, optional second entity, optional open label | Present, deliberately minimal |
| Ambiguity | Explicit uncertain source span and reason | Present |
| Independent Gold creation | Client output hidden until the claim is sealed | Present |
| Returned watchlist validation | Per-note, post-seal identity decision with source-support assessment and reason | Present |

## The reviewer does not work from a category taxonomy

The current client groupings — medical, legal, claimant, financier, repair shop, and witness — are useful as **client proposals to compare later**. They are not a suitable general Gold taxonomy. They overlap role, organization type, and case function; they do not cover every kind of unstructured text; and a reviewer should never need to choose one merely because a note contains an entity.

The workbench therefore records a **source characterization**: the smallest exact phrase that describes the entity, linked to that entity. `orthopedic surgeon`, `the medical provider`, and `counsel for the claimant` are all valid source characterizations. An optional open label is available only when the SME wants to record an interpretation. There is no required category or subcategory dropdown. A later mapping layer can map these grounded phrases to the client’s six groupings or to a future taxonomy without changing the original evidence.

## Statement capture is a separate, minimal annotation action

The general-first system design requires a **statement layer**. A statement is what a note says happened or was asserted, not merely who or what appeared in it. It must be a separate annotation action because a category, a role, an attribute, and an event are different things.

It is deliberately kept light in the default workflow. Requiring one SME to normalize predicates, semantic roles, polarity, reporting source, and event time while they establish entities, fields, source characterizations, and coreference creates avoidable ambiguity. The reviewer selects the exact action/relationship wording, links a primary entity, and optionally links a clearly supported second entity. An open label and note are optional. Do not ask the reviewer to label every verb.

For `Dr. Ada Monroe called regarding the claim`, the statement record would be:

| Part | Gold value |
|---|---|
| Predicate wording | `called regarding the claim` |
| Primary entity | Dr. Ada Monroe (`E1`) |
| Second entity | Leave blank unless another entity in the selected wording is explicit |
| Source support | exact selected predicate span, plus the participant mention span |
| Qualifiers | reported speaker, negation, uncertainty, quotation, and stated time when the note supplies them |

For `Dr. Ada Monroe is an orthopedic surgeon with Northstar Orthopedics`, the workbench should create two distinct records when each is supported:

1. A source characterization for Dr. Ada Monroe: `orthopedic surgeon`.
2. A sourced affiliation statement between Dr. Ada Monroe and Northstar Orthopedics. It must not be silently treated as a permanent employment fact or as identity evidence.

## Why actions should not be folded into entity annotations

An entity mention answers **who or what is referred to**. A category context answers **how the note characterizes that entity**. An action or relationship answers **what the note says occurred, involving which arguments**. Combining them would lose polarity, source/reporter, time, and participant roles. It would also create unsupported graph edges from mere co-occurrence.

The production system must extract and retain statements/actions because the dossier is expected to show activity and connections. The Gold dataset also needs them to evaluate that capability. The reviewer should not label every verb in prose. The reviewer should label source-supported, entity-relevant statements under a controlled statement template.

## A later detail layer, only if needed

If later evaluation requires it, an advanced statement-detail layer can add:

- one or more exact source spans;
- predicate wording;
- one or more participant entity references and their roles;
- optional value/object argument;
- negated, uncertain, quoted/reported, and hypothetical flags;
- stated event time when present; and
- unresolved or alternative participant treatment when the note does not decide it.

It should export `16_Blind_gold_statements`. It must not automatically create a relationship edge, change entity identity, or overwrite a category/field record.

## Other system-level gaps, intentionally outside this workbench today

- Immutable document versions, raw-byte hashes, and source-version lineage.
- Multiple coreference candidates and accepted/rejected decision history; the workbench currently records a selected link or uncertainty.
- Multiple independent source spans for one statement; the first form captures the predicate span and participant references.
- Corpus-wide identity candidate review, merge/split lineage, and cross-claim decisions.
- Post-seal category reconciliation against each client row.
- Dossier rendering, source coverage, and a graph export derived only from accepted statement and decision records.

These are system requirements, not reasons to overload the current annotation screen. They should be introduced one decision gate at a time.
